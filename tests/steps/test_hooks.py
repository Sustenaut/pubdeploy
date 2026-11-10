"""What pubkit calls of pubdeploy (hooks.py), and that pubdeploy imports
nothing of pubkit's."""

from __future__ import annotations

import json
import subprocess
import sys
from importlib.metadata import entry_points
from pathlib import Path

from pubdeploy import hooks
CALLER = ".github/workflows/deploy-check.yml"

SRC = Path(__file__).resolve().parents[2] / "src" / "pubdeploy"
WHEEL = "https://github.com/Sustenaut/pubdeploy/releases/download/v{0}/pubdeploy-{0}-py3-none-any.whl"
COMMIT = "a" * 40


def test_the_hooks_are_offered_under_their_groups():
    assert [p.value for p in entry_points(group="sustenaut.sync") if p.name == "pubdeploy"] == ["pubdeploy.hooks:check"]
    assert [p.value for p in entry_points(group="sustenaut.bump") if p.name == "pubdeploy"] == ["pubdeploy.hooks:bump"]


def test_pubdeploy_imports_nothing_of_pubkit():
    """Every module loads with pubkit unimportable."""
    names = sorted(f"pubdeploy.{p.relative_to(SRC).with_suffix('').as_posix().replace('/', '.')}".removesuffix(".__init__")
                   for p in SRC.rglob("*.py"))
    script = ("import sys, importlib\n"
              "class Block:\n"
              "    def find_spec(self, name, path=None, target=None):\n"
              "        if name == 'pubkit' or name.startswith('pubkit.'): raise ImportError('pubkit is blocked')\n"
              "sys.meta_path.insert(0, Block())\n"
              f"for n in {names!r}: importlib.import_module(n)\n")
    done = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr


def test_without_a_deploy_block_the_sync_hook_says_nothing(tmp_path):
    assert hooks.check(tmp_path, {"kind": "utility"}, check=True) == ([], False)


def test_the_sync_hook_seeds_no_scheduled_walk(tmp_path, monkeypatch):
    monkeypatch.setattr("pubdeploy.offline_lines", lambda root, config: ([], False))
    config = {"kind": "service", "deploy": {"namespace": "example"}}
    assert hooks.check(tmp_path, config, check=True) == ([], False)
    assert hooks.check(tmp_path, config, check=False) == ([], False)
    assert not (tmp_path / ".github").exists()


def test_writing_a_disagreement_is_said_and_fails_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr("pubdeploy.offline_lines", lambda root, config: (["pubdeploy: deploy: drift"], True))
    (tmp_path / CALLER).parent.mkdir(parents=True)
    (tmp_path / CALLER).write_text("kept\n")
    config = {"kind": "service", "deploy": {"namespace": "example"}}
    assert hooks.check(tmp_path, config, check=False) == (["pubdeploy: deploy: drift"], False)
    assert hooks.check(tmp_path, config, check=True) == (["pubdeploy: deploy: drift"], True)


def bumped_repo(tmp_path, version, trigger):
    (tmp_path / "pubkit.json").write_text(json.dumps({"kind": "service", "deploy": {
        "namespace": "example", "providers": [{"distribution": "pubdeploy", "wheel": WHEEL.format(version),
                                               "sha256": "b" * 64}]}}))
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "deploy.yml").write_text(
        f"name: deploy\non:\n{trigger}\npermissions: {{ contents: read, packages: write }}\njobs:\n  deploy:\n"
        f"    uses: Sustenaut/pubdeploy/.github/workflows/k8s-deploy.yml@v0.0.9\n")
    (workflows / "deploy-check.yml").write_text(
        f"jobs:\n  check:\n    uses: Sustenaut/pubdeploy/.github/workflows/deploy-check.yml@{'c' * 40} # v0.0.9\n")
    return workflows


def fake_gh(method, path, body=None):
    assert method == "GET"
    if path == "repos/Sustenaut/pubdeploy/git/ref/tags/v0.2.0":
        return {"object": {"type": "tag", "sha": "d" * 40}}
    if path == f"repos/Sustenaut/pubdeploy/git/tags/{'d' * 40}":
        return {"object": {"type": "commit", "sha": COMMIT}}
    raise AssertionError(path)


def test_bump_moves_pubdeploys_workflows_to_the_release_providers_names(tmp_path):
    workflows = bumped_repo(tmp_path, "0.2.0", "  workflow_run: { workflows: [main], types: [completed], branches: [main] }\n"
                                               "  workflow_dispatch: {}")
    lines = hooks.bump(tmp_path, gh=fake_gh, find=lambda wheel, gh: None)
    assert sorted(lines) == [f"updated  .github/workflows/deploy-check.yml (pubdeploy@{COMMIT} # v0.2.0)",
                             f"updated  .github/workflows/deploy.yml (pubdeploy@{COMMIT} # v0.2.0)"]
    assert f"k8s-deploy.yml@{COMMIT} # v0.2.0" in (workflows / "deploy.yml").read_text()
    assert f"deploy-check.yml@{COMMIT} # v0.2.0" in (workflows / "deploy-check.yml").read_text()


def test_bump_rewrites_a_deploy_started_by_push(tmp_path):
    workflows = bumped_repo(tmp_path, "0.2.0", "  push: { branches: [main] }")
    hooks.bump(tmp_path, gh=fake_gh, find=lambda wheel, gh: None)
    text = (workflows / "deploy.yml").read_text()
    assert "push:" not in text and "workflow_run: { workflows: [main]" in text and "workflow_dispatch: {}" in text
    assert "actions: read" in text


def test_bump_pins_by_tag_when_the_tag_cannot_be_read(tmp_path):
    from pubdeploy.github import ApiError  # noqa: PLC0415

    def refused(method, path, body=None):
        raise ApiError("gh api -X GET x: Not Found (HTTP 404)")

    workflows = bumped_repo(tmp_path, "0.2.0", "  workflow_run: { workflows: [main] }\n  workflow_dispatch: {}")
    hooks.bump(tmp_path, gh=refused, find=lambda wheel, gh: None)
    assert "deploy-check.yml@v0.2.0" in (workflows / "deploy-check.yml").read_text()


def test_bump_without_pubdeploy_in_providers_moves_no_workflow(tmp_path):
    (tmp_path / "pubkit.json").write_text(json.dumps({"kind": "service", "deploy": {"namespace": "example"}}))
    assert hooks.bump(tmp_path, gh=fake_gh, find=lambda wheel, gh: None) == []


def test_deploy_ssh_passes_its_own_tests():
    """actions/deploy-ssh/test.sh, which pubkit's CI ran while the action was pubkit's."""
    script = Path(__file__).resolve().parents[2] / "actions" / "deploy-ssh" / "test.sh"
    done = subprocess.run(["bash", str(script)], capture_output=True, text=True, check=False, timeout=120)
    assert done.returncode == 0, done.stdout + done.stderr
