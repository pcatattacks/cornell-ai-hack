"""Stagehand-based chat scanner — find, open, and interact with any chatbot.

Three-phase architecture:
  Phase 1: Agent-driven setup — dismiss overlays, find + open chatbot widget
  Phase 2: Observe-then-act sending — cached send button, template variables for typing
  Phase 3: Simple extraction reading — proven schema, polling with stale detection

Uses Browserbase Stagehand v3 SDK for reliable browser automation.
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
        self._seen_responses: set[str] = set()
        self._cached_send_action = None  # observed send button, reused for all messages
        self.human_detected = False  # set when human agent handoff is detected
        self.send_blocked = False  # set when messages are being blocked/rejected
        self._consecutive_recovery_failures = 0  # skip recovery after 2 consecutive failures

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
            model_api_key=os.getenv("GOOGLE_API_KEY"),
        )
        self.session = await self.client.sessions.start(
            model_name="google/gemini-2.5-flash",
            self_heal=True,
            wait_for_captcha_solves=True,
            dom_settle_timeout_ms=5000,
            browserbase_session_create_params={
                "browser_settings": {
                    "solve_captchas": True,
                    "block_ads": True,
                    "record_session": True,
                    "viewport": {"width": 1288, "height": 711},
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

    # ── Phase 0: Navigation ──────────────────────────────────────────────

    async def navigate(self, url: str):
        """Navigate to the target URL and wait for page load."""
        await self.session.navigate(url=url)
        await self._log(f"Navigated to {url}")
        # Wait for time-based widget loaders (most fire within 3-5s)
        await asyncio.sleep(5)

    # ── Phase 1: Agent-driven setup ──────────────────────────────────────

    async def find_and_open_chat(self) -> bool:
        """Use Stagehand agent to find and open the chatbot.

        The agent handles the unpredictable setup: dismissing overlays/cookies,
        finding the widget, navigating menus, filling email gates. No pre-pass
        overlay dismissal — the agent handles everything in one execution.
        """
        try:
            await self._log("Starting agent-driven chatbot setup...")
            await self.session.execute(
                agent_config={
                    "model": "google/gemini-2.5-flash",
                },
                execute_options={
                    "instruction": (
                        "Your goal is to find and open the AI chatbot on this page so I can type messages to it.\n\n"
                        "IMPORTANT: You are looking for a REAL, INTERACTIVE chat widget — NOT screenshots, "
                        "images, videos, or demos of chatbots that are part of the page's marketing content. "
                        "The real chat widget is typically a small floating element overlaid on the page, not "
                        "embedded in the main page layout.\n\n"
                        "Step 1: If any popups, cookie banners, or modals are blocking the page, dismiss them "
                        "(click Accept, Close, Skip, X, or 'No thanks').\n\n"
                        "Step 2: Look for the chat widget. It could appear as:\n"
                        "  - A floating bubble or icon in the bottom-right or bottom-left corner\n"
                        "  - A 'Chat with us' or 'Ask AI' button fixed to the screen edge\n"
                        "  - A chat bar or search-style input in the center of the page (like ChatGPT or assistant-ui)\n"
                        "  - A support/help widget icon\n"
                        "If you don't see one immediately, scroll down to the bottom of the page and back up "
                        "to trigger lazy-loaded widgets, then look again.\n\n"
                        "Step 3: Click to open the chat widget if it's collapsed or minimized.\n\n"
                        "Step 4: If the chat shows a menu, home screen, or conversation picker (buttons like "
                        "'Chat', 'Talk to us', 'Ask AI', 'New conversation', 'Send us a message'), click the "
                        "option that starts a new conversation.\n\n"
                        "Step 5: If asked for an email address or name, type 'test@scanner.local' for email "
                        "and 'Test' for name, then submit. If there's a Skip button, click Skip instead.\n\n"
                        "Step 6: Wait a moment for the chat to fully load and any animations to finish. "
                        "Then click on the chat message input field to confirm it is interactive. "
                        "Only stop once you have successfully clicked the input and it is ready for typing.\n\n"
                        "Do NOT type any chat messages — just get the chat ready for messaging."
                    ),
                    "max_steps": 15,
                },
            )
            await self._log("Agent setup completed")

            # Validate the chat input is in the DOM and findable by act().
            # The agent and act() resolve elements independently — the agent
            # confirming the input is interactive doesn't guarantee act() can
            # find it. This observe() also provides natural timing for any
            # remaining animations to settle.
            observe_resp = await self.session.observe(
                instruction=(
                    "find the textarea or text input where a user types chat messages to send. "
                    "This input typically has a placeholder like 'Type your message', 'Ask a question', "
                    "'Type here', or 'Send a message'. Do NOT return email/name input fields."
                ),
            )
            if observe_resp and observe_resp.data and observe_resp.data.result:
                await self._log("Chat input validated by observe — ready for messages")
                return True

            # If observe fails, wait and retry once (animation timing)
            await self._log("Chat input not found by observe, waiting for animations...")
            await asyncio.sleep(3)
            observe_resp = await self.session.observe(
                instruction=(
                    "find the textarea or text input where a user types chat messages to send. "
                    "Do NOT return email/name input fields."
                ),
            )
            if observe_resp and observe_resp.data and observe_resp.data.result:
                await self._log("Chat input validated on retry — ready for messages")
                return True

            await self._log("Agent completed but chat input not found by observe")
        except Exception as e:
            await self._log(f"Agent setup failed: {e}")

        return False

    # ── Phase 2: Sending with cached send button ─────────────────────────

    async def _observe_send_button(self):
        """Find and cache the send button action for reuse across all messages."""
        try:
            observe_resp = await self.session.observe(
                instruction=(
                    "find the send button or submit icon for the chat message input. "
                    "This is usually a button with a send icon (arrow, paper plane), "
                    "or a button labeled 'Send', right next to or inside the chat input field."
                ),
            )
            if observe_resp and observe_resp.data and observe_resp.data.result:
                action = observe_resp.data.result[0]
                self._cached_send_action = (
                    action.to_dict(exclude_none=True)
                    if hasattr(action, "to_dict")
                    else action
                )
                await self._log("Send button cached for reuse")
                return True
        except Exception as e:
            await self._log(f"Send button observe failed: {e}")
        return False

    async def _click_send(self) -> bool:
        """Click the send button using the cached action, or fall back to act()."""
        if self._cached_send_action:
            try:
                await self.session.act(input=self._cached_send_action)
                return True
            except Exception:
                # Cached action stale — clear it and fall back
                self._cached_send_action = None

        # Fallback: ask the LLM to find and click it
        try:
            await self.session.act(
                input="click the send button or submit icon next to the chat message input",
            )
            return True
        except Exception:
            pass

        # Last resort: try pressing Enter via act()
        try:
            await self.session.act(
                input="press the Enter key to send the chat message",
            )
            return True
        except Exception:
            return False

    async def send_message(self, message: str) -> bool:
        """Type a message and send it.

        Uses template variables for typing (cache-friendly across 30 attacks).
        Uses observe-then-act for the send button (0 LLM calls after first).
        """
        # Observe send button on first call
        if self._cached_send_action is None:
            await self._observe_send_button()

        try:
            # Type the message using template variables for caching
            await self.session.act(
                input="type %message% into the chat message input field",
                options={"variables": {"message": message}},
            )
            # Click the cached send button
            sent = await self._click_send()
            if sent:
                await self._log(f"Sent: {message[:50]}...")
                return True
        except Exception as e:
            await self._log(f"Send failed: {e}")

        return False

    async def _verify_message_sent(self, message: str) -> bool:
        """Verify that a message was sent by checking if the chat input cleared.

        After a successful send, virtually all chat UIs clear the input field.
        If typed text is still in the input, the message wasn't sent.

        Uses input-cleared check instead of chat-history text matching because:
        - No adversarial payload text in the extraction instruction
        - Simple binary question → fewer model errors
        - Works regardless of chat layout (scroll direction, message visibility)
        """
        await asyncio.sleep(1)  # brief wait for UI to update
        try:
            result = await self.session.extract(
                instruction=(
                    "Look at the chat message input field — the textarea or text input "
                    "where the user types messages to send to the chatbot.\n"
                    "Does it currently contain any typed text, or is it empty?\n"
                    "Note: placeholder text like 'Type a message...', 'Ask anything', or "
                    "'Send a message' shown in grey does NOT count as typed text — that's "
                    "just the placeholder. Only actual typed content counts."
                ),
                schema={
                    "type": "object",
                    "properties": {
                        "input_is_empty": {
                            "type": "boolean",
                            "description": (
                                "True if the chat input field is empty (only has placeholder "
                                "text or nothing at all). False if it contains actual typed text "
                                "that hasn't been sent yet."
                            ),
                        },
                    },
                    "required": ["input_is_empty"],
                },
            )
            is_empty = (
                result.data.result.get("input_is_empty", False)
                if isinstance(result.data.result, dict)
                else False
            )
            await self._log(f"Send verification: input {'empty (sent)' if is_empty else 'has text (not sent)'}")
            return is_empty
        except Exception as e:
            await self._log(f"Send verification failed: {e}")
            # If verification itself fails, assume sent to avoid blocking.
            # If the message wasn't actually sent, read_response will fail
            # and recovery will handle it.
            return True

    # ── Recovery ─────────────────────────────────────────────────────────

    async def _recover_send_failure(self) -> bool:
        """Agent recovery when a message failed to send.

        Describes the expected visual layout so the agent can distinguish
        the chat widget from overlays and take the right corrective action.
        """
        try:
            await self._log("Recovering from send failure...")
            await self.session.execute(
                agent_config={
                    "model": "google/gemini-2.5-flash",
                },
                execute_options={
                    "instruction": (
                        "I tried to send a chat message but it didn't go through.\n\n"
                        "The page should have a chat widget — a panel or window with:\n"
                        "- A conversation area showing sent and received messages\n"
                        "- A text input field at the bottom for typing messages\n"
                        "- A send button (arrow icon, paper plane, or 'Send') next to the input\n\n"
                        "Check these things in order:\n\n"
                        "1. Is the chat widget still visible? If it's gone, find the chat launcher "
                        "button (usually bottom-right corner) and reopen it.\n\n"
                        "2. Is something overlaying the chat? Overlays like email forms, surveys, or "
                        "bottom sheets appear ON TOP of the chat panel — they have their own background "
                        "and their own buttons. If you see one, dismiss it using its own Skip/No thanks/"
                        "X button. The overlay's X is ON the overlay itself, not at the top of the chat "
                        "widget. Do NOT click the chat widget's own close/minimize button.\n\n"
                        "3. Is there text sitting in the chat input that hasn't been sent? If so, click "
                        "the send button to send it.\n\n"
                        "4. Is the text input field visible and ready for typing?\n\n"
                        "IMPORTANT: After EACH action you take, verify the chat widget is still open. "
                        "If you accidentally closed it, reopen it immediately.\n\n"
                        "You're done when: the chat input field is visible, empty, and ready for typing.\n"
                        "Do NOT type any new messages."
                    ),
                    "max_steps": 10,
                },
            )
            await self._log("Send recovery completed")
            await asyncio.sleep(1)
            return True
        except Exception as e:
            await self._log(f"Send recovery failed: {e}")
            return False

    async def _recover_read_failure(self) -> bool:
        """Agent recovery when no chatbot response was detected.

        Different focus from send recovery — checks whether the message was
        actually sent, whether an overlay is blocking the response area, etc.
        """
        try:
            await self._log("Recovering from read failure...")
            await self.session.execute(
                agent_config={
                    "model": "google/gemini-2.5-flash",
                },
                execute_options={
                    "instruction": (
                        "I sent a chat message but couldn't detect the chatbot's response.\n\n"
                        "The chat widget should be a panel/window with a conversation area showing "
                        "messages and a text input at the bottom.\n\n"
                        "Check these things in order:\n\n"
                        "1. Is the chat widget still visible? If it's gone, find the chat launcher "
                        "and reopen it.\n\n"
                        "2. Is something overlaying the chat conversation area? Overlays (email forms, "
                        "surveys, bottom sheets) appear ON TOP of the chat panel with their own "
                        "background. If you see one, dismiss it using its own buttons (Skip, No thanks, "
                        "X on the overlay itself). Do NOT click the chat widget's close button.\n\n"
                        "3. Does my sent message appear in the conversation? Look in the chat history — "
                        "if the message is NOT there but is still sitting in the input field, click the "
                        "send button to send it.\n\n"
                        "4. Is the chatbot still typing or loading? Look for a typing indicator, "
                        "loading spinner, or animated dots. If so, do nothing — the response is coming.\n\n"
                        "IMPORTANT: After EACH action you take, verify the chat widget is still open. "
                        "If you accidentally closed it, reopen it immediately.\n\n"
                        "You're done when: the chat conversation is visible with no overlays blocking it, "
                        "and the input field is ready for the next message.\n"
                        "Do NOT type any new messages."
                    ),
                    "max_steps": 10,
                },
            )
            await self._log("Read recovery completed")
            await asyncio.sleep(1)
            return True
        except Exception as e:
            await self._log(f"Read recovery failed: {e}")
            return False

    # ── Phase 3: Response reading ────────────────────────────────────────

    async def read_response(self, sent_message: str) -> Optional[str]:
        """Read the chatbot's response with polling and stale detection.

        Uses the simple proven extraction schema (chatbot_response + response_found)
        that worked reliably across chatgpt.com, assistant-ui.com, hackathon.cornell.edu/ai.
        """
        await asyncio.sleep(3)  # initial wait for response to appear

        for attempt in range(4):
            try:
                extract_resp = await self.session.extract(
                    instruction=(
                        "In the chat area, find the most recent message from the CHATBOT or AI ASSISTANT. "
                        "Chat areas show two types of messages: USER messages (sent by the visitor, "
                        "usually on the right side or in a colored bubble) and BOT messages (from the "
                        "chatbot/assistant, usually on the left side or in a different colored bubble). "
                        "Do NOT extract the most recent USER message — extract only the BOT's reply "
                        "that came after it. If the bot has not replied yet, set response_found to false.\n\n"
                        "Also check: has the conversation been handed off to a real human agent? "
                        "And are there any error messages indicating messages are being blocked?"
                    ),
                    schema={
                        "type": "object",
                        "properties": {
                            "chatbot_response": {
                                "type": "string",
                                "description": "The full text of the chatbot/AI assistant's most recent reply, NOT the user's message",
                            },
                            "response_found": {
                                "type": "boolean",
                                "description": "True only if a new chatbot response was found after the user's message",
                            },
                            "is_human_agent": {
                                "type": "boolean",
                                "description": (
                                    "True if the conversation has been handed off to a real human agent "
                                    "(not an AI chatbot). Signs include: a message like 'You have been "
                                    "transferred to our support team' or 'Connecting you with an agent', "
                                    "a real person's name and photo appearing (e.g., 'Angelique from Crisp', "
                                    "'Sarah joined the chat'), or the conversation style clearly changing "
                                    "from bot-like to human-like. Only set True if the handoff HAS happened, "
                                    "not if the bot merely offers to connect you."
                                ),
                            },
                            "is_send_blocked": {
                                "type": "boolean",
                                "description": (
                                    "True if there are visible error messages indicating messages are being "
                                    "blocked or rejected. Signs include: error badges or red icons next to "
                                    "sent messages like 'Failed to send', 'Not allowed to send', 'Message "
                                    "rejected', 'You have been blocked', or messages like 'You can no longer "
                                    "send messages in this conversation'. Do NOT set True just because no "
                                    "response was received — only if there's an explicit error visible."
                                ),
                            },
                        },
                        "required": ["chatbot_response", "response_found", "is_human_agent", "is_send_blocked"],
                    },
                )
                result = extract_resp.data.result
                await self._log(f"Extract attempt {attempt + 1}: {result}")

                if isinstance(result, dict):
                    # Check chat status flags
                    if result.get("is_human_agent"):
                        self.human_detected = True
                        await self._log("DETECTED: Human agent handoff")
                    if result.get("is_send_blocked"):
                        self.send_blocked = True
                        await self._log("DETECTED: Messages being blocked")

                    if result.get("response_found") and result.get("chatbot_response", "").strip():
                        text = result["chatbot_response"].strip()

                        # Stale response check
                        if text in self._seen_responses:
                            await self._log(f"Stale response (seen before): {text[:40]}...")
                            await asyncio.sleep(3)
                            continue

                        # Streaming stability check: wait briefly, re-extract,
                        # confirm text hasn't changed (i.e., streaming is done)
                        await asyncio.sleep(2)
                        stable_resp = await self.session.extract(
                            instruction=(
                                "Extract the most recent CHATBOT/AI ASSISTANT message in the chat area. "
                                "Only the bot's reply, not the user's message."
                            ),
                            schema={
                                "type": "object",
                                "properties": {
                                    "chatbot_response": {
                                        "type": "string",
                                        "description": "The chatbot's most recent reply text",
                                    },
                                },
                                "required": ["chatbot_response"],
                            },
                        )
                        stable_result = stable_resp.data.result
                        stable_text = (
                            stable_result.get("chatbot_response", "").strip()
                            if isinstance(stable_result, dict)
                            else ""
                        )

                        # If text matches, streaming is done — return it
                        # If text changed, use the newer (more complete) version
                        final_text = stable_text if stable_text else text
                        if final_text not in self._seen_responses:
                            self._seen_responses.add(final_text)
                            await self._log(f"Response: {final_text[:60]}...")
                            return final_text
            except Exception as e:
                await self._log(f"Extract attempt {attempt + 1} failed: {type(e).__name__}: {e}")

            if attempt < 3:
                await asyncio.sleep(3)

        await self._log("No response received (timeout)")
        return None

    # ── Convenience ──────────────────────────────────────────────────────

    async def send_and_read(self, message: str) -> Optional[str]:
        """Send a message and read the response, with verified sending and recovery.

        Flow:
        1. Send message → verify input cleared
        2. If not verified: retry send once (cheap, handles transient failures)
        3. If still not verified AND recovery not exhausted: agent recover → final retry
        4. Read response with polling (also detects human handoff + send-blocked)
        5. If no response AND recovery not exhausted: agent recover → retry read
        """
        # ── Send with verification ───────────────────────────────────────
        verified = False
        skip_recovery = self._consecutive_recovery_failures >= 2

        sent = await self.send_message(message)
        if sent:
            verified = await self._verify_message_sent(message)

        if not verified:
            # Cheap retry — handles transient failures (button didn't register, etc.)
            await self._log("Message not verified, retrying send...")
            sent = await self.send_message(message)
            if sent:
                verified = await self._verify_message_sent(message)

        if not verified and not skip_recovery:
            # Something structural — agent diagnoses and fixes
            await self._recover_send_failure()
            sent = await self.send_message(message)
            if sent:
                verified = await self._verify_message_sent(message)

        if not verified:
            await self._log("Message could not be sent after recovery")
            self._consecutive_recovery_failures += 1
            return None

        # ── Read response ────────────────────────────────────────────────
        response = await self.read_response(message)
        if response is None and not skip_recovery:
            await self._recover_read_failure()
            response = await self.read_response(message)

        if response is None:
            self._consecutive_recovery_failures += 1
        else:
            self._consecutive_recovery_failures = 0  # reset on any success

        return response
