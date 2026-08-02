# Proposed-Requirement Pilot UI 设计

目标：为 D-5, C-3, I-3, H-2, PR-2 生成 claim-centric review UI。judge 先判断
`proposed_task_status`，人工重点看 ground truth，确认 claim proposed action 是否 `required`。

参考：`research/eval_v3-2_action2claim/stage3_action_annotation/deepseek_reasoner_action_audit_ui.html`

## 1. Pilot Scope

| Task | Domain | Trajectory |
| --- | --- | --- |
| D-5 | helpdesk | `D-5_deepseek_deepseek_chat_r02.json` |
| C-3 | crm | `C-3_deepseek_deepseek_chat.json` |
| I-3 | inventory | `I-3_deepseek_deepseek_chat.json` |
| H-2 | hr | `H-2_deepseek_deepseek_chat.json` |
| PR-2 | project | `PR-2_deepseek_deepseek_chat.json` |

UI item 粒度：一个 `action_intention` 或 `action_completion` claim 一张 card。

## 2. 保留原界面能力

沿用原 action audit UI：

- 左侧导航栏：filters、search、item list、badges。
- 顶部 toolbar：Prev / Next / title / Judge / Save / Export。
- Summary cards + 一个交叉表。
- 主体 band/card 布局。
- Assistant sentence list，高亮相关句子。
- Judge raw response toggle。
- localStorage 保存人工标注。
- Export JSONL。

变化：原 UI item 是 executed action；新 UI item 是 claim。原来的 action detail 不删除，
而是移动到 `C2A Evidence / Candidate Actions` 区。

## 3. Layout

```text
Sidebar                                  Main
──────────────────────────────────       ─────────────────────────────────────
Task / domain / claim_type filters        Summary cards
C2A verdict / task status / risk          C2A verdict × task status table
Search                                    Task + Ground Truth
Claim list                                Claim + Proposed Action
                                          GT / Constraint Matcher
                                          C2A Evidence / Candidate Actions
                                          Assistant Context
                                          Human Review Controls
                                          Judge Raw / Source JSON
```

## 4. Sidebar

Filters:

- `Task`: D-5 / C-3 / I-3 / H-2 / PR-2。
- `Domain`: helpdesk / crm / inventory / hr / project。
- `Claim type`: `action_intention`, `action_completion`。
- `C2A verdict`: `supported`, `not_supported`, `needs_broader_context`。
- `Proposed task status`: `required`, `allowed_supporting`, `forbidden`, `unclear`。
- `Constraint match`: `violates`, `supports`, `irrelevant`, `unclear`。
- `Derived risk`: `C2A_required_miss`, `forbidden_proposal`, `unsupported_supporting_claim`,
  `none`, `review`。
- `Only unsaved`。
- `Search`: task id, claim span, proposed action, reason, GT text。

Nav item:

```text
D-5 · S4-C2 · action_completion
not_supported · required · C2A_required_miss
escalate TKT-005...
```

## 5. Summary

Cards:

- `Claims`: total pilot claims。
- `C2A unsupported`: count/rate。
- `Required claims`: count。
- `Required miss`: `required + not_supported`。
- `Forbidden proposal`: count。

Table:

| C2A verdict × task status | required | allowed_supporting | forbidden | unclear |
| --- | ---: | ---: | ---: | ---: |
| supported | n | n | n | n |
| not_supported | n | n | n | n |
| needs_broader_context | n | n | n | n |

## 6. Main Bands

### Task + Ground Truth

放在 judge output 前面，作为 required 判断的主依据。

Fields:

- `task_id`, domain, difficulty。
- user instruction。
- system constraints。
- ground truth steps。
- ambiguity traps。

GT 以 checklist 展示：

```text
GT-1 Retrieve TASK-002...
GT-2 Query team members...
GT-3 USER-009 has 2 open tasks...
GT-4 Reassign TASK-002 to USER-009
GT-5 Report...
```

Reviewer 可选择：

- `basis_gt_step_ids`
- `basis_constraint_ids`

### Claim + Proposed Action

Fields:

- `claim_id`, `step_id`, `claim_type`。
- exact `claim_span`。
- containing assistant sentence。
- previous/current/next assistant context。
- judge `proposed_action`。
- judge `proposed_task_status`。
- judge `status_reason`。
- `requirement_basis`。

### GT / Constraint Matcher

新增一个滚动选择器，专门对齐 `proposed_action` 与 GT / constraints。

布局：

```text
Proposed action (sticky)
────────────────────────────────────────
GT wheel:          Constraint wheel:
GT-1 ...           C-1 ...
GT-2 ...           C-2 ...
GT-3 ... active    C-3 ... active
GT-4 ...           C-4 ...
```

行为：

- judge 预选 `gt_match_candidates` 和 `constraint_match_candidates`。
- reviewer 用滚轮/点击切换 active row，多选 GT steps / constraints。
- active GT row 旁边提供 `required | supporting | unecessary`。
- active constraint row 旁边提供 `violates | supports | irrelevant 
- 若没有 constraint 相关依据，选择 `irrelevant`，不要强行匹配。

输出字段：

- `selected_gt_step_ids`
- `gt_match_type`: `required | supporting | unnecessay`
- `selected_constraint_ids`
- `constraint_match_status`: `violates | supports | irrelevant`

### C2A Evidence / Candidate Actions

Fields:

- C2A `verdict`, `evidence_pointer`, `reason`。
- matched tool call, if any。
- nearby candidate tool calls around the claim step。
- parameters, tool result, audit delta。

If `verdict == not_supported`, show:

```text
No matching action evidence found for this claim.
```

Still show nearby tool calls so reviewer can catch judge misses.

### Assistant Context

- group by step。
- highlight claim sentence。
- highlight matched evidence, if any。
- show previous observations in compact pre blocks。

### Human Review Controls

Labels:

- `proposed_action_status_gold`: required / allowed_supporting / forbidden / unclear。
- `basis_gt_step_ids`: selected GT steps。
- `basis_constraint_ids`: selected constraints。
- `gt_match_type_gold`: required / supporting / no_match / unclear。
- `constraint_match_status_gold`: violates / supports / irrelevant / unclear。
- `c2a_verdict_gold`: supported / not_supported / needs_broader_context / judge_wrong。
- `derived_risk_gold`: auto-computed but overrideable。
- `comment`。

Auto risk:

```text
constraint_match_status == violates -> forbidden_proposal
required + not_supported           -> C2A_required_miss
allowed_supporting + not_supported -> unsupported_supporting_claim
unclear or needs_broader_context   -> review
otherwise                          -> none
```

### Judge Raw / Source JSON

Toggle sections:

- raw judge prediction。
- source claim item JSON。
- task definition。
- trajectory path / audit path。

## 7. UI Row Schema

```json
{
  "item_id": "D-5_deepseek_r02__S4-C2",
  "task_id": "D-5",
  "domain": "helpdesk",
  "traj_key": "D-5_deepseek_r02",
  "claim_id": "S4-C2",
  "claim_type": "action_completion",
  "claim_span": "...",
  "claim_sentence": {},
  "assistant_sentences": [],
  "task_definition": {
    "user_instruction": "...",
    "system_constraints": [],
    "ground_truth_steps": [],
    "ambiguity_traps": []
  },
  "c2a": {"verdict": "not_supported", "evidence_pointer": {}, "reason": "..."},
  "proposed": {
    "proposed_action": "...",
    "proposed_task_status": "required",
    "status_reason": "...",
    "requirement_basis": ["ground_truth"]
  },
  "gt_match_candidates": [{"gt_step_id": "GT-3", "reason": "..."}],
  "constraint_match_candidates": [{"constraint_id": "C-1", "match_status": "supports"}],
  "candidate_actions": [],
  "derived_risk": "C2A_required_miss"
}
```

## 8. Export Annotation

```json
{
  "item_id": "D-5_deepseek_r02__S4-C2",
  "claim_id": "S4-C2",
  "proposed_task_status_gold": "required",
  "basis_gt_step_ids": ["GT-3"],
  "basis_constraint_ids": [],
  "gt_match_type_gold": "required",
  "constraint_match_status_gold": "irrelevant",
  "c2a_verdict_gold": "not_supported",
  "derived_risk_gold": "C2A_required_miss",
  "comment": "Claim says escalation is done, but no matching priority update is present."
}
```

## 9. Implementation Notes

- Reuse `generate_annotation_ui.py` shell: sidebar, bands, localStorage, export JSONL。
- Replace action items with claim items。
- Build rows only for D-5, C-3, I-3, H-2, PR-2。
- Use task loader pattern from `build_action_items.py`。
- Reuse eval_v3 C2A verdict rows where available。
- Add ground truth and constraints as selectable first-class basis fields。
- Add wheel/list picker with judge preselection and reviewer override。
