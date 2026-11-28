"""
Regression tests for retry_insufficient distinct behaviour in baseline processing.

These tests verify the fix for Defect #1: compute_retry_state_update when called with
retry_insufficient=True must NOT increment attempt_count beyond max_attempts-1 and must
set baseline_retry_after=None so the reading remains eligible on the very next
incremental pass without a cooldown delay.
"""

from datetime import datetime, timedelta, timezone

from app.services.baselines import compute_retry_state_update


NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)


def test_retry_insufficient_clears_cooldown_and_caps_count() -> None:
    """retry_insufficient=True: no cooldown, attempt_count stays below max."""
    result = compute_retry_state_update(
        is_ready=False,
        reprocess=False,
        retry_insufficient=True,
        retry_exhausted=False,
        was_previously_ready=False,
        prior_attempt_count=1,
        now_utc=NOW,
        meter_max_valid_id=50,
        max_attempts=3,
        base_cooldown_minutes=60,
        max_cooldown_minutes=1440,
    )
    # Must NOT set a cooldown — eligible again immediately
    assert result.baseline_retry_after is None
    # Must NOT exhaust: count must be strictly less than max_attempts
    assert result.baseline_attempt_count < 3
    assert result.baseline_attempt_count >= 1
    # baseline_computed_at must remain None (reading is not ready)
    assert result.baseline_computed_at is None
    # last_attempt_at is stamped
    assert result.baseline_last_attempt_at == NOW
    # max_meter_id is recorded so new data above it triggers wake
    assert result.baseline_attempt_max_meter_id == 50


def test_retry_insufficient_already_at_max_minus_one_stays_capped() -> None:
    """When prior_attempt_count is already max_attempts-1, count must not increase."""
    result = compute_retry_state_update(
        is_ready=False,
        reprocess=False,
        retry_insufficient=True,
        retry_exhausted=False,
        was_previously_ready=False,
        prior_attempt_count=2,  # already at max_attempts-1
        now_utc=NOW,
        meter_max_valid_id=99,
        max_attempts=3,
        base_cooldown_minutes=60,
        max_cooldown_minutes=1440,
    )
    assert result.baseline_retry_after is None
    assert result.baseline_attempt_count == 2  # capped at max-1=2
    assert result.baseline_computed_at is None


def test_retry_insufficient_zero_prior_count_gives_at_least_one() -> None:
    """First attempt under retry_insufficient starts count at 1."""
    result = compute_retry_state_update(
        is_ready=False,
        reprocess=False,
        retry_insufficient=True,
        retry_exhausted=False,
        was_previously_ready=False,
        prior_attempt_count=0,
        now_utc=NOW,
        meter_max_valid_id=None,
        max_attempts=5,
        base_cooldown_minutes=30,
        max_cooldown_minutes=720,
    )
    assert result.baseline_attempt_count >= 1
    assert result.baseline_retry_after is None
    assert result.baseline_computed_at is None


def test_retry_insufficient_does_not_fire_when_ready() -> None:
    """is_ready=True must always win regardless of retry_insufficient flag."""
    result = compute_retry_state_update(
        is_ready=True,
        reprocess=False,
        retry_insufficient=True,
        retry_exhausted=False,
        was_previously_ready=False,
        prior_attempt_count=2,
        now_utc=NOW,
        meter_max_valid_id=50,
        max_attempts=3,
        base_cooldown_minutes=60,
        max_cooldown_minutes=1440,
    )
    # Ready branch must win
    assert result.baseline_computed_at == NOW
    assert result.baseline_attempt_count == 0
    assert result.baseline_retry_after is None
    assert result.baseline_last_attempt_at is None


def test_retry_insufficient_false_gives_cooldown() -> None:
    """Control: without retry_insufficient, a failed pass sets a cooldown."""
    result = compute_retry_state_update(
        is_ready=False,
        reprocess=False,
        retry_insufficient=False,
        retry_exhausted=False,
        was_previously_ready=False,
        prior_attempt_count=1,
        now_utc=NOW,
        meter_max_valid_id=50,
        max_attempts=5,
        base_cooldown_minutes=60,
        max_cooldown_minutes=1440,
    )
    # Normal incremental pass must set a future cooldown
    assert result.baseline_retry_after is not None
    assert result.baseline_retry_after > NOW
    assert result.baseline_computed_at is None
