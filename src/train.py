"""LoRA на тензорах ДЗ4: валидация, воспроизводимость и переносимый адаптер."""

import argparse
import hashlib
import json
import math
import os
import time
from pathlib import Path

os.environ.setdefault("PYTORCH_MPS_HIGH_WATERMARK_RATIO", "0.5")
os.environ.setdefault("PYTORCH_MPS_LOW_WATERMARK_RATIO", "0.4")

import torch
from peft import LoraConfig, get_peft_model
from transformers import AutoModelForCausalLM, AutoTokenizer, get_cosine_schedule_with_warmup

from src.config import load_params
from src.data import LABEL_PAD_ID, batches, load_split
from src.runtime import allocated_bytes, memory_metric, resolve_device, resolve_dtype, setup_runtime

TRAIN_CODE = ("src/train.py", "src/data.py", "src/runtime.py", "src/config.py", "pyproject.toml", "uv.lock")
TRAIN_PARAMS = ("model", "data", "lora", "train", "variants")


def inputs_fingerprint(params: dict) -> str:
    h = hashlib.sha256()
    for name in TRAIN_CODE:
        h.update(name.encode())
        h.update(Path(name).read_bytes())
    h.update(json.dumps({k: params.get(k) for k in TRAIN_PARAMS}, sort_keys=True).encode())
    for key in ("train", "val"):
        h.update(Path(params["data"][key]).read_bytes())
    return h.hexdigest()[:12]


def lora_config(params: dict, n_layers: int, freeze_first: int) -> LoraConfig:
    if not 0 <= freeze_first < n_layers:
        raise ValueError(f"freeze_first={freeze_first}, слоёв {n_layers}")
    cfg = params["lora"]
    if cfg.get("modules_to_save") or any("embed" in x or "lm_head" in x for x in cfg["target_modules"]):
        raise ValueError("В адаптер разрешены только низкоранговые матрицы проекций")
    return LoraConfig(
        r=cfg["r"], lora_alpha=cfg["alpha"], lora_dropout=cfg["dropout"],
        target_modules=cfg["target_modules"],
        layers_to_transform=list(range(freeze_first, n_layers)), task_type="CAUSAL_LM",
    )


@torch.no_grad()
def evaluate(model, examples, pad_id, device, batch_size: int, label="val") -> float:
    """Loss взвешен числом обучаемых токенов, включая сдвиг labels."""
    was_training = model.training
    model.eval()
    total, count = 0.0, 0
    started = time.perf_counter()
    for i, batch in enumerate(batches(examples, batch_size, pad_id, False, 0), 1):
        batch = {k: v.to(device) for k, v in batch.items()}
        n = int((batch["labels"][:, 1:] != LABEL_PAD_ID).sum())
        if n:
            loss = float(model(**batch).loss)
            if not math.isfinite(loss):
                raise FloatingPointError(f"{label}: loss={loss}")
            total += loss * n
            count += n
        done = min(i * batch_size, len(examples))
        if i % 25 == 0 or done == len(examples):
            print(f"  [{label}] {done}/{len(examples)} примеров, {time.perf_counter() - started:.0f} с", flush=True)
    model.train(was_training)
    if device.type == "mps":
        torch.mps.empty_cache()
    if not count:
        raise ValueError("В val нет обучаемых токенов")
    return total / count


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def dir_size_mb(path: Path) -> float:
    return round(sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / 1048576, 2)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="all_layers")
    ap.add_argument("--max-steps", type=int, default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--val-limit", type=int, default=None)
    args = ap.parse_args()
    params = load_params()
    setup_runtime(params)
    variants = {v["name"]: v for v in params["variants"]}
    if args.variant not in variants:
        raise SystemExit(f"Неизвестный вариант: {args.variant}")
    variant, tcfg = variants[args.variant], params["train"]
    max_steps = args.max_steps if args.max_steps is not None else tcfg.get("max_steps")
    device, dtype = resolve_device(params["model"]["device"]), resolve_dtype(params["model"]["dtype"])
    train_blob = load_split(params["data"]["train"])
    val_blob = load_split(params["data"]["val"])
    if args.val_limit:
        val_blob["examples"] = val_blob["examples"][:args.val_limit]
    examples, pad_id = train_blob["examples"], train_blob["pad_token_id"]
    tokenizer = AutoTokenizer.from_pretrained(params["model"]["name"])
    tokenizer.padding_side = "left"
    model = AutoModelForCausalLM.from_pretrained(params["model"]["name"], dtype=dtype).to(device)
    n_layers = model.config.num_hidden_layers
    if tcfg.get("gradient_checkpointing"):
        model.config.use_cache = False
        # Non-reentrant checkpointing works with frozen inputs. Forcing gradients
        # on embeddings would also backpropagate through the frozen lower layers.
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model = get_peft_model(model, lora_config(params, n_layers, variant["freeze_first"]))
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    model.train()
    micro_per_epoch = math.ceil(len(examples) / tcfg["batch_size"])
    steps_per_epoch = math.ceil(micro_per_epoch / tcfg["grad_accum"])
    total_steps = steps_per_epoch * tcfg["epochs"]
    if max_steps is not None:
        if max_steps <= 0:
            raise ValueError("max_steps должен быть положительным")
        total_steps = min(total_steps, max_steps)
    optimizer = torch.optim.AdamW(
        [p for p in model.parameters() if p.requires_grad], lr=tcfg["lr"], weight_decay=tcfg["weight_decay"],
    )
    scheduler = get_cosine_schedule_with_warmup(
        optimizer, max(1, int(total_steps * tcfg["warmup_ratio"])), total_steps,
    )
    out_root = Path(args.out) if args.out else Path(params["paths"]["models"])
    progress_path = out_root / f"progress_{args.variant}.json"
    curve_train, curve_val = [], []
    started = time.perf_counter()
    eval_seconds = 0.0
    print(f"[{args.variant}] устройство {device}, dtype {dtype}, CPU threads {torch.get_num_threads()}", flush=True)
    print(f"[{args.variant}] обучаемых {trainable:,} из {total:,} ({trainable / total:.3%}); шагов {total_steps}", flush=True)
    print(f"[{args.variant}] {len(examples)} train / {len(val_blob['examples'])} val; lr={tcfg['lr']}; effective batch={tcfg['batch_size'] * tcfg['grad_accum']}", flush=True)

    def progress(phase, step):
        write_json(progress_path, {
            "variant": args.variant, "phase": phase, "step": step, "total_steps": total_steps,
            "elapsed_seconds": round(time.perf_counter() - started, 1),
            "curve_train": curve_train, "curve_val": curve_val,
            "inputs_fingerprint": inputs_fingerprint(params),
        })

    def validation(step):
        nonlocal eval_seconds
        progress("validation", step)
        tick = time.perf_counter()
        result = evaluate(model, val_blob["examples"], pad_id, device, tcfg["eval_batch_size"], f"val шаг {step}")
        eval_seconds += time.perf_counter() - tick
        curve_val.append([step, round(result, 6)])
        print(f"[{args.variant}] шаг {step}/{total_steps}: val {result:.6f}", flush=True)
        progress("training", step)
        return result

    base_val = validation(0)
    peak = allocated_bytes(device)
    step, processed_tokens = 0, 0
    optimizer.zero_grad(set_to_none=True)
    for epoch in range(tcfg["epochs"]):
        accum_loss = 0.0
        for index, batch in enumerate(batches(examples, tcfg["batch_size"], pad_id, True, tcfg["seed"] + epoch)):
            batch = {k: v.to(device) for k, v in batch.items()}
            group_size = min(tcfg["grad_accum"], micro_per_epoch - (index // tcfg["grad_accum"]) * tcfg["grad_accum"])
            raw_loss = model(**batch).loss
            if not torch.isfinite(raw_loss):
                raise FloatingPointError(f"Нечисловой train loss на шаге {step + 1}")
            (raw_loss / group_size).backward()
            accum_loss += float(raw_loss.detach()) / group_size
            processed_tokens += int(batch["attention_mask"].sum())
            peak = max(peak, allocated_bytes(device))
            if (index + 1) % tcfg["grad_accum"] and index + 1 < micro_per_epoch:
                continue
            torch.nn.utils.clip_grad_norm_(model.parameters(), tcfg["max_grad_norm"])
            optimizer.step()
            scheduler.step()
            optimizer.zero_grad(set_to_none=True)
            step += 1
            curve_train.append([step, round(accum_loss, 4)])
            print(f"[{args.variant}] шаг {step}/{total_steps}: train {accum_loss:.4f}; elapsed {(time.perf_counter() - started) / 60:.1f} мин", flush=True)
            accum_loss = 0.0
            progress("training", step)
            if step % tcfg["eval_every"] == 0 or step == total_steps:
                validation(step)
                peak = max(peak, allocated_bytes(device))
            if step >= total_steps:
                break
        if step >= total_steps:
            break
    seconds = time.perf_counter() - started - eval_seconds
    adapter_dir = out_root / f"adapter_{args.variant}"
    progress("saving", step)
    model.save_pretrained(adapter_dir, safe_serialization=True)
    tokenizer.save_pretrained(adapter_dir)
    write_json(adapter_dir / "inference_config.json", {
        "model": params["model"], "compare": params["compare"],
        "padding_side": "left", "inputs_fingerprint": inputs_fingerprint(params),
    })
    metrics = {
        "variant": args.variant, "freeze_first": variant["freeze_first"],
        "model": params["model"]["name"], "device": device.type, "dtype": params["model"]["dtype"],
        "seed": tcfg["seed"], "lr": tcfg["lr"], "effective_batch": tcfg["batch_size"] * tcfg["grad_accum"],
        "steps": step, "planned_steps": total_steps, "completed": step == total_steps,
        "trainable_params": trainable, "total_params": total,
        "trainable_share": round(trainable / total, 6),
        "base_val_loss": base_val, "final_val_loss": curve_val[-1][1], "diverged": False,
        "curve_train": curve_train, "curve_val": curve_val,
        "seconds": round(seconds, 1), "eval_seconds": round(eval_seconds, 1),
        "wall_seconds": round(time.perf_counter() - started, 1),
        "seconds_per_step": round(seconds / max(step, 1), 3),
        "processed_train_tokens": processed_tokens,
        "train_tokens_per_sec": round(processed_tokens / seconds, 2),
        "peak_memory_mb": round(peak / 1048576, 1), "memory_metric": memory_metric(device),
        "adapter_dir": str(adapter_dir), "adapter_size_mb": dir_size_mb(adapter_dir),
        "inputs_fingerprint": inputs_fingerprint(params),
        "source_data": {key: {"path": params["data"][key], "sha256": hashlib.sha256(Path(params["data"][key]).read_bytes()).hexdigest()}
                        for key in ("train", "val")},
    }
    mdir = out_root / "metrics" if args.out else Path(params["paths"]["metrics"])
    write_json(mdir / f"train_{args.variant}.json", metrics)
    progress("completed", step)
    print(f"[{args.variant}] ВАРИАНТ ЗАВЕРШЁН: {step} шагов; train {seconds:.0f} с, val {eval_seconds:.0f} с; база {base_val:.6f} -> val {curve_val[-1][1]:.6f}; адаптер {metrics['adapter_size_mb']} МБ", flush=True)


if __name__ == "__main__":
    main()
