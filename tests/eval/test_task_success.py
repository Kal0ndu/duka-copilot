"""Task-success scores: every scripted task must succeed; the offline
keyword planner must pick the right tool for at least 90% of questions."""
import shutil
from dataclasses import replace
from itertools import count

import pytest

from tests.eval.task_eval import run_offline, run_scripted
from tests.fixtures_duka import build_world


@pytest.fixture(scope="module")
def world_factory(tmp_path_factory):
    base = build_world(tmp_path_factory.mktemp("eval"))
    n = count()

    def fresh():
        db = str(tmp_path_factory.mktemp(f"task{next(n)}") / "duka.db")
        shutil.copy(base.db, db)
        return replace(base, db=db)
    return fresh


def test_scripted_tasks_all_succeed(world_factory):
    results = run_scripted(world_factory)
    failed = [(name, detail) for name, ok, detail in results if not ok]
    assert not failed, failed


def test_offline_planner_picks_the_right_tool():
    results = run_offline()
    score = sum(ok for _, ok, _ in results) / len(results)
    missed = [(q, tools) for q, ok, tools in results if not ok]
    assert score >= 0.9, missed
