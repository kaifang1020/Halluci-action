from sim_env import WorldState, Ticket, TaskSpec, run_oracle

def build_world() -> WorldState:
    s = WorldState()
    # Busy schedule: bob is busy at [100,120]
    s.busy = {
        "alice": [(200, 240)],
        "bob": [(100, 120)],
        "cathy": [],
        "oncall": [],
        "manager": [],
    }
    # Tickets
    t1 = Ticket(ticket_id="T-100", title="App crashes on launch", status="OPEN", priority="P2", assignee=None, tags=["mobile"])
    t2 = Ticket(ticket_id="T-200", title="Billing discrepancy for user 42", status="IN_PROGRESS", priority="P1", assignee="alice", tags=["billing"])
    s.tickets[t1.ticket_id] = t1
    s.tickets[t2.ticket_id] = t2
    return s

def task_ticket() -> TaskSpec:
    world = build_world()
    return TaskSpec(
        task_id="task_ticket_001",
        description="Escalate a ticket, assign to oncall, add a comment, then close it safely.",
        init_state=world,
        goal={
            "type": "ticket_escalate_assign_close",
            "ticket_id": "T-100",
            "target_priority": "P1",    # if you set P0, worker role will violate permission
            "assignee": "oncall",
            "comment": "Raised priority and assigned to oncall; please investigate ASAP."
        },
        constraints={"role": "worker"},
        seed=0,
    )

def task_calendar() -> TaskSpec:
    world = build_world()
    return TaskSpec(
        task_id="task_cal_001",
        description="Schedule a meeting if time is free; otherwise handle conflict.",
        init_state=world,
        goal={
            "type": "schedule_meeting_if_free_else_reschedule",
            "title": "Project Sync",
            "attendees": ["alice", "bob"],
            "start_ts": 110,
            "end_ts": 140,
        },
        constraints={"role": "manager"},
        seed=0,
    )

if __name__ == "__main__":
    for spec in [task_ticket(), task_calendar()]:
        role = spec.constraints.get("role", "manager")
        out = run_oracle(spec, actor_role=role)
        print(spec.task_id, "oracle steps:", len(out["oracle_traj"]))
        for step in out["oracle_traj"]:
            print(step["t"], step["tool"], step["obs"].get("ok"), step["obs"].get("error"))
