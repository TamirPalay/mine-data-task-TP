"""
agent.py — C3

The LLM judgment layer. Given an adset_id + decision_date + loaded data, runs:
  1. Build compressed context (via context_builder)
  2. Apply hard gates (block before LLM if forbidden conditions apply)
  3. Check for clear losers (deterministic pause — no LLM needed)
  4. Call claude-haiku-4-5 with structured prompt
  5. Parse and validate JSON response
  6. Apply confidence ceiling from uncertainty detector
  7. Return structured decision dict

Entry point: make_decision(adset_id, decision_date, data, memory_text="")
"""

import os
import json
import re
import pandas as pd
import anthropic

from context_builder import build_context


# ─────────────────────────────────────────────
# Anthropic client (reads key from env)
# ─────────────────────────────────────────────

def _get_client() -> anthropic.Anthropic:
    """Create Anthropic client from ANTHROPIC_API_KEY env var. Fail fast if missing."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "ANTHROPIC_API_KEY environment variable not set. "
            "Export it before running: set ANTHROPIC_API_KEY=sk-ant-..."
        )
    return anthropic.Anthropic(api_key=api_key)


# ─────────────────────────────────────────────
# System prompt — role, schema, guardrails
# ─────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert media buyer managing Meta (Facebook) ad campaigns for a performance marketing agency.

Your job: review the data for a single adset and recommend ONE of the following actions:
  - scale_up   : increase daily budget (for strong performers)
  - scale_down : decrease daily budget (for under-performers, but adset has potential)
  - pause      : stop the adset (clear loser with no recovery signal)
  - keep       : take no action (performance acceptable, no clear signal)
  - escalate   : you are not confident enough to recommend an action; send to human review

IMPORTANT: ROI is a RATIO (profit / spend), NOT a percentage.
  roi = +0.50  means  +50% return on spend (profit)
  roi =  0.00  means  break-even
  roi = -0.50  means  lost 50% of spend
  roi = -1.00  means  total loss (zero revenue)

Decision rules you MUST follow:
  - If fewer than 3 days of spend data exist -> action must be "escalate"
  - If a human buyer took action in the last 24h -> action must be "escalate"
  - Never recommend a budget increase of more than 50% in one action
  - Budget changes must be expressed as a new daily budget value in USD (the "amount" field)
  - For "keep", "pause", and "escalate", set amount to null
  - The mandate is to MAINTAIN or GROW spend AND profit. Do not pause everything. Only pause clear losers.

Respond ONLY with a single valid JSON object in this exact schema — no markdown, no explanation:
{
  "adset_id": "<string>",
  "decision_date": "<YYYY-MM-DD>",
  "action": "<scale_up|scale_down|pause|keep|escalate>",
  "amount": <new daily budget as float, or null>,
  "confidence": <float between 0.0 and 1.0>,
  "reasoning": "<1-3 sentence explanation>",
  "data_quality_flags": ["<flag1>", ...]
}"""


# ─────────────────────────────────────────────
# Hard gate checks (no LLM, deterministic)
# ─────────────────────────────────────────────

def _apply_hard_gates(adset_id: str, decision_date: str, flags: list[str]) -> dict | None:
    """
    Check conditions that block ANY LLM call.
    Returns a pre-built decision dict if a gate fires, else None (proceed to LLM).

    Gates:
    - insufficient_history: < 3 days of spend data
    - recent_human_action: buyer acted on this adset within 24h
    """
    if "insufficient_history" in flags:
        print(f"    [gate] BLOCKED: insufficient_history -> escalate")
        return _make_result(
            adset_id, decision_date,
            action="escalate", amount=None, confidence=0.0,
            reasoning="Fewer than 3 days of spend data — cannot make a reliable decision.",
            flags=flags, via="hard_gate",
        )

    if "recent_human_action" in flags:
        print(f"    [gate] BLOCKED: recent_human_action -> escalate")
        return _make_result(
            adset_id, decision_date,
            action="escalate", amount=None, confidence=0.0,
            reasoning="A human buyer acted on this adset in the last 24 hours. Deferring to avoid overriding.",
            flags=flags, via="hard_gate",
        )

    return None  # no gate fired


# ─────────────────────────────────────────────
# Clear loser check (no LLM, deterministic)
# ─────────────────────────────────────────────

def _check_clear_loser(adset_id: str, decision_date: str, data: dict, flags: list[str]) -> dict | None:
    """
    Deterministic pause for clear losers — no LLM call needed.
    Criteria (all must be true):
      - ROI < -0.50 for 3+ consecutive recent days
      - Total spend on those days > $30
      - No upward trend in ROI (last day not better than the day before)
    """
    perf = data["perf"]
    decision_dt = pd.Timestamp(decision_date)

    # Get last 5 days of spend data for this adset, up to decision_date
    adset_perf = perf[
        (perf["adset_id"] == adset_id) &
        (pd.to_datetime(perf["date"]) <= decision_dt)
    ].sort_values("date", ascending=False)

    # Only consider rows with actual spend
    with_spend = adset_perf[adset_perf["spend"] > 0].head(5)
    if len(with_spend) < 3:
        return None  # not enough data to declare a clear loser

    # Check last 3 consecutive spending days
    last_3 = with_spend.head(3)
    all_bad_roi = (last_3["roi"] < -0.50).all()
    total_spend = last_3["spend"].sum()

    if not all_bad_roi or total_spend <= 30:
        return None  # not a clear loser

    # Check for upward trend: is the most recent day better than the one before?
    roi_values = last_3["roi"].tolist()  # [most_recent, ..., oldest]
    has_upward_trend = roi_values[0] > roi_values[1]  # today better than yesterday

    if has_upward_trend:
        print(f"    [clear_loser] ROI bad but upward trend detected — sending to LLM")
        return None  # recovery signal: let LLM decide

    print(f"    [clear_loser] ROI {roi_values} < -0.50 for 3 days, spend=${total_spend:.2f} -> pause (no LLM)")
    return _make_result(
        adset_id, decision_date,
        action="pause", amount=None, confidence=0.90,
        reasoning=(
            f"ROI below -0.50 for 3 consecutive days "
            f"(last 3: {roi_values[2]:+.2f}, {roi_values[1]:+.2f}, {roi_values[0]:+.2f}), "
            f"total spend ${total_spend:.2f}. No recovery trend. Deterministic pause — no LLM needed."
        ),
        flags=flags, via="clear_loser_rule",
    )


# ─────────────────────────────────────────────
# LLM call
# ─────────────────────────────────────────────

def _call_llm(
    adset_id: str,
    decision_date: str,
    context_text: str,
    flags: list[str],
    memory_text: str,
    client: anthropic.Anthropic,
) -> tuple[dict | None, int, int]:
    """
    Call claude-haiku-4-5 with the compressed context block.
    Returns (parsed_dict_or_None, input_tokens, output_tokens).
    """
    # Build user prompt from context + flags + memory
    user_parts = [context_text]

    if memory_text:
        user_parts.append(f"\nPAST DECISIONS FOR THIS ADSET:\n{memory_text}")

    if flags:
        user_parts.append(f"\nNOTE: Data quality flags are active: {', '.join(flags)}. "
                          "These should make you more cautious. Consider escalating if uncertain.")

    user_prompt = "\n".join(user_parts)

    print(f"    [llm] Calling claude-haiku-4-5 ...")

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,  # JSON response is short; cap to control cost
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    raw_text = response.content[0].text.strip()

    print(f"    [llm] {input_tokens} in + {output_tokens} out tokens")

    # Parse JSON — handle occasional markdown fences
    try:
        # Strip markdown code fences if present
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_text, flags=re.MULTILINE).strip()
        parsed = json.loads(cleaned)
        return parsed, input_tokens, output_tokens
    except (json.JSONDecodeError, ValueError) as e:
        print(f"    [llm] JSON parse failed: {e}")
        print(f"    [llm] Raw response: {raw_text[:200]}")
        return None, input_tokens, output_tokens


# ─────────────────────────────────────────────
# Result builder helper
# ─────────────────────────────────────────────

def _make_result(
    adset_id: str,
    decision_date: str,
    action: str,
    amount,
    confidence: float,
    reasoning: str,
    flags: list[str],
    via: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> dict:
    """Standardised decision dict. 'via' records how the decision was made."""
    return {
        "adset_id": adset_id,
        "decision_date": str(decision_date),
        "action": action,
        "amount": amount,
        "confidence": confidence,
        "reasoning": reasoning,
        "data_quality_flags": flags,
        "via": via,           # 'hard_gate' | 'clear_loser_rule' | 'llm' | 'llm_parse_error'
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }


# ─────────────────────────────────────────────
# Validate LLM response against guardrails
# ─────────────────────────────────────────────

ALLOWED_ACTIONS = {"scale_up", "scale_down", "pause", "keep", "escalate"}

def _validate_and_clean(parsed: dict, adset_id: str, decision_date: str,
                        flags: list[str], ceiling: float,
                        input_tok: int, output_tok: int) -> dict:
    """
    Post-LLM validation. Enforces:
    - action must be in allowed list
    - amount must be None/null for non-budget actions
    - confidence ceiling applied
    - confidence < 0.3 -> override to escalate
    """
    action = parsed.get("action", "").lower()
    if action not in ALLOWED_ACTIONS:
        print(f"    [validate] Unknown action '{action}' -> escalate")
        action = "escalate"

    amount = parsed.get("amount")
    # Only scale_up / scale_down should have an amount
    if action not in ("scale_up", "scale_down"):
        amount = None

    # Validate amount bounds (only for budget-change actions)
    if amount is not None:
        try:
            amount = float(amount)
            if amount <= 0:
                print(f"    [validate] Non-positive amount {amount} -> escalate")
                action = "escalate"
                amount = None
        except (TypeError, ValueError):
            print(f"    [validate] Non-numeric amount {amount} -> escalate")
            action = "escalate"
            amount = None

    # Apply confidence ceiling from uncertainty detector
    confidence = float(parsed.get("confidence", 0.5))
    if confidence > ceiling:
        print(f"    [validate] Confidence {confidence:.2f} capped to ceiling {ceiling:.2f}")
        confidence = ceiling

    # Low confidence -> escalate
    if confidence < 0.3:
        print(f"    [validate] Confidence {confidence:.2f} < 0.3 -> escalate")
        action = "escalate"
        amount = None

    return _make_result(
        adset_id=adset_id,
        decision_date=decision_date,
        action=action,
        amount=amount,
        confidence=confidence,
        reasoning=parsed.get("reasoning", ""),
        flags=flags,
        via="llm",
        input_tokens=input_tok,
        output_tokens=output_tok,
    )


# ─────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────

def make_decision(
    adset_id: str,
    decision_date: str,
    data: dict,
    memory_text: str = "",
    client: anthropic.Anthropic | None = None,
) -> dict:
    """
    Make a decision for one adset on one date.

    Args:
        adset_id:       Adset ID as string.
        decision_date:  Date string 'YYYY-MM-DD'.
        data:           Dict from load_all_data().
        memory_text:    Optional past-decision context from feedback.build_decision_memory().
        client:         Optional Anthropic client (creates one if not provided).

    Returns:
        Standardised decision dict (see _make_result).
    """
    print(f"\n  [agent] {adset_id} | {decision_date}")

    # ── Step 1: Build context + uncertainty flags ────────────────────────────
    context_text, flags, ceiling = build_context(adset_id, decision_date, data)

    # ── Step 2: Hard gates — block before any LLM call ──────────────────────
    gate_result = _apply_hard_gates(adset_id, decision_date, flags)
    if gate_result:
        return gate_result

    # ── Step 3: Clear loser check — deterministic, no LLM ──────────────────
    loser_result = _check_clear_loser(adset_id, decision_date, data, flags)
    if loser_result:
        return loser_result

    # ── Step 4: LLM call ─────────────────────────────────────────────────────
    if client is None:
        client = _get_client()

    parsed, in_tok, out_tok = _call_llm(
        adset_id, decision_date, context_text, flags, memory_text, client
    )

    # If LLM response couldn't be parsed, escalate
    if parsed is None:
        return _make_result(
            adset_id, decision_date,
            action="escalate", amount=None, confidence=0.0,
            reasoning="LLM response could not be parsed as valid JSON.",
            flags=flags, via="llm_parse_error",
            input_tokens=in_tok, output_tokens=out_tok,
        )

    # ── Step 5: Validate + apply ceiling ────────────────────────────────────
    result = _validate_and_clean(parsed, adset_id, decision_date, flags, ceiling, in_tok, out_tok)

    print(f"    [agent] => {result['action']} (conf={result['confidence']:.2f})")
    return result


# ─────────────────────────────────────────────
# Smoke test — single adset, checks LLM call
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
    from context_builder import load_all_data

    print("=== agent.py smoke test ===\n")

    # Check API key before loading data
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY not set. Cannot run LLM smoke test.")
        sys.exit(1)

    data = load_all_data()

    # Pick an ACC-04 adset from rule_executions (most interesting — has rule history)
    sample_id = data["execs"]["adset_id"].iloc[10]
    test_date = "2026-06-11"

    print(f"Running agent for adset {sample_id} on {test_date}...\n")
    result = make_decision(sample_id, test_date, data)

    print("\n=== Decision ===")
    for k, v in result.items():
        print(f"  {k}: {v}")

    cost = (result["input_tokens"] * 0.00000025) + (result["output_tokens"] * 0.00000125)
    print(f"\n  Estimated cost: ${cost:.6f}")
