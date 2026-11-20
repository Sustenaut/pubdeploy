"""The tools `pubrules deploy check` reaches outside a test's fakes: kustomize,
kubectl, HTTP, dig and git, each given one of pubtest's stand-ins, never the
real one, and the command run whole, as a person runs it."""

from __future__ import annotations

import io
import json
import shlex
import time
import urllib.error

import pubdeploy as deploy
from pubdeploy.model import Context, Need, Result
from pubdeploy.walk import timed
from pytest_bdd import given, parsers, scenarios, when

scenarios("deploy-tools.feature")


# --- kustomize, kubectl, dig, git -----------------------------------------------------


@when(parsers.parse('the overlay "{overlay}" is rendered'))
def rendered(ctx, overlay):
    ctx.attempt(lambda: deploy.render(ctx.directory, overlay))


@when(parsers.parse('the overlay "{overlay}" is rendered, twice by one renderer'))
def rendered_twice(ctx, overlay):
    render = deploy.renderer(ctx.directory, overlay)
    ctx.attempt(lambda: [render(), render()])


@when(parsers.parse('kubectl "{command}" runs "{args}"'))
def kubectl_runs(ctx, command, args):
    ctx.attempt(lambda: deploy.kubectl(command)(shlex.split(args)))


@when(parsers.parse('"{host}" is resolved as "{rtype}"'))
def resolved(ctx, host, rtype):
    ctx.attempt(lambda: deploy.resolve(host, rtype))


@given(parsers.parse('the remote "{name}" is "{url}"'))
def remote(ctx, name, url):
    from pubtest.steps.git import git  # noqa: PLC0415
    git(ctx, "remote", "add", name, url)


@when("the repository's slug is read")
def slug_read(ctx):
    ctx.attempt(lambda: deploy.slug(ctx.directory))


# --- HTTP ------------------------------------------------------------------------------


class Answer(io.BytesIO):
    def __init__(self, status, body):
        super().__init__(body)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@given(parsers.parse('the network answers {status:d}, "{body}"'))
def answers(monkeypatch, status, body):
    def urlopen(request, timeout):
        if status < 400:
            return Answer(status, body.encode())
        raise urllib.error.HTTPError(request.full_url, status, "Unavailable", {}, io.BytesIO(body.encode()))
    monkeypatch.setattr("urllib.request.urlopen", urlopen)


@given(parsers.parse("the network fails with a {reason}"))
def fails(monkeypatch, reason):
    def urlopen(request, timeout):
        raise urllib.error.URLError({"TimeoutError": TimeoutError, "ConnectionRefusedError": ConnectionRefusedError}[reason]())
    monkeypatch.setattr("urllib.request.urlopen", urlopen)


@when(parsers.parse('"{url}" is fetched'))
def fetched(ctx, url):
    def fetch():
        status, body = deploy.http_get(url, 1.0)
        assert isinstance(body, bytes), body
        return {"status": status, "body": body.decode()}
    ctx.attempt(fetch)


# --- zones and the journal ---------------------------------------------------------------


@when(parsers.re(r'the zones of (?P<config>\{.*\}) and "(?P<files>[^"]+)" are gathered$'))
def zones_gathered(ctx, config, files):
    paths = [ctx.directory / f for f in files.split(", ")]
    ctx.attempt(lambda: sorted(deploy.zones_of(json.loads(config), paths[0] if len(paths) == 1 else paths)))


@when(parsers.re(r"the zones of (?P<config>\{.*\}) and no zones file are gathered$"))
def no_zones_gathered(ctx, config):
    ctx.attempt(lambda: deploy.zones_of(json.loads(config), None))


@given(parsers.parse('a walk that keeps the zones files it is given in "{path}"'))
def walk_keeps(ctx, monkeypatch, path):
    def run_walk(root, offline, as_json, kubectl, zones, *a, **k):
        (ctx.directory / path).write_text(json.dumps([z.parent.name for z in zones]))
        return 0
    monkeypatch.setattr("pubdeploy.run_walk", run_walk)


@when(parsers.parse('pubdeploy runs "{argv}" in "{where}"'), target_fixture="result")
def runs_in(ctx, monkeypatch, argv, where):
    from pubdeploy import cli  # noqa: PLC0415
    monkeypatch.chdir(ctx.directory / where)
    ctx.attempt(lambda: cli.main(argv.split()))
    if ctx.refused is None:
        ctx.outcome.code = ctx.outcome.value  # main's code, as the program exits with it
    return ctx.outcome


@when(parsers.re(r'the service in "(?P<path>[^"]+)" is checked offline, in the environment (?P<env>\{.*\})$'))
def checked_offline(ctx, path, env):
    root = ctx.directory / path
    config = json.loads((root / "pubrules.json").read_text())
    context = Context(root=root, config=config, block=config["deploy"], namespace="example", env=json.loads(env),
                      offline=True, rendered=lambda: (root / "rendered.yaml").read_text())
    ctx.attempt(lambda: deploy.check(deploy.load(root, config, context), context).walk)


# --- need types, results and budgets ---------------------------------------------------------


@given(parsers.parse('a need type "{kind}" whose check returns "{value}", not a result'))
def odd(ctx, kind, value):
    class Odd:
        type, budget = kind, 1.0

        def check(self, need, context):
            return value
    ctx.kind = Odd()


@given(parsers.parse('a need type "{kind}" whose fulfil takes {seconds:g} seconds, over its fulfil budget of '
                     '{budget:g} seconds'))
def slow(ctx, kind, seconds, budget):
    class Slow:
        type, grade, budget, fulfil_budget, offline, schema = kind, "auto", 1.0, None, False, {}

        def fulfil(self, need, context):
            time.sleep(seconds)
    ctx.kind = Slow()
    ctx.kind.fulfil_budget = budget


@when(parsers.parse('its need "{name}" is {done} within its budget'))
def within_budget(ctx, name, done):
    phase = {"checked": "check", "fulfilled": "fulfil"}[done]
    need = Need(ctx.kind.type, name, {})
    ctx.attempt(lambda: timed(ctx.kind, need, Context.for_tests(), phase))


@when("the registry checks every builtin type, pubrules's own as one word")
def builtin_checked(ctx):
    from pubdeploy.contract import problems  # noqa: PLC0415
    from pubdeploy.registry import BUILTIN  # noqa: PLC0415
    # pubrules's own may be one word, as upstream is.
    ctx.attempt(lambda: [f"{kind.type}: {p}" for kind in BUILTIN for p in problems(kind) if "dotted" not in p])


@when(parsers.parse('the registry checks the type "{name}" with a fulfil budget of {seconds:d} seconds'))
def budget_checked(ctx, name, seconds):
    from pubdeploy.contract import problems  # noqa: PLC0415
    from pubdeploy.registry import types  # noqa: PLC0415
    kind = type(types()[name])()
    kind.fulfil_budget = seconds
    ctx.attempt(lambda: problems(kind))


@when('a result is made whose summary is "a", then a line of "b " and 200 "c"s')
def summary_made(ctx):
    ctx.attempt(lambda: Result("ready", "a\nb " + "c" * 200))


@when(parsers.parse('the context for tests runs kubectl "{args}"'))
def for_tests_kubectl(ctx, args):
    ctx.attempt(lambda: Context.for_tests().kubectl(args.split()))


@when(parsers.parse('the context for tests resolves "{host}" as "{rtype}"'))
def for_tests_resolve(ctx, host, rtype):
    ctx.attempt(lambda: Context.for_tests().resolve(host, rtype))


@when(parsers.parse('the context for tests asks GitHub for "{path}"'))
def for_tests_gh(ctx, path):
    ctx.attempt(lambda: Context.for_tests().gh("GET", path, None))


@when(parsers.parse('the context for tests fetches "{url}"'))
def for_tests_http(ctx, url):
    ctx.attempt(lambda: Context.for_tests().http_get(url, 1.0))


@when("the context for tests renders the manifests")
def for_tests_render(ctx):
    ctx.attempt(lambda: Context.for_tests().rendered())


@given(parsers.parse('a provider\'s need type "{name}" whose results are its own, missing until it is fulfilled'))
def foreign(ctx, name):
    """An out-of-tree type imports nothing of pubrules's: any object with
    state, summary, fix and details is a result, for its check and its fulfil."""
    class Found:
        def __init__(self, state, summary, fix="", details=()):
            self.state, self.summary, self.fix, self.details = state, summary, fix, list(details)

    class Foreign:
        type, grade, budget, offline, schema = name, "auto", 1.0, False, {}
        made = False

        def default_name(self, params):
            return None

        def depends_on(self, need, needs):
            return []

        def check(self, need, context):
            return Found("ready", "the database is there") if self.made else Found("missing", "no database",
                                                                                   "make it", ["one"])

        def fulfil(self, need, context):
            self.made = True
            return Found("ready", "made the database")
    ctx.kind = Foreign()


def walked(ctx, name, also_fulfil):
    from pubdeploy.walk import fulfil, walk  # noqa: PLC0415
    need, kinds, context = Need(ctx.kind.type, name, {}), {ctx.kind.type: ctx.kind}, Context.for_tests()

    def action():
        journal = walk({need.id: need}, kinds, context, service={})
        if also_fulfil:
            journal = fulfil(journal, kinds, context, {need.id})
        (_, found), = journal.entries
        return found
    ctx.attempt(action)


@when(parsers.parse('a walk checks its need "{name}"'))
def walk_checks(ctx, name):
    walked(ctx, name, False)


@when(parsers.parse('a walk checks and fulfils its need "{name}"'))
def walk_fulfils(ctx, name):
    walked(ctx, name, True)


@when(parsers.parse('the journal head of "{repository}" and the unit "{unit}" is named'))
def head_named(ctx, repository, unit):
    from pubdeploy.store import head_name  # noqa: PLC0415
    ctx.attempt(lambda: head_name(repository, unit))


# --- the k8s types, against stand-ins ---------------------------------------------------------


@when(parsers.parse('the need "{need_id}" is checked over the admin channel of the server "{host}"'))
def checked_admin(ctx, need_id, host):
    from pubdeploy.registry import types  # noqa: PLC0415
    kind, name = need_id.split(":", 1)
    context = Context(root=ctx.directory, config={}, block={}, namespace=name, kubectl=deploy.kubectl("kubectl"),
                      server=deploy.kubectl("server"), channel="admin", env={"SUSTENAUT_SERVER": host})
    ctx.attempt(lambda: types()[kind].check(Need(type=kind, name=name, params={}), context))


@when(parsers.parse('the need "{need_id}" of the path "{path}" is fulfilled in the namespace "{ns}"'))
def fulfilled_in(ctx, need_id, path, ns):
    from pubdeploy.registry import types  # noqa: PLC0415
    kind, name = need_id.split(":", 1)
    context = Context(root=ctx.directory, config={}, block={}, namespace=ns, kubectl=deploy.kubectl("kubectl"), env={})
    ctx.attempt(lambda: types()[kind].fulfil(Need(type=kind, name=name, params={"path": path}), context))
