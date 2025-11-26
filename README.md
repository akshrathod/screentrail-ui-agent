# ScreenTrail UI Agent

ScreenTrail is a dual-agent system that turns a plain-English instruction into real actions inside a browser. One agent cleans up and simplifies the task, the second figures out the exact UI steps, and Playwright carries them out using a saved login session. Each run produces a clear, step-by-step trail of what happened (kept locally, not committed to GitHub).

---

## What This Project Does

- You type a natural-language task **for a supported web app** (e.g., *“Create a new project in Linear”*).
- **Agent A** rewrites it into a clean, unambiguous goal.
- **Agent B** inspects the current UI state and determines the next actionable step, building the sequence incrementally.
- **Playwright** executes those actions in the real browser using saved user profiles.
- Screenshots and task summaries are saved locally for traceability.

It’s basically:
**LLM thinks, Playwright clicks.**

---

## System Architecture

**`main.py`**
Entry point. Coordinates the flow from user instruction → Agent A → Agent B.

**`Agents/`**

* `agent_a.py`: Task Normalizer
Takes the user’s raw instruction and rewrites it into one clean, concise task using an LLM. Removes noise and standardizes the request before it reaches Agent B.
* `agent_b.py`: Stepwise UI Navigator
Detects the target web app, launches the browser, and drives the entire automation loop. It reads the current UI state, asks the LLM for the next single action, executes it with Playwright, captures screenshots, and repeats until the task is complete.

**`Helpers/`**

* `webapp_info.py`: App Detector
Extracts the explicitly mentioned web app (e.g., Linear) and its base URL from the user’s instruction. Returns null if no app is named, ensuring no guessing.

**`BrowserProfiles/`** *(git-ignored)*
**App-specific** browser profiles (e.g., linear, notion, asana) that store your logged-in sessions so you don’t have to authenticate on every run.

**`Screenshots/`** *(git-ignored)*
Local-only visual trace of each task (step screenshots + README).
Not uploaded to GitHub for privacy and repo size.

---

## Project Structure

```
screentrail-ui-agent/
│
├── Agents/
│   ├── agent_a.py
│   └── agent_b.py
│
├── Helpers/
│   └── webapp_info.py
│
├── BrowserProfiles/       # ignored by git
├── Screenshots/           # ignored by git
│
├── main.py
├── requirements.txt
├── .env                   # ignored by git
└── .gitignore
```

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/akshrathod/screentrail-ui-agent.git
cd screentrail-ui-agent
```

### 2. Create a virtual environment

```bash
python -m venv venv
source venv/bin/activate        # Mac/Linux
venv\Scripts\activate           # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Add your `.env` file (local only, never committed)

```
OPENAI_API_KEY=your_key_here
# Add other keys or config you need
```

### 5. Ensure `BrowserProfiles/` exists

First run will prompt you to manually log in — afterward your sessions persist.

---

## Running the Agent

```bash
python main.py
```

After execution:

* UI automation runs in a Playwright browser.
* A task folder with screenshots + a summary is created under `Screenshots/` (local only).

---

## Add Support for a New Web App

1. Teach Agent B how to route tasks to this app.
2. Extend Playwright executor if needed (selectors, modals, flows).

---

## Roadmap / Possible Enhancements

* More robust error recovery when selectors change
* Support for additional productivity apps
* Diff-based verification of UI changes
