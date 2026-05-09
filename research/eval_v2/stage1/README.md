# Eval V2 Stage 1: Claim Extraction

Stage 1 extracts atomic claims from each step's `assistant_text`.

It does **not** validate claims. It should not assign validation scope, gold
status, error type, severity, evidence, or human notes. Those belong to later
stages.

## Goal

Input:
- one raw trajectory JSON
- Stage 1 claim extraction guideline
- Stage 1 examples

Output:
- a structured JSON claim list
- a Markdown rendering for human review
- the exact prompt sent to the LLM

## Stage 1 Fields

Each extracted claim has only:

- `claim`
- `type`
- `requires_validation`

The script adds stable claim IDs such as `S2-S3-C4` after parsing model output.

## Files

- `claim_extraction_guideline.md`: extraction-only rules.
- `examples/stage1_examples.md`: human-annotation examples projected into Stage 1 format.
- `prompt.md`: prompt template used to ask the LLM for extraction.
- `extract.py`: builds the prompt, optionally calls an OpenAI-compatible API, and writes JSON/Markdown outputs.
- `render_md.py`: renders Stage 1 JSON into the familiar annotation-like Markdown view.
- `validate_output.py`: validates the Stage 1 JSON schema.

## Suggested First Test

Generate a prompt without calling an API:

```bash
python research/eval_v2/stage1/extract.py \
  --trajectory research/experiments/independent_non_p_m_pr_20260427T074902Z/sales/S-2/20260427T075729Z_deepseek_watanabe_mei_from_corporate_wants_5_dyson_v15_de.json \
  --dry-run
```

After an API call is configured, review:

- `outputs/md/<task_id>.md`: claim extraction result for humans.
- `outputs/json/<task_id>.json`: canonical Stage 1 output for Stage 2.
- `outputs/prompts/<task_id>.md`: full prompt used for reproducibility.

## Batch Mode

Create a target set like `target_set.example.json`:

```json
[
  {
    "task_id": "S-2",
    "raw_path": "research/experiments/.../S-2/file.json",
    "output_stem": "S-2"
  }
]
```

Generate prompts only:

```bash
python research/eval_v2/stage1/extract.py \
  --target-set research/eval_v2/stage1/target_set.example.json \
  --dry-run
```

Run the model:

```bash
python research/eval_v2/stage1/extract.py \
  --target-set research/eval_v2/stage1/target_set.example.json \
  --model "$STAGE1_MODEL" \
  --continue-on-error
```

The script automatically loads project-root `.env` if it exists. You can put:

```bash
STAGE1_API_KEY=...
STAGE1_BASE_URL=...
STAGE1_MODEL=...
```

in `.env` and then run the script without manually sourcing the file.

Useful flags:
- `--overwrite`: replace existing outputs.
- `--limit N`: process only the first N targets.
- `--continue-on-error`: save per-target errors and continue the batch.
