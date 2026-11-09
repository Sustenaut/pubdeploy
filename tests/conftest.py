"""pubdeploy's suite. The steps it does not define here (`it succeeds`, `it
prints ...`) are pubkit's plugin's.

Steps and fixtures more than one steps module uses live here: the scratch
repository, running the `pubdeploy` command in it, and its files. pytest-bdd
registers a step only in the module that defines it, or in a conftest.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest
from pytest_bdd import given, parsers, then, when


@pytest.fixture(autouse=True)
def no_release_commit(monkeypatch):
    """A source tree has no release commit, so pubdeploy pins its own
    workflows by tag unless a scenario gives it one."""
    monkeypatch.delenv("PUBDEPLOY_RELEASE_COMMIT", raising=False)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    return root


def pubdeploy():
    """The `pubdeploy` installed beside the Python running this suite."""
    found = shutil.which("pubdeploy", path=str(Path(sys.executable).parent))
    assert found, "pubdeploy is not installed in this environment; run `make venv`"
    return found


@pytest.fixture
def env():
    return {}


@given("an empty repository")
def empty(repo):
    pass


@given(parsers.parse('the file "{path}" reads "{text}"'))
@when(parsers.parse('the file "{path}" reads "{text}"'))
def file_reads(repo, path, text):
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text + "\n")


@when(parsers.re(r'I run pubdeploy (?P<args>(?:"[^"]*" ?)+)'), target_fixture="result")
def run_pubdeploy(repo, run, env, args):
    variables = {k: v for k, v in env.items() if k != "resolved"}
    return run(pubdeploy(), *args.strip().strip('"').split('" "'), cwd=repo, env=variables)


@given(parsers.parse('pubdeploy is a release whose tag names "{commit}"'))
def released(env, commit):
    env["PUBDEPLOY_RELEASE_COMMIT"] = commit


@then(parsers.parse("the repository has {paths}"))
def has(repo, paths):
    for path in paths.split(", "):
        assert (repo / path.strip('"')).is_file(), path


@then(parsers.parse('"{path}" contains "{text}"'))
def contains(repo, path, text):
    assert text in (repo / path).read_text()


@then(parsers.parse('"{path}" does not contain "{text}"'))
def lacks(repo, path, text):
    assert text not in (repo / path).read_text()
