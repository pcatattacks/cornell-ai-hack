import asyncio
import pytest
from scanner.chat_interactor import ChatInteractor
from scanner.widget_detector import PLATFORM_CONFIGS


def test_chat_interactor_init():
    interactor = ChatInteractor(platform="tidio", config=PLATFORM_CONFIGS["tidio"])
    assert interactor.platform == "tidio"
    assert interactor.config["uses_iframe"] is False  # Tidio uses shadow DOM, not iframes


def test_chat_interactor_has_send_message():
    interactor = ChatInteractor(platform="crisp", config=PLATFORM_CONFIGS["crisp"])
    assert hasattr(interactor, "send_message")
    assert asyncio.iscoroutinefunction(interactor.send_message)


def test_chat_interactor_build_read_script():
    interactor = ChatInteractor(platform="crisp", config=PLATFORM_CONFIGS["crisp"])
    script = interactor.build_read_script()
    assert "crisp-message-text" in script


def test_chat_interactor_crisp_no_iframe():
    interactor = ChatInteractor(platform="crisp", config=PLATFORM_CONFIGS["crisp"])
    assert interactor.needs_iframe() is False


def test_chat_interactor_tidio_uses_shadow_dom():
    interactor = ChatInteractor(platform="tidio", config=PLATFORM_CONFIGS["tidio"])
    assert interactor.needs_iframe() is False
    assert interactor.config.get("shadow_host") == "#tidio-chat"
