# Robust Chat Input Detection & Interaction Plan

> **For agentic workers:** REQUIRED: Use superpowers:executing-plans to implement this plan.

**Goal:** Make the scanner reliably find and type into ANY chat input on ANY website, regardless of whether it's in the main DOM, an iframe, shadow DOM, or nested combinations thereof.

**Core Problem:** The current `_locate_input` only searches the main document and top-level shadow roots. Many chat widgets live inside iframes (Intercom, Zendesk, the Cornell hackathon chatbot). When DOM search fails, we fall back to Claude's coordinate guess, which is fragile across different viewports.

**Architecture:**
```
Vision says "chat is ready" + provides widget_bounds
    ↓
Exhaustive DOM search (main → iframes → shadow roots → nested)
    ↓ returns list of candidates with metadata
Filter by widget_bounds proximity
    ↓ 0-N candidates
If 0: Tab-cycling fallback
If 1: use it
If 2+: ask Claude to pick the right one
    ↓
ChatTarget with frame_handle + selector (not just coordinates)
    ↓
send_message uses frame_handle to type reliably
```

---

## Task 1: Rewrite ChatTarget to support iframe-scoped elements

**Files:** `backend/scanner/vision_navigator.py`

The current `ChatTarget` has `input_selector` and `input_coordinates`. This doesn't work for elements inside iframes — you need a reference to the frame.

- [ ] **Step 1: Update ChatTarget dataclass**

```python
@dataclass
class ChatTarget:
    input_selector: Optional[str]       # CSS selector within the target frame
    input_coordinates: Optional[tuple[int, int]]  # fallback pixel coordinates
    frame_index: Optional[int]          # which iframe (None = main frame)
    frame_url: Optional[str]            # iframe src for debugging
    description: str
    method: str                         # "selector" | "coordinates" | "tab"
```

- [ ] **Step 2: Commit**

---

## Task 2: Exhaustive DOM search across all contexts

**Files:** `backend/scanner/vision_navigator.py`

Rewrite `_locate_input` to search everywhere.

- [ ] **Step 1: Create `_find_all_inputs` function**

This function uses `page.evaluate` to search the main document, then uses Playwright's `page.frames` to search all iframes (Playwright gives direct access to iframe content via `page.frames`).

```python
async def _find_all_inputs(page: Page, widget_bounds: dict | None, _log) -> list[dict]:
    """Find ALL textarea/input/contenteditable elements across the entire page.

    Searches: main document, all iframes (via page.frames), all shadow roots.
    Returns a list of candidates with metadata for ranking.
    """
    candidates = []

    # Search each frame (main + all iframes)
    for frame_idx, frame in enumerate(page.frames):
        try:
            results = await frame.evaluate("""
                (() => {
                    function searchRoot(root, prefix) {
                        const found = [];
                        const els = root.querySelectorAll('textarea, input[type="text"], input:not([type]), [contenteditable="true"]');
                        for (const el of els) {
                            const rect = el.getBoundingClientRect();
                            if (rect.width < 20 || rect.height < 10) continue;
                            const style = window.getComputedStyle(el);
                            if (style.display === 'none' || style.visibility === 'hidden') continue;
                            found.push({
                                tag: el.tagName,
                                id: el.id || null,
                                name: el.name || null,
                                placeholder: el.placeholder || el.getAttribute('aria-label') || '',
                                type: el.type || null,
                                rect: { x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height) },
                                cx: Math.round(rect.x + rect.width/2),
                                cy: Math.round(rect.y + rect.height/2),
                                prefix: prefix,
                            });
                        }
                        // Also check shadow roots
                        const allEls = root.querySelectorAll('*');
                        for (const host of allEls) {
                            if (host.shadowRoot) {
                                found.push(...searchRoot(host.shadowRoot, prefix + ' > shadow(' + (host.id || host.tagName) + ')'));
                            }
                        }
                        return found;
                    }
                    return JSON.stringify(searchRoot(document, 'main'));
                })()
            """)
            frame_candidates = json.loads(results)
            for c in frame_candidates:
                c["frame_index"] = frame_idx
                c["frame_url"] = frame.url
                c["frame_name"] = frame.name or None
            candidates.extend(frame_candidates)
        except Exception:
            continue  # Frame may be cross-origin or detached

    return candidates
```

Key points:
- `page.frames` gives us Playwright Frame objects for ALL iframes (including nested ones)
- Playwright handles cross-origin iframes transparently
- We search shadow roots within each frame
- Each candidate knows which frame it's in (`frame_index`)

- [ ] **Step 2: Filter candidates by widget bounds**

If vision gave us widget bounds, filter candidates to ones whose center is within or near the bounds:

```python
def _filter_by_bounds(candidates, widget_bounds):
    if not widget_bounds:
        return candidates
    bx, by = widget_bounds["x"], widget_bounds["y"]
    bw, bh = widget_bounds["width"], widget_bounds["height"]
    margin = 50  # pixels of tolerance
    filtered = []
    for c in candidates:
        if (bx - margin <= c["cx"] <= bx + bw + margin and
            by - margin <= c["cy"] <= by + bh + margin):
            filtered.append(c)
    return filtered if filtered else candidates  # fall back to all if none in bounds
```

- [ ] **Step 3: If multiple candidates, ask Claude to pick**

```python
async def _pick_chat_input(candidates, anthropic_client):
    """Ask Claude which candidate is the chat message input."""
    desc = "\n".join([
        f"  [{i}] {c['tag']} placeholder='{c['placeholder']}' id='{c['id']}' "
        f"frame={c['frame_url'][:50] if c['frame_url'] else 'main'} "
        f"at ({c['cx']}, {c['cy']}) size={c['rect']['w']}x{c['rect']['h']}"
        for i, c in enumerate(candidates)
    ])
    result = await _ask_claude(None, None,  # no screenshot needed
        prompt=f"Which input is the CHAT MESSAGE input (for typing messages to an AI chatbot)?\n{desc}\nRespond with ONLY the index number."
    )
    # ... parse index ...
```

Wait — `_ask_claude` requires a screenshot. For a text-only query, we should either make a separate helper or pass a dummy. Actually, let's just use the anthropic client directly for this simple classification.

- [ ] **Step 4: Build ChatTarget from the selected candidate**

Using `frame_index` to get the right Playwright Frame for later interaction.

- [ ] **Step 5: Commit**

---

## Task 3: Tab-cycling fallback

**Files:** `backend/scanner/vision_navigator.py`

If exhaustive DOM search finds nothing (rare but possible with heavily obfuscated widgets).

- [ ] **Step 1: Implement `_tab_to_input` function**

```python
async def _tab_to_input(page, widget_bounds, _log, max_tabs=20):
    """Click in widget area then Tab until we focus a text input."""
    if widget_bounds:
        cx = widget_bounds["x"] + widget_bounds["width"] // 2
        cy = widget_bounds["y"] + widget_bounds["height"] // 2
        await page.mouse.click(cx, cy)

    for i in range(max_tabs):
        await page.keyboard.press("Tab")
        await asyncio.sleep(0.1)
        tag = await page.evaluate("document.activeElement?.tagName?.toLowerCase() || ''")
        if tag in ("textarea", "input"):
            # Check it's a text input, not a button
            input_type = await page.evaluate("document.activeElement?.type || ''")
            if input_type in ("", "text", "search"):
                return True  # focused on a text input
    return False
```

- [ ] **Step 2: Commit**

---

## Task 4: Update send_message to handle frame-scoped inputs

**Files:** `backend/scanner/generic_chat.py`

The current `send_message` only interacts with the main page. If the input is in an iframe, we need to use the Frame object.

- [ ] **Step 1: Update send_message to accept a frame reference**

```python
async def send_message(page, message, chat_target, ...):
    # Get the right frame to interact with
    target_frame = page
    if chat_target.frame_index is not None and chat_target.frame_index > 0:
        if chat_target.frame_index < len(page.frames):
            target_frame = page.frames[chat_target.frame_index]

    # Strategy 1: selector click + keyboard.type (in the right frame)
    if chat_target.input_selector:
        locator = target_frame.locator(chat_target.input_selector).first
        ...
```

- [ ] **Step 2: Update read_latest_response to search all frames too**

The response reading has the same problem — it only checks the main document. The chatbot's response messages are in the same frame as the input.

```python
async def read_latest_response(page, chat_target=None, ...):
    # If we know which frame the chat is in, search there
    frames_to_search = [page.frames[chat_target.frame_index]] if chat_target and chat_target.frame_index else page.frames
    for frame in frames_to_search:
        try:
            result = await frame.evaluate(read_script)
            ...
```

- [ ] **Step 3: Commit**

---

## Task 5: Wire it all together in _locate_input

**Files:** `backend/scanner/vision_navigator.py`

- [ ] **Step 1: Rewrite `_locate_input` to use the new approach**

```python
async def _locate_input(page, anthropic_client, screenshot_b64, _log, widget_bounds=None):
    # Step 1: Exhaustive DOM search
    candidates = await _find_all_inputs(page, widget_bounds, _log)
    await _log(f"vision: found {len(candidates)} input candidates across {len(page.frames)} frames")

    # Step 2: Filter by widget bounds
    if widget_bounds:
        candidates = _filter_by_bounds(candidates, widget_bounds)
        await _log(f"vision: {len(candidates)} candidates after bounds filter")

    # Step 3: Pick the right one
    if len(candidates) == 0:
        # Tab-cycling fallback
        await _log("vision: no candidates found, trying Tab cycling")
        if await _tab_to_input(page, widget_bounds, _log):
            # Tab found an input — get its info
            ...
        return None
    elif len(candidates) == 1:
        selected = candidates[0]
    else:
        # Ask Claude to pick
        selected = await _pick_chat_input(candidates, anthropic_client, _log)

    # Step 4: Build ChatTarget
    return ChatTarget(
        input_selector=_build_selector(selected),
        input_coordinates=(selected["cx"], selected["cy"]),
        frame_index=selected["frame_index"],
        frame_url=selected.get("frame_url"),
        description=f"{selected['tag']} placeholder='{selected['placeholder']}' in frame {selected['frame_index']}",
        method="selector" if _build_selector(selected) else "coordinates",
    )
```

- [ ] **Step 2: Pass widget_bounds through the vision navigation loop**

The vision step returns `widget_bounds` or `widget_location.bounding_box`. Thread this through to `_locate_input`.

- [ ] **Step 3: Commit**

---

## Task 6: Test on all three sites

- [ ] **Step 1: Test hackathon.cornell.edu/ai via Browserbase** — verify iframe detection works
- [ ] **Step 2: Test crisp.chat via Browserbase** — verify overlay handling + frame-scoped typing
- [ ] **Step 3: Test assistant-ui.com via Browserbase** — verify no-widget detection
- [ ] **Step 4: Fix any issues, commit**

---

## Summary of what changes

| File | Change |
|------|--------|
| `vision_navigator.py` | New `_find_all_inputs`, `_filter_by_bounds`, `_pick_chat_input`, `_tab_to_input`. Rewrite `_locate_input`. Updated `ChatTarget` dataclass. |
| `generic_chat.py` | `send_message` and `read_latest_response` use `chat_target.frame_index` to work in the correct iframe. |
| `main.py` | Set viewport to 1280x720 for consistency (already done). Pass widget_bounds through. |
