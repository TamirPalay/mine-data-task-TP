# Task B — Presentation Notes
Cheat notes for walking someone through the architecture design. Simple language, pointers to where things live.

---

## The One-Sentence Pitch

Instead of simple rules that fire blindly every 30 minutes, we have four agents with different jobs — one watches, one thinks, one acts, one reviews — and nothing reaches the ad platform without passing through a safety check first.

---

## What a "POC Architecture" Actually Means

POC = Proof of Concept. The diagram and document are not running code — they're a blueprint that shows:
- Who the agents are and what each one does
- What decisions they're allowed to make on their own vs. what needs a human
- How much it costs to run
- What could go wrong and how we stop it

**Where to point:** open `Task B/ARCHITECTURE.md` — the Mermaid diagram at the top renders as a visual flowchart on GitHub. Walk through it left to right.

---

## The Four Agents — What to Say About Each

### Monitor — "The Watchman"
Runs every 30 minutes. Looks at all adsets and answers one question: *does anything need attention right now?* It does this with pure arithmetic — no AI involved, so it's fast and free to run. Crucially, it also enforces the gates we learned from Task A: no action on day-1 adsets before 20:00 UTC, no action if a human buyer touched this adset in the last 24 hours, no action if we already acted on it in the last 4 hours.

**Why this matters to say:** the existing rule system had no gates at all. That's why 45 out of 68 pauses happened on day 1 of an adset's life.

**Where to point:** Section 1 — "Monitor Agent — the filter" bullet list.

### Analyst — "The Decision-Maker"
Only gets called when the Monitor flags something. It reads the last 7 days of that adset's history, compresses it into a short summary (under 500 tokens — roughly one paragraph), and asks the AI to make a recommendation. The AI returns a structured answer: what to do, how confident it is, and why. If confidence is below 50%, it doesn't act — it sends the case to a human instead.

**Why this matters to say:** this is the only place an LLM is used. Everything else is code. That keeps costs near zero and keeps the AI in its lane — making judgment calls, not running the whole system.

**Where to point:** the context compression example in Section 5 — it shows exactly what the AI sees (and what it doesn't see).

### Executor — "The Gatekeeper"
Takes the Analyst's recommendation and checks it against a hard list of rules before touching the Meta API. These rules cannot be overridden by the AI — they're in code. If something fails the check, it's blocked and logged. The Executor is also what prevented the R09 problem: if the API fails, it alerts immediately rather than silently doing nothing.

**Why this matters to say:** this is the safety layer that lets us trust the AI. The AI can be wrong — the Executor makes sure wrong decisions don't cause too much damage.

**Where to point:** Section 2 — "Forbidden" tier. These are the non-negotiables.

### Auditor — "The Reviewer"
Runs once a day at 2am, after the previous day's revenue has settled. It looks at every decision made yesterday and checks: did it turn out to be right? It writes that result into a memory file that the Analyst reads the next time it looks at that adset. This is how the system gets smarter over time — not by retraining the AI model, but by giving it better context each time.

**Why this matters to say:** no rule engine can do this. Rules have no memory. This is the key advantage of the agent approach.

**Where to point:** the `decision_memory.jsonl` example at the bottom of Section 5 — one line per decision, showing whether it was vindicated.

---

## Decision Boundaries — What to Say

Three tiers. The clearest way to explain it:

> "We drew a line around what the system can do on its own, what it has to ask a human about, and what it can never do regardless of what the AI recommends."

**Acts on its own:** small budget changes (≤20%), pausing a consistent loser (negative ROI for 3+ days), re-enabling something it wrongly paused.

**Asks a human first:** anything bigger than 20% budget change, anything where a human buyer was recently involved, scaling a second adset that looks similar to a winner (risky — could cannibalise it).

**Never allowed:** acting on an adset with fewer than 3 days of data, budget increases over 50% in one go, acting on the same adset twice within 4 hours, continuing if the API is broken or the system is behaving erratically.

**Where to point:** Section 2 — the three-tier list. Clean and readable.

---

## Economics — What to Say

The honest version of the cost story:

> "At 6 accounts and ~1,000 adsets, this system costs about 12 cents a day to run. The $30/day budget in the brief is 250× more than we actually need. Even at 600 accounts, it costs less per year than one media buyer's salary — and it's managing 200× more accounts."

**The key number:** $0.0003 per AI decision. That's three-hundredths of a cent.

**The smart design choice to highlight:** most decisions *don't* use AI at all. The Monitor filters out 95% of adsets every cycle. Clear losers go straight to the Executor without an AI call. The AI only gets involved when there's a genuine judgment call to make. This is why the cost is so low.

**Where to point:** Section 3 — the cost calculation block and the "When to use which model" table.

---

## Failure Modes — What to Say

> "I mapped out the five most likely ways this system loses money or breaks, and designed a specific guardrail and a kill-switch for each."

The ones worth highlighting in a presentation:

**Failure 1 — Acting on noise:** same problem as R08 in Task A. Guardrail: 3-day data gate and trend check, so the AI can't make a call on incomplete information.

**Failure 3 — API breaks silently:** this is exactly what happened to R09 all week. Guardrail: Executor logs every API response. Kill-switch: three failures in a row = all automated actions stop until a human fixes it.

**Failure 5 — Campaign cascade:** if one campaign's adsets all look bad simultaneously, the old rule system could have paused all of them and killed the campaign's spend entirely. Guardrail: max 2 pauses per campaign per 30-minute cycle.

**Where to point:** Section 4 — the failure modes table. Third column is the guardrail, fifth column is the kill-switch.

---

## One Honest Gap to Acknowledge

The data flow section (Section 5) covers what each agent reads and when, but it doesn't fully address the risks of relying on buyer_actions.csv — which we know from Task A has an ID corruption bug and 49 rows with no timestamps. In production, buyer actions would need to be treated as unreliable historical context rather than a source of truth. This is flagged in the "What this POC does not cover" section at the bottom.

---

## The Line That Lands Best

> "The rule engine had no memory, no concept of time of day, and no way to know when its own actions had failed. This system fixes all three."

---

## Quick Reference: Where Things Live

| Topic | Where |
|---|---|
| Full diagram | `ARCHITECTURE.md` Section 1 — Mermaid flowchart |
| Decision tiers | `ARCHITECTURE.md` Section 2 |
| Cost maths | `ARCHITECTURE.md` Section 3 |
| Failure modes table | `ARCHITECTURE.md` Section 4 |
| What the AI actually sees | `ARCHITECTURE.md` Section 5 — context compression example |
| What we didn't build | `ARCHITECTURE.md` Section 6 |
