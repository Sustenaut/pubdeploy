"""The tools `pubrules deploy check` reaches outside a test's fakes: kustomize,
kubectl, HTTP, dig and git, each given a stand-in, never the real one, and
the command run whole, as a person runs it."""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest

from deploy_world import CANARY, FIXTURE
import pubdeploy as deploy
from pubdeploy.model import Context, Result, Stop
from pubdeploy.walk import timed
from pytest_bdd import scenarios, then

scenarios("deploy-tools.feature")


def program(bin_dir: Path, name: str, script: str) -> None:
    """A stand-in for a tool on PATH: a Python script."""
    bin_dir.mkdir(exist_ok=True)
    path = bin_dir / name
    path.write_text(f"#!{sys.executable}\nimport sys, json\n{script}\n")
    path.chmod(0o755)


@pytest.fixture
def tools(tmp_path, monkeypatch):
    """A PATH of only the stand-ins, and Python and git."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in ("git",):
        os.symlink(shutil.which(tool), bin_dir / tool)
    monkeypatch.setenv("PATH", str(bin_dir))
    return bin_dir


@then("render runs kustomize build")
def render_runs_kustomize_build(tools, tmp_path):
    program(tools, "kustomize", "print('kind: ConfigMap') if sys.argv[1:2] == ['build'] else sys.exit(3)")
    assert deploy.render(tmp_path, "k8s") == "kind: ConfigMap\n"


@then("render falls back to kubectl kustomize")
def render_falls_back_to_kubectl_kustomize(tools, tmp_path):
    program(tools, "kubectl", "print('kind: Secret') if sys.argv[1:2] == ['kustomize'] else sys.exit(3)")
    assert deploy.render(tmp_path, "k8s") == "kind: Secret\n"


@then("render says what kustomize said")
def render_says_what_kustomize_said(tools, tmp_path):
    program(tools, "kustomize", "print('warning', file=sys.stderr); print('Error: no such file', file=sys.stderr); "
                                "sys.exit(1)")
    with pytest.raises(Stop) as stop:
        deploy.render(tmp_path, "k8s")
    assert str(stop.value) == "kustomize build k8s failed: Error: no such file" and not stop.value.missing_tool


@then("render without either tool")
def render_without_either_tool(tools, tmp_path):
    with pytest.raises(Stop) as stop:
        deploy.render(tmp_path, "k8s")
    assert stop.value.missing_tool and "neither kustomize nor kubectl is installed" in str(stop.value)


@then("render is done once")
def render_is_done_once(tools, tmp_path):
    program(tools, "kustomize", "import pathlib; p = pathlib.Path(sys.argv[2]).parent / 'count'; "
                                "p.write_text(p.read_text() + 'x' if p.exists() else 'x'); print('kind: List')")
    rendered = deploy.renderer(tmp_path, "k8s")
    assert rendered() == rendered() == "kind: List\n"
    assert (tmp_path / "count").read_text() == "x"


@then("kubectl runs the command given")
def kubectl_runs_the_command_given(tools):
    program(tools, "k3s", "print(json.dumps(sys.argv[1:]))")
    ran = deploy.kubectl("k3s kubectl --kubeconfig 'a file'")(["get", "namespace", "example"])
    assert ran.returncode == 0 and json.loads(ran.stdout) == ["kubectl", "--kubeconfig", "a file", "get",
                                                             "namespace", "example"]


@then("kubectl that is not there")
def kubectl_that_is_not_there(tools):
    ran = deploy.kubectl("kubectl")(["get", "namespace", "example"])
    assert ran.returncode == 127 and ran.stderr == "kubectl did not run (FileNotFoundError)"


@then("resolve asks dig for addresses")
def resolve_asks_dig_for_addresses(tools):
    program(tools, "dig", "print('example.example.eu.') if 'CNAME' in sys.argv else print('192.0.2.1\\nhost.example.eu.')")
    assert deploy.resolve("example.example.eu", "A") == ["192.0.2.1"]


@then("resolve without dig")
def resolve_without_dig(tools):
    assert deploy.resolve("example.example.eu", "A") is None


class Answer(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@then("http get")
def http_get(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout: Answer(b"ok"))
    assert deploy.http_get("https://example.example.eu/healthz", 1.0) == (200, b"ok")


@then("http get of an error status")
def http_get_of_an_error_status(monkeypatch):
    def refuse(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 503, "Unavailable", {}, io.BytesIO(CANARY.encode()))
    monkeypatch.setattr("urllib.request.urlopen", refuse)
    assert deploy.http_get("https://example.example.eu/healthz", 1.0) == (503, b"")


@then("http get that is not answered")
def http_get_that_is_not_answered(monkeypatch):
    """Every case of the parametrized test this was, in turn."""
    for case0 in [(TimeoutError(), TimeoutError),
                                                (ConnectionRefusedError(), ConnectionError)]:
        case0 = case0.values if type(case0).__name__ == "ParameterSet" else case0
        _case_http_get_that_is_not_answered(reason=case0[0], raised=case0[1], monkeypatch=monkeypatch)


def _case_http_get_that_is_not_answered(monkeypatch, reason, raised):
    def fail(request, timeout):
        raise urllib.error.URLError(reason)
    monkeypatch.setattr("urllib.request.urlopen", fail)
    with pytest.raises(raised):
        deploy.http_get("https://example.example.eu/healthz", 1.0)


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
                   check=True, capture_output=True)


@then("slug of origin")
def slug_of_origin(tmp_path):
    """Every case of the parametrized test this was, in turn."""
    for case0 in [("git@github.com:example-org/example.git", "example-org/example"),
                                           ("https://github.com/example-org/example", "example-org/example"),
                                           ("https://example.eu/example.git", "")]:
        case0 = case0.values if type(case0).__name__ == "ParameterSet" else case0
        case_dir = tmp_path / f"case-{len(list(tmp_path.iterdir()))}"
        case_dir.mkdir()
        _case_slug_of_origin(url=case0[0], slug=case0[1], tmp_path=case_dir)


def _case_slug_of_origin(tmp_path, url, slug):
    git(tmp_path, "init", "-q")
    git(tmp_path, "remote", "add", "origin", url)
    assert deploy.slug(tmp_path) == slug


@then("slug outside a repository")
def slug_outside_a_repository(tmp_path):
    assert deploy.slug(tmp_path) == ""


@then("zones come from the config and the zones file")
def zones_come_from_the_config_and_the_zones_file(tmp_path):
    other = tmp_path / "other.json"
    other.write_text(json.dumps({"hosting": {"zones": {"example.org": {"sites": {"@": {}}}}}}))
    config = {"hosting": {"zones": {"example.eu": {"sites": {}}}}}
    assert set(deploy.zones_of(config, other)) == {"example.eu", "example.org"}
    assert deploy.zones_of({}, None) is None


@then("zones come from each zones file one per owner")
def zones_come_from_each_zones_file_one_per_owner(tmp_path):
    files = []
    for zone in ("example.org", "example.net"):
        f = tmp_path / f"{zone}.json"
        f.write_text(json.dumps({"hosting": {"zones": {zone: {"sites": {}}}}}))
        files.append(f)
    assert set(deploy.zones_of({}, files)) == {"example.org", "example.net"}


@then("the walk takes zones more than once")
def the_walk_takes_zones_more_than_once(tmp_path, monkeypatch):
    from pubdeploy import cli
    for owner in ("a", "b"):
        (tmp_path / owner).mkdir()
        (tmp_path / owner / "pubrules.json").write_text("{}")
    (tmp_path / "svc").mkdir()
    monkeypatch.chdir(tmp_path / "svc")
    seen = {}
    monkeypatch.setattr("pubdeploy.run_walk", lambda root, offline, as_json, kubectl, zones, *a, **k: seen.setdefault("z", zones) and 0)
    cli.main(["walk", "--zones", "../a/pubrules.json", "--zones", "../b/pubrules.json"])
    assert [z.parent.name for z in seen["z"]] == ["a", "b"]


@then("the journal says where the walk ran")
def the_journal_says_where_the_walk_ran(tmp_path):
    """Every case of the parametrized test this was, in turn."""
    for case0 in [({}, "laptop"), ({"GITHUB_ACTIONS": "true", "GITHUB_ACTOR": "someone"},
                                                               "actions"), ({"PUBRULES_PLANE": "1", "PUBRULES_WALK_BY": "schedule"}, "plane")]:
        case0 = case0.values if type(case0).__name__ == "ParameterSet" else case0
        case_dir = tmp_path / f"case-{len(list(tmp_path.iterdir()))}"
        case_dir.mkdir()
        _case_the_journal_says_where_the_walk_ran(env=case0[0], origin=case0[1], tmp_path=case_dir)


def _case_the_journal_says_where_the_walk_ran(tmp_path, env, origin):
    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    config = json.loads((root / "pubrules.json").read_text())
    ctx = Context(root=root, config=config, block=config["deploy"], namespace="example", env=env, offline=True,
                  rendered=lambda: (root / "rendered.yaml").read_text())
    journal = deploy.check(deploy.load(root, config, ctx), ctx)
    assert journal.walk["from"] == origin
    assert journal.walk["by"] == env.get("PUBRULES_WALK_BY", env.get("GITHUB_ACTOR", journal.walk["by"]))


@then("a check that returns no result is unknown")
def a_check_that_returns_no_result_is_unknown():
    class Odd:
        type, budget = "example.odd", 1.0

        def check(self, need, ctx):
            return "ready"

    from pubdeploy.model import Need  # noqa: PLC0415
    result = timed(Odd(), Need("example.odd", "one", {}), Context.for_tests())
    assert (result.state, result.summary) == ("unknown", "the check returned no result (str)")


@then("every builtin type is one the registry takes")
def every_builtin_type_is_one_the_registry_takes():
    from pubdeploy.registry import BUILTIN, type_problems  # noqa: PLC0415
    # pubrules's own may be one word, as upstream is.
    found = {kind.type: [p for p in type_problems(kind) if "dotted" not in p] for kind in BUILTIN}
    assert found == {kind.type: [] for kind in BUILTIN}


@then("a summary is one line of at most 120 characters")
def a_summary_is_one_line_of_at_most_120_characters():
    result = Result("ready", "a\nb " + "c" * 200)
    assert "\n" not in result.summary and len(result.summary) == 120


@then("the context for tests reaches nothing")
def the_context_for_tests_reaches_nothing():
    from pubdeploy.github import ApiError  # noqa: PLC0415
    ctx = Context.for_tests()
    assert ctx.kubectl(["get", "namespace", "example"]).returncode == 127
    assert ctx.resolve("example.example.eu", "A") is None
    with pytest.raises(ApiError):
        ctx.gh("GET", "repos/example-org/example", None)
    with pytest.raises(ConnectionRefusedError):
        ctx.http_get("https://example.example.eu", 1.0)
    with pytest.raises(Stop):
        ctx.rendered()


@then("deploy check runs whole")
def deploy_check_runs_whole(tmp_path, run):
    """The command as a person runs it: its own kustomize, kubectl and git
    stand-ins on PATH, offline, with --zones outside the repository."""
    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    bin_dir = tmp_path / "bin"
    program(bin_dir, "kustomize", f"print(open({str(root / 'rendered.yaml')!r}).read())")
    zones = tmp_path / "infra" / "pubrules.json"
    zones.parent.mkdir()
    shutil.move(root / "zones.json", zones)
    from conftest import pubdeploy as pubrules  # noqa: PLC0415
    env = {"PATH": f"{bin_dir}:{os.environ['PATH']}", "PUBRULES_ANY_VERSION": "1"}
    done = run(pubrules(), "check", "--offline", "--zones", str(zones), cwd=root, env=env)
    assert done.code == 0, done.describe()
    assert "ready   k8s.secrets-declared:example" in done.stdout
    done = run(pubrules(), "check", "--offline", "--zones", str(tmp_path / "gone" / "pubrules.json"),
               cwd=root, env=env)
    assert done.code == 2 and "--zones" in done.stderr


@then("deploy check reads only a pubrules json beside the repository")
def deploy_check_reads_only_a_pubrules_json_beside_the_repository(tmp_path, run):
    """Every case of the parametrized test this was, in turn."""
    for case0 in [("../infra/zones.json", "must be a repository's pubrules.json"),
                                           ("/pubrules.json", "must be in the working directory")]:
        case0 = case0.values if type(case0).__name__ == "ParameterSet" else case0
        case_dir = tmp_path / f"case-{len(list(tmp_path.iterdir()))}"
        case_dir.mkdir()
        _case_deploy_check_reads_only_a_pubrules_json_beside_the_repository(path=case0[0], why=case0[1], tmp_path=case_dir, run=run)


def _case_deploy_check_reads_only_a_pubrules_json_beside_the_repository(tmp_path, run, path, why):
    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    from conftest import pubdeploy as pubrules  # noqa: PLC0415
    done = run(pubrules(), "check", "--offline", "--zones", path, cwd=root, env={"PUBRULES_ANY_VERSION": "1"})
    assert done.code != 0 and why in done.stderr, done.describe()


@then("a providers result need not be pubruless")
def a_providers_result_need_not_be_pubruless():
    """An out-of-tree type imports nothing of pubrules's: any object with
    state, summary, fix and details is a result, for its check and its fulfil."""
    from pubdeploy.model import Need  # noqa: PLC0415
    from pubdeploy.walk import fulfil, walk  # noqa: PLC0415

    class Found:
        def __init__(self, state, summary, fix="", details=()):
            self.state, self.summary, self.fix, self.details = state, summary, fix, list(details)

    class Foreign:
        type, grade, budget, offline, schema = "example.database", "auto", 1.0, False, {}
        made = False

        def default_name(self, params):
            return None

        def depends_on(self, need, needs):
            return []

        def check(self, need, ctx):
            return Found("ready", "the database is there") if self.made else Found("missing", "no database",
                                                                                   "make it", ["one"])

        def fulfil(self, need, ctx):
            self.made = True
            return Found("ready", "made the database")

    need, kinds, ctx = Need("example.database", "one", {}), {"example.database": Foreign()}, Context.for_tests()
    journal = walk({need.id: need}, kinds, ctx, service={})
    (_, found), = journal.entries
    assert (found.state, found.summary, found.fix, found.details) == ("missing", "no database", "make it", ["one"])
    (_, made), = fulfil(journal, kinds, ctx, {need.id}).entries
    assert (made.state, made.fulfilled, made.details) == ("ready", True, ["fulfilled: made the database"])


@then("a fulfil over its budget is left")
def a_fulfil_over_its_budget_is_left(monkeypatch):
    import time  # noqa: PLC0415
    from pubdeploy.model import Need  # noqa: PLC0415
    from pubdeploy.walk import timed  # noqa: PLC0415

    class Slow:
        type, grade, budget, fulfil_budget, offline, schema = "example.slow", "auto", 1.0, 0.05, False, {}

        def fulfil(self, need, ctx):
            time.sleep(0.5)

    result = timed(Slow(), Need("example.slow", "one", {}), Context.for_tests(), "fulfil")
    assert (result.state, result.summary) == ("unknown", "the fulfil took longer than 0.05 s, and was left")


@then("a fulfil budget over 900 seconds is refused")
def a_fulfil_budget_over_900_seconds_is_refused():
    from pubdeploy.registry import type_problems  # noqa: PLC0415
    from pubdeploy.types.k8s import CronJob  # noqa: PLC0415
    kind = CronJob()
    kind.fulfil_budget = 901
    assert "its fulfil_budget must be more than 0 and at most 900 seconds" in type_problems(kind)


@then("a journal head is a name storage takes")
def a_journal_head_is_a_name_storage_takes():
    from pubdeploy.store import head_name
    assert head_name("Example-Org/example", "api-eu") == "example-org.example.api-eu"
    assert head_name("Some Owner/Repo", "U" * 80) == ("some-owner.repo." + "u" * 80)[:64]


@then("a namespace without the deploy kubeconfig is missing over the admin channel")
def a_namespace_without_the_deploy_kubeconfig_is_missing_over_the_admin_channel(tmp_path):
    from pubdeploy.model import Need, Ran
    from pubdeploy.types.k8s import Namespace

    def kubectl(args, input=None):  # noqa: A002
        return Ran(0, '{"metadata": {"name": "x"}}', "")
    asked = []

    def server(args, input=None):  # noqa: A002
        asked.append(args)
        return Ran(1, "", "")
    ctx = Context(root=tmp_path, config={}, block={}, namespace="app", kubectl=kubectl, server=server,
                  channel="admin", env={"SUSTENAUT_SERVER": "host"})
    result = Namespace().check(Need(type="k8s.namespace", name="app", params={}), ctx)
    assert result.state == "missing"
    assert "deploy kubeconfig (/home/deploy/.kube/app on the server)" in result.summary
    assert result.fix == "ssh root@host sustenaut-app app"
    assert asked == [["test", "-f", "/home/deploy/.kube/app"]]

@then("manifests apply each object in its own namespace")
def manifests_apply_each_object_in_its_own_namespace(tmp_path):
    from pubdeploy.model import Need, Ran
    from pubdeploy.types.k8s import Manifests
    (tmp_path / "admin.yaml").write_text(
        "kind: ClusterRole\nmetadata: {name: reader}\n---\n"
        "kind: RoleBinding\nmetadata: {name: read, namespace: one}\n---\n"
        "kind: RoleBinding\nmetadata: {name: read, namespace: two}\n---\n"
        "kind: NetworkPolicy\nmetadata: {name: only}\n")
    calls = []

    def kubectl(args, input=None):  # noqa: A002
        calls.append((args, input.decode()))
        return Ran(0, "configured\n" * input.decode().count("kind:"), "")
    ctx = Context(root=tmp_path, config={}, block={}, namespace="unit", kubectl=kubectl, env={})
    result = Manifests().fulfil(Need(type="k8s.manifests", name="admin.yaml", params={"path": "admin.yaml"}), ctx)
    assert result.state == "ready" and result.summary == "applied admin.yaml: 4 objects"
    assert [args[:2] for args, _ in calls] == [["-n", "unit"], ["-n", "one"], ["-n", "two"]]
    assert "ClusterRole" in calls[0][1] and "NetworkPolicy" in calls[0][1]


@then("manifests that do not parse are not applied")
def manifests_that_do_not_parse_are_not_applied(tmp_path):
    from pubdeploy.model import Need
    from pubdeploy.types.k8s import Manifests
    (tmp_path / "bad.yaml").write_text("kind: [\n")
    ctx = Context(root=tmp_path, config={}, block={}, namespace="unit", env={})
    assert Manifests().fulfil(Need(type="k8s.manifests", name="bad.yaml", params={"path": "bad.yaml"}), ctx).state == "drift"
