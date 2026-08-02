# Stage3 Action Annotation UIs

This folder contains several prototype/static HTML views. The most relevant
ones are:

| File | Generator | Use |
| --- | --- | --- |
| `d5_filtered_bipartite_gap_graph.html` | `generate_d5_filtered_bipartite_ui.py` | Current recommended D-5 claim/action graph. Left side only includes stage1 claims with `requires_validation=true` and type `action_intention` or `action_completion`. Use this for the clean action-gap view. |
| `d5_bipartite_gap_graph.html` | `generate_d5_bipartite_ui.py` | Older D-5 bipartite prototype. Left side includes all assistant sentences, so it is noisier and can mix observations/summaries into the graph. |
| `d5_claim_action_gap_ui.html` | `generate_d5_gap_ui.py` | Earlier D-5 non-graph gap inspection UI. Useful for debugging rows, not the main graph. |
| `real_deepseek_action_audit_ui.html` | `summarize_action_audit.py` | Action2Claim audit browser for real DeepSeek chat trajectories. |
| `deepseek_reasoner_action_audit_ui.html` | `summarize_action_audit.py` | Action2Claim audit browser for DeepSeek reasoner trajectories. |
| `openai_gpt_4o_action_audit_ui.html` | `summarize_action_audit.py` | Action2Claim audit browser for GPT-4o trajectories. |
| `annotation_ui.html` | `generate_annotation_ui.py` | Human annotation UI for action-centered labels. |
| `score_ui.html` | `generate_score_ui.py` | Human-vs-judge scoring UI. |

Recommended file for the current D-5 design:

```text
d5_filtered_bipartite_gap_graph.html
```

The older file below is kept for comparison only:

```text
d5_bipartite_gap_graph.html
```
