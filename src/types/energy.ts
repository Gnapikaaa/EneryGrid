export type TimeWindow = '24h' | '7d' | '30d';
export type EnergyUnitMode = 'both' | 'kwh' | 'mwh';
export type DataSourceScope = 'measured' | 'all' | 'simulation';

export interface TelemetryPoint {
  id: string;
  label: string;
  timestamp: string;
  actualKw: number;
  baselineKw: number;
  stdDevKw: number;
  powerFactor: number;
  tariffPeriod: 'Peak' | 'Mid-Peak' | 'Off-Peak';
  ambientTempC: number;
  zScore: number;
  zone: string;
  probableCause?: string;
  hasBaseline?: boolean;
}

export interface SubMeterZone {
  id: string;
  name: string;
  meterCode: string;
  kwhUsed: number;
  sharePct: number;
  peakKw: number;
  powerFactor: number;
  deltaVsBaselinePct: number;
  status: 'Nominal' | 'Warning' | 'Fault';
}
