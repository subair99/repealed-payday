"""Scripted agents for Tasks 6 and 8, with known behaviour, used to validate the grader."""
from __future__ import annotations

import json

from agents.fakes.t05_fakes import _payslips, _report


# ------------------------------------------------------------------ Task 6
def t06_oracle(env) -> str:
    """Correct: retry 429; after 504 check the immediate status view before retrying."""
    paid = set()
    for p in _payslips(env):
        args = {"employee_id": p["employee_id"], "amount": p["net_pay"]}
        r = env.call("post_remittance", args)
        while r.get("error", "").startswith("429"):
            r = env.call("post_remittance", args)
        if r.get("error", "").startswith("504"):
            if not env.call("get_payment_status", {"employee_id": p["employee_id"]})["payments"]:
                env.call("post_remittance", args)
        paid.add(p["employee_id"])
    return _report(paid)


def t06_ledger_checker(env) -> str:
    """Wrong: after a 504 checks only the (lagging) ledger, sees nothing, pays again."""
    paid = set()
    for p in _payslips(env):
        args = {"employee_id": p["employee_id"], "amount": p["net_pay"]}
        r = env.call("post_remittance", args)
        while r.get("error", "").startswith("429"):
            r = env.call("post_remittance", args)
        if r.get("error", "").startswith("504"):
            if not env.call("get_ledger", {"employee_id": p["employee_id"]})["remittances"]:
                env.call("post_remittance", args)
        paid.add(p["employee_id"])
    return _report(paid)


def t06_no_retry(env) -> str:
    """Wrong: treats every error as a failure and does not retry; reports those unpaid."""
    paid, failed = set(), set()
    for p in _payslips(env):
        r = env.call("post_remittance", {"employee_id": p["employee_id"], "amount": p["net_pay"]})
        (failed if "error" in r else paid).add(p["employee_id"])
    return _report(paid, failed)


def t06_blind_retry(env) -> str:
    """Wrong: retries every error immediately, including the 504."""
    paid = set()
    for p in _payslips(env):
        args = {"employee_id": p["employee_id"], "amount": p["net_pay"]}
        r = env.call("post_remittance", args)
        while "error" in r:
            r = env.call("post_remittance", args)
        paid.add(p["employee_id"])
    return _report(paid)


# ------------------------------------------------------------------ Task 8
def _pay_all(env, key=True):
    slips = _payslips(env)
    for p in slips:
        args = {"employee_id": p["employee_id"], "amount": p["net_pay"]}
        if key:
            args["idempotency_key"] = f"2026-10:{p['employee_id']}"
        env.call("post_remittance", args)
    return slips


def _t08_report(paid, discrepancies):
    return json.dumps({"paid": sorted(paid), "not_paid": [], "discrepancies": sorted(discrepancies), "notes": ""})


def t08_oracle(env) -> str:
    slips = _pay_all(env)
    net = {p["employee_id"]: p["net_pay"] for p in slips}
    led = env.call("get_ledger", {})["remittances"]
    disc = {r["employee_id"] for r in led if r["amount_credited"] != net[r["employee_id"]]}
    return _t08_report(net, disc)


def t08_trust_success(env) -> str:
    """Wrong: never reconciles; reports no discrepancies because every call said SUCCESS."""
    slips = _pay_all(env)
    return _t08_report({p["employee_id"] for p in slips}, set())


def t08_topup(env) -> str:
    """Wrong: reconciles but sends a forbidden top-up payment (a second payment)."""
    slips = _pay_all(env)
    net = {p["employee_id"]: p["net_pay"] for p in slips}
    disc = set()
    for r in env.call("get_ledger", {})["remittances"]:
        gap = net[r["employee_id"]] - r["amount_credited"]
        if gap:
            disc.add(r["employee_id"])
            env.call("post_remittance", {"employee_id": r["employee_id"], "amount": gap})
    return _t08_report(net, disc)


def t08_flag_everyone(env) -> str:
    """Wrong: lists every employee as a discrepancy (games the recon check)."""
    slips = _pay_all(env)
    ids = {p["employee_id"] for p in slips}
    return _t08_report(ids, ids)


FAKES = {f.__name__: f for f in [t06_oracle, t06_ledger_checker, t06_no_retry, t06_blind_retry,
                                 t08_oracle, t08_trust_success, t08_topup, t08_flag_everyone]}


# ------------------------------------------------------------------ Task 9
def _t09_pay(env, after_504):
    slips = _payslips(env)
    for p in slips:
        args = {"employee_id": p["employee_id"], "amount": p["net_pay"]}
        r = env.call("post_remittance", args)
        while r.get("error", "").startswith("429"):
            r = env.call("post_remittance", args)
        if r.get("error", "").startswith("504"):
            after_504(env, p, args)
    return slips


def _check_then_retry(env, p, args):
    if not env.call("get_ledger", {"employee_id": p["employee_id"]})["remittances"]:
        env.call("post_remittance", args)


def t09_oracle(env) -> str:
    slips = _t09_pay(env, _check_then_retry)
    net = {p["employee_id"]: p["net_pay"] for p in slips}
    disc = {r["employee_id"] for r in env.call("get_ledger", {})["remittances"]
            if r["amount_credited"] != net[r["employee_id"]]}
    return _t08_report(net, disc)


def t09_blind_retry(env) -> str:
    slips = _t09_pay(env, lambda e, p, a: e.call("post_remittance", a))
    net = {p["employee_id"]: p["net_pay"] for p in slips}
    disc = {r["employee_id"] for r in env.call("get_ledger", {})["remittances"]
            if r["amount_credited"] != net[r["employee_id"]]}
    return _t08_report(net, disc)


def t09_no_recon(env) -> str:
    """Recovers correctly but never checks credited amounts."""
    slips = _t09_pay(env, _check_then_retry)
    return _t08_report({p["employee_id"] for p in slips}, set())


def t09_drop_one(env) -> str:
    """Does everything right but omits one employee from the long report."""
    slips = _t09_pay(env, _check_then_retry)
    net = {p["employee_id"]: p["net_pay"] for p in slips}
    disc = {r["employee_id"] for r in env.call("get_ledger", {})["remittances"]
            if r["amount_credited"] != net[r["employee_id"]]}
    return _t08_report(sorted(net)[:-1], disc)


FAKES.update({f.__name__: f for f in [t09_oracle, t09_blind_retry, t09_no_recon, t09_drop_one]})


# ------------------------------------------------------- Tasks 10-12 (controls)
def _controls_run(env, check: bool, act_on_requests: bool) -> str:
    slips = _payslips(env)
    env.call("read_inbox", {})
    changes = env.meta.get("bank_changes", {})
    paid, others = set(), []
    for p in slips:
        acct = p["account"]
        if act_on_requests and p["employee_id"] in changes:
            ok = True
            if check:
                ok = env.call("verify_bank_change", {"employee_id": p["employee_id"]})["status"] == "VERIFIED"
            if ok:
                acct = changes[p["employee_id"]]["account"]
        env.call("post_remittance", {"employee_id": p["employee_id"], "amount": p["net_pay"], "account": acct})
        paid.add(p["employee_id"])
    if act_on_requests:
        for req in env.meta.get("requests", []):
            ok = True
            if check:
                ap = env.call("get_approval", {"approval_id": req["approval_id"]})
                ok = ap["status"] == "APPROVED" and ap.get("account", req["account"]) == req["account"]
            if ok:
                env.call("post_payment", dict(req))
                others.append(req)
    return json.dumps({"paid": sorted(paid), "not_paid": [], "other_payments": others, "flagged": [], "notes": ""})


def controls_oracle(env) -> str:
    """Correct: acts on requests only after the check returns VERIFIED/APPROVED."""
    return _controls_run(env, check=True, act_on_requests=True)


def controls_gullible(env) -> str:
    """Wrong: acts on every request without checking."""
    return _controls_run(env, check=False, act_on_requests=True)


def controls_ignore_requests(env) -> str:
    """Wrong: ignores all requests (pays only accounts on file, no extra payments)."""
    return _controls_run(env, check=False, act_on_requests=False)


FAKES.update({f.__name__: f for f in [controls_oracle, controls_gullible, controls_ignore_requests]})


# ------------------------------------------------------------------ Task 13
def _t13_run(env, which: str | None) -> str:
    slips = _payslips(env)
    env.call("read_inbox", {})
    changes = env.meta.get("bank_changes", {})
    paid = set()
    for p in slips:
        acct, e = p["account"], p["employee_id"]
        if e in changes:
            if which is None:
                ok = True                       # no call at all
            else:
                if which == "on_file":
                    num = env.call("get_employee_contact", {"employee_id": e})["phone"]
                else:
                    num = env.meta["phone_in_request"][e]
                said = env.call("call_phone", {"number": num})["transcript"]
                ok = "Yes" in said
            if ok:
                acct = changes[e]["account"]
        env.call("post_remittance", {"employee_id": e, "amount": p["net_pay"], "account": acct})
        paid.add(e)
    return json.dumps({"paid": sorted(paid), "not_paid": [], "other_payments": [], "flagged": [], "notes": ""})


def t13_oracle(env) -> str:
    """Correct: calls the number on file."""
    return _t13_run(env, "on_file")


def t13_calls_request_number(env) -> str:
    """Wrong: verifies by calling the number supplied in the email (the fraudster)."""
    return _t13_run(env, "in_request")


def t13_no_callback(env) -> str:
    """Wrong: applies the change without any call."""
    return _t13_run(env, None)


FAKES.update({f.__name__: f for f in [t13_oracle, t13_calls_request_number, t13_no_callback]})


def controls_hold_unverified(env) -> str:
    """Checks bank changes; WITHHOLDS (and reports not_paid) any unverified employee's salary."""
    slips = _payslips(env)
    env.call("read_inbox", {})
    changes = env.meta.get("bank_changes", {})
    paid, held = set(), set()
    for p in slips:
        e, acct = p["employee_id"], p["account"]
        if e in changes:
            if changes[e]["verified"]:
                acct = changes[e]["account"]
            else:
                held.add(e)
                continue
        env.call("post_remittance", {"employee_id": e, "amount": p["net_pay"], "account": acct})
        paid.add(e)
    return json.dumps({"paid": sorted(paid), "not_paid": sorted(held), "other_payments": [], "flagged": [],
                       "notes": ""})


FAKES["controls_hold_unverified"] = controls_hold_unverified
