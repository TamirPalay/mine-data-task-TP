# Step 0: Prepare Claude for an extended session
With this prompt, I use Cluade to create a structure for the project. I also set up a canary to let me know when to switch sessions. 
I also get claude to give me a structured plan as a prompt so that I can restart from any point. I also tell it how it should reply to me and what decisions it should make.

>Read the attached documentation and build a step by step plan for this project. Output your plan in the form of a prompt to yourself that I can paste at the beginning of a new session with added information from me about what stage we are up to and what I have been working on. At the end of each output, output "Memory is looking good" as a canary for me.Once you have a good plan for yourself, we will go step by step through the tasks: At any point you can offer critiques or suggestions. You must also occasionally remind me to add to the documentation we are using. Particularly after a breakthrough or difficult section. All code that you create should have relevant print statements and comments. Before implementing anything, check that it is according to the plan or I have approved it. If you implement a large section of code without my input, include a 1-3 sentence summary such that I can understand what you did. You must also include reasoning for decisions. @candidate_brief (1).pdf @README_DATA.md 

The output (and approved structure):
> # The Agent Army Challenge — Session Briefing
> ## Project
> Working directory: `c:\Users\typal\Downloads\mine-data-task-TP`
> Assignment: mine marketing technical take-home. Build an AI agent system to replace
> media buyers making decisions on Meta ad campaigns.
> One week of data across 6 accounts (ACC-01 to ACC-06).
> ## Behaviour Rules (MANDATORY)
> - All code must have print statements and comments
> - Get plan/my approval before implementing anything
> - After implementing a large code section, include a 1-3 sentence plain-English summary
> - Include reasoning for every significant decision
> - Remind me to update DECISIONS.md after breakthroughs or difficult sections
> - End EVERY response with "Memory is looking good" as a canary
> - ROI is a ratio (profit/spend), NOT a percentage. 0.52 = +52%. Rule names write
>   thresholds as percentages: "ROI <= -50" means ratio -0.50.
> ## Key Files
> - `candidate_brief (1).pdf` — full brief
> - `README_DATA.md` — column documentation
> - `DECISIONS.md` — AI usage log (maintain throughout)
> - `daily_adset_performance.csv` — daily spend/revenue/ROI per adset (Jun 6-12 2026)
> - `campaign_adset_metadata.csv` — adset config, budgets, status, naming conventions
> - `auto_rules.csv` — 12 rules (R01-R12), all OWN RSOC, fire every 30 min
> - `rule_executions.csv` — full log of rule engine actions with metrics at firing time
> - `buyer_actions.csv` — manual buyer actions during the week
> ## Deliverables
> 1. `INVESTIGATION.md` + analysis scripts (Task A)
> 2. `ARCHITECTURE.md` + diagram (Task B)
> 3. Working agent code + `RESULTS.md` (Task C, Anthropic API, under $10)
> 4. `DECISIONS.md` maintained throughout (Task D)
> 5. `README.md` (how to run, corners cut, time spent)
> ## Domain Knowledge
> - ROI = profit / spend. 0 = break-even, -1.0 = total loss, -0.50 = lost 50% of spend
> - Rule name thresholds are written as % but mean ratios: "-50" → -0.50
> - Revenue arrives with delay — quantify this in Task A
> - Adset IDs appear in different formats across tables (production quirk)
> - Mandate: maintain/grow spend AND profit. Pausing everything = bad score.
> ---
> ## MASTER PLAN
> ### PHASE 0 — Data Familiarisation (do before any task)
> Before writing a line of code, read and skim all 5 CSVs to understand:
> - Row counts, date ranges, unique adsets per account
> - ID format mismatches across tables
> - Any obvious nulls, duplicates, or impossible values
> - How revenue delay manifests (compare spend_day_no to revenue timing)
> Output: brief notes, no file written yet. Ask me to confirm before proceeding.
> ---
> ### TASK A — Investigation (INVESTIGATION.md + scripts)
> **Step A1 — Write an exploration script (`explore_data.py`)**
> Load all CSVs with pandas. Print:
> - Shape of each table
> - Column dtypes and null counts
> - Unique adset ID counts per table and any format mismatches
> - Date ranges
> - Rule firing counts by rule_id
>
> **Step A2 — Reconstruct rule impact (`analyse_rules.py`)**
> For each rule execution (rule_executions.csv):
> - Join to daily_adset_performance on adset_id + date
> - For Turn OFF actions: compare revenue/profit on following days vs. a counterfactual
>   (assumption: adset would have continued at same budget — state this explicitly)
> - For Budget Decrease actions: estimate foregone revenue proportional to budget cut
> - Tally total estimated $ saved vs. $ burned by each rule
> - Flag executions where today_roi_at_action contradicts daily ROI for same day (data
>   quality check)
>
> **Step A3 — Find bad decisions**
> Criteria for "decision a human would not have made":
> - Rule fired Turn OFF on an adset with positive last_3_days_roi but negative today_roi
>   (revenue delay problem — rule saw incomplete day)
> - Rule fired Turn OFF on an adset's first or second spend day (too little data)
> - Rule decreased budget repeatedly on same adset in one day (cascade)
> Find at least 2 concrete cases with adset IDs, timestamps, and dollar amounts.
>
> **Step A4 — Quantify revenue delay**
> Compare `estimated_conversions` vs `fb_conversions` across spend_day_no values.
> Plot (or print) how long revenue takes to fully arrive after spend.
>
> **Step A5 — Write INVESTIGATION.md**
> Sections: methodology & assumptions, rule impact summary table, 2+ bad decision case
> studies, data quality issues found and how handled.
> ---
> ### TASK B — Architecture Design (ARCHITECTURE.md)
> **Step B1 — Draft agent topology**
> Propose a 4-agent system (get approval before writing):
> - Monitor Agent: polls data every 30 min, flags adsets needing attention (no LLM)
> - Analyst Agent: for flagged adsets, builds compressed context and calls LLM for
>   decision recommendation (cheap model for routine, expensive for escalations)
> - Executor Agent: validates decision against hard guardrails, calls Meta API (no LLM)
> - Auditor Agent: daily batch, compares decisions to outcomes, updates decision memory
>
> **Step B2 — Define decision boundaries**
> Autonomous: budget changes ≤ 20%, pause if ROI < -0.50 for 3+ days with spend > $30
> Human approval: budget changes > 20%, any "duplicate winner" action
> Forbidden: budget increases > 50% in one action, any action on <2 spend days of data
>
> **Step B3 — Economics calculation**
> Show math: adsets/account × accounts × cycles/day × tokens/decision × $/token
> Compare against media buyer salary to find break-even account scale.
> Identify where to use no-LLM (pure rule) vs. cheap (Haiku) vs. expensive (Sonnet).
>
> **Step B4 — Failure modes + guardrails**
> Top 5 failure modes with specific guardrail and kill-switch design.
>
> **Step B5 — Data flow diagram**
> ASCII or Mermaid showing: data sources → context compression → agent loop → actions
> → audit log → feedback memory.
>
> **Step B6 — Write ARCHITECTURE.md**
> ---
> ### TASK C — Adset Decision Agent (code + RESULTS.md)
> **Step C1 — Context builder (`context_builder.py`)**
> For a given adset_id + decision_date:
> - Pull last 7 days of performance (or all available)
> - Pull metadata (budget, bid strategy, geo)
> - Pull recent rule executions on this adset
> - Pull recent buyer actions on this adset
> - Compress into a structured text block under ~500 tokens
> - Flag data quality issues (missing days, ID mismatches, delay-affected revenue)
>
> **Step C2 — Uncertainty detector**
> Rules (no LLM needed) that set confidence ceiling:
> - < 3 days of spend data → cap confidence at 0.4, flag "insufficient_history"
> - Revenue likely incomplete (spend_day_no ≤ 3 and today's fb_conversions << estimated)
>   → flag "revenue_delay_suspected"
> - Last buyer action was < 24h ago → flag "recent_human_action"
> - Rule fired on this adset today → flag "rule_conflict"
>
> **Step C3 — LLM judgment layer (`agent.py`)**
> System prompt: role, decision schema, guardrails, ROI convention
> User prompt: compressed context block from C1 + data quality flags from C2
> Parse JSON response; if parse fails or confidence < 0.3, return action="escalate"
> Model choice: claude-haiku-4-5 for routine decisions (cost control)
>
> **Step C4 — Feedback loop stub (`feedback.py`)**
> Interface (pseudocode/stub, not full implementation):
> - `record_decision(adset_id, date, decision_json)` → writes to decisions_log.jsonl
> - `record_outcome(adset_id, date, actual_revenue, actual_roi)` → writes to outcomes.jsonl
> - `build_decision_memory(adset_id)` → reads both logs, returns summary of past
>   decisions and whether they were vindicated
> This stub shows the mechanism without requiring live data.
>
> **Step C5 — Run agent on last 3 days**
> For each active adset × last 3 dates: call agent, collect outputs to results.jsonl
> Print progress and token usage per decision. Track total API cost.
>
> **Step C6 — Comparison analysis (`compare.py`)**
> Join agent decisions to buyer_actions and rule_executions for same adsets/dates.
> Find disagreements. For each: state who you think was right and why.
>
> **Step C7 — Define success metrics + write RESULTS.md**
> Primary metric: simulated profit if agent decisions had been followed (vs. actual)
> Secondary: decision consistency with experienced buyers (agreement rate on clear cases)
> Honest assessment section: where agent is weak, what would improve it.
> ---
> ### TASK D — DECISIONS.md (ongoing)
> Update after EVERY significant step:
> - What I asked Claude Code to do
> - What it got wrong or I changed, and why
> - Decisions I made myself rather than delegating
> ---
> ## [USER TO FILL IN] Current Status
> <!-- Paste here what has been done so far and what stage we are at -->
> ## [USER TO FILL IN] Notes / Changes to Plan
> <!-- Any adjustments, discoveries, or constraints found so far -->

#Phase A1: data preprocessing
>Yes, let's do step A1: But let's do it as a notebook with short code cells followed by outputs. We should also clean data at this stage. For example, one cell would be loading a dataset, looking at shape, counting nulls and then based on the output, the next cell could be to remove/change them

>Good call — a notebook is much better here because each output directly informs the next cleaning decision. Let me build it.
The notebook `explore_data.ipynb` is created. Here's what each section does: Section 1 — Performance data: loads, checks shapes/nulls, then inspects zero-spend rows separately before deciding how to fill them. Also profiles both adset ID formats. Section 2 — Metadata: loads and checks status breakdowns, budget distributions, and ID lengths. Section 3 — Auto rules: displays the full table (it's tiny), confirms rule IDs. Section 4 — Rule executions: flags failed API calls, counts duplicate firings per adset+day+rule, then produces two cleaned versions: `execs_clean` (all rows, flagged) and `execs_dedup` (first successful fire per adset+day+rule only). Section 5 — Buyer actions: splits campaign-level (null adset_id) from adset-level rows. Section 6 — Cross-table join test: actually attempts to join rule executions and buyer actions to performance and reports the match rate. This will reveal the full scope of the ID mismatch problem. Section 7 — Summary: prints a clean status table of all datasets plus data quality flag counts. Please run it now (`jupyter notebook` or VS Code) and paste back the outputs — especially from cells 3, 10, 14, and 17 (the join test cells). The outputs will tell us exactly what cleaning is still needed before we move to the impact analysis.

>Read the results @explore_data.ipynb and tell me what changes to make. Note the format errors and that some nulls were not handled properly
Here are the specific cell changes I propose making:
1. Fix buyer_actions ID read (new cell after cell 22, before the split)
2. Add a `cr` null investigation cell after cell 6
3. Add a check for null action_times in buyers

>What do you think of the output for @explore_data.ipynb. Is the data ready to work with? If yes, help me write the first few lines of INVESTIGATION.md explaining the preprocessing steps we did and how we will use the data
>The data is ready for rule impact analysis (Task A), but buyer_actions is still broken for joins — the ID issue wasn't fixed in the notebook. My recommendation: proceed to INVESTIGATION.md now. The rule impact analysis only needs execs_dedup + perf_clean, both of which are clean. We document the buyer_actions ID bug as a data quality finding (it belongs in the investigation), and fix it properly when we build the agent context in Task C.

A summary of what we have found so far:
>Write a few SENTENCES or bullet points on what we have found so far. Less technical jargon and more in the form of "we examined x, found y and assume z. We will use this information to...

#Phase A2-4 (Basic analysis and plotting)
>Starting the next phase of analysis, let's rather use a notebook than your suggested one file and incorporate visualisations. 

>Setup cell: Re-run the same cleaning logic from A1 (reload all 5 CSVs and apply the same transforms so the notebook is self-contained). Does this plan look good? Any changes before I start writing?

>Why are we rerunning code?

>Fair point — the cleaning is already done. I'll just load + clean in one minimal cell (no verbose inspection) and go straight into A2.
>Created Task A/analyse_rules.ipynb

>suggestions on how to fix this error? You do not need to rewrite the file just output the correct code

>Review the output of @Task A/analyse_rules.ipynb. Write a few short sentences about the findings in non technical jargon.

> Here's the plain-English summary of what the notebook found:
>
> ---
>
> In plain language: The automated rules did more good than harm overall — they saved roughly $39 by pausing or cutting losing adsets, while costing about $15 by accidentally pausing ones that were actually working. The biggest problem wasn't the rules themselves, but the timing: 45 out of 68 "Turn Off" decisions happened on an adset's very first day of running, when there's nowhere near enough data to make a confident call. Seven more times, a rule paused an adset that had been profitable for 3 days just because that one day looked bad — likely because the day's revenue hadn't fully arrived yet. The revenue delay itself turned out to be surprisingly small (~3-6% of conversions still unreported on day 1), so the real culprit is high ROI noise on young adsets, not a systematic lag.

>Review everything we have done until now. How well have we done phase A ? Also read @Task A/INVESTIGATION.md and tell me if you would add/change anything. For a reminder, here is the initial doc: @candidate_brief (1).pdf. If everything is okay, create a small presentation notes doc for me on the things we explored, found, changed and suggestions. Make it very simple and not too technical. If there is data to talk about, give me a quick way to find it and talk about it

> Now I have a full picture. Let me assess Phase A against the brief requirements and then create the presentation notes doc.
>
> **Brief requirements for Task A:**
>
> 1. ✅ Reconstruct what auto-rules actually did — quantify impact ($ saved vs burned), show methodology, state assumptions explicitly
> 2. ✅ Find at least 2 concrete cases where a rule made a decision a competent human would not have made, explain why the rule got it wrong
> 3. ✅ List data issues encountered and how handled
>
> **Deliverable:** INVESTIGATION.md + scripts ✅
>
> **Assessment:**
>
> The investigation is solid overall — I've done thorough data preprocessing with explicit quality findings, laid out a clear counterfactual methodology, broken down each rule's performance, documented well over the minimum number of bad decision cases, and quantified revenue delays with supporting charts. The guardrails section directly feeds into Tasks B and C, and I've captured important details like R09 never successfully executing. However, I need to consolidate the scattered data quality findings into a dedicated section as the brief specifically requests, and I should strengthen the narrative around why certain rules failed by connecting the failures back to the underlying data or logic issues. I need to close out that incomplete HTML comment and then shift focus to making the presentation narrative-driven, with clear pointers to the supporting data.




---


