"""GitHub through `gh`: one API call, and setting a secret or variable with
its value on standard input. The walk's ctx.gh and ctx.send, with which the
github.* types (pubsec's among them) read and set what GitHub holds."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from typing import Any


# A copy of pubkit's protect.gh.
def gh(method: str, path: str, body: Any = None) -> Any:
    """One GitHub API call through `gh api`; its JSON, or None when empty."""
    argv = ["gh", "api", "-X", method, "-H", "Accept: application/vnd.github+json", path]
    if body is not None:
        argv += ["--input", "-"]
    proc = subprocess.run(argv, input=None if body is None else json.dumps(body),
                          capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise ApiError(f"gh api -X {method} {path}: {proc.stderr.strip()}", proc.stdout)
    return json.loads(proc.stdout) if proc.stdout.strip() else None


# A copy of pubkit's protect.ApiError; pubsec's types read its .status.
class ApiError(Exception):
    """A refused call: gh's message, then the reasons GitHub's response gives."""

    def __init__(self, message: str, response: str = ""):
        m = re.search(r"\(HTTP (\d+)\)", message)
        self.status = int(m.group(1)) if m else None
        try:
            errors = json.loads(response).get("errors") or []
        except (ValueError, AttributeError):
            errors = []
        reasons = [e if isinstance(e, str) else e.get("message") or json.dumps(e) for e in errors]
        super().__init__("; ".join([message, *reasons]))


# A copy of pubkit's protect.gh_set.
def gh_set(kind: str, name: str, repo: str, value: str, environment: str | None = None) -> str | None:
    """Set one secret or variable in `repo` through gh, the value on its standard
    input; what gh said if it refused, else None."""
    done = subprocess.run(["gh", kind, "set", name, "-R", repo,
                           *(["--env", environment] if environment else [])],
                          input=value, text=True, capture_output=True, check=False)
    return done.stderr.strip() if done.returncode != 0 else None


# A copy of pubkit's protect.origin.
def origin() -> str:
    """OWNER/NAME of the GitHub repository `origin` points at."""
    proc = subprocess.run(["git", "remote", "get-url", "origin"],
                          capture_output=True, text=True, check=False)
    m = re.search(r"github\.com[:/]([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?$",
                  proc.stdout.strip())
    if not m:
        sys.exit("pubdeploy: origin is not a GitHub repository")
    return m.group(1)
