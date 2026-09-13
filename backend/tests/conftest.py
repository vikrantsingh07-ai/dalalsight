from __future__ import annotations

import pytest
import requests
from fastapi.testclient import TestClient
from helpers import FakeAdapter, FakeProvider, FakeRegistry, make_env

from cc.api.app import create_app
from cc.api.container import build_services
from cc.storage.db import Database


@pytest.fixture(autouse=True)
def no_network_or_real_keys(monkeypatch):
    """Tests never reach the network and never see real API keys from the developer's .env."""
    for name in ("AI_API_KEY", "CC_TEST_AI_KEY", "MARKET_DATA_API_KEY", "MARKET_DATA_API_SECRET", "MARKET_DATA_ACCESS_TOKEN"):
        monkeypatch.delenv(name, raising=False)

    def blocked(*args, **kwargs):
        raise requests.ConnectionError("network disabled in tests")

    monkeypatch.setattr(requests, "get", blocked)
    monkeypatch.setattr(requests, "post", blocked)
    monkeypatch.setattr(requests.Session, "request", blocked)


@pytest.fixture
def registry(tmp_path):
    return FakeRegistry(tmp_path)


@pytest.fixture
def provider(registry):
    return FakeProvider(registry)


@pytest.fixture
def services(registry, provider):
    return build_services(make_env(), db=Database(":memory:"), provider=provider, registry=registry, adapter_factory=FakeAdapter)


@pytest.fixture
def client(services):
    with TestClient(create_app(services=services, start_background=False)) as test_client:
        yield test_client
