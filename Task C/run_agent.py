"""
run_agent.py — C5

Runs the agent over the last 3 days of data (Jun 10, 11, 12) for all adsets
that meet Option B criteria: effective_status = ACTIVE in metadata AND
spend > 0 on that specific date in performance data.

For each adset × date:
  - Calls agent.make_decision()
  - Records result via feedback.record_decision()
  - Prints progress with token counts

Writes all decisions to Task C/results.jsonl.
Prints total token usage and estimated cost at the end.
"""

import sys
import json
import time
import pathlib
import pandas as pd

# Make sure Task C/ is on the import path
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from context_builder import load_all_data
from agent import make_decision, _get_client
from feedback import record_decision, DECISIONS_LOG


# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────

RESULTS_FILE = pathlib.Path(__file__).resolve().parent / "results.jsonl"

# Last 3 dates in the dataset
TARGET_DATES = ["2026-06-10", "2026-06-11", "2026-06-12"]

# Haiku pricing (per token)
COST_PER_INPUT_TOKEN = 0.00000025   # $0.25 per million
COST_PER_OUTPUT_TOKEN = 0.00000125  # $1.25 per million

# Safety: stop if we exceed this cost
BUDGET_LIMIT_USD = 8.00


# ─────────────────────────────────────────────
# Get active adsets for a given date (Option B)
# ─────────────────────────────────────────────

def get_active_adsets_for_date(date: str, data: dict) -> list[str]:
    """
    Return adset IDs that are:
      1. effective_status = ACTIVE in metadata
      2. have spend > 0 on this specific date in performance data

    This is Option B (tighter filter) — agreed with user before implementation.
    """
    perf = data["perf"]
    meta = data["meta"]

    # Active adsets in metadata
    active_meta = set(meta[meta["effective_status"] == "ACTIVE"]["adset_id"].unique())

    # Adsets with spend > 0 on this date
    date_perf = perf[(perf["date"] == date) & (perf["spend"] > 0)]
    spending_today = set(date_perf["adset_id"].unique())

    # Intersection: must be both active AND spending today
    active_spending = active_meta & spending_today
    return sorted(active_spending)


# ─────────────────────────────────────────────
# Main run loop
# ─────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  run_agent.py — Adset Decision Agent")
    print(f"  Dates: {TARGET_DATES}")
    print("=" * 60)

    # Load all data once (not per-adset)
    data = load_all_data()

    # Create Anthropic client once (not per-call)
    client = _get_client()

    # Clear results file if it exists (fresh run)
    if RESULTS_FILE.exists():
        RESULTS_FILE.unlink()
        print(f"[run] Cleared existing {RESULTS_FILE.name}")

    # Clear decisions log too (fresh run)
    if DECISIONS_LOG.exists():
        DECISIONS_LOG.unlink()
        print(f"[run] Cleared existing {DECISIONS_LOG.name}")

    # Counters
    total_input_tokens = 0
    total_output_tokens = 0
    total_cost = 0.0
    total_decisions = 0
    skipped_budget = 0

    # Action breakdown counters
    action_counts = {"scale_up": 0, "scale_down": 0, "pause": 0, "keep": 0, "escalate": 0}
    via_counts = {"hard_gate": 0, "clear_loser_rule": 0, "llm": 0, "llm_parse_error": 0}

    print(f"\n[run] Starting agent run...\n")

    for date in TARGET_DATES:
        adsets = get_active_adsets_for_date(date, data)
        print(f"\n[date] {date} — {len(adsets)} active+spending adsets")
        print("-" * 50)

        for adset_id in adsets:
            # Check budget before each LLM call
            if total_cost >= BUDGET_LIMIT_USD:
                print(f"\n[BUDGET] Reached ${BUDGET_LIMIT_USD:.2f} limit — stopping.")
                skipped_budget += 1
                break

            # Make decision (includes context building, gate checks, LLM if needed)
            decision = make_decision(
                adset_id=adset_id,
                decision_date=date,
                data=data,
                client=client,
            )

            # Track token usage and cost
            in_tok = decision.get("input_tokens", 0)
            out_tok = decision.get("output_tokens", 0)
            call_cost = (in_tok * COST_PER_INPUT_TOKEN) + (out_tok * COST_PER_OUTPUT_TOKEN)

            total_input_tokens += in_tok
            total_output_tokens += out_tok
            total_cost += call_cost
            total_decisions += 1

            # Track action and routing breakdown
            action = decision.get("action", "unknown")
            via = decision.get("via", "unknown")
            if action in action_counts:
                action_counts[action] += 1
            if via in via_counts:
                via_counts[via] += 1

            # Write to results.jsonl
            with open(RESULTS_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(decision) + "\n")

            # Record to feedback log
            record_decision(adset_id, date, decision)

            # Print per-decision summary
            conf = decision.get("confidence", 0.0)
            print(
                f"    => {action:<10} conf={conf:.2f} | "
                f"{in_tok}in+{out_tok}out tok | "
                f"${call_cost:.5f} | via={via}"
            )

        else:
            # loop completed without hitting budget limit
            continue
        break  # break out of date loop too if budget hit

    # ── Final summary ──────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  RUN COMPLETE")
    print("=" * 60)
    print(f"\n  Total decisions:     {total_decisions}")
    print(f"  Skipped (budget):    {skipped_budget}")
    print(f"\n  Action breakdown:")
    for action, count in sorted(action_counts.items(), key=lambda x: -x[1]):
        pct = (count / total_decisions * 100) if total_decisions > 0 else 0
        print(f"    {action:<12}: {count:4d}  ({pct:.1f}%)")
    print(f"\n  Routing breakdown:")
    for via, count in sorted(via_counts.items(), key=lambda x: -x[1]):
        pct = (count / total_decisions * 100) if total_decisions > 0 else 0
        print(f"    {via:<20}: {count:4d}  ({pct:.1f}%)")
    print(f"\n  Token usage:")
    print(f"    Input tokens:        {total_input_tokens:,}")
    print(f"    Output tokens:       {total_output_tokens:,}")
    print(f"\n  Estimated API cost:  ${total_cost:.4f}")
    print(f"  Budget remaining:    ${BUDGET_LIMIT_USD - total_cost:.4f}")
    print(f"\n  Results written to:  {RESULTS_FILE}")
    print("=" * 60)


if __name__ == "__main__":
    main()
