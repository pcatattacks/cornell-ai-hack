"""Stagehand-based chat scanner — find, open, and interact with any chatbot.

Uses Browserbase Stagehand v3 SDK for reliable browser automation.
Stagehand handles iframes, shadow DOM, and complex DOM automatically.

Best practices applied:
- One action per act() call
- Observe+act pattern for 2-3x speed
- Specific action verbs (click, type, press)
- Descriptive extract() schemas
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
        self._chat_input_action = None  # cached observe result for observe+act pattern

    async def _log(self, msg: str):
        print(f"[stagehand] {msg}")
        if self._debug:
            try:
                await self._debug(msg)
            except Exception:
                pass  # WebSocket might be closed

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
        """Navigate to the target URL."""
        await self.session.navigate(url=url)
        await self._log(f"Navigated to {url}")
        await asyncio.sleep(5)  # Wait for chat widgets to lazy-load

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

        # Step 1: Observe for chat launcher
        await self._log("Looking for chat widget...")
        try:
            observe_resp = await self.session.observe(
                instruction="find the chat widget launcher button or chatbot icon on this page",
            )
            results = observe_resp.data.result
            if not results:
                await self._log("No chat widget found")
                return False
            await self._log(f"Found {len(results)} potential chat elements")

            # Use observe+act pattern: act on the observed element (no LLM inference)
            first_action = results[0].to_dict(exclude_none=True) if hasattr(results[0], 'to_dict') else results[0]
            await self.session.act(input=first_action)
            await asyncio.sleep(3)
            await self._log("Clicked chat launcher via observe+act")
        except Exception as e:
            await self._log(f"Chat launcher click failed: {type(e).__name__}: {e}")
            # Try direct act as fallback
            try:
                await self.session.act(
                    input="click the chat widget button in the bottom-right corner of the page",
                )
                await asyncio.sleep(3)
                await self._log("Clicked chat launcher via direct act")
            except Exception as e2:
                await self._log(f"Direct act also failed: {e2}")
                return False

        # Step 2: Navigate through menus if needed, find the chat input
        for attempt in range(3):
            try:
                observe_resp = await self.session.observe(
                    instruction="find the text input field for typing chat messages in the chat widget",
                )
                results = observe_resp.data.result
                if results:
                    # Cache the input action for fast sending later
                    self._chat_input_action = results[0].to_dict(exclude_none=True) if hasattr(results[0], 'to_dict') else results[0]
                    await self._log("Chat input found — ready to send messages")
                    return True
            except Exception:
                pass

            # Try clicking through menu
            try:
                await self.session.act(
                    input="click the button to start a new chat conversation in the chat widget",
                )
                await asyncio.sleep(3)
                await self._log(f"Clicked menu option (attempt {attempt + 1})")
            except Exception:
                break

        # Step 3: Handle email/name forms
        try:
            await self.session.act(
                input="type 'test@scanner.local' into the email input field in the chat widget",
            )
            await asyncio.sleep(0.5)
            await self.session.act(
                input="check any consent or GDPR checkboxes in the chat widget",
            )
            await asyncio.sleep(0.5)
            await self.session.act(
                input="click the Send or Submit button in the chat widget form",
            )
            await asyncio.sleep(3)
            await self._log("Filled pre-chat form")
        except Exception:
            pass

        # Final check
        try:
            observe_resp = await self.session.observe(
                instruction="find the text input field for typing chat messages",
            )
            results = observe_resp.data.result
            if results:
                self._chat_input_action = results[0].to_dict(exclude_none=True) if hasattr(results[0], 'to_dict') else results[0]
                await self._log("Chat input found after form handling")
                return True
        except Exception:
            pass

        await self._log("Could not find chat input")
        return False

    async def send_message(self, message: str) -> bool:
        """Type a message into the chat input and send it."""
        try:
            # Type the message
            await self.session.act(
                input=f'type "{message}" into the chat message input field',
            )
            await self._log("Message typed")

            # Send via Enter key
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
        await asyncio.sleep(3)  # Wait for chatbot to generate response

        for attempt in range(3):
            try:
                extract_resp = await self.session.extract(
                    instruction="extract the text of the most recent chatbot response message in the chat widget, not the user's message",
                    schema={
                        "type": "object",
                        "properties": {
                            "chatbot_response": {
                                "type": "string",
                                "description": "The full text of the chatbot's most recent reply message",
                            },
                            "response_found": {
                                "type": "boolean",
                                "description": "True if a chatbot response message was found, false if only user messages are visible",
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
