"""The checks of pubdeploy's code that were in pubrules's test_deploy_sync.py
when the walk was pubrules's: providers.bump, a type no installed package
offers, the trigger rewrite, pubsec's types without pubsec, the provider
contract and the sustenaut.walk hook."""

from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path
from types import SimpleNamespace

from pubdeploy import prepare, providers
from pubdeploy.model import Context, Need
from pubdeploy.registry import BUILTIN, lacking, types
from pubdeploy.schema import need_problems
from pubdeploy.testing.world import FIXTURE
from pubdeploy.units import retrigger, trigger_problems
from pytest_bdd import given, parsers, scenarios, when

scenarios("moved.feature")

ROOT = Path(__file__).resolve().parents[2]
WHEEL = "https://github.com/{repo}/releases/download/v{version}/{dist}-{version}-py3-none-any.whl"


@given(parsers.parse('the latest release of "{repo}" offers its wheel {version}, of the digest "{digest}"'))
def latest_release(ctx, repo, version, digest):
    dist = repo.split("/")[1].replace("-", "_")
    wheel = WHEEL.format(repo=repo, version=version, dist=dist)

    def gh(method, path, body):
        assert (method, path) == ("GET", f"repos/{repo}/releases/latest"), (method, path)
        return {"assets": [{"name": f"{dist}-{version}.tar.gz", "browser_download_url": "x"},
                           {"name": wheel.rsplit("/", 1)[1], "browser_download_url": wheel, "digest": digest}]}
    ctx.gh = gh


@given("GitHub may be asked nothing")
def asks_nothing(ctx):
    def gh(*_):
        raise AssertionError("no release is read")
    ctx.gh = gh


@when("the providers are bumped")
def bumped(ctx):
    ctx.attempt(lambda: providers.bump(ctx.directory, ctx.gh))


@when(parsers.re(r'the need (?P<need>\{.*\}) is checked against the installed types, with the providers "(?P<dist>[^"]+)"$'))
def checked_installed(ctx, need, dist):
    ctx.attempt(lambda: need_problems(json.loads(need), 0, types(), FIXTURE, [dist]))


@when(parsers.re(r"the need (?P<need>\{.*\}) is checked against pubdeploy's own types$"))
def checked_own(ctx, need):
    own = {kind.type: kind for kind in BUILTIN}
    ctx.attempt(lambda: need_problems(json.loads(need), 0, own, FIXTURE))


@when(parsers.parse('the needs "{a}" and "{b}" are looked for among pubdeploy\'s own types'))
def looked_for(ctx, a, b):
    own = {kind.type: kind for kind in BUILTIN}
    ctx.attempt(lambda: lacking([Need(*a.split(":"), {}), Need(*b.split(":"), {})], own))


@when(parsers.parse('the trigger of "{path}" is checked'))
def trigger_checked(ctx, path):
    ctx.attempt(lambda: trigger_problems((ctx.directory / path).read_text(), path))


@when(parsers.parse('the trigger of "{path}" is rewritten'))
def trigger_rewritten(ctx, path):
    target = ctx.directory / path

    def rewrite() -> None:
        target.write_text(retrigger(target.read_text()))
    ctx.attempt(rewrite)


@when("the names a context holds are listed")
def context_names(ctx):
    ctx.attempt(lambda: sorted(f.name for f in fields(Context)))


@when("the README's provider contract is read")
def contract_read(ctx):
    ctx.attempt(lambda: (ROOT / "README.md").read_text().split("### Provider contract", 1)[1].split("\n## ", 1)[0])


@given(parsers.parse('a walk hook "{name}" that fails, saying "{message}"'))
def hook_fails(ctx, name, message):
    def broken(context, plan, terminal):
        raise ValueError(message)
    ctx.hooks = [*getattr(ctx, "hooks", []), SimpleNamespace(name=name, load=lambda: broken)]


@given(parsers.parse('a walk hook "{name}" that gives the context the writer "{writer}", saying "{line}"'))
def hook_says(ctx, name, writer, line):
    def says(context, plan, terminal):
        context.bitwarden_writer = writer
        return line
    ctx.hooks = [*getattr(ctx, "hooks", []), SimpleNamespace(name=name, load=lambda: says)]


@when("the walk is prepared")
def prepared(ctx):
    context = Context.for_tests()

    def walk_prepared():
        prepare(context, [], True, ctx.hooks)
        return context.bitwarden_writer
    ctx.attempt(walk_prepared)
