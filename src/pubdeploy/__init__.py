"""`pubdeploy walk`, `pubdeploy check` and `pubdeploy types` (cli.py):
what a service needs before it deploys, whether it has it, and making it.

    pubdeploy walk [--fulfil] [--yes] [--unit NAME] [--kubectl CMD] [--server HOST]
                       [--zones PATH]... [--journal URL] [--json] [--offline] [--namespace NS]
    pubdeploy check ...                      walk without --fulfil
    pubdeploy types

pubrules.json's `deploy` block names the namespace, and maybe the host, the
deploy workflow, the gate variable, the overlay and needs nothing implies.
The block, the secrets, github_app and variables blocks, and the Secrets the
rendered overlay reads imply the rest (implied.py). `check` walks every need
in order (order.py, walk.py) and prints its state: ready, missing, drift,
blocked or unknown. It reads, and changes nothing. `--offline` checks only
what needs no network: the rendered manifests against the needs, the
manifest files, and the host against the hosting block. `pubrules sync
--check` runs that too, so a block that disagrees with the manifests fails CI.

`walk --fulfil` then acts (walk.py): it prints the plan, a line per need
it will act on, waits for a typed `yes` (--yes skips that), asks for a
Bitwarden write token when a need wants one (the sustenaut.walk hook,
pubsec's, asks for it at a hidden prompt), and visits
the needs again, making each auto one that is missing. A walk from GitHub
Actions, or with --yes and no terminal, asks for no token, so the needs that
want one are unknown, unless PUBSEC_WRITE_TOKEN_FILE names a file the hook
reads the token from (the convergence engine's Fulfil). The channels kubectl and the server are reached by are
channels.py's; a block's units, units.py's: each is walked, and journaled,
on its own.

Exit 0 when every need checked is ready, 1 otherwise, 2 for a bad block;
with --tolerate-unknown, 0 unless one is missing, drift or blocked, for a
scheduled walk whose token may not read everything (the unknowns stay in
the journal).
`--json` prints the walk as a deploy-journal/2 document instead (journal.json),
a list of them for more than one unit; `--journal URL` also writes it to
storage (store.py). No value is printed: a check names a secret, its key,
its length and its kind, never what it holds.

    load(root) -> Plan            the needs of a unit, in walk order
    check(plan, ctx) -> Journal   the walk
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from .model import Context, Journal, Need, NeedType, Result, Stop
from .schema import BLOCK, DEFAULT_OVERLAY

__all__ = ["Context", "Journal", "Need", "NeedType", "Plan", "Result", "__version__", "check", "load"]


def _version() -> str:
    from importlib.metadata import PackageNotFoundError, version  # noqa: PLC0415
    try:
        return version("pubdeploy")
    except PackageNotFoundError:
        return "0+source"


__version__ = _version()
RENDER_TIMEOUT = 60
TOOL_TIMEOUT = 30


@dataclass
class Plan:
    root: Path
    config: dict[str, Any]
    namespace: str
    needs: dict[str, Need]
    order: list[str]
    problems: list[str]
    unit: str = ""


def render(root: Path, overlay: str) -> str:
    """The overlay as kustomize builds it: kustomize, or kubectl's own."""
    where = root / overlay
    if shutil.which("kustomize"):
        argv = ["kustomize", "build", str(where)]
    elif shutil.which("kubectl"):
        argv = ["kubectl", "kustomize", str(where)]
    else:
        raise Stop(f"neither kustomize nor kubectl is installed, to render {overlay}", missing_tool=True)
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=RENDER_TIMEOUT, check=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise Stop(f"{argv[0]} did not render {overlay} ({type(e).__name__})", missing_tool=True) from None
    if done.returncode != 0:
        last = (done.stderr.strip().splitlines() or [f"exit {done.returncode}"])[-1]
        raise Stop(f"{' '.join(argv[:2])} {overlay} failed: {last[:300]}")
    return done.stdout


def renderer(root: Path, overlay: str) -> Any:
    """render, once."""
    return cache(lambda: render(root, overlay))


def kubectl(command: str) -> Any:
    from .channels import plain  # noqa: PLC0415
    return plain(command)


def http_get(url: str, timeout: float) -> tuple[int, bytes]:
    request = urllib.request.Request(url, headers={"User-Agent": "pubdeploy"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - an https:// need
            return response.status, response.read(1 << 16)
    except urllib.error.HTTPError as e:
        return e.code, b""
    except urllib.error.URLError as e:
        if isinstance(e.reason, TimeoutError):
            raise TimeoutError from None
        raise ConnectionError(type(e.reason).__name__) from None


def resolve(host: str, rtype: str) -> list[str] | None:
    from .names import NAME, checked, checked_type  # noqa: PLC0415
    if not shutil.which("dig"):
        return None
    done = subprocess.run(["dig", "+short", "-q", checked(f"{host}."), "-t", checked_type(rtype)],
                          capture_output=True, text=True, timeout=TOOL_TIMEOUT, check=False)
    return [line for line in done.stdout.split() if line and not NAME.fullmatch(line)]


def git(root: Path, *args: str) -> str:
    try:
        done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)
    except OSError:
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def slug(root: Path) -> str:
    """OWNER/NAME of the GitHub repository origin points at, or ""."""
    import re  # noqa: PLC0415
    m = re.search(r"github\.com[:/]([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?$", git(root, "remote", "get-url", "origin"))
    return m.group(1) if m else ""


def zones_of(config: dict[str, Any], zones_file: Path | list[Path] | None) -> dict[str, Any] | None:
    """The hosting block's zones: this repository's, and each --zones's (one per owner
    whose zones the units' hosts are in)."""
    out: dict[str, Any] = {}
    found = False
    files = [] if zones_file is None else [zones_file] if isinstance(zones_file, Path) else list(zones_file)
    for given in [config] + [json.loads(f.read_text(encoding="utf-8")) for f in files]:
        hosting = given.get("hosting") if isinstance(given, dict) else None
        if isinstance(hosting, dict) and isinstance(hosting.get("zones"), dict):
            out |= hosting["zones"]
            found = True
    return out if found else None


def load(root: Path, config: dict[str, Any] | None = None, ctx: Context | None = None,
         namespace: str | None = None, types: dict[str, NeedType] | None = None, unit: str | None = None) -> Plan:
    """The needs of a unit of `root`'s deploy block (the top level's by
    default), with those the rendered manifests imply when they render, in
    walk order; `problems` when the block is not sound."""
    from . import k8s  # noqa: PLC0415
    from .implied import build  # noqa: PLC0415
    from .order import cycle_problems, topological  # noqa: PLC0415
    from .registry import types as registered  # noqa: PLC0415
    from .schema import problems  # noqa: PLC0415
    if config is None:
        from .config import read_config  # noqa: PLC0415
        config = read_config(root)
    types = types or registered()
    if BLOCK not in config:
        return Plan(root, config, "", {}, [], [f"{BLOCK}: pubrules.json has no deploy block"])
    from .units import unit_block  # noqa: PLC0415
    if bad := problems(config, root, types):
        return Plan(root, config, "", {}, [], bad)
    unit = unit or config[BLOCK]["namespace"]
    block = unit_block(config[BLOCK], unit)
    ns = namespace or block["namespace"]
    rendered = ctx.rendered if ctx else renderer(root, block.get("overlay", DEFAULT_OVERLAY))
    try:
        found = k8s.collect(k8s.documents(rendered()), ns)
    except (Stop, ValueError, yaml.YAMLError):
        found = None  # k8s.secrets-declared says why
    needs, bad = build(config, types, root=root, namespace=ns, found=found, unit=unit)
    bad = bad or cycle_problems(needs, types)
    return Plan(root, config, ns, needs, [] if bad else topological(needs, types), bad, unit)


def check(plan: Plan, ctx: Context, types: dict[str, NeedType] | None = None) -> Journal:
    """Walk the plan's needs."""
    from .registry import types as registered  # noqa: PLC0415
    from .walk import walk  # noqa: PLC0415
    from . import __version__  # noqa: PLC0415
    service = {"repository": ctx.slug, "namespace": plan.namespace, "unit": plan.unit or plan.namespace,
               "commit": git(plan.root, "rev-parse", "HEAD"), "pubdeploy": __version__}
    # PUBRULES_WALK_BY: who a host that walks for others (the convergence engine) says asked.
    by = ctx.env.get("PUBRULES_WALK_BY") or ctx.env.get("GITHUB_ACTOR") or git(plan.root, "config", "user.email")
    origin = "actions" if ctx.env.get("GITHUB_ACTIONS") == "true" else (
        "plane" if ctx.env.get("PUBRULES_PLANE") else "laptop")
    return walk(plan.needs, types or registered(), ctx, service, by=by, origin=origin)


def context(root: Path, config: dict[str, Any], offline: bool, kubectl_command: str | None = None,
            zones_file: Path | list[Path] | None = None, namespace: str | None = None, server: str | None = None,
            unit: str | None = None) -> Context:
    """The context `pubdeploy walk` runs a unit in: the real tools."""
    from .github import gh, gh_set as send  # noqa: PLC0415
    from .channels import channels  # noqa: PLC0415
    from .units import unit_block  # noqa: PLC0415
    unit = unit or config[BLOCK]["namespace"]
    block = unit_block(config[BLOCK], unit)
    ns = namespace or block["namespace"]
    reach = channels(kubectl_command, server, os.environ, ns)
    if reach.connection is not None and not offline:
        reach.connection.open()  # a failure shows in the first check that uses it
    return Context(root=root, config=config, block=block, namespace=ns, kubectl=reach.kubectl,
                   server=reach.server, channel=reach.name, gh=gh, send=send, http_get=http_get, env=os.environ,
                   now=lambda: datetime.now(UTC), rendered=renderer(root, block.get("overlay", DEFAULT_OVERLAY)),
                   offline=offline, slug=slug(root), zones=zones_of(config, zones_file), resolve=resolve, unit=unit)


def offline_lines(root: Path, config: dict[str, Any], ctx: Context | None = None) -> tuple[list[str], bool]:
    """For `pubrules sync`: what is wrong with the deploy block, or the offline
    walk's needs that are not ready, and whether that fails --check. An
    offline need that could not be checked (no kustomize, no hosting block)
    is said, and fails nothing."""
    from .registry import load as registry  # noqa: PLC0415
    loaded = registry()
    lines = [f"pubdeploy: warning: {w}" for w in loaded.warnings]
    from .units import names, problems as unit_problems  # noqa: PLC0415
    plan = load(root, config, ctx or context(root, config, offline=True), types=loaded.types)
    if plan.problems:
        return lines + [f"pubdeploy: {p}" for p in plan.problems], True
    bad = unit_problems(root, config[BLOCK])
    lines += [f"pubdeploy: {p}" for p in bad]
    failed = bool(bad)
    entries = []
    for unit in names(config[BLOCK]):
        given = ctx or context(root, config, offline=True, unit=unit)
        plan = load(root, config, given, types=loaded.types, unit=unit)
        if plan.problems:
            return lines + [f"pubdeploy: {p}" for p in plan.problems], True
        from . import machine  # noqa: PLC0415
        run = machine.problems(unit_block(config, unit), machine_needs(plan, loaded.types))
        lines += [f"pubdeploy: {p}" for p in run]
        failed = failed or bool(run)
        entries += check(plan, given, loaded.types).entries
    for need, result in entries:
        if not loaded.types[need.type].offline or result.state == "ready":
            continue
        failed = failed or result.state != "unknown"
        said = "not checked" if result.state == "unknown" else result.state
        lines.append(f"pubdeploy: deploy: {said}, {need.id}: {result.summary}")
        lines += [f"pubdeploy:   {d}" for d in result.details]
        if result.fix:
            lines.append(f"pubdeploy:   {result.fix}")
    return lines, failed


def ask(prompt: str) -> str:
    """A typed answer, the prompt on standard error, so --json's output is the document alone."""
    print(prompt, end="", file=sys.stderr, flush=True)
    return sys.stdin.readline().strip()


# The entry-point group of the hooks a walk calls before it fulfils, such as
# pubsec's, which asks for the Bitwarden write token and gives the walk its
# writer: pubrules holds no write token itself.
WALK_HOOKS = "sustenaut.walk"


def prepare(ctx: Context, plan: list[tuple[str, str]], terminal: bool, points: Any = None) -> None:
    """Call each hook's prepare(ctx, plan, terminal), printing the line it
    returns. A hook that fails is said, by its name and the error's type
    alone, and the walk goes on without what it would have given."""
    from importlib.metadata import entry_points  # noqa: PLC0415
    for point in sorted(entry_points(group=WALK_HOOKS) if points is None else points, key=lambda p: p.name):
        try:
            said = point.load()(ctx, plan, terminal)
        except Exception as e:  # noqa: BLE001 - a hook's failure is said, not fatal, and holds no value
            print(f"pubdeploy: deploy: the {WALK_HOOKS} hook {point.name} failed ({type(e).__name__})", file=sys.stderr)
            continue
        if isinstance(said, str) and said:
            print(said, file=sys.stderr)


def machine_needs(plan: Plan, types: dict[str, NeedType]) -> list[dict[str, Any]]:
    """The plan's needs as machine.compile takes them: id, type, grade, the needs each waits
    for, its fulfil budget, how a Stop treats it, and its params (for shared resources)."""
    from .order import edges  # noqa: PLC0415
    from .walk import fulfil_budget, grade_of  # noqa: PLC0415
    waits = edges(plan.needs, types)
    out = []
    for i, need in plan.needs.items():
        kind = types[need.type]
        out.append({"id": i, "type": need.type, "grade": grade_of(kind, need), "after": sorted(waits[i]),
                    "seconds": fulfil_budget(kind), "serial": bool(getattr(kind, "serial", False)),
                    "stop": getattr(kind, "stop", "signal"), "stop_warning": getattr(kind, "stop_warning", ""),
                    "params": need.params})
    return out


def narrow(plan: Plan, types: dict[str, NeedType], config: dict[str, Any], unit: str | None,
           only: list[str]) -> tuple[Plan, set[str]] | str:
    """The plan walk --need checks: the named needs and every need they wait for, by the
    walk's order and the run's after-edges (checked, never fulfilled), and the needs they
    wait for directly, which must be ready. Or why it cannot be walked."""
    from dataclasses import replace  # noqa: PLC0415
    from . import machine  # noqa: PLC0415
    unknown = sorted(set(only) - set(plan.needs))
    if unknown:
        return f"--need {', '.join(unknown)} is no need of this unit; it has {', '.join(sorted(plan.needs))}"
    needs = machine_needs(plan, types)
    after = machine.generated_after(needs)
    section = unit_block(config, unit).get("run") or {}
    for name, entry in (section.get("needs") or {}).items() if isinstance(section, dict) else ():
        if name in after and isinstance(entry, dict):
            after[name] |= {a for a in entry.get("after", []) if a in after}
    direct = set().union(*(after[i] for i in only)) - set(only)
    keep, todo = set(only), list(only)
    while todo:
        for a in after[todo.pop()]:
            if a not in keep:
                keep.add(a)
                todo.append(a)
    sub = {i: n for i, n in plan.needs.items() if i in keep}
    return replace(plan, needs=sub, order=[i for i in plan.order if i in keep]), direct


def unit_block(config: dict[str, Any], unit: str | None) -> dict[str, Any]:
    """The deploy block as the unit sees it (its run section included)."""
    from .units import unit_block as block_of  # noqa: PLC0415
    block = config[BLOCK]
    return block_of(block, unit) if unit and isinstance(block, dict) and "namespace" in block else block


def run_machine(root: Path, unit: str | None, mode: str | None, modes: dict[str, str]) -> int:
    """`pubdeploy machine`: the unit's machine, as JSON, from pubrules.json alone."""
    from . import machine  # noqa: PLC0415
    from .config import read_config  # noqa: PLC0415
    from .registry import load as registry  # noqa: PLC0415
    from .units import names  # noqa: PLC0415
    config = read_config(root)
    if BLOCK not in config:
        print(f"pubdeploy: {BLOCK}: pubrules.json has no deploy block", file=sys.stderr)
        return 2
    units = names(config[BLOCK]) if isinstance(config[BLOCK], dict) and "namespace" in config[BLOCK] else [None]
    if unit is None and len(units) > 1:
        print(f"pubdeploy: deploy: give --unit, one of {', '.join(map(str, units))}", file=sys.stderr)
        return 2
    unit = unit if unit is not None else units[0]
    if unit not in units:
        print(f"pubdeploy: deploy: --unit {unit} is no unit of the deploy block; it has {', '.join(map(str, units))}",
              file=sys.stderr)
        return 2
    loaded = registry()
    ctx = context(root, config, True, unit=unit)
    plan = load(root, config, ctx, None, loaded.types, unit=unit)
    if plan.problems:
        for problem in plan.problems:
            print(f"pubdeploy: {problem}", file=sys.stderr)
        return 2
    needs = machine_needs(plan, loaded.types)
    section = unit_block(config, unit).get("run")
    if mode:
        section = {**(section or machine.default_section(needs, mode)), "default_mode": mode}
        if "needs" in section:
            section["needs"] = {k: {**v, "mode": mode} for k, v in section["needs"].items()}
    try:
        compiled = machine.compile(needs, section, modes)
    except ValueError as e:
        print(f"pubdeploy: deploy: {e}", file=sys.stderr)
        return 2
    print(json.dumps(compiled, indent=2))
    return 0


def run_walk(root: Path, offline: bool, as_json: bool, kubectl_command: str | None, zones: Path | list[Path] | None,
             namespace: str | None, fulfil: bool = False, unit: str | None = None, server: str | None = None,
             yes: bool = False, journal_url: str | None = None, tolerate_unknown: bool = False,
             only: list[str] | None = None, budget_seconds: float | None = None) -> int:
    from .config import read_config  # noqa: PLC0415
    from .registry import load as registry  # noqa: PLC0415
    from .units import names  # noqa: PLC0415
    from .walk import counted, fulfil as act, lines, outcomes, planned, unable, wants_token  # noqa: PLC0415
    config = read_config(root)
    loaded = registry()
    for warning in loaded.warnings:
        print(f"pubdeploy: warning: {warning}", file=sys.stderr)
    if BLOCK not in config:
        print(f"pubdeploy: {BLOCK}: pubrules.json has no deploy block", file=sys.stderr)
        return 2
    if fulfil and offline:
        print("pubdeploy: deploy: --fulfil does not run --offline", file=sys.stderr)
        return 2
    units = names(config[BLOCK]) if isinstance(config[BLOCK], dict) and "namespace" in config[BLOCK] else [None]
    if unit is not None and unit not in units:
        print(f"pubdeploy: deploy: --unit {unit} is no unit of the deploy block; it has {', '.join(map(str, units))}",
              file=sys.stderr)
        return 2
    walks = []
    for name in [unit] if unit else units:
        try:
            ctx = context(root, config, offline, kubectl_command, zones, namespace, server=server, unit=name)
        except (OSError, ValueError) as e:
            print(f"pubdeploy: deploy: --zones {zones}: {type(e).__name__}", file=sys.stderr)
            return 2
        plan = load(root, config, ctx, namespace, loaded.types, unit=name)
        if plan.problems:
            for problem in plan.problems:
                print(f"pubdeploy: {problem}", file=sys.stderr)
            return 2
        ctx.budget_cap = budget_seconds
        if only:
            narrowed = narrow(plan, loaded.types, config, name, only)
            if isinstance(narrowed, str):
                print(f"pubdeploy: deploy: {narrowed}", file=sys.stderr)
                return 2
            plan, waited = narrowed
            journal = check(plan, ctx, loaded.types)
            late = sorted(i for i, r in ((n.id, r) for n, r in journal.entries) if i in waited and r.state != "ready")
            if late:
                print(f"pubdeploy: deploy: --need {', '.join(only)} waits for {', '.join(late)}, which "
                      f"{'is' if len(late) == 1 else 'are'} not ready: walk those first", file=sys.stderr)
                return 2
            walks.append((ctx, journal))
            continue
        walks.append((ctx, check(plan, ctx, loaded.types)))
    if fulfil:
        env = walks[0][0].env
        terminal = sys.stdin.isatty() and env.get("GITHUB_ACTIONS") != "true"
        # Without a terminal, a token file the hook reads (pubsec's, for the engine's Fulfil).
        token_coming = terminal or bool(env.get("PUBSEC_WRITE_TOKEN_FILE"))
        # With --need, only the named needs are ever fulfilled: the needs they wait for are checked.
        acts = [(ctx, [(i, line) for i, line in planned(journal, loaded.types, ctx, token_coming=token_coming)
                       if not only or i in only]) for ctx, journal in walks]
        approved: set[tuple[str, str]] = set()
        declined = False
        if any(plan for _, plan in acts):
            print("deploy: the walk will:", file=sys.stderr)
            for ctx, plan in acts:
                for _, line in plan:
                    print(f"  {ctx.unit}: {line}" if len(walks) > 1 else f"  {line}", file=sys.stderr)
            if yes or ask('Type "yes" to do it: ') == "yes":
                approved = {(ctx.unit, i) for ctx, plan in acts for i, _ in plan}
            else:
                declined = True
                print("deploy: nothing was fulfilled", file=sys.stderr)
        if approved and token_coming:
            for ctx, plan in acts:
                if wants_token(plan, loaded.types, ctx):
                    prepare(ctx, plan, terminal)
        for ctx, journal in walks:
            unable(journal, loaded.types, ctx, declined)
            act(journal, loaded.types, ctx, {i for u, i in approved if u == ctx.unit})
        if approved:
            # What it did, on stderr too: with --json (the engine's Fulfil) the journal is stdout's.
            print("deploy: the walk did:", file=sys.stderr)
            for ctx, journal in walks:
                said = outcomes(journal, {i for u, i in approved if u == ctx.unit})
                if said and len(walks) > 1:
                    print(f"  unit {ctx.unit}:", file=sys.stderr)
                for line in said:
                    print(line, file=sys.stderr)
    if only:  # only the named needs are said and journaled
        for _, journal in walks:
            journal.entries = [(n, r) for n, r in journal.entries if n.id in only]
    documents = [journal.document() for _, journal in walks]
    if as_json:
        print(json.dumps(documents[0] if len(documents) == 1 else documents, indent=2))
    else:
        for k, (ctx, journal) in enumerate(walks):
            if len(walks) > 1:
                print(("\n" if k else "") + f"unit {ctx.unit}:")
            print("\n".join(lines(journal)))
    url = journal_url or walks[0][0].env.get("PUBRULES_JOURNAL_URL")
    if url:
        from .store import write  # noqa: PLC0415
        for document in documents:
            print(write(url, document, walks[0][0].env), file=sys.stderr)
    passing = ("ready", "unknown") if tolerate_unknown else ("ready",)
    ready = all(r.state in passing for _, journal in walks for _, r in counted(journal, loaded.types, offline))
    return 0 if ready else 1


def run_check(root: Path, offline: bool, as_json: bool, kubectl_command: str | None, zones: Path | list[Path] | None,
              namespace: str | None, **given: Any) -> int:
    return run_walk(root, offline, as_json, kubectl_command, zones, namespace, **given)


def run_types() -> int:
    from .registry import load as registry  # noqa: PLC0415
    from .schema import COMMON, listed  # noqa: PLC0415
    loaded = registry()
    for warning in loaded.warnings:
        print(f"pubdeploy: warning: {warning}", file=sys.stderr)
    from .walk import fulfil_budget  # noqa: PLC0415
    rows = [("type", "grade", "budget", "offline", "from", "fulfil", "keys")]
    for name in sorted(loaded.types):
        kind = loaded.types[name]
        required = set(kind.schema.get("required", []))
        keys = [f"{k}{'' if k in required else '?'}" for k in kind.schema.get("properties", {})]
        rows.append((name, kind.grade, f"{kind.budget:g} s", "yes" if kind.offline else "no",
                     loaded.origin[name], f"{fulfil_budget(kind):g} s", ", ".join(keys) or "-"))
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]) - 1)]
    for row in rows:
        print("  ".join(cell.ljust(w) for cell, w in zip(row, widths)) + "  " + row[-1])
    print(f"{len(loaded.types)} types; every need also takes {listed(list(COMMON))}, and one with a secret "
          f"fills that Kubernetes Secret, a k8s.secret the walk adds")
    return 0
