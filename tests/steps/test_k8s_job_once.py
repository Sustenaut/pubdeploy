"""Steps for k8s.job-once, against a fake kubectl that keeps Jobs and CronJobs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from pytest_bdd import given, parsers, scenarios, then, when

from pubdeploy.model import Context, Need, Ran
from pubdeploy.registry import types

scenarios("k8s-job-once.feature")


class Kubectl:
    """Jobs and CronJobs by name, the calls, and the verbs it refuses."""

    def __init__(self) -> None:
        self.jobs: dict[str, dict] = {}
        self.cronjobs: dict[str, dict] = {}
        self.calls: list[list[str]] = []
        self.made: list[dict] = []
        self.deleted: list[str] = []
        self.refuse: set[str] = set()

    def __call__(self, args: list[str], input: bytes | None = None) -> Ran:  # noqa: A002
        self.calls.append(args)
        ns, verb, rest = args[1], args[2], args[3:]
        assert ns == "integrations", args
        if verb == "get":
            kind, name = rest[0], rest[1]
            if f"read {kind}s" in {r.lower() for r in self.refuse}:
                return Ran(1, "", f'Error from server (Forbidden): cannot get {kind}s')
            held = self.jobs if kind == "job" else self.cronjobs
            if name not in held:
                return Ran(1, "", f'Error from server (NotFound): {kind}s.batch "{name}" not found')
            return Ran(0, json.dumps(held[name]))
        if verb == "delete":
            if "delete" in self.refuse:
                return Ran(1, "", 'Error from server (Forbidden): cannot delete jobs')
            self.deleted.append(rest[1])
            self.jobs.pop(rest[1], None)
            return Ran(0, f"job.batch \"{rest[1]}\" deleted")
        if verb == "create":
            assert rest == ["-f", "-"] and input is not None
            if "create" in self.refuse:
                return Ran(1, "", 'Error from server (Forbidden): cannot create jobs')
            job = json.loads(input)
            self.made.append(job)
            self.jobs[job["metadata"]["name"]] = {**job, "status": {"active": 1}}
            return Ran(0, f"job.batch/{job['metadata']['name']} created")
        raise AssertionError(args)


def job_spec(command: str, containers: bool = True) -> dict:
    return {"ttlSecondsAfterFinished": 3600, "template": {"spec": {
        "restartPolicy": "Never",
        "containers": [{"name": "main", "image": "example", "command": command.split()}] if containers else []}}}


class World:
    def __init__(self, root: Path) -> None:
        self.root, self.kubectl = root, Kubectl()
        self.need: Need | None = None
        self.ctx = Context.for_tests(root=root, block={"namespace": "integrations"}, kubectl=self.kubectl)
        self.result = None
        self.line = ""

    @property
    def kind(self):
        return types()["k8s.job-once"]


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def need_of(text: str) -> Need:
    params = json.loads(text)
    kind, name = params.pop("type"), params.pop("name")
    return Need(kind, name, params)


@given(parsers.parse('the namespace "integrations" has the CronJob "{name}", whose job runs "{command}"'))
def has_cronjob(world, name, command):
    world.kubectl.cronjobs[name] = {"metadata": {"name": name}, "spec": {"jobTemplate": {"spec": job_spec(command)}}}


@given(parsers.parse('the namespace "integrations" has no CronJob "{name}"'))
def no_cronjob(world, name):
    world.kubectl.cronjobs.pop(name, None)


@given(parsers.re(r'the need (?:is )?(?P<text>\{.*\})'))
def the_need(world, text):
    world.need = need_of(text)


@given(parsers.parse('the need also says "{key}" is "{value}"'))
def also_says(world, key, value):
    world.need = Need(world.need.type, world.need.name, {**world.need.params, key: value})


JOB_STATES = {"is running": {"active": 1},
              "completed": {"succeeded": 1, "completionTime": "2026-11-17T03:00:00Z"},
              "has a condition Complete": {"conditions": [{"type": "Complete", "status": "True"}]},
              "failed": {"failed": 1, "conditions": [{"type": "Failed", "status": "True"}]}}


@given(parsers.re(r'the Job "(?P<name>[^"]+)" (?P<state>is not there|is running|completed|has a condition Complete|failed)'))
def job_state(world, name, state):
    if state == "is not there":
        world.kubectl.jobs.pop(name, None)
    else:
        world.kubectl.jobs[name] = {"metadata": {"name": name}, "status": JOB_STATES[state]}


@given(parsers.parse('the file "{path}" holds a Job whose container runs "{command}"'))
def file_job(world, path, command):
    write(world, path, [{"apiVersion": "batch/v1", "kind": "Job", "metadata": {"name": "anything"},
                         "spec": job_spec(command)}])


@given(parsers.re(r'the file "(?P<path>[^"]+)" (?P<holds>holds two Jobs|is not there|holds a Job with no container)'))
def file_holds(world, path, holds):
    if holds == "holds two Jobs":
        write(world, path, [{"kind": "Job", "spec": job_spec("a")}, {"kind": "Job", "spec": job_spec("b")}])
    elif holds == "holds a Job with no container":
        write(world, path, [{"kind": "Job", "spec": job_spec("a", containers=False)}])


def write(world, path, docs):
    target = world.root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump_all(docs))


@given(parsers.parse("kubectl refuses to {verb}"))
def refuses(world, verb):
    world.kubectl.refuse.add(verb)


@when("the need is checked")
def checked(world):
    world.result = world.kind.check(world.need, world.ctx)
    world.ctx.results[world.need.id] = world.result


@when("the plan's line is asked for")
def plan_line(world):
    world.line = world.kind.action(world.need, world.ctx)


@when("the need is fulfilled")
def fulfilled(world):
    world.result = world.kind.fulfil(world.need, world.ctx)


@then(parsers.parse('it is {state}, saying "{text}"'))
def it_is(world, state, text):
    assert world.result.state == state and text in world.result.summary, world.result


@then("the walk would not act on it")
def not_acted(world):
    assert world.result.fixable is False, world.result


@then(parsers.parse('its fix says "{text}"'))
def fix_says(world, text):
    assert text in world.result.fix


@then(parsers.parse('the line is "{line}"'))
def line_is(world, line):
    assert world.line == line


@then(parsers.re(r'kubectl made the Job "(?P<name>[^"]+)" running "(?P<argv>[^"]+)", '
                 r'(?:for (?P<seconds>\d+) seconds at most|with no deadline), kept after it ends'))
def made(world, name, argv, seconds):
    (job,) = world.kubectl.made
    container = job["spec"]["template"]["spec"]["containers"][0]
    assert job["metadata"]["name"] == name and job["metadata"]["namespace"] == "integrations"
    assert job["metadata"]["annotations"]["pubdeploy/need"] == world.need.id
    assert [*container["command"], *container.get("args", [])] == argv.split()
    assert job["spec"].get("activeDeadlineSeconds") == (int(seconds) if seconds else None)
    assert "ttlSecondsAfterFinished" not in job["spec"]


@then("kubectl made no Job")
def made_none(world):
    assert world.kubectl.made == []


@then("kubectl deleted nothing")
def deleted_nothing(world):
    assert world.kubectl.deleted == []


@then(parsers.parse('kubectl deleted the Job "{name}" alone'))
def deleted_alone(world, name):
    assert world.kubectl.deleted == [name]
    assert [c for c in world.kubectl.calls if c[2] == "delete"] == [["-n", "integrations", "delete", "job", name,
                                                                    "--wait=true"]]


@then(parsers.parse('the types pubdeploy has include "{name}", graded {grade}, needing kubectl that writes'))
def listed(world, name, grade):
    kind = types()[name]
    assert kind.grade == grade and kind.requires(world.need) == ("kubectl-write",)
