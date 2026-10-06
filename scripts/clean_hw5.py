"""Explicit make clean for generated HW5 outputs; retains HW3/HW4 input data."""

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    targets = [ROOT / "models", ROOT / "docs/curves.png", ROOT / "docs/compare.md"]
    targets += [ROOT / "metrics" / name for name in (
        "train_all_layers.json", "train_freeze14.json", "compare_all_layers.json")]
    for target in targets:
        resolved = target.resolve()
        if resolved == ROOT or not resolved.is_relative_to(ROOT):
            raise SystemExit(f"Refusing unexpected cleanup path: {resolved}")
    for target in targets:
        if target.is_dir():
            shutil.rmtree(target)
        elif target.is_file():
            target.unlink()
        print(f"clean: {target.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
