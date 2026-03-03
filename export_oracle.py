import json
from Agent.camel_agent.make_tasks import task_ticket, task_calendar
from sim_env import run_oracle

specs = [task_ticket(), task_calendar()]
out = []
for spec in specs:
    role = spec.constraints.get("role", "manager")
    r = run_oracle(spec, actor_role=role)
    # 只保存可 json 序列化部分（state 太大先不存）
    out.append({
        "task_id": spec.task_id,
        "description": spec.description,
        "goal": spec.goal,
        "constraints": spec.constraints,
        "oracle_traj": r["oracle_traj"],
    })

with open("oracle_examples.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)

print("saved oracle_examples.json")