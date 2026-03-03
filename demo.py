import json
import time
from datetime import datetime
from camel.agents import ChatAgent
from camel.models import DeepSeekModel

# ====== 直接写在代码里（别提交到 git）======
DEEPSEEK_API_KEY = "sk-9cde766f76654a45b32e65eadf979d30"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"

LOG_PATH = "/gpfsnyu/scratch/km6704/Agent/camel_agent/demo_log.jsonl"  

def log_jsonl(record: dict):
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

def main():
    if not DEEPSEEK_API_KEY or "你的key" in DEEPSEEK_API_KEY:
        raise ValueError("请在 demo.py 里把 DEEPSEEK_API_KEY 改成你自己的真实 key。")

    model = DeepSeekModel(
        model_type="deepseek-chat",
        api_key=DEEPSEEK_API_KEY,
        url=DEEPSEEK_BASE_URL,
    )

    pm = ChatAgent(
        system_message="You are a product manager. Reply in Chinese.",
        model=model,
    )
    eng = ChatAgent(
        system_message="You are a software engineer. Reply in Chinese.",
        model=model,
    )

    # 确保 runs 目录存在
    import os
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    task = (
        "我们要做一个给大学生用的学习番茄钟 App。"
        "请输出：核心功能、非目标、边界条件、验收标准（可测试）、以及开放问题。"
        "尽量结构化。"
    )

    # 记录 run 的元信息
    log_jsonl({
        "type": "run_start",
        "run_id": run_id,
        "ts": time.time(),
        "task": task,
        "model": {"type": "deepseek-chat", "base_url": DEEPSEEK_BASE_URL},
    })

    msg = task
    rounds = 3

    for r in range(1, rounds + 1):
        # PM step
        pm_in = msg
        pm_resp = pm.step(pm_in)
        pm_out = pm_resp.msg.content

        log_jsonl({
            "type": "turn",
            "run_id": run_id,
            "round": r,
            "agent": "PM",
            "input": pm_in,
            "output": pm_out,
            "ts": time.time(),
        })

        # ENG step
        eng_in = pm_out
        eng_resp = eng.step(eng_in)
        eng_out = eng_resp.msg.content

        log_jsonl({
            "type": "turn",
            "run_id": run_id,
            "round": r,
            "agent": "ENG",
            "input": eng_in,
            "output": eng_out,
            "ts": time.time(),
        })

        msg = eng_out  # 下一轮继续

    # 记录最终结果
    log_jsonl({
        "type": "run_end",
        "run_id": run_id,
        "ts": time.time(),
        "final_output": msg,
    })

    print("\n========== Final Output ==========\n")
    print(msg)
    print(f"\n[Saved multi-turn log] {LOG_PATH} (run_id={run_id})")

if __name__ == "__main__":
    main()