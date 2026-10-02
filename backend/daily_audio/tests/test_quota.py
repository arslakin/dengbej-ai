"""
Focused tests for the Kurdish TTS DynamoDB quota-reservation expression.

Regression target: the reservation ConditionExpression previously used
``if_not_exists(chars_used, :zero) + :inc <= :limit``. ``if_not_exists()`` is
only valid inside an UpdateExpression, so DynamoDB rejected the reservation
with a ValidationException and the batch correctly failed closed (zero chars
consumed). The fix moves the budget check onto the largest permitted previous
value: ``attribute_not_exists(chars_used) OR chars_used <= :max_before`` where
``:max_before = MONTHLY_BUDGET - chars``.

These tests assert both the behaviour and the exact boto3 UpdateItem params.
"""

import os
import sys
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import quota  # noqa: E402


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _mock_table(mock_resource):
    """Wire quota's lazy boto3 resource to a fresh mock table."""
    quota._dynamodb = None
    table = MagicMock()
    mock_resource.return_value.Table.return_value = table
    table.update_item.return_value = {}
    return table


def _conditional_failed():
    return ClientError(
        {"Error": {"Code": "ConditionalCheckFailedException", "Message": "budget"}},
        "UpdateItem",
    )


def _validation_exception():
    return ClientError(
        {"Error": {"Code": "ValidationException",
                   "Message": "Invalid ConditionExpression"}},
        "UpdateItem",
    )


# ─── First reservation when the quota record does not yet exist ──────────────

@patch("quota._dynamodb", None)
@patch("quota.boto3.resource")
def test_first_reservation_creates_record(mock_resource):
    table = _mock_table(mock_resource)
    assert quota.reserve(500, "2026-10") is True
    table.update_item.assert_called_once()


# ─── Incrementing an existing record ─────────────────────────────────────────

@patch("quota._dynamodb", None)
@patch("quota.boto3.resource")
def test_increment_existing_record(mock_resource):
    table = _mock_table(mock_resource)
    # The conditional update is atomic server-side; a non-raising call == success.
    assert quota.reserve(1000, "2026-10") is True
    kwargs = table.update_item.call_args[1]
    assert kwargs["UpdateExpression"] == (
        "SET chars_used = if_not_exists(chars_used, :zero) + :inc, updated_at = :now"
    )


# ─── Reservation exactly at the monthly limit ────────────────────────────────

@patch("quota._dynamodb", None)
@patch("quota.boto3.resource")
def test_reservation_exactly_at_limit(mock_resource):
    table = _mock_table(mock_resource)
    # Requesting the entire budget at once: max_before == 0, so the record must
    # be absent or at zero. A non-raising update means it fit exactly.
    assert quota.reserve(quota.MONTHLY_BUDGET, "2026-10") is True
    kwargs = table.update_item.call_args[1]
    assert kwargs["ExpressionAttributeValues"][":max_before"] == Decimal("0")


# ─── Reservation that would exceed the limit ─────────────────────────────────

@patch("quota._dynamodb", None)
@patch("quota.boto3.resource")
def test_reservation_exceeding_limit_returns_false(mock_resource):
    table = _mock_table(mock_resource)
    table.update_item.side_effect = _conditional_failed()
    # In-budget request size, but the stored value is already too high: the
    # condition fails and reserve reports False without consuming quota.
    assert quota.reserve(500, "2026-10") is False
    table.update_item.assert_called_once()


# ─── A request larger than the monthly budget makes no DynamoDB call ─────────

@patch("quota._dynamodb", None)
@patch("quota.boto3.resource")
def test_request_larger_than_budget_makes_no_dynamodb_call(mock_resource):
    table = _mock_table(mock_resource)
    assert quota.reserve(quota.MONTHLY_BUDGET + 1, "2026-10") is False
    table.update_item.assert_not_called()


# ─── ConditionalCheckFailedException returns False ───────────────────────────

@patch("quota._dynamodb", None)
@patch("quota.boto3.resource")
def test_conditional_check_failed_returns_false(mock_resource):
    table = _mock_table(mock_resource)
    table.update_item.side_effect = _conditional_failed()
    assert quota.reserve(100, "2026-10") is False


# ─── ValidationException / unexpected ClientError propagates (fail closed) ───

@patch("quota._dynamodb", None)
@patch("quota.boto3.resource")
def test_validation_exception_propagates(mock_resource):
    table = _mock_table(mock_resource)
    table.update_item.side_effect = _validation_exception()
    with pytest.raises(ClientError) as exc:
        quota.reserve(100, "2026-10")
    assert exc.value.response["Error"]["Code"] == "ValidationException"


@patch("quota._dynamodb", None)
@patch("quota.boto3.resource")
def test_other_client_error_propagates(mock_resource):
    table = _mock_table(mock_resource)
    table.update_item.side_effect = ClientError(
        {"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "x"}},
        "UpdateItem",
    )
    with pytest.raises(ClientError):
        quota.reserve(100, "2026-10")


# ─── Exact boto3 UpdateItem parameter assertions ─────────────────────────────

@patch("quota._dynamodb", None)
@patch("quota.boto3.resource")
def test_condition_expression_has_no_if_not_exists(mock_resource):
    table = _mock_table(mock_resource)
    quota.reserve(1200, "2026-10")
    kwargs = table.update_item.call_args[1]
    condition = kwargs["ConditionExpression"]
    assert "if_not_exists" not in condition, \
        "if_not_exists() is invalid inside a ConditionExpression"
    assert condition == "attribute_not_exists(chars_used) OR chars_used <= :max_before"


@patch("quota._dynamodb", None)
@patch("quota.boto3.resource")
def test_update_expression_still_uses_if_not_exists(mock_resource):
    table = _mock_table(mock_resource)
    quota.reserve(1200, "2026-10")
    kwargs = table.update_item.call_args[1]
    assert "if_not_exists(chars_used, :zero) + :inc" in kwargs["UpdateExpression"]


@patch("quota._dynamodb", None)
@patch("quota.boto3.resource")
def test_max_before_equals_budget_minus_request_and_is_decimal(mock_resource):
    table = _mock_table(mock_resource)
    chars = 3833
    quota.reserve(chars, "2026-10")
    values = table.update_item.call_args[1]["ExpressionAttributeValues"]
    assert values[":max_before"] == Decimal(str(quota.MONTHLY_BUDGET - chars))
    assert isinstance(values[":max_before"], Decimal)
    assert values[":inc"] == Decimal(str(chars))
    assert isinstance(values[":inc"], Decimal)
    # The invalid :limit placeholder must be gone.
    assert ":limit" not in values


# ─── Two reservations cannot logically exceed the configured limit ───────────

@patch("quota._dynamodb", None)
@patch("quota.boto3.resource")
def test_two_reservations_cannot_exceed_limit(mock_resource):
    """
    Simulate the server-side atomic condition against a shared stored value.
    The second reservation that would push the total past the budget must be
    rejected, mirroring DynamoDB's ConditionalCheckFailedException.
    """
    table = _mock_table(mock_resource)
    state = {"chars_used": None}  # None == attribute_not_exists

    def fake_update_item(**kwargs):
        values = kwargs["ExpressionAttributeValues"]
        inc = int(values[":inc"])
        max_before = int(values[":max_before"])
        current = state["chars_used"]
        condition_ok = current is None or current <= max_before
        if not condition_ok:
            raise _conditional_failed()
        state["chars_used"] = (0 if current is None else current) + inc
        return {}

    table.update_item.side_effect = fake_update_item

    half = quota.MONTHLY_BUDGET // 2
    first = quota.reserve(half, "2026-10")
    # A second request that would exceed the remaining budget.
    second = quota.reserve(quota.MONTHLY_BUDGET - half + 1, "2026-10")

    assert first is True
    assert second is False
    assert state["chars_used"] <= quota.MONTHLY_BUDGET


# ─── Existing refund and usage behaviour remains intact ──────────────────────

@patch("quota._dynamodb", None)
@patch("quota.boto3.resource")
def test_refund_unchanged(mock_resource):
    table = _mock_table(mock_resource)
    quota.refund(300, "2026-10")
    kwargs = table.update_item.call_args[1]
    assert "chars_used - :dec" in kwargs["UpdateExpression"]
    assert kwargs["ExpressionAttributeValues"][":dec"] == Decimal("300")
    assert kwargs["ConditionExpression"] == "chars_used >= :dec"


@patch("quota._dynamodb", None)
@patch("quota.boto3.resource")
def test_refund_zero_is_noop(mock_resource):
    table = _mock_table(mock_resource)
    quota.refund(0, "2026-10")
    table.update_item.assert_not_called()


@patch("quota._dynamodb", None)
@patch("quota.boto3.resource")
def test_get_usage_and_remaining(mock_resource):
    table = _mock_table(mock_resource)
    table.get_item.return_value = {"Item": {"chars_used": Decimal("5000")}}
    assert quota.get_usage("2026-10") == 5000
    assert quota.get_remaining("2026-10") == quota.MONTHLY_BUDGET - 5000


def test_reserve_zero_chars_is_true_without_dynamodb():
    # Zero/negative requests short-circuit to True and never touch DynamoDB.
    with patch("quota.boto3.resource") as mock_resource:
        assert quota.reserve(0) is True
        mock_resource.assert_not_called()


def test_reserve_negative_chars_is_true_without_dynamodb():
    with patch("quota.boto3.resource") as mock_resource:
        assert quota.reserve(-10) is True
        mock_resource.assert_not_called()


# ─── No synthesis occurs when reservation returns False ──────────────────────

@patch("lambda_function.s3_client")
@patch("lambda_function._update_program_ku_audio")
@patch("lambda_function._update_briefing_ku_audio")
@patch("lambda_function._get_program_for_batch")
@patch("lambda_function._get_briefing_for_batch")
def test_no_synthesis_when_reservation_false(mock_briefing, mock_program,
                                             mock_upd_brief, mock_upd_prog, mock_s3):
    """A failed reservation must skip synthesis, S3 writes, and DB updates."""
    from lambda_function import lambda_handler

    mock_briefing.return_value = {
        "briefing_date": "2026-10-02", "generated_at": "T",
        "daily_audio_script_ku": "Rojbaş. Ev Dengbej e.",
        "daily_audio_meta": {},
    }
    mock_program.return_value = None

    with patch.dict("sys.modules", {"kurdish_tts": MagicMock()}):
        ku_mock = sys.modules["kurdish_tts"]
        ku_mock.synthesize_kurdish = MagicMock()
        with patch("quota.reserve", return_value=False), \
             patch("quota.get_usage", return_value=0):
            result = lambda_handler({
                "generate_kurdish_batch": True,
                "max_chars": 10000,
                "dry_run": False,
                "date": "2026-10-02",
            }, None)

    ku_mock.synthesize_kurdish.assert_not_called()
    mock_s3.put_object.assert_not_called()
    mock_upd_brief.assert_not_called()
    mock_upd_prog.assert_not_called()
    assert result["body"]["status"] == "completed"
    assert result["body"]["results"][0]["status"] == "skipped"
    assert result["body"]["results"][0]["reason"] == "reservation_not_confirmed"
    assert result["body"]["chars_consumed"] == 0
