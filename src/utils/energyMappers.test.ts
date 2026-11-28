import { describe, expect, it } from 'vitest';
import {
  buildBackendCsvExportRows,
  buildHeatmapMatrixFromReadings,
  calculateLiveDashboardKpis,
  filterReadingsBySourceScope,
  filterReadingsByTimeWindow,
  formatCurrency,
  getCostEstimateStatusLabel,
  mapAnomalyResponse,
  mapFacilityResponse,
  mapInsightResponse,
  mapMetersToAssets,
  mapSummarySeriesToTelemetryPoints,
  mapSummaryZonesToSubMeters,
  mapTelemetryReadingsToSeries,
  mapZonesToSubMeters,
  serializeBackendCsv,
  toNullableNumber,
  toNumber,
} from './energyMappers';
import {
  AnomalyResponse,
  FacilityResponse,
  InsightResponse,
  MeterResponse,
  TelemetryReadingResponse,
  ZoneResponse,
} from '../types/api';

const SAMPLE_FACILITY: FacilityResponse = {
  id: 'north-assembly',
  code: 'PLT-NA01',
  name: 'North Assembly Plant',
  location: 'Detroit Sector B',
  timezone: 'UTC',
  currency_code: 'USD',
  contracted_demand_kw: '1850.00',
  off_peak_tariff_rate: '0.1180',
  mid_peak_tariff_rate: '0.1550',
  peak_tariff_rate: '0.2140',
  is_active: true,
  deactivated_at: null,
  created_at: '2026-11-01T00:00:00Z',
  zone_count: 2,
  active_zone_count: 2,
  meter_count: 2,
  active_meter_count: 2,
};

const SAMPLE_ZONES: ZoneResponse[] = [
  {
    id: 'z-1',
    facility_id: 'north-assembly',
    slug: 'cnc',
    name: 'CNC Machining Line 1–4',
    primary_meter_code: 'MTR-104',
    share_pct: '60.00',
    status: 'Nominal',
    is_active: true,
    deactivated_at: null,
    meter_count: 1,
    active_meter_count: 1,
  },
  {
    id: 'z-2',
    facility_id: 'north-assembly',
    slug: 'air',
    name: 'Compressed Air Header',
    primary_meter_code: 'MTR-208',
    share_pct: '40.00',
    status: 'Fault',
    is_active: true,
    deactivated_at: null,
    meter_count: 1,
    active_meter_count: 1,
  },
];

const SAMPLE_METERS: MeterResponse[] = [
  {
    id: 'm-1',
    facility_id: 'north-assembly',
    zone_id: 'z-1',
    meter_code: 'MTR-104',
    equipment_name: '5-Axis CNC Bank A',
    rated_kw: '800.00',
    nominal_interval_seconds: 3600,
    current_kw: '600.00',
    power_factor: '0.940',
    thd_pct: '3.10',
    status: 'Nominal',
    last_calibrated_at: '2026-09-14',
    is_active: true,
    deactivated_at: null,
  },
  {
    id: 'm-2',
    facility_id: 'north-assembly',
    zone_id: 'z-2',
    meter_code: 'MTR-208',
    equipment_name: 'Rotary Screw Compressor #2',
    rated_kw: '450.00',
    nominal_interval_seconds: 3600,
    current_kw: '420.00',
    power_factor: '0.840',
    thd_pct: '6.80',
    status: 'Fault',
    last_calibrated_at: '2026-08-02',
    is_active: true,
    deactivated_at: null,
  },
];

const SAMPLE_READINGS: TelemetryReadingResponse[] = [
  {
    id: 1,
    facility_id: 'north-assembly',
    zone_id: 'z-1',
    meter_id: 'm-1',
    interval_start: '2026-11-18T13:00:00Z',
    recorded_at: '2026-11-18T14:00:00Z',
    interval_seconds: 3600,
    actual_kw: '600.00',
    energy_kwh: '600.0000',
    baseline_kw: '580.00',
    std_dev_kw: '25.00',
    z_score: '0.80',
    baseline_status: 'ready',
    power_factor: '0.940',
    tariff_period: 'Peak',
    ambient_temp_c: '22.50',
    quality_flag: 'valid',
    source: 'meter_feed',
  },
  {
    id: 2,
    facility_id: 'north-assembly',
    zone_id: 'z-2',
    meter_id: 'm-2',
    interval_start: '2026-11-18T13:00:00Z',
    recorded_at: '2026-11-18T14:00:00Z',
    interval_seconds: 3600,
    actual_kw: '420.00',
    energy_kwh: '420.0000',
    baseline_kw: '280.00',
    std_dev_kw: '20.00',
    z_score: '7.00',
    baseline_status: 'ready',
    power_factor: '0.840',
    tariff_period: 'Peak',
    ambient_temp_c: '22.50',
    quality_flag: 'valid',
    source: 'meter_feed',
  },
  {
    id: 3,
    facility_id: 'north-assembly',
    zone_id: 'z-1',
    meter_id: 'm-1',
    interval_start: '2026-11-01T13:00:00Z',
    recorded_at: '2026-11-01T14:00:00Z',
    interval_seconds: 3600,
    actual_kw: '500.00',
    energy_kwh: '500.0000',
    baseline_kw: null,
    std_dev_kw: null,
    z_score: null,
    baseline_status: 'insufficient_history',
    power_factor: '0.950',
    tariff_period: 'Off-Peak',
    ambient_temp_c: null,
    quality_flag: 'valid',
    source: 'seed',
  },
];

describe('energyMappers', () => {
  it('parses Decimal strings and nullable cost fields without treating null as zero', () => {
    expect(toNumber('1850.00')).toBe(1850);
    expect(toNullableNumber(null)).toBeNull();
    expect(formatCurrency(null, 'USD')).toBe('Unavailable');
    expect(getCostEstimateStatusLabel('unavailable_tariff')).toBe('Tariff unavailable');
  });

  it('aggregates telemetry, zones, heatmaps, anomalies, insights, KPIs, and CSV rows accurately', () => {
    const facility = mapFacilityResponse(SAMPLE_FACILITY);
    const meters = mapMetersToAssets(SAMPLE_METERS, SAMPLE_ZONES);
    const windowed24h = filterReadingsByTimeWindow(SAMPLE_READINGS, '24h');
    expect(windowed24h).toHaveLength(2);

    const zones = mapZonesToSubMeters(SAMPLE_ZONES, windowed24h, SAMPLE_METERS);
    const series = mapTelemetryReadingsToSeries(windowed24h, SAMPLE_ZONES, '24h', 'UTC');
    const matrix = buildHeatmapMatrixFromReadings(windowed24h, 'UTC');

    expect(series).toHaveLength(1);
    expect(series[0].actualKw).toBe(1020);
    expect(zones[1].deltaVsBaselinePct).toBe(50);
    expect(matrix[2][14]).toBe(1020);

    const anomalyRaw: AnomalyResponse = {
      id: 'a-1',
      event_code: 'ANM-001',
      facility_id: 'north-assembly',
      zone_id: 'z-2',
      meter_id: 'm-2',
      reading_id: 2,
      detected_at: '2026-11-18T14:00:00Z',
      severity: 'Critical',
      status: 'Open',
      z_score: '7.00',
      actual_kw: '420.00',
      expected_kw: '280.00',
      deviation_pct: '50.0',
      duration_min: 60,
      estimated_waste_kwh: '140.00',
      estimated_cost: null,
      cost_estimate_status: 'unavailable_tariff',
      signature: 'Compressor surge',
      recommendation: 'Inspect solenoid',
      assigned_to_user_id: null,
    };

    const insightRaw: InsightResponse = {
      id: 'ins-1',
      facility_id: 'north-assembly',
      zone_id: 'z-2',
      meter_id: 'm-2',
      rule_code: 'OFF_PEAK_BASELOAD_PATTERN',
      dedupe_key: 'k-1',
      title: 'Fix solenoid',
      category: 'Compressed Air',
      summary: 'Idle draw',
      monthly_kwh_savings: '1200.00',
      annual_cost_savings: '15000.00',
      payback_months: '2.5',
      cost_estimate_status: 'available',
      savings_basis: 'estimated_excess_avoidance',
      priority: 'High',
      status: 'Recommended',
      updated_at: '2026-11-18T14:00:00Z',
    };

    const mappedAnomaly = mapAnomalyResponse(
      anomalyRaw,
      SAMPLE_ZONES,
      SAMPLE_METERS,
      'UTC',
      windowed24h
    );
    const mappedInsight = mapInsightResponse(insightRaw, SAMPLE_ZONES, SAMPLE_METERS);

    const kpis = calculateLiveDashboardKpis({
      facility,
      readings: windowed24h,
      series,
      anomalies: [mappedAnomaly],
      insights: [mappedInsight],
      meters,
      selectedZoneId: null,
    });

    expect(kpis.totalMwh).toBeCloseTo(1.02, 3);
    expect(kpis.potentialSavingsAmount).toBe(15000);
    expect(kpis.hasQuantifiedSavings).toBe(true);

    const csvRows = buildBackendCsvExportRows({
      readings: windowed24h,
      facility,
      zones: SAMPLE_ZONES,
      meters: SAMPLE_METERS,
      anomalies: [mappedAnomaly],
    });
    const csv = serializeBackendCsv(csvRows, 'both');
    expect(csv).toContain('Consumption_kWh,Consumption_MWh');
    expect(csv).toContain('ANOMALY');
  });

  it('filters telemetry by sourceScope and overlays live meter snapshots & summary series', () => {
    const mixedReadings: TelemetryReadingResponse[] = [
      ...SAMPLE_READINGS,
      {
        ...SAMPLE_READINGS[0],
        id: 99,
        actual_kw: '950.00',
        energy_kwh: '950.0000',
        source: 'simulation',
      },
    ];

    expect(filterReadingsBySourceScope(mixedReadings, 'measured')).toHaveLength(3);
    expect(filterReadingsBySourceScope(mixedReadings, 'all')).toHaveLength(4);
    const simOnly = filterReadingsBySourceScope(mixedReadings, 'simulation');
    expect(simOnly).toHaveLength(1);
    expect(simOnly[0].id).toBe(99);

    const metersWithLive = mapMetersToAssets(SAMPLE_METERS, SAMPLE_ZONES, [
      {
        meter_id: 'm-1',
        meter_code: 'MTR-104',
        zone_id: 'z-1',
        latest_recorded_at: '2026-11-18T15:00:00Z',
        latest_kw: 712.5,
        avg_kw: 630.0,
        peak_kw: 740.0,
        latest_power_factor: 0.912,
        reading_count: 12,
        open_anomalies_count: 0,
        derived_status: 'Warning',
      },
    ]);
    expect(metersWithLive[0].currentKw).toBe(712.5);
    expect(metersWithLive[0].powerFactor).toBe(0.912);
    expect(metersWithLive[0].status).toBe('Warning');

    const summaryZones = mapSummaryZonesToSubMeters(
      [
        {
          zone_id: 'z-1',
          slug: 'cnc',
          name: 'CNC Machining Line 1–4',
          primary_meter_code: 'MTR-104',
          kwh_used: 1200.4,
          share_pct: 65.5,
          avg_kw: 610,
          peak_kw: 740,
          power_factor: 0.93,
          delta_vs_baseline_pct: 4.2,
          derived_status: 'Nominal',
          reading_count: 12,
        },
      ],
      SAMPLE_ZONES
    );
    expect(summaryZones).toHaveLength(1);
    expect(summaryZones[0].sharePct).toBe(65.5);
    expect(summaryZones[0].kwhUsed).toBe(1200.4);
    expect(summaryZones[0].powerFactor).toBe(0.93);

    const summaryPoints = mapSummarySeriesToTelemetryPoints(
      [
        {
          timestamp: '2026-11-18T14:00:00Z',
          label: 'Nov 18 14:00',
          actual_kw: 1020,
          baseline_kw: 860,
          std_dev_kw: 32.02,
          power_factor: 0.9,
          tariff_period: 'Peak',
          ambient_temp_c: 22.5,
          z_score: 7.0,
          zone_id: 'z-2',
          has_baseline: true,
        },
      ],
      SAMPLE_ZONES,
      SAMPLE_READINGS
    );
    expect(summaryPoints[0].id).toMatch(/^(reading-|bucket-)/);
    expect(summaryPoints[0].zone).toBe('Compressed Air Header');
  });
});

