"""What pubkit calls of pubdeploy, through two entry-point groups, so pubkit
imports nothing of the walk:

- `sustenaut.sync`, `check(root, config, check) -> (lines, failed)`: the deploy
  block's offline check (the block and its needs, the manifests against
  them, the units against the deploy workflow) and, without `check`, seeding
  the scheduled walk's caller. `pubkit sync` calls it after its own work, and
  `--check` fails when it says so. `pubdeploy sync-check` runs it alone.
- `sustenaut.bump`, `bump(root) -> lines`: each deploy.providers entry moved
  to its latest release, then this repository's uses of pubdeploy's
  reusable workflows moved to the pubdeploy deploy.providers names, a caller
  of k8s-deploy.yml still started by `push` rewritten to `workflow_run`.
  `pubkit bump` calls it after moving pubkit's own pins; `pubdeploy bump`
  runs it alone.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .schema import BLOCK


def check(root: Path, config: dict[str, Any], check: bool) -> tuple[list[str], bool]:
    if BLOCK not in config:
        return [], False
    from . import offline_lines  # noqa: PLC0415
    from .scheduled import seed  # noqa: PLC0415
    lines, failed = offline_lines(root, config)
    seeded, missing = seed(root, config, check)
    # Writing, a disagreement is said and fails nothing, as pubkit sync goes on.
    return lines + seeded, check and (failed or missing)


# A use of pubdeploy's reusable workflows, by commit with the version in a
# comment, or by tag.
PIN = re.compile(r"(?P<owner>[A-Za-z0-9][A-Za-z0-9-]*)/(?P<path>pubdeploy/\.github/workflows/[\w.-]+\.ya?ml@)"
                 r"(?:v|[0-9a-f]{40}[ \t]+#[ \t]*v)(?P<version>[0-9][^\s'\"]*)")


def tag_commit(repo: str, version: str, gh: Any = None) -> str | None:
    """The commit the tag v`version` of `repo` names, or None when it cannot be read."""
    from .github import ApiError, gh as api  # noqa: PLC0415
    call = gh or api
    try:
        found = call("GET", f"repos/{repo}/git/ref/tags/v{version}", None) or {}
        target = found.get("object") or {}
        if target.get("type") == "tag":  # annotated: the tag object names the commit
            target = (call("GET", f"repos/{repo}/git/tags/{target.get('sha')}", None) or {}).get("object") or {}
    except ApiError:
        return None
    sha = target.get("sha")
    return sha if isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{40}", sha) else None


def bump(root: Path, gh: Any = None, find: Any = None) -> list[str]:
    import json  # noqa: PLC0415
    from .config import ref  # noqa: PLC0415
    from .providers import WHEEL, bump as providers  # noqa: PLC0415
    from .units import K8S_DEPLOY, retrigger, trigger_problems  # noqa: PLC0415
    path = root / "pubkit.json"
    if not path.is_file():
        return []
    out = providers(root, gh, find)
    deploy = json.loads(path.read_text(encoding="utf-8")).get(BLOCK)
    listed = deploy.get("providers") if isinstance(deploy, dict) else None
    ours = next((p for p in listed or [] if isinstance(p, dict) and p.get("distribution") == "pubdeploy"), None)
    m = WHEEL.fullmatch(str((ours or {}).get("wheel", "")))
    if not m:
        return out
    version = m["version"]
    commit = tag_commit(m["repo"], version, gh)
    for workflow in sorted((root / ".github" / "workflows").glob("*.y*ml")):
        text = workflow.read_text(encoding="utf-8")
        new = PIN.sub(lambda p: f"{p['owner']}/{p['path']}{ref(version, commit)}", text)
        if K8S_DEPLOY.search(new) and trigger_problems(new, workflow.name):
            new = retrigger(new)
        if new != text:
            workflow.write_text(new, encoding="utf-8")
            out.append(f"updated  {workflow.relative_to(root)} (pubdeploy@{ref(version, commit)})")
    return out
