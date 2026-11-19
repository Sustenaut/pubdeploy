"""The canary: no secret value ever reaches what `pubrules deploy` prints.

Every fake Secret value, every fake Bitwarden value, the write token, every
fake key JSON and what the deploy channel shows of a Secret hold CANARY, and
every value a fulfil generates is kept as one too. Each test drives the
checks, and the fulfils, through a state where values are read, judged,
generated and moved, and what comes out (stdout, stderr, the journal, any
exception's text, and every argv kubectl, ssh, gcloud or gh was given) must
not hold one: a value moves on a standard input only. This test must never
be weakened: a check or a fulfil that needs to show a value is wrong, not
the test."""

from __future__ import annotations

import json

import pytest
from pubdeploy import load
from pubdeploy.model import Need, Result
from pubdeploy.registry import types
from pubdeploy.testing.world import CANARY, run
from pubdeploy.walk import walk
from pytest_bdd import given, parsers, scenarios, then, when

# Every scenario runs in the deploy world, under its canary (pubdeploy.testing).
pytestmark = pytest.mark.usefixtures("world")

scenarios("deploy-canary.feature")

STATES = {
    "all well": lambda w: None,
    "a bad cookie in the cluster": lambda w: w.cluster["namespaces"]["example"]["secrets"]["example-page-secrets"]
    .update({"cookie-secret": (CANARY + "+/+/").encode()}),
    "a bad cookie in Bitwarden": lambda w: w.env.update({"EXAMPLE_COOKIE_SECRET": CANARY + "+/+/" * 6}),
    "a variable that differs from Bitwarden": lambda w: w.env.update({"EXAMPLE_USER": CANARY + "-other"}),
    "a Secret without its key": lambda w: w.cluster["namespaces"]["example"]["secrets"]["example-files"]
    .update({"other": CANARY.encode()}) or w.cluster["namespaces"]["example"]["secrets"]["example-files"]
    .pop("token"),
    "nothing reachable": lambda w: w.http.clear(),
    "kubectl forbidden": lambda w: w.cluster.update({"forbidden": True}),
    "GitHub forbidden": lambda w: w.github.update({"forbidden": True}),
    "outside with-secrets": lambda w: w.env.pop("PUBKIT_SECRETS_PROJECT"),
    "nothing in the cluster": lambda w: w.cluster["namespaces"].pop("example") and None,
    "no cookie in Bitwarden, nor its Secret": lambda w: w.env.pop("EXAMPLE_COOKIE_SECRET") and
    w.cluster["namespaces"]["example"]["secrets"].pop("example-page-secrets") and None,
    "over the deploy channel": lambda w: setattr(w, "channel", "deploy"),
    "over the deploy channel, before secret-keys": lambda w: setattr(w, "channel", "deploy") or
    w.cluster.update({"secret_keys_verb": False}),
    "GitHub without its secrets": lambda w: w.github.update({"secrets": set()}),
    "a key to make": lambda w: w.block["needs"].append({
        "type": "gcp.service-account-key", "account": "example-files", "project": "example-project",
        "bitwarden": "example-files-key"}),
    "a key Bitwarden refuses": lambda w: w.block["needs"].append({
        "type": "gcp.service-account-key", "account": "example-files", "project": "example-project",
        "bitwarden": "example-files-key"}) or setattr(w, "bitwarden_refuses", True),
    "kubectl refusing writes": lambda w: w.cluster["namespaces"]["example"]["secrets"].pop("example-files")
    and w.cluster.update({"refuse_writes": True}),
}


@given(parsers.parse('the deploy world with {state}'))
def in_state(world, state):
    STATES[state](world)


@when(parsers.parse('pubdeploy runs "{argv}"'), target_fixture="result")
def runs(world, ctx, argv):
    run(world, ctx, *argv.split())
    return ctx.outcome


@then("no value is printed, passed to a program or kept in the journal")
def no_value(world):
    assert world.code in (0, 1)
    for text in world.outputs:
        assert CANARY not in text
    assert not world.leaked(), world.leaked()[0][:500]


class Leaky:
    """A need type whose check or fulfil raises, its message holding a value."""

    type, budget, offline, schema = "example.leaky", 1.0, True, {}

    def __init__(self, grade, raises, message):
        self.grade, self.raises, self.message = grade, raises, message

    def default_name(self, params):
        return None

    def depends_on(self, need, needs):
        return []

    def check(self, need, ctx):
        if self.raises == "check":
            raise ValueError(self.message)
        return Result("missing", "not there")

    def fulfil(self, need, ctx):
        if self.raises == "fulfil":
            raise ValueError(self.message)
        raise NotImplementedError("phase 2")


@given(parsers.parse('a need type "{kind}" whose {part} raises, saying "{message}"'))
def leaky(world, kind, part, message):
    world.kinds = {kind: Leaky("none" if part == "check" else "auto", part, message)}


def walked(world, ctx, also_fulfil):
    from pubdeploy.walk import fulfil  # noqa: PLC0415
    (kind,) = world.kinds
    need = Need(kind, "one", {})
    context = world.context()

    def action():
        journal = walk({need.id: need}, world.kinds, context, service={})
        if also_fulfil:
            journal = fulfil(journal, world.kinds, context, {need.id})
        world.journal = journal.document()
        return json.loads(journal.json())
    ctx.attempt(action)


@when(parsers.parse('its need "one" is walked'))
def walk_one(world, ctx):
    walked(world, ctx, False)


@when(parsers.parse('its need "one" is walked and fulfilled'))
def walk_and_fulfil_one(world, ctx):
    walked(world, ctx, True)


@when("the example service's needs are walked")
def walk_example(world, ctx):
    context = world.context()

    def action():
        journal = walk(load(world.root, world.config, context).needs, types(), context, service={})
        world.journal = journal.document()
        return {"journal": json.loads(journal.json()),
                "results": sorted({type(r).__name__ for _, r in journal.entries})}
    ctx.attempt(action)


@then(parsers.parse('Bitwarden was given a value the walk generated for "{name}"'))
def generated(world, name):
    assert world.written[name] in world.values, "Bitwarden was given a value the walk did not generate"
