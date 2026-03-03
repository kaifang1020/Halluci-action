from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple
import time
import uuid
import copy


# -----------------------------
# Data Models
# -----------------------------
@dataclass
class Ticket:
    ticket_id: str
    title: str
    status: str = "OPEN"          # OPEN / IN_PROGRESS / RESOLVED / CLOSED
    priority: str = "P2"          # P0 / P1 / P2 / P3
    assignee: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    comments: List[Dict[str, Any]] = field(default_factory=list)
    history: List[Dict[str, Any]] = field(default_factory=list)

@dataclass
class Event:
    event_id: str
    title: str
    start_ts: int
    end_ts: int
    attendees: List[str]
    location: str = "online"

@dataclass
class WorldState:
    tickets: Dict[str, Ticket] = field(default_factory=dict)
    events: Dict[str, Event] = field(default_factory=dict)
    users: List[str] = field(default_factory=lambda: ["alice", "bob", "cathy", "oncall", "manager"])
    # Busy map: user -> list[(start_ts, end_ts)]
    busy: Dict[str, List[Tuple[int, int]]] = field(default_factory=dict)

    def clone(self) -> "WorldState":
        return copy.deepcopy(self)


# -----------------------------
# Simulator / Environment
# -----------------------------
class ActionError(Exception):
    pass


class WorkflowSim:
    """
    A toy-but-structured ticket+calendar simulator for action hallucination research.
    - Deterministic if you keep initial state fixed.
    - Provides tool-like actions and structured observations.
    """

    # Ticket status transition graph (strict)
    _ALLOWED_TRANSITIONS = {
        "OPEN": {"IN_PROGRESS", "CLOSED"},  # allow direct close for trivial tickets
        "IN_PROGRESS": {"RESOLVED", "OPEN"},  # "OPEN" here acts like REOPEN
        "RESOLVED": {"CLOSED", "IN_PROGRESS"},
        "CLOSED": {"OPEN"},  # reopen only
    }

    def __init__(self, state: WorldState, actor_role: str = "worker"):
        """
        actor_role: "worker" or "manager"
        """
        self.state = state
        self.actor_role = actor_role
        self.step_count = 0

    # ---- Helpers ----
    def _ts(self) -> float:
        return time.time()

    def _log_ticket(self, t: Ticket, action: str, args: Dict[str, Any], ok: bool, error: Optional[str] = None):
        t.history.append({
            "ts": self._ts(),
            "action": action,
            "args": args,
            "ok": ok,
            "error": error,
        })

    def _overlaps(self, a: Tuple[int, int], b: Tuple[int, int]) -> bool:
        return not (a[1] <= b[0] or b[1] <= a[0])

    # -----------------------------
    # Ticket Tools
    # -----------------------------
    def ticket_search(self, query: str) -> Dict[str, Any]:
        self.step_count += 1
        q = query.lower().strip()
        hits = []
        for tid, t in self.state.tickets.items():
            if q in t.title.lower() or q in tid.lower() or any(q in tag.lower() for tag in t.tags):
                hits.append(tid)
        return {"ok": True, "tool": "ticket.search", "hits": hits}

    def ticket_get(self, ticket_id: str) -> Dict[str, Any]:
        self.step_count += 1
        t = self.state.tickets.get(ticket_id)
        if not t:
            return {"ok": False, "tool": "ticket.get", "error": "TICKET_NOT_FOUND", "ticket_id": ticket_id}
        return {"ok": True, "tool": "ticket.get", "ticket": asdict(t)}

    def ticket_update(self, ticket_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
        self.step_count += 1
        t = self.state.tickets.get(ticket_id)
        if not t:
            return {"ok": False, "tool": "ticket.update", "error": "TICKET_NOT_FOUND", "ticket_id": ticket_id}

        # Permission: only manager can set P0
        if "priority" in fields:
            new_p = fields["priority"]
            if new_p == "P0" and self.actor_role != "manager":
                self._log_ticket(t, "ticket.update", fields, False, "PERMISSION_DENIED_P0")
                return {"ok": False, "tool": "ticket.update", "error": "PERMISSION_DENIED_P0"}

        # Apply allowed fields
        for k in ["priority", "assignee", "tags", "status"]:
            if k in fields:
                setattr(t, k, fields[k])

        self._log_ticket(t, "ticket.update", fields, True)
        return {"ok": True, "tool": "ticket.update", "ticket": asdict(t)}

    def ticket_comment(self, ticket_id: str, text: str, author: str = "agent") -> Dict[str, Any]:
        self.step_count += 1
        t = self.state.tickets.get(ticket_id)
        if not t:
            return {"ok": False, "tool": "ticket.comment", "error": "TICKET_NOT_FOUND", "ticket_id": ticket_id}

        t.comments.append({"ts": self._ts(), "author": author, "text": text})
        self._log_ticket(t, "ticket.comment", {"text": text, "author": author}, True)
        return {"ok": True, "tool": "ticket.comment", "ticket_id": ticket_id}

    def ticket_transition(self, ticket_id: str, to_status: str) -> Dict[str, Any]:
        self.step_count += 1
        t = self.state.tickets.get(ticket_id)
        if not t:
            return {"ok": False, "tool": "ticket.transition", "error": "TICKET_NOT_FOUND", "ticket_id": ticket_id}

        cur = t.status
        allowed = self._ALLOWED_TRANSITIONS.get(cur, set())
        if to_status not in allowed:
            self._log_ticket(t, "ticket.transition", {"to_status": to_status}, False, "INVALID_TRANSITION")
            return {
                "ok": False,
                "tool": "ticket.transition",
                "error": "INVALID_TRANSITION",
                "from": cur,
                "to": to_status,
                "allowed": sorted(list(allowed)),
            }

        t.status = to_status
        self._log_ticket(t, "ticket.transition", {"to_status": to_status}, True)
        return {"ok": True, "tool": "ticket.transition", "ticket": asdict(t)}

    # -----------------------------
    # Calendar Tools
    # -----------------------------
    def cal_freebusy(self, attendees: List[str], start_ts: int, end_ts: int) -> Dict[str, Any]:
        self.step_count += 1
        fb = {}
        for u in attendees:
            fb[u] = self.state.busy.get(u, [])
        return {"ok": True, "tool": "cal.freebusy", "start_ts": start_ts, "end_ts": end_ts, "busy": fb}

    def cal_create(self, title: str, start_ts: int, end_ts: int, attendees: List[str]) -> Dict[str, Any]:
        self.step_count += 1

        # Uniqueness guard: title+time+attendees
        for e in self.state.events.values():
            if e.title == title and e.start_ts == start_ts and e.end_ts == end_ts and sorted(e.attendees) == sorted(attendees):
                return {"ok": False, "tool": "cal.create", "error": "DUPLICATE_EVENT"}

        # Conflict check
        conflicts = []
        for u in attendees:
            for b in self.state.busy.get(u, []):
                if self._overlaps((start_ts, end_ts), b):
                    conflicts.append({"user": u, "busy": b})

        if conflicts:
            return {"ok": False, "tool": "cal.create", "error": "TIME_CONFLICT", "conflicts": conflicts}

        eid = str(uuid.uuid4())
        e = Event(event_id=eid, title=title, start_ts=start_ts, end_ts=end_ts, attendees=attendees)
        self.state.events[eid] = e
        # Update busy blocks
        for u in attendees:
            self.state.busy.setdefault(u, []).append((start_ts, end_ts))

        return {"ok": True, "tool": "cal.create", "event": asdict(e)}

    def cal_reschedule(self, event_id: str, start_ts: int, end_ts: int) -> Dict[str, Any]:
        self.step_count += 1
        e = self.state.events.get(event_id)
        if not e:
            return {"ok": False, "tool": "cal.reschedule", "error": "EVENT_NOT_FOUND", "event_id": event_id}

        attendees = e.attendees

        # Remove old busy
        for u in attendees:
            self.state.busy[u] = [b for b in self.state.busy.get(u, []) if b != (e.start_ts, e.end_ts)]

        # Check conflicts for new time
        conflicts = []
        for u in attendees:
            for b in self.state.busy.get(u, []):
                if self._overlaps((start_ts, end_ts), b):
                    conflicts.append({"user": u, "busy": b})

        if conflicts:
            # Restore old busy
            for u in attendees:
                self.state.busy.setdefault(u, []).append((e.start_ts, e.end_ts))
            return {"ok": False, "tool": "cal.reschedule", "error": "TIME_CONFLICT", "conflicts": conflicts}

        # Apply new time
        e.start_ts, e.end_ts = start_ts, end_ts
        for u in attendees:
            self.state.busy.setdefault(u, []).append((start_ts, end_ts))

        return {"ok": True, "tool": "cal.reschedule", "event": asdict(e)}


# -----------------------------
# TaskSpec + Oracle
# -----------------------------
@dataclass
class TaskSpec:
    task_id: str
    description: str
    init_state: WorldState
    goal: Dict[str, Any]
    constraints: Dict[str, Any] = field(default_factory=dict)
    seed: int = 0


class OraclePlanner:
    """
    Minimal oracle that emits a correct action plan for a few task templates.
    Extend this to generate ground-truth for more tasks.
    """

    def plan(self, spec: TaskSpec) -> List[Dict[str, Any]]:
        g = spec.goal
        ttype = g.get("type")

        if ttype == "ticket_escalate_assign_close":
            # Goal: set priority, assignee, add comment, transition to CLOSED (with valid transitions)
            tid = g["ticket_id"]
            target_p = g["target_priority"]
            assignee = g["assignee"]
            comment = g.get("comment", "Escalated and assigned.")

            # We'll do: get -> update fields -> comment -> transition chain
            actions = [
                {"tool": "ticket.get", "args": {"ticket_id": tid}},
                {"tool": "ticket.update", "args": {"ticket_id": tid, "fields": {"priority": target_p, "assignee": assignee}}},
                {"tool": "ticket.comment", "args": {"ticket_id": tid, "text": comment, "author": "oracle"}},
            ]

            # Close requires legal transition: if OPEN can close; else bring to RESOLVED then CLOSED if needed
            # We'll check current status at runtime with a conditional marker.
            actions.append({"tool": "ticket.transition", "args": {"ticket_id": tid, "to_status": "CLOSED"}, "conditional": True})
            return actions

        if ttype == "schedule_meeting_if_free_else_reschedule":
            attendees = g["attendees"]
            title = g["title"]
            start_ts = g["start_ts"]
            end_ts = g["end_ts"]

            return [
                {"tool": "cal.freebusy", "args": {"attendees": attendees, "start_ts": start_ts, "end_ts": end_ts}},
                {"tool": "cal.create", "args": {"title": title, "start_ts": start_ts, "end_ts": end_ts, "attendees": attendees}},
            ]

        raise ValueError(f"Oracle: unknown task type: {ttype}")


def run_oracle(spec: TaskSpec, actor_role: str = "manager") -> Dict[str, Any]:
    """
    Execute oracle plan in the simulator to produce ground-truth trajectory.
    """
    env = WorkflowSim(state=spec.init_state.clone(), actor_role=actor_role)
    oracle = OraclePlanner()
    plan = oracle.plan(spec)

    traj = []
    for i, step in enumerate(plan, start=1):
        tool = step["tool"]
        args = step["args"]

        obs = dispatch(env, tool, args)
        traj.append({
            "t": i,
            "tool": tool,
            "args": args,
            "obs": obs,
        })

        # Simple conditional handling for close transition:
        if step.get("conditional") and (not obs.get("ok")) and obs.get("error") == "INVALID_TRANSITION":
            # attempt a legal chain: OPEN (reopen) then CLOSED
            # Most common: CLOSED -> OPEN -> CLOSED, or IN_PROGRESS -> RESOLVED -> CLOSED
            cur = obs.get("from")
            if cur == "CLOSED":
                dispatch(env, "ticket.transition", {"ticket_id": args["ticket_id"], "to_status": "OPEN"})
                dispatch(env, "ticket.transition", {"ticket_id": args["ticket_id"], "to_status": "CLOSED"})
            elif cur == "IN_PROGRESS":
                dispatch(env, "ticket.transition", {"ticket_id": args["ticket_id"], "to_status": "RESOLVED"})
                dispatch(env, "ticket.transition", {"ticket_id": args["ticket_id"], "to_status": "CLOSED"})
            elif cur == "RESOLVED":
                dispatch(env, "ticket.transition", {"ticket_id": args["ticket_id"], "to_status": "CLOSED"})
            else:
                # fallback: reopen then close
                dispatch(env, "ticket.transition", {"ticket_id": args["ticket_id"], "to_status": "OPEN"})
                dispatch(env, "ticket.transition", {"ticket_id": args["ticket_id"], "to_status": "CLOSED"})

    return {
        "task_id": spec.task_id,
        "oracle_plan": plan,
        "oracle_traj": traj,
        "final_state": env.state,
    }


def dispatch(env: WorkflowSim, tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
    if tool == "ticket.search":
        return env.ticket_search(**args)
    if tool == "ticket.get":
        return env.ticket_get(**args)
    if tool == "ticket.update":
        # 兼容两种输入：
        # 1) 标准：{"ticket_id":"T-100","fields":{"priority":"P1","assignee":"oncall"}}
        # 2) 平铺：{"ticket_id":"T-100","priority":"P1","assignee":"oncall"}
        if "fields" not in args:
            ticket_id = args.get("ticket_id")
            fields = {k: v for k, v in args.items() if k != "ticket_id"}
            args = {"ticket_id": ticket_id, "fields": fields}
        return env.ticket_update(**args)
    if tool == "ticket.comment":
        # Accept both {"text": "..."} and {"comment": "..."}
        if "text" not in args and "comment" in args:
            args["text"] = args.pop("comment")

        # If author missing, optionally default (depends on your ticket_comment signature)
        if "author" not in args:
            args["author"] = env.actor_role if hasattr(env, "actor_role") else "worker"

        return env.ticket_comment(**args)
    if tool == "ticket.transition":
        if "to_status" not in args and "status" in args:
            args["to_status"] = args.pop("status")
        return env.ticket_transition(**args)
    if tool == "cal.freebusy":
        return env.cal_freebusy(**args)
    if tool == "cal.create":
        return env.cal_create(**args)
    if tool == "cal.reschedule":
        if "event_id" not in args and "id" in args:
            args["event_id"] = args.pop("id")
        return env.cal_reschedule(**args)
    return {"ok": False, "tool": tool, "error": "UNKNOWN_TOOL"}