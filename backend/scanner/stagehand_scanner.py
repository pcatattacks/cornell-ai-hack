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
        """Navigate to the target URL and simulate user behavior to trigger lazy widgets."""
        await self.session.navigate(url=url)
        await self._log(f"Navigated to {url}")

        # Simulate real user browsing to trigger lazy-loaded chat widgets
        await asyncio.sleep(3)
        try:
            await self.session.act(input="scroll down halfway on the page")
            await asyncio.sleep(2)
            await self.session.act(input="scroll down to the bottom of the page")
            await asyncio.sleep(2)
            await self.session.act(input="scroll back to the top of the page")
            await asyncio.sleep(3)
            await self._log("Simulated user scrolling to trigger widgets")
        except Exception:
            await asyncio.sleep(5)

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
        for attempt in range(5):
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
        """Find the chat widget launcher and click it. Retries with scroll."""
        for attempt in range(3):
            try:
                observe_resp = await self.session.observe(
                    instruction="find a floating chat widget button, chatbot launcher icon, or live chat bubble on this page",
                )
                results = observe_resp.data.result
                if results:
                    await self._log(f"Found {len(results)} chat elements (attempt {attempt + 1})")
                    action = results[0].to_dict(exclude_none=True) if hasattr(results[0], 'to_dict') else results[0]
                    await self.session.act(input=action)
                    await asyncio.sleep(3)
                    await self._log("Clicked chat launcher")
                    return True
            except Exception as e:
                await self._log(f"Launcher search attempt {attempt + 1}: {e}")

            # Scroll to trigger lazy widgets
            try:
                await self.session.act(input="scroll down to the bottom of the page")
                await asyncio.sleep(3)
                await self.session.act(input="scroll back to the top of the page")
                await asyncio.sleep(3)
            except Exception:
                await asyncio.sleep(3)

        # Final fallback — direct act
        try:
            await self.session.act(
                input="click the chat widget button in the bottom-right corner of the page",
            )
            await asyncio.sleep(3)
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
        """Dismiss anything blocking the chat: menus, email forms, overlays.

        Each action is independent — if one fails, try the next.
        """
        # Try clicking a conversation-starting menu option
        try:
            await self.session.act(
                input="click the button or link to start a new chat conversation with the AI chatbot",
            )
            await self._log("Clicked conversation starter")
            await asyncio.sleep(2)
            return
        except Exception:
            pass

        # Try filling and submitting an email/name form
        try:
            await self.session.act(
                input="type 'test@scanner.local' into the email input field",
            )
            await asyncio.sleep(0.5)
        except Exception:
            return  # No email field — nothing more to dismiss

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
                        "extract the text of the most recent chatbot response message "
                        "in the chat widget. Return the bot's reply, not the user's message."
                    ),
                    schema={
                        "type": "object",
                        "properties": {
                            "chatbot_response": {
                                "type": "string",
                                "description": "The full text of the chatbot's most recent reply",
                            },
                            "response_found": {
                                "type": "boolean",
                                "description": "True if a chatbot response was found",
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
