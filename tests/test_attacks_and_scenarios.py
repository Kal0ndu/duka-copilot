"""Every attack must be blocked, and every scripted scenario must succeed."""

import tempfile

import pytest

from attacks import ATTACKS
from evaluation import SCENARIOS, run_scenario


@pytest.mark.parametrize("category, name, attack", ATTACKS, ids=[a[1] for a in ATTACKS])
def test_attack_is_blocked(category, name, attack):
    with tempfile.TemporaryDirectory() as tmp:
        ok, detail = attack(tmp)
    assert ok, detail


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s["id"] for s in SCENARIOS])
def test_scripted_scenario_succeeds(scenario):
    failures, _ = run_scenario(scenario)
    assert not failures, failures
