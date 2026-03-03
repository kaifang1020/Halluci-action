# python -u runner_star.py --task ticket --max_steps 12 --log_path runs/star_ticket.jsonl
python -u runner_chain.py --task ticket --max_steps 12 --log_path runs/chain_ticket_v2.jsonl
python -u runner_debate.py --task ticket --max_steps 12 --log_path runs/debate_ticket_v2.jsonl
python -u runner_blackboard.py --task ticket --max_steps 12 --log_path runs/blackboard_ticket_v2.jsonl

# python -u runner_star.py --task calendar --max_steps 12 --log_path runs/star_cal.jsonl
python -u runner_chain.py --task calendar --max_steps 12 --log_path runs/chain_cal_v2.jsonl
python -u runner_debate.py --task calendar --max_steps 12 --log_path runs/debate_cal_v2.jsonl
# python -u runner_blackboard.py --task calendar --max_steps 12 --log_path runs/blackboard_cal.jsonl