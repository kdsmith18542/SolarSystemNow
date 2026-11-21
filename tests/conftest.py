"""Pytest configuration and shared fixtures."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from ssnow_core.store import Store

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def load_json_fixture(name: str):
    return json.loads(load_fixture(name))


@pytest.fixture
def tmp_store(tmp_path, monkeypatch):
    monkeypatch.setenv("SSNOW_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SSNOW_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("SSNOW_CACHE_DIR", str(tmp_path / "cache"))
    store = Store()
    yield store
    store.close()
