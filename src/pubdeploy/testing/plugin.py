"""The `pytest11` entry point `pubdeploy.testing`: it loads the deploy-walk
steps and fixtures (`pubdeploy.testing.steps`) into a suite whose ini sets
`pubdeploy_testing = true`, and nothing into any other. pubdeploy is
installed in the test environment of every repository with a deploy block,
whose suites must not get these steps unasked."""

from __future__ import annotations

import pytest

STEPS = "pubdeploy.testing.steps"

# Installed as a plugin's modules are, an editable install's included, so a
# failed assert in a step shows its values.
pytest.register_assert_rewrite(STEPS, "pubdeploy.testing.world")


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addini("pubdeploy_testing", "load pubdeploy's deploy-walk steps and fixtures (pubdeploy.testing.steps)",
                  type="bool", default=False)


def pytest_configure(config: pytest.Config) -> None:
    if config.getini("pubdeploy_testing"):
        # Loaded once, however the suite asked: pytest_plugins in a conftest registers the same name.
        config.pluginmanager.import_plugin(STEPS)
