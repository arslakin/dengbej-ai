"""
Shared fixtures for todays_five_curator tests.

Autouse fixture mocks invoke_bedrock so no test makes a live Bedrock call.
deduplicate_selection and cluster verification call Bedrock for ambiguous
pairs; without a mock the client retries/times out (~2s per affected test).
"""

import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(autouse=True)
def _mock_bedrock_by_default():
    """Prevent live Bedrock calls. Returns an empty JSON verdict array so
    dedup/clustering treats pairs as 'no merge' deterministically."""
    try:
        with patch("lambda_function.invoke_bedrock", return_value="[]"):
            yield
    except (ImportError, AttributeError):
        yield
