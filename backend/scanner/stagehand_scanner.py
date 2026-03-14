"""Stagehand-based chat scanner — find, open, and interact with any chatbot.

Uses Browserbase Stagehand v3 SDK for reliable browser automation.
Stagehand handles iframes, shadow DOM, and complex DOM automatically.
"""

import asyncio
import os
from typing import Optional, Callable, Awaitable

from stagehand import AsyncStagehand


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
            await self._debug(msg)

    async def init(self):
        """Initialize Stagehand client and start a session."""
        self.client = AsyncStagehand(
            browserbase_api_key=os.getenv("BROWSERBASE_API_KEY"),
            browserbase_project_id=os.getenv("BROWSERBASE_PROJECT_ID"),
            model_api_key=os.getenv("ANTHROPIC_API_KEY"),
        )

        self.session = await self.client.sessions.create(
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
        await asyncio.sleep(5)  # Wait for dynamic content / chat widgets to load

    async def dismiss_cookies(self):
        """Try to dismiss cookie consent banners."""
        try:
            await self.session.act(
                input="If there is a cookie consent banner or popup, click Accept/Confirm/OK to dismiss it. If there is no cookie banner, do nothing.",
            )
            await self._log("Cookie dismissal attempted")
        except Exception:
            pass

    async def find_and_open_chat(self) -> bool:
        """Find and open the chat widget, navigating through any menus.

        Returns True if a chat input is ready for messaging.
        """
        # Step 1: Look for a chat widget
        await self._log("Looking for chat widget...")
        try:
            observe_resp = await self.session.observe(
                instruction="Find a chat widget, chatbot launcher button, or AI assistant icon on this page. "
                "Look for floating buttons in corners, chat bubbles, or 'Chat with us' buttons. "
                "Do NOT select search bars, contact forms, or navigation links.",
            )
            results = observe_resp.data.result
            if not results:
                await self._log("No chat widget found via observe")
                return False
            await self._log(f"Found {len(results)} potential chat elements")
        except Exception as e:
            await self._log(f"Observe failed: {e}")
            return False

        # Step 2: Click to open the widget
        try:
            await self.session.act(
                input="Click on the chat widget launcher button or chat icon to open the chat conversation. "
                "If the chat is already open showing a text input, do nothing.",
            )
            await asyncio.sleep(3)
            await self._log("Clicked chat launcher")
        except Exception as e:
            await self._log(f"Failed to click launcher: {e}")

        # Step 3: Navigate through any menu/home screen to the conversation
        for attempt in range(3):
            # Check if we can find a text input for messages
            try:
                observe_resp = await self.session.observe(
                    instruction="Find a text input field where I can type a chat message. "
                    "It should be a textarea or input with placeholder like 'Type your message', "
                    "'Compose your message', 'Ask a question', 'Type here'. "
                    "Do NOT select email inputs, search bars, or form fields.",
                )
                results = observe_resp.data.result
                if results:
                    await self._log("Chat input found — ready to send messages")
                    return True
            except Exception:
                pass

            # Not ready — try clicking through menu options
            try:
                await self.session.act(
                    input="In the chat widget, click the option that will start a conversation. "
                    "Look for buttons like 'Chat', 'Talk to us', 'Ask AI', 'Start conversation', 'Message us'. "
                    "Avoid 'FAQ', 'Help Center', 'Documentation', 'Pricing' links.",
                )
                await asyncio.sleep(3)
                await self._log(f"Clicked menu option (attempt {attempt + 1})")
            except Exception:
                break

        # Step 4: Handle pre-chat forms (email gates)
        try:
            await self.session.act(
                input="If there is a form asking for email address or name before chatting, "
                "fill the email field with 'test@scanner.local', check any consent checkboxes, "
                "and click the Send/Submit/Start button. If there is no form, do nothing.",
            )
            await asyncio.sleep(3)
        except Exception:
            pass

        # Final check for chat input
        try:
            observe_resp = await self.session.observe(
                instruction="Find a text input field for typing chat messages.",
            )
            results = observe_resp.data.result
            if results:
                await self._log("Chat input found after form handling")
                return True
        except Exception:
            pass

        await self._log("Could not find chat input after all attempts")
        return False

    async def send_message(self, message: str) -> bool:
        """Type a message into the chat input and send it."""
        try:
            # Use act with the exact message to type
            await self.session.act(
                input=f'Type the following text into the chat message input field and press Enter to send it: "{message}"',
            )
            await self._log("Message sent")
            return True
        except Exception as e:
            await self._log(f"Failed to send message: {e}")
            return False

    async def read_response(self, sent_message: str) -> Optional[str]:
        """Read the chatbot's response after sending a message."""
        await asyncio.sleep(3)  # Wait for response to render

        for attempt in range(3):
            try:
                extract_resp = await self.session.extract(
                    instruction=f"Extract the chatbot's most recent response message. "
                    f"I just sent: '{sent_message[:80]}'. "
                    f"Read the bot's reply, NOT my own message. "
                    f"The bot's response is typically in a different color or alignment from user messages. "
                    f"If the bot hasn't responded yet, return empty string.",
                    schema={
                        "type": "object",
                        "properties": {
                            "response_text": {
                                "type": "string",
                                "description": "The chatbot's most recent response text, or empty string if no response",
                            },
                        },
                        "required": ["response_text"],
                    },
                )
                result = extract_resp.data.result
                if isinstance(result, dict):
                    text = result.get("response_text", "")
                    if text and text.strip():
                        await self._log(f"Response: {text[:60]}...")
                        return text.strip()
            except Exception as e:
                await self._log(f"Extract attempt {attempt + 1} failed: {e}")

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
