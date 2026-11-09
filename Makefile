# pubdeploy: the deploy walk, its need types, and the k8s checks.
SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help
export PATH := $(CURDIR)/.venv/bin:$(PATH)

.PHONY: help venv functional lock sync-check check wheel clean

help: ## Available targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | sed 's/:.*## /\t/'

venv: ## Hash-locked environment, with this checkout installed editable
	python3 -m venv .venv
	.venv/bin/pip install --quiet --require-hashes -r tests/requirements.lock
	.venv/bin/pip install --quiet --no-deps -e .

functional: ## The Gherkin suite, with its coverage in coverage/coverage.xml
	rm -rf coverage && mkdir coverage
	cd tests && COVERAGE_RCFILE=$(CURDIR)/pyproject.toml COVERAGE_FILE=$(CURDIR)/coverage/.coverage \
	  ../.venv/bin/coverage run -m pytest -q $(PYTEST_ARGS)
	COVERAGE_FILE=coverage/.coverage .venv/bin/coverage combine -q
	COVERAGE_FILE=coverage/.coverage .venv/bin/coverage xml -q

lock: ## Pin tests/requirements.txt with hashes
	./pubkit lock

sync-check: ## Fail if pubkit's managed files drifted
	./pubkit sync --check

check: sync-check functional ## Everything CI runs

wheel: ## Build the wheel a release carries
	.venv/bin/pip wheel --quiet --no-deps . -w dist

clean: ## Remove build artifacts
	rm -rf build dist coverage src/*.egg-info .pytest_cache tests/.pytest_cache
