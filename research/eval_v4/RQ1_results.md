# Slides — Experimental Setup + RQ1

## Slide 1 — Experimental Setup

**Agent (author) models evaluated (5):**
DeepSeek-Chat · DeepSeek-Reasoner · Gemini-Flash · GPT-4o-mini · Qwen3-8B

**Judge model:** Gemini-3.1-pro (used uniformly across all evaluation stages)

**Environment:** simulated Odoo ERP; agents act via business tool calls
(search/get reads + create/update/escalate/confirm/deliver writes).

**Tasks:** ~60 tasks across **10 business domains** — accounting, CRM, helpdesk,
HR, inventory, manufacturing, POS, project, purchase, sales. Two conditions:
**independent** (single task) and **dependent** (chained tasks).

**Scale evaluated (5 models):**
- 2,142 action claims (action_intention / action_completion)
- 4,069 factual claims (observation / constraint)
- 2,835 executed tool actions

**Halluci-Action measured as a two-direction say-do framework**
| Direction | Base gap | Severity refinement |
| --- | --- | --- |
| claim → action ("said it") | ① say-not-done (over-claim) | required_miss / forbidden |
| action → claim ("did it") | ② did-not-say (silent) | covert (silent ∧ forbidden) |
| facts | ④ fabrication (one-way) | — |

---

## Slide 2 — RQ1: Is there halluci-action? (cross-model)

**Per-model halluci-action**

| Model | ① say-not-done | of which **required-miss** | ② did-not-say | of which **covert** | HAR ③ | ④ fab |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| DeepSeek-Chat | 6.7% | 0.4% | 2.6% | 0.0% (0) | 4.7% | 2.4% |
| DeepSeek-Reasoner | 3.7% | 0.2% | 7.5% | 0.6% (5) | 5.6% | 1.3% |
| Gemini-Flash | 0.9% | 0.0% | 43.6% | 0.0% (0) | 28.1% | 1.3% |
| GPT-4o-mini | 9.5% | 9.5% | 42.7% | 0.3% (1) | 29.8% | 3.9% |
| Qwen3-8B | 21.3% | 9.6% | 49.7% | 3.3% (11) | 38.6% | 3.0% |

① say-not-done = unsupported action claims / action claims (action_intention + action_completion
only). ② did-not-say = undisclosed actions / **all** executed actions (canonical, matches paper
Table 2). required-miss = required ∧ unsupported; covert = silent ∧ forbidden (the dangerous
slices). Gemini-Flash's 43.6% ② is almost entirely undisclosed *read* operations (0 silent writes).

**Takeaways**

1. **Halluci-action is present in every model** — no model is gap-free on say-do
   alignment.
2. **The raw over-claim rate is misleading; severity is what separates models.**
   DeepSeek's over-claims are almost all benign (required-miss 0.2–0.4%), i.e.
   "said it would run some optional check it didn't." GPT-4o-mini and Qwen
   over-claim on the task's **core required actions** (required-miss ~9.5%) —
   they falsely report completing what the task actually needed.
3. **Two failure profiles:**
   - Strong models (DeepSeek-Chat/Reasoner): occasional, *low-stakes* say-not-done;
     little silent action.
   - Weak models (Qwen, GPT-4o-mini): high required-miss **and** silent
     consequential actions (Qwen: 12.9% silent writes, 11 covert).
4. **Gemini-Flash's low say-side scores are an artifact of inaction** — it only
   reads, never writes (0 silent writes, 0 covert), so its say-not-done and
   required-miss are near-zero. Its high ② (43.6%) is purely undisclosed
   *reads*; "honest by doing nothing." Read alongside a task-completion measure,
   not as faithfulness.
5. **Risk ranking** (severity-weighted): Qwen ≫ GPT-4o-mini ≫ DeepSeek-Reasoner ≈
   DeepSeek-Chat ≫ Gemini-Flash (passive).

**One-line answer to RQ1:** Yes — and the *type/severity* of halluci-action,
not its raw rate, is the discriminating signal across models.

---

## Paper framing — RQ1

**RQ1. Do tool-using LLM agents exhibit halluci-action, and how do its
prevalence and severity vary across models?**

*Motivation.* Existing studies of LLM hallucination assess the truthfulness of
generated *text* against world knowledge or provided context. Agentic settings
introduce a distinct and arguably more consequential failure: a mismatch between
an agent's natural-language account of its behavior and the actions it actually
executes through tools. An agent may claim to have completed an operation it
never performed (**say-not-done**, or over-claim), or silently execute a
state-changing operation it never discloses (**did-not-say**, or silent action).
We call these failures **halluci-action**. Because they can directly corrupt
downstream state — records created, orders confirmed, tickets escalated — while
leaving the user's text-level view intact, they pose a risk that
text-faithfulness metrics do not capture. RQ1 asks whether halluci-action is
empirically present in current agents, and whether models differ in how much and
what kind of it they exhibit.

*Finding.* Halluci-action is present in every model we evaluate; none achieves
perfect say–do alignment. The headline over-claim rate, however, is a poor basis
for comparison, because it conflates benign and dangerous failures. Refining
over-claims by the **task-requirement status** of the claimed action exposes two
qualitatively different profiles. The DeepSeek models over-claim at a moderate
rate (3.7–6.7%) but almost exclusively on non-essential actions (required-miss
0.2–0.4%): they occasionally announce an optional check they never run. In
contrast, GPT-4o-mini and Qwen over-claim predominantly on the task's *required*
actions (required-miss ≈9.5%) — they falsely report completing the operations
the task actually demands — and additionally execute consequential actions
silently (Qwen: 12.9% silent state-changing actions, 11 covert violations).
A third pattern, Gemini-Flash's near-zero halluci-action, is an artifact of
inaction: it issues only read operations and executes no state changes, and is
thus "faithful by abstention" rather than by accurate reporting; its scores must
be read alongside task completion. We conclude that **halluci-action is
universal, but its severity and character — not its raw frequency — are the
signals that distinguish models.**
