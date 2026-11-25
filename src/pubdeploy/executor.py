"""`pubdeploy executor`: a live run's needs, walked outside the convergence engine.

    PUBDEPLOY_RUN_TOKEN=... pubdeploy executor --engine URL --run ID [--journal URL]

What the engine's in-process executor does, from wherever this runs (a Job in the
service's namespace): it reads the run (GET URL/runs/ID/executor, the run's own token as
its bearer), walks each need once every need it comes after has ended, as many at once as the
run's machine allows (its `parallel`), and reports each move as one event (POST
URL/runs/ID/events), numbered by the need's own sequence, so a re-post after a lost
answer is the same event and the engine keeps it once.

Each need is walked by itself, as the engine walks it: `pubdeploy walk --unit U --need
NAME --budget-seconds S --json [--fulfil --yes]`, first to check it, then, when it is
found and is to be fulfilled (mode fulfil, grade auto: machine.fulfils_need), to fulfil
it, which checks it again; a need still found after its fulfil fails. Each walk is its
own process of the same pubdeploy, and not a call in this one, because a Stop acts on one
need's walk at once: its signal (terminate), or SIGUSR1, which a walk takes as "its budget
is what has elapsed" (walk.SHORTENED, one per process). A walk may take its need's budget
and 60 s more: past that it is terminated, and the need fails.

Every 5 s the executor reads the run again for a Stop (`stopping`) and the needs a person
cancelled by name (`cancelled`). On a Stop, what has not started never starts (stopped),
and a need walking stops as its class says: signal terminates its walk; shorten sends it
SIGUSR1, and the walk ends the step unknown, its journal kept; continue lets it finish,
unless a person cancels it. A need after one that did not end ready is blocked.

It exits 0 once every need is final, 3 when the engine refused it (its token, or an event
the run's machine does not take), and 1 when the engine could not be reached. Every exit
first posts a last event naming it (`executor_exit`).
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .machine import fulfils_need

FINAL = ("ready", "failed", "blocked", "stopped", "unknown")
NOT_READY = ("failed", "blocked", "stopped", "unknown")
GRACE = 60.0  # what a need's walk may run past its budget before it is ended
POLL = 5.0  # how often the run is read again, for a Stop and the cancels
SLICE = 0.2  # how often a walk is looked at, for its deadline
TRIES = 5  # an engine call's attempts, each after a longer wait, when the engine does not answer
KNOWN = {"ready": "ready", "missing": "found", "drift": "found", "blocked": "blocked", "unknown": "unknown"}


class Refused(Exception):
    """The engine refused a call: not this run's executor, or a move its machine does not take."""


class Unreachable(Exception):
    """The engine did not answer, after every attempt."""


class Engine(Protocol):
    def run(self) -> dict[str, Any]: ...

    def post(self, event: dict[str, Any]) -> dict[str, Any]: ...


class HttpEngine:
    """The engine's run, over HTTP: GET URL/runs/ID/executor and POST URL/runs/ID/events, the
    run's token as the bearer. A 5xx or no answer is tried again after a longer wait; a 4xx is refused."""

    def __init__(self, url: str, run: str, token: str, *, opener: Callable[..., Any] = urllib.request.urlopen,
                 sleep: Callable[[float], None] = time.sleep, tries: int = TRIES, timeout: float = 30.0):
        self.base = f"{url.rstrip('/')}/runs/{run}"
        self.token, self.opener, self.sleep, self.tries, self.timeout = token, opener, sleep, tries, timeout

    def run(self) -> dict[str, Any]:
        return self._call(urllib.request.Request(f"{self.base}/executor", headers=self._headers()))

    def post(self, event: dict[str, Any]) -> dict[str, Any]:
        return self._call(urllib.request.Request(f"{self.base}/events", data=json.dumps(event).encode(),
                                                 headers={**self._headers(), "Content-Type": "application/json"},
                                                 method="POST"))

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}

    def _call(self, request: urllib.request.Request) -> dict[str, Any]:
        said = ""
        for attempt in range(self.tries):
            if attempt:
                self.sleep(min(2.0 ** attempt, 30.0))
            try:
                with self.opener(request, timeout=self.timeout) as answer:
                    return json.loads(answer.read() or b"{}")
            except urllib.error.HTTPError as e:
                if e.code < 500:
                    raise Refused(f"{request.get_method()} {request.full_url}: {e.code} {_refusal(e)}") from None
                said = f"{e.code}"
            except (urllib.error.URLError, OSError, ValueError) as e:
                said = type(e).__name__
        raise Unreachable(f"{request.get_method()} {request.full_url}: no answer after {self.tries} tries ({said})")


def _refusal(error: urllib.error.HTTPError) -> str:
    try:
        body = json.loads(error.read() or b"{}")
    except ValueError:
        return ""
    return str(body.get("refused") or body.get("why") or "") if isinstance(body, dict) else ""


class Proc(Protocol):
    def poll(self, timeout: float) -> tuple[int, str, str] | None: ...

    def terminate(self) -> None: ...

    def budget(self) -> None: ...


class Popen:  # pragma: no cover - a real walk's process; the suite's executor gets fakes
    def __init__(self, argv: list[str], cwd: Path, env: dict[str, str]):
        self.process = subprocess.Popen(argv, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        stdin=subprocess.DEVNULL, text=True, errors="replace")

    def poll(self, timeout: float) -> tuple[int, str, str] | None:
        try:
            out, err = self.process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            return None
        return self.process.returncode, out, err

    def terminate(self) -> None:
        self.process.terminate()

    def budget(self) -> None:
        self.process.send_signal(signal.SIGUSR1)


@dataclass
class Need:
    name: str
    mode: str
    grade: str
    stop: str
    after: list[str]
    seconds: float
    state: str = "waiting"
    seq: int = 0
    fulfilled: bool = False

    @property
    def fulfils(self) -> bool:
        return not self.fulfilled and fulfils_need({"mode": self.mode, "grade": self.grade})

    @property
    def ended(self) -> bool:
        return self.state in FINAL or (self.state == "found" and not self.fulfils)


@dataclass
class Walking:
    proc: Proc
    deadline: float
    ended_by: str = ""


def needs_of(view: dict[str, Any]) -> dict[str, Need]:
    """The run's needs, where its journal leaves each: mode, grade, stop class and after-edges
    as the run shows them, the budget from its machine's meta."""
    regions = (((view.get("machine") or {}).get("states") or {}).get("running") or {}).get("states") or {}
    seconds = {str((r.get("meta") or {}).get("need") or k): float((r.get("meta") or {}).get("seconds") or 60)
               for k, r in regions.items()}
    out = {name: Need(name, str(n.get("mode") or "fulfil"), str(n.get("grade") or "auto"),
                      str(n.get("stop") or "signal"), [str(a) for a in n.get("after") or []],
                      seconds.get(name, 60.0), state=str(n.get("state") or "waiting"))
           for name, n in (view.get("needs") or {}).items()}
    for event in view.get("journal") or []:
        need = out.get(event.get("need") or "")
        if need is not None:
            need.seq = max(need.seq, int(event.get("need_seq") or 0))
            need.fulfilled |= event.get("from") == "fulfilling" and event.get("to") == "checking"
    return out


def walk_argv(unit: str, need: Need, fulfil: bool, journal: str = "") -> list[str]:
    """One need's walk, by the pubdeploy this executor is (and the need types installed with it)."""
    return [sys.executable, "-m", "pubdeploy.cli", "walk", "--unit", unit, "--need", need.name,
            "--budget-seconds", f"{need.seconds:g}", *(["--fulfil", "--yes"] if fulfil else []), "--json",
            *(["--journal", journal] if journal else [])]


class Executor:
    def __init__(self, engine: Engine, root: Path, *, journal: str = "",
                 spawn: Callable[[list[str], Path, dict[str, str]], Proc] = Popen,
                 env: dict[str, str] | None = None, clock: Callable[[], float] = time.monotonic,
                 poll: float = POLL, grace: float = GRACE, slice_: float = SLICE, log: Callable[[str], None] = print):
        self.engine, self.root, self.journal, self.spawn = engine, root, journal, spawn
        self.env = dict(os.environ if env is None else env)
        self.env.pop("PUBDEPLOY_RUN_TOKEN", None)  # a walk is never given the run's token
        self.clock, self.poll, self.grace, self.slice, self.log = clock, poll, grace, slice_, log
        self.lock = threading.Condition()
        self.needs: dict[str, Need] = {}
        self.walking: dict[str, Walking] = {}
        self.stopping = False
        self.cancelled: set[str] = set()
        self.failure: BaseException | None = None
        self.unit = ""
        self.parallel = 4

    # --- The engine

    def _post(self, need: Need, to: str, result: str = "", ok: bool | None = None) -> None:
        """One move of a need, as an event the engine keeps once: its next seq, from where it is."""
        event = {"need": need.name, "seq": need.seq + 1, "from": need.state, "to": to, "result": result[:2000],
                 **({"ok": ok} if ok is not None else {})}
        self.engine.post(event)
        with self.lock:
            need.seq, need.state = need.seq + 1, to
            if event["from"] == "fulfilling" and to == "checking":
                need.fulfilled = True
            self.lock.notify_all()

    def _read(self) -> None:
        view = self.engine.run()
        with self.lock:
            self.stopping = self.stopping or bool(view.get("stopping"))
            self.cancelled |= {str(n) for n in view.get("cancelled") or []}
            for name in self.cancelled & set(self.walking):
                self._end(name, cancel=True)
            if self.stopping:
                for name in list(self.walking):
                    self._end(name)

    # --- Walking

    def run(self) -> int:
        try:
            view = self.engine.run()
            self.unit = str(view.get("unit") or "")
            self.needs = needs_of(view)
            self.parallel = max(1, int(view.get("parallel") or 4))
            self.stopping, self.cancelled = bool(view.get("stopping")), {str(n) for n in view.get("cancelled") or []}
            if view.get("state") != "running":
                raise Refused(f"the run is {view.get('state')}, not running")
            self._layers()
            if self.failure is not None:
                raise self.failure
        except Refused as e:
            return self._exit(3, f"the engine refused: {e}")
        except Unreachable as e:
            return self._exit(1, str(e))
        return self._exit(0, "every need has ended")

    def _exit(self, code: int, said: str) -> int:
        self.log(f"pubdeploy executor: {said}")
        try:
            self.engine.post({"executor_exit": code, "result": said[:2000]})
        except (Refused, Unreachable) as e:
            self.log(f"pubdeploy executor: its exit was not reported ({e})")
        return code

    def _layers(self) -> None:
        active: dict[str, threading.Thread] = {}
        parallel = self.parallel
        read_at = self.clock() + self.poll
        while True:
            with self.lock:
                if self.failure is not None:
                    return
                todo = []
                for need in self.needs.values():
                    if need.state != "waiting" or need.name in active:
                        continue
                    before = [self.needs[a] for a in need.after if a in self.needs]
                    if self.stopping:
                        todo.append((need, "stopped", "stopped before it started"))
                    elif any(b.state in NOT_READY for b in before):
                        todo.append((need, "blocked", "a need it comes after did not end ready"))
                    elif all(b.ended for b in before) and len(active) < parallel:
                        thread = threading.Thread(target=self._need, args=(need,), daemon=True,
                                                  name=f"need {need.name}")
                        active[need.name] = thread
                        thread.start()
                for name in [n for n, t in active.items() if not t.is_alive()]:
                    del active[name]
                if not todo and not active and all(n.ended for n in self.needs.values()):
                    return
            for need, to, said in todo:
                self._post(need, to, said)
            if self.clock() >= read_at:
                self._read()
                read_at = self.clock() + self.poll
            with self.lock:
                self.lock.wait(self.slice)

    def _need(self, need: Need) -> None:
        try:
            self._post(need, "checking")
            state, said = self._walk(need, fulfil=False)
            if state == "found" and need.fulfils and not self.stopping:
                self._post(need, "found", said)
                self._post(need, "fulfilling")
                state, said = self._walk(need, fulfil=True)
                if state == "found":  # the fulfil ran and left it as it was
                    self._post(need, "failed", f"still found after its fulfil: {said}", ok=False)
                    return
                if state not in ("failed", "stopped"):
                    self._post(need, "checking", said)
            self._post(need, state, said)
        except (Refused, Unreachable) as e:
            with self.lock:
                self.failure = self.failure or e
                self.lock.notify_all()
        except Exception as e:  # noqa: BLE001 - the need fails, said on the run; the others go on
            try:
                if not need.ended:
                    self._post(need, "failed", f"its walk could not run ({type(e).__name__})")
            except (Refused, Unreachable) as e2:
                with self.lock:
                    self.failure = self.failure or e2
                    self.lock.notify_all()

    def _walk(self, need: Need, fulfil: bool) -> tuple[str, str]:
        with self.lock:
            if need.name in self.cancelled:
                return "stopped", "cancelled before its walk began"
            if self.stopping and need.stop != "continue":
                return "stopped", "stopped before its walk began"
            walking = self.walking[need.name] = Walking(
                self.spawn(walk_argv(self.unit, need, fulfil, self.journal), self.root, self.env),
                self.clock() + need.seconds + self.grace)
        try:
            while True:
                ended = walking.proc.poll(self.slice)
                if ended is not None:
                    break
                if self.clock() >= walking.deadline:
                    walking.proc.terminate()
                    return "failed", f"it ran past its budget of {need.seconds:g} s and {self.grace:g} s more"
        finally:
            with self.lock:
                self.walking.pop(need.name, None)
        if walking.ended_by:
            return "stopped", f"{walking.ended_by}: its walk was ended"
        return judged(need.name, *ended)

    def _end(self, name: str, cancel: bool = False) -> None:
        """A walking need's Stop, as its class says, or its cancel: under the lock."""
        walking, need = self.walking.get(name), self.needs[name]
        if walking is None or walking.ended_by:
            return
        if cancel or need.stop == "signal":
            walking.ended_by = "cancelled" if cancel else "stopped (signal)"
            walking.proc.terminate()
        elif need.stop == "shorten":
            walking.ended_by = ""  # the walk ends the step unknown, and says so itself
            walking.proc.budget()


def judged(name: str, code: int, out: str, err: str) -> tuple[str, str]:
    """Where a walk leaves its need, by its journal: ready, found, blocked, unknown or failed."""
    try:
        data = json.loads(out)
        documents = data if isinstance(data, list) else [data]
        found = [n for d in documents for n in d.get("needs", []) if n.get("id") == name]
    except (ValueError, AttributeError):
        last = ([line for line in err.splitlines() if line.strip()] or [f"exit {code}"])[-1]
        return "failed", f"the walk printed no journal ({last[:300]})"
    if not found:
        return "failed", "the walk's journal does not name the need"
    state = str(found[0].get("state"))
    details = [str(d) for d in (found[0].get("details") or [])[:3] if str(d).strip()]
    detail = " ".join(("; ".join(details) or str(found[0].get("summary") or "")).split())[:400]
    return KNOWN.get(state, "failed"), (detail if state in KNOWN else f"{state}: {detail}")


def main(engine_url: str, run_id: str, journal: str = "", root: Path | None = None) -> int:
    token = os.environ.get("PUBDEPLOY_RUN_TOKEN", "")
    if not token:
        print("pubdeploy executor: PUBDEPLOY_RUN_TOKEN is not set: the run's token is its bearer", file=sys.stderr)
        return 2
    return Executor(HttpEngine(engine_url, run_id, token), root or Path.cwd(), journal=journal).run()
