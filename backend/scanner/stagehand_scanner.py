"""Stagehand-based chat scanner — find, open, and interact with any chatbot.

Uses Browserbase Stagehand v3 SDK for reliable browser automation.
Stagehand handles iframes, shadow DOM, and complex DOM automatically.
"""

import asyncio
import os
from typing import Optional, Callable, Awaitable

from dotenv import load_dotenv
from stagehand import AsyncStagehand

load_dotenv()


class StagehandScanner:
    """Manages a Stagehand browser session for scanning a chatbot."""

    def __init__(self, debug_cb: Optional[Callable[[str], Awaitable[None]]] = None):
        self._debug = debug_cb
        self.client: Optional[AsyncStagehand] = None
        self.session = None
        self.session_id: Optional[str] = None
        self._seen_responses: set[str] = set()  # track all responses to detect stale reads

    async def _log(self, msg: str):
        print(f"[stagehand] {msg}")
        if self._debug:
            try:
                await self._debug(msg)
            except Exception:
                pass

    async def init(self):
        """Initialize Stagehand client and start a session."""
        await self._log("Initializing Stagehand...")
        self.client = AsyncStagehand(
            browserbase_api_key=os.getenv("BROWSERBASE_API_KEY"),
            browserbase_project_id=os.getenv("BROWSERBASE_PROJECT_ID"),
            model_api_key=os.getenv("ANTHROPIC_API_KEY"),
        )
        self.session = await self.client.sessions.start(
            model_name="anthropic/claude-sonnet-4-20250514",
            self_heal=True,
            wait_for_captcha_solves=True,
            dom_settle_timeout_ms=5000,
            browserbase_session_create_params={
                "browser_settings": {
                    "solve_captchas": True,
                    "block_ads": True,
                    "record_session": True,
                    "viewport": {"width": 1280, "height": 720},
                },
            },
        )
        self.session_id = self.session.id
        await self._log(f"Session started: {self.session_id}")
        await self._log(f"Live view: https://www.browserbase.com/sessions/{self.session_id}")

    async def close(self):
        """End the Stagehand session."""
        if self.session:
            try:
                await self.session.end()
                await self._log("Session ended")
            except Exception:
                pass

    async def navigate(self, url: str):
        """Navigate to the target URL and trigger lazy-loaded widgets."""
        await self.session.navigate(url=url)
        await self._log(f"Navigated to {url}")

        # Single scroll action to trigger lazy-loaded widgets (reduces API calls)
        await asyncio.sleep(3)
        try:
            await self.session.act(input="scroll down to the bottom of the page and then scroll back to the top")
            await asyncio.sleep(3)
            await self._log("Scrolled page to trigger widgets")
        except Exception:
            await asyncio.sleep(3)

    async def dismiss_cookies(self):
        """Try to dismiss cookie consent banners."""
        try:
            await self.session.act(
                input="click the Accept or Confirm button on the cookie consent banner",
            )
            await self._log("Cookie banner dismissed")
        except Exception:
            await self._log("No cookie banner found or already dismissed")

    async def find_and_open_chat(self) -> bool:
        """Find and open the chat widget. Returns True if chat input is ready."""

        # Step 1: Find and click the chat launcher
        launcher_found = await self._find_and_click_launcher()
        if not launcher_found:
            return False

        # Step 2: Navigate to conversation view — handle menus, forms, overlays
        for attempt in range(3):
            await self._log(f"Checking chat readiness (attempt {attempt + 1})...")

            # First, try to dismiss any blockers (email forms, menus, overlays)
            # Do this BEFORE checking for chat input, because the blocker
            # might be covering the real chat input
            if attempt > 0:
                await self._dismiss_blockers()
                await asyncio.sleep(2)

            # Now check if the actual chat message input is available
            if await self._is_chat_ready():
                await self._log("Chat is ready for messages")
                return True

        await self._log("Could not reach chat input after all attempts")
        return False

    async def _find_and_click_launcher(self) -> bool:
        """Find the chat widget launcher and click it."""
        # Attempt 1: Look for chat launcher directly
        try:
            observe_resp = await self.session.observe(
                instruction="find a floating chat widget button, chatbot launcher icon, or live chat bubble on this page",
            )
            results = observe_resp.data.result
            if results:
                await self._log(f"Found {len(results)} chat elements")
                action = results[0].to_dict(exclude_none=True) if hasattr(results[0], 'to_dict') else results[0]
                await self.session.act(input=action)
                await asyncio.sleep(2)
                await self._log("Clicked chat launcher")
                return True
        except Exception as e:
            await self._log(f"Launcher search: {e}")

        # Attempt 2: Scroll and try again
        try:
            await self.session.act(input="scroll down to the bottom of the page and then scroll back to the top")
            await asyncio.sleep(3)
        except Exception:
            pass

        try:
            observe_resp = await self.session.observe(
                instruction="find a floating chat widget button, chatbot launcher icon, or live chat bubble on this page",
            )
            results = observe_resp.data.result
            if results:
                await self._log(f"Found {len(results)} chat elements after scroll")
                action = results[0].to_dict(exclude_none=True) if hasattr(results[0], 'to_dict') else results[0]
                await self.session.act(input=action)
                await asyncio.sleep(2)
                await self._log("Clicked chat launcher")
                return True
        except Exception:
            pass

        # Fallback: direct click attempt
        try:
            await self.session.act(
                input="click the chat widget button in the bottom-right corner of the page",
            )
            await asyncio.sleep(2)
            await self._log("Clicked chat launcher via fallback")
            return True
        except Exception:
            await self._log("No chat widget found")
            return False

    async def _is_chat_ready(self) -> bool:
        """Check if the chat message textarea/input is available.

        Specifically looks for a MESSAGE input, not an email/name form field.
        """
        try:
            observe_resp = await self.session.observe(
                instruction=(
                    "find the textarea or text input where a user types chat messages to send to the chatbot. "
                    "This input typically has a placeholder like 'Type your message', 'Compose your message', "
                    "'Ask a question', 'Type here', or 'Send a message'. "
                    "Do NOT return email input fields, name input fields, search bars, or form fields. "
                    "Only return the chat message composition input."
                ),
            )
            results = observe_resp.data.result
            if results:
                desc = results[0].get("description", "") if isinstance(results[0], dict) else str(results[0])
                await self._log(f"Chat input found: {desc[:60]}")
                return True
        except Exception:
            pass
        return False

    async def _dismiss_blockers(self):
        """Dismiss anything blocking the chat: modals, email forms, menus.

        Tries strategies in order of preference:
        1. Skip/close/dismiss any modal or overlay
        2. Click a menu option to start conversation
        3. Fill and submit email form as last resort
        """
        # Strategy 1: Skip, Close, or Dismiss any modal/overlay/popup
        try:
            await self.session.act(
                input="click the Skip, Close, Dismiss, No thanks, or X button on any popup, modal, or overlay in the chat widget",
            )
            await self._log("Dismissed blocker via Skip/Close")
            await asyncio.sleep(2)
            return
        except Exception:
            pass

        # Strategy 2: Click a conversation-starting menu option
        try:
            await self.session.act(
                input="click the button or link to start a new chat conversation with the AI chatbot",
            )
            await self._log("Clicked conversation starter")
            await asyncio.sleep(2)
            return
        except Exception:
            pass

        # Strategy 3: Fill and submit email form
        try:
            await self.session.act(
                input="type 'test@scanner.local' into the email input field",
            )
            await asyncio.sleep(0.5)
        except Exception:
            return

        try:
            await self.session.act(input="check any consent or privacy checkboxes")
        except Exception:
            pass

        try:
            await self.session.act(input="click the Send or Submit button")
            await self._log("Submitted pre-chat form")
            await asyncio.sleep(2)
        except Exception:
            pass

    async def send_message(self, message: str) -> bool:
        """Type a message into the chat input and send it."""
        try:
            await self.session.act(
                input=f'type "{message}" into the chat message textarea',
            )
            await self._log("Message typed")

            await self.session.act(
                input="press the Enter key to send the chat message",
            )
            await self._log("Message sent")
            return True
        except Exception as e:
            await self._log(f"Failed to send message: {type(e).__name__}: {e}")
            return False

    async def read_response(self, sent_message: str) -> Optional[str]:
        """Read the chatbot's response after sending a message."""
        await asyncio.sleep(3)

        for attempt in range(3):
            try:
                extract_resp = await self.session.extract(
                    instruction=(
                        "In the chat widget, find the most recent message from the CHATBOT or AI ASSISTANT. "
                        "Chat widgets show two types of messages: USER messages (sent by the visitor, "
                        "usually on the right side or in a colored bubble) and BOT messages (from the "
                        "chatbot/assistant, usually on the left side or in a different colored bubble). "
                        f"The user just sent: '{sent_message[:50]}'. "
                        "Do NOT extract this user message. Extract only the BOT's reply. "
                        "If the bot has not replied yet, set response_found to false."
                    ),
                    schema={
                        "type": "object",
                        "properties": {
                            "chatbot_response": {
                                "type": "string",
                                "description": "The full text of the chatbot/AI assistant's most recent reply message, NOT the user's message",
                            },
                            "response_found": {
                                "type": "boolean",
                                "description": "True only if a chatbot/bot response was found that is different from the user's sent message",
                            },
                        },
                        "required": ["chatbot_response", "response_found"],
                    },
                )
                result = extract_resp.data.result
                await self._log(f"Extract attempt {attempt + 1}: {result}")

                if isinstance(result, dict):
                    if result.get("response_found") and result.get("chatbot_response", "").strip():
                        text = result["chatbot_response"].strip()
                        # Check if this is a stale/previously seen response
                        if text in self._seen_responses:
                            await self._log(f"Stale response detected (seen before): {text[:40]}...")
                            continue  # Try again — might get the real new response
                        self._seen_responses.add(text)
                        await self._log(f"Response: {text[:60]}...")
                        return text
            except Exception as e:
                await self._log(f"Extract attempt {attempt + 1} failed: {type(e).__name__}: {e}")

            if attempt < 2:
                await asyncio.sleep(3)

        await self._log("No response received")
        return None

    async def send_and_read(self, message: str) -> Optional[str]:
        """Send a message and read the chatbot's response."""
        sent = await self.send_message(message)
        if not sent:
            return None
        return await self.read_response(message)
