"""The provider contract: what a package offering need types or walk hooks
may rely on, and the one module of pubdeploy, beside pubdeploy.testing, that
a provider or its tests may import.

A provider offers need types under the entry-point group `sustenaut.needs`,
each an instance, and hooks under `sustenaut.walk`. Its code imports nothing
of pubdeploy: any object with a result's names serves as a Result. Its tests
may build Need, Result and Ran from here, and check its types with
`problems` and its hooks with `hook_problems`, which say what `./pubdeploy`
says when it leaves one out.

The name sets below are the contract. A provider detects what it needs by
inclusion (the Context names its code reads are a subset of CONTEXT), not by
a version: a change that drops or renames a name is a breaking change, said
in pubdeploy's changelog, and README's "Provider contract" lists the same
names, which a scenario keeps equal to these.
"""

from __future__ import annotations

import inspect
import re
from typing import Any

from .model import GRADES, STATES, Need, Ran, Result

__all__ = ["CONTEXT", "GRADES", "GROUPS", "HOOK", "LONGEST", "LONGEST_FULFIL", "NEED", "NEEDS", "RESULT",
           "RESULT_OPTIONAL", "STATES", "TYPE", "TYPE_OPTIONAL", "WALK", "Need", "Ran", "Result", "hook_problems",
           "problems"]

NEEDS, WALK = "sustenaut.needs", "sustenaut.walk"
GROUPS = (NEEDS, WALK)

# What a check or a fulfil may read of the walk's Context.
CONTEXT = frozenset({"root", "config", "block", "namespace", "unit", "channel", "kubectl", "server", "gh", "send",
                     "bitwarden_writer", "http_get", "env", "now", "rendered", "offline", "slug", "zones", "resolve",
                     "values", "types", "needs", "results", "sleep", "dispatched"})
NEED = frozenset({"id", "type", "name", "params", "implied_by", "after"})
RESULT = frozenset({"state", "summary", "fix", "details"})
RESULT_OPTIONAL = frozenset({"fixable", "step"})
TYPE = frozenset({"type", "schema", "grade", "budget", "offline", "default_name", "depends_on", "check", "fulfil"})
TYPE_OPTIONAL = frozenset({"fulfil_budget", "singleton", "grade_for", "requires", "action", "value", "secret_keys",
                           "secret_shape", "made_from", "serial", "stop", "stop_warning"})
# A sustenaut.walk hook's parameters: prepare(ctx, plan, terminal), returning a line to print or None.
HOOK = ("ctx", "plan", "terminal")

NAME = re.compile(r"[a-z][a-z0-9-]*(\.[a-z][a-z0-9-]*)+")
LONGEST = 10.0  # seconds a check may take, at most
LONGEST_FULFIL = 900.0  # seconds a fulfil may take, at most


def problems(kind: Any) -> list[str]:
    """What keeps `kind` from being a need type, each as `./pubdeploy` says it."""
    out = []
    name = getattr(kind, "type", None)
    if not isinstance(name, str) or not NAME.fullmatch(name):
        out.append("its type must be dotted lower-case words, such as example.thing")
    schema = getattr(kind, "schema", None)
    if not isinstance(schema, dict) or schema.get("type") != "object" or schema.get("additionalProperties") is not False:
        out.append("its schema must be an object's, with additionalProperties false")
    budget = getattr(kind, "budget", None)
    if isinstance(budget, bool) or not isinstance(budget, int | float) or not 0 < budget <= LONGEST:
        out.append(f"its budget must be more than 0 and at most {LONGEST:g} seconds")
    fulfil = getattr(kind, "fulfil_budget", 1.0)
    if isinstance(fulfil, bool) or not isinstance(fulfil, int | float) or not 0 < fulfil <= LONGEST_FULFIL:
        out.append(f"its fulfil_budget must be more than 0 and at most {LONGEST_FULFIL:g} seconds")
    if getattr(kind, "grade", None) not in GRADES:
        out.append(f"its grade must be one of {', '.join(GRADES)}")
    if not isinstance(getattr(kind, "offline", None), bool):
        out.append("its offline must be true or false")
    for method in ("default_name", "depends_on", "check", "fulfil"):
        if not callable(getattr(kind, method, None)):
            out.append(f"it has no {method}")
    return out


def hook_problems(hook: Any) -> list[str]:
    """What keeps `hook` from being a sustenaut.walk hook."""
    if not callable(hook):
        return ["it is not a function"]
    try:
        inspect.signature(hook).bind(*HOOK)
    except TypeError:
        return [f"it must take ({', '.join(HOOK)})"]
    except ValueError:  # a builtin without a signature: called as it is
        return []
    return []
