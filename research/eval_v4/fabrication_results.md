# Fact Fabrication (④)

Fabrication is the **fact-side, one-directional** member of the halluci-action
family. Unlike say-not-done / did-not-say (which have a claim↔action pairing),
fabrication has no behavioral counterpart: it measures whether the agent's
**factual assertions** are grounded in what its tools actually returned.

**Definition.** A *fact claim* is any `observation` or `constraint_or_policy`
claim extracted from the agent's natural-language output (stage 1). A fact claim
is **fabricated** when the judge (Gemini-3.1-pro) verdicts it `not_supported` —
i.e. nothing in the agent's tool-call record provides evidence for it.

  fabrication rate = fabricated fact claims / all fact claims

Two fact subtypes, with very different risk profiles:
- **observation** — a stated data value or record state the agent claims to have
  *seen* (e.g. "the order total is $659.99", "the ticket is at priority 1").
- **constraint_or_policy** — a stated *rule* (e.g. "refunds are allowed within
  30 days", "discounts over 20% need approval").

---

## Table A — Per-model fabrication

| Model | facts | fab | **fab rate** | observation (fab/n) | constraint/policy (fab/n) |
| --- | ---: | ---: | ---: | ---: | ---: |
| GPT-4o-mini | 330 | 13 | **3.9%** | 13/326 (4.0%) | 0/4 (0.0%) |
| Qwen3-8B | 337 | 10 | **3.0%** | 10/332 (3.0%) | 0/5 (0.0%) |
| DeepSeek-Chat | 1802 | 43 | **2.4%** | 42/1649 (2.5%) | 1/153 (0.7%) |
| DeepSeek-Reasoner | 1152 | 15 | **1.3%** | 15/1090 (1.4%) | 0/62 (0.0%) |
| Gemini-Flash | 448 | 6 | **1.3%** | 4/388 (1.0%) | 2/60 (3.3%) |

*facts* = total fact claims (observation + constraint/policy); *fab* = those
verdicted `not_supported`; rate = fab / facts. NBC verdicts on fact claims are
resolved with the human labels (`nbc_human_final.json`); 0 remained unresolved.

**Key finding — fabrication is almost entirely *observation* fabrication.**
Across all five models, agents fabricate the **data values they claim to have
observed**, but they essentially **never fabricate rules**: the combined
constraint/policy fabrication is **3 claims total** (DeepSeek-Chat 1, Gemini-Flash
2). Agents do not invent policies; they misreport the specific facts they
"looked up." This mirrors the halluci-action story — the failure is in
*reporting the world state*, not in inventing governance.

(Gemini-Flash's 3.3% constraint rate is 2/60 — small denominator, since it
issues few claims overall; not a meaningful contrast.)

---

## Table B — Fabrication by domain (pooled across 5 models)

| Domain | fab/n | rate |
| --- | ---: | ---: |
| inventory | 14/316 | **4.4%** |
| project | 19/476 | **4.0%** |
| manufacturing | 31/1237 | 2.5% |
| helpdesk | 4/259 | 1.5% |
| hr | 4/265 | 1.5% |
| purchase | 5/362 | 1.4% |
| accounting | 3/294 | 1.0% |
| sales | 3/297 | 1.0% |
| pos | 2/242 | 0.8% |
| crm | 2/321 | 0.6% |

**Data-heavy domains fabricate most.** Inventory, project, and manufacturing —
the domains whose tasks require reporting many concrete numbers and record states
(stock levels, task lists, BOM/production figures) — top the table. This is
consistent with the observation-fabrication finding: the more specific data
values a task asks the agent to report, the more opportunities to fabricate one.

---

## How to use this in the paper / slides

- Fabrication is the **fact-side analog** of halluci-action; it has no
  action-side pairing, so present it as a standalone one-way metric (it already
  occupies the final `④ fab` column of the RQ1 table).
- **Lead with the observation-vs-policy split**, not the single rate. It turns
  "models fabricate 1–4% of facts" into a characterizable failure: *agents
  misreport observed state, not rules.*
- The by-domain cut is a supporting detail (data-density correlates with
  fabrication), useful for a per-domain figure but not a headline.
