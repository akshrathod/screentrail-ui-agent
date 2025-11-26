from playwright.sync_api import sync_playwright
from helpers.webapp_info import detect_webapp_and_url
from langchain.chat_models import init_chat_model
import os, json, re
from pathlib import Path

class Navigator_AgentB:
    def __init__(self, name: str = "Agent B"):
        self.name = name
        self.llm = init_chat_model("openai:gpt-4o-mini")

    def handle_question(self, question: str) -> None:
        """
        Run the browser, navigate, and capture UI states.
        """
        print(f"[INFO] {self.name} received task from Agent A")

        # Detect target app and URL
        app_info = detect_webapp_and_url(question)
        app_name = app_info.get("app")
        app_url = app_info.get("url")

        if not app_name or app_name == "none":
            print(f"[ERROR] Could not determine target web application")
            return
        else:
            print(f"[DETECTED] Web App: {app_name}")

        if not app_url or app_url == "none":
            print(f"[ERROR] Could not determine web app URL")
            return
        else:
            print(f"[DETECTED] URL: {app_url}\n")

        # Prepare screenshot directories
        screenshots_root = Path("screenshots")
        app_folder = screenshots_root / app_name
        app_folder.mkdir(parents=True, exist_ok=True)

        # Remove app name from question since it's already in the parent folder
        task_text = self._remove_app_name_from_question(question, app_name)
        base_slug = self._slug(task_text)
        if not base_slug:
            base_slug = "task"
        # Ensure uniqueness if the same task asked multiple times
        candidate = app_folder / base_slug
        if candidate.exists():
            i = 1
            while (app_folder / f"{base_slug}_{i}").exists():
                i += 1
            candidate = app_folder / f"{base_slug}_{i}"
        task_folder = candidate
        task_folder.mkdir(parents=True, exist_ok=True)
        self._snap_seq = 0
        
        # Initialize README.md for this task
        readme_path = self._init_readme(task_folder, question, app_name)


        profiles_root = Path("browser_profiles")
        app_profile_dir = profiles_root / app_name
        app_profile_dir.mkdir(parents=True, exist_ok=True)

        login_flag = app_profile_dir / "logged_in.flag"

        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(app_profile_dir),
                headless=False,
                channel="chrome",  
                slow_mo=200,                # helps stability for humans + UI
            )
            page = context.new_page()

            # Go to app URL
            page.goto(app_url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(1500)  # wait a bit for UI to settle

            # First-time login for this app → manual
            if not login_flag.exists():
                print(f"\n[ACTION REQUIRED] Please log in manually to {app_name} in the opened browser")
                print("  - Complete any SSO / captcha / 2FA if needed")
                print("  - Make sure you reach your dashboard/workspace")
                print("  - Press Enter here when ready to continue\n")
                input()

                # mark login done for this app
                login_flag.write_text("ok")

            # Logged in (either already or just now)
            self._snap(page, task_folder, "opened_app")
            opened_state = page.inner_text("body")[:1500]

            # Execute goal loop: read page -> ask LLM for next action -> execute -> repeat
            try:
                self._execute_goal_loop(
                    question,
                    page,
                    task_folder,
                    app_name=app_name,
                    max_steps=10,
                    initial_last_after_state=opened_state,
                    readme_path=readme_path,
                )
                self._finalize_readme(readme_path, success=True)
                print("[SUCCESS] Task completed successfully\n")
            except Exception as e:
                self._finalize_readme(readme_path, success=False, reasoning=str(e))
                print(f"[ERROR] Task failed: {e}\n")
            finally:
                context.close()

    # ============================= helper methods =============================

    def _snap(self, page, outdir, label):
        seq = getattr(self, "_snap_seq", 0) + 1
        self._snap_seq = seq
        filename = f"{seq:02d}_{label}.png"
        path = os.path.join(outdir, filename)
        page.screenshot(path=path, full_page=True)

    def _collect_dom_hints(self, page):
        """Scan common editable elements, buttons, and success indicators, return structured hints.

        Returns:
            {"inputs": [...], "buttons": [...], "alerts": [...]}
        """
        hints = {"inputs": [], "buttons": [], "alerts": []}
        try:
            # Scan for input/textarea/editable fields
            elements = page.query_selector_all('input, textarea, [contenteditable="true"], [role="textbox"]')
            for el in elements:
                try:
                    aria = (el.get_attribute("aria-label") or "").strip()
                except Exception:
                    aria = ""
                try:
                    name = (el.get_attribute("name") or "").strip()
                except Exception:
                    name = ""
                try:
                    id_ = (el.get_attribute("id") or "").strip()
                except Exception:
                    id_ = ""
                try:
                    placeholder = (el.get_attribute("placeholder") or "").strip()
                except Exception:
                    placeholder = ""
                try:
                    tag = el.evaluate("el => el.tagName.toLowerCase()")
                except Exception:
                    tag = ""
                try:
                    val = el.input_value()
                except Exception:
                    try:
                        val = el.inner_text()
                    except Exception:
                        val = ""
                val = (val or "").strip()

                hints["inputs"].append({
                    "aria-label": aria,
                    "name": name,
                    "id": id_,
                    "placeholder": placeholder,
                    "tag": tag,
                    "value": val,
                    "empty": not val,  # True if no value, False if has value
                })

            # Scan for buttons and clickable links (including table rows with links)
            buttons = page.query_selector_all('button, [role="button"], a[onclick], input[type="button"], input[type="submit"], a[href], [role="link"]')
            for btn in buttons:
                try:
                    btn_text = (btn.inner_text() or "").strip()
                except Exception:
                    btn_text = ""
                try:
                    btn_aria = (btn.get_attribute("aria-label") or "").strip()
                except Exception:
                    btn_aria = ""
                try:
                    btn_title = (btn.get_attribute("title") or "").strip()
                except Exception:
                    btn_title = ""
                try:
                    btn_id = (btn.get_attribute("id") or "").strip()
                except Exception:
                    btn_id = ""
                try:
                    btn_name = (btn.get_attribute("name") or "").strip()
                except Exception:
                    btn_name = ""
                try:
                    # Get the role to distinguish between different types
                    btn_role = (btn.get_attribute("role") or btn.evaluate("el => el.tagName.toLowerCase()")).strip()
                except Exception:
                    btn_role = ""
                try:
                    btn_visible = btn.is_visible()
                except Exception:
                    btn_visible = False
                
                # Include buttons with text, aria-label, title, or if they're visible icon buttons
                if (btn_text or btn_aria or btn_title) and btn_visible:
                    btn_info = {
                        "text": btn_text,
                        "aria-label": btn_aria if not btn_text else "",                        
                        "title": btn_title,
                        "id": btn_id,
                        "name": btn_name,
                        "role": btn_role if btn_role in ["button", "link", "a"] else "button"
                    }
                    # Mark icon-only buttons
                    if not btn_text and (btn_aria or btn_title):
                        btn_info["type"] = "icon"
                    hints["buttons"].append(btn_info)

            # Scan for toast/alert/notification elements (success/error messages)
            alerts = page.query_selector_all('[role="alert"], .toast, .notification, .message, [class*="toast"], [class*="alert"], [class*="message"], [class*="notification"]')
            for alert in alerts:
                try:
                    alert_text = (alert.inner_text() or "").strip()
                    if alert_text:  # Only include if has visible text
                        hints["alerts"].append({
                            "text": alert_text,
                            "type": "alert/toast/notification"
                        })
                except Exception:
                    pass
        except Exception:
            pass
        return hints

    def _decide_next_action(self, goal, page, step_num: int, action_history: list = None, app_name: str = "unknown") -> dict:
        """Ask the LLM to return the next single action (JSON dict) given the goal
        and the current page state.
        """
        if action_history is None:
            action_history = []

        visible_text = page.inner_text("body")[:4000]

        # Collect structured DOM hints (inputs, buttons, alerts)
        hints = self._collect_dom_hints(page)
        
        inputs_json = json.dumps(hints.get("inputs", [])[:20], ensure_ascii=False)
        buttons_json = json.dumps(hints.get("buttons", [])[:15], ensure_ascii=False)
        alerts_json = json.dumps(hints.get("alerts", [])[:10], ensure_ascii=False)
        
        # Format action history for the LLM
        history_summary = ""
        if action_history:
            history_summary = "\n\nActions taken so far:\n"
            for act in action_history[-5:]: 
                loc = act.get("locator", {})
                loc_str = loc.get("aria-label") or loc.get("placeholder") or loc.get("text") or loc.get("name") or "unknown"
                text_str = f" with text '{act.get('text')}'" if act.get("text") else ""
                status = act.get("status", "success")
                status_marker = "✓" if status == "success" else "✗ FAILED"
                history_summary += f"Step {act['step']}: {status_marker} {act['type']} on [{loc_str}]{text_str}\n"

        # Add app-specific complexity warning
        app_complexity_note = ""
        if app_name.lower() == "asana":
            app_complexity_note = "\n ASANA COMPLEXITY: Asana has a complex UI with nested menus, modal dialogs, and multi-step workflows. Expect to take more steps than usual. Be patient and verify each action completes before moving to the next.\n"

        prompt = (
            f"""
            You are a browser automation agent with expert knowledge of modern web applications and their typical UI patterns.

            Application: {app_name}
            Goal: {goal}
            Current Step: {step_num}{history_summary}

            Current page text (truncated):
            {visible_text}

            Detected input hints (first 20, include aria-labels, placeholders, and current values): {inputs_json}
            Detected buttons and links (first 15, available actions - includes links to items in lists/tables): {buttons_json}
            Detected alerts/toasts (success/error messages): {alerts_json}{app_complexity_note}

            IMPORTANT: Use your knowledge of how web apps typically work to make intelligent decisions:
            - Understand which apps use explicit Create/Save buttons vs. auto-save behavior
            - Recognize when a task is complete based on app-specific patterns (toasts, redirects, auto-save, list updates)
            - Adapt your strategy based on the app you're automating
            - After clicking a button that opens a dropdown/menu, the next action should typically be clicking an option from that menu (look for the specific value in the page text), NOT clicking another button or textbox.
            - If you just clicked something and now see a dropdown menu with options, your next action MUST be clicking one of those options - completely ignore any search/filter textboxes and their placeholders that appear alongside the dropdown.
            
            CRITICAL - Read the current page first:
            - Before deciding your action, carefully examine "Current page text" and "Detected buttons and links" to understand WHERE you are
            - Goals often require multiple steps. Break them down: navigate → interact → confirm
            - Don't assume you're already at the right place. If the goal requires opening an item, check if you need to navigate to a list first.
            - Take one logical step at a time based on what's actually visible on the current page

            Decide the NEXT SINGLE ACTION to take toward the goal. Return ONLY valid JSON with this schema:
            {{{{
              "type": "goto|click|fill|select|press|scroll|wait|done",
              "label": "<short human label for logs>",
              "locator": {{"role":"...","name":"...","aria-label":"...","placeholder":"...","text":"...","css":"..."}},
              "text": "<for fill - use short unique values (12-16 chars) with random suffix",
              "value": "<for select>",
              "key": "<for press>",
              "direction": "down|up",
              "url": "<for goto>"
            }}}}

            Rules:
            - Review "Actions taken so far" to see what you've already done. DO NOT repeat actions you've already completed.
            - If a previous step shows "✗ FAILED", do NOT retry the same locator - try a different approach or different element.
            - If you filled a field in a previous step, DO NOT fill it again. Move to the next action.
            - When filling text inputs (project names, issue titles, labels, comments, etc.), generate SHORT UNIQUE values between 12-16 characters with a random suffix. This prevents duplicate name errors on repeated test runs.
            - Use your app knowledge to determine the correct workflow (explicit save button vs. auto-save, etc.)
            - NEVER return type: "done" just because fields are filled. Consider if the app requires an explicit action button click.
            - Return type: "done" ONLY when goal is completed based on observable evidence appropriate for the app type.
            - Locator preference: 1) role + VISIBLE TEXT (the label users see), 2) role + aria-label/name (accessible name), 3) placeholder (for empty inputs), 4) text, 5) css (last resort).
            - To click table/list items, prefer using role: "link" with the item text rather than role: "row". Links are clickable, rows may not be.
            - When selecting from dropdowns/menus: placeholders in filter/search boxes are just hints - ignore them and directly click the actual option you need from the visible list.
            - CRITICAL RULE: Only suggest "fill" actions for inputs where "empty": true. Do NOT re-fill inputs that already have a value ("empty": false).
            - ACTION PRIORITY: 1) Fill ONLY empty required fields that you haven't filled yet, 2) Click action buttons if needed by the app, 3) Wait and verify completion, 4) Return done when truly completed.
            - When all required fields are filled (empty: false or already_filled: true), immediately look for and click relevant action buttons from the Detected buttons list.
            - CRITICAL: Do NOT invent button names or aria-labels. ONLY use elements you can see in "Detected buttons and links" or "Current page text". If you can't find an exact button, look for visible text that represents the current state (e.g., the current status value might itself be clickable to change it).
            - When you need to interact with something but can't find a dedicated button, examine the page text for the actual current value or label that might be interactive.
            - If the goal mentions an action (e.g., "change", "update", "modify") but you can't find that exact word, look for synonyms or related terms in the detected buttons (e.g., "Set", "Edit", "Configure") or click the current value directly if it's interactive.
            - When changing/updating a value (status, priority, assignee, etc.), select an option that is DIFFERENT from the current value. Don't click the same value that's already set.
            - Output JSON only. No markdown. No commentary.
            """
        )

        resp = self.llm.invoke([{"role": "user", "content": prompt}])
        text = resp.content.strip()

        # Extract JSON: find the first { and parse from there
        start_idx = text.find('{')
        if start_idx == -1:
            raise ValueError(f"LLM did not return JSON for next action: {text}")
        
        action = None
        for end_idx in range(start_idx + 1, len(text) + 1):
            try:
                candidate = text[start_idx:end_idx]
                action = json.loads(candidate)
                break
            except json.JSONDecodeError:
                continue
        
        if action is None:
            raise ValueError(f"Could not parse valid JSON from LLM response: {text}")

        return action

    def _execute_goal_loop(self, goal, page, outdir, app_name: str = "unknown", max_steps: int = 10, initial_last_after_state: str | None = None, readme_path: Path | None = None):
        """
        Real-time loop: for up to `max_steps` iterations, ask the LLM for the next
        action given the current page, execute it, take screenshots, and repeat
        until the LLM returns type == 'done'.
        """
        step_num = 1
        action_history = []  # Track all actions taken so LLM can see what it already did
        # Track last after screenshot state to avoid redundant before screenshots
        last_after_state = initial_last_after_state
        
        while step_num <= max_steps:
            action = self._decide_next_action(goal, page, step_num, action_history, app_name)
            print(f"[ACTION] Step {step_num}: {action}")

            # If LLM says we're done, finish
            if isinstance(action, dict) and action.get("type") == "done":
                print(f"[COMPLETE] Goal reached at step {step_num}: {action.get('reasoning', '')}")
                if readme_path:
                    self._append_step_to_readme(readme_path, step_num, action, "completed")
                return

            label = action.get("label") or f"step_{step_num}"

            # exiBEFORE screenshot - only if different from last after state
            current_before_state = page.inner_text("body")[:1500]
            if last_after_state is None or current_before_state != last_after_state:
                self._snap(page, outdir, f"before_{self._slug(label)}")
            # else: skip before screenshot as it's identical to previous after

            # Execute action
            action_status = "success"
            try:
                self._do_action(action, page)
                action_history.append({
                    "step": step_num,
                    "type": action.get("type"),
                    "label": label,
                    "locator": action.get("locator", {}),
                    "text": action.get("text", ""),
                    "status": "success"
                })
            except Exception:
                action_status = "failed"
                action_history.append({
                    "step": step_num,
                    "type": action.get("type"),
                    "label": label,
                    "locator": action.get("locator", {}),
                    "text": action.get("text", ""),
                    "status": "failed"
                })
            
            # Append step to README
            if readme_path:
                self._append_step_to_readme(readme_path, step_num, action, action_status)

            # Post-action settle (longer for clicks)
            try:
                if action.get("type") == "click":
                    page.wait_for_timeout(2000)
                else:
                    page.wait_for_timeout(900)
            except Exception:
                pass

            # AFTER screenshot - store state for next iteration
            self._snap(page, outdir, f"after_{self._slug(label)}")
            last_after_state = page.inner_text("body")[:1500]

            # Check if goal is completed after this action (clicks, enter presses, etc., not fills)
            action_type = action.get("type", "")
            action_label = action.get("label", "").lower()
            
            # Skip completion check for fill/type actions and early intermediate steps
            is_fill_action = action_type in ["fill", "type"]
            is_intermediate_click = action_type == "click" and any(word in action_label for word in ["open", "expand", "show", "menu", "dropdown"]) and len(action_history) < 3
            
            # Only check completion after meaningful actions (submit clicks, press Enter, etc.)
            if not is_fill_action and not is_intermediate_click and step_num >= 2:
                if self._check_goal_completion(goal, page):
                    print(f"[COMPLETE] Goal completed after step {step_num}")
                    return

            step_num += 1

        raise RuntimeError(f"Max steps ({max_steps}) reached without completing goal.")

    def _check_goal_completion(self, goal, page) -> bool:
        """Ask the LLM: 'Is the goal completed based on current page state?'
        Returns True if goal is done, False otherwise.
        """
        visible_text = page.inner_text("body")[:3000]
        hints = self._collect_dom_hints(page)
        alerts_json = json.dumps(hints.get("alerts", [])[:5], ensure_ascii=False)

        prompt = (
            f"""
            You are verifying if a task goal has been completed.

            Goal: {goal}

            Current page text (truncated):
            {visible_text}

            Detected alerts/toasts (success/error messages): {alerts_json}

            Question: Has the goal been COMPLETED based on observable evidence?

            Return ONLY a JSON object:
            {{{{
              "completed": true|false,
              "reasoning": "<brief explanation of why completed or not>"
            }}}}

            Evidence for completion (be strict):
            - Success toast/alert messages indicating the action was performed (check alerts list)
            - NEW items appearing in lists (project created, page added, task saved)
            - Page navigation to success/confirmation screens after performing an action
            - Visible confirmation messages in page text stating something was changed/updated NOW (not in the past)
            - Observable page content changes that directly result from the action you performed and align with the goal
            - For comments/posts: the comment must appear in the comment thread/history area, NOT just in the input field
            
            NOT evidence of completion:
            - Just opening an item or navigating to a page (you must perform the actual action)
            - Seeing a value that already exists (for "change" goals, you must see evidence that YOU changed it)
            - No alerts/toasts/confirmation when the goal requires explicit confirmation (create, save, delete actions)
            - Opening a menu or dialog without selecting/completing an option inside it
            - Seeing options in an open dropdown menu (the option must be selected and results must update)
            - Text typed in an input field but not yet submitted (for comments/posts, must see it in the posted history area)
            - Seeing your typed text in a text editor or input box without clicking Submit/Post/Save button

            Important: Some actions (filter, sort, search) don't show toasts but DO update the page content with the required task. If the page state matches the goal's expected outcome after performing the action, consider it complete. BUT seeing an option in a menu is NOT completion - you must see the actual results.

            Output JSON only. No markdown. No commentary.
            """
        )

        try:
            resp = self.llm.invoke([{"role": "user", "content": prompt}])
            text = resp.content.strip()
            
            # Extract JSON
            start_idx = text.find('{')
            if start_idx == -1:
                return False
            
            result = None
            for end_idx in range(start_idx + 1, len(text) + 1):
                try:
                    candidate = text[start_idx:end_idx]
                    result = json.loads(candidate)
                    break
                except json.JSONDecodeError:
                    continue
            
            if result and result.get("completed"):
                print(f"[PASS] Goal completion verified: {result.get('reasoning', '')}")
                return True
            return False
        except Exception as e:
            print(f"[FAIL] Goal completion check failed: {e}")
            return False

    def _do_action(self, action_json, page):
        if isinstance(action_json, dict):
            action = action_json
        else:
            try:
                action = json.loads(re.search(r"\{.*\}", action_json, re.S).group())
            except Exception:
                print("[WARNING] Could not parse action, skipping")
            return

        t = action.get("type")
        locator = action.get("locator", {})
        txt = action.get("text") or action.get("value")
        direction = action.get("direction", "down")

        # Build Playwright locator
        pw_locator = None

        # locator with role → prefer role + name/text/aria-label/label
        if "role" in locator:
            role = locator["role"]

            name_candidate = (
                locator.get("name")
                or locator.get("text")
                or locator.get("aria-label")
                or locator.get("label")
            )
            try:
                if name_candidate:
                    # prefer exact match by accessible name 
                    pw_locator = page.get_by_role(role, name=name_candidate, exact=True)
                    if pw_locator.count() == 0:
                        # Try without exact match
                        pw_locator = page.get_by_role(role, name=name_candidate)
                    if pw_locator.count() == 0:
                        # If still nothing, try partial match with substring
                        words = name_candidate.split()
                        for word in words:
                            if len(word) > 3:
                                try:
                                    pw_locator = page.get_by_role(role).filter(has_text=word).first
                                    if pw_locator.count() > 0:
                                        break
                                except Exception:
                                    continue
                    if pw_locator.count() == 0:
                        if locator.get("aria-label"):
                            try:
                                # Special-case common editors that are DIVs with aria-label, e.g., comment boxes
                                if role == "div":
                                    pw_locator = page.locator(f'div[aria-label*="{locator.get("aria-label")}"]')
                                else:
                                    pw_locator = page.locator(f'[role="{role}"][aria-label*="{locator.get("aria-label")}"]')
                            except Exception:
                                pw_locator = None
                    
                    # Special handling for row elements - try to find clickable child
                    if role == "row" and pw_locator is not None and pw_locator.count() > 0:
                        try:
                            # Try to find a clickable link or button within the row
                            link = pw_locator.locator('a, button, [role="link"], [role="button"]').first
                            if link.count() > 0:
                                pw_locator = link
                        except Exception:
                            pass 
                else:
                    # no name provided — try role-only (may match multiple)
                    pw_locator = page.get_by_role(role)
            except Exception:
                if locator.get("aria-label"):
                    try:
                        if role == "div":
                            pw_locator = page.locator(f'div[aria-label*="{locator.get("aria-label")}"]')
                        else:
                            pw_locator = page.locator(f'[role="{role}"][aria-label*="{locator.get("aria-label")}"]')
                    except Exception:
                        pw_locator = None
                else:
                    try:
                        pw_locator = page.get_by_role(role)
                    except Exception:
                        pw_locator = None
            # If multiple matches, narrow to first visible
            try:
                if pw_locator is not None and pw_locator.count() > 1:
                    # prefer first visible element
                    first_vis = None
                    for i in range(pw_locator.count()):
                        cand = pw_locator.nth(i)
                        try:
                            if cand.is_visible():
                                first_vis = cand
                                break
                        except Exception:
                            continue
                    if first_vis is not None:
                        pw_locator = first_vis
                    else:
                        pw_locator = pw_locator.first
            except Exception:
                pass

        # aria-label locator (semantic accessible name for hint text)
        elif "aria-label" in locator and locator.get("aria-label"):
            al = locator.get("aria-label").strip()
            try:
                pw_locator = page.get_by_label(al)
            except Exception:
                try:
                    pw_locator = page.locator(f'[aria-label="{al}"]')
                except Exception:
                    pw_locator = None

        # placeholder locator (for gray hint text in empty inputs)
        elif "placeholder" in locator and locator.get("placeholder"):
            ph = locator.get("placeholder").strip()
            try:
                pw_locator = page.get_by_placeholder(ph)
            except Exception:
                try:
                    pw_locator = page.locator(f'[placeholder="{ph}"]')
                except Exception:
                    pw_locator = None

        # id or name fallback
        elif "id" in locator and locator.get("id"):
            sel = f'#{locator.get("id").strip()}'
            pw_locator = page.locator(sel)
        elif "name" in locator and locator.get("name"):
            sel = f'[name="{locator.get("name").strip()}"]'
            pw_locator = page.locator(sel)

        # locator with text only
        elif "text" in locator:
            pw_locator = page.get_by_text(locator["text"])

        # fallback string-based selector
        elif "selector" in locator:
            pw_locator = page.locator(locator["selector"])

        else:
            print(f"[WARNING] Unknown locator format: {locator}")
            return

        # Execute Playwright action based on type
        if t == "goto":
            url = action.get("url")
            if not url:
                print("[WARNING] goto action missing url")
                return
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            self._log_action(action)
            return
        
        elif t == "click":
            # Verify locator was found
            if pw_locator is None or pw_locator.count() == 0:
                print(f"[ERROR] Could not find element to click: {locator}")
                # Try to provide helpful debug info
                if locator.get("role") and locator.get("name"):
                    print(f"   Tried: role='{locator.get('role')}' with name='{locator.get('name')}'")
                if locator.get("aria-label"):
                    print(f"   Tried: aria-label='{locator.get('aria-label')}'")
                if locator.get("text"):
                    print(f"   Tried: text='{locator.get('text')}'")
                    
                # Last resort: finding by text content anywhere
                if locator.get("name") or locator.get("text") or locator.get("aria-label"):
                    search_text = locator.get("name") or locator.get("text") or locator.get("aria-label")
                    try:
                        fallback = page.get_by_text(search_text).first
                        if fallback.count() > 0 and fallback.is_visible():
                            print(f"  [INFO] Found via text search fallback")
                            pw_locator = fallback
                        else:
                            # Try a smart hint-based remap between aria-label and visible text
                            try:
                                hints = self._collect_dom_hints(page)
                                buttons = hints.get("buttons", [])
                                # If LLM supplied aria-label, try matching a button whose visible text differs
                                supplied = locator.get("aria-label") or locator.get("text") or locator.get("name")
                                matched_text = None
                                matched_aria = None
                                for b in buttons:
                                    if supplied and (b.get("aria-label") == supplied or b.get("text") == supplied):
                                        matched_text = b.get("text") or None
                                        matched_aria = b.get("aria-label") or None
                                        break
                                # Prefer trying the visible text first if available
                                try_names = []
                                if matched_text and matched_text != supplied:
                                    try_names.append(matched_text)
                                if matched_aria and matched_aria != supplied:
                                    try_names.append(matched_aria)

                                role = locator.get("role", "button")
                                for nm in try_names:
                                    try:
                                        alt = page.get_by_role(role, name=nm, exact=True)
                                        if alt.count() == 0:
                                            alt = page.get_by_role(role, name=nm)
                                        if alt.count() > 0 and alt.first.is_visible():
                                            pw_locator = alt.first
                                            print(f"  [INFO] Remapped click target via hints to name='{nm}'")
                                            break
                                    except Exception:
                                        continue
                                if pw_locator is None or pw_locator.count() == 0:
                                    return
                            except Exception:
                                return
                    except Exception:
                        return
                else:
                    return
            
            pw_locator.click()
            
            # If value is provided, this is a dropdown - click the button, then select the option
            if action.get("value"):
                option_value = action.get("value")
                page.wait_for_timeout(500)  # Wait for dropdown menu to appear
                
                option_clicked = False
                # Multiple strategies to find and click the option
                try:
                    # Strategy 1: Look for exact text match in menu items
                    option = page.get_by_role("menuitem", name=option_value, exact=True).or_(
                        page.get_by_role("option", name=option_value, exact=True)
                    )
                    if option.count() > 0:
                        option.first.click()
                        option_clicked = True
                        self._log_action(action, status=f"selected '{option_value}'")
                except Exception:
                    pass
                
                if not option_clicked:
                    try:
                        # Strategy 2: Non-exact match for menu items
                        option = page.get_by_role("menuitem", name=option_value).or_(
                            page.get_by_role("option", name=option_value)
                        )
                        if option.count() > 0:
                            option.first.click()
                            option_clicked = True
                            self._log_action(action, status=f"selected '{option_value}'")
                    except Exception:
                        pass
                
                if not option_clicked:
                    try:
                        # Strategy 3: Look for text anywhere (fallback)
                        option = page.get_by_text(option_value, exact=True).first
                        if option.count() > 0:
                            option.click()
                            option_clicked = True
                            self._log_action(action, status=f"selected '{option_value}'")
                    except Exception:
                        pass
                
                if not option_clicked:
                    print(f"[WARNING] Dropdown opened but could not find option '{option_value}'")
                    self._log_action(action, status=f"opened dropdown (option '{option_value}' not found)")
                
                # Wait for UI to update after selecting option
                page.wait_for_timeout(800)
            else:
                self._log_action(action)
            return

        elif t in ("fill", "type") and txt is not None:
            # If locator was not found but LLM requested an aria-label, try DOM hints fallback
            if pw_locator is None and isinstance(locator, dict):
                try:
                    hints = self._collect_dom_hints(page)
                    # If LLM provided an aria-label, try to find a matching input from hints
                    al = (locator.get("aria-label") or "").strip()
                    if al:
                        for inp in hints.get("inputs", []):
                            if inp.get("aria-label") == al or inp.get("name") == al:
                                # prefer id -> name -> aria-label
                                if inp.get("id"):
                                    sel = f'#{inp.get("id")}'
                                    try:
                                        pw_locator = page.locator(sel)
                                        break
                                    except Exception:
                                        pw_locator = None
                                if inp.get("name") and pw_locator is None:
                                    sel = f'[name="{inp.get("name")}"]'
                                    try:
                                        pw_locator = page.locator(sel)
                                        break
                                    except Exception:
                                        pw_locator = None
                                if inp.get("aria-label") and pw_locator is None:
                                    try:
                                        pw_locator = page.get_by_label(inp.get("aria-label"))
                                        break
                                    except Exception:
                                        try:
                                            pw_locator = page.locator(f'[aria-label="{inp.get("aria-label")}"]')
                                            break
                                        except Exception:
                                            pw_locator = None
                except Exception:
                    pw_locator = None

            if pw_locator is not None:
                cleaned_txt = self._normalize_fill_text(pw_locator, txt)
                if not self._should_fill(pw_locator):
                    print("[INFO] Field already has text, skipping fill")
                    self._log_action(action, status="skipped (already filled)")
                    return
                try:
                    # If it's a contenteditable div, prefer keyboard typing
                    try:
                        is_contenteditable = pw_locator.evaluate("el => el.isContentEditable === true")
                    except Exception:
                        is_contenteditable = False

                    if is_contenteditable:
                        pw_locator.click()
                        page.keyboard.type(cleaned_txt, delay=15)
                    else:
                        pw_locator.fill(cleaned_txt)
                    self._log_action(action)
                    # Try to submit if this looks like a comment/input box
                    try:
                        sub = page.get_by_role("button").filter(has_text=re.compile("^(Post|Comment|Save|Send|Submit|Add|Create|Update)$", re.I)).first
                        if sub.count() > 0 and sub.is_visible():
                            sub.click()
                            print("[INFO] Auto-clicked submit button after fill")
                            page.wait_for_timeout(800)
                    except Exception:
                        try:
                            # Press Enter in text areas or editors that accept Enter to submit
                            tag = pw_locator.evaluate("el => el.tagName.toLowerCase()")
                            if tag in ["textarea"]:
                                page.keyboard.press("Enter")
                                page.wait_for_timeout(500)
                        except Exception:
                            pass
                    return
                except Exception:
                    try:
                        pw_locator.click()
                        page.keyboard.type(cleaned_txt, delay=15)
                        self._log_action(action)
                        # Attempt auto submit as above
                        try:
                            sub = page.get_by_role("button").filter(has_text=re.compile("^(Post|Comment|Save|Send|Submit|Add|Create|Update)$", re.I)).first
                            if sub.count() > 0 and sub.is_visible():
                                sub.click()
                                print("[INFO] Auto-clicked submit button after type")
                                page.wait_for_timeout(800)
                        except Exception:
                            try:
                                page.keyboard.press("Enter")
                                page.wait_for_timeout(500)
                            except Exception:
                                pass
                        return
                    except Exception:
                        pass

            editable = page.locator(
                '[contenteditable="true"], textarea, input, div[role="textbox"]'
            ).filter(has_text="").first

            if editable.count() > 0:
                if self._should_fill(editable):
                    editable.click()
                    page.keyboard.type(txt, delay=15)
                    self._log_action(action)
                    # Try to submit via common buttons or Enter
                    try:
                        sub = page.get_by_role("button").filter(has_text=re.compile("^(Post|Comment|Save|Send|Submit|Add|Create|Update)$", re.I)).first
                        if sub.count() > 0 and sub.is_visible():
                            sub.click()
                            print("[INFO] Auto-clicked submit button after editable type")
                            page.wait_for_timeout(800)
                    except Exception:
                        try:
                            page.keyboard.press("Enter")
                            page.wait_for_timeout(500)
                        except Exception:
                            pass
                else:
                    print("[INFO] Editable already has text, skipping") 
                    self._log_action(action, status="skipped (already filled)")
                return

            print("[WARNING] No editable area found for typing")
            return

        elif t == "select" and txt is not None:
            if pw_locator is None:
                print("[WARNING] No locator for select")
                return

            try:
                tag = pw_locator.evaluate("el => el.tagName.toLowerCase()")
                if tag == "select":
                    pw_locator.select_option(txt)
                    self._log_action(action)
                    return
            except Exception:
                pass 

            # Custom dropdown fallback:
            pw_locator.click()
            page.wait_for_timeout(400)
            
            # find the text node first
            text_node = page.get_by_text(txt, exact=True).first

            if text_node.count() > 0:
                # climb to a clickable parent row
                clickable = text_node.locator(
                    "xpath=ancestor-or-self::*[@role='option' or @role='menuitem' or self::button or self::div][1]"
                )

                try:
                    clickable.click(timeout=5000)
                    self._log_action(action)
                    return
                except Exception:
                    clickable.click(force=True)
                    self._log_action(action, status="done (force click)")
                    return

            page.keyboard.type(txt, delay=15)
            page.keyboard.press("Enter")
            self._log_action(action, status="done (keyboard fallback)")
            return

        elif t == "scroll":
            page.mouse.wheel(0, 800 if direction == "down" else -800)   
            self._log_action(action)
            return

        elif t == "wait":
            page.wait_for_timeout(1500) 
            self._log_action(action)
            return

        else:
            print(f"[WARNING] Unknown action type: {t}")

    def _slug(self, s):
        return re.sub(r"[^a-z0-9]+", "_", s.lower())[:45]

    def _remove_app_name_from_question(self, question: str, app_name: str):
        """
        Remove app name from question since it's redundant in folder structure.
        E.g., "create a project in Linear" -> "create a project"
        """
        question_lower = question.lower()
        app_lower = app_name.lower()
    
        # Common patterns: "in {app}", "to {app}", "on {app}", "using {app}", "from {app}"
        patterns = [
            f" in {app_lower}",
            f" to {app_lower}",
            f" on {app_lower}",
            f" using {app_lower}",
            f" from {app_lower}",
            f" at {app_lower}",
            f" with {app_lower}",
        ]
    
        cleaned = question_lower
        for pattern in patterns:
            if pattern in cleaned:
                cleaned = cleaned.replace(pattern, "")
    
        # Also remove app name if it appears at the end without preposition
        if cleaned.endswith(f" {app_lower}"):
            cleaned = cleaned[:-len(app_lower)].rstrip()
    
        return cleaned.strip() or question

    def _normalize_fill_text(self, pw_locator, txt: str):
        """Strip placeholder/prefill prefixes from txt in a generic way."""
        txt = (txt or "").strip()

        # 1) actual current value (NOT placeholder)
        try:
            current = pw_locator.input_value().strip()
        except Exception:
            current = ""

        # 2) placeholder text (gray hint)
        try:
            placeholder = (pw_locator.get_attribute("placeholder") or "").strip()
        except Exception:
            placeholder = ""

        # If field already has a real prefix typed, strip repeats
        if current and txt.startswith(current):
            return txt[len(current):].lstrip("/")

        # If placeholder exists and txt repeats it, strip repeats
        if placeholder and txt.startswith(placeholder):
            return txt[len(placeholder):].lstrip("/")

        if placeholder.endswith("/") and txt.startswith(placeholder):
            return txt[len(placeholder):].lstrip("/")

        return txt

    def _should_fill(self, pw_locator) -> bool:
        """
        Return True only if the target looks empty.
        Works for inputs/textareas and rich editors.
        """
        try:
            current = pw_locator.input_value().strip()
            if current:
                return False
            return True
        except Exception:
            pass

        try:
            current_text = pw_locator.inner_text().strip()
            if current_text:
                return False
            return True
        except Exception:
            return True 
        
    def _log_action(self, action, status="done"):
        t = action.get("type")
        loc = action.get("locator", {})
        target = (
            loc.get("name")
            or loc.get("aria-label")
            or loc.get("text")
            or loc.get("css")
            or "unknown target"
        )
        print(f"[{status.upper()}] {t.upper()} on [{target}]\n")
    
    def _init_readme(self, task_folder: Path, question: str, app_name: str):
        """Initialize README.md with task overview"""
        readme_path = task_folder / "README.md"
        content = f"""# Task: {question}

**Application:** {app_name}

## Steps
"""
        readme_path.write_text(content, encoding="utf-8")
        return readme_path
    
    def _append_step_to_readme(self, readme_path: Path, step_num: int, action: dict, status: str):
        """Generate a short step summary using LLM and append to README"""
        action_type = action.get("type", "unknown")
        label = action.get("label", f"step_{step_num}")
        locator = action.get("locator", {})
        text = action.get("text", "")
        
        # Build a context string for the LLM
        locator_desc = (
            locator.get("aria-label") or 
            locator.get("name") or 
            locator.get("text") or 
            locator.get("placeholder") or 
            "element"
        )
        
        # Use LLM to generate a concise step summary
        prompt = f"""Generate a single short sentence (under 100 characters) describing this UI automation step:
                Action: {action_type}
                Target: {locator_desc}
                Text entered: {text if text else "N/A"}
                Status: {status}

                Return ONLY the sentence, no formatting or extra text."""
        
        try:
            resp = self.llm.invoke([{"role": "user", "content": prompt}])
            summary = resp.content.strip()
        except Exception:
            # Fallback if LLM fails
            summary = f"{action_type} on {locator_desc}" + (f" with '{text}'" if text else "")
        
        # Append to README
        step_line = f"{step_num}. {summary} [{status}]\n"
        with open(readme_path, "a", encoding="utf-8") as f:
            f.write(step_line)
    
    def _finalize_readme(self, readme_path: Path, success: bool, reasoning: str = ""):
        """Add completion summary to README"""
        status_line = "\n## Result\n\n"
        if success:
            status_line += f"**Status:** Completed successfully\n"
        else:
            status_line += f"**Status:** Failed\n"
        
        if reasoning:
            status_line += f"**Details:** {reasoning}\n"
        
        with open(readme_path, "a", encoding="utf-8") as f:
            f.write(status_line)
