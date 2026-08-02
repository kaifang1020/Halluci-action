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
import re
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
# Hard ceiling on the exposed toolset. OpenAI refuses a request with more than 128 function
# definitions; the other providers are looser, but the cap is applied uniformly so a task
# presents the same tools to every agent and the cells stay comparable.
MAX_TOOLS = 128

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

# Naming a person by RELATION ("my roommates", "my landlord") means the agent has to
# resolve who that is, and the only place that mapping lives is the phone contact book —
# yet such instructions rarely contain the words "phone" or "contact". Without this signal
# phone is the app the fallback misses most often. Measured on the 147 train/dev tasks that
# carry required_apis, adding it lifts "task is doable with the tools given" 79.6% -> 98.0%.
RELATION_WORDS: tuple[str, ...] = (
    "roommate", "friend", "parent", "sibling", "coworker", "colleague", "family",
    "brother", "sister", "mother", "father", "mom", "dad", "landlord", "neighbor",
    "classmate", "boss", "partner", "spouse",
)

# The resolved answer key asserts which records changed, and spells them as `app.Model`
# (e.g. "assert model changes match venmo.PaymentRequest"). That names every app the task
# WRITES to — reliable, but blind to apps it only reads, which is why this is one signal
# of three rather than the whole answer (alone it matches required_apis just 47.6% of the
# time; unioned with the keyword and relation signals, 98.0%).
_ANSWER_KEY_APP = re.compile(
    r"\b(venmo|amazon|gmail|splitwise|spotify|todoist|phone|file_system|simple_note)\."
)


def _apps_from_answer_key(task_id: str) -> set[str]:
    """Apps named as `app.Model` in the task's resolved answer key. Never raises."""
    try:
        from research.appworld_backend.ground_truth_util import load_ground_truth_outcomes
    except Exception:  # noqa: BLE001 - importable only inside the repo
        try:
            from ground_truth_util import load_ground_truth_outcomes  # type: ignore
        except Exception:  # noqa: BLE001
            return set()
    try:
        outcomes = load_ground_truth_outcomes(task_id)
    except Exception:  # noqa: BLE001 - a missing answer key is not fatal here
        return set()
    text = " ".join(str(o.get("text", "")) for o in (outcomes or []))
    return set(_ANSWER_KEY_APP.findall(text))


def _apis_by_app(world: Any) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for d in world.task.api_docs.function_calling():
        app, api = d["function"]["name"].split("__", 1)
        out.setdefault(app, []).append(api)
    return out


def detect_involved_apps(world: Any) -> list[str]:
    """Which apps the task touches. Prefers ground-truth required_apis (exact); for test
    tasks, which ship no solution, falls back to the union of three weaker signals.
    api_docs is never involved.

    The fallback matters because getting this wrong is not a cosmetic error: an app we miss
    is an app whose tools the agent never receives, so the task becomes impossible and the
    failure looks like the agent's rather than ours. Validated against the 147 train/dev
    tasks that do carry required_apis:

        answer key only                       47.6% of tasks doable
        + instruction keywords                79.6%
        + relation words (this implementation) 98.0%   (89.8% exact, 8.2% over-broad)

    Over-broad is safe (a few extra tools just read as distractors); under-broad is not.
    """
    apps: set[str] = set()
    try:
        reqs = getattr(world.task.ground_truth, "required_apis", None) or []
        apps = {r.split(".")[0] for r in reqs if not r.endswith(".login")}
        apps.discard("api_docs")
    except Exception:
        apps = set()
    if not apps:  # test task: no solution on disk, so infer from three signals
        instr = (world.task.instruction or "").lower()
        for kws, app in KEYWORD_APP:
            if any(k in instr for k in kws):
                apps.add(app)
        if any(w in instr for w in RELATION_WORDS):
            apps.add("phone")  # resolving "my roommate" needs the contact book
        task_id = getattr(getattr(world, "task", None), "id", None)
        if task_id:
            apps |= _apps_from_answer_key(task_id)
    # supervisor is task-framing (every task) / credentials — never a routine domain app;
    # its tools enter only as a deliberate authz distractor via include_supervisor.
    apps.discard("api_docs")
    apps.discard("supervisor")
    apps = _top_up_to_num_apps(world, apps)
    return sorted(apps) or ["venmo"]  # never empty


# Apps whose tools plausibly support a task in the same domain, tried in order when the
# detected set is short of `num_apps`. Bias toward the apps that get read for identity or
# reference data, since those are exactly what the instruction tends not to name.
_TOPUP_ORDER: tuple[str, ...] = (
    "phone", "simple_note", "file_system", "venmo", "gmail",
    "splitwise", "amazon", "spotify", "todoist",
)

# Set by detect_involved_apps: task ids whose toolset had to be topped up, i.e. the three
# signals under-detected and the extra apps are a guess. Analysis should treat these
# separately — a failure there may be a missing tool rather than agent behaviour.
TOPPED_UP_TASKS: dict[str, dict[str, Any]] = {}


def _top_up_to_num_apps(world: Any, apps: set[str]) -> set[str]:
    """Widen `apps` until it is at least as large as the task's true app count.

    `ground_truth.metadata["num_apps"]` is present for every task in every split (unlike
    required_apis) and, verified against required_apis on train/dev, counts exactly the
    domain apps this function is meant to return — supervisor excluded. It gives the COUNT
    but not the identities, so it cannot repair detection; it can only tell us when
    detection came up short.

    Measured against that count over all 585 test tasks, the three signals cover 92.8%
    (test_normal 96.4%, test_challenge 91.4%); the shortfalls are concentrated in
    3+-app test_challenge tasks where the third app is only read. Under-detection is the
    harmful direction — a missing app means missing tools, so the task is impossible and
    the failure misreads as the agent's fault — while over-detection only adds distractors.
    So on a shortfall we add plausible domain apps until the count matches and record the
    task in TOPPED_UP_TASKS, because the added apps are a guess and downstream analysis
    should be able to exclude them.
    """
    try:
        want = int((world.task.ground_truth.metadata or {}).get("num_apps") or 0)
    except Exception:  # noqa: BLE001 - metadata is a bonus, never a requirement
        return apps
    if want <= len(apps):
        return apps
    detected = set(apps)
    for app in _TOPUP_ORDER:
        if len(apps) >= want:
            break
        apps.add(app)
    task_id = getattr(getattr(world, "task", None), "id", None)
    if task_id:
        TOPPED_UP_TASKS[task_id] = {"detected": sorted(detected),
                                    "added": sorted(apps - detected),
                                    "num_apps": want}
    return apps


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

    # OpenAI rejects a request carrying more than MAX_TOOLS function definitions
    # ("Invalid 'tools': array too long"), which killed gpt-4o-mini on 988af8e_1 — a
    # 9-app task whose cores plus distractors reached 141 tools. Other providers accept
    # more, but a toolset that varies by provider would make the cells incomparable, so
    # the cap applies to every model. Trim distractors only: the involved apps' cores are
    # what makes the task doable, while distractors exist to be declined. Dropping from
    # the tail preserves the semantic ranking (nearby write-tools were ranked first).
    dropped = 0
    if len(real) + len(distractors) > MAX_TOOLS:
        keep = max(0, MAX_TOOLS - len(real))
        dropped = len(distractors) - keep
        distractors = distractors[:keep]

    return {
        "task_id": seed,
        "involved_apps": involved,
        "real": real,
        "distractors": distractors,
        "toolset": real + distractors,
        "ratio": ratio,
        "semantic": semantic,
        "neighbor_apps": neigh_used,
        "distractors_dropped_for_cap": dropped,
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
