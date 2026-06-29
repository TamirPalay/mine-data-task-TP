"""
context_builder.py — C1 + C2

Builds a compressed context block (<500 tokens) for a given adset + date,
and computes uncertainty flags + confidence ceiling before any LLM call.

Two public functions:
    load_all_data()                        → dict of DataFrames (call once, pass around)
    build_context(adset_id, decision_date, data) → (context_text, flags, confidence_ceiling)
"""

import os
import pathlib
import pandas as pd


# ─────────────────────────────────────────────
# Utility: find repo root (walk up to .git dir)
# ─────────────────────────────────────────────

def find_repo_root() -> pathlib.Path:
    """Walk up from this file's directory until we find a .git folder."""
    current = pathlib.Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        if (parent / ".git").exists():
            return parent
    raise FileNotFoundError("Could not find repo root (.git folder).")


# ─────────────────────────────────────────────
# C1: Load all data once
# ─────────────────────────────────────────────

def load_all_data() -> dict:
    """
    Load all 5 CSVs from Data/ folder.
    Returns a dict with keys: perf, meta, rules, execs, buyers.

    Adset IDs are always read as strings to prevent 18-digit float corruption.
    Buyer actions ID fix is applied here (critical — was broken in Task A).
    """
    root = find_repo_root()
    data_dir = root / "Data"

    print(f"[load_all_data] Loading CSVs from: {data_dir}")

    # Performance data — one row per adset per day
    perf = pd.read_csv(
        data_dir / "daily_adset_performance.csv",
        dtype={"adset_id": str},
        parse_dates=["date", "first_spend_date"],
    )
    print(f"  [OK] daily_adset_performance: {perf.shape[0]} rows, {perf['adset_id'].nunique()} adsets")

    # Metadata — one row per adset (may have multiple snapshots; we'll take latest)
    meta = pd.read_csv(
        data_dir / "campaign_adset_metadata.csv",
        dtype={"adset_id": str, "campaign_id": str},
    )
    print(f"  [OK] campaign_adset_metadata:  {meta.shape[0]} rows")

    # Auto rules definitions
    rules = pd.read_csv(data_dir / "auto_rules.csv")
    print(f"  [OK] auto_rules:               {rules.shape[0]} rules")

    # Rule executions log — all 214 from ACC-04
    execs = pd.read_csv(
        data_dir / "rule_executions.csv",
        dtype={"adset_id": str, "campaign_id": str, "account_id": str},
        parse_dates=["action_date"],
    )
    # Parse action_time to datetime (ISO format with Z suffix)
    execs["action_time"] = pd.to_datetime(execs["action_time"], utc=True, errors="coerce")
    print(f"  [OK] rule_executions:          {execs.shape[0]} rows")

    # Buyer actions — adset_id MUST be read as string (was corrupted in Task A)
    buyers = pd.read_csv(
        data_dir / "buyer_actions.csv",
        dtype={"adset_id": str},
    )
    buyers["action_time"] = pd.to_datetime(buyers["action_time"], utc=True, errors="coerce")
    # Keep only adset-level actions (some rows are campaign-level with null adset_id)
    buyers = buyers[buyers["adset_id"].notna()].copy()
    print(f"  [OK] buyer_actions:            {buyers.shape[0]} adset-level rows")

    print("[load_all_data] All data loaded.\n")
    return {"perf": perf, "meta": meta, "rules": rules, "execs": execs, "buyers": buyers}


# ─────────────────────────────────────────────
# C2: Uncertainty detector helpers
# ─────────────────────────────────────────────

def _compute_flags_and_ceiling(
    adset_perf: pd.DataFrame,
    buyer_rows: pd.DataFrame,
    exec_rows: pd.DataFrame,
    decision_date: pd.Timestamp,
) -> tuple[list[str], float]:
    """
    Pure-code uncertainty checks. Returns (flags, confidence_ceiling).
    These run BEFORE any LLM call and can block or constrain decisions.

    Rules (from Task B design):
      insufficient_history   → < 3 days of spend  → ceiling 0.4
      revenue_delay_suspected → spend_day_no ≤ 2 AND fb/estimated < 0.85 → ceiling 0.5
      recent_human_action    → buyer action < 24h ago → ceiling 0.3
      rule_conflict          → rule fired today on this adset
    """
    flags = []
    ceiling = 1.0  # will be lowered by each flag

    # ── 1. Insufficient history ─────────────────────────────────────────────
    # Count days where spend > 0
    spend_days = (adset_perf["spend"] > 0).sum()
    if spend_days < 3:
        flags.append("insufficient_history")
        ceiling = min(ceiling, 0.4)
        print(f"    [flag] insufficient_history (spend days = {spend_days})")

    # ── 2. Revenue delay suspected ──────────────────────────────────────────
    # On the decision date row, check spend_day_no and conversion completeness
    today_row = adset_perf[adset_perf["date"] == decision_date]
    if not today_row.empty:
        row = today_row.iloc[0]
        spend_day_no = row.get("spend_day_no", 99)
        fb_conv = row.get("fb_conversions", 0)
        est_conv = row.get("estimated_conversions", 0)
        # Check if revenue is likely incomplete
        if spend_day_no <= 2 and est_conv > 0 and (fb_conv / est_conv) < 0.85:
            flags.append("revenue_delay_suspected")
            ceiling = min(ceiling, 0.5)
            ratio = fb_conv / est_conv
            print(f"    [flag] revenue_delay_suspected (day {spend_day_no}, fb/est={ratio:.2f})")

    # ── 3. Recent human action ──────────────────────────────────────────────
    if not buyer_rows.empty:
        # buyer action_time is tz-aware (UTC); decision_date is tz-naive — localise to compare
        cutoff = (decision_date - pd.Timedelta(hours=24)).tz_localize("UTC")
        recent = buyer_rows[buyer_rows["action_time"] >= cutoff]
        if not recent.empty:
            flags.append("recent_human_action")
            ceiling = min(ceiling, 0.3)
            print(f"    [flag] recent_human_action ({len(recent)} action(s) in last 24h)")

    # ── 4. Rule fired today ─────────────────────────────────────────────────
    if not exec_rows.empty:
        today_execs = exec_rows[exec_rows["action_date"] == decision_date.date()]
        if not today_execs.empty:
            flags.append("rule_conflict")
            rule_names = today_execs["rule_name"].unique().tolist()
            print(f"    [flag] rule_conflict (rules fired today: {rule_names})")

    return flags, ceiling


# ─────────────────────────────────────────────
# C1: Context block formatter
# ─────────────────────────────────────────────

def _format_context_block(
    adset_id: str,
    decision_date: pd.Timestamp,
    adset_perf: pd.DataFrame,
    meta_row: pd.Series | None,
    exec_rows: pd.DataFrame,
    buyer_rows: pd.DataFrame,
    flags: list[str],
) -> str:
    """
    Compress all relevant data into a structured text block under ~500 tokens.
    This is what gets sent to the LLM — never raw CSV rows.
    """
    lines = []

    # ── Header ──────────────────────────────────────────────────────────────
    account = adset_perf["account_name"].iloc[0] if not adset_perf.empty else "Unknown"
    lines.append(f"ADSET: {adset_id} | Account: {account}")

    # ── Metadata ────────────────────────────────────────────────────────────
    if meta_row is not None:
        budget = meta_row.get("daily_budget", "?")
        bid_strat = meta_row.get("bid_strategy", "?")
        status = meta_row.get("effective_status", "?")
        # Geo can be 100+ countries — truncate to keep tokens down
        geo_raw = str(meta_row.get("geo_countries", "?"))
        # Count comma-separated entries; show first 3 + count if many
        import json as _json
        try:
            geo_list = _json.loads(geo_raw)
            if len(geo_list) > 3:
                geo = f"{', '.join(geo_list[:3])} +{len(geo_list)-3} more"
            else:
                geo = ", ".join(geo_list)
        except Exception:
            geo = geo_raw[:40]  # fallback: truncate raw string
        lines.append(f"Budget: ${budget}/day | Bid: {bid_strat} | Geo: {geo} | Status: {status}")
    else:
        lines.append("Budget: ? | Bid: ? | Geo: ? | Status: ?")

    # ── Spend day info from latest perf row ─────────────────────────────────
    today_rows = adset_perf[adset_perf["date"] == decision_date]
    if not today_rows.empty:
        today = today_rows.iloc[0]
        spend_day_no = today.get("spend_day_no", "?")
        lines.append(f"Spend day: {spend_day_no}")
    else:
        lines.append("Spend day: no data for this date")

    lines.append("")

    # ── Performance (last 7 days, most recent first) ─────────────────────────
    lines.append("PERFORMANCE (last 7 days, newest first):")
    # Sort descending so the LLM sees the most recent days first
    perf_sorted = adset_perf.sort_values("date", ascending=False).head(7)
    if perf_sorted.empty:
        lines.append("  [no performance data]")
    else:
        for _, r in perf_sorted.iterrows():
            date_str = pd.Timestamp(r["date"]).strftime("%b-%d")
            spend = r.get("spend", 0)
            roi = r.get("roi", float("nan"))
            conv = r.get("fb_conversions", 0)
            roi_str = f"{roi:+.2f}" if pd.notna(roi) else "N/A"
            lines.append(f"  {date_str}: spend=${spend:.2f}  roi={roi_str}  conversions={conv:.0f}")

    lines.append("")

    # ── Recent rule executions (last 7 days) ────────────────────────────────
    lines.append("RECENT RULE ACTIONS:")
    if exec_rows.empty:
        lines.append("  none")
    else:
        recent_execs = exec_rows.sort_values("action_time", ascending=False).head(5)
        for _, r in recent_execs.iterrows():
            t = r["action_time"]
            t_str = t.strftime("%b-%d %H:%M UTC") if pd.notna(t) else "?"
            rule = r.get("rule_name", "?")
            action = r.get("action_name", "?")
            roi_at = r.get("today_roi_at_action", float("nan"))
            roi_str = f"{roi_at:+.2f}" if pd.notna(roi_at) else "?"
            lines.append(f"  {t_str} -- {rule} -> {action} (roi_at_fire={roi_str})")

    lines.append("")

    # ── Recent buyer actions (last 7 days) ──────────────────────────────────
    lines.append("RECENT BUYER ACTIONS:")
    if buyer_rows.empty:
        lines.append("  none in last 7 days")
    else:
        recent_buyers = buyer_rows.sort_values("action_time", ascending=False).head(5)
        for _, r in recent_buyers.iterrows():
            t = r["action_time"]
            t_str = t.strftime("%b-%d %H:%M UTC") if pd.notna(t) else "?"
            event = r.get("event_type", "?")
            old_b = r.get("old_budget", "?")
            new_b = r.get("new_budget", "?")
            lines.append(f"  {t_str} -- {event} (${old_b} -> ${new_b})")

    lines.append("")

    # ── Data quality flags ──────────────────────────────────────────────────
    if flags:
        lines.append(f"DATA FLAGS: {' / '.join(flags)}")
    else:
        lines.append("DATA FLAGS: none")

    return "\n".join(lines)


# ─────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────

def build_context(
    adset_id: str,
    decision_date: str | pd.Timestamp,
    data: dict,
) -> tuple[str, list[str], float]:
    """
    Build compressed context for one adset on one date.

    Args:
        adset_id:      Adset ID as string.
        decision_date: Date string 'YYYY-MM-DD' or Timestamp.
        data:          Dict returned by load_all_data().

    Returns:
        (context_text, flags, confidence_ceiling)
        context_text     — structured text block to pass to LLM
        flags            — list of data quality flag strings
        confidence_ceiling — float 0.0–1.0, max confidence LLM can return
    """
    decision_date = pd.Timestamp(decision_date)
    perf = data["perf"]
    meta = data["meta"]
    execs = data["execs"]
    buyers = data["buyers"]

    # ── Filter performance to this adset, last 7 days ───────────────────────
    cutoff_7d = decision_date - pd.Timedelta(days=6)  # 7 days inclusive
    adset_perf = perf[
        (perf["adset_id"] == adset_id) &
        (pd.to_datetime(perf["date"]) >= cutoff_7d) &
        (pd.to_datetime(perf["date"]) <= decision_date)
    ].copy()
    adset_perf["date"] = pd.to_datetime(adset_perf["date"])

    # ── Get latest metadata row for this adset ──────────────────────────────
    adset_meta = meta[meta["adset_id"] == adset_id]
    meta_row = adset_meta.iloc[0] if not adset_meta.empty else None

    # ── Filter rule executions to this adset, last 7 days ──────────────────
    # action_time is tz-aware (UTC), so cutoff must be too
    exec_cutoff = (decision_date - pd.Timedelta(days=6)).tz_localize("UTC")
    adset_execs = execs[
        (execs["adset_id"] == adset_id) &
        (execs["action_time"] >= exec_cutoff)
    ].copy()

    # ── Filter buyer actions to this adset, last 7 days ─────────────────────
    # Same tz-awareness requirement
    buyer_cutoff = (decision_date - pd.Timedelta(days=6)).tz_localize("UTC")
    adset_buyers = buyers[
        (buyers["adset_id"] == adset_id) &
        (buyers["action_time"] >= buyer_cutoff)
    ].copy()

    # ── C2: Compute uncertainty flags ───────────────────────────────────────
    flags, ceiling = _compute_flags_and_ceiling(
        adset_perf, adset_buyers, adset_execs, decision_date
    )

    # ── C1: Build compressed text block ────────────────────────────────────
    context_text = _format_context_block(
        adset_id, decision_date, adset_perf, meta_row,
        adset_execs, adset_buyers, flags
    )

    return context_text, flags, ceiling


# ─────────────────────────────────────────────
# Quick smoke test
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("=== context_builder.py smoke test ===\n")
    data = load_all_data()

    # Pick one adset from ACC-04 that had rule executions (most interesting)
    execs = data["execs"]
    sample_id = execs["adset_id"].iloc[0]
    test_date = "2026-06-12"

    print(f"Building context for adset {sample_id} on {test_date}...\n")
    ctx, flags, ceiling = build_context(sample_id, test_date, data)

    print("--- Context block -------------------------------------------")
    print(ctx)
    print("--- Flags:", flags)
    print("--- Confidence ceiling:", ceiling)
    print(f"\nApprox token count (chars/4): {len(ctx) // 4}")
