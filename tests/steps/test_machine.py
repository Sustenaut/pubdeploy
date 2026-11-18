"""Steps for a unit's machine: compiled from needs, checked, driven alike by
python-statemachine and XState v5, and pubdeploy's machine and walk --need against the
example service. The shared deploy steps are deploy_steps.py's."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from pytest_bdd import given, parsers, scenarios, then, when

from deploy_steps import *  # noqa: F403 - the shared steps, and the fixtures pytest-bdd keeps them as
from pubdeploy import machine

scenarios("machine.feature")

XSTATE = Path(__file__).resolve().parents[1] / "xstate"


def need(i: str, after=(), **more) -> dict:
    return {"id": i, "type": i.split(":")[0], "grade": more.pop("grade", "auto"), "after": list(after),
            "seconds": 60.0, **more}


@pytest.fixture
def unit():
    return {"needs": [], "section": None, "machine": None, "problems": None}


@given(parsers.parse('the needs "{a}", "{b}" after "{c}", and "{d}"'))
def three_needs(unit, a, b, c, d):
    unit["needs"] = [need(a), need(b, [c]), need(d)]


@given(parsers.parse('the needs "{a}", "{b}" and "{c}" of a serial kind'))
def serial_needs(unit, a, b, c):
    unit["needs"] = [need(x, serial=True) for x in (a, b, c)]


@given(parsers.parse('the needs "{a}" and "{b}", both filling the Secret "{secret}"'))
def shared_secret(unit, a, b, secret):
    unit["needs"] = [need(x, params={"secret": {"name": secret}}) for x in (a, b)]


@given(parsers.parse('the needs "{a}" graded human, and "{b}" that continues on Stop, warning "{warning}"'))
def human_and_continue(unit, a, b, warning):
    unit["needs"] = [need(a, grade="human"), need(b, stop="continue", stop_warning=warning)]


@given(parsers.re(r"the run section (?P<text>\{.*\})"))
def run_section(unit, text):
    unit["section"] = json.loads(text)


@given(parsers.parse('every need in mode "{mode}"'))
def every_mode(unit, mode):
    unit["section"] = {"schema": 1, "default_mode": mode}


@when("the machine is compiled")
def compiled(unit):
    unit["machine"] = machine.compile(unit["needs"], unit["section"])


@when("the run section is checked")
def section_checked(unit):
    unit["problems"] = machine.problems({"run": unit["section"]}, unit["needs"])


def regions(unit) -> dict:
    return unit["machine"]["states"]["running"]["states"]


@then("it validates")
def validates(unit):
    assert machine.validate(unit["machine"]) == []
    machine.load(unit["machine"])  # python-statemachine takes it too


@then(parsers.parse('every region is in mode "{mode}", and the machine runs {n:d} at a time'))
def every_region(unit, mode, n):
    assert {r["meta"]["mode"] for r in regions(unit).values()} == {mode}
    assert unit["machine"]["meta"]["parallel"] == n


@then(parsers.parse('the machine runs {n:d} at a time'))
def at_a_time(unit, n):
    assert unit["machine"]["meta"]["parallel"] == n


@then(parsers.parse('the region "{key}" is after "{other}"'))
def region_after(unit, key, other):
    assert other in regions(unit)[key]["meta"]["after"], regions(unit)[key]["meta"]


@then(parsers.parse('the region "{key}" is after nothing'))
def after_nothing(unit, key):
    assert regions(unit)[key]["meta"]["after"] == []


@then(parsers.parse('the region "{key}" is in mode "{mode}", and its found state is final'))
def mode_found_final(unit, key, mode):
    assert regions(unit)[key]["meta"]["mode"] == mode
    assert regions(unit)[key]["states"]["found"] == {"type": "final"}


@then(parsers.parse('the problem is "{text}"'))
def problem_is(unit, text):
    assert any(text in p for p in unit["problems"]), unit["problems"]


@then(parsers.parse('the region "{key}" never enters fulfilling'))
def never_fulfils(unit, key):
    found = regions(unit)[key]["states"]["found"]
    assert found == {"type": "final"}


@then(parsers.parse('the region "{key}" stops with "{stop}", warning "{warning}"'))
def stops_with(unit, key, stop, warning):
    meta = regions(unit)[key]["meta"]
    assert (meta["stop"], meta["stop_warning"]) == (stop, warning)


@then("a machine whose region goes to a state it lacks, or continues on Stop without a warning, does not validate")
def invalid_machines():
    good = machine.compile([need("upstream:u"), need("deploy.rollout:r", stop="continue", stop_warning="w")])
    assert machine.validate(good) == []
    broken = json.loads(json.dumps(good))
    part = broken["states"]["running"]["states"]["upstream_u"]
    part["states"]["waiting"]["on"]["start.upstream_u"] = {"target": "nowhere"}
    assert any("goes to nowhere" in p for p in machine.validate(broken))
    del broken["states"]["running"]["states"]["deploy_rollout_r"]["meta"]["stop_warning"]
    assert any("continue needs a stop_warning" in p for p in machine.validate(broken))
    assert machine.validate({"initial": "else"})[0].startswith("the machine must be")
    with pytest.raises(ValueError):
        machine.load(broken)


SCRIPTS = {
    "check-only, all clean": [
        {"type": "start.k8s_namespace_a"}, {"type": "checked.k8s_namespace_a", "state": "ready"},
        {"type": "start.k8s_secret_s"}, {"type": "start.upstream_u"},
        {"type": "checked.k8s_secret_s", "state": "ready"}, {"type": "checked.upstream_u", "state": "ready"}],
    "a failed fulfil blocks its dependant": [
        {"type": "start.k8s_namespace_a"}, {"type": "start.upstream_u"},
        {"type": "checked.k8s_namespace_a", "state": "missing"}, {"type": "checked.upstream_u", "state": "ready"},
        {"type": "approved.k8s_namespace_a"}, {"type": "fulfilled.k8s_namespace_a", "ok": False},
        {"type": "predecessor_failed.k8s_secret_s"}],
    "Stop in the middle": [
        {"type": "start.k8s_namespace_a"}, {"type": "start.upstream_u"},
        {"type": "checked.upstream_u", "state": "ready"}, {"type": "checked.k8s_namespace_a", "state": "drift"},
        {"type": "approved.k8s_namespace_a"}, {"type": "stop"}],
}


@pytest.fixture(scope="session")
def xstate_installed():
    if not (XSTATE / "node_modules" / "xstate").is_dir():
        npm = shutil.which("npm")
        assert npm, "npm is not installed: the XState scenarios need Node"
        subprocess.run([npm, "ci", "--silent", "--no-audit", "--no-fund"], cwd=XSTATE, check=True)
    return XSTATE


@when(parsers.parse('the script "{name}" drives the machine in python-statemachine and in XState v5'))
def drives(unit, name, tmp_path, xstate_installed):
    compiled_machine = machine.compile(unit["needs"], unit["section"])
    script = SCRIPTS[name]
    chart = machine.load(compiled_machine)
    python = [machine.states(chart)]
    for event in script:
        machine.send(chart, event)
        python.append(machine.states(chart))
    (tmp_path / "machine.json").write_text(json.dumps(compiled_machine))
    (tmp_path / "script.json").write_text(json.dumps(script))
    ran = subprocess.run(["node", str(xstate_installed / "run.mjs"), str(tmp_path / "machine.json"),
                          str(tmp_path / "script.json")], capture_output=True, text=True, check=True)
    unit["python"], unit["xstate"] = python, json.loads(ran.stdout)


@then("both give the same states after each event")
def same_states(unit):
    assert unit["python"] == unit["xstate"], (unit["python"], unit["xstate"])


@then(parsers.parse("the last states are {last}"))
def last_states(unit, last):
    want = dict(part.split(" ") for part in last.split(", "))
    assert unit["python"][-1] == want


@then(parsers.parse('it prints a machine that validates, with a region for "{need_id}" after "{other}"'))
def prints_machine(world, need_id, other):
    printed = json.loads(world.stdout)
    assert machine.validate(printed) == []
    found = {r["meta"]["need"]: r for r in printed["states"]["running"]["states"].values()}
    assert other in found[need_id]["meta"]["after"]


@then(parsers.parse('it prints a machine with "{a}" in mode "{ma}" and "{b}" in mode "{mb}"'))
def prints_modes(world, a, ma, b, mb):
    found = {r["meta"]["need"]: r["meta"]["mode"] for r in json.loads(world.stdout)["states"]["running"]["states"].values()}
    assert (found[a], found[b]) == (ma, mb), found


@then(parsers.parse('it prints only "{a}" and "{b}"'))
def prints_only(world, a, b):
    named = {line.split()[1] for line in world.stdout.splitlines() if len(line.split()) > 1
             and line.split()[0] in ("ready", "missing", "drift", "blocked", "unknown")}
    assert named == {a, b}, world.stdout


@then(parsers.parse('kubectl made no Job and no other Secret than "{secret}"'))
def only_that_secret(world, secret):
    applied = [d for given in world.cluster.get("stdin") or [] for d in yaml.safe_load_all(given)]
    assert {d["metadata"]["name"] for d in applied if d.get("kind") == "Secret"} == {secret}
    assert not [c for c in world.calls["kubectl"] if "create" in c and "job" in c], world.calls["kubectl"]


@given(parsers.parse('the "{kind}" check takes {seconds:g} second'))
def slow(monkeypatch, kind, seconds):
    import time  # noqa: PLC0415
    from pubdeploy.registry import types  # noqa: PLC0415
    t = types()[kind]
    check = t.check

    def slowly(need, ctx):
        time.sleep(seconds)
        return check(need, ctx)
    monkeypatch.setattr(t, "check", slowly)
