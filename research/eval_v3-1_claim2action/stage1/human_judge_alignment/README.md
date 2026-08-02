# Stage 1 Human-Judge Alignment

Measures how well the stage1 judge's atomic claim extraction matches human gold annotations across 4 trajectories (C-1, D-5_r02, H-2, PR-2).

## Metrics (all at claim level)

- **Span Recall** = matched / gold claims  
  How many of the human-annotated claims did the judge successfully extract?

- **Span Precision** = matched / judge claims  
  Of the claims the judge extracted, how many are actually valid (not spurious)?

- **Type Accuracy** = correct_types / matched claims  
  Among the matched claims, how often is the claim type classification correct?

## Matching Algorithm

1. **Compute token overlap** for every (gold_claim, judge_claim) pair:
   ```
   overlap = |tokens(gold) ∩ tokens(judge)| / min(|tokens(gold)|, |tokens(judge)|)
   ```

2. **Greedy bipartite matching**: Sort all pairs by overlap (descending), greedily pick the highest-scoring pair that hasn't been used yet.

3. **Apply threshold**: A pair is "matched" only if `overlap >= MATCH_THRESHOLD` (currently **0.80**).

4. **Count**: 
   - Matched claims = successfully extracted
   - Unmatched gold = missed claims  
   - Unmatched judge = spurious claims

## Results (Threshold = 0.80)

| Trajectory | N_gold | N_judge | Matched | Recall | Precision | Type Acc | F1 |
|---|---|---|---|---|---|---|---|
| C-1 | 44 | 43 | 41 | 0.932 | 0.953 | 0.902 | 0.943 |
| D-5_r02 | 50 | 48 | 46 | 0.920 | 0.958 | 0.957 | 0.939 |
| H-2 | 14 | 14 | 14 | 1.000 | 1.000 | 0.929 | 1.000 |
| PR-2 | 53 | 54 | 52 | 0.981 | 0.963 | 0.865 | 0.972 |
| **Macro avg** | | | | **0.958** | **0.969** | **0.913** | **0.963** |

### Per-Type Recall (what fraction of each claim type the judge found)

| Type | N_gold | Matched | Recall |
|---|---|---|---|
| observation | 61 | 55 | 0.902 |
| action_intention | 54 | 53 | 0.981 |
| reasoning_conclusion | 19 | 18 | 0.947 |
| non_actionable_text | 12 | 12 | 1.000 |
| action_completion | 11 | 11 | 1.000 |
| constraint_or_policy | 3 | 3 | 1.000 |
| recommendation | 1 | 1 | 1.000 |

### Type Confusion (rows=gold, cols=judge; only matched pairs shown)

The main confusion is **observation → reasoning_conclusion** (4 cases) where the judge categorizes an observation as a reasoning conclusion. This reflects genuine boundary ambiguity between these two categories.

## Files

- `compute_alignment.py` — main computation script
- `results_all.json` — full per-trajectory, per-step, per-pair results with all overlap and match details
- `README.md` — this file

## Usage

```bash
# Run on all 4 trajectories
python3 -m research.eval_v3-1_claim2action.stage1.human_judge_alignment.compute_alignment

# Run on a single trajectory with verbose output (shows missed/spurious/type_errors)
python3 -m research.eval_v3-1_claim2action.stage1.human_judge_alignment.compute_alignment \
    --traj C-1_deepseek --verbose

# Change threshold (default 0.80)
python3 -m research.eval_v3-1_claim2action.stage1.human_judge_alignment.compute_alignment \
    --threshold 0.50

# Save results to custom file
python3 -m research.eval_v3-1_claim2action.stage1.human_judge_alignment.compute_alignment \
    --save-json my_results.json
```

## Key Findings

1. **High extraction quality**: Judge achieves 95.8% recall and 96.9% precision on span extraction.
2. **Type classification is the main source of error**: 91.3% type accuracy. Confusion is primarily between `observation` and `reasoning_conclusion`.
3. **Observation type is hardest**: Only 90.2% recall on observation; other types are 94.7%+.
4. **No spurious mutations**: All mutation claims were correctly extracted with high confidence.

## Implementation Notes

- All matched claims in the dataset have overlap = 1.0 (identical token sets), so threshold choice (50%, 80%, 90%) doesn't affect results in practice. Threshold set to 80% for future robustness.
- Judge uses extractive prompting (span directly from assistant_text), ensuring high similarity to gold annotations.
