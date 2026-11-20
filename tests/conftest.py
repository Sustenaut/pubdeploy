"""pubdeploy's suite. The steps it does not define (`it succeeds`, `it prints
...`, files, stand-ins) are pubtest's (its GRAMMAR.md); pubtest's pytest
plugin loads them.

The deploy scenarios run in pubdeploy.testing's world (pytest.ini sets
pubdeploy_testing). The walk implies need types pubdeploy does not offer
(registry.PUBSEC_TYPES); this suite's world loads them from a stand-in
provider (standin_provider.py), built on pubdeploy.contract alone, so the
suite needs no provider installed and imports none.

What every steps module shares lives here: the release commit pubdeploy pins
its workflows by, and the built `pubdeploy` that `Given the program under
test is "pubdeploy"` runs: the one installed beside the Python running this
suite, unless PUBDEPLOY_BIN_DIR names another.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from pytest_bdd import given, parsers, then

import standin_provider
from pubdeploy.testing.world import Providers, World

os.environ.setdefault("PUBDEPLOY_BIN_DIR", str(Path(sys.executable).parent))


@pytest.fixture(autouse=True)
def no_release_commit(monkeypatch):
    """A source tree has no release commit, so pubdeploy pins its own
    workflows by tag unless a scenario gives it one."""
    monkeypatch.delenv("PUBDEPLOY_RELEASE_COMMIT", raising=False)


def refusal(ctx):
    ctx.refusal_read = True
    assert ctx.refused is not None, f"it was not refused: the result is {ctx.result!r}"
    return ctx.refused.error


@then(parsers.parse('the refusal is a "{name}"'))
def refusal_is_a(ctx, name):
    """The refusal is of the class named, or of one it derives from."""
    error = refusal(ctx)
    assert name in [c.__name__ for c in type(error).__mro__], f"it was refused with {error!r}"


@then(parsers.parse('the refusal\'s "{key}" is "{wanted}"'))
def refusal_key(ctx, key, wanted):
    """The refusal's attribute, as a step's value is compared; "message" is its text."""
    from pubtest.core import same  # noqa: PLC0415
    error = refusal(ctx)
    got = str(error) if key == "message" else getattr(error, key)
    assert same(got, wanted), f"the refusal's {key} is {got!r}, not {wanted}"


@given(parsers.parse('a stand-in "{name}" that prints the file "{path}"'))
def standin_prints_file(ctx, tmp_path, name, path):
    """A stand-in whose output is a file of the scratch directory, as it is now."""
    from pubtest.steps.standins import _refresh, standins  # noqa: PLC0415
    standins(ctx, tmp_path).add(name, out=(ctx.directory / path).read_text())
    _refresh(ctx)


# --- the deploy world, its providers the stand-in's ---------------------------------------------


class SuiteWorld(World):
    """pubdeploy.testing's world, whose walk loads the stand-in provider's types and hook."""

    def __init__(self, root) -> None:
        super().__init__(root)
        self.hook_terminal: list[bool] = []  # how the stand-in's hook was called, each time
        self.hook_writer = None  # the writer it gives, once a token is asked for

    def providers(self) -> Providers:
        needs, hooks = standin_provider.points()
        return Providers(tuple(needs), tuple(hooks))

    def patch(self, monkeypatch) -> None:
        super().patch(monkeypatch)
        monkeypatch.setattr(standin_provider, "WORLD", self)


@pytest.fixture
def deploy_world_class() -> type[World]:
    return SuiteWorld


@given("PUBSEC_WRITE_TOKEN_FILE names the write token's file")
def token_file(world):
    world.env["PUBSEC_WRITE_TOKEN_FILE"] = "/var/run/secrets/bitwarden-write/token"


@then("the hook was called without a terminal")
def hook_without_terminal(world):
    assert world.hook_terminal and not any(world.hook_terminal), world.hook_terminal


@given("the program finds the stand-in provider")
def standin_on_path(monkeypatch):
    """A `pubdeploy` the scenario starts loads the stand-in's types and hook, as its
    metadata beside it says, from PYTHONPATH: it is never installed."""
    here = Path(standin_provider.__file__).resolve().parent
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([str(standin_provider.DIST.parent), str(here)]))
