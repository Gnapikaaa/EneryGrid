import type {
  EnergyUnitMode,
  SubMeterZone,
  TelemetryPoint,
  TimeWindow,
} from '../types/energy';

export type { EnergyUnitMode, SubMeterZone, TelemetryPoint, TimeWindow };

export type FacilityId = 'north-assembly' | 'foundry-press' | 'cold-storage';
export type AnomalyStatus = 'Open' | 'Acknowledged' | 'Assigned' | 'Resolved';
export type AnomalySeverity = 'Critical' | 'High' | 'Elevated';
export type InsightStatus = 'Recommended' | 'In Progress' | 'Implemented';

export interface AnomalyRecord {
  id: string;
  pointId: string;
  timestamp: string;
  meterCode: string;
  zone: string;
  severity: AnomalySeverity;
  zScore: number;
  actualKw: number;
  expectedKw: number;
  deviationPct: number;
  durationMin: number;
  estimatedWasteKwh: number;
  estimatedCostUsd: number;
  signature: string;
  recommendation: string;
  status: AnomalyStatus;
  waveform: number[];
  baselineWaveform: number[];
}

export interface ActionableInsight {
  id: string;
  title: string;
  category: 'Load Shifting' | 'Power Quality' | 'HVAC & Thermal' | 'Compressed Air';
  zone: string;
  summary: string;
  monthlyKwhSavings: number;
  annualUsdSavings: number;
  paybackMonths: number;
  priority: 'High' | 'Medium';
  status: InsightStatus;
}

export interface MeterAsset {
  id: string;
  meterCode: string;
  equipmentName: string;
  zone: string;
  ratedKw: number;
  currentKw: number;
  powerFactor: number;
  thdPct: number;
  lastCalibrated: string;
  status: 'Nominal' | 'Warning' | 'Fault';
}

export interface FacilityProfile {
  id: FacilityId;
  name: string;
  code: string;
  location: string;
  contractedDemandKw: number;
  tariffRateUsd: number;
  peakTariffRateUsd: number;
  zones: SubMeterZone[];
  meters: MeterAsset[];
  insights: ActionableInsight[];
  heatmapMatrix: number[][]; // 7 days x 24 hours (kW)
}

function deterministicNoise(seed: number): number {
  const x = Math.sin(seed * 12.9898 + 78.233) * 43758.5453;
  return x - Math.floor(x);
}

export const FACILITIES: Record<FacilityId, FacilityProfile> = {
  'north-assembly': {
    id: 'north-assembly',
    name: 'North Assembly Plant',
    code: 'PLT-NA01',
    location: 'Detroit Sector B',
    contractedDemandKw: 1850,
    tariffRateUsd: 0.118,
    peakTariffRateUsd: 0.214,
    zones: [
      {
        id: 'cnc',
        name: 'CNC Machining Line 1–4',
        meterCode: 'MTR-104',
        kwhUsed: 14280,
        sharePct: 38.4,
        peakKw: 742,
        powerFactor: 0.94,
        deltaVsBaselinePct: 2.1,
        status: 'Nominal',
      },
      {
        id: 'air',
        name: 'Compressed Air Header',
        meterCode: 'MTR-208',
        kwhUsed: 8640,
        sharePct: 23.2,
        peakKw: 495,
        powerFactor: 0.84,
        deltaVsBaselinePct: 18.6,
        status: 'Fault',
      },
      {
        id: 'hvac',
        name: 'Chiller & Cleanroom HVAC',
        meterCode: 'MTR-312',
        kwhUsed: 7910,
        sharePct: 21.3,
        peakKw: 390,
        powerFactor: 0.91,
        deltaVsBaselinePct: 7.4,
        status: 'Warning',
      },
      {
        id: 'paint',
        name: 'Curing Ovens & Exhaust',
        meterCode: 'MTR-401',
        kwhUsed: 4120,
        sharePct: 11.1,
        peakKw: 265,
        powerFactor: 0.96,
        deltaVsBaselinePct: -1.8,
        status: 'Nominal',
      },
      {
        id: 'aux',
        name: 'Bay Lighting & Auxiliaries',
        meterCode: 'MTR-509',
        kwhUsed: 2230,
        sharePct: 6.0,
        peakKw: 118,
        powerFactor: 0.98,
        deltaVsBaselinePct: -3.2,
        status: 'Nominal',
      },
    ],
    meters: [
      {
        id: 'm1',
        meterCode: 'MTR-104',
        equipmentName: '5-Axis CNC Bank A',
        zone: 'CNC Machining Line 1–4',
        ratedKw: 800,
        currentKw: 618,
        powerFactor: 0.94,
        thdPct: 3.1,
        lastCalibrated: '2026-09-14',
        status: 'Nominal',
      },
      {
        id: 'm2',
        meterCode: 'MTR-208',
        equipmentName: 'Rotary Screw Compressor #2',
        zone: 'Compressed Air Header',
        ratedKw: 450,
        currentKw: 438,
        powerFactor: 0.84,
        thdPct: 6.8,
        lastCalibrated: '2026-08-02',
        status: 'Fault',
      },
      {
        id: 'm3',
        meterCode: 'MTR-312',
        equipmentName: 'Centrifugal Chiller Loop B',
        zone: 'Chiller & Cleanroom HVAC',
        ratedKw: 420,
        currentKw: 342,
        powerFactor: 0.91,
        thdPct: 4.2,
        lastCalibrated: '2026-10-05',
        status: 'Warning',
      },
      {
        id: 'm4',
        meterCode: 'MTR-401',
        equipmentName: 'IR Curing Tunnel #1',
        zone: 'Curing Ovens & Exhaust',
        ratedKw: 320,
        currentKw: 214,
        powerFactor: 0.96,
        thdPct: 2.4,
        lastCalibrated: '2026-10-19',
        status: 'Nominal',
      },
      {
        id: 'm5',
        meterCode: 'MTR-509',
        equipmentName: 'High-Bay LED Busbar',
        zone: 'Bay Lighting & Auxiliaries',
        ratedKw: 150,
        currentKw: 92,
        powerFactor: 0.98,
        thdPct: 1.9,
        lastCalibrated: '2026-11-01',
        status: 'Nominal',
      },
      {
        id: 'm6',
        meterCode: 'MTR-211',
        equipmentName: 'Air Dryer & Receiver Bank',
        zone: 'Compressed Air Header',
        ratedKw: 160,
        currentKw: 141,
        powerFactor: 0.87,
        thdPct: 5.4,
        lastCalibrated: '2026-07-22',
        status: 'Warning',
      },
    ],
    insights: [
      {
        id: 'ins-1',
        title: 'Eliminate off-shift compressor short-cycling on Header #2',
        category: 'Compressed Air',
        zone: 'Compressed Air Header',
        summary:
          'MTR-208 draws 260 kW in 18-minute bursts between 00:00 and 04:30 despite zero line pressure demand, indicating a leaking solenoid valve on Bay 4.',
        monthlyKwhSavings: 19400,
        annualUsdSavings: 27470,
        paybackMonths: 1.5,
        priority: 'High',
        status: 'Recommended',
      },
      {
        id: 'ins-2',
        title: 'Stagger CNC warm-up & compressor purge out of 14:00–18:00 peak window',
        category: 'Load Shifting',
        zone: 'CNC Machining Line 1–4',
        summary:
          'Shifting scheduled spindle warm-up and regenerative dryer purges by 90 minutes avoids exceeding the 1,850 kW demand ratchet tier.',
        monthlyKwhSavings: 8200,
        annualUsdSavings: 21050,
        paybackMonths: 0.5,
        priority: 'High',
        status: 'In Progress',
      },
      {
        id: 'ins-3',
        title: 'Engage Capacitor Bank Stage 3 on Compressed Air feeder',
        category: 'Power Quality',
        zone: 'Compressed Air Header',
        summary:
          'Power factor drops to 0.84 during heavy pneumatic press cycles, incurring utility reactive penalty charges above 0.90 threshold.',
        monthlyKwhSavings: 3100,
        annualUsdSavings: 9840,
        paybackMonths: 3.0,
        priority: 'Medium',
        status: 'Recommended',
      },
      {
        id: 'ins-4',
        title: 'Clean Chiller B condenser tubes & raise night setpoint +2.5°C',
        category: 'HVAC & Thermal',
        zone: 'Chiller & Cleanroom HVAC',
        summary:
          'Approach temperature drift of +3.1°C increased Chiller Loop B specific power from 0.64 to 0.75 kW/ton over the last 14 days.',
        monthlyKwhSavings: 6850,
        annualUsdSavings: 9700,
        paybackMonths: 2.0,
        priority: 'Medium',
        status: 'Recommended',
      },
    ],
    heatmapMatrix: buildHeatmapMatrix(1, 1480),
  },
  'foundry-press': {
    id: 'foundry-press',
    name: 'Foundry & Press Hall',
    code: 'PLT-FP02',
    location: 'Toledo Heavy Wing',
    contractedDemandKw: 2600,
    tariffRateUsd: 0.112,
    peakTariffRateUsd: 0.205,
    zones: [
      {
        id: 'furnace',
        name: 'Induction Melting Furnaces',
        meterCode: 'MTR-601',
        kwhUsed: 24900,
        sharePct: 49.2,
        peakKw: 1380,
        powerFactor: 0.93,
        deltaVsBaselinePct: 4.5,
        status: 'Nominal',
      },
      {
        id: 'stamping',
        name: 'Hydraulic Stamping Presses',
        meterCode: 'MTR-604',
        kwhUsed: 12150,
        sharePct: 24.0,
        peakKw: 690,
        powerFactor: 0.85,
        deltaVsBaselinePct: 14.2,
        status: 'Warning',
      },
      {
        id: 'extraction',
        name: 'Baghouse & Fume Extraction',
        meterCode: 'MTR-612',
        kwhUsed: 8420,
        sharePct: 16.6,
        peakKw: 380,
        powerFactor: 0.90,
        deltaVsBaselinePct: 2.8,
        status: 'Nominal',
      },
      {
        id: 'cooling',
        name: 'Quench Cooling Towers',
        meterCode: 'MTR-619',
        kwhUsed: 5140,
        sharePct: 10.2,
        peakKw: 240,
        powerFactor: 0.95,
        deltaVsBaselinePct: -2.4,
        status: 'Nominal',
      },
    ],
    meters: [
      {
        id: 'fm1',
        meterCode: 'MTR-601',
        equipmentName: 'Coreless Induction Furnace #1',
        zone: 'Induction Melting Furnaces',
        ratedKw: 1500,
        currentKw: 1240,
        powerFactor: 0.93,
        thdPct: 4.9,
        lastCalibrated: '2026-10-11',
        status: 'Nominal',
      },
      {
        id: 'fm2',
        meterCode: 'MTR-604',
        equipmentName: '1,200T Hydraulic Press B',
        zone: 'Hydraulic Stamping Presses',
        ratedKw: 750,
        currentKw: 672,
        powerFactor: 0.85,
        thdPct: 6.1,
        lastCalibrated: '2026-08-29',
        status: 'Warning',
      },
      {
        id: 'fm3',
        meterCode: 'MTR-612',
        equipmentName: 'Main Baghouse VFD Fan',
        zone: 'Baghouse & Fume Extraction',
        ratedKw: 420,
        currentKw: 348,
        powerFactor: 0.90,
        thdPct: 3.4,
        lastCalibrated: '2026-09-30',
        status: 'Nominal',
      },
      {
        id: 'fm4',
        meterCode: 'MTR-619',
        equipmentName: 'Quench Loop Pump Bank',
        zone: 'Quench Cooling Towers',
        ratedKw: 280,
        currentKw: 204,
        powerFactor: 0.95,
        thdPct: 2.2,
        lastCalibrated: '2026-10-24',
        status: 'Nominal',
      },
    ],
    insights: [
      {
        id: 'fins-1',
        title: 'Reschedule Melt Batch #3 charge start to 21:00 off-peak window',
        category: 'Load Shifting',
        zone: 'Induction Melting Furnaces',
        summary:
          'Starting the third daily induction melt 2 hours later removes 620 kW from peak tariff overlap without reducing shift tonnage.',
        monthlyKwhSavings: 11800,
        annualUsdSavings: 34200,
        paybackMonths: 0.5,
        priority: 'High',
        status: 'Recommended',
      },
      {
        id: 'fins-2',
        title: 'Install VFD idle ramp-down on Hydraulic Press B pump',
        category: 'Power Quality',
        zone: 'Hydraulic Stamping Presses',
        summary:
          'Press pump motor runs at full synchronous RPM during 22-minute die-change intervals, wasting 190 kW continuously.',
        monthlyKwhSavings: 14200,
        annualUsdSavings: 19080,
        paybackMonths: 4.5,
        priority: 'High',
        status: 'Recommended',
      },
    ],
    heatmapMatrix: buildHeatmapMatrix(2, 2240),
  },
  'cold-storage': {
    id: 'cold-storage',
    name: 'Cold Storage & HVAC',
    code: 'PLT-CS03',
    location: 'Columbus Hub',
    contractedDemandKw: 1100,
    tariffRateUsd: 0.109,
    peakTariffRateUsd: 0.196,
    zones: [
      {
        id: 'ammonia',
        name: 'Ammonia Rack Compressors',
        meterCode: 'MTR-801',
        kwhUsed: 11400,
        sharePct: 54.8,
        peakKw: 540,
        powerFactor: 0.92,
        deltaVsBaselinePct: 9.8,
        status: 'Warning',
      },
      {
        id: 'evap',
        name: 'Blast Freezer Evaporators',
        meterCode: 'MTR-805',
        kwhUsed: 5620,
        sharePct: 27.0,
        peakKw: 275,
        powerFactor: 0.95,
        deltaVsBaselinePct: 1.9,
        status: 'Nominal',
      },
      {
        id: 'dock',
        name: 'Dock Seals & Rapid Doors',
        meterCode: 'MTR-810',
        kwhUsed: 2380,
        sharePct: 11.4,
        peakKw: 132,
        powerFactor: 0.94,
        deltaVsBaselinePct: 15.1,
        status: 'Fault',
      },
      {
        id: 'charge',
        name: 'Forklift Charging Bay',
        meterCode: 'MTR-814',
        kwhUsed: 1410,
        sharePct: 6.8,
        peakKw: 98,
        powerFactor: 0.97,
        deltaVsBaselinePct: -4.1,
        status: 'Nominal',
      },
    ],
    meters: [
      {
        id: 'cm1',
        meterCode: 'MTR-801',
        equipmentName: 'Ammonia Screw Rack A',
        zone: 'Ammonia Rack Compressors',
        ratedKw: 600,
        currentKw: 486,
        powerFactor: 0.92,
        thdPct: 3.3,
        lastCalibrated: '2026-09-18',
        status: 'Warning',
      },
      {
        id: 'cm2',
        meterCode: 'MTR-805',
        equipmentName: 'Blast Tunnel Evaporator Bank',
        zone: 'Blast Freezer Evaporators',
        ratedKw: 320,
        currentKw: 244,
        powerFactor: 0.95,
        thdPct: 2.1,
        lastCalibrated: '2026-10-08',
        status: 'Nominal',
      },
      {
        id: 'cm3',
        meterCode: 'MTR-810',
        equipmentName: 'Bay 1–6 Air Curtain & Door Heater',
        zone: 'Dock Seals & Rapid Doors',
        ratedKw: 150,
        currentKw: 138,
        powerFactor: 0.94,
        thdPct: 2.6,
        lastCalibrated: '2026-06-19',
        status: 'Fault',
      },
    ],
    insights: [
      {
        id: 'cins-1',
        title: 'Repair Dock Door #3 limit switch & thermal strip seal',
        category: 'HVAC & Thermal',
        zone: 'Dock Seals & Rapid Doors',
        summary:
          'Frequent warm-air infiltration between 13:00 and 16:00 drives an extra 88 kW compressor load on Rack A.',
        monthlyKwhSavings: 9400,
        annualUsdSavings: 14820,
        paybackMonths: 1.0,
        priority: 'High',
        status: 'Recommended',
      },
      {
        id: 'cins-2',
        title: 'Pre-cool Freezer Vaults to -22°C before 13:00 peak tariff',
        category: 'Load Shifting',
        zone: 'Ammonia Rack Compressors',
        summary:
          'Thermal flywheel pre-cooling allows floating vault temperature +2°C during peak utility hours with zero product risk.',
        monthlyKwhSavings: 5200,
        annualUsdSavings: 11640,
        paybackMonths: 0.5,
        priority: 'Medium',
        status: 'Implemented',
      },
    ],
    heatmapMatrix: buildHeatmapMatrix(3, 860),
  },
};

function buildHeatmapMatrix(seedOffset: number, peakBaseKw: number): number[][] {
  // 7 days (Mon..Sun) x 24 hours
  const matrix: number[][] = [];
  for (let d = 0; d < 7; d++) {
    const row: number[] = [];
    const isWeekend = d >= 5;
    for (let h = 0; h < 24; h++) {
      let loadFactor = 0.34;
      if (!isWeekend) {
        if (h >= 6 && h <= 17) {
          loadFactor = 0.78 + 0.14 * Math.sin(((h - 6) / 11) * Math.PI);
        } else if (h >= 18 && h <= 21) {
          loadFactor = 0.56;
        }
      } else {
        loadFactor = h >= 8 && h <= 16 ? 0.42 : 0.31;
      }

      // Inject realistic off-shift baseload anomaly on Wednesday & Thursday 02:00-04:00
      if ((d === 2 || d === 3) && h >= 1 && h <= 3) {
        loadFactor += 0.24;
      }

      const jitter = (deterministicNoise(seedOffset * 100 + d * 24 + h) - 0.5) * 0.08;
      row.push(Math.round(peakBaseKw * Math.max(0.22, loadFactor + jitter)));
    }
    matrix.push(row);
  }
  return matrix;
}

export function getAnomalyStatusKey(
  facilityId: FacilityId,
  window: TimeWindow,
  anomalyId: string
): string {
  return `${facilityId}:${window}:${anomalyId}`;
}

export function getScopedDemandCeilingKw(
  facility: FacilityProfile,
  zoneId: string | null
): number {
  if (!zoneId) return facility.contractedDemandKw;
  const zone = facility.zones.find((z) => z.id === zoneId);
  if (!zone) return facility.contractedDemandKw;
  const zoneMeters = facility.meters.filter((m) => m.zone === zone.name);
  if (zoneMeters.length > 0) {
    return zoneMeters.reduce((sum, m) => sum + m.ratedKw, 0);
  }
  return Math.round(zone.peakKw * 1.15);
}

export function getScopedHeatmapMatrix(
  facility: FacilityProfile,
  zoneId: string | null
): number[][] {
  if (!zoneId) return facility.heatmapMatrix;
  const zone = facility.zones.find((z) => z.id === zoneId);
  if (!zone) return facility.heatmapMatrix;

  const share = zone.sharePct / 100;
  const isNominal = zone.status === 'Nominal';

  return facility.heatmapMatrix.map((row, dayIdx) =>
    row.map((kw, hourIdx) => {
      let scaled = kw * share;
      // Nominal zones do not carry the facility's off-shift compressor/dock drift spike
      if (isNominal && (dayIdx === 2 || dayIdx === 3) && hourIdx >= 1 && hourIdx <= 3) {
        scaled *= 0.68;
      } else if (zone.status === 'Fault' && (dayIdx === 2 || dayIdx === 3) && hourIdx >= 1 && hourIdx <= 3) {
        scaled *= 1.18;
      }
      return Math.max(8, Math.round(scaled));
    })
  );
}

export function generateTelemetrySeries(
  facilityId: FacilityId,
  window: TimeWindow,
  injectedSpikeKw = 0,
  zoneId: string | null = null
): TelemetryPoint[] {
  const facility = FACILITIES[facilityId];
  const selectedZone = zoneId ? facility.zones.find((z) => z.id === zoneId) ?? null : null;
  const zoneScale = selectedZone ? selectedZone.sharePct / 100 : 1.0;
  const baseScale =
    facilityId === 'north-assembly' ? 1.0 : facilityId === 'foundry-press' ? 1.44 : 0.62;

  const count = window === '24h' ? 24 : window === '7d' ? 28 : 30;
  const points: TelemetryPoint[] = [];

  for (let i = 0; i < count; i++) {
    const hourOfDay = window === '24h' ? i : (i * 6) % 24;
    const isPeak = hourOfDay >= 14 && hourOfDay <= 18;
    const isMid = (hourOfDay >= 7 && hourOfDay < 14) || (hourOfDay > 18 && hourOfDay <= 21);
    const tariffPeriod: TelemetryPoint['tariffPeriod'] = isPeak
      ? 'Peak'
      : isMid
        ? 'Mid-Peak'
        : 'Off-Peak';

    const baselineCurve =
      480 +
      620 * Math.max(0, Math.sin(((hourOfDay - 5) / 14) * Math.PI)) +
      (isPeak ? 120 : 0);
    const baselineKw = Math.max(12, Math.round(baselineCurve * baseScale * zoneScale));
    const stdDevKw = Math.max(2, Math.round(baselineKw * 0.065));
    const noise = (deterministicNoise(i * 17 + baseScale * 100) - 0.5) * 2 * stdDevKw * 0.85;

    let anomalyBoost = 0;
    let eventZone = facility.zones[0].name;
    let probableCause: string | undefined;

    if (window === '24h') {
      if (i === 2 || i === 3) {
        anomalyBoost = Math.round(295 * baseScale);
        eventZone = facility.zones[1]?.name ?? facility.zones[0].name;
        probableCause = 'Off-shift compressor header short-cycling';
      } else if (i === 15) {
        anomalyBoost = Math.round(375 * baseScale);
        eventZone = facility.zones[2]?.name ?? facility.zones[0].name;
        probableCause = 'Peak tariff demand surge + chiller condenser fouling';
      } else if (i === 20) {
        anomalyBoost = Math.round(215 * baseScale);
        eventZone = facility.zones[1]?.name ?? facility.zones[0].name;
        probableCause = 'Reactive power draw spike (PF 0.84)';
      }
    } else if (i === 9 || i === 18 || i === 24) {
      anomalyBoost = Math.round((270 + (i % 5) * 35) * baseScale);
      eventZone = facility.zones[i % facility.zones.length].name;
      probableCause =
        i === 9
          ? 'Unscheduled weekend baseload drift'
          : i === 18
            ? 'Peak demand ratchet overshoot'
            : 'Harmonic distortion & phase imbalance';
    }

    // If scoped to a specific zone, only retain interval excursions belonging to that zone
    if (selectedZone && anomalyBoost > 0 && eventZone !== selectedZone.name) {
      anomalyBoost = 0;
      probableCause = undefined;
    }

    if (injectedSpikeKw > 0 && i === count - 2) {
      const scaledSpike = selectedZone ? Math.max(45, Math.round(injectedSpikeKw * Math.max(0.25, zoneScale))) : injectedSpikeKw;
      anomalyBoost += scaledSpike;
      if (!selectedZone) {
        eventZone = facility.zones[1]?.name ?? facility.zones[0].name;
      }
      probableCause = 'Simulated fault injection — sudden inductive load surge';
    }

    const activeZoneName = selectedZone ? selectedZone.name : eventZone;

    const actualKw = Math.max(10, Math.round(baselineKw + noise + anomalyBoost));
    const zScore = Number(((actualKw - baselineKw) / Math.max(1, stdDevKw)).toFixed(2));
    const basePf = selectedZone ? selectedZone.powerFactor : 0.94;
    const powerFactor = Number(
      Math.max(0.81, Math.min(0.98, basePf - (anomalyBoost > 0 ? 0.08 : 0) + noise / 5000)).toFixed(2)
    );
    const ambientTempC = Number((19 + 7 * Math.sin(((hourOfDay - 8) / 24) * Math.PI * 2)).toFixed(1));

    const label =
      window === '24h'
        ? `${String(i).padStart(2, '0')}:00`
        : window === '7d'
          ? `D${Math.floor(i / 4) + 1} ${String((i % 4) * 6).padStart(2, '0')}h`
          : `Nov ${String(i + 1).padStart(2, '0')}`;

    points.push({
      id: `pt-${facilityId}-${window}-${zoneId ?? 'all'}-${i}`,
      label,
      timestamp:
        window === '24h'
          ? `2026-11-18 ${String(i).padStart(2, '0')}:00`
          : window === '7d'
            ? `2026-11-${String(12 + Math.floor(i / 4)).padStart(2, '0')} ${String((i % 4) * 6).padStart(2, '0')}:00`
            : `2026-11-${String(i + 1).padStart(2, '0')} 14:00`,
      actualKw,
      baselineKw,
      stdDevKw,
      powerFactor,
      tariffPeriod,
      ambientTempC,
      zScore,
      zone: selectedZone ? selectedZone.name : activeZoneName,
      probableCause,
    });
  }

  return points;
}

export function detectAnomaliesFromSeries(
  facility: FacilityProfile,
  series: TelemetryPoint[],
  sigmaThreshold: number,
  statusOverrides: Record<string, AnomalyStatus>,
  windowKey?: TimeWindow
): AnomalyRecord[] {
  const anomalies: AnomalyRecord[] = [];

  for (const pt of series) {
    if (pt.zScore >= sigmaThreshold) {
      const deviationPct = Number((((pt.actualKw - pt.baselineKw) / pt.baselineKw) * 100).toFixed(1));
      const severity: AnomalySeverity =
        pt.zScore >= sigmaThreshold + 1.4
          ? 'Critical'
          : pt.zScore >= sigmaThreshold + 0.6
            ? 'High'
            : 'Elevated';

      const zoneObj = facility.zones.find((z) => z.name === pt.zone) ?? facility.zones[0];
      const deltaKw = Math.max(10, pt.actualKw - pt.baselineKw);
      const durationMin = severity === 'Critical' ? 45 : severity === 'High' ? 30 : 20;
      const estimatedWasteKwh = Math.round((deltaKw * durationMin) / 60);
      const rate = pt.tariffPeriod === 'Peak' ? facility.peakTariffRateUsd : facility.tariffRateUsd;
      const estimatedCostUsd = Number((estimatedWasteKwh * rate).toFixed(2));

      const id = `ANM-${pt.id.split('-').slice(-1)[0].padStart(3, '0')}`;
      const scopedStatusKey = windowKey
        ? getAnomalyStatusKey(facility.id, windowKey, id)
        : id;

      const baselineWaveform = Array.from({ length: 12 }, (_, idx) =>
        Math.round(pt.baselineKw + Math.sin(idx * 0.6) * pt.stdDevKw * 0.4)
      );
      const waveform = baselineWaveform.map((base, idx) =>
        idx >= 3 && idx <= 8
          ? Math.round(base + deltaKw * (idx === 5 || idx === 6 ? 1.05 : 0.78))
          : Math.round(base + (deterministicNoise(idx + pt.actualKw) - 0.5) * 18)
      );

      anomalies.push({
        id,
        pointId: pt.id,
        timestamp: pt.timestamp,
        meterCode: zoneObj.meterCode,
        zone: zoneObj.name,
        severity,
        zScore: pt.zScore,
        actualKw: pt.actualKw,
        expectedKw: pt.baselineKw,
        deviationPct,
        durationMin,
        estimatedWasteKwh,
        estimatedCostUsd,
        signature: pt.probableCause ?? 'Sustained load excursion above rolling 30-day envelope',
        recommendation:
          severity === 'Critical'
            ? `Dispatch utility engineer to inspect ${zoneObj.meterCode} contactor and isolate parasitic load.`
            : `Verify VFD setpoint and check power factor compensation on ${zoneObj.name}.`,
        status: statusOverrides[scopedStatusKey] ?? statusOverrides[id] ?? 'Open',
        waveform,
        baselineWaveform,
      });
    }
  }

  return anomalies.sort((a, b) => b.zScore - a.zScore);
}

export interface DashboardKpis {
  totalMwh: number;
  peakDemandKw: number;
  demandCeilingKw: number;
  demandHeadroomPct: number;
  avgPf: number;
  openAnomaliesCount: number;
  criticalCount: number;
  potentialSavingsUsd: number;
}

export function calculateKpis(
  facility: FacilityProfile,
  series: TelemetryPoint[],
  timeWindow: TimeWindow,
  anomalies: AnomalyRecord[],
  selectedZone: SubMeterZone | null
): DashboardKpis {
  const intervalHours = timeWindow === '24h' ? 1 : timeWindow === '7d' ? 6 : 24;
  const totalKwh = series.reduce((sum, pt) => sum + pt.actualKw, 0) * intervalHours;
  const totalMwh = totalKwh / 1000;
  const peakDemandKw = Math.max(...series.map((p) => p.actualKw), 0);
  const demandCeilingKw = getScopedDemandCeilingKw(facility, selectedZone?.id ?? null);
  const avgPf = series.reduce((sum, pt) => sum + pt.powerFactor, 0) / Math.max(1, series.length);
  const openAnomalies = anomalies.filter((a) => a.status !== 'Resolved');
  const scopedInsights = selectedZone
    ? facility.insights.filter((ins) => ins.zone === selectedZone.name)
    : facility.insights;
  const potentialSavingsUsd = scopedInsights.reduce((sum, item) => sum + item.annualUsdSavings, 0);

  return {
    totalMwh,
    peakDemandKw,
    demandCeilingKw,
    demandHeadroomPct: Math.round((peakDemandKw / Math.max(1, demandCeilingKw)) * 100),
    avgPf,
    openAnomaliesCount: openAnomalies.length,
    criticalCount: openAnomalies.filter((a) => a.severity === 'Critical').length,
    potentialSavingsUsd,
  };
}

export function buildCsvContent(
  facility: FacilityProfile,
  series: TelemetryPoint[],
  anomalies: AnomalyRecord[]
): string {
  const headers = [
    'Facility',
    'Timestamp',
    'Actual_kW',
    'Baseline_kW',
    'StdDev_kW',
    'Z_Score',
    'Power_Factor',
    'Tariff_Period',
    'Zone',
    'Anomaly_Flag',
  ];
  const anomalyPointIds = new Set(anomalies.map((a) => a.pointId));
  const rows = series.map((pt) => [
    `"${facility.name}"`,
    pt.timestamp,
    pt.actualKw,
    pt.baselineKw,
    pt.stdDevKw,
    pt.zScore,
    pt.powerFactor,
    pt.tariffPeriod,
    `"${pt.zone}"`,
    anomalyPointIds.has(pt.id) ? 'ANOMALY' : 'NORMAL',
  ]);

  return [headers.join(','), ...rows.map((r) => r.join(','))].join('\n');
}

export function exportTelemetryCsv(
  facility: FacilityProfile,
  series: TelemetryPoint[],
  anomalies: AnomalyRecord[],
  zoneSlug?: string
): void {
  const csvContent = buildCsvContent(facility, series, anomalies);
  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  const scopeSuffix = zoneSlug ? `-${zoneSlug}` : '';
  link.href = url;
  link.setAttribute('download', `enerygrid-${facility.code.toLowerCase()}${scopeSuffix}-telemetry.csv`);
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

// EnergyUnitMode re-exported from ../types/energy above

export interface ConsumptionExportFilters {
  facilityId: FacilityId;
  zoneId: string | null;
  meterCode: string | null;
  startDate: string;
  endDate: string;
  timeWindow: TimeWindow;
  injectedSpikeKw?: number;
  sigmaThreshold?: number;
  anomalyStatuses?: Record<string, AnomalyStatus>;
}

export interface ConsumptionExportRow {
  facilityName: string;
  facilityCode: string;
  timestamp: string;
  date: string;
  zone: string;
  meterCode: string;
  equipmentName: string;
  intervalHours: number;
  actualKw: number;
  baselineKw: number;
  consumptionKwh: number;
  consumptionMwh: number;
  baselineKwh: number;
  baselineMwh: number;
  powerFactor: number;
  tariffPeriod: TelemetryPoint['tariffPeriod'];
  zScore: number;
  anomalyFlag: 'ANOMALY' | 'NORMAL';
}

export interface ConsumptionExportResult {
  rows: ConsumptionExportRow[];
  effectiveWindow: TimeWindow;
  intervalHours: number;
  totalKwh: number;
  totalMwh: number;
  peakKw: number;
  anomalyCount: number;
  filename: string;
}

export const TELEMETRY_MIN_DATE = '2026-11-01';
export const TELEMETRY_MAX_DATE = '2026-11-30';

export function getTimeWindowDateBounds(timeWindow: TimeWindow): {
  startDate: string;
  endDate: string;
  minDate: string;
  maxDate: string;
} {
  if (timeWindow === '24h') {
    return {
      startDate: '2026-11-18',
      endDate: '2026-11-18',
      minDate: TELEMETRY_MIN_DATE,
      maxDate: TELEMETRY_MAX_DATE,
    };
  }
  if (timeWindow === '7d') {
    return {
      startDate: '2026-11-12',
      endDate: '2026-11-18',
      minDate: TELEMETRY_MIN_DATE,
      maxDate: TELEMETRY_MAX_DATE,
    };
  }
  return {
    startDate: TELEMETRY_MIN_DATE,
    endDate: TELEMETRY_MAX_DATE,
    minDate: TELEMETRY_MIN_DATE,
    maxDate: TELEMETRY_MAX_DATE,
  };
}

export function resolveExportTimeWindow(
  requestedWindow: TimeWindow,
  startDate: string,
  endDate: string
): TimeWindow {
  if (requestedWindow === '24h' && startDate === '2026-11-18' && endDate === '2026-11-18') {
    return '24h';
  }
  if (requestedWindow === '7d' && startDate >= '2026-11-12' && endDate <= '2026-11-18') {
    return '7d';
  }
  if (requestedWindow === '30d') {
    return '30d';
  }
  if (startDate >= '2026-11-12' && endDate <= '2026-11-18') {
    return '7d';
  }
  return '30d';
}

export function getAvailableMetersForFilter(
  facility: FacilityProfile,
  zoneId: string | null
): MeterAsset[] {
  if (!zoneId) return facility.meters;
  const zone = facility.zones.find((z) => z.id === zoneId);
  if (!zone) return facility.meters;
  return facility.meters.filter((m) => m.zone === zone.name);
}

export function getFilteredConsumptionData(
  filters: ConsumptionExportFilters
): ConsumptionExportResult {
  const facility = FACILITIES[filters.facilityId];
  const effectiveWindow = resolveExportTimeWindow(
    filters.timeWindow,
    filters.startDate,
    filters.endDate
  );
  const intervalHours = effectiveWindow === '24h' ? 1 : effectiveWindow === '7d' ? 6 : 24;

  const zoneSuffix = filters.zoneId ? `-${filters.zoneId}` : '';
  const meterSuffix = filters.meterCode ? `-${filters.meterCode.toLowerCase()}` : '';
  const filename = `enerygrid-${facility.code.toLowerCase()}${zoneSuffix}${meterSuffix}-${filters.startDate}-to-${filters.endDate}.csv`;

  if (!filters.startDate || !filters.endDate || filters.startDate > filters.endDate) {
    return {
      rows: [],
      effectiveWindow,
      intervalHours,
      totalKwh: 0,
      totalMwh: 0,
      peakKw: 0,
      anomalyCount: 0,
      filename,
    };
  }

  const selectedZone = filters.zoneId
    ? facility.zones.find((z) => z.id === filters.zoneId) ?? null
    : null;

  const selectedMeter = filters.meterCode
    ? facility.meters.find((m) => m.meterCode === filters.meterCode) ?? null
    : null;

  let effectiveZoneId: string | null = filters.zoneId;
  let meterShare = 1;

  if (filters.meterCode) {
    if (selectedMeter) {
      const meterZone = facility.zones.find((z) => z.name === selectedMeter.zone) ?? null;
      if (selectedZone && meterZone && selectedZone.id !== meterZone.id) {
        return {
          rows: [],
          effectiveWindow,
          intervalHours,
          totalKwh: 0,
          totalMwh: 0,
          peakKw: 0,
          anomalyCount: 0,
          filename,
        };
      }
      effectiveZoneId = meterZone?.id ?? filters.zoneId;
      const zoneMeters = facility.meters.filter((m) => m.zone === selectedMeter.zone);
      if (zoneMeters.length > 1) {
        const totalCurrentKw = zoneMeters.reduce((sum, m) => sum + m.currentKw, 0);
        meterShare =
          totalCurrentKw > 0 ? selectedMeter.currentKw / totalCurrentKw : 1 / zoneMeters.length;
      }
    } else {
      const zoneByMeterCode =
        facility.zones.find((z) => z.meterCode === filters.meterCode) ?? null;
      if (!zoneByMeterCode || (selectedZone && selectedZone.id !== zoneByMeterCode.id)) {
        return {
          rows: [],
          effectiveWindow,
          intervalHours,
          totalKwh: 0,
          totalMwh: 0,
          peakKw: 0,
          anomalyCount: 0,
          filename,
        };
      }
      effectiveZoneId = zoneByMeterCode.id;
    }
  }

  const series = generateTelemetrySeries(
    filters.facilityId,
    effectiveWindow,
    filters.injectedSpikeKw ?? 0,
    effectiveZoneId
  );

  const anomalies = detectAnomaliesFromSeries(
    facility,
    series,
    filters.sigmaThreshold ?? 2.0,
    filters.anomalyStatuses ?? {},
    effectiveWindow
  );
  const anomalyPointIds = new Set(anomalies.map((a) => a.pointId));

  const filteredPoints = series.filter((pt) => {
    const datePart = pt.timestamp.slice(0, 10);
    return datePart >= filters.startDate && datePart <= filters.endDate;
  });

  const rows: ConsumptionExportRow[] = filteredPoints.map((pt) => {
    const zoneObj = facility.zones.find((z) => z.name === pt.zone) ?? facility.zones[0];
    const primaryMeter =
      selectedMeter ??
      facility.meters.find((m) => m.meterCode === zoneObj.meterCode) ??
      facility.meters.find((m) => m.zone === zoneObj.name) ??
      null;

    const actualKw = Math.round(pt.actualKw * meterShare);
    const baselineKw = Math.round(pt.baselineKw * meterShare);
    const consumptionKwh = Number((actualKw * intervalHours).toFixed(2));
    const consumptionMwh = Number((consumptionKwh / 1000).toFixed(4));
    const baselineKwh = Number((baselineKw * intervalHours).toFixed(2));
    const baselineMwh = Number((baselineKwh / 1000).toFixed(4));

    return {
      facilityName: facility.name,
      facilityCode: facility.code,
      timestamp: pt.timestamp,
      date: pt.timestamp.slice(0, 10),
      zone: pt.zone,
      meterCode: selectedMeter?.meterCode ?? primaryMeter?.meterCode ?? zoneObj.meterCode,
      equipmentName: selectedMeter?.equipmentName ?? primaryMeter?.equipmentName ?? zoneObj.name,
      intervalHours,
      actualKw,
      baselineKw,
      consumptionKwh,
      consumptionMwh,
      baselineKwh,
      baselineMwh,
      powerFactor: pt.powerFactor,
      tariffPeriod: pt.tariffPeriod,
      zScore: pt.zScore,
      anomalyFlag: anomalyPointIds.has(pt.id) ? 'ANOMALY' : 'NORMAL',
    };
  });

  const totalKwh = Number(rows.reduce((sum, r) => sum + r.consumptionKwh, 0).toFixed(2));
  const totalMwh = Number((totalKwh / 1000).toFixed(4));
  const peakKw = rows.length > 0 ? Math.max(...rows.map((r) => r.actualKw)) : 0;
  const anomalyCount = rows.filter((r) => r.anomalyFlag === 'ANOMALY').length;

  return {
    rows,
    effectiveWindow,
    intervalHours,
    totalKwh,
    totalMwh,
    peakKw,
    anomalyCount,
    filename,
  };
}

function escapeCsvCell(value: string | number): string {
  if (typeof value === 'number') {
    return String(value);
  }
  const safe = /^[=+\-@]/.test(value) ? `'${value}` : value;
  if (/[",\n\r]/.test(safe)) {
    return `"${safe.replace(/"/g, '""')}"`;
  }
  return `"${safe}"`;
}

export function buildConsumptionCsvContent(
  rows: ConsumptionExportRow[],
  unitMode: EnergyUnitMode = 'both'
): string {
  const unitHeaders =
    unitMode === 'both'
      ? ['Consumption_kWh', 'Consumption_MWh', 'Baseline_kWh', 'Baseline_MWh']
      : unitMode === 'kwh'
        ? ['Consumption_kWh', 'Baseline_kWh']
        : ['Consumption_MWh', 'Baseline_MWh'];

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
    'Anomaly_Flag',
  ];

  const csvRows = rows.map((row) => {
    const unitValues =
      unitMode === 'both'
        ? [row.consumptionKwh, row.consumptionMwh, row.baselineKwh, row.baselineMwh]
        : unitMode === 'kwh'
          ? [row.consumptionKwh, row.baselineKwh]
          : [row.consumptionMwh, row.baselineMwh];

    return [
      escapeCsvCell(row.facilityName),
      row.facilityCode,
      row.timestamp,
      escapeCsvCell(row.zone),
      row.meterCode,
      escapeCsvCell(row.equipmentName),
      row.intervalHours,
      row.actualKw,
      row.baselineKw,
      ...unitValues,
      row.powerFactor,
      row.tariffPeriod,
      row.zScore,
      row.anomalyFlag,
    ].join(',');
  });

  return [headers.join(','), ...csvRows].join('\n');
}

export function exportConsumptionCsv(
  filters: ConsumptionExportFilters,
  unitMode: EnergyUnitMode = 'both'
): ConsumptionExportResult {
  const result = getFilteredConsumptionData(filters);
  const csvContent = buildConsumptionCsvContent(result.rows, unitMode);
  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.setAttribute('download', result.filename);
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
  return result;
}

