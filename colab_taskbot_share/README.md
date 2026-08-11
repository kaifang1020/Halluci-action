# Colab TaskBot Starter

This folder is a ready-to-share medical appointment TaskBot demo.

## What is included

- `TaskBot_Colab_Demo.ipynb`: open this first in Colab.
- `taskbot_app.py`: TaskBot logic, custom functions, persistence, and Gradio UI.
- `data/appointments.json`: the live mock database.
- `data/appointments_seed.json`: clean data used by the reset button.
- `statecharts/`: the two state graphs provided by the instructor.
- `outputs/conversation_logs.json`: created automatically after the first message.
- `tests/test_cases.json`: repeatable demo conversations.

## Upload and share

1. Upload the entire `colab_taskbot_share` folder to Google Drive.
2. Rename it only if you also change `PROJECT_FOLDER` in the first notebook cell.
3. Open `TaskBot_Colab_Demo.ipynb` with Google Colab.
4. Run the cells from top to bottom.
5. Share the Google Drive folder with teammates as Editors.

Important: collaborators share files, but they do not share the same Colab
runtime. Use one person as the demo driver when changing the JSON database.

## Persistence

The notebook runs `taskbot_app.py` directly from the mounted Drive folder.
Therefore these files survive runtime resets:

- `data/appointments.json`
- `outputs/conversation_logs.json`

Do not move the project into `/content` if you want changes to persist.

## UI

The final notebook cell launches Gradio. In Colab, `share=True` creates a
temporary public link. The link expires when the Colab runtime stops, but the
data files remain in Drive.

## Demo script

1. `I need to reschedule my appointment`
2. `My name is John Smith and my date of birth is 1985-01-15`
3. `2026-08-03 at 14:00`
4. `yes`

The database table on the right updates after confirmation.

## Team safety

- Do not put API keys in this folder or in Notebook code.
- If an LLM is added later, use Colab Secrets.
- Avoid two people saving `appointments.json` simultaneously.
- Keep `appointments_seed.json` unchanged so the demo can always be reset.
