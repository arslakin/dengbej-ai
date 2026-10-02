"""
Persistent monthly quota tracking for Kurdish TTS.

Uses a DynamoDB record keyed by YYYY-MM to atomically track character usage.
Prevents concurrent Lambda invocations from exceeding the monthly limit via
conditional writes. Supports reservation/refund pattern for safe budgeting.

Table: dengbej-programs (reuses existing table with a synthetic key)
Record key: program_id="tts-quota", briefing_date="YYYY-MM"
"""

import os
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError


# ─── Configuration ───────────────────────────────────────────────────────────

# Free-tier allowance is 20,000 chars; keep a safety reserve below that.
MONTHLY_BUDGET = int(os.environ.get("KURDISH_TTS_MONTHLY_BUDGET_CHARS", "18000"))
QUOTA_TABLE = os.environ.get("PROGRAMS_TABLE", "dengbej-programs")

# Synthetic DynamoDB key for quota records
QUOTA_PARTITION_KEY = "tts-quota"


# ─── AWS Client ──────────────────────────────────────────────────────────────

_dynamodb = None


def _get_table():
    global _dynamodb
    if _dynamodb is None:
        _dynamodb = boto3.resource("dynamodb").Table(QUOTA_TABLE)
    return _dynamodb


# ─── Public API ──────────────────────────────────────────────────────────────

def get_current_month_key() -> str:
    """Return the current month key in YYYY-MM format."""
    return datetime.now(timezone.utc).strftime("%Y-%m")


def get_usage(month_key: str = None) -> int:
    """Get current character usage for the given month."""
    if month_key is None:
        month_key = get_current_month_key()
    table = _get_table()
    try:
        response = table.get_item(
            Key={"program_id": QUOTA_PARTITION_KEY, "briefing_date": month_key}
        )
        item = response.get("Item")
        if item:
            return int(item.get("chars_used", 0))
        return 0
    except ClientError:
        return 0


def get_remaining(month_key: str = None) -> int:
    """Get remaining character budget for the month."""
    used = get_usage(month_key)
    return max(0, MONTHLY_BUDGET - used)


def reserve(chars: int, month_key: str = None) -> bool:
    """
    Atomically reserve characters from the monthly budget.

    Uses a conditional update to prevent exceeding the limit even
    under concurrent invocations. Returns True if reservation succeeded.

    The condition is expressed on the largest permitted *previous* value
    rather than on the post-increment total, because ``if_not_exists()`` is
    only valid inside an ``UpdateExpression`` — not inside a
    ``ConditionExpression`` (using it there raises a DynamoDB
    ``ValidationException``). The increment itself still uses
    ``if_not_exists`` in the ``UpdateExpression`` so a missing record is
    treated as a starting value of zero.
    """
    if chars <= 0:
        return True
    if month_key is None:
        month_key = get_current_month_key()

    # A single request larger than the whole monthly budget can never fit.
    # Reject it without touching DynamoDB (max_before would be negative).
    if chars > MONTHLY_BUDGET:
        return False

    # Largest existing chars_used that still leaves room for this request:
    #   previous + chars <= MONTHLY_BUDGET  <=>  previous <= MONTHLY_BUDGET - chars
    max_before = MONTHLY_BUDGET - chars

    table = _get_table()

    try:
        # Create the record or increment it, but only if the current value is
        # absent (new month) or small enough that adding `chars` stays within
        # budget. This is concurrency-safe: a racing writer that already pushed
        # chars_used above max_before makes the condition fail.
        table.update_item(
            Key={"program_id": QUOTA_PARTITION_KEY, "briefing_date": month_key},
            UpdateExpression="SET chars_used = if_not_exists(chars_used, :zero) + :inc, updated_at = :now",
            ConditionExpression="attribute_not_exists(chars_used) OR chars_used <= :max_before",
            ExpressionAttributeValues={
                ":inc": Decimal(str(chars)),
                ":zero": Decimal("0"),
                ":max_before": Decimal(str(max_before)),
                ":now": datetime.now(timezone.utc).isoformat(),
            },
        )
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            # Would exceed budget
            return False
        raise


def refund(chars: int, month_key: str = None):
    """
    Refund characters back to the monthly budget after a failed synthesis.

    Does not go below zero.
    """
    if chars <= 0:
        return
    if month_key is None:
        month_key = get_current_month_key()

    table = _get_table()
    try:
        table.update_item(
            Key={"program_id": QUOTA_PARTITION_KEY, "briefing_date": month_key},
            UpdateExpression="SET chars_used = chars_used - :dec, updated_at = :now",
            ConditionExpression="chars_used >= :dec",
            ExpressionAttributeValues={
                ":dec": Decimal(str(chars)),
                ":now": datetime.now(timezone.utc).isoformat(),
            },
        )
    except ClientError:
        # If refund fails (e.g., would go below zero), just log and continue
        pass
