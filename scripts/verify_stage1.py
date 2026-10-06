"""Preflight checks for a completed smoke run and its offline portability."""

import json
from pathlib import Path

import torch
import yaml
from peft import PeftModel
from safetensors import safe_open
from transformers import AutoModelForCausalLM, AutoTokenizer

from src.compare import generate
from src.config import load_params
from src.runtime import setup_runtime
from src.train import inputs_fingerprint, lora_config


def main():
    params = load_params()
    setup_runtime(params)
    root = Path("benchmark/smoke-a")
    m = json.loads((root / "metrics/train_all_layers.json").read_text(encoding="utf-8"))
    assert m["completed"] and m["steps"] == 3
    assert m["inputs_fingerprint"] == inputs_fingerprint(params)
    assert m["curve_val"][0][0] == 0 and m["curve_val"][-1][0] == 3
    assert m["final_val_loss"] < m["base_val_loss"]
    assert m["trainable_params"] == 5046272
    adir = root / "adapter_all_layers"
    with safe_open(adir / "adapter_model.safetensors", framework="pt") as weights:
        assert all("lora_" in key for key in weights.keys())
    tok = AutoTokenizer.from_pretrained(adir, local_files_only=True)
    print(f"Smoke: completed, val {m['base_val_loss']:.6f} -> {m['final_val_loss']:.6f}; adapter {m['adapter_size_mb']} MiB", flush=True)
    cfg = lora_config(params, 28, 14)
    assert cfg.layers_to_transform == list(range(14, 28))
    dvc = yaml.safe_load(Path("dvc.yaml").read_text(encoding="utf-8"))["stages"]
    assert all(stage in dvc for stage in ("train_all", "train_freeze", "compare"))
    base = AutoModelForCausalLM.from_pretrained(params["model"]["name"], dtype=torch.float32, local_files_only=True)
    model = PeftModel.from_pretrained(base, adir).eval()
    probe = dict(params, compare=dict(params["compare"], max_new_tokens=8))
    answer = generate(model, tok, [params["compare"]["prompts"][0]], params["compare"]["system"], probe, torch.device("cpu"))
    assert len(answer) == 1 and answer[0]
    print(f"Offline adapter load + generation OK: {answer[0]!r}", flush=True)
    print("Freeze14 config: layers 14..27; DVC stages OK", flush=True)


if __name__ == "__main__":
    main()
