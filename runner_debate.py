import argparse, json, os, time
from datetime import datetime
from collections import Counter

from camel.agents import ChatAgent
from camel.models import DeepSeekModel

from sim_env import WorkflowSim, dispatch
from make_tasks import task_ticket, task_calendar

DEEPSEEK_API_KEY = "sk-9cde766f76654a45b32e65eadf979d30"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"

TOOLS = [
    "ticket.search","ticket.get","ticket.update","ticket.comment","ticket.transition",
    "cal.freebusy","cal.create","cal.reschedule"
]

def ensure_dir(path):
    d = os.path.dirname(path)
    if d: os.makedirs(d, exist_ok=True)

def log_jsonl(path, rec):
    ensure_dir(path)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

def extract_json(text):
    text = text.strip()
    if text.startswith("{") and text.endswith("}"):
        return json.loads(text)
    s, e = text.find("{"), text.rfind("}")
    if s != -1 and e != -1 and e > s:
        return json.loads(text[s:e+1])
    raise ValueError("No JSON found")

def build_planner(model, name):
    sys = f"""
You are {name}, a planner proposing the NEXT SINGLE tool action.
Output exactly one JSON object:

{{"tool":"...", "args":{{...}}}}
or
{{"tool":"finish", "result":"..." }}

Rules:
- JSON only.
- Tools allowed: {TOOLS}
- Base your action on the latest observation.
"""
    return ChatAgent(system_message=sys, model=model)

def vote(actions):
    # vote by exact JSON string
    strs = [json.dumps(a, sort_keys=True, ensure_ascii=False) for a in actions]
    c = Counter(strs)
    winner_str, _ = c.most_common(1)[0]
    return json.loads(winner_str)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", choices=["ticket","calendar"], default="ticket")
    ap.add_argument("--max_steps", type=int, default=12)
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--log_path", type=str, default="runs/llm_debate_log.jsonl")
    args = ap.parse_args()

    model = DeepSeekModel(model_type="deepseek-chat", api_key=DEEPSEEK_API_KEY, url=DEEPSEEK_BASE_URL)

    planners = [build_planner(model, f"PLANNER_{i+1}") for i in range(args.k)]

    spec = task_ticket() if args.task == "ticket" else task_calendar()
    env = WorkflowSim(state=spec.init_state.clone(), actor_role=spec.constraints.get("role","worker"))

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    topology_id = f"debate_vote_k{args.k}"

    log_jsonl(args.log_path, {
        "type":"run_start","run_id":run_id,"topology_id":topology_id,
        "task_id":spec.task_id,"task":{"description":spec.description,"goal":spec.goal,"constraints":spec.constraints},
        "ts":time.time()
    })

    obs = {"ok": True, "note":"Start."}
    for step in range(1, args.max_steps+1):
        prompt = {
            "task": {"description": spec.description, "goal": spec.goal},
            "observation": obs
        }

        candidates = []
        raws = []
        for i, p in enumerate(planners):
            out = p.step(json.dumps(prompt, ensure_ascii=False)).msg.content
            raws.append(out)
            try:
                candidates.append(extract_json(out))
            except Exception as e:
                candidates.append({"tool":"__invalid__", "error": str(e), "raw": out})

        # choose action
        valid = [c for c in candidates if c.get("tool") in TOOLS or c.get("tool") == "finish"]
        chosen = vote(valid) if valid else {"tool":"finish", "result":"No valid action produced."}

        log_jsonl(args.log_path, {
            "type":"turn","run_id":run_id,"topology_id":topology_id,"step":step,
            "candidates": candidates, "chosen": chosen, "observation_before": obs, "ts": time.time()
        })

        if chosen.get("tool") == "finish":
            log_jsonl(args.log_path, {"type":"run_end","run_id":run_id,"topology_id":topology_id,"finish":True,
                                      "step":step,"result":chosen.get("result",""),"ts":time.time()})
            print(chosen.get("result",""))
            return

        obs = dispatch(env, chosen["tool"], chosen.get("args", {}))
        log_jsonl(args.log_path, {
            "type":"obs","run_id":run_id,"topology_id":topology_id,"step":step,
            "observation": obs, "ts": time.time()
        })

    log_jsonl(args.log_path, {"type":"run_end","run_id":run_id,"topology_id":topology_id,"finish":False,
                              "reason":"MAX_STEPS","ts":time.time()})
    print("MAX_STEPS reached without finish")

if __name__ == "__main__":
    main()