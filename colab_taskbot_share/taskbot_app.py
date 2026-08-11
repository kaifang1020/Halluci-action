"""Beginner-friendly, persistent medical appointment TaskBot demo.

The UI uses a small deterministic state machine. Business records are stored in
data/appointments.json, so changes persist when the project folder is on Drive.
"""

from __future__ import annotations

import json
import re
import shutil
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

import gradio as gr


PROJECT_DIR = Path(__file__).resolve().parent
DATA_FILE = PROJECT_DIR / "data" / "appointments.json"
SEED_FILE = PROJECT_DIR / "data" / "appointments_seed.json"
LOG_FILE = PROJECT_DIR / "outputs" / "conversation_logs.json"


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return deepcopy(default)
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as file:
        json.dump(value, file, ensure_ascii=False, indent=2)
    temporary.replace(path)


def find_patient(name: str, date_of_birth: str) -> dict[str, Any] | None:
    database = load_json(DATA_FILE, {"patients": []})
    normalized_name = name.strip().casefold()
    for patient in database["patients"]:
        if (
            patient["name"].strip().casefold() == normalized_name
            and patient["date_of_birth"] == date_of_birth
        ):
            return patient
    return None


def update_appointment(patient_id: str, new_date: str, new_time: str) -> dict[str, Any]:
    database = load_json(DATA_FILE, {"patients": []})
    for patient in database["patients"]:
        if patient["patient_id"] == patient_id:
            patient["appointment"]["date"] = new_date
            patient["appointment"]["time"] = new_time
            patient["appointment"]["status"] = "rescheduled"
            save_json(DATA_FILE, database)
            return patient
    raise ValueError("Patient was not found during update.")


def reset_database() -> str:
    shutil.copyfile(SEED_FILE, DATA_FILE)
    return database_markdown()


def database_markdown() -> str:
    database = load_json(DATA_FILE, {"patients": []})
    lines = [
        "| Patient ID | Name | DOB | Date | Time | Doctor | Status |",
        "|---|---|---|---|---|---|---|",
    ]
    for patient in database["patients"]:
        appointment = patient["appointment"]
        lines.append(
            f"| {patient['patient_id']} | {patient['name']} | "
            f"{patient['date_of_birth']} | {appointment['date']} | "
            f"{appointment['time']} | {appointment['doctor']} | "
            f"{appointment['status']} |"
        )
    return "\n".join(lines)


def new_session() -> dict[str, Any]:
    return {
        "state": "ASK_INTENT",
        "name": None,
        "date_of_birth": None,
        "patient_id": None,
        "new_date": None,
        "new_time": None,
    }


def session_markdown(session: dict[str, Any]) -> str:
    return "```json\n" + json.dumps(session, indent=2, ensure_ascii=False) + "\n```"


def log_turn(user_message: str, bot_message: str, session: dict[str, Any]) -> None:
    logs = load_json(LOG_FILE, [])
    logs.append(
        {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "user": user_message,
            "assistant": bot_message,
            "state": session["state"],
            "session": deepcopy(session),
        }
    )
    save_json(LOG_FILE, logs)


def parse_identity(text: str) -> tuple[str | None, str | None]:
    dob = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    name = re.search(
        r"(?:my name is|i am|i'm)\s+([A-Za-z][A-Za-z .'-]+?)(?=\s+and\b|,|\s+born\b|$)",
        text,
        flags=re.IGNORECASE,
    )
    return (
        name.group(1).strip() if name else None,
        dob.group(1) if dob else None,
    )


def parse_new_slot(text: str) -> tuple[str | None, str | None]:
    date = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    time = re.search(r"\b([01]\d|2[0-3]):[0-5]\d\b", text)
    return (
        date.group(1) if date else None,
        time.group(0) if time else None,
    )


def process_message(
    message: str,
    history: list[dict[str, str]] | None,
    session: dict[str, Any] | None,
):
    history = history or []
    session = deepcopy(session or new_session())
    text = message.strip()
    lower = text.casefold()

    if session["state"] == "ASK_INTENT":
        if any(word in lower for word in ("reschedule", "change", "appointment")):
            session["state"] = "VERIFY_PATIENT"
            reply = (
                "I can help reschedule your appointment. Please enter your full "
                "name and date of birth in `YYYY-MM-DD` format.\n\n"
                "Example: `My name is John Smith and my date of birth is 1985-01-15`"
            )
        else:
            reply = "This demo handles appointment rescheduling. Would you like to reschedule?"

    elif session["state"] == "VERIFY_PATIENT":
        name, dob = parse_identity(text)
        if not name or not dob:
            reply = (
                "I still need both fields. Please use: "
                "`My name is John Smith and my date of birth is 1985-01-15`."
            )
        else:
            patient = find_patient(name, dob)
            if not patient:
                reply = (
                    "I could not find a matching record. Please check the spelling and "
                    "use `YYYY-MM-DD`, or ask a staff member for help."
                )
            else:
                appointment = patient["appointment"]
                session.update(
                    {
                        "state": "ASK_NEW_SLOT",
                        "name": patient["name"],
                        "date_of_birth": dob,
                        "patient_id": patient["patient_id"],
                    }
                )
                reply = (
                    f"I found your appointment with {appointment['doctor']} on "
                    f"**{appointment['date']} at {appointment['time']}**. "
                    "What new date and time would you like?\n\n"
                    "Example: `2026-08-03 at 14:00`"
                )

    elif session["state"] == "ASK_NEW_SLOT":
        new_date, new_time = parse_new_slot(text)
        if not new_date or not new_time:
            reply = "Please provide both values, for example: `2026-08-03 at 14:00`."
        else:
            session.update(
                {
                    "state": "CONFIRM",
                    "new_date": new_date,
                    "new_time": new_time,
                }
            )
            reply = (
                f"Please confirm: reschedule {session['name']}'s appointment to "
                f"**{new_date} at {new_time}**? Reply `yes` or `no`."
            )

    elif session["state"] == "CONFIRM":
        if lower in {"yes", "y", "confirm", "yes, confirm"}:
            patient = update_appointment(
                session["patient_id"], session["new_date"], session["new_time"]
            )
            session["state"] = "COMPLETE"
            reply = (
                "✅ Appointment updated and saved to `data/appointments.json`.\n\n"
                f"**{patient['name']} — {patient['appointment']['date']} at "
                f"{patient['appointment']['time']}**"
            )
        elif lower in {"no", "n", "cancel"}:
            session["state"] = "ASK_NEW_SLOT"
            reply = "No changes were saved. Please enter a different date and time."
        else:
            reply = "Please reply `yes` to save the change or `no` to choose another time."

    else:
        reply = "This task is complete. Click **New conversation** to run another demo."

    history = history + [
        {"role": "user", "content": text},
        {"role": "assistant", "content": reply},
    ]
    log_turn(text, reply, session)
    return "", history, session, session_markdown(session), database_markdown()


def clear_chat():
    session = new_session()
    greeting = [
        {
            "role": "assistant",
            "content": (
                "Hello! I am the ABC Health TaskBot. "
                "How can I help with your appointment today?"
            ),
        }
    ]
    return greeting, session, session_markdown(session), database_markdown()


def build_ui():
    with gr.Blocks(title="ABC Health TaskBot") as demo:
        gr.Markdown(
            "# ABC Health TaskBot\n"
            "A beginner-friendly demo of a state-driven assistant with persistent records."
        )
        session = gr.State(new_session())

        with gr.Row():
            with gr.Column(scale=2):
                chatbot = gr.Chatbot(
                    value=clear_chat()[0],
                    type="messages",
                    height=460,
                    label="Conversation",
                )
                message = gr.Textbox(
                    label="Your message",
                    placeholder="Try: I need to reschedule my appointment",
                )
                with gr.Row():
                    send = gr.Button("Send", variant="primary")
                    new_chat = gr.Button("New conversation")

            with gr.Column(scale=1):
                gr.Markdown("### Current task state")
                state_view = gr.Markdown(session_markdown(new_session()))
                gr.Markdown("### Persistent appointment records")
                database_view = gr.Markdown(database_markdown())
                refresh = gr.Button("Refresh records")
                reset = gr.Button("Reset demo database", variant="stop")

        inputs = [message, chatbot, session]
        outputs = [message, chatbot, session, state_view, database_view]
        message.submit(process_message, inputs, outputs)
        send.click(process_message, inputs, outputs)
        new_chat.click(
            clear_chat,
            outputs=[chatbot, session, state_view, database_view],
        )
        refresh.click(database_markdown, outputs=database_view)
        reset.click(reset_database, outputs=database_view)

        gr.Markdown(
            "Demo account: **John Smith**, DOB **1985-01-15**. "
            "Saved changes and conversation logs remain in the Drive project folder."
        )
    return demo


if __name__ == "__main__":
    build_ui().launch()
