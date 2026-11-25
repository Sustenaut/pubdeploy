"""Steps for pubdeploy's executor: a live run walked against a stand-in engine, which keeps
each event as the convergence engine does (its seq the need's next, its from the need's
state), with stand-in walks, whose journals the scenario gives. The HTTP scenarios give
HttpEngine a stand-in opener; the CLI's is pubtest's."""

from __future__ import annotations

import io
import json
import threading
import time
import urllib.error

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from pubdeploy import executor

scenarios("executor.feature")

SCHEMA = "deploy-journal/2"


def journal(name: str, state: str, summary: str = "") -> str:
    return json.dumps({"schema": SCHEMA, "needs": [{"id": name, "state": state, "summary": summary or state}]})


class Engine:
    """A run, and the events it keeps: the convergence engine's rules for an executor's event."""

    def __init__(self, world):
        self.world, self.lock = world, threading.Lock()
        self.events: list[dict] = []
        self.exits: list[int] = []
        self.refuse: tuple[str, str] | None = None

    def run(self) -> dict:
        w = self.world
        with self.lock:
            needs = {n: {**spec, "state": w.states[n]} for n, spec in w.needs.items()}
            return {"id": "r1", "unit": "app", "state": w.state, "parallel": w.parallel, "needs": needs,
                    "machine": {"states": {"running": {"states": {
                        n.replace(":", "_"): {"meta": {"need": n, "seconds": w.seconds.get(n, 60)}}
                        for n in w.needs}}}},
                    "journal": [], "stopping": w.stopping, "cancelled": sorted(w.cancelled)}

    def post(self, event: dict) -> dict:
        w = self.world
        with self.lock:
            if "executor_exit" in event:
                self.exits.append(event["executor_exit"])
                return {}
            name = event["need"]
            if self.refuse == (name, event["to"]):
                raise executor.Refused(f"409 {name} does not move to {event['to']}")
            assert event["seq"] == w.seqs[name] + 1, event
            assert event["from"] == w.states[name], event
            w.seqs[name], w.states[name] = event["seq"], event["to"]
            self.events.append({**event, "at": time.monotonic()})
            return event


class Proc:
    """A stand-in walk: what it prints, when it ends."""

    def __init__(self, world, name: str, fulfil: bool, argv, env):
        self.world, self.name, self.fulfil = world, name, fulfil
        self.record = {"name": name, "fulfil": fulfil, "argv": argv, "env": env, "start": time.monotonic(),
                       "end": None, "budget": False}
        self.outcome = world.outcome(name, fulfil)
        self.ended: tuple[int, str, str] | None = None
        world.walks.append(self.record)

    def poll(self, timeout: float):
        time.sleep(min(timeout, 0.01))
        if self.ended is None:
            if self.outcome in ("ready", "missing"):
                if time.monotonic() - self.record["start"] >= 0.05:
                    self.ended = (0, journal(self.name, self.outcome), "")
            elif self.outcome == "nojournal":
                self.ended = (1, "", "Traceback\nboom")
            elif self.outcome == "wait" and self.world.release.is_set():
                self.ended = (0, journal(self.name, "ready"), "")
        if self.ended is not None and self.record["end"] is None:
            self.record["end"] = time.monotonic()
        return self.ended

    def terminate(self):
        self.ended = self.ended or (-15, "", "")

    def budget(self):
        self.record["budget"] = True
        self.ended = self.ended or (0, journal(self.name, "unknown", "its budget ended"), "")


class World:
    def __init__(self):
        self.needs: dict[str, dict] = {}
        self.states: dict[str, str] = {}
        self.seqs: dict[str, int] = {}
        self.seconds: dict[str, float] = {}
        self.state, self.parallel, self.stopping = "running", 4, False
        self.cancelled: set[str] = set()
        self.outcomes: dict[tuple[str, bool | None], str] = {}
        self.default = "ready"
        self.walks: list[dict] = []
        self.release = threading.Event()
        self.engine = Engine(self)
        self.code: int | None = None
        self.said: list[str] = []
        self.env: dict[str, str] = {}

    def add(self, name: str, after=(), mode="fulfil", stop="signal"):
        self.needs[name] = {"mode": mode, "grade": "auto", "stop": stop, "after": list(after)}
        self.states[name], self.seqs[name] = "waiting", 0

    def outcome(self, name: str, fulfil: bool) -> str:
        return self.outcomes.get((name, fulfil), self.outcomes.get((name, None), self.default))

    def walking(self) -> int:
        return sum(1 for w in self.walks if w["end"] is None)

    def spawn(self, argv, cwd, env):
        name = argv[argv.index("--need") + 1]
        return Proc(self, name, "--fulfil" in argv, argv, env)

    def moves(self, name: str) -> list[str]:
        return ["waiting", *[e["to"] for e in self.engine.events if e["need"] == name]]

    def last(self, name: str) -> dict:
        return [e for e in self.engine.events if e["need"] == name][-1]


@pytest.fixture
def world():
    return World()


# --- Given


@given(parsers.parse('a running run with the needs "{a}", "{b}" and "{c}" after "{d}"'))
def three_after(world, a, b, c, d):
    world.add(a), world.add(b), world.add(c, after=[d])


@given(parsers.parse('a running run with the needs "{a}", "{b}" and "{c}", {n:d} at a time'))
def three_capped(world, a, b, c, n):
    world.add(a), world.add(b), world.add(c)
    world.parallel = n


@given(parsers.parse('a running run with the need "{a}" in mode check'))
def one_check(world, a):
    world.add(a, mode="check")


@given(parsers.parse('a running run with the need "{a}" of a {s:g} s budget'))
def one_budget(world, a, s):
    world.add(a)
    world.seconds[a] = s


@given(parsers.parse('a running run with the need "{a}"'))
def one(world, a):
    world.add(a)


@given(parsers.parse('an awaiting run with the need "{a}"'))
def awaiting(world, a):
    world.add(a)
    world.state = "awaiting"


@given(parsers.parse('a running run with the needs "{s}" stopping by signal, "{h}" that shortens, '
                     '"{c}" that continues, and "{later}" after "{d}"'))
def stop_classes(world, s, h, c, later, d):
    world.add(s, stop="signal"), world.add(h, stop="shorten"), world.add(c, stop="continue")
    world.add(later, after=[d])


@given(parsers.parse('a running run with the needs "{c}" that continues, and "{o}"'))
def continue_and_other(world, c, o):
    world.add(c, stop="continue"), world.add(o)


@given("every walk finds its need ready")
def all_ready(world):
    world.default = "ready"


@given(parsers.parse('the check of "{a}" finds it missing, and its fulfil leaves it ready'))
def fulfils(world, a):
    world.outcomes[(a, False)], world.outcomes[(a, True)] = "missing", "ready"


@given(parsers.parse('every walk of "{a}" finds it missing'))
def always_missing(world, a):
    world.outcomes[(a, None)] = "missing"


@given(parsers.parse('the walk of "{a}" prints no journal'))
def no_journal(world, a):
    world.outcomes[(a, None)] = "nojournal"


@given(parsers.parse('the walk of "{a}" never ends'))
def never(world, a):
    world.outcomes[(a, None)] = "never"


@given("every walk waits until it is told to end")
def waits(world):
    world.default = "wait"


@given(parsers.parse('the engine refuses the event that moves "{a}" to "{to}"'))
def refuses(world, a, to):
    world.engine.refuse = (a, to)


@given("PUBDEPLOY_RUN_TOKEN is set")
def token_set(world):
    world.env = {"PUBDEPLOY_RUN_TOKEN": "secret-run-token", "PATH": "/usr/bin"}


# --- When


def walk(world, during=None):
    ex = executor.Executor(world.engine, world_root(), spawn=world.spawn, env=world.env or {"PATH": "/usr/bin"},
                           poll=0.03, grace=0.0, slice_=0.01, log=world.said.append)
    if during is not None:
        threading.Thread(target=during, daemon=True).start()
    world.code = ex.run()


def world_root():
    from pathlib import Path  # noqa: PLC0415
    return Path.cwd()


def until(check, seconds=5.0):
    end = time.monotonic() + seconds
    while not check():
        assert time.monotonic() < end, "timed out"
        time.sleep(0.01)


@when("the executor walks the run")
def walks(world):
    walk(world)


@when("the executor walks the run, and a person presses Stop while all three walk")
def walks_and_stop(world):
    def stop():
        until(lambda: world.walking() == 3)
        world.stopping = True
        time.sleep(0.3)
        world.release.set()
    walk(world, stop)


@when(parsers.parse('the executor walks the run, and a person presses Stop and cancels "{c}"'))
def walks_stop_cancel(world, c):
    def stop():
        until(lambda: world.walking() == 2)
        world.stopping = True
        world.cancelled.add(c)
    walk(world, stop)


class Answer(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def http_error(code: int, body: dict | None = None):
    return urllib.error.HTTPError("http://engine/runs/r1", code, "x", {}, io.BytesIO(json.dumps(body or {}).encode()))


@pytest.fixture
def http():
    return {"calls": [], "sleeps": [], "answer": None}


@given("the engine answers the first POST of an event with 502")
def first_502(http):
    def opener(request, timeout):
        http["calls"].append(request)
        if len(http["calls"]) == 1:
            raise http_error(502)
        return Answer(request.data)
    http["answer"] = opener


@given("the engine never answers")
def never_answers(http):
    def opener(request, timeout):
        http["calls"].append(request)
        raise urllib.error.URLError("refused")
    http["answer"] = opener


@given(parsers.parse('the engine answers every call with {code:d} "{why}"'))
def always_refused(http, code, why):
    def opener(request, timeout):
        http["calls"].append(request)
        raise http_error(code, {"refused": why})
    http["answer"] = opener


def http_engine(http):
    return executor.HttpEngine("http://engine/", "r1", "run-token", opener=http["answer"], sleep=http["sleeps"].append)


@when("an event is posted to the engine over HTTP")
def posts(http):
    http_engine(http).post({"need": "a", "seq": 1, "from": "waiting", "to": "checking", "result": ""})


@when("the executor walks the run over HTTP")
def walks_http(world, http):
    world.code = executor.Executor(http_engine(http), world_root(), spawn=world.spawn, env={},
                                   log=world.said.append).run()


# --- Then


@then(parsers.parse("it exits {code:d}"))
def exits(world, code):
    assert world.code == code, (world.code, world.said)


@then(parsers.parse("its last event reports exit {code:d}"))
def reported(world, code):
    assert world.engine.exits == [code]


@then(parsers.parse('"{a}" and "{b}" were walked at the same time'))
def together(world, a, b):
    wa, wb = (next(w for w in world.walks if w["name"] == n) for n in (a, b))
    assert wa["start"] < wb["end"] and wb["start"] < wa["end"]


@then(parsers.parse('"{c}" was walked only after "{a}" was ready'))
def after_ready(world, c, a):
    ready = next(e["at"] for e in world.engine.events if e["need"] == a and e["to"] == "ready")
    assert next(w for w in world.walks if w["name"] == c)["start"] >= ready


@then(parsers.parse('every need ended "{state}"'))
def all_ended(world, state):
    assert set(world.states.values()) == {state}, world.states


@then("no two walks ran at the same time")
def one_at_a_time(world):
    spans = sorted((w["start"], w["end"]) for w in world.walks)
    assert all(b[0] >= a[1] for a, b in zip(spans, spans[1:])), spans


@then(parsers.parse('"{a}" moved {moves}'))
def moved(world, a, moves):
    assert world.moves(a) == [m.strip() for m in moves.split(",")]


@then("its fulfil was walked with --fulfil --yes and its budget")
def fulfil_argv(world):
    argv = next(w for w in world.walks if w["fulfil"])["argv"]
    assert argv[argv.index("walk"):] == ["walk", "--unit", "app", "--need", "a", "--budget-seconds", "60",
                                         "--fulfil", "--yes", "--json"]


@then("no walk was given --fulfil")
def no_fulfil(world):
    assert world.walks and not any(w["fulfil"] for w in world.walks)


@then(parsers.parse('"{a}" ended "{state}", saying "{said}"'))
def ended_saying(world, a, state, said):
    last = world.last(a)
    assert last["to"] == state and said in last["result"], last


@then(parsers.parse('"{a}" ended "{state}"'))
def ended(world, a, state):
    assert world.states[a] == state, world.states


@then("the event that failed it is not ok")
def not_ok(world):
    assert world.last("a")["ok"] is False


@then(parsers.parse('"{c}" was never walked'))
def never_walked(world, c):
    assert not any(w["name"] == c for w in world.walks)


@then(parsers.parse('"{h}" was told its budget had ended, and ended "{state}"'))
def shortened(world, h, state):
    assert next(w for w in world.walks if w["name"] == h)["budget"]
    assert world.states[h] == state


@then("no walk ran")
def none_ran(world):
    assert world.walks == []


@then("it was posted twice, the same event both times, with the run's token as the bearer")
def posted_twice(http):
    assert len(http["calls"]) == 2
    a, b = http["calls"]
    assert a.data == b.data and a.full_url == "http://engine/runs/r1/events" and a.get_method() == "POST"
    assert a.get_header("Authorization") == "Bearer run-token"


@then("the executor waited before it posted again")
def waited(http):
    assert http["sleeps"] and http["sleeps"][0] > 0


@then(parsers.parse('it said "{text}"'))
def said(world, text):
    assert any(text in line for line in world.said), world.said


@then("no walk's environment holds PUBDEPLOY_RUN_TOKEN")
def no_token(world):
    assert world.walks and all("PUBDEPLOY_RUN_TOKEN" not in w["env"] for w in world.walks)


@given(parsers.parse('the run\'s journal already moved "{a}" to "{to}" by its events 1 and 2'))
def journal_moved(world, a, to):
    world.states[a], world.seqs[a] = to, 2
    original = world.engine.run

    def run():
        view = original()
        view["journal"] = [{"seq": 2, "need": a, "need_seq": 1, "from": "waiting", "to": "checking"},
                           {"seq": 3, "need": a, "need_seq": 2, "from": "checking", "to": to}]
        return view
    world.engine.run = run
    world.engine.events.append({"need": a, "to": to, "at": 0.0})


@given(parsers.parse('the walk of "{a}" cannot start'))
def cannot_start(world, a):
    spawn = world.spawn

    def failing(argv, cwd, env):
        if argv[argv.index("--need") + 1] == a:
            raise OSError("no such file")
        return spawn(argv, cwd, env)
    world.spawn = failing


@when(parsers.parse('the walk of "{a}" prints {stdout}'), target_fixture="judged")
def judge(a, stdout):
    return executor.judged(a, 1, stdout, "")


@then(parsers.parse('the need is judged "{state}", saying "{said}"'))
def judged_as(judged, state, said):
    assert judged == (state, said)
