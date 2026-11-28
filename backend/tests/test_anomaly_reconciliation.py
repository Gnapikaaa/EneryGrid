"""
Regression tests for anomaly reconciliation plan correctness.

Imports only app.services.anomalies submodule directly to avoid the
app.schemas.__init__ → app.schemas.auth → argon2 DLL chain that is
blocked by Windows Application Control policy in the sandbox environment.
These tests cover the waveform-propagation fix (Defect #6 — reconciliation
waveforms now refreshed and stored on every pass).
"""

from decimal import Decimal

from app.core.constants import AnomalySeverity, AnomalyStatus, CostEstimateStatus
from app.services.anomalies import ExistingAnomalySnapshot, build_reconciliation_plan


def _make_open_snap(
    waveform: list[float],
    baseline_waveform: list[float],
    z_score: str = "3.00",
    actual_kw: str = "140.00",
    expected_kw: str = "100.00",
) -> ExistingAnomalySnapshot:
    return ExistingAnomalySnapshot(
        status=AnomalyStatus.OPEN,
        severity=AnomalySeverity.HIGH,
        z_score=Decimal(z_score),
        expected_kw=Decimal(expected_kw),
        deviation_pct=Decimal("40.00"),
        estimated_waste_kwh=Decimal("10.00"),
        estimated_cost=Decimal("2.00"),
        cost_estimate_status=CostEstimateStatus.AVAILABLE,
        waveform=waveform,
        baseline_waveform=baseline_waveform,
    )


def test_waveform_propagated_to_plan() -> None:
    """new_waveform and new_baseline_waveform must be stored verbatim on the returned plan."""
    new_w = [150.0, 152.0, 149.0]
    new_bw = [100.0, 101.0, 100.5]
    plan = build_reconciliation_plan(
        existing=_make_open_snap([140.0, 141.0], [100.0, 100.0]),
        metrics=None,
        actual_kw=Decimal("140.00"),
        interval_seconds=900,
        fallback_baseline_kw=Decimal("95.00"),  # still anomalous → OPEN stays
        fallback_raw_mean_kw=Decimal("95.00"),
        fallback_z_score=Decimal("3.20"),
        applicable_rate=Decimal("0.15"),
        new_waveform=new_w,
        new_baseline_waveform=new_bw,
    )
    assert plan.new_waveform == new_w
    assert plan.new_baseline_waveform == new_bw


def test_waveform_array_change_alone_triggers_update() -> None:
    """When only the waveform arrays differ from the snapshot, should_update must be True."""
    snap = _make_open_snap(waveform=[140.0], baseline_waveform=[100.0])
    plan = build_reconciliation_plan(
        existing=snap,
        metrics=None,
        actual_kw=Decimal("140.00"),
        interval_seconds=900,
        fallback_baseline_kw=Decimal("95.00"),
        fallback_raw_mean_kw=Decimal("95.00"),
        fallback_z_score=Decimal("3.00"),
        applicable_rate=None,
        new_waveform=[140.0, 141.0],      # changed: longer array
        new_baseline_waveform=[100.0],
    )
    assert plan.should_update is True


def test_identical_waveforms_do_not_force_update() -> None:
    """Idempotency: when waveforms and all metrics are identical, should_update must be False.

    Uses an ACKNOWLEDGED snapshot — ACKNOWLEDGED preserves human state and respects
    fields_changed, so identical data round-trips to should_update=False.
    The fallback path with metrics=None is used because OPEN auto-resolves unconditionally;
    for ACKNOWLEDGED the idempotency check on fields_changed applies.
    """
    wf = [140.0, 141.0]
    bwf = [100.0, 100.5]
    # ACKNOWLEDGED: human has seen it; reconciliation preserves status, only updates if fields differ
    snap = ExistingAnomalySnapshot(
        status=AnomalyStatus.ACKNOWLEDGED,
        severity=AnomalySeverity.HIGH,
        z_score=Decimal("3.00"),
        expected_kw=Decimal("95.00"),
        deviation_pct=Decimal("47.37"),
        estimated_waste_kwh=Decimal("11.25"),
        estimated_cost=None,
        cost_estimate_status=CostEstimateStatus.UNAVAILABLE_TARIFF,
        waveform=wf,
        baseline_waveform=bwf,
    )
    # Pass exactly the same calculated values back; waveforms identical too
    plan = build_reconciliation_plan(
        existing=snap,
        metrics=None,
        actual_kw=Decimal("140.00"),
        interval_seconds=900,
        fallback_baseline_kw=Decimal("95.00"),
        fallback_raw_mean_kw=Decimal("95.00"),
        fallback_z_score=Decimal("3.00"),
        applicable_rate=None,
        new_waveform=list(wf),          # copy, same values
        new_baseline_waveform=list(bwf),
    )
    # ACKNOWLEDGED keeps its status; nothing changed → no update needed
    assert plan.new_status == AnomalyStatus.ACKNOWLEDGED
    assert plan.should_update is False


def test_open_drop_below_threshold_resolves_and_carries_waveforms() -> None:
    """OPEN anomaly falling below threshold auto-resolves and stores the final waveforms."""
    new_w = [116.0]
    new_bw = [115.0]
    plan = build_reconciliation_plan(
        existing=_make_open_snap([120.0], [100.0]),
        metrics=None,
        actual_kw=Decimal("120.00"),
        interval_seconds=900,
        fallback_baseline_kw=Decimal("115.00"),   # z ≈ 1.1 → below threshold → RESOLVED
        fallback_raw_mean_kw=Decimal("115.00"),
        fallback_z_score=Decimal("1.10"),
        applicable_rate=Decimal("0.20"),
        new_waveform=new_w,
        new_baseline_waveform=new_bw,
    )
    assert plan.new_status == AnomalyStatus.RESOLVED
    assert plan.log_from_status == AnomalyStatus.OPEN
    assert plan.log_to_status == AnomalyStatus.RESOLVED
    assert plan.new_waveform == new_w
    assert plan.new_baseline_waveform == new_bw
