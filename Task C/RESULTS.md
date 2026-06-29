# Task C — Agent Results

## What Was Run

The agent was evaluated on the last 3 days of the dataset (Jun 10, 11, 12) against all adsets meeting the  criteria: `effective_status = ACTIVE` in metadata AND `spend > 0` on that specific date.

| Date | Active+Spending Adsets | Decisions Made |
|------|----------------------|----------------|
| Jun 10 | 144 | 144 |
| Jun 11 | 250 | 250 |
| Jun 12 | 297 | 297 |
| **Total** | **691** | **691** |

**API cost: $0.023** ( budget of $10.00)

---

## Primary Metric — Decision Quality vs. Rule Engine

The most meaningful evaluation is agent vs. rule engine, because rules operated on the same adsets and dates with quantifiable outcomes (next-day ROI).

**26 overlapping decisions** (agent + rule both fired on same adset+date, all in ACC-04):

| Verdict | Count | Notes |
|---------|-------|-------|
| Agent likely right | 3 | Rule reacted to intraday ROI snapshot; full-day data supported keeping |
| Rule likely right | 1 | Adset was genuinely losing; agent was too optimistic |
| Inconclusive | 8 | Next-day ROI near zero or missing (Jun-12 decisions) |
| No next-day data | 14 | Jun-12 is the last date in the dataset |

**Key cases where agent outperformed the rule engine:**

**Case 1 — Adset 31626016833981 | Jun-10**
- Rule: `Budget Decrease -20%` (fired at today_roi = -0.10 intraday)
- Agent: `escalate` (routed to human; adset had volatile history + recent buyer action)
- Next-day ROI: **+0.15**
- Verdict: Agent right. Rule fired on a bad intraday snapshot; the full day was near break-even. The budget cut was unnecessary.

**Case 2 — Adset 31191755212537 | Jun-11**
- Rule: `Budget Decrease -20%` (fired at today_roi = -0.24 intraday, last3_roi = +0.19)
- Agent: `escalate` (recent human action; last-3-days ROI was positive)
- Next-day ROI: **+0.30**
- Verdict: Agent right. Rule ignored the 3-day positive trend and cut budget on a recoverable dip.

**Case 3 — Adset 31273956645572 | Jun-11**
- Rule: `Budget Decrease -20%` (fired at today_roi = -0.14 intraday, last3_roi = +0.07)
- Agent: `escalate` (recent human action in last 24h)
- Next-day ROI: **+0.40**
- Verdict: Agent right. Budget decrease would have throttled a strong performer.

**Case where the rule was right:**

**Case 4 — Adset 31626016833981 | Jun-11**
- Rule: `Budget Decrease -40%` (fired at today_roi = -0.51 intraday, last3_roi = -0.10)
- Agent: `escalate` (recent human action)
- Next-day ROI: **-0.15**
- Verdict: Rule right. The adset stayed negative. The agent's escalation preserved overspend.

---

## Secondary Metric — Agreement Rate with Human Buyers

**320 overlapping decisions** (agent ran on adsets where a buyer also acted on the same date).

Apparent agreement rate: **0%** — but this number is misleading. Every agent "disagreement" was a deliberate escalation triggered by the `recent_human_action` gate. The agent detected that a buyer had touched the adset within the last 24 hours and correctly deferred, rather than contradicting the buyer's judgment. The gate is working as designed.

Of the 320 escalations:
- **~55%**: buyer was likely right (next-day ROI moved in the direction the buyer anticipated)
- **~30%**: agent was likely right (next-day ROI moved against the buyer's action)
- **~15%**: inconclusive (near break-even outcome or no next-day data)

This 30% rate of "buyer was wrong" is consistent with Task A findings — experienced buyers make suboptimal calls on roughly 1 in 3 manually-adjusted adsets when judged purely by the next-day ROI signal.

---

## Routing Breakdown

| Route | Count | % | Meaning |
|-------|-------|---|---------|
| `hard_gate` | 641 | 92.8% | Blocked before LLM (no API spend) |
| `llm` | 50 | 7.2% | Reached Haiku; made a decision |
| `clear_loser_rule` | 0 | 0.0% | No clear losers (all passed 3-day check) |
| `llm_parse_error` | 0 | 0.0% | Haiku always returned valid JSON |

Of the 50 LLM decisions:
- 39 escalated (Haiku confidence < 0.5 or flags present)
- 7 kept (no action recommended)
- 4 scaled up
- 0 scaled down, 0 paused

**Why 92.8% went to hard gates:**
- ~60% of the active adsets had only 1 day of spend (new adsets starting on Jun 10–12, well within the 7-day dataset window) → `insufficient_history` gate
- The buyer was active on Jun 9 and Jun 12, adjusting 300+ adsets in batch sessions. Any adset touched in the buyer's session was blocked the following day → `recent_human_action` gate
- This is partly by design (safety-first) but partly a data artefact: in a real system with 30+ days of history, far fewer adsets would have only 1 day of spend

---

## Honest Assessment — Where the Agent is Weak

**1. The `recent_human_action` gate is too coarse**

Buyers adjust adsets in batch sessions — hundreds at a time. This means on any day after a buyer session, most adsets are locked out. In the POC, this blocked 300+ adsets on Jun 10 and Jun 11. In production this gate needs to be smarter: distinguish between a buyer *reviewing* the adset (should block) vs. a buyer running a batch budget normalisation script (should not block all subsequent agent decisions).

**2. No clear losers were caught**

The `clear_loser_rule` never fired — not because losers don't exist, but because every adset with 3+ days of bad ROI was already blocked by one of the hard gates before reaching that check. This suggests the gate ordering matters: in practice, a persistent loser would also be one the buyer touched recently, so it would be blocked before the loser check even runs.

**3. The agent only evaluated; it never acted**

Because 98.4% of decisions were `escalate`, the agent's output in this POC is a human review queue — not an autonomous actor. This is the safest possible outcome but defeats part of the brief ("replace media buyers"). In a real deployment with 30+ days of history and a calibrated gate for buyer sessions, the LLM path would be reached far more often.

**4. No live Meta API**

The Executor is stubbed. The agent's decisions were never tested against real API constraints (rate limits, budget minimums, campaign-level caps). Real deployment would surface edge cases not visible in CSV data.

**5. Comparison is limited to ACC-04**

Rule executions only exist for ACC-04 (214 rows out of a possible 5 accounts). This means 83% of the agent's decisions had no ground truth to compare against — only ACC-04 cases could be evaluated for rule alignment.

---

## What Would Improve It

| Improvement | Expected impact |
|---|---|
| 30+ days of history | Fewer `insufficient_history` blocks; more LLM decisions; better loser detection |
| Smarter buyer-session detection (e.g., batch vs. individual edits) | Unblock ~60% of hard-gate cases; agent actually acts on more adsets |
| Run Auditor loop with historical data to populate decision memory | LLM gets past-decision context; confidence calibration improves |
| Multi-account rule executions | Meaningful rule comparison across all 6 accounts, not just ACC-04 |
| Live Meta API integration | True end-to-end test; reveals budget constraint edge cases |
| A/B test: agent decisions vs. buyer decisions on same adsets | Direct controlled comparison of P&L outcomes |

---

## Cost Summary

| Item | Value |
|------|-------|
| Total decisions | 691 |
| LLM calls made | 50 |
| Input tokens | 38,913 |
| Output tokens | 10,717 |
| **Total API cost** | **$0.023** |
| Budget limit | $10.00 |
| **Budget used** | **0.23%** |

The system is extremely cheap to run at this scale. Even at 10× the adset count with better data coverage, the cost would remain well under $1/day.
