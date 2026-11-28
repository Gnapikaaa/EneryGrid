from datetime import UTC, datetime, timedelta
from decimal import Decimal
import unittest

from app.services.analytics_summary_math import (
    SummarySampleRow,
    build_series_and_heatmap,
    compute_interval_demand_stats,
    compute_trend_pct,
    derive_health_status,
    resolve_window_bounds,
)


class AnalyticsSummaryMathTests(unittest.TestCase):
    def test_window_bounds_and_trend_calculations(self) -> None:
        anchor = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
        w_start, w_end, p_start, p_end = resolve_window_bounds(
            time_window="24h",
            anchor_utc=anchor,
        )
        self.assertEqual(w_end, anchor)
        self.assertEqual(w_start, datetime(2026, 11, 19, 12, 0, tzinfo=UTC))
        self.assertEqual(p_end, w_start)
        self.assertEqual(p_start, datetime(2026, 11, 18, 12, 0, tzinfo=UTC))

        self.assertIsNone(compute_trend_pct(100.0, 0.0, 0))
        self.assertEqual(compute_trend_pct(125.0, 100.0, 10), 25.0)
        self.assertEqual(compute_trend_pct(80.0, 100.0, 10), -20.0)

    def test_health_status_derivation_from_live_anomalies_and_pf(self) -> None:
        self.assertEqual(
            derive_health_status(latest_pf=0.95, open_critical_or_high=1, open_elevated=0),
            "Fault",
        )
        self.assertEqual(
            derive_health_status(latest_pf=0.82, open_critical_or_high=0, open_elevated=0),
            "Fault",
        )
        self.assertEqual(
            derive_health_status(latest_pf=0.88, open_critical_or_high=0, open_elevated=0),
            "Warning",
        )
        self.assertEqual(
            derive_health_status(latest_pf=0.94, open_critical_or_high=0, open_elevated=0),
            "Nominal",
        )
        self.assertEqual(
            derive_health_status(latest_pf=None, open_critical_or_high=0, open_elevated=0, fallback_status="Warning"),
            "Warning",
        )

    def test_series_and_heatmap_sum_concurrent_meters_accurately(self) -> None:
        t1 = datetime(2026, 11, 16, 14, 0, tzinfo=UTC)  # Monday 14:00 UTC
        samples = [
            SummarySampleRow(
                meter_id="m1",
                zone_id="11111111-1111-1111-1111-111111111111",
                recorded_at=t1,
                interval_seconds=3600,
                actual_kw=Decimal("600.00"),
                energy_kwh=Decimal("600.0000"),
                baseline_kw=Decimal("580.00"),
                std_dev_kw=Decimal("20.00"),
                z_score=Decimal("1.00"),
                power_factor=Decimal("0.940"),
                tariff_period="Peak",
                ambient_temp_c=Decimal("21.00"),
            ),
            SummarySampleRow(
                meter_id="m2",
                zone_id="22222222-2222-2222-2222-222222222222",
                recorded_at=t1,
                interval_seconds=3600,
                actual_kw=Decimal("400.00"),
                energy_kwh=Decimal("400.0000"),
                baseline_kw=Decimal("250.00"),
                std_dev_kw=Decimal("15.00"),
                z_score=Decimal("10.00"),
                power_factor=Decimal("0.840"),
                tariff_period="Peak",
                ambient_temp_c=Decimal("21.00"),
            ),
        ]
        series, heatmap = build_series_and_heatmap(
            samples,
            time_window="24h",
            window_start=datetime(2026, 11, 15, 14, 0, tzinfo=UTC),
            window_end=t1,
            timezone_name="UTC",
        )
        self.assertEqual(len(series), 1)
        self.assertEqual(series[0]["actual_kw"], 1000.0)
        self.assertEqual(series[0]["baseline_kw"], 830.0)
        self.assertEqual(series[0]["z_score"], 10.0)
        self.assertEqual(heatmap[0][14], 1000)

    def test_interval_demand_stats_preserves_true_peak_across_7d_bucketing(self) -> None:
        t1 = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
        t2 = t1 + timedelta(minutes=15)
        samples = [
            SummarySampleRow(
                meter_id="m1",
                zone_id="z1",
                recorded_at=t1,
                interval_seconds=900,
                actual_kw=Decimal("100.00"),
                energy_kwh=Decimal("25.0000"),
                baseline_kw=None,
                std_dev_kw=None,
                z_score=None,
                power_factor=Decimal("0.920"),
                tariff_period="Mid-Peak",
                ambient_temp_c=None,
            ),
            SummarySampleRow(
                meter_id="m1",
                zone_id="z1",
                recorded_at=t2,
                interval_seconds=900,
                actual_kw=Decimal("628.72"),
                energy_kwh=Decimal("157.1800"),
                baseline_kw=None,
                std_dev_kw=None,
                z_score=None,
                power_factor=Decimal("0.920"),
                tariff_period="Mid-Peak",
                ambient_temp_c=None,
            ),
        ]
        avg_kw, peak_kw = compute_interval_demand_stats(samples)
        self.assertEqual(avg_kw, 364.36)
        self.assertEqual(peak_kw, 628.72)


if __name__ == "__main__":
    unittest.main()
