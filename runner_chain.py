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
    if d:
        os.makedirs(d, exist_ok=True)

def log_jsonl(path, rec):
    ensure_dir(path)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

def extract_json(text: str):
    text = text.strip()
    if text.startswith("{") and text.endswith("}"):
        return json.loads(text)
    s, e = text.find("{"), text.rfind("}")
    if s != -1 and e != -1 and e > s:
        return json.loads(text[s:e+1])
    raise ValueError("No JSON found")

def build_planner(model):
    sys = f"""
You are a PLANNER. You do NOT execute tools.
Given TASK and GOAL, output a plan as a JSON object:

{{
  "plan": [
    {{"tool": "...", "args": {{...}}}},
    ...
  ]
}}

Rules:
- JSON only. No extra text.
- Tools allowed: {TOOLS}
- Plan should be 3~10 steps.
- You may include verification steps (e.g., ticket.get, cal.freebusy) before mutations.
"""
    return ChatAgent(system_message=sys, model=model)

def build_executor(model):
    sys = f"""
You are an EXECUTOR controlling tools in a simulator.
Each turn you MUST output exactly ONE JSON object:

Tool call:
{{"tool":"...", "args":{{...}}}}

or Finish:
{{"tool":"finish", "result":"..." }}

Rules:
- JSON only.
- Tools allowed: {TOOLS}
- Use observation to decide next action.
- If plan step is invalid or observation indicates failure, you MUST adapt (fix args, retry, or replan).
"""
    return ChatAgent(system_message=sys, model=model)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", choices=["ticket","calendar"], default="ticket")
    ap.add_argument("--max_steps", type=int, default=12)
    ap.add_argument("--log_path", type=str, default="runs/llm_chain_log.jsonl")
    args = ap.parse_args()

    model = DeepSeekModel(model_type="deepseek-chat", api_key=DEEPSEEK_API_KEY, url=DEEPSEEK_BASE_URL)
    planner = build_planner(model)
    executor = build_executor(model)

    spec = task_ticket() if args.task == "ticket" else task_calendar()
    env = WorkflowSim(state=spec.init_state.clone(), actor_role=spec.constraints.get("role","worker"))

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    topology_id = "chain_planner_executor"

    log_jsonl(args.log_path, {
        "type":"run_start","run_id":run_id,"topology_id":topology_id,
        "task_id":spec.task_id,"task":{"description":spec.description,"goal":spec.goal,"constraints":spec.constraints},
        "ts":time.time()
    })

    # 1) Planner produces plan once
    plan_prompt = f"TASK:\n{spec.description}\nGOAL:\n{json.dumps(spec.goal, ensure_ascii=False)}"
    plan_out = planner.step(plan_prompt).msg.content
    plan_json = extract_json(plan_out)
    plan = plan_json.get("plan", [])
    log_jsonl(args.log_path, {"type":"plan","run_id":run_id,"topology_id":topology_id,"agent":"PLANNER","plan":plan,"raw":plan_out,"ts":time.time()})

    # 2) Executor runs step-by-step, can deviate from plan
    obs = {"ok": True, "note":"Start executing the plan."}
    plan_idx = 0

    for step in range(1, args.max_steps+1):
        # Suggest next planned step (if any) to the executor
        suggested = plan[plan_idx] if plan_idx < len(plan) else None
        prompt = {
            "observation": obs,
            "suggested_plan_step": suggested,
            "remaining_plan_steps": max(0, len(plan)-plan_idx),
        }

        out = executor.step(json.dumps(prompt, ensure_ascii=False)).msg.content
        action = None
        try:
            action = extract_json(out)
        except Exception as e:
            obs = {"ok": False, "error":"INVALID_JSON", "detail":str(e), "raw_output":out}
            log_jsonl(args.log_path, {"type":"turn","run_id":run_id,"topology_id":topology_id,"step":step,
                                      "agent":"EXECUTOR","action_parse_ok":False,"raw_output":out,"observation":obs,"ts":time.time()})
            continue

        if action.get("tool") == "finish":
            log_jsonl(args.log_path, {"type":"run_end","run_id":run_id,"topology_id":topology_id,"finish":True,
                                      "step":step,"result":action.get("result",""),"ts":time.time()})
            print(action.get("result",""))
            return

        tool = action.get("tool")
        tool_args = action.get("args", {})
        obs = dispatch(env, tool, tool_args)

        # if executor followed suggested step, advance plan index; otherwise it deviated
        followed = (suggested == {"tool": tool, "args": tool_args}) if suggested else False
        if followed:
            plan_idx += 1

        log_jsonl(args.log_path, {"type":"turn","run_id":run_id,"topology_id":topology_id,"step":step,
                                  "agent":"EXECUTOR","suggested":suggested,"followed_suggested":followed,
                                  "action":action,"observation":obs,"ts":time.time()})

    log_jsonl(args.log_path, {"type":"run_end","run_id":run_id,"topology_id":topology_id,"finish":False,
                              "reason":"MAX_STEPS","ts":time.time()})
    print("MAX_STEPS reached without finish")

if __name__ == "__main__":
    main()