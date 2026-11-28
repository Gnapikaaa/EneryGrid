import {
  AnalyticsSeriesBucketItem,
  AnomalyDetailResponse,
  AnomalyResponse,
  AnomalySeverity,
  AnomalyStatus,
  CostEstimateStatus,
  DecimalValue,
  FacilityResponse,
  HealthStatus,
  InsightCategory,
  InsightDetailResponse,
  InsightPriority,
  InsightResponse,
  InsightRuleCode,
  InsightSavingsBasis,
  InsightStatus,
  MeterLiveSnapshotItem,
  MeterResponse,
  TariffPeriod,
  TelemetryReadingResponse,
  ZoneAnalyticsSummaryItem,
  ZoneResponse,
} from '../types/api';
import {
  DataSourceScope,
  EnergyUnitMode,
  TelemetryPoint,
  TimeWindow,
} from '../types/energy';

export interface MappedFacility {
  id: string;
  code: string;
  name: string;
  location: string;
  timezone: string;
  currencyCode: string;
  contractedDemandKw: number;
  offPeakTariffRate: number;
  midPeakTariffRate: number;
  peakTariffRate: number;
  isActive: boolean;
  zoneCount: number;
  activeZoneCount: number;
  meterCount: number;
  activeMeterCount: number;
}

export interface MappedZone {
  id: string;
  facilityId: string;
  slug: string;
  name: string;
  meterCode: string;
  sharePct: number;
  kwhUsed: number;
  peakKw: number;
  powerFactor: number;
  deltaVsBaselinePct: number;
  status: HealthStatus;
  isActive: boolean;
  meterCount: number;
  activeMeterCount: number;
}

export interface MappedMeter {
  id: string;
  facilityId: string;
  zoneId: string;
  meterCode: string;
  equipmentName: string;
  zone: string;
  ratedKw: number;
  nominalIntervalSeconds: number;
  currentKw: number;
  powerFactor: number;
  thdPct: number;
  lastCalibrated: string;
  status: HealthStatus;
  isActive: boolean;
}

export interface MappedAnomaly {
  id: string;
  eventCode: string;
  facilityId: string;
  zoneId: string;
  meterId: string;
  readingId: number | null;
  pointId: string | null;
  detectedAt: string;
  timestamp: string;
  meterCode: string;
  zone: string;
  severity: AnomalySeverity;
  status: AnomalyStatus;
  zScore: number;
  actualKw: number;
  expectedKw: number;
  deviationPct: number;
  durationMin: number;
  estimatedWasteKwh: number;
  estimatedCost: number | null;
  costEstimateStatus: CostEstimateStatus;
  signature: string;
  recommendation: string;
  assignedToUserId: string | null;
  waveform: number[];
  baselineWaveform: number[];
}

export interface MappedInsight {
  id: string;
  facilityId: string;
  zoneId: string;
  meterId: string | null;
  meterCode: string | null;
  ruleCode: InsightRuleCode;
  dedupeKey: string;
  title: string;
  category: InsightCategory;
  zone: string;
  summary: string;
  monthlyKwhSavings: number;
  annualCostSavings: number | null;
  paybackMonths: number | null;
  costEstimateStatus: CostEstimateStatus;
  savingsBasis: InsightSavingsBasis;
  priority: InsightPriority;
  status: InsightStatus;
  updatedAt: string;
  evidence: Record<string, unknown> | null;
}

export interface LiveDashboardKpis {
  totalMwh: number;
  avgDemandKw: number;
  consumptionTrendPct: number | null;
  peakDemandKw: number;
  demandCeilingKw: number;
  demandHeadroomPct: number;
  avgPf: number;
  openAnomaliesCount: number;
  criticalCount: number;
  potentialSavingsAmount: number;
  hasQuantifiedSavings: boolean;
  unquantifiedInsightsCount: number;
}

export interface BackendCsvExportRow {
  facilityName: string;
  facilityCode: string;
  timestamp: string;
  zone: string;
  meterCode: string;
  equipmentName: string;
  intervalHours: number;
  actualKw: number;
  baselineKw: number | null;
  consumptionKwh: number;
  consumptionMwh: number;
  powerFactor: number;
  tariffPeriod: TariffPeriod;
  zScore: number | null;
  qualityFlag: string;
  source: string;
  anomalyFlag: 'ANOMALY' | 'NORMAL';
}

export function toNumber(value: DecimalValue | null | undefined, fallback = 0): number {
  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : fallback;
  }
  if (typeof value === 'string') {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
  }
  return fallback;
}

export function toNullableNumber(value: DecimalValue | null | undefined): number | null {
  if (value === null || value === undefined || value === '') return null;
  const parsed = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function formatCurrency(
  amount: number | null | undefined,
  currencyCode = 'USD',
  options?: { maximumFractionDigits?: number; minimumFractionDigits?: number; fallbackLabel?: string }
): string {
  if (amount === null || amount === undefined || !Number.isFinite(amount)) {
    return options?.fallbackLabel ?? 'Unavailable';
  }
  const normalizedCode = (currencyCode || 'USD').trim().toUpperCase();
  const minFrac = options?.minimumFractionDigits ?? 0;
  const maxFrac = options?.maximumFractionDigits ?? 0;

  try {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: normalizedCode,
      minimumFractionDigits: minFrac,
      maximumFractionDigits: maxFrac,
    }).format(amount);
  } catch {
    return `${normalizedCode} ${amount.toFixed(maxFrac)}`;
  }
}

export function getCostEstimateStatusLabel(status: CostEstimateStatus): string {
  switch (status) {
    case 'unavailable_tariff':
      return 'Tariff unavailable';
    case 'not_quantifiable':
      return 'Not quantifiable';
    case 'legacy_unverified':
      return 'Legacy unverified';
    case 'available':
    default:
      return '';
  }
}

export function getSavingsBasisLabel(basis: InsightSavingsBasis): string {
  switch (basis) {
    case 'tariff_arbitrage_only':
      return 'Tariff arbitrage only';
    case 'estimated_excess_avoidance':
      return 'Estimated excess avoidance';
    case 'unquantified_telemetry':
      return 'Unquantified telemetry';
    case 'legacy_migrated':
      return 'Legacy migrated';
    default:
      return String(basis);
  }
}

function getZonedDateParts(
  isoString: string,
  timeZone = 'UTC'
): {
  year: string;
  month: string;
  day: string;
  hour: string;
  minute: string;
  weekdayIndex: number; // 0 = Mon .. 6 = Sun
} {
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) {
    return { year: '1970', month: '01', day: '01', hour: '00', minute: '00', weekdayIndex: 0 };
  }

  let parts: Intl.DateTimeFormatPart[];
  try {
    parts = new Intl.DateTimeFormat('en-US', {
      timeZone,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      weekday: 'short',
      hour12: false,
    }).formatToParts(date);
  } catch {
    parts = new Intl.DateTimeFormat('en-US', {
      timeZone: 'UTC',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      weekday: 'short',
      hour12: false,
    }).formatToParts(date);
  }

  const lookup: Record<string, string> = {};
  for (const part of parts) {
    lookup[part.type] = part.value;
  }
  const rawHour = lookup.hour === '24' ? '00' : (lookup.hour ?? '00');
  const weekdayMap: Record<string, number> = {
    Mon: 0,
    Tue: 1,
    Wed: 2,
    Thu: 3,
    Fri: 4,
    Sat: 5,
    Sun: 6,
  };

  return {
    year: lookup.year ?? '1970',
    month: lookup.month ?? '01',
    day: lookup.day ?? '01',
    hour: rawHour,
    minute: lookup.minute ?? '00',
    weekdayIndex: weekdayMap[lookup.weekday ?? 'Mon'] ?? 0,
  };
}

export function formatTimestampInZone(isoString: string, timeZone = 'UTC'): string {
  const p = getZonedDateParts(isoString, timeZone);
  return `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute}`;
}

export function mapFacilityResponse(raw: FacilityResponse): MappedFacility {
  return {
    id: raw.id,
    code: raw.code,
    name: raw.name,
    location: raw.location,
    timezone: raw.timezone,
    currencyCode: raw.currency_code,
    contractedDemandKw: toNumber(raw.contracted_demand_kw),
    offPeakTariffRate: toNumber(raw.off_peak_tariff_rate),
    midPeakTariffRate: toNumber(raw.mid_peak_tariff_rate),
    peakTariffRate: toNumber(raw.peak_tariff_rate),
    isActive: raw.is_active,
    zoneCount: raw.zone_count,
    activeZoneCount: raw.active_zone_count,
    meterCount: raw.meter_count,
    activeMeterCount: raw.active_meter_count,
  };
}

export function filterReadingsBySourceScope(
  readings: TelemetryReadingResponse[],
  scope: DataSourceScope
): TelemetryReadingResponse[] {
  if (scope === 'all') return readings;
  if (scope === 'simulation') {
    return readings.filter(
      (r) => r.source === 'simulation' || r.quality_flag === 'simulated'
    );
  }
  return readings.filter(
    (r) => r.source !== 'simulation' && r.quality_flag !== 'simulated'
  );
}

export function mapMetersToAssets(
  meters: MeterResponse[],
  zones: ZoneResponse[],
  snapshots: MeterLiveSnapshotItem[] = []
): MappedMeter[] {
  const zoneById = new Map(zones.map((z) => [z.id, z]));
  const snapById = new Map(snapshots.map((s) => [s.meter_id, s]));
  return meters.map((m) => {
    const snap = snapById.get(m.id);
    const hasTelemetrySnap = snap !== undefined && snap.reading_count > 0;
    return {
      id: m.id,
      facilityId: m.facility_id,
      zoneId: m.zone_id,
      meterCode: m.meter_code,
      equipmentName: m.equipment_name,
      zone: zoneById.get(m.zone_id)?.name ?? m.zone_id,
      ratedKw: toNumber(m.rated_kw),
      nominalIntervalSeconds: m.nominal_interval_seconds,
      currentKw: hasTelemetrySnap ? snap.latest_kw : toNumber(m.current_kw),
      powerFactor: hasTelemetrySnap ? snap.latest_power_factor : toNumber(m.power_factor),
      thdPct: toNumber(m.thd_pct),
      lastCalibrated: m.last_calibrated_at,
      status: hasTelemetrySnap ? snap.derived_status : m.status,
      isActive: m.is_active,
    };
  });
}

export function mapSummaryZonesToSubMeters(
  summaryZones: ZoneAnalyticsSummaryItem[],
  zones: ZoneResponse[]
): MappedZone[] {
  const rawById = new Map(zones.map((z) => [z.id, z]));
  return summaryZones.map((sz) => {
    const raw = rawById.get(sz.zone_id);
    return {
      id: sz.zone_id,
      facilityId: raw?.facility_id ?? '',
      slug: sz.slug,
      name: sz.name,
      meterCode: sz.primary_meter_code,
      sharePct: sz.share_pct,
      kwhUsed: sz.kwh_used,
      peakKw: Math.round(sz.peak_kw),
      powerFactor: sz.power_factor,
      deltaVsBaselinePct: sz.delta_vs_baseline_pct,
      status: sz.derived_status,
      isActive: raw?.is_active ?? true,
      meterCount: raw?.meter_count ?? 0,
      activeMeterCount: raw?.active_meter_count ?? 0,
    };
  });
}

export function mapSummarySeriesToTelemetryPoints(
  series: AnalyticsSeriesBucketItem[],
  zones: ZoneResponse[],
  readings: TelemetryReadingResponse[],
  timeZone = 'UTC'
): TelemetryPoint[] {
  const zoneById = new Map(zones.map((z) => [z.id, z.name]));
  const readingByBucket = new Map<string, TelemetryReadingResponse>();
  for (const r of readings) {
    const formatted = formatTimestampInZone(r.recorded_at, timeZone);
    const existing = readingByBucket.get(formatted);
    if (!existing || toNumber(r.actual_kw) > toNumber(existing.actual_kw)) {
      readingByBucket.set(formatted, r);
    }
  }
  return series.map((item, idx) => {
    const matched = readingByBucket.get(item.timestamp);
    return {
      id: matched ? `reading-${matched.id}` : `bucket-${idx}-${item.timestamp}`,
      label: item.label,
      timestamp: item.timestamp,
      actualKw: item.actual_kw,
      baselineKw: item.baseline_kw,
      stdDevKw: item.std_dev_kw,
      powerFactor: item.power_factor,
      tariffPeriod: item.tariff_period,
      ambientTempC: item.ambient_temp_c,
      zScore: item.z_score,
      zone: zoneById.get(item.zone_id) ?? item.zone_id,
      hasBaseline: item.has_baseline,
    };
  });
}

export function mapZonesToSubMeters(
  zones: ZoneResponse[],
  readings: TelemetryReadingResponse[],
  meters: MeterResponse[]
): MappedZone[] {
  const readingsByZone = new Map<string, TelemetryReadingResponse[]>();
  for (const r of readings) {
    const existing = readingsByZone.get(r.zone_id);
    if (existing) {
      existing.push(r);
    } else {
      readingsByZone.set(r.zone_id, [r]);
    }
  }

  const metersByZone = new Map<string, MeterResponse[]>();
  for (const m of meters) {
    const existing = metersByZone.get(m.zone_id);
    if (existing) {
      existing.push(m);
    } else {
      metersByZone.set(m.zone_id, [m]);
    }
  }

  let totalKwhAcrossZones = 0;
  const rawZoneKwh = new Map<string, number>();
  for (const z of zones) {
    const zoneReadings = readingsByZone.get(z.id) ?? [];
    const kwh = zoneReadings.reduce((sum, r) => sum + toNumber(r.energy_kwh), 0);
    rawZoneKwh.set(z.id, kwh);
    totalKwhAcrossZones += kwh;
  }

  return zones.map((z) => {
    const zoneReadings = readingsByZone.get(z.id) ?? [];
    const zoneMeters = metersByZone.get(z.id) ?? [];
    const kwhUsed = Number((rawZoneKwh.get(z.id) ?? 0).toFixed(1));

    let peakKw = 0;
    if (zoneReadings.length > 0) {
      // Group by timestamp in case multiple meters exist in the zone
      const kwByTimestamp = new Map<string, number>();
      for (const r of zoneReadings) {
        kwByTimestamp.set(
          r.recorded_at,
          (kwByTimestamp.get(r.recorded_at) ?? 0) + toNumber(r.actual_kw)
        );
      }
      peakKw = Math.round(Math.max(...kwByTimestamp.values(), 0));
    } else if (zoneMeters.length > 0) {
      peakKw = Math.round(zoneMeters.reduce((sum, m) => sum + toNumber(m.current_kw), 0));
    }

    const powerFactor =
      zoneReadings.length > 0
        ? Number(
            (
              zoneReadings.reduce((sum, r) => sum + toNumber(r.power_factor), 0) /
              zoneReadings.length
            ).toFixed(2)
          )
        : zoneMeters.length > 0
          ? Number(
              (
                zoneMeters.reduce((sum, m) => sum + toNumber(m.power_factor), 0) /
                zoneMeters.length
              ).toFixed(2)
            )
          : 0;

    let deltaVsBaselinePct = 0;
    const baselinedReadings = zoneReadings.filter((r) => toNullableNumber(r.baseline_kw) !== null);
    if (baselinedReadings.length > 0) {
      const actualSum = baselinedReadings.reduce((sum, r) => sum + toNumber(r.actual_kw), 0);
      const baselineSum = baselinedReadings.reduce((sum, r) => sum + toNumber(r.baseline_kw), 0);
      if (baselineSum > 0) {
        deltaVsBaselinePct = Number((((actualSum - baselineSum) / baselineSum) * 100).toFixed(1));
      }
    }

    const sharePct =
      totalKwhAcrossZones > 0
        ? Number(((kwhUsed / totalKwhAcrossZones) * 100).toFixed(1))
        : toNumber(z.share_pct);

    return {
      id: z.id,
      facilityId: z.facility_id,
      slug: z.slug,
      name: z.name,
      meterCode: z.primary_meter_code,
      sharePct,
      kwhUsed,
      peakKw,
      powerFactor,
      deltaVsBaselinePct,
      status: z.status,
      isActive: z.is_active,
      meterCount: z.meter_count,
      activeMeterCount: z.active_meter_count,
    };
  });
}

export function getWindowDurationMs(timeWindow: TimeWindow): number {
  if (timeWindow === '24h') return 24 * 60 * 60 * 1000;
  if (timeWindow === '7d') return 7 * 24 * 60 * 60 * 1000;
  return 30 * 24 * 60 * 60 * 1000;
}

export function filterReadingsByTimeWindow(
  readings: TelemetryReadingResponse[],
  timeWindow: TimeWindow
): TelemetryReadingResponse[] {
  if (readings.length === 0) return [];
  let maxMs = -Infinity;
  for (const r of readings) {
    const ms = new Date(r.recorded_at).getTime();
    if (Number.isFinite(ms) && ms > maxMs) {
      maxMs = ms;
    }
  }
  if (!Number.isFinite(maxMs)) return readings;
  const cutoffMs = maxMs - getWindowDurationMs(timeWindow);
  return readings.filter((r) => {
    const ms = new Date(r.recorded_at).getTime();
    return Number.isFinite(ms) && ms >= cutoffMs;
  });
}

export function filterAnomaliesByTimeWindow(
  anomalies: MappedAnomaly[],
  readings: TelemetryReadingResponse[],
  timeWindow: TimeWindow
): MappedAnomaly[] {
  if (anomalies.length === 0) return [];
  let maxMs = -Infinity;
  for (const r of readings) {
    const ms = new Date(r.recorded_at).getTime();
    if (Number.isFinite(ms) && ms > maxMs) maxMs = ms;
  }
  for (const a of anomalies) {
    const ms = new Date(a.detectedAt).getTime();
    if (Number.isFinite(ms) && ms > maxMs) maxMs = ms;
  }
  if (!Number.isFinite(maxMs)) return anomalies;
  const cutoffMs = maxMs - getWindowDurationMs(timeWindow);
  return anomalies.filter((a) => {
    const ms = new Date(a.detectedAt).getTime();
    return Number.isFinite(ms) && ms >= cutoffMs;
  });
}

export function mapTelemetryReadingsToSeries(
  readings: TelemetryReadingResponse[],
  zones: ZoneResponse[],
  timeWindow: TimeWindow,
  timeZone = 'UTC'
): TelemetryPoint[] {
  if (readings.length === 0) return [];

  const zoneById = new Map(zones.map((z) => [z.id, z.name]));
  const sorted = [...readings].sort(
    (a, b) => new Date(a.recorded_at).getTime() - new Date(b.recorded_at).getTime()
  );

  const getBucketKey = (isoString: string): string => {
    const p = getZonedDateParts(isoString, timeZone);
    if (timeWindow === '24h') {
      return `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute}`;
    }
    if (timeWindow === '7d') {
      const hour6 = Math.floor(Number(p.hour) / 6) * 6;
      return `${p.year}-${p.month}-${p.day} ${String(hour6).padStart(2, '0')}:00`;
    }
    return `${p.year}-${p.month}-${p.day} 00:00`;
  };

  interface BucketGroup {
    key: string;
    firstIso: string;
    readings: TelemetryReadingResponse[];
  }

  const bucketMap = new Map<string, BucketGroup>();
  for (const reading of sorted) {
    const key = getBucketKey(reading.recorded_at);
    const existing = bucketMap.get(key);
    if (existing) {
      existing.readings.push(reading);
    } else {
      bucketMap.set(key, { key, firstIso: reading.recorded_at, readings: [reading] });
    }
  }

  const points: TelemetryPoint[] = [];
  for (const bucket of bucketMap.values()) {
    // Average per meter inside the bucket, then sum across meters so multi-meter concurrent demand adds up cleanly
    const byMeter = new Map<string, TelemetryReadingResponse[]>();
    for (const r of bucket.readings) {
      const list = byMeter.get(r.meter_id);
      if (list) list.push(r);
      else byMeter.set(r.meter_id, [r]);
    }

    let actualKw = 0;
    let baselineKw = 0;
    let stdDevSqSum = 0;
    let hasBaseline = false;

    for (const meterReadings of byMeter.values()) {
      const avgActual =
        meterReadings.reduce((sum, r) => sum + toNumber(r.actual_kw), 0) / meterReadings.length;
      actualKw += avgActual;

      const baselined = meterReadings.filter((r) => toNullableNumber(r.baseline_kw) !== null);
      if (baselined.length > 0) {
        hasBaseline = true;
        const avgBase =
          baselined.reduce((sum, r) => sum + toNumber(r.baseline_kw), 0) / baselined.length;
        baselineKw += avgBase;
        const avgStd =
          baselined.reduce((sum, r) => sum + toNumber(r.std_dev_kw), 0) / baselined.length;
        stdDevSqSum += avgStd * avgStd;
      } else {
        baselineKw += avgActual;
      }
    }

    const roundedActual = Number(actualKw.toFixed(1));
    const roundedBaseline = Number((hasBaseline ? baselineKw : actualKw).toFixed(1));
    const stdDevKw = Number(Math.sqrt(stdDevSqSum).toFixed(1));

    const maxReadingZScore = bucket.readings.reduce<number | null>((acc, r) => {
      const z = toNullableNumber(r.z_score);
      if (z === null) return acc;
      return acc === null ? z : Math.max(acc, z);
    }, null);

    const zScore =
      maxReadingZScore !== null
        ? Number(maxReadingZScore.toFixed(2))
        : stdDevKw > 0
          ? Number(((roundedActual - roundedBaseline) / stdDevKw).toFixed(2))
          : 0;

    const avgPf = Number(
      (
        bucket.readings.reduce((sum, r) => sum + toNumber(r.power_factor), 0) /
        bucket.readings.length
      ).toFixed(2)
    );

    const tempReadings = bucket.readings
      .map((r) => toNullableNumber(r.ambient_temp_c))
      .filter((v): v is number => v !== null);
    const ambientTempC =
      tempReadings.length > 0
        ? Number((tempReadings.reduce((a, b) => a + b, 0) / tempReadings.length).toFixed(1))
        : 0;

    const tariffPriority: Record<TariffPeriod, number> = {
      Peak: 3,
      'Mid-Peak': 2,
      'Off-Peak': 1,
    };
    const tariffPeriod = bucket.readings.reduce<TariffPeriod>(
      (best, r) =>
        tariffPriority[r.tariff_period] > tariffPriority[best] ? r.tariff_period : best,
      bucket.readings[0].tariff_period
    );

    const highestReading = bucket.readings.reduce((best, r) =>
      toNumber(r.actual_kw) > toNumber(best.actual_kw) ? r : best
    );

    const parts = getZonedDateParts(bucket.firstIso, timeZone);
    const label =
      timeWindow === '24h'
        ? `${parts.hour}:${parts.minute}`
        : timeWindow === '7d'
          ? `${parts.month}/${parts.day} ${parts.hour}h`
          : `${parts.month}/${parts.day}`;

    points.push({
      id: `reading-${highestReading.id}`,
      label,
      timestamp: bucket.key,
      actualKw: roundedActual,
      baselineKw: roundedBaseline,
      stdDevKw,
      powerFactor: avgPf,
      tariffPeriod,
      ambientTempC,
      zScore,
      zone: zoneById.get(highestReading.zone_id) ?? highestReading.zone_id,
      hasBaseline,
    });
  }

  return points;
}

export function buildHeatmapMatrixFromReadings(
  readings: TelemetryReadingResponse[],
  timeZone = 'UTC'
): number[][] {
  // 7 days (Mon..Sun) x 24 hours
  const matrix = Array.from({ length: 7 }, () => Array.from({ length: 24 }, () => 0));
  if (readings.length === 0) return matrix;

  // Step 1: Group by exact calendar day + hour + meter to average sub-hourly intervals per meter
  // Step 2: Sum concurrent meters per calendar day + hour
  // Step 3: Average across multiple weeks matching the same weekday + hour
  const dayHourMeterMap = new Map<string, { weekday: number; hour: number; dateKey: string; meterValues: Map<string, number[]> }>();

  for (const r of readings) {
    const parts = getZonedDateParts(r.recorded_at, timeZone);
    const hour = Number(parts.hour);
    const dateKey = `${parts.year}-${parts.month}-${parts.day}-${hour}`;
    let slot = dayHourMeterMap.get(dateKey);
    if (!slot) {
      slot = {
        weekday: parts.weekdayIndex,
        hour,
        dateKey,
        meterValues: new Map(),
      };
      dayHourMeterMap.set(dateKey, slot);
    }
    const list = slot.meterValues.get(r.meter_id);
    const kw = toNumber(r.actual_kw);
    if (list) list.push(kw);
    else slot.meterValues.set(r.meter_id, [kw]);
  }

  const weekdayHourTotals: number[][][] = Array.from({ length: 7 }, () =>
    Array.from({ length: 24 }, () => [])
  );

  for (const slot of dayHourMeterMap.values()) {
    let slotTotalKw = 0;
    for (const values of slot.meterValues.values()) {
      slotTotalKw += values.reduce((a, b) => a + b, 0) / values.length;
    }
    weekdayHourTotals[slot.weekday][slot.hour].push(slotTotalKw);
  }

  for (let d = 0; d < 7; d += 1) {
    for (let h = 0; h < 24; h += 1) {
      const samples = weekdayHourTotals[d][h];
      if (samples.length > 0) {
        const avg = samples.reduce((a, b) => a + b, 0) / samples.length;
        matrix[d][h] = Math.round(avg);
      }
    }
  }

  return matrix;
}

export function mapAnomalyResponse(
  raw: AnomalyResponse | AnomalyDetailResponse,
  zones: ZoneResponse[],
  meters: MeterResponse[],
  timeZone = 'UTC',
  readings?: TelemetryReadingResponse[]
): MappedAnomaly {
  const zoneMap = new Map(zones.map((z) => [z.id, z]));
  const meterMap = new Map(meters.map((m) => [m.id, m]));
  const detail = raw as Partial<AnomalyDetailResponse>;
  const matchedReading =
    raw.reading_id !== null && readings
      ? readings.find((r) => r.id === raw.reading_id)
      : undefined;

  return {
    id: raw.id,
    eventCode: raw.event_code,
    facilityId: raw.facility_id,
    zoneId: raw.zone_id,
    meterId: raw.meter_id,
    readingId: raw.reading_id,
    pointId: matchedReading ? `reading-${matchedReading.id}` : null,
    detectedAt: raw.detected_at,
    timestamp: formatTimestampInZone(raw.detected_at, timeZone),
    meterCode: meterMap.get(raw.meter_id)?.meter_code ?? raw.meter_id,
    zone: zoneMap.get(raw.zone_id)?.name ?? raw.zone_id,
    severity: raw.severity,
    status: raw.status,
    zScore: toNumber(raw.z_score),
    actualKw: toNumber(raw.actual_kw),
    expectedKw: toNumber(raw.expected_kw),
    deviationPct: toNumber(raw.deviation_pct),
    durationMin: raw.duration_min,
    estimatedWasteKwh: toNumber(raw.estimated_waste_kwh),
    estimatedCost: toNullableNumber(raw.estimated_cost),
    costEstimateStatus: raw.cost_estimate_status,
    signature: raw.signature,
    recommendation: raw.recommendation,
    assignedToUserId: raw.assigned_to_user_id,
    waveform: Array.isArray(detail.waveform) ? detail.waveform : [],
    baselineWaveform: Array.isArray(detail.baseline_waveform) ? detail.baseline_waveform : [],
  };
}

export function mapInsightResponse(
  raw: InsightResponse | InsightDetailResponse,
  zones: ZoneResponse[],
  meters: MeterResponse[]
): MappedInsight {
  const zoneMap = new Map(zones.map((z) => [z.id, z]));
  const meterMap = new Map(meters.map((m) => [m.id, m]));
  const detail = raw as Partial<InsightDetailResponse>;

  return {
    id: raw.id,
    facilityId: raw.facility_id,
    zoneId: raw.zone_id,
    meterId: raw.meter_id,
    meterCode: raw.meter_id ? (meterMap.get(raw.meter_id)?.meter_code ?? null) : null,
    ruleCode: raw.rule_code,
    dedupeKey: raw.dedupe_key,
    title: raw.title,
    category: raw.category,
    zone: zoneMap.get(raw.zone_id)?.name ?? raw.zone_id,
    summary: raw.summary,
    monthlyKwhSavings: toNumber(raw.monthly_kwh_savings),
    annualCostSavings: toNullableNumber(raw.annual_cost_savings),
    paybackMonths: toNullableNumber(raw.payback_months),
    costEstimateStatus: raw.cost_estimate_status,
    savingsBasis: raw.savings_basis,
    priority: raw.priority,
    status: raw.status,
    updatedAt: raw.updated_at,
    evidence: detail.evidence ?? null,
  };
}

export function getLiveScopedDemandCeilingKw(
  facility: MappedFacility,
  meters: MappedMeter[],
  selectedZoneId: string | null
): number {
  if (!selectedZoneId) {
    return facility.contractedDemandKw;
  }
  const zoneMeters = meters.filter((m) => m.zoneId === selectedZoneId && m.isActive);
  if (zoneMeters.length > 0) {
    return Math.round(zoneMeters.reduce((sum, m) => sum + m.ratedKw, 0));
  }
  const allZoneMeters = meters.filter((m) => m.zoneId === selectedZoneId);
  if (allZoneMeters.length > 0) {
    return Math.round(allZoneMeters.reduce((sum, m) => sum + m.ratedKw, 0));
  }
  return facility.contractedDemandKw;
}

export function calculateLiveDashboardKpis(params: {
  facility: MappedFacility;
  readings: TelemetryReadingResponse[];
  series: TelemetryPoint[];
  anomalies: MappedAnomaly[];
  insights: MappedInsight[];
  meters: MappedMeter[];
  selectedZoneId: string | null;
}): LiveDashboardKpis {
  const { facility, readings, series, anomalies, insights, meters, selectedZoneId } = params;

  const totalKwh = readings.reduce((sum, r) => sum + toNumber(r.energy_kwh), 0);
  const totalMwh = totalKwh / 1000;
  const avgDemandKw =
    series.length > 0
      ? Number((series.reduce((sum, p) => sum + p.actualKw, 0) / series.length).toFixed(1))
      : 0;

  const peakDemandKw =
    series.length > 0
      ? Math.round(Math.max(...series.map((p) => p.actualKw), 0))
      : 0;

  const demandCeilingKw = getLiveScopedDemandCeilingKw(facility, meters, selectedZoneId);
  const demandHeadroomPct =
    demandCeilingKw > 0 ? Math.round((peakDemandKw / demandCeilingKw) * 100) : 0;

  const avgPf =
    readings.length > 0
      ? readings.reduce((sum, r) => sum + toNumber(r.power_factor), 0) / readings.length
      : 0;

  const openAnomalies = anomalies.filter((a) => a.status !== 'Resolved');
  const criticalCount = openAnomalies.filter((a) => a.severity === 'Critical').length;

  const scopedInsights = selectedZoneId
    ? insights.filter((ins) => ins.zoneId === selectedZoneId)
    : insights;

  let potentialSavingsAmount = 0;
  let hasQuantifiedSavings = false;
  let unquantifiedInsightsCount = 0;

  for (const ins of scopedInsights) {
    if (ins.annualCostSavings !== null) {
      potentialSavingsAmount += ins.annualCostSavings;
      hasQuantifiedSavings = true;
    } else {
      unquantifiedInsightsCount += 1;
    }
  }

  return {
    totalMwh,
    avgDemandKw,
    consumptionTrendPct: null,
    peakDemandKw,
    demandCeilingKw,
    demandHeadroomPct,
    avgPf,
    openAnomaliesCount: openAnomalies.length,
    criticalCount,
    potentialSavingsAmount,
    hasQuantifiedSavings,
    unquantifiedInsightsCount,
  };
}

function escapeCsvCell(value: string | number | null): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'number') {
    return Number.isFinite(value) ? String(value) : '';
  }
  const safe = /^[=+\-@]/.test(value) ? `'${value}` : value;
  if (/[",\n\r]/.test(safe)) {
    return `"${safe.replace(/"/g, '""')}"`;
  }
  return `"${safe}"`;
}

export function buildBackendCsvExportRows(params: {
  readings: TelemetryReadingResponse[];
  facility: MappedFacility;
  zones: ZoneResponse[];
  meters: MeterResponse[];
  anomalies: MappedAnomaly[];
}): BackendCsvExportRow[] {
  const { readings, facility, zones, meters, anomalies } = params;
  const zoneMap = new Map(zones.map((z) => [z.id, z]));
  const meterMap = new Map(meters.map((m) => [m.id, m]));
  const anomalyReadingIds = new Set(
    anomalies.map((a) => a.readingId).filter((id): id is number => id !== null)
  );

  const sorted = [...readings].sort(
    (a, b) => new Date(a.recorded_at).getTime() - new Date(b.recorded_at).getTime()
  );

  return sorted.map((r) => {
    const meter = meterMap.get(r.meter_id);
    const zone = zoneMap.get(r.zone_id);
    const consumptionKwh = Number(toNumber(r.energy_kwh).toFixed(4));
    const consumptionMwh = Number((consumptionKwh / 1000).toFixed(6));

    return {
      facilityName: facility.name,
      facilityCode: facility.code,
      timestamp: formatTimestampInZone(r.recorded_at, facility.timezone),
      zone: zone?.name ?? r.zone_id,
      meterCode: meter?.meter_code ?? r.meter_id,
      equipmentName: meter?.equipment_name ?? zone?.name ?? r.meter_id,
      intervalHours: Number((r.interval_seconds / 3600).toFixed(4)),
      actualKw: toNumber(r.actual_kw),
      baselineKw: toNullableNumber(r.baseline_kw),
      consumptionKwh,
      consumptionMwh,
      powerFactor: toNumber(r.power_factor),
      tariffPeriod: r.tariff_period,
      zScore: toNullableNumber(r.z_score),
      qualityFlag: r.quality_flag,
      source: r.source,
      anomalyFlag: anomalyReadingIds.has(r.id) ? 'ANOMALY' : 'NORMAL',
    };
  });
}

export function serializeBackendCsv(
  rows: BackendCsvExportRow[],
  unitMode: EnergyUnitMode = 'both'
): string {
  const unitHeaders =
    unitMode === 'both'
      ? ['Consumption_kWh', 'Consumption_MWh']
      : unitMode === 'kwh'
        ? ['Consumption_kWh']
        : ['Consumption_MWh'];

  const headers = [
    'Facility',
    'Facility_Code',
    'Timestamp',
    'Zone',
    'Meter_Code',
    'Equipment',
    'Interval_Hours',
    'Actual_Demand_kW',
    'Baseline_Demand_kW',
    ...unitHeaders,
    'Power_Factor',
    'Tariff_Period',
    'Z_Score',
    'Quality_Flag',
    'Source',
    'Anomaly_Flag',
  ];

  const lines = rows.map((row) => {
    const unitValues =
      unitMode === 'both'
        ? [row.consumptionKwh, row.consumptionMwh]
        : unitMode === 'kwh'
          ? [row.consumptionKwh]
          : [row.consumptionMwh];

    return [
      escapeCsvCell(row.facilityName),
      escapeCsvCell(row.facilityCode),
      escapeCsvCell(row.timestamp),
      escapeCsvCell(row.zone),
      escapeCsvCell(row.meterCode),
      escapeCsvCell(row.equipmentName),
      row.intervalHours,
      row.actualKw,
      row.baselineKw ?? '',
      ...unitValues,
      row.powerFactor,
      row.tariffPeriod,
      row.zScore ?? '',
      row.qualityFlag,
      row.source,
      row.anomalyFlag,
    ].join(',');
  });

  return [headers.join(','), ...lines].join('\n');
}
