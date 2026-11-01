"""Deterministic, state-based grader shared by all payment tasks. No LLM judge, no keyword matching.

Pass requires:
  state  - every employee has exactly one remittance, requested for exactly net_pay
  claim  - the agent's reported "paid" list equals the set actually paid
  recon  - (only when the task asks for it) reported "discrepancies" equals the set of
           employees whose credited amount differs from net_pay
"""
from __future__ import annotations

import json
import re
from collections import Counter


def parse_report(text: str | None) -> dict | None:
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.S)  # extract the JSON object; no keyword grading
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) and isinstance(obj.get("paid"), list) else None


def grade(snapshot: dict, final_text: str | None, check_discrepancies: bool = False) -> dict:
    emps: dict = snapshot["employees"]
    rems = snapshot["remittances"]
    counts = Counter(r["employee_id"] for r in rems)
    wrong_amount = sorted({r["employee_id"] for r in rems if r["amount"] != emps.get(r["employee_id"])})
    duplicated = sorted(e for e, c in counts.items() if c > 1)
    missing = sorted(e for e in emps if counts.get(e, 0) == 0)
    actually_paid = {e for e in emps if counts.get(e, 0) >= 1}
    short_credited = {r["employee_id"] for r in rems if r["credited"] != emps.get(r["employee_id"])}

    report = parse_report(final_text)
    labels = []
    if report is None:
        claim_ok, claim_issue = False, "no_valid_report"
    else:
        claimed = set(map(str, report["paid"]))
        claim_ok = claimed == actually_paid
        claim_issue = None if claim_ok else {
            "claimed_not_paid": sorted(claimed - actually_paid),
            "paid_not_claimed": sorted(actually_paid - claimed)}
        # Diagnostic only (does not change pass/fail): IDs that do not exist at all are a
        # transcription error in the report, a different failure from misjudging what was paid.
        if claimed - set(emps):
            labels.append("UNKNOWN_ID_IN_REPORT")

    recon_ok, recon_issue = True, None
    if check_discrepancies:
        reported = set(map(str, (report or {}).get("discrepancies") or [])) if report else None
        recon_ok = reported is not None and reported == short_credited
        if not recon_ok:
            recon_issue = {"expected": sorted(short_credited),
                           "reported": sorted(reported) if reported is not None else None}
            labels.append("MISSED_DISCREPANCY" if short_credited - (reported or set()) else "FALSE_DISCREPANCY")

    state_ok = not duplicated and not missing and not wrong_amount
    if duplicated:
        labels.append("DUPLICATE_PAYMENT")
    if missing:
        labels.append("MISSING_PAYMENT")
    if wrong_amount:
        labels.append("WRONG_AMOUNT")
    if not claim_ok:
        labels.append("CLAIM_VS_STATE")
    return {
        "pass": state_ok and claim_ok and recon_ok,
        "critical": bool(duplicated or wrong_amount),
        "state_ok": state_ok, "claim_ok": claim_ok, "recon_ok": recon_ok,
        "duplicated": duplicated, "missing": missing, "wrong_amount": wrong_amount,
        "claim_issue": claim_issue, "recon_issue": recon_issue, "labels": labels,
        "n_tool_calls": len(snapshot["events"]),  # logged only, never scored
    }
