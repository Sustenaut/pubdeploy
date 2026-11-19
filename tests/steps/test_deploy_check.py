"""Steps for pubrules deploy check, against fakes of everything it touches: the shared ones are pubdeploy.testing's."""

from __future__ import annotations

import pytest
from pytest_bdd import scenarios

# Every scenario runs in the deploy world, under its canary (pubdeploy.testing).
pytestmark = pytest.mark.usefixtures("world")

scenarios("deploy-check.feature")
