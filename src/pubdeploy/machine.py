"""A unit's needs as a state machine, which the convergence engine runs live.

`pubdeploy machine --unit U` prints it: a documented subset of XState v5 config,
as JSON, so Stately's editor and inspector draw it and XState runs it as well as
`load()` here (python-statemachine) does:

    id, initial, states, type ("parallel", "final"), on (event -> {target, guard?}
    or a list of them, tried in order), entry, exit, meta

Guards and actions are names only; the runner provides them. The root holds one
parallel state, `running`, with a region per need. A region's states:

    waiting --start.K--> checking
    checking --checked.K [is_ready]--> ready              (final)
             --checked.K [is_found]--> found              (missing or drift)
             --checked.K--> blocked                       (blocked or unknown: final)
             --error.K--> failed                          (final)
    found    final in mode check, and for a human need in any mode;
             in mode fulfil --approved.K--> fulfilling
    fulfilling --fulfilled.K [is_ok]--> checking          (a fulfil ends with a re-check)
               --fulfilled.K--> failed
               --error.K--> failed
    waiting  --predecessor_failed.K--> blocked
    any state not final --stop--> stopped                 (final)

K is the region's key: the need's id with each character a JavaScript or Python
name cannot hold as `_`, made unique. The need itself is in the region's meta:
its id, type, grade, mode, the needs it is after (keys), its seconds budget, and
how a Stop treats it (`stop`: signal, shorten or continue, and `stop_warning`).
Events carry what the guards read: `checked` a `state`, `fulfilled` an `ok`.

What runs, and in which order, is the deploy block's `run` section's, or the
default generated from the needs (`compile`): every need in `default_mode`, the
`after` edges the walk's order already has, the needs of a serial kind chained,
needs touching one resource (a Secret, a Terraform state, a database) chained,
and 4 at a time. A `run` section may only narrow that: change a need's mode, add
after-edges, lower `parallel`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from typing import Any

SCHEMA = 1
MODES = ("check", "fulfil")
STOPS = ("signal", "shorten", "continue")
PARALLEL = 4
SECTION_KEYS = ("schema", "default_mode", "parallel", "needs")
NEED_KEYS = ("mode", "after")
FINAL = ("ready", "found", "blocked", "failed", "stopped")
# A transformer per schema change: TRANSFORMERS[n] turns a version n section into n + 1.
TRANSFORMERS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {}
UNSAFE = re.compile(r"[^A-Za-z0-9_]")
# What two needs touch alike, by their params: they are chained, one after the other.
RESOURCES = (("secret", "name"), ("state", None), ("database", None))


def key_of(need_id: str, taken: set[str]) -> str:
    """A region's key: the need's id, as a JavaScript and a Python name may hold it, unique."""
    key = UNSAFE.sub("_", need_id)
    out, n = key, 2
    while out in taken:
        out, n = f"{key}_{n}", n + 1
    taken.add(out)
    return out


def region(key: str, meta: dict[str, Any]) -> dict[str, Any]:
    """One need's states, as the module says."""
    fulfils = meta["mode"] == "fulfil" and meta["grade"] != "human"
    stop = {"stop": {"target": "stopped"}}
    found: dict[str, Any] = {"type": "final"}
    if fulfils:
        found = {"on": {f"approved.{key}": {"target": "fulfilling"}, **stop}}
    return {
        "initial": "waiting",
        "meta": meta,
        "states": {
            "waiting": {"on": {f"start.{key}": {"target": "checking"},
                               f"predecessor_failed.{key}": {"target": "blocked"}, **stop}},
            "checking": {"on": {f"checked.{key}": [{"target": "ready", "guard": "is_ready"},
                                                   {"target": "found", "guard": "is_found"},
                                                   {"target": "blocked"}],
                                f"error.{key}": {"target": "failed"}, **stop}},
            "found": found,
            "fulfilling": {"on": {f"fulfilled.{key}": [{"target": "checking", "guard": "is_ok"},
                                                       {"target": "failed"}],
                                  f"error.{key}": {"target": "failed"}, **stop}},
            "ready": {"type": "final"},
            "blocked": {"type": "final"},
            "failed": {"type": "final"},
            "stopped": {"type": "final"},
        },
    }


def default_section(needs: list[dict[str, Any]], default_mode: str = "fulfil") -> dict[str, Any]:
    """The run section a block without one has: every need in default_mode, with its
    after-edges, 4 at a time."""
    return {"schema": SCHEMA, "default_mode": default_mode, "parallel": PARALLEL,
            "needs": {n["id"]: {"mode": default_mode, "after": sorted(n["after"])} for n in needs}}


def generated_after(needs: list[dict[str, Any]]) -> dict[str, set[str]]:
    """Each need's after-edges: the walk's order, then a serial kind's needs chained, then
    needs touching one resource chained, each chain in id order."""
    after = {n["id"]: set(n["after"]) for n in needs}
    by_id = list(needs)  # in the order given: the walk's

    def chain(group: list[dict[str, Any]]) -> None:
        for earlier, later in zip(group, group[1:]):
            if earlier["id"] not in after[later["id"]] and not reaches(after, earlier["id"], later["id"]):
                after[later["id"]].add(earlier["id"])
    for kind in sorted({n["type"] for n in needs if n.get("serial")}):
        chain([n for n in by_id if n["type"] == kind])
    for param, field in RESOURCES:
        groups: dict[str, list[dict[str, Any]]] = {}
        for n in by_id:
            value = (n.get("params") or {}).get(param)
            value = value.get(field) if field and isinstance(value, dict) else (None if field else value)
            if isinstance(value, str) and value:
                groups.setdefault(value, []).append(n)
        for group in groups.values():
            chain(group)
    return after


def reaches(after: Mapping[str, set[str]], start: str, goal: str) -> bool:
    """Whether `start` waits, by after-edges, for `goal`: a chain must not close a cycle."""
    seen, todo = set(), [start]
    while todo:
        i = todo.pop()
        if i == goal:
            return True
        if i not in seen:
            seen.add(i)
            todo += list(after.get(i, ()))
    return False


def upgrade(section: dict[str, Any]) -> dict[str, Any] | str:
    """A run section at this schema version, or why it is not one pubdeploy reads."""
    version = section.get("schema")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        return f'deploy.run must give "schema": {SCHEMA}'
    if version > SCHEMA:
        return f"deploy.run's schema {version} is newer than this pubdeploy's ({SCHEMA}): move to a newer pubdeploy"
    while version < SCHEMA:
        section = TRANSFORMERS[version](section)
        version += 1
    return section


def section_problems(section: Any, needs: list[dict[str, Any]]) -> list[str]:
    """What is wrong with a run section, against the needs it runs: it may only narrow the
    generated default."""
    if not isinstance(section, dict):
        return ["deploy.run must be an object, such as {\"schema\": 1, \"default_mode\": \"fulfil\"}"]
    out = [f"deploy.run has no setting {k}; it takes {', '.join(SECTION_KEYS)}" for k in sorted(set(section) - set(SECTION_KEYS))]
    upgraded = upgrade(section)
    if isinstance(upgraded, str):
        return [*out, upgraded]
    if upgraded.get("default_mode", "fulfil") not in MODES:
        out.append("deploy.run.default_mode must be check or fulfil")
    parallel = upgraded.get("parallel", PARALLEL)
    if not isinstance(parallel, int) or isinstance(parallel, bool) or not 1 <= parallel <= PARALLEL:
        out.append(f"deploy.run.parallel may only lower the default: 1 to {PARALLEL}, not {parallel!r}")
    known = {n["id"] for n in needs}
    given = upgraded.get("needs", {})
    if not isinstance(given, dict):
        return [*out, "deploy.run.needs must be an object, by need id"]
    for name, entry in sorted(given.items()):
        if name not in known:
            out.append(f"deploy.run.needs names {name}, which is no need of this unit")
            continue
        if not isinstance(entry, dict):
            out.append(f"deploy.run.needs.{name} must be an object with mode and after")
            continue
        out += [f"deploy.run.needs.{name} has no setting {k}; it takes {', '.join(NEED_KEYS)}"
                for k in sorted(set(entry) - set(NEED_KEYS))]
        if "mode" in entry and entry["mode"] not in MODES:
            out.append(f"deploy.run.needs.{name}.mode must be check or fulfil")
        after = entry.get("after", [])
        if not isinstance(after, list) or not all(isinstance(a, str) for a in after):
            out.append(f"deploy.run.needs.{name}.after must list need ids")
            continue
        out += [f"deploy.run.needs.{name} is after {a}, which is no need of this unit" for a in after if a not in known]
    if not out:
        edges = generated_after(needs)
        for name, entry in given.items():
            edges[name] |= set(entry.get("after", []))
        if any(reaches(edges, a, name) for name, entry in given.items() for a in entry.get("after", [])):
            out.append("deploy.run.needs' after-edges make needs wait for each other")
    return out


def compile(plan: list[dict[str, Any]], run_section: dict[str, Any] | None = None,
            modes: Mapping[str, str] | None = None) -> dict[str, Any]:
    """The unit's machine: `plan` is each need (id, type, grade, after, seconds, stop,
    stop_warning, serial, params), `run_section` the deploy block's run section or None,
    `modes` a run's own choice of mode per need id, over the section's. ValueError when
    the section or the modes are not ones to run."""
    if bad := section_problems(run_section if run_section is not None else default_section(plan), plan):
        raise ValueError("; ".join(bad))
    section = upgrade(run_section) if run_section is not None else default_section(plan)
    assert isinstance(section, dict)  # noqa: S101 - section_problems said so
    default_mode = section.get("default_mode", "fulfil")
    after = generated_after(plan)
    for name, entry in (section.get("needs") or {}).items():
        after[name] |= set(entry.get("after", []))
    unknown = sorted(set(modes or {}) - {n["id"] for n in plan})
    if unknown or any(m not in MODES for m in (modes or {}).values()):
        raise ValueError(f"the modes name {', '.join(unknown) or 'a mode'} that is not check or fulfil of a need here")
    taken: set[str] = set()
    keys = {n["id"]: key_of(n["id"], taken) for n in sorted(plan, key=lambda n: n["id"])}
    regions = {}
    for n in sorted(plan, key=lambda n: n["id"]):
        mode = (modes or {}).get(n["id"]) or (section.get("needs") or {}).get(n["id"], {}).get("mode") or default_mode
        meta = {"need": n["id"], "type": n["type"], "grade": n["grade"], "mode": mode,
                "after": sorted(keys[a] for a in after[n["id"]] if a in keys), "seconds": n.get("seconds", 60.0),
                "stop": n.get("stop", "signal")}
        if n.get("stop_warning"):
            meta["stop_warning"] = n["stop_warning"]
        regions[keys[n["id"]]] = region(keys[n["id"]], meta)
    return {"id": "service-needs", "initial": "running",
            "meta": {"schema": SCHEMA, "parallel": section.get("parallel", PARALLEL)},
            "states": {"running": {"type": "parallel", "states": regions}}}


def targets(on: Any) -> list[str]:
    listed = on if isinstance(on, list) else [on]
    return [t.get("target") for t in listed if isinstance(t, dict)]


def validate(machine: Any) -> list[str]:
    """What keeps `machine` from being one this module makes and runs."""
    if not isinstance(machine, dict) or machine.get("initial") != "running":
        return ['the machine must be an object whose initial state is "running"']
    running = (machine.get("states") or {}).get("running") or {}
    if running.get("type") != "parallel" or not isinstance(running.get("states"), dict):
        return ["the machine's running state must be parallel, a region per need"]
    out = []
    keys = set(running["states"])
    for key, part in running["states"].items():
        meta = part.get("meta") or {}
        states = part.get("states") or {}
        if part.get("initial") not in states:
            out.append(f"{key}: its initial state {part.get('initial')!r} is not one of its states")
        if meta.get("mode") not in MODES:
            out.append(f"{key}: meta.mode must be check or fulfil")
        if meta.get("stop", "signal") not in STOPS:
            out.append(f"{key}: meta.stop must be one of {', '.join(STOPS)}")
        if meta.get("stop") == "continue" and not meta.get("stop_warning"):
            out.append(f"{key}: meta.stop continue needs a stop_warning")
        out += [f"{key}: it is after {a}, which is no region" for a in meta.get("after", []) if a not in keys]
        for name, state in states.items():
            for event, on in (state.get("on") or {}).items():
                out += [f"{key}.{name}: {event} goes to {t}, which is no state of {key}" for t in targets(on)
                        if t not in states]
        if meta.get("grade") == "human" and "fulfilling" in {t for s in states.values()
                                                              for on in (s.get("on") or {}).values()
                                                              for t in targets(on)}:
            out.append(f"{key}: a human need never enters fulfilling")
    after = {k: set((p.get("meta") or {}).get("after", [])) for k, p in running["states"].items()}
    if not out and any(reaches(after, a, k) for k, v in after.items() for a in v):
        out.append("the regions' after-edges make needs wait for each other")
    return out


def problems(deploy: dict[str, Any], needs: list[dict[str, Any]]) -> list[str]:
    """The deploy block's run section, as `pubrules sync --check` checks it: none when it
    has none."""
    if "run" not in deploy:
        return []
    return section_problems(deploy["run"], needs)


class Guards:
    """What the machine's guards read of an event, for `load()`. python-statemachine passes
    its own `state` to a guard, so `send()` hands the event's state over as `need_state`."""

    def is_ready(self, need_state: str | None = None, **_: Any) -> bool:
        return need_state == "ready"

    def is_found(self, need_state: str | None = None, **_: Any) -> bool:
        return need_state in ("missing", "drift")

    def is_ok(self, ok: bool | None = None, **_: Any) -> bool:
        return ok is True


def send(chart: Any, event: Mapping[str, Any]) -> None:
    """Send an event, as XState takes it ({"type": "checked.KEY", "state": "missing"}), to a
    chart `load()` made."""
    data = {("need_state" if k == "state" else k): v for k, v in event.items() if k != "type"}
    chart.send(event["type"], **data)


def native(machine: dict[str, Any]) -> dict[str, Any]:
    """The machine in python-statemachine's own JSON form: each state's id made unique by
    its region's key, each guard a condition on the bound model."""
    running = machine["states"]["running"]
    regions = {}
    for key, part in running["states"].items():
        states = {}
        for name, state in part["states"].items():
            out: dict[str, Any] = {}
            if name == part["initial"]:
                out["initial"] = True
            if state.get("type") == "final":
                out["final"] = True
            transitions = []
            for event, on in (state.get("on") or {}).items():
                for t in on if isinstance(on, list) else [on]:
                    move = {"event": event, "target": f"{key}__{t['target']}"}
                    if t.get("guard"):
                        move["cond"] = t["guard"]
                    transitions.append(move)
            if transitions:
                out["transitions"] = transitions
            states[f"{key}__{name}"] = out
        regions[key] = {"states": states}
    return {"name": "ServiceNeeds", "states": {"running": {"initial": True, "parallel": True, "states": regions}}}


def load(machine: dict[str, Any]) -> Any:
    """The machine as a python-statemachine StateChart, bound to the guards: give it events
    with `send(chart, {"type": "checked.KEY", "state": "missing"})`, and read `states(chart)`."""
    from statemachine.io import loader  # noqa: PLC0415
    if bad := validate(machine):
        raise ValueError("; ".join(bad))
    return loader.load(json.dumps(native(machine)), format="json")(model=Guards())


def states(chart: Any) -> dict[str, str]:
    """Each region's state, by key, as the chart holds them."""
    out = {}
    for state in chart.configuration:
        key, sep, name = str(state.id).rpartition("__")
        if sep:
            out[key] = name
    return dict(sorted(out.items()))
