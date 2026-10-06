.PHONY: install repro v1 v2 diff dag diversity contamination tokenize train train-all train-freeze plot compare check check-hw3 report clean
.NOTPARALLEL: train

ifeq ($(OS),Windows_NT)
CHECK_BASH := "$(shell git --exec-path)/../../../bin/bash.exe"
else
CHECK_BASH := bash
endif

install:
	uv sync

repro:
	uv run dvc repro

v1:
	uv run python scripts/set_version.py v1
	uv run dvc repro

v2:
	uv run python scripts/set_version.py v2
	uv run dvc repro

diff:
	uv run dvc metrics diff

dag:
	uv run dvc dag

diversity:
	uv run python -m src.diversity

contamination:
	uv run python scripts/check_contamination.py

tokenize:
	uv run python -X utf8 -m src.tokenize_data

train: train-all train-freeze plot

train-all:
	uv run python -u -X utf8 -m src.train --variant all_layers

train-freeze:
	uv run python -u -X utf8 -m src.train --variant freeze14

plot:
	uv run python -X utf8 -m src.plot

compare:
	uv run python -X utf8 -m src.compare --variant all_layers

check:
	uv run python -X utf8 scripts/run_check.py

check-hw3:
	uv run python -X utf8 scripts/run_check.py --script tests/check_hw3.sh

report:
	uv run python -X utf8 -m scripts.report_hw5

clean:
	uv run python -X utf8 scripts/clean_hw5.py
