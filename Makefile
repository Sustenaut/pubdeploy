# pubdeploy: the deploy walk, its need types, and the k8s checks. The targets every
# Python package shares (venv, functional, lock, sync-check, wheel, clean, help) are
# pubrules-python.mk's, which pubrules sync writes.
include pubrules-python.mk

.PHONY: check

check: sync-check functional ## Everything CI runs
