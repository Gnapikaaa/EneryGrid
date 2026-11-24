import { describe, expect, it } from 'vitest';
import {
  FACILITIES,
  buildConsumptionCsvContent,
  buildCsvContent,
  calculateKpis,
  detectAnomaliesFromSeries,
  generateTelemetrySeries,
  getAnomalyStatusKey,
  getAvailableMetersForFilter,
  getFilteredConsumptionData,
  getScopedDemandCeilingKw,
  getScopedHeatmapMatrix,
  getTimeWindowDateBounds,
} from './energyData';

describe('energyData analytical engine', () => {
  it('generates expected interval counts for 24h, 7d, and 30d windows', () => {
    expect(generateTelemetrySeries('north-assembly', '24h')).toHaveLength(24);
    expect(generateTelemetrySeries('north-assembly', '7d')).toHaveLength(28);
    expect(generateTelemetrySeries('north-assembly', '30d')).toHaveLength(30);
  });

  it('scopes telemetry series and anomalies accurately to the selected zone', () => {
    const facility = FACILITIES['north-assembly'];
    const airSeries = generateTelemetrySeries('north-assembly', '24h', 0, 'air');
    const cncSeries = generateTelemetrySeries('north-assembly', '24h', 0, 'cnc');

    expect(airSeries.every((pt) => pt.zone === 'Compressed Air Header')).toBe(true);
    expect(cncSeries.every((pt) => pt.zone === 'CNC Machining Line 1–4')).toBe(true);

    const airAnomalies = detectAnomaliesFromSeries(facility, airSeries, 2.0, {}, '24h');
    const cncAnomalies = detectAnomaliesFromSeries(facility, cncSeries, 2.0, {}, '24h');

    // Compressed Air Header has known off-shift cycling + PF spike anomalies; CNC is nominal
    expect(airAnomalies.length).toBeGreaterThan(0);
    expect(airAnomalies.every((a) => a.zone === 'Compressed Air Header')).toBe(true);
    expect(cncAnomalies).toHaveLength(0);
  });

  it('detects synthetic load spikes both facility-wide and when scoped to a nominal zone', () => {
    const facility = FACILITIES['north-assembly'];
    const cncBaseline = generateTelemetrySeries('north-assembly', '24h', 0, 'cnc');
    const cncWithSpike = generateTelemetrySeries('north-assembly', '24h', 480, 'cnc');

    const before = detectAnomaliesFromSeries(facility, cncBaseline, 2.0, {}, '24h');
    const after = detectAnomaliesFromSeries(facility, cncWithSpike, 2.0, {}, '24h');

    expect(before).toHaveLength(0);
    expect(after.length).toBe(1);
    expect(after[0].signature).toContain('Simulated fault injection');
  });

  it('isolates anomaly status overrides across facilities and time windows', () => {
    const north = FACILITIES['north-assembly'];
    const foundry = FACILITIES['foundry-press'];
    const northSeries = generateTelemetrySeries('north-assembly', '24h');
    const foundrySeries = generateTelemetrySeries('foundry-press', '24h');

    const northFirst = detectAnomaliesFromSeries(north, northSeries, 2.0, {}, '24h')[0];
    const overrideKey = getAnomalyStatusKey('north-assembly', '24h', northFirst.id);
    const overrides = { [overrideKey]: 'Resolved' as const };

    const updatedNorth = detectAnomaliesFromSeries(north, northSeries, 2.0, overrides, '24h');
    const updatedFoundry = detectAnomaliesFromSeries(foundry, foundrySeries, 2.0, overrides, '24h');

    expect(updatedNorth.find((a) => a.id === northFirst.id)?.status).toBe('Resolved');
    expect(updatedFoundry.every((a) => a.status === 'Open')).toBe(true);
  });

  it('computes scoped demand ceilings, heatmaps, KPIs, and CSV output consistently', () => {
    const facility = FACILITIES['north-assembly'];
    const airZone = facility.zones.find((z) => z.id === 'air')!;
    const airMatrix = getScopedHeatmapMatrix(facility, 'air');

    expect(airMatrix).toHaveLength(7);
    expect(airMatrix[0]).toHaveLength(24);
    expect(getScopedDemandCeilingKw(facility, null)).toBe(facility.contractedDemandKw);
    // Compressed Air Header has MTR-208 (450 kW) + MTR-211 (160 kW) = 610 kW
    expect(getScopedDemandCeilingKw(facility, 'air')).toBe(610);

    const series = generateTelemetrySeries('north-assembly', '24h', 0, 'air');
    const anomalies = detectAnomaliesFromSeries(facility, series, 2.0, {}, '24h');
    const kpis = calculateKpis(facility, series, '24h', anomalies, airZone);

    expect(kpis.demandCeilingKw).toBe(610);
    expect(kpis.totalMwh).toBeGreaterThan(0);
    expect(kpis.openAnomaliesCount).toBe(anomalies.length);

    const csv = buildCsvContent(facility, series, anomalies);
    const lines = csv.split('\n');
    expect(lines[0]).toBe(
      'Facility,Timestamp,Actual_kW,Baseline_kW,StdDev_kW,Z_Score,Power_Factor,Tariff_Period,Zone,Anomaly_Flag'
    );
    expect(lines).toHaveLength(series.length + 1);
    expect(lines.some((line) => line.endsWith(',ANOMALY'))).toBe(true);
  });

  it('exports energy consumption matching dashboard KPIs with accurate kWh and MWh conversions across time windows', () => {
    const facility = FACILITIES['north-assembly'];
    const airZone = facility.zones.find((z) => z.id === 'air')!;

    for (const window of ['24h', '7d', '30d'] as const) {
      const bounds = getTimeWindowDateBounds(window);
      const series = generateTelemetrySeries('north-assembly', window, 0, 'air');
      const anomalies = detectAnomaliesFromSeries(facility, series, 2.0, {}, window);
      const kpis = calculateKpis(facility, series, window, anomalies, airZone);

      const exported = getFilteredConsumptionData({
        facilityId: 'north-assembly',
        zoneId: 'air',
        meterCode: null,
        startDate: bounds.startDate,
        endDate: bounds.endDate,
        timeWindow: window,
      });

      expect(exported.rows).toHaveLength(series.length);
      expect(exported.totalMwh).toBeCloseTo(kpis.totalMwh, 3);
      expect(exported.totalKwh).toBeCloseTo(kpis.totalMwh * 1000, 1);

      const expectedHours = window === '24h' ? 1 : window === '7d' ? 6 : 24;
      expect(exported.intervalHours).toBe(expectedHours);
      expect(exported.rows[0].consumptionKwh).toBe(exported.rows[0].actualKw * expectedHours);
      expect(exported.rows[0].consumptionMwh).toBeCloseTo(
        exported.rows[0].consumptionKwh / 1000,
        4
      );
    }
  });

  it('filters consumption exports by meter, date range, and energy unit columns', () => {
    const north = FACILITIES['north-assembly'];
    const airMeters = getAvailableMetersForFilter(north, 'air');
    expect(airMeters.map((m) => m.meterCode)).toEqual(['MTR-208', 'MTR-211']);

    const zoneExport = getFilteredConsumptionData({
      facilityId: 'north-assembly',
      zoneId: 'air',
      meterCode: null,
      startDate: '2026-11-12',
      endDate: '2026-11-18',
      timeWindow: '7d',
    });

    const mtr208Export = getFilteredConsumptionData({
      facilityId: 'north-assembly',
      zoneId: 'air',
      meterCode: 'MTR-208',
      startDate: '2026-11-12',
      endDate: '2026-11-18',
      timeWindow: '7d',
    });

    const mtr211Export = getFilteredConsumptionData({
      facilityId: 'north-assembly',
      zoneId: 'air',
      meterCode: 'MTR-211',
      startDate: '2026-11-12',
      endDate: '2026-11-18',
      timeWindow: '7d',
    });

    expect(mtr208Export.rows.every((r) => r.meterCode === 'MTR-208')).toBe(true);
    expect(mtr211Export.rows.every((r) => r.meterCode === 'MTR-211')).toBe(true);
    expect(mtr208Export.totalKwh + mtr211Export.totalKwh).toBeCloseTo(zoneExport.totalKwh, -2);

    // Date range subsetting
    const twoDayExport = getFilteredConsumptionData({
      facilityId: 'north-assembly',
      zoneId: null,
      meterCode: null,
      startDate: '2026-11-14',
      endDate: '2026-11-15',
      timeWindow: '7d',
    });
    expect(twoDayExport.rows).toHaveLength(8);
    expect(twoDayExport.rows.every((r) => r.date === '2026-11-14' || r.date === '2026-11-15')).toBe(
      true
    );

    // Invalid date range yields 0 rows
    const invalidExport = getFilteredConsumptionData({
      facilityId: 'north-assembly',
      zoneId: null,
      meterCode: null,
      startDate: '2026-11-20',
      endDate: '2026-11-10',
      timeWindow: '30d',
    });
    expect(invalidExport.rows).toHaveLength(0);
    expect(invalidExport.totalKwh).toBe(0);

    // Unit column modes
    const bothCsv = buildConsumptionCsvContent(twoDayExport.rows, 'both').split('\n')[0];
    const kwhCsv = buildConsumptionCsvContent(twoDayExport.rows, 'kwh').split('\n')[0];
    const mwhCsv = buildConsumptionCsvContent(twoDayExport.rows, 'mwh').split('\n')[0];

    expect(bothCsv).toContain('Consumption_kWh,Consumption_MWh');
    expect(kwhCsv).toContain('Consumption_kWh');
    expect(kwhCsv).not.toContain('Consumption_MWh');
    expect(mwhCsv).toContain('Consumption_MWh');
    expect(mwhCsv).not.toContain('Consumption_kWh');
  });
});

