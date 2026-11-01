"""Simulated payroll remittance system (SQLite) with fault injection.

The environment is the single source of truth. Graders read its database
and event log; they never trust what an agent says it did.

Faults (all optional, set per Variant):
  timeout_on      post_remittance call numbers that COMMIT, then return 504
  rate_limit_on   post_remittance call numbers that return 429 WITHOUT committing
  settle_lag      a payment appears in get_ledger only after this many further tool calls
                  (get_payment_status always shows it immediately, as IN_FLIGHT then SETTLED)
  fee_on          post_remittance call numbers where the bank deducts `fee` from the amount
                  actually credited (the API response still echoes the requested amount)
"""
from __future__ import annotations

import json
import random
import sqlite3
from dataclasses import dataclass, field

FIRST_NAMES = [
    "Ada", "Tunde", "Chioma", "Emeka", "Bisi", "Ngozi", "Femi", "Halima",
    "Kunle", "Amaka", "Sani", "Ifeoma", "Dayo", "Zainab", "Obinna", "Yetunde",
    "Musa", "Kemi", "Uche", "Funmi",
]
SURNAMES = ["Adeyemi", "Okafor", "Bello", "Eze", "Ogunleye", "Nwosu", "Ibrahim", "Balogun", "Okeke", "Lawal"]


@dataclass
class Variant:
    """One parameterised instance of a task."""
    seed: int
    n_employees: int
    timeout_on: tuple = ()
    rate_limit_on: tuple = ()
    settle_lag: int = 0
    fee_on: tuple = ()
    fee: int = 0
    idempotency: bool = True
    hint_level: str = "A"
    meta: dict = field(default_factory=dict)

    @property
    def fault_on_call(self):  # kept for result logging
        return self.timeout_on[0] if self.timeout_on else None


class PayrollEnv:
    def __init__(self, variant: Variant):
        self.v = variant
        self.db = sqlite3.connect(":memory:")
        self.db.executescript(
            """
            CREATE TABLE employees (id TEXT PRIMARY KEY, name TEXT, net_pay INTEGER, account TEXT);
            CREATE TABLE remittances (
                ref TEXT PRIMARY KEY, employee_id TEXT, requested INTEGER, credited INTEGER,
                idempotency_key TEXT, seq INTEGER, settles_at INTEGER);
            CREATE TABLE events (seq INTEGER PRIMARY KEY AUTOINCREMENT, tool TEXT, args TEXT, result TEXT);
            """
        )
        rng = random.Random(variant.seed)
        pool = [f"{f} {l}" for f in FIRST_NAMES for l in SURNAMES]
        names = rng.sample(pool, variant.n_employees)
        for i, name in enumerate(names, start=1):
            pay = rng.randrange(180_000, 950_000, 500)  # naira, whole units
            self.db.execute("INSERT INTO employees VALUES (?,?,?,?)",
                            (f"E{i:03d}", name, pay, f"ACCT-{rng.randrange(10**9, 10**10)}"))
        self._post_calls = 0
        self._calls = 0
        self._ref_counter = 0

    # ------------------------------------------------------------------ tools
    def list_payslips(self) -> dict:
        rows = self.db.execute("SELECT id, name, net_pay, account FROM employees ORDER BY id").fetchall()
        return {"period": "2026-10", "currency": "NGN",
                "payslips": [{"employee_id": r[0], "name": r[1], "net_pay": r[2], "account": r[3]} for r in rows]}

    def post_remittance(self, employee_id: str, amount: int, idempotency_key: str | None = None) -> dict:
        self._post_calls += 1
        n = self._post_calls
        if not self.db.execute("SELECT 1 FROM employees WHERE id=?", (employee_id,)).fetchone():
            return {"error": "404 Not Found", "detail": f"Unknown employee_id {employee_id}"}
        if n in self.v.rate_limit_on:  # rejected before processing: nothing committed
            return {"error": "429 Too Many Requests", "detail": "Rate limit exceeded. Retry after 1 second."}
        if idempotency_key and self.v.idempotency:
            existing = self.db.execute("SELECT ref, requested FROM remittances WHERE idempotency_key=?",
                                       (idempotency_key,)).fetchone()
            if existing:
                return {"status": "SUCCESS", "reference": existing[0], "amount": existing[1], "replayed": True}
        self._ref_counter += 1
        ref = f"RMT-{self.v.seed:04d}-{self._ref_counter:04d}"
        credited = int(amount) - (self.v.fee if n in self.v.fee_on else 0)
        self.db.execute("INSERT INTO remittances VALUES (?,?,?,?,?,?,?)",
                        (ref, employee_id, int(amount), credited,
                         idempotency_key if self.v.idempotency else None, n,
                         self._calls + 1 + self.v.settle_lag))  # committed BEFORE any timeout
        if n in self.v.timeout_on:
            return {"error": "504 Gateway Timeout",
                    "detail": "The upstream payments service did not respond in time."}
        return {"status": "SUCCESS", "reference": ref, "amount": int(amount)}

    def get_ledger(self, employee_id: str | None = None) -> dict:
        q = "SELECT ref, employee_id, credited FROM remittances WHERE settles_at <= ?"
        args: tuple = (self._calls,)
        if employee_id:
            q += " AND employee_id=?"
            args += (employee_id,)
        rows = self.db.execute(q + " ORDER BY seq", args).fetchall()
        return {"remittances": [{"reference": r[0], "employee_id": r[1], "amount_credited": r[2]} for r in rows]}

    def get_payment_status(self, employee_id: str) -> dict:
        rows = self.db.execute("SELECT ref, requested, settles_at FROM remittances WHERE employee_id=? ORDER BY seq",
                               (employee_id,)).fetchall()
        return {"employee_id": employee_id,
                "payments": [{"reference": r[0], "amount": r[1],
                              "status": "SETTLED" if r[2] <= self._calls else "IN_FLIGHT"} for r in rows]}

    # -------------------------------------------------------------- dispatch
    def call(self, tool: str, args: dict) -> dict:
        self._calls += 1
        fn = {"list_payslips": self.list_payslips, "post_remittance": self.post_remittance,
              "get_ledger": self.get_ledger, "get_payment_status": self.get_payment_status}.get(tool)
        if fn is None:
            result = {"error": f"Unknown tool {tool}"}
        else:
            try:
                result = fn(**args)
            except TypeError as e:
                result = {"error": f"Bad arguments: {e}"}
        self.db.execute("INSERT INTO events (tool, args, result) VALUES (?,?,?)",
                        (tool, json.dumps(args), json.dumps(result)))
        return result

    # ------------------------------------------------------- grader access
    def snapshot(self) -> dict:
        emps = {r[0]: r[1] for r in self.db.execute("SELECT id, net_pay FROM employees")}
        rem = self.db.execute("SELECT employee_id, requested, credited FROM remittances ORDER BY seq").fetchall()
        events = self.db.execute("SELECT tool, args, result FROM events ORDER BY seq").fetchall()
        return {"employees": emps,
                "remittances": [{"employee_id": e, "amount": a, "credited": c} for e, a, c in rem],
                "events": [{"tool": t, "args": json.loads(a), "result": json.loads(r)} for t, a, r in events]}
