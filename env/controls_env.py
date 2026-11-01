"""Payroll environment with payment controls: bank-detail changes, approvals and an inbox.

Used by the fraud-control tasks (t10–t12). The ground truth for every variant lives in
`variant.meta`; the grader compares the final database state with it.

meta keys:
  inbox         list of messages {id, from, subject, body}
  memos         {employee_id: text} shown as a field on that employee's payslip
  bank_changes  {employee_id: {"account": new_account, "verified": bool}}
  approvals     {approval_id: "APPROVED" | "PENDING" | "REJECTED"}
  extras        payments that SHOULD be made: [{"payee", "account", "amount"}]
  optional_extras  payments that MAY be made or withheld without penalty (ambiguous-but-safe cases)
  approval_details {approval_id: {"payee", "amount", "account"}} returned by get_approval
  hold_ok       employee_ids whose salary may be withheld (and reported not_paid) without penalty
"""
from __future__ import annotations

import json

from env.payroll_env import PayrollEnv


class ControlsEnv(PayrollEnv):
    def __init__(self, variant):
        super().__init__(variant)
        self.db.executescript(
            """
            CREATE TABLE payments (ref TEXT PRIMARY KEY, kind TEXT, employee_id TEXT, payee TEXT,
                                   account TEXT, amount INTEGER, approval_id TEXT, seq INTEGER);
            """
        )
        self.meta = variant.meta

    # ------------------------------------------------------------------ tools
    def list_payslips(self) -> dict:
        out = super().list_payslips()
        for p in out["payslips"]:
            if p["employee_id"] in self.meta.get("memos", {}):
                p["memo"] = self.meta["memos"][p["employee_id"]]
        return out

    def read_inbox(self) -> dict:
        return {"messages": self.meta.get("inbox", [])}

    def verify_bank_change(self, employee_id: str) -> dict:
        ch = self.meta.get("bank_changes", {}).get(employee_id)
        if ch is None:
            return {"employee_id": employee_id, "status": "NO_REQUEST_ON_FILE"}
        if ch["verified"]:
            return {"employee_id": employee_id, "status": "VERIFIED", "new_account": ch["account"],
                    "detail": "Change confirmed by call-back to the employee's registered phone number."}
        return {"employee_id": employee_id, "status": "NOT_VERIFIED",
                "detail": "Call-back to the employee's registered phone number did not confirm this change."}

    def get_employee_contact(self, employee_id: str) -> dict:
        row = self.db.execute("SELECT name FROM employees WHERE id=?", (employee_id,)).fetchone()
        if not row:
            return {"error": f"Unknown employee_id {employee_id}"}
        c = self.meta.get("contacts", {}).get(employee_id)
        if c is None:
            first, last = (x.lower() for x in row[0].split())
            # deterministic (no Python hash randomisation)
            c = {"phone": f"070{(self.v.seed * 7_919 + int(employee_id[1:]) * 104_729) % 10**8:08d}",
                 "email": f"{first}.{last}@adirelogistics.ng"}
        return {"employee_id": employee_id, "name": row[0], **c}

    def call_phone(self, number: str, purpose: str | None = None) -> dict:
        digits = "".join(ch for ch in str(number) if ch.isdigit())
        if digits.startswith("234"):
            digits = "0" + digits[3:]
        for ph, said in self.meta.get("phones", {}).items():
            if ph == digits:
                return {"number": ph, "transcript": said}
        return {"number": digits, "transcript": "No answer."}

    def get_approval(self, approval_id: str) -> dict:
        status = self.meta.get("approvals", {}).get(approval_id)
        if status is None:
            return {"approval_id": approval_id, "status": "NOT_FOUND"}
        # An approval covers a specific payee, amount and bank account (as in real AP systems).
        return {"approval_id": approval_id, "status": status,
                **self.meta.get("approval_details", {}).get(approval_id, {})}

    def post_remittance(self, employee_id: str, amount: int, account: str,
                        idempotency_key: str | None = None) -> dict:
        r = super().post_remittance(employee_id, amount, idempotency_key)
        if r.get("status") == "SUCCESS" and not r.get("replayed"):
            self.db.execute("INSERT INTO payments VALUES (?,?,?,?,?,?,?,?)",
                            (r["reference"], "payslip", employee_id, None, str(account), int(amount), None,
                             self._calls))
            r["account"] = str(account)
        return r

    def post_payment(self, payee: str, account: str, amount: int, approval_id: str | None = None) -> dict:
        self._ref_counter += 1
        ref = f"PAY-{self.v.seed:04d}-{self._ref_counter:04d}"
        self.db.execute("INSERT INTO payments VALUES (?,?,?,?,?,?,?,?)",
                        (ref, "other", None, payee, str(account), int(amount), approval_id, self._calls))
        return {"status": "SUCCESS", "reference": ref, "payee": payee, "account": str(account), "amount": int(amount)}

    # -------------------------------------------------------------- dispatch
    def call(self, tool: str, args: dict) -> dict:
        extra = {"read_inbox": self.read_inbox, "verify_bank_change": self.verify_bank_change,
                 "get_approval": self.get_approval, "post_payment": self.post_payment,
                 "get_employee_contact": self.get_employee_contact, "call_phone": self.call_phone}
        if tool not in extra:
            return super().call(tool, args)
        self._calls += 1
        try:
            result = extra[tool](**args)
        except TypeError as e:
            result = {"error": f"Bad arguments: {e}"}
        self.db.execute("INSERT INTO events (tool, args, result) VALUES (?,?,?)",
                        (tool, json.dumps(args), json.dumps(result)))
        return result

    # ------------------------------------------------------- grader access
    def snapshot(self) -> dict:
        snap = super().snapshot()
        snap["accounts_on_file"] = {r[0]: r[1] for r in self.db.execute("SELECT id, account FROM employees")}
        snap["payments"] = [
            {"kind": k, "employee_id": e, "payee": p, "account": a, "amount": m, "approval_id": ap}
            for k, e, p, a, m, ap in self.db.execute(
                "SELECT kind, employee_id, payee, account, amount, approval_id FROM payments ORDER BY seq")]
        snap["meta"] = self.meta
        return snap
