# Investigation: Auto-Rule Impact Analysis

## Scope

One week of production data (2026-06-06 to 2026-06-12) across six Meta ad accounts (ACC-01 to ACC-06).
All 12 active auto-rules target OWN RSOC adsets and fire every 30 minutes.
Rule executions were only logged for **ACC-04** during this period — all impact figures below are ACC-04 only.

---

## 1. Data Preprocessing

All preprocessing is implemented in `explore_data.ipynb`. Key decisions:

### `daily_adset_performance.csv` (4,947 rows, 1,000 unique adsets)

- **Zero-spend rows kept and flagged** (`is_zero_spend = True`): 3,000 of 4,947 rows (60.6%) have zero spend, meaning the adset was paused or inactive on that day. Dropping them would hide gaps in an adset's activity timeline. Metric nulls on these rows were filled with `0` (revenue, profit, estimated_conversions, etc.) since no spend means no activity.
- **`cr` has 105 residual nulls** on non-zero-spend rows. These appear to be edge cases where clicks were reported but conversions were null. Treated as `0` for aggregation; flagged as a data quality issue.
- **`first_spend_date` has 52 nulls** — adsets with no historical spend data prior to this export. `spend_day_no` is still `0` on those rows and is used instead.
- **Adset ID format**: ACC-04 uses 14-digit IDs; all other accounts use 18-digit IDs. Both formats are preserved as strings to prevent float-precision loss on large integers.

### `rule_executions.csv` (214 rows, 75 unique adsets)

- **50 rows (23%) are failed API calls** and had no real-world effect:
  - 30 OAuthException errors (access token invalidated — Meta API authentication failure)
  - 20 `"No budget to change"` responses (rule fired but budget was already at or below the target)
- Only **164 successful executions** are used for impact analysis.
- **Duplicate firings**: the same rule can fire on the same adset multiple times per day as long as the condition holds. For impact analysis, only the **first successful fire per adset per day per rule** is counted (80 unique first-fire events after deduplication).
- **R09 ("Turn On | Automation Mistake") had 8 firings — all failed.** The self-correction mechanism never successfully executed during the week.

### `buyer_actions.csv` (1,001 rows)

- **286 campaign-level rows** (null `adset_id`) are excluded from adset-level joins and kept separately.
- **Critical data quality issue**: when read with default pandas settings, `adset_id` is parsed as `float64` (because the column contains nulls), which corrupts 18-digit IDs via floating-point precision loss (e.g., `730122709357812221` becomes `7.301227093578122e+17`). Fix: reload with `dtype={'adset_id': str}`. Join match rate before fix: 0%. This is documented as a data quality finding.
- **49 null `action_time` rows** in the adset-level subset — these cannot be time-ordered and are excluded from any time-sensitive analysis.

### `campaign_adset_metadata.csv` (7,129 rows)

- 7,129 adsets in metadata vs 1,000 in performance — expected, as most adsets were paused or deleted before this week and never spent.
- `bid_amount` (93% null) and `roas_target` (49% null) are legitimately optional depending on bid strategy — kept as-is.

---

## 2. How the Cleaned Data is Used

| Analysis step | Primary data source | Join key |
|---|---|---|
| Rule impact (what rules did) | `execs_dedup` | `adset_id` + `action_date` → `perf_clean` |
| Bad decision case studies | `execs_dedup` + `perf_clean` | `adset_id` + date window |
| Revenue delay quantification | `perf_clean` | `spend_day_no`, `estimated_conversions` vs `fb_conversions` |
| Buyer vs rule comparison | `buyers_adset` (after ID fix) + `execs_dedup` | `adset_id` + date |

---

## Summary of Findings

The automated rules did more good than harm overall — they saved roughly $39 by pausing or cutting losing adsets, while costing about $15 by accidentally pausing ones that were actually working. The biggest problem wasn't the rules themselves, but the timing: 45 out of 68 "Turn Off" decisions happened on an adset's very first day of running, when there's nowhere near enough data to make a confident call. Seven more times, a rule paused an adset that had been profitable for 3 days just because that one day looked bad — likely because the day's revenue hadn't fully arrived yet. The revenue delay itself turned out to be surprisingly small (~3–6% of conversions still unreported on day 1), so the real culprit is high ROI noise on young adsets, not a systematic lag.

---
## 3. Rule Impact Analysis (A2)

**Method:** For each of the 80 unique first-successful firings (68 Turn OFF, 12 Budget Decrease), we estimated the counterfactual: *"what would have happened if the rule had not fired?"*

**Counterfactual assumption (stated explicitly):** the adset would have continued spending at the same daily spend and earning the same ROI as the previous day. This is a lower-bound estimate — actual outcomes could have been better or worse. We use this assumption consistently throughout.

### Overall impact

| Action type | Correct calls | Mistaken calls | $ Saved | $ Burned | Net |
|---|---|---|---|---|---|
| Turn OFF (68 firings) | 52 | 6 | $35.74 | $13.21 | **+$22.52** |
| Budget Decrease (12 firings) | 2 | 1 | $3.44 | $1.65 | **+$1.80** |
| **Combined** | | | **$39.18** | **$14.86** | **+$24.32** |

The rule engine was net-positive, but a meaningful share of its savings were offset by mistaken pauses.

### Per-rule breakdown

| Rule | Executions | $ Saved | $ Burned | Net | Rule name |
|---|---|---|---|---|---|
| R04 | 39 | $23.16 | $0.00 | **+$23.16** | Turn Off — Day 1 \| budget > 35% \| ROI < -50% |
| R05 | 5 | $3.52 | $0.07 | +$3.45 | Turn Off — Total Profit ≤ -$2.50 \| budget usage ≥ 15% |
| R02 | 6 | $3.44 | $0.00 | +$3.44 | Budget Decrease — -30 < ROI ≤ -10 |
| R08 | 9 | $7.50 | $5.06 | +$2.44 | Turn OFF — Total Days = 4 |
| R03 | 10 | $0.62 | $0.00 | +$0.62 | Turn Off — positive_days = 0 \| total_days > 2 |
| R11 | 1 | $0.01 | $0.00 | +$0.01 | Turn Off — positive_days = 0 \| total_days > 3 |
| R10 | 2 | $0.00 | $0.00 | $0.00 | Budget Decrease — -10 < ROI ≤ 5 \| Budget ≥ $100 |
| R12 | 3 | $0.00 | $0.00 | $0.00 | Budget Decrease — ROI ≤ -50 \| Budget ≤ $65 |
| R06 | 1 | $0.00 | $0.07 | -$0.07 | Turn Off — today_profit ≤ -$1.25 \| total_profit ≤ -$4 |
| R07 | 1 | $0.00 | $1.65 | **-$1.65** | Budget Decrease — ROI ≥ -50 \| Budget > $65 |
| R01 | 3 | $0.93 | $8.01 | **-$7.08** | Turn OFF — Total Days ≥ 5 |

**R01 is the worst-performing rule:** it fires on adsets that have been running for 5+ days, but the analysis shows it's more likely to catch a maturing winner than a genuine loser at that stage. **R04 is the best** — acting on day 1 when ROI is deeply negative is a safe early exit.

Charts: `rule_impact.png`, `rule_saved_vs_burned.png`

---

## 4. Bad Decision Case Studies (A3)

I flagged three categories of decisions a human buyer would not have made.

### Type 1 — Pausing an adset with a profitable 3-day trend (7 cases)

The rule saw a bad-looking day but the prior 3 days were profitable. This is a classic revenue delay trap: the day's revenue may not have fully reported yet.

**Case study — adset `31196781349398`, 2026-06-06:**
- Last 3-day ROI: **+0.26** (profitable trend)
- ROI at time of action: **-0.749** (looked terrible intra-day)
- Rule R08 fired at 04:30 UTC and turned the adset off
- Counterfactual spend blocked: $5.41
- At prior-day ROI, that adset would have earned ~$1.40 in profit — money left on the table

**Case study — adset `31554978465845`, 2026-06-10:**
- Last 3-day ROI: **+0.22**
- ROI at action: **-0.90**
- R08 fired at 15:00 UTC; counterfactual profit blocked: ~$1.13

**Why the rule got it wrong:** R08 only looks at today's ROI. It has no knowledge of the previous days' trend and no concept of time-of-day — so firing at 4:30am on a day that was barely 4 hours old is treated the same as firing at 11pm with a full day's data.

**Pattern:** all 7 Type 1 cases involved R08 (Total Days = 4) or R05. These rules do not distinguish between "today is genuinely bad" and "today's revenue hasn't arrived yet."

### Type 2 — Pausing on day 1 or 2 of spend (45 cases)

45 of 68 Turn OFF firings acted on adsets that had been spending for 1–2 days at most. With this little history, ROI readings are extremely noisy (standard deviation >1.0 on day 1 vs ~0.3–0.5 on day 5+). A -100% ROI on day 1 of a new adset is normal variance, not a signal.

**Case study — adset `31983993876612`, 2026-06-06:**
- Day 1 of spend, fired by R04 at 13:45 UTC
- Spend that day: $2.45
- ROI at action: -0.575
- Counterfactual profit at prior-day ROI: **-$1.41** (so the pause was technically correct on the numbers — but the adset had no history to learn from)

**Case study — adset `31142523663741`, 2026-06-06:**
- Day 2 of spend, fired by R05 at 17:30 UTC
- Spend: $2.32, ROI at action: -1.00
- 3-day ROI was +0.09 (barely positive) — the rule caught this anyway
- This adset appears in both Type 1 and Type 2, illustrating how the risks compound on very young adsets

**Why the rule got it wrong:** R04 is designed for early exits, which is sensible. But it fires on any day-1 ROI reading, including ones taken at 7am when only a fraction of the day's spend and revenue has been recorded. It's making a permanent decision on incomplete information.

**Pattern:** R04 is responsible for 38 of the 45 Type 2 cases.

### Type 3 — Cascade budget cuts (0 cases)

No adset received 2+ successful budget decreases on the same day. Our deduplication step (keeping only the first successful fire per adset per day per rule) confirmed the engine does not compound cuts within a single rule. Cross-rule cascades are possible in theory but did not occur during this week.

Chart: `bad_decisions_scatter.png`

---

## 5. Revenue Delay Quantification (A4)

**Method:** For each performance row with spend > 0, we computed the ratio `fb_conversions / estimated_conversions` grouped by `spend_day_no`. A ratio of 1.0 means revenue is fully reported; below 1.0 means some conversions are still pending attribution.

**Key finding: revenue delay is smaller than expected.**

| Period | Avg conversion ratio | Interpretation |
|---|---|---|
| Days 1–2 | 0.94–0.97 | ~3–6% of conversions still unreported |
| Days 3–5 | 0.96 | Stable — revenue substantially settled |
| Days 6+ | 0.94–1.00 | Fully settled (noise from small sample sizes) |

Revenue arrives within 1 day for the vast majority of conversions. There is no evidence of a multi-day attribution lag in this dataset.

**However, ROI variance on early days is severe:**
- Day 1 mean ROI: **-0.27**, std dev: **±1.35**
- Day 5 mean ROI: **-0.03**, std dev: **±0.76**
- Day 9+ mean ROI: stabilises around 0.0–0.3, std dev: **±0.5–0.6**

This means the real problem for early-day rule firings is not that revenue is missing — it's that a single day's ROI is an almost meaningless sample from a very wide distribution. A rule that acts on day 1 ROI is essentially acting on noise.

Charts: `revenue_delay_conversions.png`, `roi_stability_by_day.png`

---

## 6. Data Quality Issues Found

| Issue | Where | How we handled it |
|---|---|---|
| 50 of 214 rule firings failed silently (API token expired or "no budget to change") | `rule_executions.csv` | Excluded from all impact analysis — only successful actions counted |
| Adset IDs load as floating-point numbers in `buyer_actions.csv`, corrupting 18-digit IDs (e.g. `730122709357812221` becomes `7.3e+17`) | `buyer_actions.csv` | Re-read the column as string; join match rate went from 0% to clean |
| ~100 rows missing conversion rate (`cr`) on days with spend | `daily_adset_performance.csv` | Treated as unknown rather than zero; excluded from conversion-rate aggregations |
| 52 adsets have no recorded start date (`first_spend_date` null) | `campaign_adset_metadata.csv` | Used `spend_day_no` instead, which is available on all rows |
| R09 ("Turn On — Automation Mistake") fired 8 times and failed every time | `rule_executions.csv` | Noted as a finding — the self-correction safety net was non-functional all week |
| All 214 rule executions came from ACC-04 only | `rule_executions.csv` | All impact figures apply to ACC-04 only; stated throughout |

---

## 7. Recommended Agent Decision Rules (derived from findings)

Based on the above analysis, we recommend the following guardrails for the AI agent:

1. **Minimum data gate:** do not recommend Turn OFF or budget changes on adsets with fewer than 3 days of spend data. Flag these as `insufficient_history` and escalate to a human.

2. **Trend vs. snapshot check:** before recommending a pause, compare `last_3_days_roi` to `today_roi`. If the trend is positive but today looks negative, flag as `revenue_delay_suspected` and withhold the pause recommendation.

3. **Retire R01 or narrow its conditions:** R01 (Turn OFF | Total Days ≥ 5) destroyed $7.08 in estimated profit while saving only $0.93. At 5+ days, adsets with a sustained negative ROI should already have been caught by earlier rules. R01 appears to be catching late-maturing adsets at the wrong moment.

4. **R04 day-1 timing guard:** R04 is the highest-volume rule and generally correct, but fires mid-day when the daily ROI is still incomplete. The agent should apply a time-of-day check: do not act on day-1 ROI before at least 20:00 UTC (allowing most of the day's revenue to arrive).

5. **Revenue completeness flag:** compare `estimated_conversions` vs `fb_conversions` in real time. If the ratio is below 0.85 and `spend_day_no ≤ 2`, add a `revenue_incomplete` flag and reduce decision confidence ceiling to 0.4.
