import re
import json
from langchain.chat_models import init_chat_model

detector_model = init_chat_model("openai:gpt-4.1-mini")

def detect_webapp_and_url(question: str) -> dict | None:
    """
    Use an LLM to extract the web app name and url from a natural language question.
    Returns a dict like:
      {"app": "linear", "url": "https://linear.app"}
    or
      {"app": None, "url": None}    
    """

    system_prompt = (
        """
        You are a web app name and url extraction agent.

        Given a user's question, identify which web app the user is EXPLICITLY referring to.

        Rules:
        1. Output ONLY valid JSON.
        2. JSON must have exactly two keys: app, url.
        3. app must be a lowercase app name (e.g., linear, notion, github, jira) ONLY if explicitly mentioned in the question.
        4. If the app name is not explicitly stated (e.g., just "add a label to an issue" without mentioning Linear/GitHub/etc), set app to null.
        5. url must be the official base login/home URL if you are confident about the app.
        6. If app is null or unsure, set url to null.
        7. No extra text outside JSON.
        8. Do NOT infer or guess the app based on terminology - only extract if explicitly named.
        """
    )

    response = detector_model.invoke([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Question: {question}\nApp name:"}
    ])

    text = response.content.strip()

    # JSON extraction in case model wraps it weirdly
    json_text = re.search(r"\{.*\}", text, flags=re.S)
    if not json_text:
        return {"app": None, "url": None}

    try:
        data = json.loads(json_text.group())
    except json.JSONDecodeError:
        return {"app": None, "url": None}

    app = data.get("app")
    url = data.get("url")

    # normalize
    if isinstance(app, str):
        app = app.strip().lower()
    else:
        app = None

    if isinstance(url, str):
        url = url.strip()
    else:
        url = None

    return {"app": app, "url": url}
