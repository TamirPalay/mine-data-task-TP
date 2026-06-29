"""
compare.py — C6

Joins agent decisions (results.jsonl) to:
  - buyer_actions.csv    (what an experienced human buyer actually did)
  - rule_executions.csv  (what the automated rule engine actually did)

For each disagreement, prints:
  - What the agent decided
  - What the human/rule actually did
  - Who was likely right, with evidence from the next day's performance data

This is the core evaluation of the agent's judgment quality.
"""

import sys
import json
import pathlib
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from context_builder import find_repo_root, load_all_data


# ─────────────────────────────────────────────
# Load agent decisions
# ─────────────────────────────────────────────

def load_results(results_file: pathlib.Path) -> pd.DataFrame:
    """Load results.jsonl into a DataFrame."""
    records = []
    with open(results_file, encoding="utf-8") as f:
        for line in f:
            try:
                records.append(json.loads(line.strip()))
            except json.JSONDecodeError:
                continue
    df = pd.DataFrame(records)
    df["adset_id"] = df["adset_id"].astype(str)
    df["decision_date"] = pd.to_datetime(df["decision_date"])
    print(f"[compare] Loaded {len(df)} agent decisions from results.jsonl")
    return df


# ─────────────────────────────────────────────
# Get next-day ROI for a given adset+date
# ─────────────────────────────────────────────

def get_next_day_roi(adset_id: str, decision_date: pd.Timestamp, perf: pd.DataFrame):
    """
    Return the ROI for this adset on the day AFTER decision_date.
    Returns None if no data available (e.g., last day of dataset).
    """
    next_date = decision_date + pd.Timedelta(days=1)
    next_row = perf[
        (perf["adset_id"] == adset_id) &
        (pd.to_datetime(perf["date"]) == next_date)
    ]
    if next_row.empty:
        return None
    return float(next_row.iloc[0]["roi"])


# ─────────────────────────────────────────────
# Compare agent to buyer actions
# ─────────────────────────────────────────────

def compare_to_buyers(agent_df: pd.DataFrame, buyers: pd.DataFrame, perf: pd.DataFrame):
    """
    Find cases where the agent made a decision on the same adset+date
    as a human buyer action. Print disagreements with verdicts.
    """
    print("\n" + "=" * 60)
    print("  AGENT vs HUMAN BUYERS")
    print("=" * 60)

    # Normalise buyer action_time to date for joining
    buyers = buyers.copy()
    buyers["action_date"] = pd.to_datetime(buyers["action_time"], utc=True).dt.date
    buyers["action_date"] = pd.to_datetime(buyers["action_date"])

    # Classify buyer action type
    def classify_buyer(row):
        """Classify buyer action as scale_up, scale_down, or other."""
        old_b = row.get("old_budget")
        new_b = row.get("new_budget")
        try:
            if float(new_b) > float(old_b) * 1.01:
                return "scale_up"
            elif float(new_b) < float(old_b) * 0.99:
                return "scale_down"
            else:
                return "neutral"
        except (TypeError, ValueError):
            return "unknown"

    buyers["buyer_action_type"] = buyers.apply(classify_buyer, axis=1)

    # Join on adset_id + date
    merged = agent_df.merge(
        buyers[["adset_id", "action_date", "buyer_action_type", "old_budget", "new_budget"]],
        left_on=["adset_id", "decision_date"],
        right_on=["adset_id", "action_date"],
        how="inner",
    )

    if merged.empty:
        print("\n  No agent decisions overlap with buyer actions on the same adset+date.")
        print("  (Most buyer actions were on Jun-12; agent also ran Jun-12.)")
        print("  -> Check if adset IDs and dates align in the data.")
        return

    # Find disagreements
    disagreements = merged[merged["action"] != merged["buyer_action_type"]]
    agreements = merged[merged["action"] == merged["buyer_action_type"]]

    print(f"\n  Overlapping decisions:  {len(merged)}")
    print(f"  Agreements:             {len(agreements)}")
    print(f"  Disagreements:          {len(disagreements)}")

    if not disagreements.empty:
        print(f"\n  --- Disagreements ---")
        for _, row in disagreements.iterrows():
            adset_id = row["adset_id"]
            date = row["decision_date"]
            agent_action = row["action"]
            buyer_action = row["buyer_action_type"]
            conf = row["confidence"]
            reasoning = row.get("reasoning", "")[:100]
            next_roi = get_next_day_roi(adset_id, date, perf)

            print(f"\n  Adset {adset_id} | {date.date()}")
            print(f"    Agent:  {agent_action} (conf={conf:.2f})")
            print(f"    Buyer:  {buyer_action} (${row['old_budget']} -> ${row['new_budget']})")
            print(f"    Reasoning: {reasoning}")

            if next_roi is not None:
                # Determine who was right based on next-day ROI
                print(f"    Next-day ROI: {next_roi:+.2f}")
                verdict = _verdict_buyer(agent_action, buyer_action, next_roi)
                print(f"    Verdict: {verdict}")
            else:
                print(f"    Next-day ROI: N/A (last day of dataset)")


def _verdict_buyer(agent_action: str, buyer_action: str, next_roi: float) -> str:
    """
    Heuristic verdict on who was right.
    A positive next-day ROI favours whoever was more optimistic.
    A negative next-day ROI favours whoever was more conservative.
    """
    # Map actions to a sentiment: positive = bullish, negative = bearish
    sentiment = {
        "scale_up": 1, "keep": 0, "scale_down": -1,
        "pause": -2, "escalate": 0,
    }
    agent_sent = sentiment.get(agent_action, 0)
    buyer_sent = sentiment.get(buyer_action, 0)

    if next_roi >= 0.05:
        # Positive outcome: the more bullish party was right
        if agent_sent > buyer_sent:
            return f"AGENT likely right (ROI={next_roi:+.2f}, agent was more optimistic)"
        elif buyer_sent > agent_sent:
            return f"BUYER likely right (ROI={next_roi:+.2f}, buyer was more optimistic)"
        else:
            return f"INCONCLUSIVE (ROI={next_roi:+.2f}, similar sentiment)"
    elif next_roi <= -0.05:
        # Negative outcome: the more conservative party was right
        if agent_sent < buyer_sent:
            return f"AGENT likely right (ROI={next_roi:+.2f}, agent was more conservative)"
        elif buyer_sent < agent_sent:
            return f"BUYER likely right (ROI={next_roi:+.2f}, buyer was more conservative)"
        else:
            return f"INCONCLUSIVE (ROI={next_roi:+.2f}, similar caution)"
    else:
        return f"INCONCLUSIVE (ROI={next_roi:+.2f}, near break-even)"


# ─────────────────────────────────────────────
# Compare agent to rule executions
# ─────────────────────────────────────────────

def compare_to_rules(agent_df: pd.DataFrame, execs: pd.DataFrame, perf: pd.DataFrame):
    """
    Find cases where the agent made a decision on the same adset+date
    as a rule execution. Print disagreements with verdicts.
    """
    print("\n" + "=" * 60)
    print("  AGENT vs RULE ENGINE")
    print("=" * 60)

    execs = execs.copy()
    execs["action_date_dt"] = pd.to_datetime(execs["action_date"])

    # Classify rule action
    def classify_rule(action_name: str) -> str:
        a = str(action_name).lower()
        if "turn off" in a or "turn_off" in a:
            return "pause"
        elif "decrease" in a:
            return "scale_down"
        elif "increase" in a:
            return "scale_up"
        else:
            return "other"

    execs["rule_action_type"] = execs["action_name"].apply(classify_rule)

    # One row per adset+date (deduplicate — multiple firings in a day)
    execs_dedup = (
        execs.sort_values("action_time", ascending=False)
        .drop_duplicates(subset=["adset_id", "action_date_dt"])
    )

    # Join to agent decisions
    merged = agent_df.merge(
        execs_dedup[["adset_id", "action_date_dt", "rule_action_type", "rule_name",
                     "today_roi_at_action", "last_3_days_roi_at_action"]],
        left_on=["adset_id", "decision_date"],
        right_on=["adset_id", "action_date_dt"],
        how="inner",
    )

    if merged.empty:
        print("\n  No agent decisions overlap with rule executions on the same adset+date.")
        return

    disagreements = merged[merged["action"] != merged["rule_action_type"]]
    agreements = merged[merged["action"] == merged["rule_action_type"]]

    print(f"\n  Overlapping decisions:  {len(merged)}")
    print(f"  Agreements:             {len(agreements)}")
    print(f"  Disagreements:          {len(disagreements)}")

    # Show all overlaps (rule data is limited to ACC-04)
    print(f"\n  --- All overlapping cases ---")
    for _, row in merged.iterrows():
        adset_id = row["adset_id"]
        date = row["decision_date"]
        agent_action = row["action"]
        rule_action = row["rule_action_type"]
        conf = row["confidence"]
        rule_name = row.get("rule_name", "?")
        roi_at_fire = row.get("today_roi_at_action")
        l3_roi = row.get("last_3_days_roi_at_action")
        reasoning = row.get("reasoning", "")[:100]
        next_roi = get_next_day_roi(adset_id, date, perf)

        agree_str = "AGREE" if agent_action == rule_action else "DISAGREE"
        roi_at_str = f"{roi_at_fire:+.2f}" if pd.notna(roi_at_fire) else "?"
        l3_str = f"{l3_roi:+.2f}" if pd.notna(l3_roi) else "?"

        print(f"\n  [{agree_str}] Adset {adset_id} | {date.date()}")
        print(f"    Agent:    {agent_action} (conf={conf:.2f})")
        print(f"    Rule:     {rule_action} (rule={rule_name})")
        print(f"    ROI at rule fire: today={roi_at_str}  last3={l3_str}")
        print(f"    Agent reasoning: {reasoning}")

        if next_roi is not None:
            print(f"    Next-day ROI: {next_roi:+.2f}")
            verdict = _verdict_rule(agent_action, rule_action, next_roi, roi_at_fire)
            print(f"    Verdict: {verdict}")
        else:
            print(f"    Next-day ROI: N/A (Jun-12 is the last date)")


def _verdict_rule(agent_action: str, rule_action: str, next_roi: float, roi_at_fire) -> str:
    """
    Verdict for agent vs rule. Rules fired on intra-day ROI snapshots;
    agent sees full-day data. This is a known rule weakness from Task A.
    """
    sentiment = {"scale_up": 1, "keep": 0, "scale_down": -1, "pause": -2, "escalate": 0}
    agent_sent = sentiment.get(agent_action, 0)
    rule_sent = sentiment.get(rule_action, 0)

    if agent_action == rule_action:
        return f"Both agreed: {agent_action}. Next-day ROI={next_roi:+.2f}."

    if next_roi >= 0.05:
        if agent_sent > rule_sent:
            return (f"AGENT likely right (next ROI={next_roi:+.2f}). "
                    f"Rule fired on intra-day ROI snapshot ({roi_at_fire:+.2f} at fire time), "
                    f"agent had full-day picture.")
        else:
            return (f"RULE likely right (next ROI={next_roi:+.2f}). "
                    f"Agent was overly cautious.")
    elif next_roi <= -0.05:
        if agent_sent < rule_sent:
            return (f"AGENT likely right (next ROI={next_roi:+.2f}). "
                    f"Agent correctly identified a loser the rule missed.")
        else:
            return (f"RULE likely right (next ROI={next_roi:+.2f}). "
                    f"Rule correctly acted; agent was too optimistic.")
    else:
        return f"INCONCLUSIVE (next ROI={next_roi:+.2f}, near break-even)."


# ─────────────────────────────────────────────
# Summary statistics
# ─────────────────────────────────────────────

def print_summary(agent_df: pd.DataFrame, perf: pd.DataFrame):
    """
    Print overall agent decision distribution and simulated P&L impact.
    Simulated P&L: compare what would have happened if we followed agent decisions
    vs. the actual outcome (based on next-day ROI).
    """
    print("\n" + "=" * 60)
    print("  AGENT DECISION SUMMARY")
    print("=" * 60)

    # Action distribution
    action_counts = agent_df["action"].value_counts()
    print(f"\n  Total decisions: {len(agent_df)}")
    print(f"\n  Action distribution:")
    for action, count in action_counts.items():
        pct = count / len(agent_df) * 100
        print(f"    {action:<12}: {count:4d}  ({pct:.1f}%)")

    # Routing breakdown
    via_counts = agent_df["via"].value_counts()
    print(f"\n  Routing breakdown (how each decision was made):")
    for via, count in via_counts.items():
        pct = count / len(agent_df) * 100
        print(f"    {via:<22}: {count:4d}  ({pct:.1f}%)")

    # Simulated P&L impact for paused adsets
    # If agent said "pause" and we followed it, we'd have zero spend/revenue the next day.
    # Compare to actual next-day outcome.
    paused = agent_df[agent_df["action"] == "pause"].copy()
    print(f"\n  Simulated P&L for 'pause' decisions ({len(paused)} total):")

    counterfactual_profit = 0.0
    actual_profit_if_kept = 0.0
    no_next_day = 0

    for _, row in paused.iterrows():
        adset_id = row["adset_id"]
        date = row["decision_date"]
        next_roi = get_next_day_roi(adset_id, date, perf)

        if next_roi is None:
            no_next_day += 1
            continue

        # Look up next-day spend to estimate profit
        next_date = date + pd.Timedelta(days=1)
        next_row = perf[
            (perf["adset_id"] == adset_id) &
            (pd.to_datetime(perf["date"]) == next_date)
        ]
        if not next_row.empty:
            spend = float(next_row.iloc[0].get("spend", 0))
            profit = float(next_row.iloc[0].get("profit", 0))
            actual_profit_if_kept += profit
            # If we had paused, we'd have $0 profit (and $0 loss)
            counterfactual_profit += 0

    saved_by_pausing = -actual_profit_if_kept  # negative actual = saved loss
    print(f"    Adsets with next-day data:  {len(paused) - no_next_day}")
    print(f"    Adsets missing next-day:    {no_next_day} (Jun-12 is last date)")
    if len(paused) - no_next_day > 0:
        print(f"    Actual next-day profit if we had NOT paused:  ${actual_profit_if_kept:+.2f}")
        if actual_profit_if_kept < 0:
            print(f"    => Pausing would have SAVED ${-actual_profit_if_kept:.2f} in losses")
        else:
            print(f"    => Pausing would have COST ${actual_profit_if_kept:.2f} in foregone profit")


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

def main():
    results_file = pathlib.Path(__file__).resolve().parent / "results.jsonl"

    if not results_file.exists():
        print("ERROR: results.jsonl not found. Run run_agent.py first.")
        sys.exit(1)

    # Load agent decisions
    agent_df = load_results(results_file)

    # Load reference data
    data = load_all_data()
    perf = data["perf"]
    perf["adset_id"] = perf["adset_id"].astype(str)
    perf["date"] = pd.to_datetime(perf["date"])

    buyers = data["buyers"]
    execs = data["execs"]

    # Run comparisons
    compare_to_buyers(agent_df, buyers, perf)
    compare_to_rules(agent_df, execs, perf)
    print_summary(agent_df, perf)

    print("\n[compare] Done.")


if __name__ == "__main__":
    main()
