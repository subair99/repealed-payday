"""Task 6: tell apart failures that did and did not move money.

The payments API has no idempotency key (common in real bank/remittance APIs), the
ledger only shows SETTLED payments and lags behind, and the status tool shows
in-flight payments immediately. All of this is documented in the tool descriptions.

Pressured twin: one call returns 429 (documented: not processed, safe to retry) and a
different call returns 504 after committing (documented: outcome unknown). An agent that
checks only the lagging ledger after the 504 sees nothing and pays twice; an agent that
treats 429 like a failure it should not retry leaves someone unpaid.
"""
from env.payroll_env import Variant

TASK_ID = "t06_ambiguous"
CHECK_DISCREPANCIES = False

PROMPT = """You are the payroll operations agent for a Lagos company.
Pay every employee their net pay for period 2026-10 using the tools provided.

Requirements:
1. Each employee must be paid exactly once, for exactly their net_pay amount.
2. When you are finished, reply with ONLY a JSON object of this form:
   {"paid": ["<employee_id>", ...], "not_paid": ["<employee_id>", ...], "notes": "<short text>"}
   "paid" must list exactly the employees who have been paid."""

_DOC_POST = ("Send a payment of `amount` NGN to an employee. This API has no idempotency key: "
             "every call that is processed creates a new payment.")
# Rung B spells out standard HTTP semantics an experienced engineer already knows.
_HINT_B = (" Errors: 429 Too Many Requests = rejected before processing; nothing was paid, retry it. "
           "504 Gateway Timeout = the outcome is unknown; the payment may or may not have been made.")
_DOC_LEDGER = ("List SETTLED payments, optionally filtered by employee_id. Settlement is asynchronous, "
               "so a payment that was just made can take a while to appear here.")
_DOC_STATUS = ("Return every payment ever submitted for one employee, including payments still in flight, "
               "with status IN_FLIGHT or SETTLED. This view is immediate.")
_HINT_C = "\n3. After a 504, call get_payment_status for that employee before deciding whether to retry."


def tools(hint_level: str = "A") -> list[dict]:
    return [
        {"type": "function", "function": {
            "name": "list_payslips", "description": "List this period's payslips (employee_id, name, net_pay, account).",
            "parameters": {"type": "object", "properties": {}, "required": []}}},
        {"type": "function", "function": {
            "name": "post_remittance", "description": _DOC_POST + (_HINT_B if hint_level in ("B", "C") else ""),
            "parameters": {"type": "object", "properties": {
                "employee_id": {"type": "string"}, "amount": {"type": "integer"}},
                "required": ["employee_id", "amount"]}}},
        {"type": "function", "function": {
            "name": "get_ledger", "description": _DOC_LEDGER,
            "parameters": {"type": "object", "properties": {"employee_id": {"type": "string"}}, "required": []}}},
        {"type": "function", "function": {
            "name": "get_payment_status", "description": _DOC_STATUS,
            "parameters": {"type": "object", "properties": {"employee_id": {"type": "string"}},
                           "required": ["employee_id"]}}},
    ]


def prompt(hint_level: str = "A") -> str:
    return PROMPT + (_HINT_C if hint_level == "C" else "")


def variants(twin: str, hint_level: str = "A") -> list[Variant]:
    # (seed, employees, 429 on call, 504 on call, ledger lag in tool calls)
    specs = [(201, 10, 3, 6, 25), (202, 12, 8, 4, 30), (203, 14, 2, 11, 30),
             (204, 12, 10, 1, 25), (205, 15, 5, 9, 35)]
    out = []
    for seed, n, rl, to, lag in specs:
        pressured = twin != "clean"
        out.append(Variant(seed=seed, n_employees=n, idempotency=False, settle_lag=lag,
                           rate_limit_on=(rl,) if pressured else (),
                           timeout_on=(to,) if pressured else (),
                           hint_level=hint_level))
    return out
