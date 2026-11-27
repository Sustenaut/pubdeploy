"""Each unit's Secret for its live runs' Job, which pubrules sync adds (executor_secret.py)."""

from __future__ import annotations

import json

from pubdeploy import executor_secret, hooks
from pytest_bdd import given, parsers, scenarios, then, when

scenarios("executor-secret.feature")


@given("the offline check of the deploy block finds nothing")
def finds_nothing(monkeypatch):
    monkeypatch.setattr("pubdeploy.offline_lines", lambda root, config: ([], False))


@when(parsers.re(r"the sync hook (?P<mode>checks|syncs) pubrules\.json$"))
def sync_hook(ctx, mode):
    config = json.loads((ctx.directory / "pubrules.json").read_text(encoding="utf-8"))
    ctx.hooked = hooks.check(ctx.directory, config, check=mode == "checks")


@then("the hook fails, saying:")
def fails_saying(ctx, docstring):
    assert ctx.hooked == (docstring.splitlines(), True), ctx.hooked


@then("the hook succeeds, saying:")
def succeeds_saying(ctx, docstring):
    assert ctx.hooked == (docstring.splitlines(), False), ctx.hooked


@then("the hook succeeds, saying nothing")
def succeeds_silently(ctx):
    assert ctx.hooked == ([], False), ctx.hooked


@when(parsers.re(r'the need for the unit "(?P<unit>[^"]+)" is put into the pubrules\.json text (?P<text>\{.*\})$'))
def put(ctx, unit, text):
    ctx.attempt(lambda: executor_secret.appended(text, executor_secret.need(json.loads(text)["deploy"], unit)))
