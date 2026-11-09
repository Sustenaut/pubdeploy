"""What pubdeploy reads of a repository's pubkit.json beside the deploy
block: the file itself, whose owner's pubdeploy a workflow calls, and the
`github_app` and `secrets` blocks, which imply the github.* needs. pubkit
validates those blocks in `pubkit sync`; this is the same reading, kept here
so pubdeploy imports nothing of pubkit's."""

from __future__ import annotations

import json
import os
import re
import sys
from importlib import resources
from pathlib import Path
from typing import Any

CONFIG = "pubkit.json"
# The owner of pubdeploy's repository, whose workflows a repository calls;
# pubkit.json's `workflows_owner` names another.
OWNER = "Sustenaut"
OWNER_NAME = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?")
COMMIT = re.compile(r"[0-9a-f]{40}")


def read_config(root: Path) -> dict[str, Any]:
    path = root / CONFIG
    if not path.exists():
        sys.exit(f"pubdeploy: no {CONFIG} here; pubdeploy walks the deploy block of a repository's {CONFIG}")
    config = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        sys.exit(f"pubdeploy: {CONFIG} must be an object")
    return config


# A copy of pubkit's refs.owner.
def owner(config: dict[str, Any] | None) -> str:
    """The owner pubkit.json's `workflows_owner` names, or OWNER."""
    given = (config or {}).get("workflows_owner", OWNER)
    if not isinstance(given, str) or not OWNER_NAME.fullmatch(given):
        sys.exit(f"pubdeploy: pubkit.json's workflows_owner must be a GitHub owner, such as "
                 f'"{OWNER}", not {given!r}')
    return given


# A copy of pubkit's refs.ref.
def ref(version: str, commit: str | None) -> str:
    """What follows `@` in a pin of `version`: its commit, with the version
    in a comment, or the tag when the commit is unknown."""
    return f"{commit} # v{version}" if commit else f"v{version}"


# After pubkit's refs.release_commit.
def release_commit() -> str | None:
    """The commit of this pubdeploy's release tag, which wheel.yml writes into
    the wheel as `release-commit`; None from a source tree.
    PUBDEPLOY_RELEASE_COMMIT, which tests set, stands in for it."""
    given = os.environ.get("PUBDEPLOY_RELEASE_COMMIT")
    if given is None:
        try:
            given = (resources.files("pubdeploy") / "release-commit").read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
    given = given.strip()
    if not given:
        return None
    if not COMMIT.fullmatch(given):
        sys.exit(f"pubdeploy: its release commit must be 40 hexadecimal digits, not {given!r}")
    return given


# The github_app and secrets blocks: after pubkit's secrets_config (plan, config_problems).
APP = "github_app"
OTHERS = "secrets"
KINDS = {"secret", "variable"}
SLOTS = {"id": "variable", "installation_id": "variable", "key": "secret"}
FROM = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
TO = re.compile(r"[A-Z_][A-Z0-9_]*")
ENVIRONMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")


def _app_sound(block: Any) -> bool:
    if not isinstance(block, dict) or set(block) != set(SLOTS):
        return False
    for given in block.values():
        if not isinstance(given, dict) or set(given) != {"from", "to"}:
            return False
        if not isinstance(given["from"], str) or not FROM.fullmatch(given["from"]):
            return False
        if not isinstance(given["to"], str) or not TO.fullmatch(given["to"]) or given["to"].startswith("GITHUB_"):
            return False
    return True


def _entry_sound(entry: Any) -> bool:
    if not isinstance(entry, dict) or set(entry) - {"environment"} != {"from", "to", "kind"}:
        return False
    return (isinstance(entry["from"], str) and bool(FROM.fullmatch(entry["from"]))
            and isinstance(entry["to"], str) and bool(TO.fullmatch(entry["to"])) and not entry["to"].startswith("GITHUB_")
            and entry["kind"] in KINDS
            and ("environment" not in entry or (isinstance(entry["environment"], str)
                                                and bool(ENVIRONMENT.fullmatch(entry["environment"])))))


def secrets_sound(config: dict[str, Any]) -> bool:
    """Whether both blocks read as `pubkit sync` takes them, no name used twice.
    pubkit says what is wrong with them; an unsound block implies no need."""
    if APP in config:
        block = config[APP]
        apps = block if isinstance(block, list) else [block]
        if not apps or not all(_app_sound(a) for a in apps):
            return False
    if OTHERS in config:
        if not isinstance(config[OTHERS], list) or not all(_entry_sound(e) for e in config[OTHERS]):
            return False
    names = [(item["kind"], item["to"], item.get("environment", "")) for item in plan(config)]
    return len(names) == len(set(names))


def plan(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Everything the two blocks name: from, to, kind, and which app slot, if any."""
    block = config.get(APP, [])
    apps = block if isinstance(block, list) else [block]
    out = [{"from": app[slot]["from"], "to": app[slot]["to"], "kind": kind, "check": slot}
           for app in apps for slot, kind in SLOTS.items()]
    return out + [{**entry, "check": None} for entry in config.get(OTHERS, [])]


# A copy of pubkit's paths.confined.
def confined(path: Path | str, what: str, also: tuple[Path, ...] = ()) -> Path:
    """`path`, resolved, when it lies in the working directory, a temporary
    directory, or one of `also`; otherwise pubdeploy stops, naming `what`."""
    import tempfile  # noqa: PLC0415
    bases = [Path.cwd(), Path(tempfile.gettempdir())]
    if os.environ.get("RUNNER_TEMP"):
        bases.append(Path(os.environ["RUNNER_TEMP"]))
    resolved = Path(path).resolve()
    if any(resolved.is_relative_to(base.resolve()) for base in [*bases, *also]):
        return resolved
    where = " or ".join(["the working directory", "a temporary directory", *(str(a) for a in also)])
    sys.exit(f"pubdeploy: {what} ({path}) must be in {where}")
