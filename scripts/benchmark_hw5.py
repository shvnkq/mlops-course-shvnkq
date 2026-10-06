"""Measure actual CPU training and full-validation cost without a full run."""

import gc
import json
import math
import random
import time
from pathlib import Path

import numpy as np
import psutil
import torch
from peft import LoraConfig, get_peft_model
from transformers import AutoModelForCausalLM

from src.data import LABEL_PAD_ID, batches, load_split

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "benchmark"
OUT.mkdir(exist_ok=True)
MODEL = "Qwen/Qwen3-0.6B"
TARGETS = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]


def log(message):
    print(message, flush=True)


def seed():
    random.seed(42)
    np.random.seed(42)
    torch.manual_seed(42)


def create_model(freeze):
    seed()
    model = AutoModelForCausalLM.from_pretrained(
        MODEL, dtype=torch.float32, local_files_only=True,
    )
    model.config.use_cache = False
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    config = LoraConfig(
        r=8, lora_alpha=16, lora_dropout=0.05, target_modules=TARGETS,
        layers_to_transform=list(range(freeze, model.config.num_hidden_layers)),
        task_type="CAUSAL_LM",
    )
    return get_peft_model(model, config).train()


def train_probe(model, examples, pad_id, micros, accumulation, optimizer=None):
    started = time.perf_counter()
    tokens = 0
    losses = []
    for i, batch in enumerate(batches(examples, 1, pad_id, True, 42), 1):
        loss = model(**batch).loss / accumulation
        loss.backward()
        tokens += int(batch["attention_mask"].sum())
        losses.append(float(loss.detach()) * accumulation)
        if i % accumulation == 0:
            if optimizer is not None:
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
            model.zero_grad(set_to_none=True)
            if accumulation > 1:
                log(f"  optimizer step {i // accumulation}: {time.perf_counter() - started:.1f}s elapsed")
        if i >= micros:
            break
    model.zero_grad(set_to_none=True)
    seconds = time.perf_counter() - started
    return {"seconds": seconds, "tokens": tokens, "tokens_per_sec": tokens / seconds, "losses": losses}


@torch.no_grad()
def eval_probe(model, examples, pad_id):
    model.eval()
    started = time.perf_counter()
    total, count = 0.0, 0
    for i, batch in enumerate(batches(examples, 1, pad_id, False, 0), 1):
        n = int((batch["labels"][:, 1:] != LABEL_PAD_ID).sum())
        loss = model(**batch).loss
        total += float(loss) * n
        count += n
        if i % 25 == 0 or i == len(examples):
            log(f"  val {i}/{len(examples)}: {time.perf_counter() - started:.1f}s elapsed")
    model.train()
    return {"seconds": time.perf_counter() - started, "examples": len(examples), "loss": total / count}


def main():
    torch.set_num_interop_threads(1)
    torch.set_num_threads(4)
    torch.use_deterministic_algorithms(True)
    train = load_split(str(ROOT / "data/tokenized/train.pt"))
    val = load_split(str(ROOT / "data/tokenized/val.pt"))
    examples, pad = train["examples"], train["pad_token_id"]
    tokens = sum(len(x["input_ids"]) for x in examples)
    steps = math.ceil(len(examples) / 8)
    eval_calls = 1 + steps // 10 + int(steps % 10 != 0)
    result = {"train_examples": len(examples), "val_examples": len(val["examples"]),
              "train_tokens": tokens, "optimizer_steps_per_variant": steps,
              "full_evaluations_per_variant": eval_calls, "batch_size": 1,
              "grad_accum": 8, "dtype": "float32", "threads_probe": [], "variants": []}
    log(f"Data: {len(examples)} train, {len(val['examples'])} val, {tokens} tokens")
    log(f"Full run: {steps} optimizer steps + {eval_calls} full val passes per variant")
    log(f"Available RAM: {psutil.virtual_memory().available / 2**30:.2f} GiB")
    model = create_model(0)
    log("Warmup...")
    train_probe(model, examples, pad, 1, 1)
    for threads in (2, 4, 6):
        torch.set_num_threads(threads)
        log(f"Thread probe: {threads} CPU threads, 3 forward/backward passes")
        probe = train_probe(model, examples, pad, 3, 1)
        probe["threads"] = threads
        result["threads_probe"].append(probe)
        log(f"  {probe['seconds']:.2f}s; {probe['tokens_per_sec']:.2f} tokens/s")
        (OUT / "timing.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    chosen = max(result["threads_probe"], key=lambda x: x["tokens_per_sec"])["threads"]
    torch.set_num_threads(chosen)
    result["chosen_threads"] = chosen
    del model
    gc.collect()
    for freeze, name in ((0, "all_layers"), (14, "freeze14")):
        log(f"Variant {name}: {chosen} threads")
        started = time.perf_counter()
        model = create_model(freeze)
        load_sec = time.perf_counter() - started
        optimizer = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=2e-4)
        training = train_probe(model, examples, pad, 24, 8, optimizer)
        log(f"Training speed: {training['tokens_per_sec']:.2f} tokens/s")
        validation = eval_probe(model, val["examples"], pad)
        rss = psutil.Process().memory_info().rss / 2**30
        train_sec = tokens / training["tokens_per_sec"]
        eval_sec = eval_calls * validation["seconds"]
        record = {"variant": name, "trainable_params": sum(p.numel() for p in model.parameters() if p.requires_grad),
                  "load_seconds": load_sec, "training_probe": training, "validation_probe": validation,
                  "rss_gib_after_probe": rss, "estimated_train_seconds": train_sec,
                  "estimated_validation_seconds": eval_sec,
                  "estimated_total_seconds": load_sec + train_sec + eval_sec}
        result["variants"].append(record)
        (OUT / "timing.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        log(f"{name}: estimated {record['estimated_total_seconds'] / 3600:.2f}h incl. full validation; RSS {rss:.2f} GiB")
        del optimizer, model
        gc.collect()
    result["estimated_both_seconds"] = sum(x["estimated_total_seconds"] for x in result["variants"])
    (OUT / "timing.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    log(f"TOTAL estimate: {result['estimated_both_seconds'] / 3600:.2f}h. Details: {OUT / 'timing.json'}")


if __name__ == "__main__":
    main()
