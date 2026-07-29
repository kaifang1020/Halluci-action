"""Systematic per-task tool exposure for the AppWorld migration.

Replaces the ad-hoc hand-listed EXPOSED_APIS with a principled, reproducible rule:

    toolset(task) = REAL  ⊎  DISTRACTORS
      REAL        = the CORE toolset of every app the task involves
                    (guarantees coverage — the task's needed APIs are in its app's core —
                     without having to know the exact APIs; the extra core tools double as
                     WITHIN-app distractors, e.g. venmo create_transaction next to
                     create_payment_request).
      DISTRACTORS = round(len(REAL) * ratio) tools from OTHER apps, chosen with SEMANTIC
                    BIAS: same-/adjacent-domain apps' ACTION tools first (the "plausible but
                    wrong" temptations — splitwise.record_expense / gmail.send_email for a
                    "request money" task), sampled deterministically by a task seed.

Design rationale (see the long chat thread): controlling the distractor RATIO (signal:noise
density) is a better experimental control than a constant total-N, because what makes
wrong-tool selection hard is distractor density, not absolute count; and app sizes vary
6..91 so constant-N + "whole app core" cannot both hold. Coverage is guaranteed because we
expose the involved app's whole core. `supervisor` is NOT a routine distractor (its
credential APIs are a deliberate authorization-hallucination trap — include only via
`include_supervisor=True` for authz tasks). `api_docs` is never exposed (no discovery).

Additive; validates every curated name against the world's real api_docs at runtime.

CLI (inspect any task's injected toolset):
    APPWORLD_ROOT=... PYTHONPATH=$PWD python research/appworld_backend/tool_exposure.py \
        --task-id 2e9b91e_1 [--ratio 0.33] [--random] [--seed 2e9b91e_1]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path
from typing import Any

_API_METHODS: dict[str, Any] | None = None


def _is_write(full_name: str) -> bool:
    """Is `app__api` a state-mutating call? Uses the prebuilt api_methods.json (real
    HTTP method); falls back to the ACTION_PREFIX heuristic if the table is absent."""
    global _API_METHODS
    if _API_METHODS is None:
        p = Path(__file__).resolve().parent / "api_methods.json"
        _API_METHODS = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    if full_name in _API_METHODS:
        return bool(_API_METHODS[full_name].get("is_write"))
    return full_name.split("__", 1)[-1].startswith(ACTION_PREFIX)

# ---------------------------------------------------------------- curated cores
# Main business read+write ops per app; auth plumbing + long tail dropped. Validated
# against the world's actual APIs at runtime (unknown names are silently dropped).
CORE: dict[str, list[str]] = {
    "venmo": ["show_account", "show_profile", "search_users", "search_friends", "show_venmo_balance",
              "show_transactions", "show_transaction", "create_transaction", "update_transaction",
              "show_received_payment_requests", "show_sent_payment_requests", "create_payment_request",
              "approve_payment_request", "deny_payment_request", "remind_payment_request", "show_payment_cards"],
    "amazon": ["show_account", "show_profile", "search_products", "show_product", "show_cart",
               "add_product_to_cart", "delete_product_from_cart", "update_product_quantity_in_cart",
               "clear_cart", "apply_promo_code_to_cart", "place_order", "show_orders", "show_order",
               "initiate_return", "show_addresses", "show_payment_cards"],
    "gmail": ["show_profile", "search_users", "show_inbox_threads", "show_outbox_threads", "show_thread",
              "show_email", "send_email", "reply_to_email", "forward_email_from_thread", "forward_email_thread",
              "create_draft", "update_draft", "send_email_from_draft", "show_drafts", "delete_thread",
              "mark_thread_read"],
    "splitwise": ["show_profile", "search_users", "show_groups", "create_group", "show_group",
                  "add_member_to_group", "record_expense", "show_expense", "update_expense", "delete_expense",
                  "show_group_expenses", "record_payment", "show_payment", "settle_up", "show_person_balance",
                  "show_people_balance", "show_group_balance", "post_expense_comment"],
    "phone": ["show_profile", "show_contact_relationships", "search_contacts", "add_contact", "update_contact",
              "show_text_message", "search_text_messages", "send_text_message", "send_voice_message",
              "search_voice_messages", "show_alarms", "create_alarm"],
    "spotify": ["show_profile", "search_songs", "show_song", "like_song", "show_liked_songs", "search_albums",
                "show_album", "show_playlist_library", "search_playlists", "create_playlist", "show_playlist",
                "update_playlist", "add_song_to_playlist", "remove_song_from_playlist", "search_artists",
                "show_artist", "play_music", "review_song"],
    "todoist": ["show_profile", "search_users", "show_projects", "create_project", "show_project", "show_tasks",
                "create_task", "show_task", "update_task", "delete_task", "create_sub_task", "show_sub_tasks",
                "add_label_to_task", "post_task_comment", "assign_or_unassign_task", "show_sections"],
    "simple_note": ["show_profile", "search_notes", "create_note", "show_note", "update_note", "add_content_to_note"],
    "file_system": ["show_directory", "create_directory", "delete_directory", "show_file", "create_file",
                    "delete_file", "update_file", "copy_file", "move_file", "copy_directory",
                    "compress_directory", "decompress_file"],
    "supervisor": ["show_active_task", "complete_task", "show_profile", "show_addresses",
                   "show_payment_cards", "show_account_passwords"],
}

# ---------------------------------------------------------------- domains
DOMAIN: dict[str, str] = {
    "venmo": "money_p2p", "splitwise": "money_p2p", "amazon": "shopping",
    "gmail": "comms", "phone": "comms", "spotify": "media",
    "todoist": "productivity", "simple_note": "productivity", "file_system": "system",
    "supervisor": "identity",
}
# which domains count as "semantically near" a given domain (for distractor bias)
ADJACENCY: dict[str, set[str]] = {
    "money_p2p": {"money_p2p", "comms", "shopping"},
    "shopping": {"shopping", "money_p2p"},
    "comms": {"comms", "money_p2p", "productivity"},
    "media": {"media", "productivity"},
    "productivity": {"productivity", "comms", "media"},
    "system": {"system", "productivity"},
    "identity": {"identity"},
}
# "tempting wrong action" verbs — a distractor that DOES something (not a passive read)
ACTION_PREFIX = ("create_", "send_", "record_", "settle_", "add_", "place_", "post_", "write_",
                 "approve_", "deny_", "remind_", "subscribe_", "forward_", "reply_", "assign_",
                 "review_", "like_", "play_")
AUTHISH = {"login", "logout", "signup", "verify_account", "send_verification_code", "reset_password",
           "send_password_reset_code", "delete_account", "update_account_name"}

# instruction keyword -> app (fallback when required_apis unavailable, e.g. test tasks)
KEYWORD_APP: list[tuple[tuple[str, ...], str]] = [
    (("venmo",), "venmo"),
    (("amazon", "cart", "order", "package", "prime"), "amazon"),
    (("gmail", "email", "inbox", "mail"), "gmail"),
    (("splitwise", "expense", "split the", "owe", "settle"), "splitwise"),
    (("spotify", "song", "playlist", "album", "artist"), "spotify"),
    (("text ", "message", "contact", "roommate", "coworker", "call", "voicemail"), "phone"),
    (("todoist", "task", "project", "to-do", "todo"), "todoist"),
    (("note", "simple note"), "simple_note"),
    (("file", "directory", "folder", "download"), "file_system"),
]


def _apis_by_app(world: Any) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for d in world.task.api_docs.function_calling():
        app, api = d["function"]["name"].split("__", 1)
        out.setdefault(app, []).append(api)
    return out


def detect_involved_apps(world: Any) -> list[str]:
    """Which apps the task touches. Prefers ground-truth required_apis (accurate); falls
    back to instruction keyword parsing (test tasks). api_docs is never involved."""
    apps: set[str] = set()
    try:
        reqs = getattr(world.task.ground_truth, "required_apis", None) or []
        apps = {r.split(".")[0] for r in reqs if not r.endswith(".login")}
        apps.discard("api_docs")
    except Exception:
        apps = set()
    if not apps:  # test task: parse the instruction
        instr = (world.task.instruction or "").lower()
        for kws, app in KEYWORD_APP:
            if any(k in instr for k in kws):
                apps.add(app)
    # supervisor is task-framing (every task) / credentials — never a routine domain app;
    # its tools enter only as a deliberate authz distractor via include_supervisor.
    apps.discard("api_docs")
    apps.discard("supervisor")
    return sorted(apps) or ["venmo"]  # never empty


def build_task_toolset(
    world: Any,
    *,
    ratio: float = 1 / 3,
    semantic: bool = True,
    seed: str | None = None,
    involved_apps: list[str] | None = None,
    include_supervisor: bool = False,
) -> dict[str, Any]:
    by_app = _apis_by_app(world)
    involved = involved_apps or detect_involved_apps(world)
    involved = [a for a in involved if a in by_app]
    seed = seed or (world.task.id if hasattr(world.task, "id") else "seed")
    rng = random.Random(int(hashlib.md5(seed.encode()).hexdigest(), 16) % 2 ** 32)

    def valid(app: str, names: list[str]) -> list[str]:
        have = set(by_app.get(app, []))
        return [f"{app}__{n}" for n in names if n in have and n not in AUTHISH]

    # REAL = core of each involved app (fall back to whole app if uncurated)
    real: list[str] = []
    for app in involved:
        real += valid(app, CORE.get(app, [n for n in by_app[app] if n not in AUTHISH]))

    # DISTRACTOR pool from OTHER apps
    skip = set(involved) | {"api_docs"} | (set() if include_supervisor else {"supervisor"})
    others = [a for a in by_app if a not in skip]
    n_dist = round(len(real) * ratio)

    if semantic:
        near_domains: set[str] = set()
        for a in involved:
            near_domains |= ADJACENCY.get(DOMAIN.get(a, ""), set())
        neigh = [a for a in others if DOMAIN.get(a) in near_domains]
        far = [a for a in others if a not in neigh]
        # priority: neighbor ACTION tools -> neighbor reads -> far ACTION -> far reads
        def bucket(apps, action):
            names = [f"{a}__{n}" for a in apps for n in by_app[a]
                     if n not in AUTHISH and (_is_write(f"{a}__{n}") == action)]
            rng.shuffle(names)
            return names
        ranked = bucket(neigh, True) + bucket(neigh, False) + bucket(far, True) + bucket(far, False)
        distractors = ranked[:n_dist]
        neigh_used = sorted(neigh)
    else:  # random cross-app, round-robin for breadth
        pool = {a: [f"{a}__{n}" for n in by_app[a] if n not in AUTHISH] for a in others}
        for a in pool:
            rng.shuffle(pool[a])
        order = sorted(others)
        rng.shuffle(order)
        distractors, i = [], 0
        while len(distractors) < n_dist and any(pool.values()):
            a = order[i % len(order)]
            i += 1
            if pool[a]:
                distractors.append(pool[a].pop())
        neigh_used = []

    return {
        "task_id": seed,
        "involved_apps": involved,
        "real": real,
        "distractors": distractors,
        "toolset": real + distractors,
        "ratio": ratio,
        "semantic": semantic,
        "neighbor_apps": neigh_used,
    }


def _open_world(task_id: str, experiment_name: str) -> Any:
    """Open a throwaway world for detection. Try ground_truth_mode='full' (gives
    required_apis for train/dev app detection); test tasks have no ground-truth files,
    so fall back to the default mode (detection then uses instruction parsing)."""
    import os
    os.environ.setdefault("APPWORLD_ROOT", "/Users/maokaifang/appworld-root")
    from appworld import AppWorld
    try:
        return AppWorld(task_id=task_id, experiment_name=experiment_name, ground_truth_mode="full")
    except Exception:
        return AppWorld(task_id=task_id, experiment_name=experiment_name)


def exposed_apis_for_task(task_id: str, **kwargs: Any) -> list[str]:
    """Convenience: open a throwaway world and return just the toolset list of
    `app__api` names (used to configure the AGENT's separate world)."""
    w = _open_world(task_id, "tool_exposure")
    try:
        return build_task_toolset(w, seed=task_id, **kwargs)["toolset"]
    finally:
        try:
            w.close()
        except Exception:
            pass


def main() -> None:
    import os
    os.environ.setdefault("APPWORLD_ROOT", "/Users/maokaifang/appworld-root")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--task-id", required=True)
    p.add_argument("--ratio", type=float, default=1 / 3)
    p.add_argument("--random", action="store_true", help="random cross-app distractors instead of semantic bias")
    p.add_argument("--seed", default=None)
    p.add_argument("--involved", default=None, help="comma-separated apps to force (else auto-detect)")
    p.add_argument("--supervisor", action="store_true", help="allow supervisor credential tools as distractors")
    args = p.parse_args()
    w = _open_world(args.task_id, "tool_exposure_cli")
    res = build_task_toolset(
        w, ratio=args.ratio, semantic=not args.random, seed=args.seed or args.task_id,
        involved_apps=(args.involved.split(",") if args.involved else None),
        include_supervisor=args.supervisor,
    )
    print(f"task {res['task_id']}  involved={res['involved_apps']}  "
          f"mode={'semantic' if res['semantic'] else 'random'}  ratio={res['ratio']:.2f}")
    print(f"REAL={len(res['real'])}  DISTRACTOR={len(res['distractors'])}  TOTAL={len(res['toolset'])}  "
          f"neighbors={res['neighbor_apps']}\n")
    for app in res["involved_apps"]:
        names = [x.split("__", 1)[1] for x in res["real"] if x.startswith(app + "__")]
        print(f"  REAL[{app}] ({len(names)}): {', '.join(names)}")
    print(f"\n  DISTRACTORS ({len(res['distractors'])}): {', '.join(res['distractors'])}")
    w.close()


if __name__ == "__main__":
    main()
