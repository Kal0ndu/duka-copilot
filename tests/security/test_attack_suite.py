"""Every attack in attack_suite.ATTACKS must be blocked."""
import shutil
from dataclasses import replace

import pytest

from tests.fixtures_duka import build_world
from tests.security.attack_suite import ATTACKS


@pytest.fixture(scope="module")
def base_world(tmp_path_factory):
    return build_world(tmp_path_factory.mktemp("attacks"))


@pytest.fixture
def world(base_world, tmp_path):
    """A fresh copy of the database for each attack (they change state)."""
    db = str(tmp_path / "duka.db")
    shutil.copy(base_world.db, db)
    return replace(base_world, db=db)


@pytest.mark.parametrize("name,attack", ATTACKS, ids=[n for n, _ in ATTACKS])
def test_attack_is_blocked(world, name, attack):
    blocked, detail = attack(world)
    assert blocked, f"NOT BLOCKED: {name} ({detail})"
