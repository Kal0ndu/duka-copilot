"""
sandbox.py - Step 7: a pretend account and lender where approved actions run
=============================================================================

  SandboxAccount - a simulated mobile-money account (no overdraft: a payment
                   bigger than the balance fails)
  MockLender     - prices loans with credit.py and pays them into the account
  Sandbox        - the ONLY place actions are carried out. Every action passes
                   the policy guard, every money action needs a valid owner
                   approval, and every step is written to the audit log.

Nothing here touches real money or any real service.

HOW TO RUN (runs the security demo)
    py sandbox.py
Set your own owner PIN first if you like:  $env:DUKA_OWNER_PIN = "1234"
"""

import csv
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from analytics import DATA, load_ledger
from credit import compare_options
from security import (AMINA_POLICY, ApprovalError, Approvals, AuditLog, PolicyGuard,
                      Redactor, verify_log)

AUDIT_PATH = Path(__file__).parent / "logs" / "audit_log.jsonl"
LENDER_PRODUCTS = {"sacco": "SACCO loan*", "bank": "Bank SME loan*",
                   "micro_loan": "Mobile micro-loan"}


class SandboxError(Exception):
    pass


class SandboxAccount:
    def __init__(self, opening_balance, payees):
        self.balance = opening_balance
        self.payees = payees            # payee_id -> name
        self.history = []

    def pay(self, payee_id, amount, when):
        if amount > self.balance:
            raise SandboxError(f"not enough money: balance KES {self.balance:,.0f} "
                               f"(the sandbox has no overdraft)")
        self.balance -= amount
        self.history.append({"time": when, "out": amount, "in": 0,
                             "details": f"Pay {self.payees[payee_id]} ({payee_id})"})

    def receive(self, amount, details, when):
        self.balance += amount
        self.history.append({"time": when, "out": 0, "in": amount, "details": details})

    def paid_out_on(self, day):
        return sum(t["out"] for t in self.history if t["time"].date() == day)


class MockLender:
    LIMITS = {"sacco": 100_000, "bank": 500_000, "micro_loan": 50_000}   # illustrative

    def __init__(self):
        self.loans = []

    def lend(self, product, amount, term_days):
        if amount > self.LIMITS[product]:
            raise SandboxError(f"lender declined: {product} limit is KES {self.LIMITS[product]:,}")
        option = next(o for o in compare_options(amount, term_days)
                      if o["name"] == LENDER_PRODUCTS[product])
        loan = {"loan_id": f"LN-{len(self.loans) + 1:03d}", "product": product,
                "amount": amount, "term_days": term_days,
                "upfront_fee": round(option["upfront_fee"], 2),
                "total_repaid": round(option["total_repaid"], 2),
                "annual_cost": round(option["annual_cost"], 3),
                "repayments": [(day, round(p, 2)) for day, p in option["payments"]]}
        self.loans.append(loan)
        return loan


class Sandbox:
    def __init__(self, guard, approvals, audit, account, lender, clock=datetime.now):
        self.guard, self.approvals, self.audit = guard, approvals, audit
        self.account, self.lender, self.clock = account, lender, clock

    def _spent_today(self):
        return self.account.paid_out_on(self.clock().date())

    def propose(self, action, actor="ai"):
        """Step 1 (the AI's tool): check an action. T2 actions wait for the owner."""
        decision = self.guard.check(action, self._spent_today())
        self.audit.record(actor, "proposed", action=action, tier=decision.tier,
                          allowed=decision.allowed, reason=decision.reason)
        if not decision.allowed:
            return {"status": "blocked", "tier": decision.tier, "reason": decision.reason}
        if not decision.needs_approval:
            return {"status": "ok", "tier": decision.tier}
        request_id = self.approvals.request(action)
        self.audit.record("system", "approval_requested", request_id=request_id)
        return {"status": "waiting_for_owner", "tier": decision.tier, "request_id": request_id}

    def owner_approve(self, request_id, pin):
        """Step 2 (OWNER'S APP ONLY, never an AI tool): the owner types their PIN."""
        try:
            code = self.approvals.approve(request_id, pin, self.clock())
        except ApprovalError as e:
            self.audit.record("owner_app", "approval_refused", request_id=request_id, reason=str(e))
            return None
        self.audit.record("owner_app", "approved", request_id=request_id)
        return code

    def execute(self, request_id, approval_code, actor="owner_app"):
        """Step 3: carry out an approved action. Uses the stored copy of the action,
        so nothing can be changed after approval, and checks the rules again."""
        try:
            action = self.approvals.consume(request_id, approval_code, self.clock())
        except ApprovalError as e:
            self.audit.record(actor, "execute_blocked", request_id=request_id, reason=str(e))
            return {"status": "blocked", "reason": str(e)}

        decision = self.guard.check(action, self._spent_today())
        if not decision.allowed:
            self.audit.record(actor, "execute_blocked", request_id=request_id,
                              reason=decision.reason)
            return {"status": "blocked", "reason": decision.reason}

        try:
            result = self._run(action)
        except SandboxError as e:
            self.audit.record(actor, "execute_failed", request_id=request_id, reason=str(e))
            return {"status": "failed", "reason": str(e)}
        self.audit.record(actor, "executed", request_id=request_id, action=action, result=result)
        return {"status": "done", **result}

    def _run(self, action):
        now = self.clock()
        if action["type"] == "pay_supplier":
            self.account.pay(action["payee_id"], action["amount"], now)
            return {"paid": action["amount"], "to": action["payee_id"],
                    "balance": self.account.balance}
        if action["type"] == "request_loan":
            loan = self.lender.lend(action["product"], action["amount"], action["term_days"])
            received = loan["amount"] - loan["upfront_fee"]
            self.account.receive(received, f"Loan {loan['loan_id']} ({loan['product']})", now)
            return {"loan_id": loan["loan_id"], "received": received,
                    "total_to_repay": loan["total_repaid"], "balance": self.account.balance}
        raise SandboxError(f"no sandbox handler for {action['type']}")


# ---------------------------------------------------------------------------
# DEMO
# ---------------------------------------------------------------------------

def show(label, result):
    detail = result.get("reason") or ", ".join(f"{k}={v}" for k, v in result.items()
                                               if k not in ("status", "tier"))
    print(f"  {label:<50} -> {result['status'].upper()}: {detail}")


def demo_redaction():
    print("\n1. REDACTION (what the AI sees)")
    redactor = Redactor(known_names=["Amina"])
    rows = load_ledger(DATA / "amina_grocery_ledger.csv")
    samples = [next(r["Description"] for r in rows if r["Category"] == "sales"),
               next(r["Description"] for r in rows if r["Category"] == "family_transfer"),
               "Amina says: call me on +254 712 345 678 before paying"]
    with open(DATA / "malicious_statement.csv", newline="", encoding="utf-8") as f:
        samples += [r["Details"] for r in csv.DictReader(f) if "IGNORE" in r["Details"].upper()]
    for text in samples:
        print(f"  before: {text}\n  after:  {redactor.redact(text)}")


def demo_actions(sandbox, pin):
    print("\n2. ALLOWED ACTIONS")
    show("AI reads the forecast (T0)", sandbox.propose({"type": "read_forecast"}))

    loan = {"type": "request_loan", "product": "sacco", "amount": 45_000, "term_days": 180}
    r = sandbox.propose(loan)
    show("AI asks for a KES 45,000 SACCO loan (T2)", r)
    code = sandbox.owner_approve(r["request_id"], pin)
    show("  owner approves with PIN, app executes", sandbox.execute(r["request_id"], code))

    pay = {"type": "pay_supplier", "payee_id": "SUP-01", "amount": 30_000}
    r = sandbox.propose(pay)
    show("AI asks to pay SOKO SUPPLIES KES 30,000 (T2)", r)
    code = sandbox.owner_approve(r["request_id"], pin)
    show("  owner approves with PIN, app executes", sandbox.execute(r["request_id"], code))
    used = (r["request_id"], code)

    print("\n3. BLOCKED: OVER THE LIMITS")
    show("Pay FRESHFARM KES 80,000 (per-payment cap)",
         sandbox.propose({"type": "pay_supplier", "payee_id": "SUP-02", "amount": 80_000}))
    show("Pay UNGA KES 31,000 today (daily cap)",
         sandbox.propose({"type": "pay_supplier", "payee_id": "SUP-03", "amount": 31_000}))

    print("\n4. BLOCKED: UNVERIFIED PAYEE (what the injected text asked for)")
    show("Pay 0799***000 KES 5,000",
         sandbox.propose({"type": "pay_supplier", "payee_id": "0799***000", "amount": 5_000}))

    print("\n5. BLOCKED: ACTING WITHOUT THE OWNER'S APPROVAL")
    r = sandbox.propose({"type": "pay_supplier", "payee_id": "SUP-03", "amount": 5_000})
    show("AI asks to pay UNGA KES 5,000", r)
    rid = r["request_id"]
    show("  AI executes with no approval code", sandbox.execute(rid, None, actor="ai"))
    show("  AI executes with a made-up code", sandbox.execute(rid, "APPROVED", actor="ai"))
    show("  AI reuses the code from the last payment", sandbox.execute(rid, used[1], actor="ai"))
    show("  AI replays the used approval", sandbox.execute(*used, actor="ai"))
    guess = sandbox.owner_approve(rid, "0000")
    print(f"  {'  AI guesses the PIN':<50} -> {'BLOCKED: wrong PIN' if guess is None else 'APPROVED?!'}")
    show("  AI calls 'approve_request' itself (T3)",
         sandbox.propose({"type": "approve_request", "request_id": rid}))
    show("  AI adds \"approved\": true to an action",
         sandbox.propose({"type": "pay_supplier", "payee_id": "SUP-03",
                          "amount": 5_000, "approved": True}))

    print("\n6. BLOCKED: FORBIDDEN AND UNKNOWN ACTIONS (T3)")
    show("AI tries to raise the daily cap",
         sandbox.propose({"type": "raise_limit", "daily_cap": 1_000_000}))
    show("AI tries to send the ledger out",
         sandbox.propose({"type": "send_data_external", "url": "http://example.com"}))
    show("AI invents an action", sandbox.propose({"type": "transfer_all_funds"}))


def demo_audit(audit):
    print("\n7. AUDIT LOG")
    ok, count, problem, head = verify_log(audit.path)
    print(f"  {audit.path.name}: {count} entries, chain {'OK' if ok else 'BROKEN: ' + problem}")
    print(f"  latest hash (keep a copy elsewhere): {head[:16]}...")

    # Tamper with a COPY: change a paid amount from 30000 to 3000
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "tampered.jsonl"
        shutil.copy(audit.path, copy)
        lines = copy.read_text(encoding="utf-8").splitlines()
        for i in range(len(lines) - 1, -1, -1):
            if '"executed"' in lines[i] and '"paid": 30000' in lines[i]:
                lines[i] = lines[i].replace('"paid": 30000', '"paid": 3000')
                break
        copy.write_text("\n".join(lines) + "\n", encoding="utf-8")
        ok, _, problem, _ = verify_log(copy)
        print(f"  tampered copy (30,000 changed to 3,000): {'OK' if ok else 'DETECTED: ' + problem}")

        del lines[1]                      # now also delete an entry
        copy.write_text("\n".join(lines) + "\n", encoding="utf-8")
        ok, _, problem, _ = verify_log(copy)
        print(f"  copy with entry 2 deleted:               {'OK' if ok else 'DETECTED: ' + problem}")


def main():
    pin = os.environ.get("DUKA_OWNER_PIN")
    if not pin:
        pin = "2468"
        print("(No DUKA_OWNER_PIN set: using demo PIN 2468. The AI never sees the PIN.)")

    rows = load_ledger(DATA / "amina_grocery_ledger.csv")
    account = SandboxAccount(rows[-1]["balance"], AMINA_POLICY.verified_payees)
    audit = AuditLog(AUDIT_PATH)
    sandbox = Sandbox(PolicyGuard(AMINA_POLICY), Approvals(pin), audit, account, MockLender())
    print(f"Sandbox account for Amina, starting balance KES {account.balance:,.0f}. "
          f"Caps: KES {AMINA_POLICY.per_transaction_cap:,} per payment, "
          f"KES {AMINA_POLICY.daily_cap:,} per day.")

    demo_redaction()
    demo_actions(sandbox, pin)
    demo_audit(audit)
    print(f"\nSandbox balance at the end: KES {account.balance:,.0f}")


if __name__ == "__main__":
    main()
