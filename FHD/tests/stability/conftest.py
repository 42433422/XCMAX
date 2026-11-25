"""Native resilience tools are mandatory in CI; local absence is an explicit skip."""

import os
import shutil

import pytest


@pytest.fixture
def native_tool():
    def resolve(name):
        configured = os.environ.get(name.upper().replace("-", "_") + "_BIN")
        binary = shutil.which(configured or name)
        if binary:
            return binary
        message = f"{name} is required; install the pinned binary documented in README.md"
        if configured or os.environ.get("REQUIRE_RESILIENCE_TOOLS") == "1":
            pytest.fail(message)
        pytest.skip(message)

    return resolve
