import json
import random
from unittest.mock import patch, mock_open

import pytest
from scanner.attack_runner import load_payloads

# --- Fixtures ---

CATEGORIES = [
    "system_prompt_extraction",
    "goal_hijacking",
    "data_leakage",
    "guardrail_bypass",
    "insecure_output_handling",
    "indirect_prompt_injection",
]


def _make_payload(id: str, category: str, priority: int) -> dict:
    return {
        "id": id,
        "category": category,
        "name": f"Test {id}",
        "description": "test",
        "payload": f"payload for {id}",
        "severity": "high",
        "priority": priority,
        "source": "test",
        "reference_url": "https://example.com",
        "technique": "test",
        "tags": ["test"],
    }


# --- Tests ---


def test_load_payloads_returns_all_by_default():
    """No params = return all attacks."""
    payloads = load_payloads()
    assert len(payloads) == 45


def test_load_payloads_max_per_category_legacy():
    """Legacy max_per_category still works (takes first N per category)."""
    payloads = load_payloads(max_per_category=2)
    by_cat = {}
    for p in payloads:
        by_cat.setdefault(p["category"], []).append(p)
    for cat, items in by_cat.items():
        assert len(items) <= 2, f"{cat} has {len(items)} items, expected <= 2"


def test_load_payloads_all_have_priority():
    """Every payload in the new suite must have a priority field."""
    payloads = load_payloads()
    for p in payloads:
        assert "priority" in p, f"{p['id']} missing priority"
        assert p["priority"] in (1, 2, 3), f"{p['id']} bad priority: {p['priority']}"


def test_load_payloads_priority_strategy():
    """Priority strategy returns sample_size attacks, P1 first."""
    payloads = load_payloads(sample_size=18, strategy="priority")
    assert len(payloads) == 18

    # Every category should be represented
    cats = {p["category"] for p in payloads}
    assert len(cats) == 6

    # P1 attacks should come before P2/P3 within each category
    by_cat = {}
    for p in payloads:
        by_cat.setdefault(p["category"], []).append(p)
    for cat, items in by_cat.items():
        priorities = [p["priority"] for p in items]
        assert priorities == sorted(priorities), f"{cat} not sorted by priority: {priorities}"


def test_load_payloads_priority_strategy_minimum_one_per_category():
    """Even with small sample_size, every category gets at least 1 attack."""
    payloads = load_payloads(sample_size=6, strategy="priority")
    assert len(payloads) == 6
    cats = {p["category"] for p in payloads}
    assert len(cats) == 6


def test_load_payloads_random_strategy():
    """Random strategy returns sample_size attacks with all categories."""
    payloads = load_payloads(sample_size=18, strategy="random")
    assert len(payloads) == 18
    cats = {p["category"] for p in payloads}
    assert len(cats) == 6


def test_load_payloads_sample_size_exceeds_total():
    """If sample_size >= total attacks, return all."""
    payloads = load_payloads(sample_size=100, strategy="priority")
    assert len(payloads) == 45


def test_load_payloads_sample_size_overrides_max_per_category():
    """sample_size takes precedence over max_per_category."""
    payloads = load_payloads(max_per_category=1, sample_size=24, strategy="priority")
    assert len(payloads) == 24
