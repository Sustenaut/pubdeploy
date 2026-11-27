"""The Secret a unit's live runs' Job reads Bitwarden with (`pubrules sync`, through hooks.py).

A live run's Job runs in the unit's namespace with that namespace's Secret
`pubdeploy-executor` as its environment, each key a variable. A unit whose needs
are bitwarden.* ones checks and fulfils them with a Bitwarden token, so the Secret
holds `BWS_ACCESS_TOKEN`, filled like any other need: a bitwarden.secret named
`<unit>-executor-bws-token`, the unit's own token of the read account, so one
unit's token is revoked alone.

`sync --check` fails for a unit with bitwarden.* needs and no need filling that
key; `sync` adds the need, changing nothing else of pubrules.json. A unit whose
runs no Job walks (the engine's own namespace) says `"executor": false`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .schema import BLOCK

SECRET = "pubdeploy-executor"
KEY = "BWS_ACCESS_TOKEN"
TYPE = "bitwarden.secret"


def item(unit: str) -> str:
    """The unit's own Bitwarden item, its token of the read account."""
    return f"{unit}-executor-bws-token"


def need(block: dict[str, Any], unit: str) -> dict[str, Any]:
    """The need that fills the unit's executor Secret; scoped to the unit when the block has more."""
    entry: dict[str, Any] = {"type": TYPE, "name": item(unit), "secret": {"name": SECRET, "key": KEY}}
    if block.get("units"):
        entry["unit"] = unit
    return entry


def fills(entry: dict[str, Any], unit: str) -> bool:
    secret = entry.get("secret")
    return entry.get("unit", unit) == unit and isinstance(secret, dict) \
        and secret.get("name") == SECRET and secret.get("key") == KEY


def missing(block: Any) -> list[str]:
    """The units with bitwarden.* needs and none filling their executor Secret's token."""
    if not isinstance(block, dict) or not isinstance(block.get("namespace"), str) \
            or not isinstance(block.get("needs", []), list) or not isinstance(block.get("units") or {}, dict):
        return []  # the block's own check says what is wrong with it
    from .units import names, unit_block  # noqa: PLC0415
    out = []
    for unit in names(block):
        if unit_block(block, unit).get("executor") is False:
            continue
        needs = [e for e in block.get("needs", []) if isinstance(e, dict) and e.get("unit", unit) == unit]
        if any(fills(e, unit) for e in needs):
            continue
        if any(str(e.get("type", "")).startswith("bitwarden.") for e in needs):
            out.append(unit)
    return out


def problem(unit: str) -> str:
    return (f"pubdeploy: deploy: unit {unit} has bitwarden.* needs and no need filling the Secret {SECRET}'s "
            f"{KEY}, which its live runs' Job reads Bitwarden with; run `pubrules sync`, which adds the "
            f"{TYPE} {item(unit)}, or say \"executor\": false for a unit no Job walks")


def ensure(root: Path, config: dict[str, Any], check: bool) -> tuple[list[str], bool, dict[str, Any]]:
    """Lines to print, whether that fails, and the config as it now reads."""
    units = missing(config.get(BLOCK))
    if not units:
        return [], False, config
    if check:
        return [problem(u) for u in units], True, config
    path = root / "pubrules.json"
    out = []
    for unit in units:
        text = path.read_text(encoding="utf-8")
        entry = need(json.loads(text)[BLOCK], unit)
        path.write_text(appended(text, entry), encoding="utf-8")
        out.append(f"updated  pubrules.json (deploy.needs {TYPE}:{item(unit)}, the Secret {SECRET}'s {KEY})")
    return out, False, json.loads(path.read_text(encoding="utf-8"))


def closing(text: str, start: int) -> int:
    """The index of the `]` that closes the array opened at `start`, in a text that is JSON."""
    depth, quoted, escaped = 0, False, False
    for i in range(start, len(text)):
        c = text[i]
        if quoted:
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == '"':
                quoted = False
            continue
        if c == '"':
            quoted = True
        elif c in "[{":
            depth += 1
        elif c in "]}":
            depth -= 1
            if depth == 0:
                return i
    raise ValueError("an array that does not close")  # pragma: no cover - the text is JSON


def appended(text: str, entry: dict[str, Any]) -> str:
    """pubrules.json with the entry last in the deploy block's needs, the rest of the text as
    it was. The text edit is kept only when it reads as that same JSON; otherwise the file
    is written whole."""
    expected = json.loads(text)
    expected[BLOCK]["needs"] = [*expected[BLOCK].get("needs", []), entry]
    deploy = re.search(r'"deploy"\s*:\s*\{', text)
    listed = re.compile(r'"needs"\s*:\s*\[').search(text, deploy.end()) if deploy else None
    if listed:
        end = closing(text, listed.end() - 1)
        inside = text[listed.end():end]
        lead = re.match(r"\s*", inside).group()
        at = listed.end() + len(inside.rstrip())
        sep = "" if not inside.strip() else "," + (lead if "\n" in lead else " ")
        candidate = text[:at] + sep + json.dumps(entry) + text[at:]
        if json.loads(candidate) == expected:  # another block's "needs" first, say: written whole
            return candidate
    return json.dumps(expected, indent=2) + "\n"
