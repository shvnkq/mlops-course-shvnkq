.PHONY: install repro v1 v2 diff dag diversity contamination tokenize check check-hw3 clean

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

check:
	$(CHECK_BASH) tests/check.sh

check-hw3:
	$(CHECK_BASH) tests/check_hw3.sh

clean:
	rm -rf data metrics/*.json params.yaml.bak params.yaml.orig
