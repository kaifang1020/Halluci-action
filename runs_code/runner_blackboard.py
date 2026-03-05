import argparse, json, os, time
from datetime import datetime

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

def build_agent(model, role_name, instruction):
    sys = f"""
You are {role_name}.
You will be given a BLACKBOARD (shared state) and the latest observation.
Your job: {instruction}

Output exactly one JSON object:
{{"blackboard_update": "...(a short text to append/overwrite)..."}}
No other text.
"""
    return ChatAgent(system_message=sys, model=model)

def build_executor(model):
    sys = f"""
You are EXECUTOR.
Given BLACKBOARD + latest observation, output exactly one JSON:

{{"tool":"...", "args":{{...}}}}
or
{{"tool":"finish", "result":"..." }}

Tools allowed: {TOOLS}
JSON only.
"""
    return ChatAgent(system_message=sys, model=model)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", choices=["ticket","calendar"], default="ticket")
    ap.add_argument("--max_steps", type=int, default=12)
    ap.add_argument("--log_path", type=str, default="runs/llm_blackboard_log.jsonl")
    args = ap.parse_args()

    model = DeepSeekModel(model_type="deepseek-chat", api_key=DEEPSEEK_API_KEY, url=DEEPSEEK_BASE_URL)

    spec = task_ticket() if args.task == "ticket" else task_calendar()
    env = WorkflowSim(state=spec.init_state.clone(), actor_role=spec.constraints.get("role","worker"))

    writer = build_agent(model, "PM", "summarize the goal, constraints, and acceptance criteria briefly.")
    verifier = build_agent(model, "Verifier", "spot risks, constraints, and propose checks using available tools.")
    strategist = build_agent(model, "Strategist", "propose next best action given current info.")
    executor = build_executor(model)

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    topology_id = "blackboard_roles_pm_verifier_executor"

    log_jsonl(args.log_path, {
        "type":"run_start","run_id":run_id,"topology_id":topology_id,
        "task_id":spec.task_id,"task":{"description":spec.description,"goal":spec.goal,"constraints":spec.constraints},
        "ts":time.time()
    })

    blackboard = {
        "task": spec.description,
        "goal": spec.goal,
        "constraints": spec.constraints,
        "notes": []
    }

    obs = {"ok": True, "note":"Start."}

    for step in range(1, args.max_steps+1):
        context = {"blackboard": blackboard, "observation": obs}

        for agent_name, agent in [("PM", writer), ("Verifier", verifier), ("Strategist", strategist)]:
            out = agent.step(json.dumps(context, ensure_ascii=False)).msg.content
            upd = extract_json(out).get("blackboard_update", "")
            blackboard["notes"].append(f"[{agent_name} step{step}] {upd}")
            log_jsonl(args.log_path, {"type":"bb_update","run_id":run_id,"topology_id":topology_id,
                                      "step":step,"agent":agent_name,"update":upd,"ts":time.time()})

        # executor chooses action
        exec_prompt = {"blackboard": blackboard, "observation": obs}
        out = executor.step(json.dumps(exec_prompt, ensure_ascii=False)).msg.content
        action = extract_json(out)

        log_jsonl(args.log_path, {"type":"turn","run_id":run_id,"topology_id":topology_id,
                                  "step":step,"agent":"EXECUTOR","blackboard":blackboard,
                                  "action":action,"observation_before":obs,"ts":time.time()})

        if action.get("tool") == "finish":
            log_jsonl(args.log_path, {"type":"run_end","run_id":run_id,"topology_id":topology_id,
                                      "finish":True,"step":step,"result":action.get("result",""),"ts":time.time()})
            print(action.get("result",""))
            return

        obs = dispatch(env, action["tool"], action.get("args", {}))
        log_jsonl(args.log_path, {"type":"obs","run_id":run_id,"topology_id":topology_id,
                                  "step":step,"observation":obs,"ts":time.time()})

    log_jsonl(args.log_path, {"type":"run_end","run_id":run_id,"topology_id":topology_id,
                              "finish":False,"reason":"MAX_STEPS","ts":time.time()})
    print("MAX_STEPS reached without finish")

if __name__ == "__main__":
    main()
