"""Steps for the deploy-journal feature, against fakes: the shared ones are pubdeploy.testing's."""

from __future__ import annotations

import pytest
from pytest_bdd import scenarios

# Every scenario runs in the deploy world, under its canary (pubdeploy.testing).
pytestmark = pytest.mark.usefixtures("world")

scenarios("deploy-journal.feature")
