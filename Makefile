.PHONY: install generate bench check clean

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

check:
	$(CHECK_BASH) tests/check.sh

clean:
	rm -rf docs/bench.json out1.txt out2.txt params.yaml.bak
