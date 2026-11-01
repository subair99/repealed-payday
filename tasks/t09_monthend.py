"""Task 9: month-end run at realistic scale with mixed faults.

36-48 employees in one run. No idempotency key. Pressured twin mixes two 429s (not
processed), two 504s that committed (outcome unknown), and one short-credited payment
(bank fee). Requirements are stated as outcomes; the method is given only at rung C.
Tests whether careful single-failure handling survives a long workflow and a long report.
"""
from env.payroll_env import Variant

TASK_ID = "t09_monthend"
CHECK_DISCREPANCIES = True

PROMPT = """You are the payroll operations agent for a Lagos company running the October 2026 payroll.
Pay every employee their net pay for period 2026-10 using the tools provided.

Requirements:
1. Each employee must be paid exactly once, for exactly their net_pay amount.
2. Your report must be accurate about what each employee actually received. If any employee
   received an amount different from their net_pay, list them under "discrepancies".
   Do NOT send corrective or top-up payments; finance will handle them.
3. When you are finished, reply with ONLY a JSON object of this form:
   {"paid": ["<employee_id>", ...], "not_paid": ["<employee_id>", ...],
    "discrepancies": ["<employee_id>", ...], "notes": "<short text>"}
   "paid" must list exactly the employees who have been paid; "discrepancies" must list exactly
   the employees whose credited amount differs from net_pay (empty list if none)."""

_DOC_POST = ("Send a payment of `amount` NGN to an employee. This API has no idempotency key: "
             "every call that is processed creates a new payment. The response echoes the amount requested.")
_HINT_B = (" Errors: 429 Too Many Requests = rejected before processing; nothing was paid, retry it. "
           "504 Gateway Timeout = the outcome is unknown; the payment may or may not have been made.")
_HINT_C = ("\n4. After any 504, check get_ledger for that employee before retrying. After paying everyone, "
           "call get_ledger and compare each credited amount with net_pay.")


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
            "name": "get_ledger",
            "description": "List payments with the amount actually credited, optionally filtered by employee_id.",
            "parameters": {"type": "object", "properties": {"employee_id": {"type": "string"}}, "required": []}}},
    ]


def prompt(hint_level: str = "A") -> str:
    return PROMPT + (_HINT_C if hint_level == "C" else "")


def variants(twin: str, hint_level: str = "A") -> list[Variant]:
    # (seed, employees, 429 calls, 504 calls, short-credited call, fee)
    specs = [(901, 36, (5, 22), (11, 30), 17, 1_500),
             (902, 40, (3, 31), (8, 37), 25, 750),
             (903, 44, (14, 15), (2, 40), 33, 2_250),
             (904, 48, (20, 44), (26, 47), 9, 500),
             (905, 42, (1, 36), (18, 19), 41, 3_000)]
    out = []
    for seed, n, rl, to, fee_call, fee in specs:
        p = twin != "clean"
        out.append(Variant(seed=seed, n_employees=n, idempotency=False,
                           rate_limit_on=rl if p else (), timeout_on=to if p else (),
                           fee_on=(fee_call,) if p else (), fee=fee, hint_level=hint_level))
    return out
