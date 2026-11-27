"""k8s.namespace, k8s.secrets-declared, k8s.manifests, k8s.cronjob, k8s.job-once and k8s.jwks:
what the cluster must hold, read through kubectl, and what the rendered
manifests read, which needs no cluster. They use pubdeploy.k8s, which needs
nothing of this package's. k8s.secret, which reads a Secret's values and
makes one from Bitwarden's, is pubsec's.

A fulfil writes through the kubectl channel or runs on the server, so each
needs the admin channel or the plane; k8s.namespace's, which runs sustenaut-app
on the server, the admin channel alone (on the plane it stays a laptop step until
the deploy channel no longer needs the node's kubeconfig)."""

from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from .. import k8s
from ..executor_secret import ACCOUNT as EXECUTOR
from ..model import Context, Need, Result, Stop
from . import Base, failed, kubectl_json, kubectl_refused, last_success, not_found, run_job, schema


class Namespace(Base):
    """The namespace, with the deploy service account and its role, as the
    server's sustenaut-app program makes them."""
    type = "k8s.namespace"
    grade = "auto"
    # Four kubectl calls: over the admin channel's kept connection about 0.35 s
    # each, as measured to the k3s server over the tailnet.
    budget = 4.0
    fulfil_budget = 60.0
    singleton = True
    needs_of_context = ("server",)

    def action(self, need: Need, ctx: Context) -> str:
        return f"make namespace {need.name} on the server: sustenaut-app {need.name}"

    def fulfil(self, need: Need, ctx: Context) -> Result:
        ran = ctx.server(["sustenaut-app", need.name], None)
        if ran.returncode != 0:
            return failed(f"sustenaut-app {need.name} failed on the server", ran)
        return Result("ready", f"made namespace {need.name}, with the deploy service account and its role")

    def check(self, need: Need, ctx: Context) -> Result:
        ns = need.name
        server = ctx.env.get("SUSTENAUT_SERVER", "<server>")
        fix = f"ssh root@{server} sustenaut-app {ns}"
        if ctx.channel == "deploy":
            # The deploy identity may read neither namespaces nor roles.
            return Result("unknown", f"namespace {ns} is judged over the admin channel only",
                          fix="run the walk with --server HOST, the admin channel, or from the plane")
        _, ran = kubectl_json(ctx, "get", "namespace", ns)
        if ran.returncode != 0:
            if not_found(ran):
                return Result("missing", f"namespace {ns} is not there", fix=fix)
            return kubectl_refused(ran, ns, "namespaces")
        missing = []
        for kind in ("serviceaccount", "role", "rolebinding"):
            _, ran = kubectl_json(ctx, "-n", ns, "get", kind, "deploy")
            if ran.returncode != 0 and not not_found(ran):
                return kubectl_refused(ran, ns, f"{kind}s")
            if ran.returncode != 0:
                missing.append(f"{kind} deploy")
        if ctx.channel == "admin":
            # The server's deploy command refuses an app without the deploy user's kubeconfig,
            # which sustenaut-app writes last: the cluster's objects alone are not enough.
            ran = ctx.server(["test", "-f", f"/home/deploy/.kube/{ns}"], None)
            if ran.returncode != 0:
                missing.append(f"deploy kubeconfig (/home/deploy/.kube/{ns} on the server)")
        if missing:
            return Result("missing", f"namespace {ns} has no {', '.join(missing)}", fix=fix)
        return Result("ready", f"namespace {ns} is there, with the deploy service account and its role")


class SecretsDeclared(Base):
    """Every Secret the rendered manifests read is one a need fills, and every
    Secret a need fills is read."""
    type = "k8s.secrets-declared"
    budget = 1.0
    offline = True
    singleton = True

    def check(self, need: Need, ctx: Context) -> Result:
        from ..implied import declarers  # noqa: PLC0415
        from ..registry import types  # noqa: PLC0415
        try:
            found = k8s.collect(k8s.documents(ctx.rendered()), ctx.namespace)
        except Stop as stop:
            if stop.missing_tool:
                return Result("unknown", "the overlay could not be rendered", fix=str(stop))
            return Result("drift", "the overlay does not render", fix=str(stop))
        except (ValueError, yaml.YAMLError) as e:
            return Result("drift", "the rendered manifests are not YAML", fix=f"see what the overlay renders "
                                                                             f"({type(e).__name__})")
        declared = declarers(ctx.block, ctx.types or types(), ctx.namespace)
        held = {name for ns, name in found.held if ns == ctx.namespace}
        reads: dict[str, list[k8s.Need]] = {}
        for n in found.needs:
            if n.namespace == ctx.namespace:
                reads.setdefault(n.secret, []).append(n)
        lines = list(found.problems)
        for name, refs in sorted(reads.items()):
            required = [r for r in refs if not r.optional]
            if name in held or not required:
                continue
            fillers = declared.get(name)
            if not fillers:
                lines.append(f"Secret {name} is read by {', '.join(r.where for r in required)}, and no need "
                             f"says where it comes from: add it to deploy.needs, or a need's secret")
                continue
            if any(keys is None for _, keys in fillers):
                continue
            provided = {k for _, keys in fillers for k in keys or []}
            for r in required:
                for key in r.keys:
                    if key not in provided:
                        lines.append(f"Secret {name} key {key} is read by {r.where}, and "
                                     f"{', '.join(i for i, _ in fillers)} provides only {', '.join(sorted(provided))}")
        for name, fillers in sorted(declared.items()):
            if name not in reads and name != EXECUTOR:  # the live runs' Job reads that one, not the manifests'
                lines.append(f"Secret {name} is declared by {', '.join(i for i, _ in fillers)} but nothing reads it")
        count = len([n for n, refs in reads.items() if n not in held and any(not r.optional for r in refs)])
        left = leftovers(ctx, set(reads) | set(declared) | held)
        lines += [f"Secret {name} is in the cluster, and nothing reads or declares it: "
                  f"kubectl -n {ctx.namespace} delete secret {name}" for name in left]
        if lines:
            return Result("drift", f"the manifests and the needs disagree about {len(lines)} "
                                   f"Secret{'s' * (len(lines) != 1)}", details=lines,
                          fix="make deploy.needs say where each Secret the manifests read comes from, "
                              "drop what nothing reads, and delete a Secret left in the cluster")
        return Result("ready", f"the manifests read {count} Secret{'s' * (count != 1)}, "
                               f"and a need says where each comes from")


def leftovers(ctx: Context, known: set[str]) -> list[str]:
    """The Opaque Secrets in the namespace that nothing reads or declares: one a need
    filled before the need went, say a key's once its service reaches Google without
    one. None when the walk is offline or kubectl may not list them (the check stands
    on the manifests alone then). A Secret another object owns goes with its owner, so
    it is no leftover: a live run's token, which its Job owns."""
    if ctx.offline or ctx.channel == "deploy":
        return []
    # Names and types alone: no Secret's data reaches the walk, nor crosses the admin channel.
    ran = ctx.kubectl(["-n", ctx.namespace, "get", "secrets", "--no-headers",
                       "-o", "custom-columns=NAME:.metadata.name,TYPE:.type,OWNER:.metadata.ownerReferences[0].kind"])
    if ran.returncode != 0:
        return []
    rows = [line.split() for line in ran.stdout.splitlines()]
    return sorted(row[0] for row in rows if len(row) == 3 and row[1] == "Opaque" and row[2] == "<none>"
                  and row[0] not in known)


class Manifests(Base):
    """A manifest file applied by hand, such as an admin's: it parses, and,
    online, each object in it is in the cluster."""
    type = "k8s.manifests"
    grade = "auto"
    budget = 5.0
    fulfil_budget = 60.0
    offline = True
    needs_of_context = ("kubectl-write",)
    schema = schema({"path": {"type": "string", "pattern": r"^(?!/)(?!.*(^|/)\.\.(/|$))[A-Za-z0-9_./-]+\.ya?ml$",
                              "x-phrase": "must be a YAML file in the repository"}}, ("path",))

    def default_name(self, params: dict[str, Any]) -> str | None:
        return params.get("path")

    def action(self, need: Need, ctx: Context) -> str:
        return f"kubectl apply -f {need.params['path']}"

    def fulfil(self, need: Need, ctx: Context) -> Result:
        path = need.params["path"]
        try:
            text = (Path(ctx.root) / path).read_bytes()
        except OSError as e:
            return Result("missing", f"{path} cannot be read", fix=type(e).__name__)
        try:
            docs = k8s.documents(text.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, SystemExit, yaml.YAMLError) as e:
            return Result("drift", f"{path} cannot be read as manifests", fix=type(e).__name__)
        # An object that names its namespace is applied there, the rest in the unit's:
        # kubectl refuses -n NS for an object of another namespace.
        groups: dict[str, list[Any]] = {}
        for doc in docs:
            groups.setdefault((doc.get("metadata") or {}).get("namespace") or ctx.namespace, []).append(doc)
        applied = 0
        for ns, group in groups.items():
            ran = ctx.kubectl(["-n", ns, "apply", "--server-side", "--force-conflicts", "-f", "-"],
                              input=yaml.safe_dump_all(group, sort_keys=False).encode())
            if ran.returncode != 0:
                return failed(f"kubectl apply -f {path} failed", ran)
            applied += len(ran.stdout.splitlines())
        return Result("ready", f"applied {path}: {applied} object{'s' * (applied != 1)}")

    def files(self, params: dict[str, Any]) -> list[str]:
        return [params["path"]] if isinstance(params.get("path"), str) else []

    def check(self, need: Need, ctx: Context) -> Result:
        path = need.params["path"]
        try:
            text = (Path(ctx.root) / path).read_text(encoding="utf-8")
            docs = k8s.documents(text)
        except (OSError, ValueError, SystemExit, yaml.YAMLError) as e:
            return Result("drift", f"{path} cannot be read as manifests",
                          fix=f"make {path} YAML that kubectl applies ({type(e).__name__})")
        if not docs:
            return Result("drift", f"{path} holds no object", fix=f"put the objects to apply in {path}")
        objects = [(str(d.get("kind")), str((d.get("metadata") or {}).get("name")),
                    (d.get("metadata") or {}).get("namespace") or ctx.namespace) for d in docs]
        if ctx.offline:
            return Result("ready", f"{path} holds {len(objects)} object{'s' * (len(objects) != 1)}")
        missing = []
        for kind, name, ns in objects:
            ran = ctx.kubectl(["-n", ns, "get", f"{kind.lower()}/{name}", "-o", "name"])
            if ran.returncode != 0 and not not_found(ran):
                return kubectl_refused(ran, ns, f"{kind} objects")
            if ran.returncode != 0:
                missing.append(f"{kind}/{name}")
        if missing:
            return Result("missing", f"{', '.join(missing)} from {path} {'is' if len(missing) == 1 else 'are'} "
                                     f"not in {ctx.namespace}", fix=f"kubectl apply -f {path}, as an admin")
        # There, but as the file says? A server-side dry run, authorised as the apply would be.
        groups: dict[str, list[Any]] = {}
        for doc in docs:
            groups.setdefault((doc.get("metadata") or {}).get("namespace") or ctx.namespace, []).append(doc)
        for ns, group in groups.items():
            # --force-conflicts: objects applied client-side have their fields owned by kubectl's
            # client-side apply; a dry run takes them over in its answer and writes nothing.
            ran = ctx.kubectl(["-n", ns, "diff", "--server-side", "--force-conflicts", "-f", "-"],
                              input=yaml.safe_dump_all(group, sort_keys=False).encode())
            if ran.returncode == 1:
                changed = sorted({line.split()[1].rsplit("/", 1)[0] for line in ran.stdout.splitlines()
                                  if line.startswith("diff -u") and len(line.split()) > 1})
                return Result("drift", f"{path} differs from what is in the cluster"
                                       + (f" ({len(changed)} object{'s' * (len(changed) != 1)})" if changed else ""),
                              fix=f"kubectl apply --server-side --force-conflicts -f {path}, as an admin")
            if ran.returncode != 0:
                said = (ran.stderr.strip().splitlines() or [f"exit {ran.returncode}"])[-1][:200]
                return Result("unknown", f"the objects in {path} are there; whether they match it could not be "
                                         f"compared: {said}", fix="run the walk over the admin channel")
        return Result("ready", f"the {len(objects)} object{'s' * (len(objects) != 1)} in {path} are applied, "
                               "as the file says")


DURATION = {"type": "string", "pattern": r"^[1-9][0-9]*[mhd]$", "x-phrase": "must be a duration: minutes, hours "
                                                                            "or days, such as 90m, 36h or 2d"}
UNITS = {"m": timedelta(minutes=1), "h": timedelta(hours=1), "d": timedelta(days=1)}


def duration(text: str) -> timedelta:
    return int(text[:-1]) * UNITS[text[-1]]


def interval(schedule: str) -> timedelta | None:
    """How often a schedule of a common form runs, or None for another."""
    named = {"@hourly": timedelta(hours=1), "@daily": timedelta(days=1), "@midnight": timedelta(days=1),
             "@weekly": timedelta(days=7), "@monthly": timedelta(days=31), "@yearly": timedelta(days=366),
             "@annually": timedelta(days=366)}
    if schedule.strip() in named:
        return named[schedule.strip()]
    fields = schedule.split()
    if len(fields) != 5:
        return None
    minute, hour, day, month, weekday = fields

    def every(field: str) -> int | None:
        """1 for *, N for */N, None for anything else."""
        if field == "*":
            return 1
        m = re.fullmatch(r"\*/([1-9][0-9]*)", field)
        return int(m[1]) if m else None

    def listed(field: str) -> int | None:
        """How many fixed values a field lists: 5, or 1,2,3."""
        return len(field.split(",")) if re.fullmatch(r"[0-9]+(,[0-9]+)*", field) else None

    if (n := every(minute)) and hour == day == month == weekday == "*":
        return timedelta(minutes=n)
    if listed(minute) and month == "*":
        if (n := every(hour)) and day == weekday == "*":
            return timedelta(hours=n) / listed(minute)
        if (count := listed(hour)) and day == weekday == "*":
            return timedelta(days=1) / count
        if listed(hour) == 1 and day == "*" and (count := listed(weekday)):
            return timedelta(days=7) / count
        if listed(hour) == 1 and weekday == "*" and listed(day) == 1:
            return timedelta(days=31)
    return None


def when(text: str) -> datetime:
    return datetime.fromisoformat(str(text).replace("Z", "+00:00"))


class CronJob(Base):
    """A CronJob that succeeds as often as it runs: a service without a host."""
    type = "k8s.cronjob"
    stop = "shorten"
    grade = "auto"
    budget = 4.0
    fulfil_budget = 300.0
    needs_of_context = ("kubectl-write",)
    schema = schema({"within": DURATION})

    def action(self, need: Need, ctx: Context) -> str:
        return f"run a Job from CronJob {need.name}, and wait for it"

    def check(self, need: Need, ctx: Context) -> Result:
        ns, name = ctx.namespace, need.name
        found, ran = kubectl_json(ctx, "-n", ns, "get", "cronjob", name)
        if found is None:
            if not_found(ran):
                return Result("missing", f"CronJob {name} is not in {ns}", fixable=False,
                              fix=f"see that the overlay {ctx.block.get('overlay', 'k8s')} holds it")
            return kubectl_refused(ran, ns, "cronjobs")
        spec, status = found.get("spec") or {}, found.get("status") or {}
        given = need.params.get("within")
        schedule = str(spec.get("schedule", ""))
        within = duration(given) if given else (2 * every if (every := interval(schedule)) else None)
        if within is None:
            return Result("unknown", f"CronJob {name}'s schedule {schedule} is not one pubdeploy reads",
                          fix=f"give the need's within: how recently {name} must have succeeded, such as 36h")
        if spec.get("suspend") is True:
            return Result("drift", f"CronJob {name} is suspended", fixable=False,
                          fix=f"kubectl -n {ns} patch cronjob {name} -p '{{\"spec\":{{\"suspend\":false}}}}'")
        last, scheduled = last_success(ctx, name, status), status.get("lastScheduleTime")
        hours = f"{within.total_seconds() / 3600:g} h"
        if last and ctx.now() - when(last) <= within:
            return Result("ready", f"CronJob {name} succeeded at {last}, within {hours}")
        fix = f"pubdeploy k8s diagnose --namespace {ns}"
        if last:
            return Result("drift", f"CronJob {name} last succeeded at {last}, over {hours} ago", fix=fix)
        if scheduled:
            return Result("drift", f"CronJob {name}'s last run did not succeed", fix=fix)
        return Result("missing", f"CronJob {name} never ran",
                      fix=f"kubectl -n {ns} create job --from=cronjob/{name} {name}-now")

    def fulfil(self, need: Need, ctx: Context) -> Result:
        return run_job(ctx, need.name, self.fulfil_budget)


# A clone of the file's repository older than this may hold a pin that has since moved.
STALE_HOURS = 24


class Jwks(Base):
    """A file that pins the cluster's service-account signing keys is the
    cluster's: each key `kubectl get --raw /openid/v1/jwks` gives, and no other;
    with `keys`, the cluster publishes at least that many (two: one signs, the
    other is the fallback a swap or a lost key falls back to).
    What trusts the cluster's tokens without asking it (Google's Workload
    Identity providers, storage's principals) reads the file, so a key the
    cluster rotated fails all of them at once, and only at run time."""
    type = "k8s.jwks"
    grade = "human"
    # One kubectl call.
    budget = 4.0
    schema = schema({"file": {"type": "string", "minLength": 1,
                              "x-phrase": "must be the pinned file's path, from the repository's root"},
                     "keys": {"type": "integer", "minimum": 1, "maximum": 10,
                              "x-phrase": "must be how many signing keys the cluster publishes, 1 to 10"},
                     "repository": {"type": "string", "pattern": r"^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$",
                                    "x-phrase": "must be the OWNER/NAME of the repository the file is in"}},
                    ("file",))

    def default_name(self, params: dict[str, Any]) -> str | None:
        file = params.get("file")
        return Path(file).stem if isinstance(file, str) and file else None

    def check(self, need: Need, ctx: Context) -> Result:
        import json  # noqa: PLC0415
        file, owner = need.params["file"], need.params.get("repository")
        where = f"{owner}'s {Path(file).name}" if owner else file
        fix = (f"put the output of `kubectl get --raw /openid/v1/jwks` in {where} as jwks, and in every other "
               f"copy of it, then apply what reads them")
        path = Path(ctx.root) / file
        read = read_at(path)
        try:
            pinned = keys_of(json.loads(path.read_text(encoding="utf-8")).get("jwks"))
        except OSError:
            # A file in another repository's clone (the plane's zones repository, say): no clone, no check.
            return Result("drift", f"{where} could not be read", fixable=False, details=read,
                          fix=f"see that {owner + ' is cloned beside this repository' if owner else file + ' is there'}")
        except (ValueError, AttributeError):
            return Result("drift", f"{where} is not a JSON object with the cluster's jwks", fixable=False, fix=fix,
                          details=read)
        age = fetched_hours(path) if owner else None
        if age is not None and age > STALE_HOURS:
            return Result("unknown", f"{owner}'s clone was last fetched {age:.0f} h ago; the pin may have moved",
                          details=read, fix=f"refresh the clone of {owner}")
        result = self._against_cluster(ctx, file, where, fix, pinned, need.params.get("keys"))
        result.details[:0] = read
        return result

    def _against_cluster(self, ctx: Context, file: str, where: str, fix: str, pinned: dict, wanted: Any) -> Result:
        if ctx.channel == "deploy":
            # The server's read-only verb takes get with its own flags, and --raw is not one.
            return Result("unknown", "the cluster's signing keys are read over the admin channel or from the plane",
                          fix="run the walk with --server HOST, the admin channel, or from the plane")
        ran = ctx.kubectl(["get", "--raw", "/openid/v1/jwks"])
        if ran.returncode != 0:
            return kubectl_refused(ran, ctx.namespace, "the cluster's signing keys (/openid/v1/jwks)")
        try:
            live = keys_of(json.loads(ran.stdout))
        except (ValueError, AttributeError):
            return Result("unknown", "the cluster's /openid/v1/jwks is not a JSON key set",
                          fix="see what kubectl get --raw /openid/v1/jwks gives")
        if live == pinned and wanted is not None and len(live) < wanted:
            # One key short of the pair: a lost key would have no fallback to take over.
            return Result("drift", f"the cluster publishes {len(live)} signing key{'s' * (len(live) != 1)}, "
                                   f"not the {wanted} the need asks for", fixable=False,
                          fix="give the cluster its second signing key: shared-infra's scripts/go-live-signing-keys.sh")
        if live == pinned:
            return Result("ready", f"{where} pins the cluster's {len(live)} signing key{'s' * (len(live) != 1)}")
        details = [f"the cluster signs with {kid}, which {file} does not pin" for kid in sorted(set(live) - set(pinned))]
        details += [f"{file} pins {kid}, which the cluster no longer has" for kid in sorted(set(pinned) - set(live))]
        details += [f"{kid} differs between {file} and the cluster" for kid in sorted(set(live) & set(pinned))
                    if live[kid] != pinned[kid]]
        return Result("drift", f"{file} does not pin the cluster's signing keys", details=details,
                      fixable=False, fix=fix)


def read_at(path: Path) -> list[str]:
    """Which commit of which clone the pinned file was read at, as a detail; none outside git."""
    import subprocess  # noqa: PLC0415

    def git(*args: str) -> str:
        ran = subprocess.run(["git", "-C", str(path.parent), *args], capture_output=True, text=True,
                             timeout=10, check=False)
        return ran.stdout.strip() if ran.returncode == 0 else ""
    try:
        top, head = git("rev-parse", "--show-toplevel"), git("log", "-1", "--format=%h %cI")
        shallow = git("rev-parse", "--is-shallow-repository") == "true"
        changed = "" if shallow else git("log", "-1", "--format=%h %cI", "--", path.name)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if not top or not head:
        return []
    name, (commit, when) = Path(top).name, head.split()
    # A shallow clone (the engine's are depth 1) knows its tip alone: the file's own commit is unknown.
    said = f"read from {name}'s clone at {commit} ({when})"
    if changed:
        said += f", where {path.name} was last changed in {changed.split()[0]} ({changed.split()[1]})"
    return [said]


def fetched_hours(path: Path) -> float | None:
    """How long ago the clone the file sits in was last fetched or made (FETCH_HEAD's time, else
    HEAD's), in hours; None outside git."""
    import subprocess  # noqa: PLC0415
    import time  # noqa: PLC0415
    try:
        ran = subprocess.run(["git", "-C", str(path.parent), "rev-parse", "--git-dir"], capture_output=True,
                             text=True, timeout=10, check=False)
        if ran.returncode != 0:
            return None
        git_dir = Path(ran.stdout.strip())
        git_dir = git_dir if git_dir.is_absolute() else path.parent / git_dir
        # A fetch writes FETCH_HEAD; a clone writes none, but it, like a checkout, writes HEAD.
        for name in ("FETCH_HEAD", "HEAD"):
            if (git_dir / name).is_file():
                return (time.time() - (git_dir / name).stat().st_mtime) / 3600
        return None
    except (OSError, subprocess.TimeoutExpired):
        return None


def keys_of(jwks: Any) -> dict[str, dict[str, Any]]:
    """A JSON key set's keys by their kid; an AttributeError when it is not one."""
    found = jwks.get("keys")
    if not isinstance(found, list) or not all(isinstance(k, dict) for k in found):
        raise AttributeError("keys")
    return {str(k.get("kid", "")): k for k in found}


TIMEOUT = {"type": "string", "pattern": r"^[1-9][0-9]*[mhd]$",
           "x-phrase": "must be how long the Job may run: minutes, hours or days, such as 90m or 6h"}
JOB_NAME = {"type": "string", "pattern": r"^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$",
            "x-phrase": "must be a Job's or CronJob's name, in lower case"}
MANIFEST = {"type": "string", "pattern": r"^(?!/)(?!.*(^|/)\.\.(/|$))[A-Za-z0-9_./-]+\.ya?ml$",
            "x-phrase": "must be a YAML file in the repository holding one Job"}
ANNOTATION = "pubdeploy/need"


class JobOnce(Base):
    """A one-off Job, such as a 90-day backfill, run once: made from a CronJob's
    template (`cronjob`) or a manifest holding one Job (`manifest`), with `args`
    added to its first container's, and `timeout` as its active deadline. The Job
    stays as the record that it ran: its time-to-live is dropped. A failed one is
    made again only with `rerun: if-failed`, and then only that Job is deleted.
    The fulfil makes it and returns: the next walk sees how it went."""
    type = "k8s.job-once"
    stop = "continue"
    stop_warning = "the Job keeps running in the cluster; deleting it may leave its work half done"
    grade = "auto"
    budget = 4.0  # one or two kubectl reads
    fulfil_budget = 60.0
    needs_of_context = ("kubectl-write",)
    # One source of the two, which the check says when a need gives both or neither.
    schema = schema({"cronjob": JOB_NAME, "manifest": MANIFEST,
                     "args": {"type": "array", "items": {"type": "string", "maxLength": 200},
                              "x-phrase": "must list the arguments added to the Job's container"},
                     "timeout": TIMEOUT, "rerun": {"enum": ["never", "if-failed"]}})

    def _source(self, need: Need) -> str:
        p = need.params
        return f"CronJob {p['cronjob']}" if p.get("cronjob") else p["manifest"]

    def action(self, need: Need, ctx: Context) -> str:
        args = need.params.get("args") or []
        make = (f"create Job {need.name} in namespace {ctx.namespace} from {self._source(need)}"
                + (f" with the arguments {' '.join(args)}" if args else ""))
        found = ctx.results.get(need.id)
        if found is not None and found.state == "drift":
            return f"delete Job {need.name} in namespace {ctx.namespace} (no data is deleted), then {make}"
        return make

    def check(self, need: Need, ctx: Context) -> Result:
        ns, name = ctx.namespace, need.name
        if bool(need.params.get("cronjob")) == bool(need.params.get("manifest")):
            return Result("drift", f"k8s.job-once {name} names {'both' if need.params.get('cronjob') else 'neither'} "
                                   "of cronjob and manifest", fixable=False,
                          fix="give the need one source: cronjob, a CronJob's name, or manifest, a file with one Job")
        job, ran = kubectl_json(ctx, "-n", ns, "get", "job", name)
        if job is None and not not_found(ran):
            return kubectl_refused(ran, ns, "jobs")
        if job is None:
            return self._absent(need, ctx)
        status = job.get("status") or {}
        conditions = {c.get("type"): c.get("status") for c in status.get("conditions") or [] if isinstance(c, dict)}
        if (status.get("succeeded") or 0) >= 1 or conditions.get("Complete") == "True":
            when_ = status.get("completionTime") or ""
            return Result("ready", f"Job {name} completed{' at ' + when_ if when_ else ''}")
        if conditions.get("Failed") == "True":
            again = need.params.get("rerun") == "if-failed"
            return Result("drift", f"Job {name} failed", fixable=again,
                          fix=(f"pubdeploy k8s diagnose --namespace {ns}; walk --fulfil deletes Job {name} and makes "
                               "it again" if again else
                               f"pubdeploy k8s diagnose --namespace {ns}, then kubectl -n {ns} delete job {name} and "
                               "walk --fulfil, or give the need rerun: if-failed"))
        return Result("unknown", f"Job {name} is running", fixable=False,
                      fix=f"wait for it: kubectl -n {ns} get job {name}")

    def _absent(self, need: Need, ctx: Context) -> Result:
        ns, name, cronjob = ctx.namespace, need.name, need.params.get("cronjob")
        if cronjob:
            _, ran = kubectl_json(ctx, "-n", ns, "get", "cronjob", cronjob)
            if ran.returncode != 0 and not not_found(ran):
                return kubectl_refused(ran, ns, "cronjobs")
            if ran.returncode != 0:
                return Result("missing", f"Job {name} has not run, and CronJob {cronjob} is not in {ns} yet",
                              fixable=False, fix="deploy the service first: the Job is made from its CronJob")
        return Result("missing", f"Job {name} has not run in {ns}",
                      fix=f"./pubdeploy walk --fulfil makes it from {self._source(need)}")

    def _job(self, need: Need, ctx: Context) -> dict[str, Any] | Result:
        """The Job to make, or why it cannot be."""
        ns, p = ctx.namespace, need.params
        if p.get("cronjob"):
            found, ran = kubectl_json(ctx, "-n", ns, "get", "cronjob", p["cronjob"])
            if found is None:
                return failed(f"CronJob {p['cronjob']} could not be read", ran)
            spec = copy.deepcopy(((found.get("spec") or {}).get("jobTemplate") or {}).get("spec") or {})
        else:
            try:
                docs = k8s.documents((Path(ctx.root) / p["manifest"]).read_text(encoding="utf-8"))
            except (OSError, ValueError, SystemExit, yaml.YAMLError) as e:
                return Result("drift", f"{p['manifest']} cannot be read as a Job", fix=type(e).__name__)
            jobs = [d for d in docs if d.get("kind") == "Job"]
            if len(jobs) != 1:
                return Result("drift", f"{p['manifest']} holds {len(jobs)} Jobs, not one",
                              fix=f"put the one Job to run in {p['manifest']}")
            spec = copy.deepcopy(jobs[0].get("spec") or {})
        containers = ((spec.get("template") or {}).get("spec") or {}).get("containers") or []
        if not containers:
            return Result("drift", f"{self._source(need)} gives a Job with no container",
                          fix=f"see {self._source(need)}")
        if p.get("args"):
            containers[0]["args"] = [*(containers[0].get("args") or []), *p["args"]]
        spec.pop("ttlSecondsAfterFinished", None)  # the Job stays as the record that it ran
        if p.get("timeout"):
            spec["activeDeadlineSeconds"] = int(duration(p["timeout"]).total_seconds())
        return {"apiVersion": "batch/v1", "kind": "Job",
                "metadata": {"name": need.name, "namespace": ns, "annotations": {ANNOTATION: need.id}},
                "spec": spec}

    def fulfil(self, need: Need, ctx: Context) -> Result:
        ns, name = ctx.namespace, need.name
        job = self._job(need, ctx)
        if isinstance(job, Result):
            return job
        found = ctx.results.get(need.id)
        details = []
        if found is not None and found.state == "drift":
            if need.params.get("rerun") != "if-failed":
                return Result("drift", f"Job {name} failed, and the need does not run it again", fixable=False,
                              fix=found.fix)
            ran = ctx.kubectl(["-n", ns, "delete", "job", name, "--wait=true"])
            if ran.returncode != 0 and not not_found(ran):
                return failed(f"Job {name} could not be deleted", ran)
            details.append(f"deleted Job {name}, which had failed")
        ran = ctx.kubectl(["-n", ns, "create", "-f", "-"], input=json.dumps(job).encode())
        if ran.returncode != 0:
            return failed(f"Job {name} could not be made", ran)
        return Result("ready", f"made Job {name} from {self._source(need)}: the next walk sees how it went",
                      details=details)
