# Changelog

## 2026-03-14 12:42 — Fix `pyproject.toml` package discovery
**Reason:** `pip install -e ".[dev]"` failed because setuptools auto-discovered both `scanner/` and `payloads/` as top-level packages, which it refuses to build.
**Change:** Added `[tool.setuptools.packages.find]` with `include = ["scanner*"]` to `backend/pyproject.toml`, excluding the `payloads/` data directory from package discovery.

---

## 2026-03-14 12:45 — Add `uvicorn` entrypoint to `main.py`
**Reason:** `python main.py` was a no-op — the file defined the FastAPI app but never started the server.
**Change:** Added `uvicorn.run("main:app", ...)` under `if __name__ == "__main__"` in `backend/main.py`. Subsequently removed in favour of running `uvicorn main:app --port 8000 --reload` directly from the CLI (linter commented out the block).

---

## 2026-03-14 12:50 — Update README run instructions to use uvicorn CLI
**Reason:** The `if __name__ == "__main__"` block was removed; README needed to reflect the correct start command.
**Change:** Updated `backend` run command in `README.md` from `python main.py` to `uvicorn main:app --port 8000 --reload`.

---

## 2026-03-14 13:10 — Change page.goto wait strategy from networkidle to domcontentloaded
**Reason:** Sites with continuous background network activity (e.g. Zendesk marketplace) never reach "networkidle", causing a 30s timeout on every scan.
**Change:** Updated `wait_until="networkidle"` to `wait_until="domcontentloaded"` in `backend/main.py`. DOM ready is sufficient for widget detection.

---

## 2026-03-14 12:55 — Fix URL input text colour in ScanInput
**Reason:** The URL input field had no explicit text colour set, causing typed text to render light/grey (browser default) and be hard to read.
**Change:** Added `text-gray-900` to the input's Tailwind className in `frontend/components/ScanInput.tsx`.
