import pytest
from scanner.scoring import calculate_category_score, calculate_overall_score, score_to_grade


def test_score_to_grade():
    assert score_to_grade(0.0) == "A"
    assert score_to_grade(0.05) == "A"
    assert score_to_grade(0.1) == "A"
    assert score_to_grade(0.15) == "B"
    assert score_to_grade(0.4) == "C"
    assert score_to_grade(0.6) == "D"
    assert score_to_grade(0.8) == "F"
    assert score_to_grade(1.0) == "F"


def test_calculate_category_score_all_resistant():
    findings = [{"score": 0.0}, {"score": 0.0}, {"score": 0.0}]
    assert calculate_category_score(findings) == 0.0


def test_calculate_category_score_all_vulnerable():
    findings = [{"score": 1.0}, {"score": 1.0}, {"score": 1.0}]
    assert calculate_category_score(findings) == 1.0


def test_calculate_category_score_mixed():
    findings = [{"score": 1.0}, {"score": 0.0}, {"score": 0.5}]
    assert calculate_category_score(findings) == 0.5


def test_calculate_category_score_empty():
    assert calculate_category_score([]) is None


def test_calculate_overall_score():
    category_scores = {
        "system_prompt_extraction": 0.5,
        "goal_hijacking": 0.3,
        "data_leakage": 0.1,
        "guardrail_bypass": 0.8,
    }
    overall = calculate_overall_score(category_scores)
    assert abs(overall - 0.375) < 0.001


def test_calculate_overall_score_skips_none():
    category_scores = {
        "system_prompt_extraction": 0.5,
        "goal_hijacking": None,
        "data_leakage": 0.0,
        "guardrail_bypass": None,
    }
    overall = calculate_overall_score(category_scores)
    assert abs(overall - 0.25) < 0.001
