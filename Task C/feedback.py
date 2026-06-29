"""
feedback.py — C4 (stub)

Defines the feedback loop interface. This is NOT a full implementation —
it shows the mechanism that a production system would use.

Three functions:
  record_decision(adset_id, date, decision_dict)
      -> Appends to Task C/decisions_log.jsonl

  record_outcome(adset_id, date, actual_roi)
      -> Appends to Task C/outcomes.jsonl

  build_decision_memory(adset_id)
      -> Joins both files, returns last 3 decisions + vindication as a
         formatted text string. This text is passed to the Analyst Agent
         as context on the next decision for this adset.

How this would work in production:
  1. After each decision, run_agent.py calls record_decision()
  2. The Auditor Agent runs daily, computes next-day ROI for each decided adset,
     and calls record_outcome() to fill in the actual result
  3. On the NEXT decision for that adset, agent.py calls build_decision_memory()
     and includes the returned text in the LLM's user prompt
  4. The LLM sees: "Last time I said pause on Jun-10 (conf=0.72). The next day ROI was +0.31.
     That was WRONG — I should not have paused this."
  5. Over time, the system learns which signals are reliable for which types of adsets
     without any model retraining.

Why JSONL (one JSON object per line):
  - Append-only: each call adds one line, never overwrites
  - Easy to tail, grep, or stream
  - Survives partial writes (only the current line is lost if process dies)
"""

import json
import pathlib
import pandas as pd


# ─────────────────────────────────────────────
# File paths (relative to this file's directory)
# ─────────────────────────────────────────────

_HERE = pathlib.Path(__file__).resolve().parent
DECISIONS_LOG = _HERE / "decisions_log.jsonl"
OUTCOMES_LOG = _HERE / "outcomes.jsonl"


# ─────────────────────────────────────────────
# record_decision
# ─────────────────────────────────────────────

def record_decision(adset_id: str, date: str, decision_dict: dict) -> None:
    """
    Write one decision to decisions_log.jsonl.
    Appends one JSON line per call.

    Args:
        adset_id:      Adset ID as string.
        date:          Decision date as 'YYYY-MM-DD'.
        decision_dict: Full decision dict from agent.make_decision().

    Example record written:
        {"adset_id": "31196781349398", "decision_date": "2026-06-10",
         "action": "keep", "confidence": 0.72,
         "reasoning": "3-day trend positive; today dip suspected revenue delay",
         "data_quality_flags": ["revenue_delay_suspected"]}
    """
    record = {
        "adset_id": adset_id,
        "decision_date": str(date),
        "action": decision_dict.get("action"),
        "amount": decision_dict.get("amount"),
        "confidence": decision_dict.get("confidence"),
        "reasoning": decision_dict.get("reasoning"),
        "data_quality_flags": decision_dict.get("data_quality_flags", []),
        "via": decision_dict.get("via"),
        # outcome fields filled in later by record_outcome()
        "outcome_roi_next_day": None,
        "vindicated": None,
    }

    with open(DECISIONS_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")

    # In production this would also trigger an alert if action == "escalate"


# ─────────────────────────────────────────────
# record_outcome
# ─────────────────────────────────────────────

def record_outcome(adset_id: str, date: str, actual_roi: float) -> None:
    """
    Write an outcome record to outcomes.jsonl after the next day's data arrives.
    Called by the Auditor Agent once daily.

    Args:
        adset_id:    Adset ID as string.
        date:        The DECISION date (not the outcome date) as 'YYYY-MM-DD'.
        actual_roi:  The adset's ROI on the day AFTER the decision.

    Vindication logic:
        - If action was "pause" and next-day ROI < 0: vindicated (adset was bad)
        - If action was "pause" and next-day ROI >= 0: wrong (we killed a winner)
        - If action was "keep/scale_up" and next-day ROI >= 0: vindicated
        - If action was "keep/scale_up" and next-day ROI < 0: wrong
        - If action was "escalate": unclear (no automated action to vindicate)

    Note: In this POC we don't have future-day data (dataset ends Jun 12),
    so vindication cannot be computed for the last day's decisions.
    """
    # Look up the original decision to determine vindication
    vindicated = None
    original_action = None

    if DECISIONS_LOG.exists():
        with open(DECISIONS_LOG, encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line.strip())
                    if rec.get("adset_id") == adset_id and rec.get("decision_date") == str(date):
                        original_action = rec.get("action")
                        break
                except json.JSONDecodeError:
                    continue

    if original_action == "pause":
        vindicated = actual_roi < 0  # pausing was right if adset stayed bad
    elif original_action in ("keep", "scale_up"):
        vindicated = actual_roi >= 0  # keeping was right if adset stayed good
    elif original_action == "scale_down":
        vindicated = None  # ambiguous — depends on whether budget cut improved efficiency
    else:
        vindicated = None  # escalate or unknown

    outcome = {
        "adset_id": adset_id,
        "decision_date": str(date),
        "outcome_roi_next_day": actual_roi,
        "original_action": original_action,
        "vindicated": vindicated,
    }

    with open(OUTCOMES_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(outcome) + "\n")

    print(f"  [feedback] Outcome recorded: {adset_id} | {date} | "
          f"next_roi={actual_roi:+.2f} | vindicated={vindicated}")


# ─────────────────────────────────────────────
# build_decision_memory
# ─────────────────────────────────────────────

def build_decision_memory(adset_id: str, n: int = 3) -> str:
    """
    Read decisions_log.jsonl and outcomes.jsonl for this adset.
    Return the last n decisions with their outcomes as a formatted text string.
    This text is included in the Analyst Agent's next LLM prompt.

    Args:
        adset_id: Adset ID as string.
        n:        How many past decisions to include (default 3).

    Returns:
        Formatted text string, or empty string if no history.

    Example output:
        2026-06-10: action=keep (conf=0.72) -> next-day ROI=+0.31 [VINDICATED]
          reasoning: 3-day trend positive; today dip suspected revenue delay
        2026-06-09: action=scale_down (conf=0.65) -> next-day ROI=+0.22 [WRONG]
          reasoning: Moderate ROI, budget slightly high for conversion rate
    """
    if not DECISIONS_LOG.exists():
        return ""  # no history yet

    # Load all decisions for this adset
    decisions = []
    with open(DECISIONS_LOG, encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line.strip())
                if rec.get("adset_id") == adset_id:
                    decisions.append(rec)
            except json.JSONDecodeError:
                continue

    if not decisions:
        return ""

    # Load outcomes to enrich decisions
    outcomes_by_date = {}
    if OUTCOMES_LOG.exists():
        with open(OUTCOMES_LOG, encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line.strip())
                    if rec.get("adset_id") == adset_id:
                        outcomes_by_date[rec["decision_date"]] = rec
                except json.JSONDecodeError:
                    continue

    # Sort by date descending, take last n
    decisions.sort(key=lambda r: r.get("decision_date", ""), reverse=True)
    recent = decisions[:n]

    lines = []
    for dec in recent:
        d = dec.get("decision_date", "?")
        action = dec.get("action", "?")
        conf = dec.get("confidence", 0.0)
        reasoning = dec.get("reasoning", "")[:120]  # truncate to save tokens

        outcome = outcomes_by_date.get(d)
        if outcome:
            next_roi = outcome.get("outcome_roi_next_day")
            vind = outcome.get("vindicated")
            vind_str = "[VINDICATED]" if vind else "[WRONG]" if vind is False else "[UNCLEAR]"
            roi_str = f"{next_roi:+.2f}" if next_roi is not None else "?"
            lines.append(f"{d}: action={action} (conf={conf:.2f}) -> next-day ROI={roi_str} {vind_str}")
        else:
            lines.append(f"{d}: action={action} (conf={conf:.2f}) -> outcome pending")

        if reasoning:
            lines.append(f"  reasoning: {reasoning}")

    return "\n".join(lines)


# ─────────────────────────────────────────────
# Smoke test
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import os
    import tempfile

    print("=== feedback.py smoke test ===\n")

    # Use a temp file so we don't pollute the real log
    tmp = pathlib.Path(tempfile.mkdtemp())
    _orig_decisions = DECISIONS_LOG
    _orig_outcomes = OUTCOMES_LOG

    # Monkey-patch paths to temp dir for test
    import feedback as _self
    _self.DECISIONS_LOG = tmp / "decisions_log.jsonl"
    _self.OUTCOMES_LOG = tmp / "outcomes.jsonl"

    test_id = "31196781349398"
    test_date = "2026-06-10"

    # Record a decision
    fake_decision = {
        "action": "keep",
        "amount": None,
        "confidence": 0.72,
        "reasoning": "3-day trend positive; today dip suspected revenue delay",
        "data_quality_flags": ["revenue_delay_suspected"],
        "via": "llm",
    }
    print("1. Recording decision...")
    record_decision(test_id, test_date, fake_decision)
    print(f"   Written to {_self.DECISIONS_LOG}")

    # Record outcome
    print("\n2. Recording outcome (next-day ROI = +0.31)...")
    record_outcome(test_id, test_date, actual_roi=0.31)

    # Build memory
    print("\n3. Building decision memory...")
    memory = build_decision_memory(test_id)
    print(f"\n   Memory text:\n{memory}")

    print("\n[OK] feedback.py smoke test passed.")
