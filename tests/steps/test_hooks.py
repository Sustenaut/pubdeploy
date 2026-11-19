"""What pubrules calls of pubdeploy (hooks.py), and that pubdeploy imports
nothing of pubrules's."""

from __future__ import annotations

import json
import shlex
import sys
from importlib.metadata import entry_points
from pathlib import Path

from pubdeploy import hooks
from pubtest.steps.programs import run_command
from pytest_bdd import given, parsers, scenarios, when

scenarios("hooks.feature")

SRC = Path(__file__).resolve().parents[2] / "src" / "pubdeploy"
WHEEL = "https://github.com/Sustenaut/pubdeploy/releases/download/v{0}/pubdeploy-{0}-py3-none-any.whl"


@when(parsers.parse('pubdeploy\'s entry points in the group "{group}" are listed'))
def listed(ctx, group):
    ctx.attempt(lambda: [p.value for p in entry_points(group=group) if p.name == "pubdeploy"])


@when("every module of pubdeploy is imported with pubrules blocked", target_fixture="result")
def imported_alone(ctx):
    names = sorted(f"pubdeploy.{p.relative_to(SRC).with_suffix('').as_posix().replace('/', '.')}".removesuffix(".__init__")
                   for p in SRC.rglob("*.py"))
    script = ("import sys, importlib\n"
              "class Block:\n"
              "    def find_spec(self, name, path=None, target=None):\n"
              "        if name == 'pubrules' or name.startswith('pubrules.'): raise ImportError('pubrules is blocked')\n"
              "sys.meta_path.insert(0, Block())\n"
              f"for n in {names!r}: importlib.import_module(n)\n")
    return run_command(ctx, shlex.join([sys.executable, "-c", script]), None)


@given("the offline check of the deploy block finds nothing")
def finds_nothing(monkeypatch):
    monkeypatch.setattr("pubdeploy.offline_lines", lambda root, config: ([], False))


@given(parsers.parse('the offline check of the deploy block finds "{line}"'))
def finds(monkeypatch, line):
    monkeypatch.setattr("pubdeploy.offline_lines", lambda root, config: ([line], True))


@when(parsers.re(r"the sync hook is (?P<mode>checking|syncing) (?P<config>\{.*\})$"))
def sync_hook(ctx, mode, config):
    ctx.attempt(lambda: list(hooks.check(ctx.directory, json.loads(config), check=mode == "checking")))


@given("a service whose providers list pubdeploy 0.2.0, deployed on:")
def provided(ctx, tmp_path, monkeypatch, docstring):
    from pubtest.steps.files import scratch_directory  # noqa: PLC0415
    scratch_directory(ctx, tmp_path, monkeypatch)
    root = ctx.directory
    on = "".join(f"  {line}\n" for line in docstring.splitlines())
    (root / "pubrules.json").write_text(json.dumps({"kind": "service", "deploy": {
        "namespace": "example", "providers": [{"distribution": "pubdeploy", "wheel": WHEEL.format("0.2.0"),
                                               "sha256": "b" * 64}]}}))
    workflows = root / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "deploy.yml").write_text(
        f"name: deploy\non:\n{on}permissions: {{ contents: read, packages: write }}\njobs:\n  deploy:\n"
        f"    uses: Sustenaut/pubdeploy/.github/workflows/k8s-deploy.yml@v0.0.9\n")
    (workflows / "deploy-check.yml").write_text(
        f"jobs:\n  check:\n    uses: Sustenaut/pubdeploy/.github/workflows/deploy-check.yml@{'c' * 40} # v0.0.9\n")


@given(parsers.parse('GitHub reads the tag "{tag}" of Sustenaut/pubdeploy as the commit "{commit}"'))
def reads_tag(ctx, tag, commit):
    def gh(method, path, body=None):
        assert method == "GET"
        if path == f"repos/Sustenaut/pubdeploy/git/ref/tags/{tag}":
            return {"object": {"type": "tag", "sha": "d" * 40}}
        if path == f"repos/Sustenaut/pubdeploy/git/tags/{'d' * 40}":
            return {"object": {"type": "commit", "sha": commit}}
        raise AssertionError(path)
    ctx.gh = gh


@given("GitHub answers no request")
def refuses(ctx):
    from pubdeploy.github import ApiError  # noqa: PLC0415

    def gh(method, path, body=None):
        raise ApiError("gh api -X GET x: Not Found (HTTP 404)")
    ctx.gh = gh


@when("pubdeploy's workflows are bumped")
def bumped(ctx):
    ctx.attempt(lambda: sorted(hooks.bump(ctx.directory, gh=ctx.gh, find=lambda wheel, gh: None)))
