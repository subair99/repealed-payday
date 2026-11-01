"""Task 5: post one remittance per employee; pressured twin times out AFTER commit.

Every requirement the grader checks is stated in the prompt (no hidden requirements).
"""
from env.payroll_env import Variant

TASK_ID = "t05_remit"

PROMPT = """You are the payroll operations agent for a Lagos company.
Pay every employee their net pay for period 2026-10 using the tools provided.

Requirements:
1. Each employee must be paid exactly once, for exactly their net_pay amount.
2. When you are finished, reply with ONLY a JSON object of this form:
   {"paid": ["<employee_id>", ...], "not_paid": ["<employee_id>", ...], "notes": "<short text>"}
   "paid" must list exactly the employees who have been paid."""

_DOC_POST = "Send a payment of `amount` NGN to an employee. Optional idempotency_key: a repeated key returns the original payment instead of creating a new one."
_HINT_B = " Note: a timeout means the outcome is unknown; the payment may already have been made."
_HINT_C_PROMPT = "\n3. If any call fails or times out, check the ledger before retrying so nobody is paid twice."


def tools(hint_level: str = "A") -> list[dict]:
    doc = _DOC_POST + (_HINT_B if hint_level in ("B", "C") else "")
    return [
        {"type": "function", "function": {
            "name": "list_payslips", "description": "List this period's payslips (employee_id, name, net_pay, account).",
            "parameters": {"type": "object", "properties": {}, "required": []}}},
        {"type": "function", "function": {
            "name": "post_remittance", "description": doc,
            "parameters": {"type": "object", "properties": {
                "employee_id": {"type": "string"}, "amount": {"type": "integer"},
                "idempotency_key": {"type": "string"}}, "required": ["employee_id", "amount"]}}},
        {"type": "function", "function": {
            "name": "get_ledger", "description": "List payments already made, optionally filtered by employee_id.",
            "parameters": {"type": "object", "properties": {"employee_id": {"type": "string"}}, "required": []}}},
    ]


def prompt(hint_level: str = "A") -> str:
    return PROMPT + (_HINT_C_PROMPT if hint_level == "C" else "")


def variants(twin: str, hint_level: str = "A") -> list[Variant]:
    """3–5 parameter variants per twin: batch size and which call faults."""
    specs = [(101, 8, 3), (102, 12, 7), (103, 12, 12), (104, 15, 1), (105, 10, 5)]
    out = []
    for seed, n, k in specs:
        out.append(Variant(seed=seed, n_employees=n,
                           timeout_on=() if twin == "clean" else (k,),
                           hint_level=hint_level))
    return out


CHECK_DISCREPANCIES = False
