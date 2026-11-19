"""Steps for the needs a deploy block implies, and the order they are walked in: the shared ones are pubdeploy.testing's."""

from __future__ import annotations

import pytest
from pytest_bdd import scenarios

# Every scenario runs in the deploy world, under its canary (pubdeploy.testing).
pytestmark = pytest.mark.usefixtures("world")

scenarios("deploy-order.feature")
