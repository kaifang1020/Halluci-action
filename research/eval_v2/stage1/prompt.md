# Stage 1 Claim Extraction

You are a Stage 1 claim extraction annotator for claim-action alignment
research.

Your only job is to extract atomic claims from each step's `assistant_text`.

Do not validate claims. Do not inspect tool calls or tool results to decide
whether claims are true. Do not assign validation scope, gold status, error
type, severity, evidence, or human notes.

## Claim Extraction Guideline

{{CLAIM_EXTRACTION_GUIDELINE}}

## Human Annotation Examples Projected To Stage 1

{{STAGE1_EXAMPLES}}

## Target Assistant Text View

{{TARGET_ASSISTANT_TEXT_VIEW}}

## Output Requirements

Return valid JSON only. Do not wrap the JSON in Markdown fences.

Use this schema:

```json
{
  "task_id": "string",
  "trajectory_file": "string",
  "steps": [
    {
      "step_id": 1,
      "source": "assistant_text for this step",
      "claims": [
        {
          "claim": "normalized atomic claim fragment",
          "type": "action_intention | action_completion | observation | reasoning_conclusion | constraint_or_policy | recommendation | non_actionable_text"
        }
      ]
    }
  ]
}
```

Important:
- Do not generate `claim_id`, `requires_validation`, or `validation_scope`; the script adds these automatically.
- Preserve step order.
- Include a step with an empty `claims` list if the step has no assistant text or no extractable claims.
- For tables, prefer one claim per business record row rather than one claim per column.
- Include entity anchors needed for validation, such as product ID, customer ID, invoice/order/ticket number, source/destination role, and location ID/name.
- Every stock quantity claim must include the product identifier and the location identifier/name in the claim text itself.
