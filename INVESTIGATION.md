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
#Results of phase A1:
>We have one week of data (Jun 6–12) across 6 ad accounts, covering 1,000 unique adsets and ~5,000 daily performance rows. About 60% of those rows have zero spend — adsets that were paused or inactive on a given day. We kept these rows but flagged them, since they show us when adsets went quiet, which matters for measuring rule impact.

>Revenue and profit go missing on zero-spend days — this is expected and safe to fill with zero. But even on active days, ~100 rows are still missing the cr (conversion rate) field, which we'll treat as unknown rather than zero.

>Adset IDs exist in two length formats (14-digit vs 18-digit). ACC-04 uses 14-digit IDs everywhere; all other accounts use 18-digit. This is consistent across tables, so joining is safe as long as we treat IDs as strings (not numbers, which would silently corrupt them).

>50 out of 214 rule firings failed — either the API token was invalid (OAuthException) or there was no budget left to change. We'll exclude these from any impact analysis since no actual action was taken.

>Buyer action IDs don't match the performance table at all — the buyer_actions.csv stores adset IDs in scientific notation (e.g. 7.3e+17) due to float parsing. We'll need to re-parse those as integers before any join can work.

>All 214 rule executions came from ACC-04 only, and they all joined cleanly to the performance table. The other 5 accounts had no automated rule activity this week.

<!-- Section 3: Rule Impact Analysis — to be filled in after analyse_rules.py -->
<!-- Section 4: Bad Decision Case Studies — to be filled in after analysis -->
<!-- Section 5: Data Quality Issues Summary — partially complete above -->
