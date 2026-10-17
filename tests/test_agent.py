import pytest

from agent import (FAIL_SAFE, TEST_QUESTIONS, make_agent, numbers_in_text,
                   unverified_numbers, validate_call)
from providers import OfflineProvider, detect_language
from security import POLICIES, AuditLog


# --- tool-call schema check ---

@pytest.mark.parametrize("name, args, ok", [
    ("get_forecast", {}, True),
    ("compare_credit", {"amount": 45000, "term_days": 180.0}, True),   # 180.0 -> 180
    ("compare_credit", {"amount": 45000}, False),                      # missing field
    ("compare_credit", {"amount": "45,000", "term_days": 180}, False),
    ("compare_credit", {"amount": 45000, "term_days": 5}, False),      # below minimum
    ("propose_loan", {"product": "shark", "amount": 5000, "term_days": 30}, False),
    ("propose_payment", {"payee_id": "SUP-01", "amount": 5, "approved": True}, False),
    ("approve_request", {"request_id": "x"}, False),                   # no such tool
])
def test_validate_call(name, args, ok):
    clean, problem = validate_call(name, args)
    assert (problem is None) is ok
    if ok and "term_days" in args:
        assert isinstance(clean["term_days"], int)


# --- number verification ---

def test_numbers_in_text_skips_dates_ids_and_small_numbers():
    text = "On 2026-10-22 at 10:30, REQ-9AB1 for SUP-01: pay KES 30,000 (17%) in 2 days"
    assert numbers_in_text(text) == [(30000.0, False), (17.0, True)]


@pytest.mark.parametrize("answer, bad", [
    ("Sales were KES 1,008,340.", []),
    ("Sales were about KES 1,008,000.", []),             # rounding within 0.5%
    ("Your true position is KES 37,967.", []),           # sign ignored
    ("It costs 17% a year.", []),                        # 0.17 -> 17%
    ("Sales were KES 2,000,000.", ["2,000,000"]),
    ("It costs 3% a year.", ["3%"]),
])
def test_unverified_numbers(answer, bad):
    sources = [{"sales": 1008340.0, "true_position": -37967, "annual_cost": 0.17}]
    assert unverified_numbers(answer, sources) == bad


# --- the offline agent end to end ---

@pytest.fixture(scope="module")
def offline_answers(tmp_path_factory):
    audit = AuditLog(tmp_path_factory.mktemp("audit") / "audit.jsonl")
    provider = OfflineProvider(POLICIES["amina_grocery"].verified_payees)
    agent = make_agent(provider, audit)
    results = []
    for statement, question in TEST_QUESTIONS:
        if statement:
            agent = make_agent(provider, audit, statement=statement)
        results.append((question, agent.ask(question), agent))
    return results


def test_offline_answers_pass_number_check(offline_answers):
    for question, answer, agent in offline_answers:
        assert agent.answer_verified, question


def test_offline_swahili_reply(offline_answers):
    question, answer, _ = offline_answers[3]
    assert detect_language(question) == detect_language(answer) == "sw"


def test_malicious_statement_proposes_nothing(offline_answers):
    _, answer, agent = offline_answers[4]
    assert not agent.sandbox.approvals.waiting()
    assert "WARNING" in answer and answer != FAIL_SAFE["en"]
