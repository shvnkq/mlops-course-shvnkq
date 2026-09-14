.PHONY: install generate bench inspect check clean

ifeq ($(OS),Windows_NT)
CHECK_BASH := "$(shell git --exec-path)/../../../bin/bash.exe"
else
CHECK_BASH := bash
endif

install:
	uv sync

generate:
	uv run python -m src.generate

bench:
	uv run python -m src.bench

inspect:
	uv run python -m src.inspect_model

check:
	$(CHECK_BASH) tests/check.sh

clean:
	rm -rf docs/bench.json docs/report.json out1.txt out2.txt params.yaml.bak
