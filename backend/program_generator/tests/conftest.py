"""
Shared fixtures for program_generator tests.

Autouse fixture mocks invoke_bedrock so no test makes a live Bedrock call.
Without this, handler-level tests that generate scripts hit the real
bedrock_runtime client, which retries with backoff and adds 20-30s per test.
Tests that assert Bedrock behavior can still patch invoke_bedrock locally.
"""

import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(autouse=True)
def _mock_bedrock_by_default():
    """
    Prevent live Bedrock calls in all tests. Returns a deterministic Kurdish
    script. A test that needs custom behavior can still patch
    lambda_function.invoke_bedrock inside its own `with` block, which takes
    precedence over this autouse patch.
    """
    try:
        with patch("lambda_function.invoke_bedrock", return_value="Rojbaş. Ev Dengbêj e. Ev bû Dengbej."):
            yield
    except (ImportError, AttributeError):
        # If lambda_function isn't importable in a given test context, no-op.
        yield
