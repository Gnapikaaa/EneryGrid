from datetime import UTC, datetime
from decimal import Decimal
import io
import unittest

from app.services.dataset_adapters import (
    compute_pf_from_pq,
    iter_uci_household_rows,
    iter_uci_steel_rows,
    rows_to_energygrid_csv_bytes,
)


class DatasetAdapterTests(unittest.TestCase):
    def test_uci_steel_parses_real_15min_units_and_localizes_seoul_to_utc(self) -> None:
        sample_csv = (
            "date,Usage_kWh,Lagging_Current_Reactive.Power_kVarh,"
            "Leading_Current_Reactive_Power_kVarh,CO2(tCO2),Lagging_Current_Power_Factor,"
            "Leading_Current_Power_Factor,NSM,WeekStatus,Day_of_week,Load_Type\n"
            "01/01/2018 00:15,3.17,2.95,0,0,73.21,100,900,Weekday,Monday,Light_Load\n"
            "01/01/2018 00:30,4.00,0,1.20,0,0,94.5,1800,Weekday,Monday,Light_Load\n"
            "01/01/2018 00:45,?,0,0,0,0,0,2700,Weekday,Monday,Light_Load\n"
        )
        stats: dict[str, int] = {}
        rows = list(
            iter_uci_steel_rows(
                io.StringIO(sample_csv),
                meter_code="MTR-STEEL-01",
                source_timezone="Asia/Seoul",
                stats_out=stats,
            )
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual(stats["total_rows_read"], 3)
        self.assertEqual(stats["emitted_rows"], 2)
        self.assertEqual(stats["skipped_missing_rows"], 1)

        # 2018-01-01 00:15 KST (+09:00) == 2017-12-31 15:15 UTC
        self.assertEqual(rows[0].recorded_at, datetime(2017, 12, 31, 15, 15, tzinfo=UTC))
        self.assertEqual(rows[0].interval_seconds, 900)
        self.assertEqual(rows[0].energy_kwh, Decimal("3.1700"))
        self.assertEqual(rows[0].actual_kw, Decimal("12.68"))
        self.assertEqual(rows[0].power_factor, Decimal("0.732"))
        self.assertEqual(rows[0].source, "csv_import")
        self.assertEqual(rows[0].quality_flag, "valid")

        # Fallback to leading PF when lagging PF is 0
        self.assertEqual(rows[1].power_factor, Decimal("0.945"))
        self.assertEqual(rows[1].actual_kw, Decimal("16.00"))

        csv_text = rows_to_energygrid_csv_bytes(rows).decode("utf-8")
        self.assertIn("meter_code,recorded_at,interval_seconds,actual_kw,energy_kwh", csv_text)
        self.assertIn("MTR-STEEL-01,2017-12-31T15:15:00+00:00,900,12.68,3.1700,0.732", csv_text)

    def test_uci_household_resamples_1min_semicolon_data_and_skips_question_marks(self) -> None:
        sample_txt = (
            "Date;Time;Global_active_power;Global_reactive_power;Voltage;Global_intensity;"
            "Sub_metering_1;Sub_metering_2;Sub_metering_3\n"
            "16/12/2006;17:24:00;4.000;0.400;234.840;18.400;0.000;1.000;17.000\n"
            "16/12/2006;17:25:00;2.000;0.200;233.630;23.000;0.000;1.000;16.000\n"
            "16/12/2006;17:26:00;?;?;?;?;?;?;?\n"
            "16/12/2006;17:30:00;3.000;0.000;235.000;13.000;0.000;0.000;18.000\n"
        )
        stats: dict[str, int] = {}
        rows = list(
            iter_uci_household_rows(
                io.StringIO(sample_txt),
                meter_code="MTR-HH-01",
                source_timezone="Europe/Paris",
                resample_minutes=15,
                stats_out=stats,
            )
        )

        # All timestamps 17:24..17:30 CET (+01:00 -> 16:24..16:30 UTC) fall in [16:15, 16:30) or next bucket:
        # 16:24 & 16:25 -> bucket end 16:30 UTC; 16:30 -> bucket end 16:45 UTC
        self.assertEqual(len(rows), 2)
        self.assertEqual(stats["skipped_missing_rows"], 1)
        self.assertEqual(rows[0].recorded_at, datetime(2006, 12, 16, 16, 30, tzinfo=UTC))
        self.assertEqual(rows[0].actual_kw, Decimal("3.00"))
        self.assertEqual(rows[0].energy_kwh, Decimal("0.7500"))
        self.assertEqual(rows[0].power_factor, compute_pf_from_pq(Decimal("3.000"), Decimal("0.300")))
        self.assertEqual(rows[1].recorded_at, datetime(2006, 12, 16, 16, 45, tzinfo=UTC))
        self.assertEqual(rows[1].power_factor, Decimal("1.000"))

    def test_missing_headers_raise_value_error(self) -> None:
        with self.assertRaises(ValueError):
            list(iter_uci_steel_rows(io.StringIO("wrong,cols\n1,2\n"), meter_code="MTR-1"))


if __name__ == "__main__":
    unittest.main()
