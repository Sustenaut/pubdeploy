"""The checks of pubdeploy's code that were in pubkit's test_deploy_sync.py
when the walk was pubkit's: providers.bump, a type no installed package
offers, the trigger rewrite, pubsec's types without pubsec, the provider
contract and the sustenaut.walk hook."""

from __future__ import annotations

import json
import re
from dataclasses import fields
from pathlib import Path
from types import SimpleNamespace

import pytest

from deploy_world import FIXTURE
from pubdeploy import prepare, providers
from pubdeploy.model import Context, Need
from pubdeploy.registry import BUILTIN, lacking, types
from pubdeploy.schema import need_problems
from pubdeploy.units import retrigger, trigger_problems

ROOT = Path(__file__).resolve().parents[2]
WHEEL = "https://github.com/example-org/example-needs/releases/download/v1.0.0/example_needs-1.0.0-py3-none-any.whl"
PUSHED = """name: deploy
on:
  push:
    branches: [main]
  workflow_dispatch: {}
permissions:
  contents: read
  packages: write
jobs:
  deploy:
    uses: example-org/pubdeploy/.github/workflows/k8s-deploy.yml@v0.1.0
    with:
      image: ghcr.io/example-org/example
      deploys: |
        k8s example
    secrets: inherit
"""


def test_bump_moves_a_provider_to_its_latest_release(tmp_path):
    newer = WHEEL.replace("1.0.0", "1.1.0")
    (tmp_path / "pubkit.json").write_text(json.dumps({"kind": "service", "deploy": {"namespace": "example", "providers": [
        {"distribution": "example-needs", "wheel": WHEEL, "sha256": "0" * 64}]}}, indent=2))

    def gh(method, path, body):
        assert (method, path) == ("GET", "repos/example-org/example-needs/releases/latest")
        return {"assets": [{"name": "example_needs-1.1.0.tar.gz", "browser_download_url": "x"},
                           {"name": "example_needs-1.1.0-py3-none-any.whl", "browser_download_url": newer,
                            "digest": "sha256:" + "1" * 64}]}
    assert providers.bump(tmp_path, gh) == ["updated  pubkit.json (deploy.providers example-needs: 1.1.0)"]
    given = json.loads((tmp_path / "pubkit.json").read_text())["deploy"]["providers"][0]
    assert given == {"distribution": "example-needs", "wheel": newer, "sha256": "1" * 64}
    assert providers.bump(tmp_path, lambda *_: {"assets": [{"name": "example_needs-1.1.0-py3-none-any.whl",
                                                           "browser_download_url": newer, "digest": "sha256:1"}]}) == []


def test_bump_leaves_a_provider_without_a_sha256_saying_so(tmp_path):
    (tmp_path / "pubkit.json").write_text(json.dumps({"kind": "service", "deploy": {"namespace": "example", "providers": [
        {"distribution": "example-needs", "wheel": WHEEL}]}}, indent=2))
    before = (tmp_path / "pubkit.json").read_text()
    lines = providers.bump(tmp_path, lambda *_: (_ for _ in ()).throw(AssertionError("no release is read")))
    assert lines == ["left     deploy.providers example-needs: it has no sha256 to move; give it the wheel's sha256"]
    assert (tmp_path / "pubkit.json").read_text() == before


def test_a_type_no_installed_package_offers_names_the_providers():
    assert need_problems({"type": "example.database"}, 0, types(), FIXTURE, ["example-needs"]) == [
        "deploy: needs[0]: example.database is no type of need pubdeploy or an installed package offers; it would "
        "be example-needs's, of deploy.providers, which ./pubdeploy runs with: run ./pubdeploy, or install "
        "example-needs"]


def test_the_trigger_rewrite_satisfies_the_check():
    assert trigger_problems(PUSHED, "deploy.yml")
    rewritten = retrigger(PUSHED)
    assert trigger_problems(rewritten, "deploy.yml") == []
    assert "push:" not in rewritten and "branches: [main]\n  workflow_dispatch" not in rewritten
    assert rewritten.count("workflow_dispatch") == 1 and "  actions: read\n  contents: read\n" in rewritten


def test_the_trigger_rewrite_adds_workflow_dispatch():
    rewritten = retrigger(PUSHED.replace("  workflow_dispatch: {}\n", ""))
    assert "  workflow_dispatch: {}\n" in rewritten and trigger_problems(rewritten, "deploy.yml") == [], rewritten


@pytest.mark.parametrize("text", [
    "on: push\npermissions: { contents: read }\njobs: {}\n",
    "on: [push, workflow_dispatch]\njobs: {}\n",
])
def test_the_trigger_rewrite_takes_the_short_forms(text):
    rewritten = retrigger(text.replace("jobs: {}", "jobs:\n  d:\n    uses: example-org/pubdeploy/.github/workflows/"
                                                   "k8s-deploy.yml@v0.1.0"))
    assert trigger_problems(rewritten, "deploy.yml") == [], rewritten


def test_without_pubsec_its_types_name_it():
    own = {kind.type: kind for kind in BUILTIN}
    assert need_problems({"type": "bitwarden.secret", "name": "x"}, 0, own, FIXTURE) == [
        "deploy: needs[0]: bitwarden.secret is pubsec's: list pubsec in deploy.providers, as `pubkit sync` does, "
        "and run ./pubdeploy, which runs it"]
    assert lacking([Need("k8s.secret", "x", {}), Need("github.secret", "Y", {})], own) == [
        "deploy: github.secret, k8s.secret are pubsec's, which is not installed: list pubsec in deploy.providers, "
        "as `pubkit sync` does, and run ./pubdeploy, which runs it"]


# The Context's names a provider may use, which the README lists under
# "Provider contract": changing one breaks pubsec and pg-backup.
CONTRACT = {"root", "config", "block", "namespace", "unit", "channel", "kubectl", "server", "gh", "send",
            "bitwarden_writer", "http_get", "env", "now", "rendered", "offline", "slug", "zones", "resolve",
            "values", "types", "needs", "results", "sleep", "dispatched"}


def test_the_provider_contract_is_on_the_context():
    assert CONTRACT <= {f.name for f in fields(Context)}


def test_the_readme_lists_the_provider_contract():
    section = (ROOT / "README.md").read_text().split("### Provider contract", 1)[1].split("\n## ", 1)[0]
    missing = [name for name in CONTRACT if not re.search(rf"`{name}[`(]", section)]
    assert not missing, missing


def test_a_walk_hook_that_fails_is_said_and_the_walk_goes_on(capsys):
    secret = "canary-7f3e"

    def broken(ctx, plan, terminal):
        raise ValueError(f"the token is {secret}")

    def says(ctx, plan, terminal):
        ctx.bitwarden_writer = "a writer"
        return "a line"
    points = [SimpleNamespace(name="broken", load=lambda: broken), SimpleNamespace(name="says", load=lambda: says)]
    ctx = Context.for_tests()
    prepare(ctx, [], True, points)
    err = capsys.readouterr().err
    assert "pubdeploy: deploy: the sustenaut.walk hook broken failed (ValueError)" in err and "a line" in err
    assert secret not in err and ctx.bitwarden_writer == "a writer"
