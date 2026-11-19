"""pubdeploy's suite. The steps it does not define (`it succeeds`, `it prints
...`, files, stand-ins) are pubtest's (its GRAMMAR.md); pubtest's pytest
plugin loads them.

The deploy scenarios run in pubdeploy.testing's world (pytest.ini sets
pubdeploy_testing). The walk here also loads pubsec's types, so this suite's
own World patches them: the plugin patches only pubdeploy.

What every steps module shares lives here: the release commit pubdeploy pins
its workflows by, and the built `pubdeploy` that `Given the program under
test is "pubdeploy"` runs: the one installed beside the Python running this
suite, unless PUBDEPLOY_BIN_DIR names another.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest
from pytest_bdd import given, parsers, then

from pubdeploy.testing.world import FakeWriter, World

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


# --- the deploy world, with pubsec's types patched where pubsec is installed -------------------


class SuiteWorld(World):
    """pubdeploy.testing's world, and pubsec's types and hook, which the walk
    here loads by their entry points: their writer, generator and gcloud
    pointed at the world."""

    def patch(self, monkeypatch) -> None:
        super().patch(monkeypatch)
        if importlib.util.find_spec("pubsec") is None:
            return
        import pubsec.needs.bitwarden as bitwarden  # noqa: PLC0415
        import pubsec.walk  # noqa: PLC0415
        monkeypatch.setattr(pubsec.walk, "_writers", {})
        monkeypatch.setattr(pubsec.walk, "ask_hidden", lambda prompt: self.outputs.append(prompt) or self.token)
        monkeypatch.setattr(pubsec.walk, "BitwardenWriter", lambda token, project: FakeWriter(self, token))
        made = bitwarden.generate

        def generate(shape):
            value = made(shape)
            self.values.append(value)
            return value
        monkeypatch.setattr(bitwarden, "generate", generate)
        monkeypatch.setattr("pubsec.needs.gcp.gcloud", self.run_gcloud)


@pytest.fixture
def deploy_world_class() -> type[World]:
    return SuiteWorld


@given("PUBSEC_WRITE_TOKEN_FILE names the write token's file")
def token_file(world, monkeypatch):
    import pubsec.walk  # noqa: PLC0415
    world.env["PUBSEC_WRITE_TOKEN_FILE"] = "/var/run/secrets/bitwarden-write/token"
    world.hook_terminal = []

    def prepare(ctx, plan, terminal):  # as pubsec's, which reads the file without a terminal
        world.hook_terminal.append(terminal)
        if not terminal and ctx.env.get("PUBSEC_WRITE_TOKEN_FILE"):
            ctx.bitwarden_writer = FakeWriter(world, world.token)
    monkeypatch.setattr(pubsec.walk, "prepare", prepare)


@then("the hook was called without a terminal")
def hook_without_terminal(world):
    assert world.hook_terminal and not any(world.hook_terminal), world.hook_terminal
