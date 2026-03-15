import pytest
from scanner.widget_detector import PLATFORM_CONFIGS, build_detection_script, parse_detection_results


def test_platform_configs_exist():
    assert "intercom" in PLATFORM_CONFIGS
    assert "tidio" in PLATFORM_CONFIGS
    assert "zendesk" in PLATFORM_CONFIGS
    assert "crisp" in PLATFORM_CONFIGS
    assert "demo" in PLATFORM_CONFIGS


def test_platform_config_has_required_fields():
    for name, config in PLATFORM_CONFIGS.items():
        assert "global_var" in config, f"{name} missing global_var"
        assert "dom_selector" in config, f"{name} missing dom_selector"
        assert "open_command" in config, f"{name} missing open_command"


def test_build_detection_script_returns_js():
    script = build_detection_script()
    assert isinstance(script, str)
    assert "window" in script


def test_parse_detection_results_finds_platform():
    mock_results = {
        "globals": {"intercom": False, "tidio": True, "zendesk": False, "crisp": False, "demo": False},
        "dom": {"intercom": False, "tidio": True, "zendesk": False, "crisp": False, "demo": False},
    }
    assert parse_detection_results(mock_results) == "tidio"


def test_parse_detection_results_prefers_global():
    mock_results = {
        "globals": {"intercom": True, "tidio": False, "zendesk": False, "crisp": False, "demo": False},
        "dom": {"intercom": False, "tidio": True, "zendesk": False, "crisp": False, "demo": False},
    }
    assert parse_detection_results(mock_results) == "intercom"


def test_parse_detection_results_none_found():
    mock_results = {
        "globals": {"intercom": False, "tidio": False, "zendesk": False, "crisp": False, "demo": False},
        "dom": {"intercom": False, "tidio": False, "zendesk": False, "crisp": False, "demo": False},
    }
    assert parse_detection_results(mock_results) is None
