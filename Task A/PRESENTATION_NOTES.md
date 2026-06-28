# Task A — Presentation Notes
Simple talking points for walking someone through what we did and found.

---

## The Story in One Paragraph

We were given one week of real ad campaign data and asked: "are the automated rules helping or hurting?" We analysed every action the rules took, estimated how much money each one saved or cost, and looked for cases where a rule behaved in a way a human buyer never would. We found the rules were net-positive overall — but a large chunk of their decisions were made with almost no data to go on, and a few of them actively killed campaigns that were working.

---

## What We Explored

### The data
- **5 files**, one week (Jun 6–12), across 6 ad accounts
- **1,000 unique adsets**, ~5,000 daily performance rows
- **60% of rows have zero spend** — adsets that were paused. We kept these rather than deleting them, because they show *when* adsets went quiet (that gap matters)
- **214 rule firings** logged, but **50 of those failed silently** (either the API token had expired or there was no budget left to cut). We filtered these out before any analysis.

**Where to show it:** open `explore_data.ipynb`, scroll to the summary table at the bottom (last cell). It gives row counts, null counts, and ID format notes for every file in one place.

### A data quality catch worth mentioning
When you load the buyer actions file in Python, adset IDs get silently corrupted — they're stored as floats, which rounds 18-digit numbers. The join match rate before fixing this: **0%**. After fixing (reading as strings): clean join. This is the kind of thing that would silently break a production system.

---

## What We Found

### 1. The rules did more good than harm — but not by a huge margin

| | Turn OFF rules | Budget cut rules |
|---|---|---|
| Money protected (good calls) | $35.74 | $3.44 |
| Money missed (bad calls) | $13.21 | $1.65 |
| **Net** | **+$22.52** | **+$1.80** |

Net across everything: **+$24.32 saved** over the week.

**Where to show it:** `rule_impact.png` — green bars are rules that helped, red bars are rules that hurt. R04 is the clear winner. R01 is the clear loser.

### 2. The best rule (R04) and the worst rule (R01)

**R04** — "Turn Off if it's day 1 and ROI is below -50%": saved $23.16, burned nothing. Fast, decisive, on genuinely fresh losers.

**R01** — "Turn Off if the adset has been running 5+ days": burned $8.01, saved only $0.93. By day 5, real losers have usually already been caught by earlier rules. R01 tends to catch adsets that are just starting to turn profitable.

### 3. The biggest problem: acting too early

**45 out of 68 Turn Off decisions happened on day 1 or 2 of an adset's life.** That's like firing a new employee on their first day because they haven't closed a deal yet.

ROI variance on day 1 is enormous (standard deviation of ±1.35 — meaning anything from -2.35 to +1.08 is "normal"). Acting on that is acting on noise.

**Where to show it:** `roi_stability_by_day.png` — the error bars on day 1 are huge; by day 5-6 they shrink significantly.

### 4. Pausing winners (the dangerous case)

7 times during the week, a rule turned off an adset that had been profitable for the last 3 days — because that one day looked bad. Example:

- **Adset 31196781349398, Jun 6** — 3-day ROI was +0.26 (profitable). Rule fired at 4:30am UTC. Today's ROI at that point: -0.75. The rule had no way to know it was 4.5 hours into the day and most revenue hadn't arrived yet. Blocked ~$1.40 in estimated profit.

The rule's blind spot: it looks at a snapshot of today's ROI with no concept of time-of-day or trend direction.

**Where to show it:** `bad_decisions_scatter.png` — red dots are the "paused a winner" cases. They sit in the top-right quadrant (good 3-day trend, bad today).

### 5. Revenue delay was smaller than expected

We expected revenue to take days to arrive. It doesn't — about 94-97% of conversions are reported within the same day. The real issue isn't delay; it's noise. A rule firing at 4am sees a day that's 17% complete and calls it a loss.

**Where to show it:** `revenue_delay_conversions.png` (left chart: estimated vs reported converge quickly) and `roi_stability_by_day.png` (the noise problem).

### 6. The safety net never worked

There's a rule called R09: "Turn On | Automation Mistake" — designed to reverse bad pauses. It fired 8 times during the week. It failed every single time (OAuthException). The self-correction mechanism was completely broken.

---

## What This Means for the Agent

These findings directly shaped the guardrails we're building into the AI agent:

1. **Don't act on fewer than 3 days of data** — flag as "not enough history", escalate to human
2. **Check the trend, not just today** — if 3-day ROI is positive and today looks bad, hold off
3. **Check time of day** — don't make Turn Off decisions before most of the day's revenue has had time to arrive (20:00 UTC suggested)
4. **R01 should be retired or narrowed** — it's the worst performing rule and the agent won't replicate its logic
5. **Revenue completeness check** — if estimated and reported conversions are diverging significantly on a young adset, flag the decision as uncertain

---

## Corners Cut / Honest Limitations

- The counterfactual ("what would have happened if the rule hadn't fired") assumes the adset would have continued at prior-day ROI. Real performance might have gone up or down — we can't know.
- All rule executions came from **ACC-04 only** — the other 5 accounts had no automated rule activity this week. So these conclusions apply to one account's behaviour.
- Buyer actions could not be fully compared (ID corruption issue). Fixed for the agent in Task C, but the comparison in Task A is incomplete.
