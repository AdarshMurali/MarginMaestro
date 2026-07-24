"""Scaffold smoke test: every src package must be importable."""

import importlib

import pytest

PACKAGES = ["agents", "calc", "streaming", "rag", "api", "mcp", "persistence"]


@pytest.mark.parametrize("package", PACKAGES)
def test_package_importable(package: str) -> None:
    importlib.import_module(package)
