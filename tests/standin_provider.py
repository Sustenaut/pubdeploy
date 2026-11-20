"""A stand-in provider: the need types pubdeploy's walk implies but does not
offer (registry.PUBSEC_TYPES), and a `sustenaut.walk` hook, so this suite
walks the sample service without pubsec installed.

It is built from pubdeploy.contract alone, as a real provider is: each type
has the contract's attributes, uses the Context by the contract's names, and
returns pubdeploy.contract's Result. It is not pubsec: it judges as little as
the walk's scenarios need (a value there or not, a Secret's keys, a setting
on GitHub), and pubsec's own suite tests what pubsec's types do. Its values
hold the canary, as every fake's do, so this suite's canary stays as strict.

The world loads it through `World.providers()` (conftest.py's SuiteWorld).
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import secrets as random
from importlib.metadata import Distribution, EntryPoint
from pathlib import Path
from typing import Any

from pubdeploy.contract import Result

# The world of the running scenario, for the hook and for what a fulfil generates.
WORLD: Any = None
MARKERS = ("PUBRULES_SECRETS_PROJECT", "PUBKIT_SECRETS_PROJECT")
NAME = {"type": "string", "pattern": r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"}
KEY = {"type": "string", "pattern": r"^[-._a-zA-Z0-9]{1,253}$"}
SECRET = {"type": "object", "required": ["name"], "additionalProperties": False,
          "x-phrase": "must be an object with the Secret's name, and maybe key and decode",
          "properties": {"name": {"type": "string", "pattern": r"^[a-z0-9]([-a-z0-9.]{0,251}[a-z0-9])?$",
                                  "x-phrase": "must be a Secret's name, in lower case"},
                         "key": KEY, "decode": {"enum": ["base64"]}}}
GITHUB_NAME = {"type": "string", "pattern": r"^(?!GITHUB_)[A-Z_][A-Z0-9_]*$"}


def schema(properties: dict[str, Any], required: tuple[str, ...] = ()) -> dict[str, Any]:
    out: dict[str, Any] = {"type": "object", "additionalProperties": False, "properties": properties}
    if required:
        out["required"] = list(required)
    return out


def env_name(name: str) -> str:
    return name.upper().replace("-", "_").replace(".", "_")


def project(ctx: Any) -> str | None:
    return next((ctx.env[m] for m in MARKERS if ctx.env.get(m)), None)


def bitwarden(ctx: Any, name: str) -> str | None:
    """Bitwarden's value of `name`, as ./with-secrets gives it, or None."""
    return ctx.env.get(env_name(name)) if project(ctx) else None


def refused(error: Exception, what: str) -> Result:
    return Result("unknown", f"GitHub refused to show {what}", fix="sign gh in (gh auth login)") \
        if getattr(error, "status", None) in (401, 403) else Result("unknown", f"GitHub could not be asked for {what}",
                                                                    fix=str(error)[:200])


# A generated value's shapes, as the stand-in judges them: a length, a form.
def _cookie(value: bytes) -> bool:
    return len(value) in (16, 24, 32, 43)  # 43: URL-safe base64 of 32 bytes, unpadded


def _hex(value: bytes) -> bool:
    return re.fullmatch(rb"[0-9a-f]{64}", value) is not None


def _base64(value: bytes) -> bool:
    try:
        return len(base64.b64decode(value, validate=True)) == 32
    except (binascii.Error, ValueError):
        return False


SHAPES = {"oauth2-proxy-cookie": (_cookie, lambda: random.token_urlsafe(32)),
          "hex-32": (_hex, lambda: random.token_hex(32)),
          "base64-32": (_base64, lambda: base64.b64encode(random.token_bytes(32)).decode())}


class Base:
    type = ""
    schema: dict[str, Any] = schema({})
    grade = "none"
    budget = 1.0
    offline = False

    def default_name(self, params: dict[str, Any]) -> str | None:
        return None

    def depends_on(self, need: Any, needs: Any) -> list[str]:
        return []

    def check(self, need: Any, ctx: Any) -> Result:
        return Result("unknown", f"{self.type} is the stand-in's, which does not judge it")

    def fulfil(self, need: Any, ctx: Any) -> Result:
        return Result("unknown", f"{self.type} has no fulfil here")


class BitwardenSecret(Base):
    type, grade, budget = "bitwarden.secret", "human", 0.5
    schema = schema({"secret": SECRET})

    def value(self, need: Any, ctx: Any) -> bytes | None:
        if need.name in ctx.values:
            return ctx.values[need.name]
        found = bitwarden(ctx, need.name)
        return None if found is None else found.encode()

    def present(self, need: Any, ctx: Any) -> tuple[bytes | None, Result | None]:
        if need.name in ctx.values:
            return ctx.values[need.name], None
        if not (where := project(ctx)):
            return None, Result("unknown", f"{need.name} is not looked for outside ./with-secrets",
                                fix="run this through ./with-secrets, which reads the Bitwarden project")
        found = bitwarden(ctx, need.name)
        if found is None:
            return None, Result("missing", f"{need.name} is not in the Bitwarden project {where}",
                                fix=f"put {need.name} in the Bitwarden project {where}")
        return found.encode(), None

    def check(self, need: Any, ctx: Any) -> Result:
        value, result = self.present(need, ctx)
        return result or Result("ready", f"{need.name} is in Bitwarden: {len(value)} bytes")


class BitwardenGenerated(BitwardenSecret):
    type, grade, fulfil_budget = "bitwarden.generated", "auto", 60.0
    schema = schema({"secret": SECRET, "shape": {"enum": sorted(SHAPES)}}, ("shape",))

    def requires(self, need: Any) -> tuple[str, ...]:
        return ("write-token",)

    def secret_shape(self, params: dict[str, Any]) -> str | None:
        return params.get("shape")

    def action(self, need: Any, ctx: Any) -> str:
        found = ctx.results.get(need.id)
        if found is not None and found.state == "drift":
            return f"replace {need.name} (misshapen: {found.summary}) with a new {need.params['shape']}, written to Bitwarden"
        return f"generate {need.name} as {need.params['shape']}, and write it to Bitwarden"

    def check(self, need: Any, ctx: Any) -> Result:
        value, result = self.present(need, ctx)
        if result is not None:
            return result
        if not SHAPES[need.params["shape"]][0](value):
            return Result("drift", f"{need.name} is not a {need.params['shape']}: {len(value)} bytes",
                          fix=f"make {need.name} again, as {need.params['shape']}")
        return Result("ready", f"{need.name} is in Bitwarden: {len(value)} bytes, a {need.params['shape']}")

    def fulfil(self, need: Any, ctx: Any) -> Result:
        if ctx.bitwarden_writer is None:
            return Result("missing", "there is no Bitwarden write token", fix="run the walk at a terminal")
        value = SHAPES[need.params["shape"]][1]()
        if WORLD is not None:
            WORLD.values.append(value)
        try:
            ctx.bitwarden_writer.write(need.name, value, f"made by the stand-in, as {need.params['shape']}")
        except Exception as e:  # noqa: BLE001 - the writer's failure is the need's, said without a value
            return Result("missing", f"Bitwarden refused {need.name} ({type(e).__name__})",
                          fix=str(e).replace(value, "[hidden]")[:300])
        ctx.values[need.name] = value.encode()
        return Result("ready", f"generated {need.name}, {len(value)} bytes, and wrote it to Bitwarden")


class Adopt(Base):
    type = "bitwarden.adopt"
    schema = schema({"secret": SECRET})


class ServiceAccountKey(Base):
    type, budget = "gcp.service-account-key", 5.0
    schema = schema({"account": NAME, "project": NAME, "bitwarden": NAME, "secret": SECRET})


def fillers(need: Any, ctx: Any) -> list[Any]:
    return [n for n in ctx.needs.values() if (n.params.get("secret") or {}).get("name") == need.name]


def secret_data(doc: dict[str, Any]) -> dict[str, bytes]:
    out = {k: base64.b64decode(v or "") for k, v in (doc.get("data") or {}).items()}
    return out | {k: str(v).encode() for k, v in (doc.get("stringData") or {}).items()}


def kubectl_refused(ran: Any, ns: str, name: str) -> Result:
    if "forbidden" in ran.stderr.lower():
        return Result("unknown", f"kubectl may not read Secret {name} in {ns}", fix=ran.stderr.strip()[-200:])
    return Result("unknown", f"Secret {name} in {ns} could not be read", fix=ran.stderr.strip()[-200:])


class Secret(Base):
    """A Secret with its keys; made from the needs whose secret fills it."""
    type, grade, budget, fulfil_budget = "k8s.secret", "auto", 5.0, 60.0
    schema = schema({"keys": {"type": "array", "items": KEY},
                     "shapes": {"type": "object", "additionalProperties": {"enum": sorted(SHAPES)}}})

    def requires(self, need: Any) -> tuple[str, ...]:
        return ("kubectl-write",)

    def made_from(self, need: Any, ctx: Any) -> list[str]:
        return [n.id for n in fillers(need, ctx)]

    def action(self, need: Any, ctx: Any) -> str:
        sources = ", ".join(n.id for n in fillers(need, ctx))
        return f"apply Secret {need.name} in {ctx.namespace} from {sources}, and restart what reads it"

    def check(self, need: Any, ctx: Any) -> Result:
        result = self.found(need, ctx)
        made = fillers(need, ctx)
        result.fixable = bool(made) and all(callable(getattr(ctx.types.get(n.type), "value", None)) for n in made)
        return result

    def lacking(self, need: Any, keys: Any) -> Result | None:
        if lacking := [k for k in need.params.get("keys", []) if k not in keys]:
            return Result("drift", f"Secret {need.name} has no key {lacking[0]}, which need {need.id} reads",
                          fix=f"put the right value in Secret {need.name} in {need.name}")
        return None

    def found(self, need: Any, ctx: Any) -> Result:
        ns, name = ctx.namespace, need.name
        missing = Result("missing", f"Secret {name} is not in {ns}", fix=f"make it in {ns}")
        if ctx.channel == "deploy":
            ran = ctx.kubectl(["-n", ns, "secret-keys", name])
            if ran.returncode == 0:
                keys = json.loads(ran.stdout)
                return self.lacking(need, keys) or Result(
                    "ready", f"Secret {name} in {ns} has keys {', '.join(sorted(keys))}; their values are not "
                             "checked over the deploy channel")
            if ran.returncode == 2:  # a server without the verb: by name alone
                ran = ctx.kubectl(["-n", ns, "get", "secret", name, "-o", "name"])
                if ran.returncode == 0:
                    return Result("ready", f"Secret {name} is in {ns}",
                                  details=["keys not checked on this channel: the server has no secret-keys verb"])
            return missing if "not found" in ran.stderr.lower() else kubectl_refused(ran, ns, name)
        ran = ctx.kubectl(["-n", ns, "get", "secret", name, "-o", "json"])
        if ran.returncode != 0:
            return missing if "not found" in ran.stderr.lower() else kubectl_refused(ran, ns, name)
        data = secret_data(json.loads(ran.stdout))
        keys = need.params.get("keys", [])
        return self.lacking(need, data) or Result(
            "ready", f"Secret {name} in {ns}" + (f" has keys {', '.join(keys)}" if keys else " is there"))

    def fulfil(self, need: Any, ctx: Any) -> Result:
        ns, name, data, sources = ctx.namespace, need.name, {}, []
        for filler in fillers(need, ctx):
            key = (filler.params.get("secret") or {}).get("key")
            value = ctx.types[filler.type].value(filler, ctx) if key else None
            if value is None:
                return Result("missing", f"{filler.id}'s value is not in this walk", fix="run it through ./with-secrets")
            data[key] = value
            sources.append(f"Bitwarden {filler.name}" if filler.type.startswith("bitwarden.") else filler.id)
        if lacking := [k for k in need.params.get("keys", []) if k not in data]:
            return Result("missing", f"no need fills key {lacking[0]} of Secret {name}", fix="add one")
        manifest = json.dumps({"apiVersion": "v1", "kind": "Secret", "metadata": {"name": name, "namespace": ns},
                               "data": {k: base64.b64encode(v).decode() for k, v in sorted(data.items())}})
        ran = ctx.kubectl(["-n", ns, "apply", "-f", "-"], input=manifest.encode())
        if ran.returncode != 0:
            text = ran.stderr.strip()
            for value in data.values():
                text = text.replace(value.decode(errors="replace"), "[hidden]")
            return Result("missing", f"kubectl apply of Secret {name} in {ns} failed", fix=text[-300:])
        return Result("ready", f"made Secret {name} in {ns} from {', '.join(sources)}, {sum(len(v) for v in data.values())} bytes",
                      details=self.restart(ctx, name))

    def restart(self, ctx: Any, secret: str) -> list[str]:
        ran = ctx.kubectl(["-n", ctx.namespace, "get", "deployment", "-o", "json"])
        items = json.loads(ran.stdout).get("items", []) if ran.returncode == 0 else []
        out = []
        for item in items:
            if secret in json.dumps(item.get("spec", {}).get("template", {})):
                deployment = item["metadata"]["name"]
                ctx.kubectl(["-n", ctx.namespace, "rollout", "restart", f"deployment/{deployment}"])
                out.append(f"restarted Deployment/{deployment}, which reads Secret {secret}")
        return out


def gh_name(need: Any) -> str:
    return need.params.get("to") or need.name.rsplit("/", 1)[-1]


def where(slug: str, environment: str | None) -> str:
    return f"{slug}, environment {environment}" if environment else slug


def gh_path(slug: str, kind: str, name: str, environment: str | None) -> str:
    scope = f"environments/{environment}" if environment else "actions"
    return f"repos/{slug}/{scope}/{kind}s/{name}"


def send(ctx: Any, kind: str, name: str, source: str, environment: str | None) -> Result:
    value = bitwarden(ctx, source)
    if value is None:
        return Result("missing", f"{source} is not in this walk's environment", fix="run it through ./with-secrets")
    if (said := ctx.send(kind, name, ctx.slug, value, environment)) is not None:
        return Result("missing", f"gh refused {kind} {name}", fix=said.replace(value, "[hidden]")[:300])
    return Result("ready", f"set {kind} {name} in {where(ctx.slug, environment)} from Bitwarden's {source}, "
                           f"{len(value.encode())} bytes")


class GitHubSecret(Base):
    type, grade, budget, fulfil_budget, kind = "github.secret", "auto", 3.0, 30.0, "secret"
    schema = schema({"from": NAME, "to": GITHUB_NAME, "environment": NAME})

    def grade_for(self, need: Any) -> str:
        return "auto" if need.params.get("from") else "human"

    def action(self, need: Any, ctx: Any) -> str:
        return f"gh {self.kind} set {gh_name(need)} from Bitwarden's {need.params.get('from')}"

    def fulfil(self, need: Any, ctx: Any) -> Result:
        return send(ctx, self.kind, gh_name(need), need.params["from"], need.params.get("environment"))

    def read(self, need: Any, ctx: Any) -> tuple[Any, Result | None]:
        if not ctx.slug:
            return None, Result("unknown", "origin is not a GitHub repository", fix="run this in a clone of it")
        name, env = gh_name(need), need.params.get("environment")
        try:
            return ctx.gh("GET", gh_path(ctx.slug, self.kind, name, env), None) or {}, None
        except Exception as e:  # noqa: BLE001 - ctx.gh's refusal carries its status
            if getattr(e, "status", None) == 404:
                return None, Result("missing", f"{self.kind} {name} is not set in {where(ctx.slug, env)}",
                                    fix=f"gh {self.kind} set {name} -R {ctx.slug}")
            return None, refused(e, f"{self.kind} {name}")

    def check(self, need: Any, ctx: Any) -> Result:
        _found, result = self.read(need, ctx)
        return result or Result("ready", f"{self.kind} {gh_name(need)} is set in "
                                         f"{where(ctx.slug, need.params.get('environment'))}")


class GitHubVariable(GitHubSecret):
    type, kind = "github.variable", "variable"
    schema = schema({"from": NAME, "to": GITHUB_NAME, "environment": NAME, "declared": {"type": "boolean"}})

    def grade_for(self, need: Any) -> str:
        return "auto" if need.params.get("from") and not need.params.get("declared") else "propose"

    def fulfil(self, need: Any, ctx: Any) -> Result:
        if self.grade_for(need) == "auto":
            return super().fulfil(need, ctx)
        return Result("missing", f"variable {gh_name(need)} is the state file's",
                      fix=f"give {gh_name(need)} its value in the owner's state file")

    def check(self, need: Any, ctx: Any) -> Result:
        found, result = self.read(need, ctx)
        if result is not None:
            return result
        name, env, source = gh_name(need), need.params.get("environment"), need.params.get("from")
        value = found.get("value") if isinstance(found, dict) else None
        if need.params.get("declared") and not value:
            return Result("missing", f"variable {name} is empty in {where(ctx.slug, env)}", fix="give it its value")
        wanted = bitwarden(ctx, source) if source else None
        if wanted is not None and wanted != value:
            return Result("drift", f"variable {name} in {where(ctx.slug, env)} is not Bitwarden's {source}",
                          fix="send it again from Bitwarden")
        return Result("ready", f"variable {name} is set in {where(ctx.slug, env)}")


# The names the server's deploy job reads, as pubdeploy's implied.py implies the need from them.
DEPLOY_SETTINGS = {"SUSTENAUT_SERVER": "variable", "SUSTENAUT_KNOWN_HOSTS": "variable",
                   "SUSTENAUT_DEPLOY_SSH_KEY": "secret", "TS_GH_OAUTH_CLIENT_ID": "secret",
                   "TS_GH_OAUTH_SECRET": "secret"}


class DeploySettings(Base):
    type, grade, budget, fulfil_budget, singleton = "github.deploy-settings", "auto", 3.0, 60.0, True
    schema = schema({"environment": NAME})

    def missing(self, need: Any, ctx: Any) -> tuple[list[str], Result | None]:
        env, held = need.params.get("environment", "server"), set()
        for kind in ("secret", "variable"):
            for scope in (f"repos/{ctx.slug}/actions", f"repos/{ctx.slug}/environments/{env}"):
                try:
                    found = ctx.gh("GET", f"{scope}/{kind}s", None) or {}
                except Exception as e:  # noqa: BLE001 - ctx.gh's refusal carries its status
                    if getattr(e, "status", None) == 404 and "environments" in scope:
                        continue
                    return [], refused(e, f"the {kind}s of {ctx.slug}")
                held |= {(kind, item.get("name")) for item in found.get(f"{kind}s") or []}
        return [n for n, kind in DEPLOY_SETTINGS.items() if (kind, n) not in held], None

    def action(self, need: Any, ctx: Any) -> str:
        return "set the deploy settings the secrets block names"

    def check(self, need: Any, ctx: Any) -> Result:
        if not ctx.slug:
            return Result("unknown", "origin is not a GitHub repository", fix="run this in a clone of it")
        missing, result = self.missing(need, ctx)
        if result is not None:
            return result
        if missing:
            named = {e.get("to") for e in ctx.config.get("secrets", [])}
            return Result("missing", f"{', '.join(missing)} {'is' if len(missing) == 1 else 'are'} not set in "
                                     f"{ctx.slug}", fix="name them in the secrets block",
                          fixable=all(m in named for m in missing))
        return Result("ready", f"the deploy settings are set in {ctx.slug}")

    def fulfil(self, need: Any, ctx: Any) -> Result:
        missing, result = self.missing(need, ctx)
        if result is not None:
            return Result("missing", result.summary, fix=result.fix)
        sent = {e.get("to"): e for e in ctx.config.get("secrets", [])}
        for name in missing:
            if (entry := sent.get(name)) is None:
                return Result("missing", f"the secrets block does not name {name}", fix="name it there")
            if (made := send(ctx, entry["kind"], name, entry["from"], entry.get("environment"))).state != "ready":
                return made
        return Result("ready", f"set {', '.join(missing) or 'nothing'} from Bitwarden")


def prepare(ctx: Any, plan: Any, terminal: bool) -> str | None:
    """The `sustenaut.walk` hook: a writer for the walk, from a token asked once,
    or read from PUBSEC_WRITE_TOKEN_FILE without a terminal."""
    from pubdeploy.testing.world import FakeWriter  # noqa: PLC0415
    world = WORLD
    world.hook_terminal.append(terminal)
    if ctx.bitwarden_writer is not None:
        return None
    if not terminal:
        if ctx.env.get("PUBSEC_WRITE_TOKEN_FILE"):
            ctx.bitwarden_writer = FakeWriter(world, world.token)
        return None
    if not project(ctx):
        return "stand-in: no Bitwarden project to write to: run the walk through ./with-secrets"
    if world.hook_writer is None:
        world.outputs.append("Bitwarden access token with write access (hidden): ")
        world.hook_writer = FakeWriter(world, world.token) if world.token else False
    ctx.bitwarden_writer = world.hook_writer or None
    return None if ctx.bitwarden_writer else "stand-in: no Bitwarden write token was given"


# By the names its metadata's entry points give.
BITWARDEN_SECRET, BITWARDEN_GENERATED, BITWARDEN_ADOPT = BitwardenSecret(), BitwardenGenerated(), Adopt()
GCP_SERVICE_ACCOUNT_KEY, K8S_SECRET = ServiceAccountKey(), Secret()
GITHUB_SECRET, GITHUB_VARIABLE, GITHUB_DEPLOY_SETTINGS = GitHubSecret(), GitHubVariable(), DeploySettings()


# Its distribution's metadata, beside it, so a program the suite starts finds it on PYTHONPATH.
DIST = Path(__file__).resolve().parent / "standin" / "standin-0.dist-info"


def points() -> tuple[list[EntryPoint], list[EntryPoint]]:
    """The stand-in's entry points, as its metadata gives them: its types, and its hook."""
    found = Distribution.at(DIST).entry_points
    return list(found.select(group="sustenaut.needs")), list(found.select(group="sustenaut.walk"))
