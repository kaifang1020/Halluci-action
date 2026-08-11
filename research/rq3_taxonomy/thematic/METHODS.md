# Thematic Classification of Halluci-Action Instances — Method Record

Full procedural record for the within-gate thematic classification (RQ3
sub-question). Companion files: `codebook_v0.1.md` (themes, definitions,
exemplars, matrix), `vignettes_c3.md`, and the scripts referenced below.
Everything here was executed on 2026-07-19 by coder-1 (Claude, Fable 5);
validation (Step 4) is pending.

---

## 0. Design rationale

- **Gate layer (C1–C4) is deterministic, not coded.** It is a fixed mapping
  from upstream judge fields (category → gate; see §1), itself a factorization
  of the paper's consistency indicators (¬C1/¬C2/¬C3 decompose the forward
  `Con(c)=0` bit by increasing claim–trace match depth; ¬C4 ≡ `κ(b)=∅`). All
  new judgment happens *inside* gates, so the reliability question is confined
  to the theme layer.
- **Theme layer is inductive, on the antecedent axis.** Existing categories
  answer *what form the failure took* (mechanism). Themes answer *what
  observable event in the trace preceded/triggered it* (antecedent). The two
  axes are deliberately orthogonal; cross-cutting properties (severity,
  requirement_status, claim_type, model, design_induced) stay as separate
  facets and are never baked into theme names — the faceted design is what
  prevents most category overlap.
- **Method label:** hybrid deductive–inductive codebook thematic analysis
  (deductive frame = gates; inductive codes = themes), following the
  taxonomy-development practice of MAST (Cemri et al., 2025): grounded coding
  of traces → codebook → scaled re-application with agreement checks.

## 1. Gate mapping (zero judgment)

| upstream category | gate |
|---|---|
| overclaimed-intent, fabricated-completion | C1 |
| wrong-target | C2 |
| tool-failed-but-claimed, unverified-assumption | C3 |
| undisclosed-read, silent-mutation, covert-forbidden | C4 |
| ambiguous | excluded (1 upstream artifact; coding surfaced 1 more, see §3) |

## 2. Step 1 — Evidence cards (programmatic, no LLM)

`build_evidence_cards.py` → `evidence_cards.jsonl` (736 cards).

- **say-not-done (128):** from `stage2/proposed_requirement/outputs/`
  `not_supported_items.jsonl` — verbatim `claim_span`, ±context sentences,
  routed tool calls; `judge_reason` joined from
  `halluci_action_classified.jsonl` (pool by (model, task_id), 80-char
  claim-prefix match, order fallback; 128/128 matched).
- **did-not-say (608):** rows with `said=false` from the five
  `*_action_audit_enriched.jsonl` files (eval_v3-2 stage 3). Category derived:
  `requirement_status=forbidden` → covert-forbidden; `is_mutation` →
  silent-mutation; else undisclosed-read. Derived counts equal the classified
  counts (17/5/586) exactly.
- Card = verbatim claim (or serialized call) + contradicting trace evidence
  (tool, params, result, step pointers) + ±1-step assistant context +
  judge_reason + metadata facets. All verbatim fields are byte-exact copies —
  every later classification is auditable back to the trajectory.
- **Fix made here:** `assistant_sentences` stores `<reasoning>` content as
  ordinary sentences; the per-step visible-text flag is computed *after*
  stripping `<reasoning>…</reasoning>` spans. (Before the fix,
  deepseek_reasoner's silent steps were miscounted as narrated.)
- The coding view (`print_batch.py`) hides model identity.

## 3. Step 2A — Open coding of the A-track (149 instances)

Scope: C1 (86) + C2 (33) + C3 (8) + C4 writes (covert-forbidden 17,
silent-mutation 5). Batches in file order (no selection), coded by coder-1
blind to model; not fully blind to the pre-existing category labels — mitigated
by coding on the orthogonal antecedent axis (limitation, §7).

**Per-card procedure (three fixed questions):**
1. What exactly was claimed (object, tense)?
2. What does the trace show (matching call? target? result payload)?
3. What observable event precedes/triggers the mismatch? → the antecedent code.
Codes are low-inference: they describe trace-observable events, never mental
states ("forgot", "lied").

**Rolling codebook (constant comparison).** New cards either joined an
existing code or opened one; three kinds of edits occurred and are part of the
method:
- *Merges* — e.g., "missing-tool-proxy" (picking not fetchable) and "tool
  requires customer_id" unified as interface-forced-substitution (C2) /
  capability-gap-workaround (C1): same antecedent, two gates.
- *Precedence rules* for genuine double-fits (see §5).
- *Refusals to open classes* — single-instance outliers stay labeled but do
  not become themes (rationalized-success, n=1).

**Saturation:** the last new C1 theme (terminal-unfulfilled-commitment)
appeared at instance 55/86; no new theme in the final third of any gate.

**Fixation & back-application.** `write_open_codes.py` records every
assignment as explicit index tables and asserts full coverage with no
duplicates (149/149) — the assignment is a machine-verified partition. Output:
`open_codes_coder1.jsonl` (card_id, gate, theme, group, memo, facets).
Because the tables were rewritten against the *final* codebook, this pass is
also the back-application; coder-1's other-rate is structurally 0 (themes were
induced from the same data), so the meaningful other-rate comes from the
independent second coder.

## 4. Step 2B/2C — The two non-coded tracks

**B-track: 586 undisclosed reads, programmatic strata**
(`stratify_c4_reads.py`). Highly homogeneous; forcing 3–5 open-coded themes
would manufacture distinctions. Axis instead = relation between the action and
the visible narration; three rules:
1. judge-reason matches hidden-reasoning phrasing → reasoning-only (a lower
   bound, regex-based);
2. else step has no visible text after reasoning-stripping → silent-step;
3. else → narration-mismatch.
The 3-way scheme was *iterated, not preset*: an initial 4-way version
(outcome-only + residual) collapsed after manual reading of all 52 flagged
cases showed one phenomenon; the regex gained a "reasoning tag(s)" variant.
Final: silent-step 528 / reasoning-only 16 / narration-mismatch 42; residual
0%; all 42 narration-mismatch cases manually confirmed
(`c4_read_narration_mismatch.txt`).

**C-track: C3 (n=8) as vignettes** (`vignettes_c3.md`). Too few for themes;
five labeled case descriptions instead. Analytic note: C3 failures are
shallow-verification failures (envelope vs payload; decorative identity),
not inventions.

## 5. MECE: what is guaranteed at which level

1. **Assignment level — mechanical.** Index-table assertions make the
   assignment a partition of each gate (exhaustive + exclusive by
   construction, machine-checked).
2. **Definition level — by design rules, defensible not provable.**
   (a) One analytic question per gate (C1 themes = fates of the committed
   action — mutually exclusive outcomes); (b) cross-cutting properties
   factored out as facets; (c) explicit precedence rules for real double-fits,
   recorded in the codebook and applied retroactively:
   - dropped check was a pre-write guardrail AND the write executed →
     dropped-guardrail-before-write beats explicit-retraction;
   - intent targets a capability absent from the toolset →
     capability-gap beats displaced-by-alternative;
   - C1/C2 boundary: same operation type executed in scope on a different
     target → C2; operation absent or different → C1.
   (d) each definition carries a nearest-neighbor distinction.
3. **Corpus-external — empirical only.** Exhaustiveness beyond this corpus is
   the "other" bucket's job; its adequacy (forced-other rate) and definitional
   exclusivity (per-pair confusion in κ) are exactly what Step 4 measures.
   Gate-level MECE probe already run: scan for false-denial instances
   (claims of *not* having acted) — 0 found; noted as a theoretical gap.

## 6. Step 3 — Codebook and empirical claims

Every empirical sentence in `codebook_v0.1.md` was computed from
`open_codes_coder1.jsonl` cross-tabs (theme × model, theme ×
requirement_status), e.g.: capability-gap 25/25 deepseek-family;
silent-retry-loop 8/8 deepseek_reasoner; 5/13 explicit retractions withdrew
*forbidden* writes (→ "protective abandonment" finding); guessed-id writes
9/10 qwen. Headline cross-gate finding: blocked-by-environment
(capability-gap 25 + interface-forced 20) = 45/119 genuine claim-anchored
instances (38%), plus 11/22 undisclosed writes on two broken tools —
environment/interface gaps are the largest single root cause.

## 7. Step 4 — Validation protocol (pending) & limitations

- **Human check:** `validation_ui.html` (seed=7): stratified 59 items (≤3 per
  A-track theme = 49; 4/3/3 across read strata = 10), shuffled, blind
  (coder-1 labels only in the export payload). Export → compare against
  `open_codes_coder1.jsonl` → agreement.
- **Second coder (different model family):** input = same card view + frozen
  codebook (definition, nearest-neighbor distinction, exemplars, precedence
  rules); forced choice incl. "other"; output theme + one-line antecedent
  justification. Report Cohen's κ, forced-other rate, per-pair confusion.
  The second coder replicates judgment, not induction — its independence is
  the evidence that the themes are real.
- **Limitations to state:** single primary coder; coder-1 not blind to
  pre-existing categories (mitigated by orthogonal axis); coder-1 other-rate
  is structurally 0; reasoning-only stratum is a regex lower bound; some
  claims live inside hidden `<reasoning>` blocks (counted, flagged — whether
  private deliberation constitutes a commitment deserves an explicit
  scope sentence); C3's rarity may partly reflect fault-tree routing
  (result-mismatch absorbed by C2 when a wrong target explains it first);
  a second extraction artifact was found during coding (C1
  extraction-artifact, judge-flagged stage-1 routing miss) — headline count
  735 → 734 if excluded.

## 8. File map

| file | role |
|---|---|
| build_evidence_cards.py / evidence_cards.jsonl | Step 1: 736 auditable cards |
| print_batch.py | model-blind coding view |
| write_open_codes.py / open_codes_coder1.jsonl | Step 2A: 149 assignments, asserted partition |
| stratify_c4_reads.py / c4_read_strata.tsv / c4_read_assignments.jsonl / c4_read_narration_mismatch.txt | Step 2B: read strata + manual-review record |
| vignettes_c3.md | Step 2C: C3 cases |
| codebook_v0.1.md | Step 3: themes, definitions, exemplars, matrix, findings |
| build_validation_ui.py / validation_ui.html | Step 4: 59-item blind validation sample |

## 9. Paper-ready method paragraph (draft)

> Gate assignment (C1–C4) is deterministic: it factorizes our consistency
> indicators, so no additional judgment is involved. Within each gate we ran a
> hybrid deductive–inductive codebook thematic analysis on the *antecedent*
> axis: every instance was first reduced programmatically to an auditable
> evidence card (verbatim claim, contradicting trace evidence with step
> pointers, local context); a coder blind to model identity then coded each
> card with low-inference antecedent codes under constant comparison,
> resolving double-fits with explicit precedence rules; the resulting themes
> (definitions, nearest-neighbor distinctions, exemplars) were applied back to
> all instances with an explicit "other" option, the assignment being a
> machine-verified partition. The 586 undisclosed reads, near-homogeneous,
> were instead stratified programmatically by the relation between action and
> visible narration (all narrated cases manually reviewed); the eight C3
> instances are reported as case vignettes. A stratified sample of 59
> instances was independently verified by an author (agreement: __%), and the
> frozen codebook was re-applied by a second model family over all 149 coded
> instances (Cohen's κ = __, forced-other rate = __%).
