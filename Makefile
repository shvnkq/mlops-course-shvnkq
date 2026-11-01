.PHONY: install up down sweep promote predict check check-storage
install:
	uv sync --frozen
up:
	docker compose -p mlops-hw6 up --build -d --wait
down:
	docker compose -p mlops-hw6 down
sweep:
	uv run python -m src.sweep
promote:
	uv run python -m evaluation.cli promote
predict:
	uv run python -m src.predict --uri models:/geonames-qwen-adapter@champion --prompt "В какой стране находится город Dar es Salaam?"
check:
	bash tests/check.sh
check-storage:
	uv run python tests/check_storage.py

.PHONY: report candidate baseline-init evaluate eval check-eval check-negative check-all baseline-update predict-candidate
report:
	uv run python -m src.report
candidate:
	uv run python -m evaluation.cli candidate
baseline-init:
	uv run python -m evaluation.cli baseline-init
evaluate:
	uv run python -m evaluation.cli evaluate
eval:
	uv run python -m evaluation.cli gate
check-eval:
	uv run python -m unittest discover -s tests -p 'test_*.py' -v
check-negative:
	uv run python -m evaluation.cli negative
check-all: check check-eval
baseline-update:
	uv run python -m evaluation.cli baseline-update
predict-candidate:
	uv run python -m src.predict --uri models:/geonames-qwen-adapter@candidate --prompt "В какой стране находится город Dar es Salaam?"

.PHONY: eval-data conclusion package
eval-data:
	uv run --frozen python -m scripts.prepare_eval
conclusion:
	uv run --frozen python -m scripts.conclude_hw67
package:
	uv run --frozen python -m scripts.package_hw67

.PHONY: check-hw8910 serve-hw8910 release-hw8910
check-hw8910:
	cd hw8910 && ../.venv/bin/python -m unittest discover -s tests -v
serve-hw8910:
	uv run --frozen python hw8910/api.py
release-hw8910:
	uv run --frozen python hw8910/flow.py
