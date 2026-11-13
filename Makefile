# pubdeploy: the deploy walk, its need types, and the k8s checks. The targets every
# Python package shares (venv, functional, lock, sync-check, wheel, clean, help) are
# pubkit-python.mk's, which pubkit sync writes.
include pubkit-python.mk

.PHONY: check

check: sync-check functional ## Everything CI runs
