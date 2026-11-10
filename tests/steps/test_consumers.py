"""Steps for the guard that keeps consumers' names out of pubdeploy, moved
from pubkit's test_consumers.py with the deploy code."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from pytest_bdd import given, parsers, scenarios, then, when

scenarios("consumers.feature")

ROOT = Path(__file__).resolve().parents[2]


@then(parsers.parse('it finds "{found}"'))
def finds(names, found):
    assert names == {found}


@then("it finds nothing")
def finds_nothing(names):
    assert names == set()


# pubdeploy: its package, workflows, actions, tests and example service. They may name
# example hosts, the tools' and registries' hosts, pubkit itself, and the names
# pubkit's deploy workflow and the server's program already use; any other
# host, and any other mention of the owner, is a consumer's.
DEPLOY = ("src/pubdeploy", "tests/fixtures/deploy-app", "tests/features/deploy-*.feature",
          "tests/steps/deploy_*.py", "tests/steps/test_deploy_*.py", ".github/workflows/deploy-check.yml",
          ".github/workflows/k8s-deploy.yml", "actions/deploy-ssh", "k8s/components")
# config.py names the owner of pubdeploy's own repository, whose workflows a
# repository calls, as pubkit's refs.py does.
OWN_OWNER = {"src/pubdeploy/config.py"}
# A host, not a module path such as .types.net.
HOST = re.compile(r"(?<![.\w])(?:[a-z0-9-]+\.)+(?:eu|com|org|net|io|dev|app|cloud)\b")
EXAMPLE_HOSTS = re.compile(r"(?:^|\.)example\.(?:eu|com|org|net)$")
TOOL_HOSTS = {"github.com", "json-schema.org", "quay.io", "ghcr.io"}
TOOL_DOMAINS = (".k8s.io", ".iam.gserviceaccount.com")  # Kubernetes' API groups, Google's service accounts
OWNER = re.compile(r"(?i)\b(sustenaut|schryer)\b[-.\w]*")
OWNER_NAMES = {"sustenaut.needs", "sustenaut.walk", "sustenaut.sync", "sustenaut.bump", "sustenaut-app"}


def consumer_names(text: str) -> set[str]:
    """Every host and mention of the owner in `text` that is not an example's or a tool's."""
    found = {h for h in HOST.findall(text)
             if not EXAMPLE_HOSTS.search(h) and h not in TOOL_HOSTS and not h.endswith(TOOL_DOMAINS)}
    for m in OWNER.finditer(text):
        word = m.group(0)
        if word.upper().startswith("SUSTENAUT_") or word in OWNER_NAMES or text[m.start():].startswith(("Sustenaut/pubkit", "Sustenaut/pubdeploy", "Sustenaut/pubsec", "Sustenaut/integrations", "Sustenaut/pubrel", "Sustenaut/pubhost")):
            continue
        found.add(m.group(1))
    return found


@when("I scan pubdeploy's files for consumers' names", target_fixture="names")
def scan_deploy():
    # What git tracks or would, so bytecode and other ignored files a run leaves behind do not count.
    listed = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "--", *DEPLOY],
                            cwd=ROOT, check=True, capture_output=True, text=True).stdout.split()
    assert any(name.startswith("src/pubdeploy/") for name in listed), listed
    return {(name, found) for name in listed if name not in OWN_OWNER
            for found in consumer_names((ROOT / name).read_text(encoding="utf-8", errors="ignore"))}


@then("it finds none")
def finds_none(names):
    assert names == set(), sorted(names)


@given(parsers.parse('a deploy file reads "{text}"'), target_fixture="shipped")
def deploy_text(text):
    return text


@when("I scan it for consumers' names", target_fixture="names")
def scan_deploy_text(shipped):
    return consumer_names(shipped)
