"""pubdeploy's deploy-walk test harness, for any suite that walks a service
with pubdeploy: a pytest plugin, its fakes, and the sample service they walk.
Nothing here runs in a deploy; it ships in the wheel so a suite loads it
rather than keep a copy.

Loading it. The `pytest11` entry point `pubdeploy.testing` (`plugin.py`)
is always there, and loads nothing until a suite asks, so a repository with
pubdeploy among its test tools gets none of these steps unasked. A suite
asks either way:

- `pubdeploy_testing = true` in its pytest.ini (or `[tool.pytest.ini_options]`);
- `pytest_plugins = ["pubdeploy.testing.steps"]` in its top conftest.py.

Its steps are pubtest's voice (pubtest's GRAMMAR.md), and need pubtest's
plugin, which every suite on pubtest loads. A step that runs pubrules
(`the example service's managed files are in step`) needs pubrules
installed. The world patches only pubdeploy: a suite whose installed packages
the walk also loads (pubsec's types) patches them in its own World's `patch`,
and a suite that walks with a stand-in provider instead returns its entry
points from `providers()`.

What it gives (`steps.py`):

- the fixture `world`: a `World` (`world.py`) around a copy of the sample
  service, with every fake installed, whose teardown fails the scenario
  when any output, journal, exception or argv holds a value (the canary);
- the fixture `deploy_world_class`: the class `world` makes, `World`; a
  suite overrides it to extend the world;
- the fixture `offered`: entry points of the `sustenaut.needs` group made up
  by a scenario;
- the deploy steps: the block, packages offering need types, `When I run
  pubdeploy "ARG" ...`, the plan, the walk's lines, the journal, the
  cluster, the manifests, GitHub, HTTP, Bitwarden, budgets, fulfilling,
  units, storage;
- `Given a file "P" copied from the sample "SRC"`: pubtest's `copied from`
  for the sample service, which is outside the suite's repository: SRC is
  `deploy-app`, or a path in it (`deploy-app/zones.json`).

`world` is not autouse. A test module whose every scenario should run in a
world, and under its canary, says so with
`pytestmark = pytest.mark.usefixtures("world")`.

Extending the world. Subclass `World`, and name the subclass in the suite's
conftest.py:

    from pubdeploy.testing.world import World

    class PubsecWorld(World):
        secrets_project = "PUBRULES_SECRETS_PROJECT"

        def patch(self, monkeypatch):
            super().patch(monkeypatch)
            monkeypatch.setattr("pubsec.needs.gcp.gcloud", self.run_gcloud)  # its own fake

    @pytest.fixture
    def deploy_world_class():
        return PubsecWorld

The hooks are `secrets_project` (the variable ./with-secrets names its
project in), `sample()` (the service copied), `__init__` (more state),
`providers()` (a `Providers` of the `sustenaut.needs` entry points and
`sustenaut.walk` hooks the walk loads in place of the installed ones, or None,
the default, for the installed), `patch(monkeypatch)` (what the walk reaches; a
subclass patches its own packages after calling it), `context(...)` (the walk's
Context) and `leaked()` (what the canary reads). A step of the suite's own with
a plugin step's text takes precedence over it.

`walk_needs(world, needs=None, types=None, fulfil=())` walks needs in the
world's context, as a provider's own scenarios do with its types, and gives
the deploy-journal/2 document as data. With these and `pubdeploy.contract`, a
provider's suite imports nothing else of pubdeploy.

`fixture_path(name)` is where a sample is, for a suite's own steps.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["FIXTURES", "fixture_path"]

# The samples, as package data: deploy-app, the service the world walks.
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def fixture_path(name: str = "deploy-app") -> Path:
    """The sample `name`, or a path in one (`deploy-app/zones.json`). A name
    that leads out of the samples, or is not there, is refused."""
    path = (FIXTURES / name).resolve()
    if Path(name).is_absolute() or not path.is_relative_to(FIXTURES):
        raise ValueError(f"{name} is not one of pubdeploy's samples")
    if not path.exists():
        raise FileNotFoundError(f"pubdeploy has no sample {name}")
    return path
