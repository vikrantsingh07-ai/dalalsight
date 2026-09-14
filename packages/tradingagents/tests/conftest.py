"""Shared pytest fixtures that prevent CI hangs when API keys are absent."""

import os
from unittest.mock import MagicMock, patch

import pytest

# The package loads the project's .env on import (tradingagents/__init__.py) and
# builds DEFAULT_CONFIG from TRADINGAGENTS_* variables at import time. Pin the
# market preset so a developer's TRADINGAGENTS_MARKET=india cannot switch the
# whole suite into Indian symbol resolution; load_dotenv never overrides a set var.
os.environ["TRADINGAGENTS_MARKET"] = "global"
# Same for the provider/model/debate overrides a developer .env may set: an empty
# value counts as "set" for load_dotenv and as "unset" for the config overlay.
for _name in (
    "TRADINGAGENTS_LLM_PROVIDER", "TRADINGAGENTS_DEEP_THINK_LLM", "TRADINGAGENTS_QUICK_THINK_LLM",
    "TRADINGAGENTS_LLM_BACKEND_URL", "TRADINGAGENTS_OUTPUT_LANGUAGE", "TRADINGAGENTS_MAX_DEBATE_ROUNDS",
    "TRADINGAGENTS_MAX_RISK_ROUNDS", "TRADINGAGENTS_CHECKPOINT_ENABLED", "TRADINGAGENTS_BENCHMARK_TICKER",
    "TRADINGAGENTS_TEMPERATURE", "TRADINGAGENTS_LLM_MAX_RETRIES", "TRADINGAGENTS_MAX_TOKENS",
    "TRADINGAGENTS_GOOGLE_THINKING_LEVEL", "TRADINGAGENTS_OPENAI_REASONING_EFFORT", "TRADINGAGENTS_ANTHROPIC_EFFORT",
):
    os.environ[_name] = ""


def pytest_configure(config):
    for marker in ("unit", "integration", "smoke"):
        config.addinivalue_line("markers", f"{marker}: {marker}-level tests")


_API_KEY_ENV_VARS = (
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "ANTHROPIC_API_KEY",
    "XAI_API_KEY",
    "DEEPSEEK_API_KEY",
    "DASHSCOPE_API_KEY",
    "DASHSCOPE_CN_API_KEY",
    "ZHIPU_API_KEY",
    "ZHIPU_CN_API_KEY",
    "MINIMAX_API_KEY",
    "MINIMAX_CN_API_KEY",
    "OPENROUTER_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "ALPHA_VANTAGE_API_KEY",
)


@pytest.fixture(autouse=True)
def _dummy_api_keys(monkeypatch):
    for env_var in _API_KEY_ENV_VARS:
        # `or` not a .get default: an env var present but empty (e.g. a key left
        # blank in a .env copied from .env.example) must still get the placeholder.
        monkeypatch.setenv(env_var, os.environ.get(env_var) or "placeholder")


@pytest.fixture(autouse=True)
def _isolate_config():
    """Reset the global dataflows config before and after each test.

    ``set_config`` merges (it never clears keys absent from the override), so a
    test that sets e.g. ``tool_vendors`` would otherwise leak into later tests
    and make routing behavior order-dependent. Replace the global outright so
    every test starts from a clean DEFAULT_CONFIG.
    """
    import copy

    import tradingagents.dataflows.config as config_module
    import tradingagents.default_config as default_config

    config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)
    yield
    config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)


@pytest.fixture()
def mock_llm_client():
    client = MagicMock()
    client.get_llm.return_value = MagicMock()
    with patch(
        "tradingagents.llm_clients.factory.create_llm_client",
        return_value=client,
    ):
        yield client
