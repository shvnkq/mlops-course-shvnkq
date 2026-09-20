.PHONY: install repro v1 v2 diff dag diversity contamination check clean

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

check:
	$(CHECK_BASH) tests/check.sh

clean:
	rm -rf data metrics/*.json params.yaml.bak params.yaml.orig
