"""The scheduled walk: pubdeploy's reusable deploy-check.yml, and the caller
`pubkit sync` seeds (through `sync_lines`) in a repository with a deploy
block, once, as the repository's own from then on. `pubkit bump` moves its
pin with pubdeploy's other uses.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

CALLER = ".github/workflows/deploy-check.yml"


def caller(config: dict[str, Any]) -> str:
    from . import __version__  # noqa: PLC0415
    from .config import owner, ref, release_commit  # noqa: PLC0415
    pin = ref(__version__, release_commit())
    return (f"# Seeded by pubdeploy {__version__}: this repository's own. Every 30 minutes, the deploy walk, read-only.\n"
            "name: deploy-check\n"
            "on: { schedule: [{ cron: '*/30 * * * *' }], workflow_dispatch: {} }\n"
            "permissions: { actions: read, contents: read, id-token: write }\n"
            "jobs:\n"
            "  check:\n"
            f"    uses: {owner(config)}/pubdeploy/.github/workflows/deploy-check.yml@{pin}\n"
            "    secrets: inherit\n")


def seed(root: Path, config: dict[str, Any], check: bool) -> tuple[list[str], bool]:
    """Seed the caller where there is none; with `check`, say so and fail instead."""
    if (root / CALLER).exists():
        return [], False
    if check:
        return [f"pubdeploy: no {CALLER}, the scheduled deploy walk: `pubkit sync` seeds it"], True
    (root / CALLER).parent.mkdir(parents=True, exist_ok=True)
    (root / CALLER).write_text(caller(config), encoding="utf-8")
    return [f"seeded   {CALLER}"], False
