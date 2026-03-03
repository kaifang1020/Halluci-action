import argparse
import json
import os
import time
from datetime import datetime

from camel.agents import ChatAgent
from camel.models import DeepSeekModel

from sim_env import WorkflowSim, dispatch
from make_tasks import task_ticket, task_calendar


# ====== 推荐：用环境变量；你也可以直接写在这里（但别提交到 git）======
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "sk-9cde766f76654a45b32e65eadf979d30")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

LOG_PATH = "runs/star_mas_log.jsonl"


TOOLS_SPEC = {
    "ticket.search": {"query": "str"},
    "ticket.get": {"ticket_id": "str"},
    "ticket.update": {"ticket_id": "str", "fields": "dict(priority/assignee/tags/status)"},
    "ticket.comment": {"ticket_id": "str", "text": "str", "author": "str(optional)"},
    "ticket.transition": {"ticket_id": "str", "to_status": "str(OPEN/IN_PROGRESS/RESOLVED/CLOSED)"},
    "cal.freebusy": {"attendees": "list[str]", "start_ts": "int", "end_ts": "int"},
    "cal.create": {"title": "str", "start_ts": "int", "end_ts": "int", "attendees": "list[str]"},
    "cal.reschedule": {"event_id": "str", "start_ts": "int", "end_ts": "int"},
}
ALLOWED_TOOLS = set(TOOLS_SPEC.keys())


def ensure_dir_for_file(path: str):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)


def log_jsonl(path: str, record: dict):
    ensure_dir_for_file(path)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def safe_json_extract(text: str):
    """
    Expect the model to output a single JSON object.
    We'll be forgiving: try to find the first {...} block.
    """
    text = text.strip()
    if text.startswith("{") and text.endswith("}"):
        return json.loads(text)

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(text[start : end + 1])

    raise ValueError("No JSON object found in model output.")


# -----------------------------
# Agents
# -----------------------------
def build_manager(model):
    system = f"""
You are the MANAGER (orchestrator) in a Star multi-agent system.
You decide which worker should take the next action.

Workers:
- ticket_worker: handles ticket tools only
- calendar_worker: handles calendar tools only

You will receive:
- TASK/GOAL/CONSTRAINTS
- latest OBSERVATION from simulator
- optional verifier feedback

You MUST output exactly ONE JSON object:
1) Choose a worker:
{{
  "decision": "delegate",
  "worker": "ticket_worker" | "calendar_worker",
  "instruction": "brief instruction for the worker"
}}

2) Finish:
{{
  "decision": "finish",
  "result": "brief summary"
}}

Rules:
- JSON only. No markdown.
- Pick ticket_worker for ticket.* actions; calendar_worker for cal.* actions.
- If observation shows ok=false, delegate to the most relevant worker to recover.
- Be concise and goal-driven.
"""
    return ChatAgent(system_message=system, model=model)


def build_ticket_worker(model):
    system = f"""
You are TICKET_WORKER. You can ONLY call ticket tools.

You MUST output exactly ONE JSON object each turn:
Tool call:
{{
  "tool": "ticket.search" | "ticket.get" | "ticket.update" | "ticket.comment" | "ticket.transition",
  "args": {{...}}
}}
or Finish:
{{"tool":"finish","result":"..."}}

Rules:
- JSON only. No extra text.
- Use the latest observation to decide next action.
- If you are unsure, call ticket.get first.
- If a tool returns ok=false, recover by fixing args (e.g., ticket_id) or using valid transitions.
Allowed schema:
{json.dumps({k:v for k,v in TOOLS_SPEC.items() if k.startswith("ticket.")}, ensure_ascii=False, indent=2)}
"""
    return ChatAgent(system_message=system, model=model)


def build_calendar_worker(model):
    system = f"""
You are CALENDAR_WORKER. You can ONLY call calendar tools.

You MUST output exactly ONE JSON object each turn:
Tool call:
{{
  "tool": "cal.freebusy" | "cal.create" | "cal.reschedule",
  "args": {{...}}
}}
or Finish:
{{"tool":"finish","result":"..."}}

Rules:
- JSON only. No extra text.
- Use observation to decide next action.
- When TIME_CONFLICT occurs, you should adjust the time window and retry.
Allowed schema:
{json.dumps({k:v for k,v in TOOLS_SPEC.items() if k.startswith("cal.")}, ensure_ascii=False, indent=2)}
"""
    return ChatAgent(system_message=system, model=model)


def build_verifier(model):
    system = f"""
You are VERIFIER. You do NOT call tools.
You audit the latest action+observation and provide a short critique:
- Did the action move toward the goal?
- Any errors (ok=false)? What recovery should be done next?
- Any signs of state desync (agent assumes success when ok=false)?

Output exactly ONE JSON object:
{{
  "verdict": "ok" | "needs_recovery" | "risky",
  "notes": "one short paragraph"
}}

Rules:
- JSON only.
- Be strict about ok=false and goal satisfaction.
"""
    return ChatAgent(system_message=system, model=model)


# -----------------------------
# Prompt builders
# -----------------------------
def manager_input(spec, obs, verifier_feedback):
    payload = {
        "task_description": spec.description,
        "goal": spec.goal,
        "constraints": spec.constraints,
        "last_observation": obs,
        "verifier_feedback": verifier_feedback,
    }
    return json.dumps(payload, ensure_ascii=False)


def worker_input(manager_instruction, obs):
    payload = {
        "manager_instruction": manager_instruction,
        "last_observation": obs,
    }
    return json.dumps(payload, ensure_ascii=False)


def verifier_input(spec, manager_decision, worker_action, obs):
    payload = {
        "goal": spec.goal,
        "manager_decision": manager_decision,
        "worker_action": worker_action,
        "observation": obs,
    }
    return json.dumps(payload, ensure_ascii=False)


# -----------------------------
# Main loop
# -----------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", choices=["ticket", "calendar"], default="ticket")
    ap.add_argument("--max_steps", type=int, default=12)
    ap.add_argument("--role", choices=["worker", "manager"], default=None, help="simulator role (affects permission)")
    ap.add_argument("--log_path", type=str, default=LOG_PATH)
    args = ap.parse_args()

    if not DEEPSEEK_API_KEY or "YOUR_DEEPSEEK_KEY_HERE" in DEEPSEEK_API_KEY:
        raise ValueError("请设置 DEEPSEEK_API_KEY（建议用环境变量），或在代码里替换占位符。")

    model = DeepSeekModel(
        model_type="deepseek-chat",
        api_key=DEEPSEEK_API_KEY,
        url=DEEPSEEK_BASE_URL,
    )

    manager = build_manager(model)
    ticket_worker = build_ticket_worker(model)
    calendar_worker = build_calendar_worker(model)
    verifier = build_verifier(model)

    # Pick a TaskSpec
    spec = task_ticket() if args.task == "ticket" else task_calendar()

    sim_role = args.role or spec.constraints.get("role", "worker")
    env = WorkflowSim(state=spec.init_state.clone(), actor_role=sim_role)

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    topology_id = "star_manager_ticket_calendar_verifier"

    log_jsonl(args.log_path, {
        "type": "run_start",
        "run_id": run_id,
        "topology_id": topology_id,
        "task_id": spec.task_id,
        "task": {
            "description": spec.description,
            "goal": spec.goal,
            "constraints": spec.constraints,
        },
        "sim_role": sim_role,
        "model": {"type": "deepseek-chat", "base_url": DEEPSEEK_BASE_URL},
        "ts": time.time(),
    })

    obs = {"ok": True, "note": "Initial state loaded."}
    verifier_fb = {"verdict": "ok", "notes": "Start."}

    for step in range(1, args.max_steps + 1):
        print(f"\n[step {step}] manager deciding...", flush=True)

        # --- Manager decides ---
        m_out_text = manager.step(manager_input(spec, obs, verifier_fb)).msg.content
        try:
            m_decision = safe_json_extract(m_out_text)
        except Exception as e:
            m_decision = {"decision": "delegate", "worker": "ticket_worker", "instruction": "Output valid JSON only."}
            log_jsonl(args.log_path, {
                "type": "manager_parse_error",
                "run_id": run_id,
                "step": step,
                "raw": m_out_text,
                "error": str(e),
                "ts": time.time(),
            })

        log_jsonl(args.log_path, {
            "type": "manager",
            "run_id": run_id,
            "step": step,
            "raw": m_out_text,
            "decision": m_decision,
            "ts": time.time(),
        })

        if m_decision.get("decision") == "finish":
            result = m_decision.get("result", "")
            log_jsonl(args.log_path, {
                "type": "run_end",
                "run_id": run_id,
                "topology_id": topology_id,
                "finish": True,
                "step": step,
                "result": result,
                "ts": time.time(),
            })
            print("\n========== FINISH ==========\n", flush=True)
            print(result, flush=True)
            print(f"\n[log saved] {args.log_path} (run_id={run_id})", flush=True)
            return

        # --- Delegate to worker ---
        worker = m_decision.get("worker")
        instruction = m_decision.get("instruction", "")

        if worker == "ticket_worker":
            w_agent = ticket_worker
        elif worker == "calendar_worker":
            w_agent = calendar_worker
        else:
            # fallback
            w_agent = ticket_worker
            worker = "ticket_worker"

        print(f"[step {step}] delegated to {worker}", flush=True)

        w_out_text = w_agent.step(worker_input(instruction, obs)).msg.content
        try:
            w_action = safe_json_extract(w_out_text)
        except Exception as e:
            w_action = {"tool": "__invalid__", "error": "INVALID_JSON", "detail": str(e), "raw_output": w_out_text}

        log_jsonl(args.log_path, {
            "type": "worker",
            "run_id": run_id,
            "step": step,
            "worker": worker,
            "instruction": instruction,
            "raw": w_out_text,
            "action": w_action,
            "ts": time.time(),
        })

        # Worker may ask to finish (rare). Manager is the one who should finish, but we support it.
        if w_action.get("tool") == "finish":
            # let manager decide next step; we just record and stop gracefully
            result = w_action.get("result", "")
            log_jsonl(args.log_path, {
                "type": "run_end",
                "run_id": run_id,
                "topology_id": topology_id,
                "finish": True,
                "step": step,
                "result": f"[worker_finish/{worker}] {result}",
                "ts": time.time(),
            })
            print("\n========== FINISH (worker) ==========\n", flush=True)
            print(result, flush=True)
            print(f"\n[log saved] {args.log_path} (run_id={run_id})", flush=True)
            return

        # --- Execute tool action in simulator ---
        tool = w_action.get("tool")
        tool_args = w_action.get("args", {})

        if tool not in ALLOWED_TOOLS:
            obs = {"ok": False, "error": "UNKNOWN_TOOL", "tool": tool, "allowed_tools": sorted(list(ALLOWED_TOOLS))}
        else:
            obs = dispatch(env, tool, tool_args)

        log_jsonl(args.log_path, {
            "type": "env_step",
            "run_id": run_id,
            "step": step,
            "actor": worker,
            "tool": tool,
            "args": tool_args,
            "observation": obs,
            "ts": time.time(),
        })

        print(f"[step {step}] env obs ok={obs.get('ok')} err={obs.get('error')}", flush=True)

        # --- Verifier audits ---
        v_out_text = verifier.step(verifier_input(spec, m_decision, w_action, obs)).msg.content
        try:
            verifier_fb = safe_json_extract(v_out_text)
        except Exception as e:
            verifier_fb = {"verdict": "risky", "notes": f"Verifier JSON parse error: {e}"}

        log_jsonl(args.log_path, {
            "type": "verifier",
            "run_id": run_id,
            "step": step,
            "raw": v_out_text,
            "feedback": verifier_fb,
            "ts": time.time(),
        })

    # Max steps reached
    log_jsonl(args.log_path, {
        "type": "run_end",
        "run_id": run_id,
        "topology_id": topology_id,
        "finish": False,
        "reason": "MAX_STEPS_REACHED",
        "ts": time.time(),
    })
    print("\n[STOP] Reached max_steps without finish.", flush=True)
    print(f"[log saved] {args.log_path} (run_id={run_id})", flush=True)


if __name__ == "__main__":
    main()