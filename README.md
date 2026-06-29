# The Agent Army Challenge — Mine Marketing (By Tamir Palay)

## What This Is

A working AI agent system that replaces media buyer decision-making on Meta ad campaigns. Built against one week of snapshot data across 6 accounts (ACC-01 to ACC-06).

Four deliverables:
- **Task A** — Investigation: what the existing auto-rules actually did, quantified
- **Task B** — Architecture: four-agent system design with decision boundaries and economics
- **Task C** — Working agent: runs against real data, calls Claude Haiku, costs $0.02 to evaluate 691 adsets
- **Task D** — AI usage log: `DECISIONS.md`

---

## Repo Structure

```
Data/                          ← all 5 CSVs (do not move these)
  README_DATA.md                 ← column documentation for all CSVs
Task A/
  explore_data.ipynb           ← data loading, cleaning, profiling
  analyse_rules.ipynb          ← rule impact analysis and charts
  INVESTIGATION.md             ← findings writeup
  *.png                        ← supporting charts
Task B/
  ARCHITECTURE.md              ← four-agent design doc with Mermaid diagram
Task C/
  context_builder.py           ← builds compressed context per adset (C1+C2)
  agent.py                     ← LLM judgment layer, gates, and routing (C3)
  feedback.py                  ← decision memory interface stub (C4)
  run_agent.py                 ← runs agent over last 3 days (C5)
  compare.py                   ← joins decisions to buyers/rules, finds disagreements (C6)
  RESULTS.md                   ← results, comparison, honest assessment (C7)
  results.jsonl                ← 691 agent decisions from the run
  decisions_log.jsonl          ← same decisions, written by feedback.py
DECISIONS.md                   ← AI usage log (Task D)
```

---

## How to Run

### Prerequisites

```bash
pip install pandas anthropic
```

Python 3.12 or higher recommended. No other dependencies.

### Task A — Notebooks

Open in Jupyter or VS Code. Run cells top to bottom.

```
Task A/explore_data.ipynb      ← run first (data profiling and cleaning)
Task A/analyse_rules.ipynb     ← run second (rule impact analysis)
```

Both notebooks are self-contained — they load and clean data from scratch in the first cell.

### Task C — Agent

Set your Anthropic API key (https://platform.claude.com/), then run:

```bash
# Windows
set ANTHROPIC_API_KEY=sk-ant-...

# Mac/Linux
export ANTHROPIC_API_KEY=sk-ant-...
```

Run the agent over the last 3 days of data:

```bash
python "Task C/run_agent.py"
```

This writes decisions to `Task C/results.jsonl` and prints a cost summary at the end.

Then run the comparison:

```bash
python "Task C/compare.py"
```

This reads `results.jsonl` and prints agent vs. buyer and agent vs. rule disagreements with verdicts.

**The results from my run are already committed** (`Task C/results.jsonl`, 691 decisions, $0.023). You don't need to re-run unless you want to.

### Individual module tests

```bash
python "Task C/context_builder.py"   ← smoke test: builds one context block, no API key needed
python "Task C/feedback.py"          ← smoke test: writes/reads decision memory, no API key needed
python "Task C/agent.py"             ← smoke test: one live LLM call (API key required)
```

---

## What the Agent Actually Does

For each adset on each date, `agent.py` runs this sequence:

1. **Build context** — pulls last 7 days of performance, metadata, rule executions, and buyer actions. Compresses to a structured text block under 500 tokens.
2. **Hard gates** — if fewer than 3 days of spend data, or a buyer acted in the last 24h → escalate immediately, no API call.
3. **Clear loser check** — if ROI < -0.50 for 3+ consecutive days with spend > $30 and no upward trend → pause deterministically, no API call.
4. **Haiku call** — everything else goes to `claude-haiku-4-5-20251001`. Returns JSON: action, amount, confidence, reasoning.
5. **Validate** — confidence is capped by uncertainty flags. If below 0.3 → escalate regardless.

Output schema (matches brief):

```json
{
  "adset_id": "31626016833981",
  "decision_date": "2026-06-11",
  "action": "keep",
  "amount": null,
  "confidence": 0.62,
  "reasoning": "3-day ROI trend is mixed but not decisively negative...",
  "data_quality_flags": ["rule_conflict"],
  "via": "llm",
  "input_tokens": 487,
  "output_tokens": 142
}
```

Added fields beyond the brief minimum: `via` (how the decision was made: `hard_gate` / `clear_loser_rule` / `llm` / `llm_parse_error`), and token counts for cost auditing.

---

## Run Summary

| Date | Adsets evaluated | Reached LLM |
|------|-----------------|-------------|
| Jun 10 | 144 | ~10 |
| Jun 11 | 250 | ~20 |
| Jun 12 | 297 | ~20 |
| **Total** | **691** | **50** |

- **92.8%** routed through hard gates (no API call)
- **7.2%** reached Claude Haiku
- **0%** parse errors — Haiku returned valid JSON on every call
- **Total cost: $0.023** of a $10 budget

On the 4 agent-vs-rule cases with verifiable next-day outcomes: **agent was right 3 out of 4 times**. In all 3 wins, the rule fired a budget cut on a negative intraday ROI snapshot; the adset recovered by end of day.

---

## Corners Cut

**No live Meta API.** The Executor's API call is stubbed. All decisions were evaluated against snapshot CSVs, not a live account. Real deployment would surface edge cases around rate limits, budget minimums, and campaign-level caps that aren't visible here.

**Feedback loop is a stub.** `feedback.py` shows the full interface (record decision → record outcome → build memory) and is wired into `run_agent.py`, but the Auditor Agent that scores outcomes was not built. There is no future-day data to score against anyway — the dataset ends Jun 12.

**Buyer session gate is blunt.** The `recent_human_action` gate blocks any adset a buyer touched in the last 24 hours, regardless of whether it was a considered individual edit or a 300-adset batch script. In this dataset, buyers ran batch sessions on Jun 9 and Jun 12, which blocked the majority of Jun 10 and Jun 11 decisions. A production gate would distinguish batch from individual edits.

**Comparison limited to ACC-04.** Rule executions only exist for one account. 83% of agent decisions had no rule-engine ground truth to compare against.

**Dataset is 7 days deep.** Most adsets look "new" within the evaluation window. With 30+ days of history, the `insufficient_history` gate would fire on ~5% of adsets instead of ~60%. See `Task C/RESULTS.md` for the full analysis of why this matters and what would change.

---

## Time Spent

| Task | Approximate time |
|------|-----------------|
| Task A — data exploration and cleaning | 3–4 hours |
| Task A — rule impact analysis and writeup | 2–3 hours |
| Task B — architecture design and doc | 1 hour |
| Task C — agent code (5 files) | 3–4 hours |
| Task C — running, debugging, results | 1 hour |
| Documentation (DECISIONS.md, presentation notes, README) | <1hour |


---

## Key Files to Read First

If you're reviewing this for the first time:

1. `Task A/INVESTIGATION.md` — what the rules did and where they went wrong
2. `Task B/ARCHITECTURE.md` — the four-agent design (Mermaid diagram renders on GitHub)
3. `Task C/RESULTS.md` — what the agent found, honest assessment of weaknesses
4. `DECISIONS.md` — where I pushed back on the AI and why
