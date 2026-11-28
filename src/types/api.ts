import { AuthUser, UserRole } from './auth';

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export type HealthStatus = 'Nominal' | 'Warning' | 'Fault';
export type TariffPeriod = 'Peak' | 'Mid-Peak' | 'Off-Peak';
export type BaselineStatus = 'ready' | 'insufficient_history';
export type QualityFlag = 'valid' | 'gap_bounded' | 'simulated';
export type TelemetrySource = 'meter_feed' | 'csv_import' | 'seed' | 'simulation';

export type AnomalySeverity = 'Critical' | 'High' | 'Elevated';
export type AnomalyStatus = 'Open' | 'Acknowledged' | 'Assigned' | 'Resolved';

export type InsightCategory =
  | 'Load Shifting'
  | 'Power Quality'
  | 'HVAC & Thermal'
  | 'Compressed Air';
export type InsightPriority = 'High' | 'Medium';
export type InsightStatus = 'Recommended' | 'In Progress' | 'Implemented';
export type CostEstimateStatus =
  | 'available'
  | 'unavailable_tariff'
  | 'not_quantifiable'
  | 'legacy_unverified';
export type InsightSavingsBasis =
  | 'tariff_arbitrage_only'
  | 'estimated_excess_avoidance'
  | 'unquantified_telemetry'
  | 'legacy_migrated';
export type InsightRuleCode =
  | 'PEAK_LOAD_SHIFT'
  | 'LOW_POWER_FACTOR'
  | 'OFF_PEAK_BASELOAD_PATTERN'
  | 'THERMAL_CORRELATED_LOAD';

export type DecimalValue = number | string;

export interface HealthResponse {
  status: string;
  service: string;
  environment: string;
  database: string;
  timestamp: string;
}

export interface UserAdminUpdateRequest {
  role?: UserRole;
  is_active?: boolean;
}

export interface FacilityResponse {
  id: string;
  code: string;
  name: string;
  location: string;
  timezone: string;
  currency_code: string;
  contracted_demand_kw: DecimalValue;
  off_peak_tariff_rate: DecimalValue;
  mid_peak_tariff_rate: DecimalValue;
  peak_tariff_rate: DecimalValue;
  is_active: boolean;
  deactivated_at: string | null;
  created_at: string;
  zone_count: number;
  active_zone_count: number;
  meter_count: number;
  active_meter_count: number;
}

export interface FacilityCreate {
  id: string;
  code: string;
  name: string;
  location: string;
  timezone: string;
  currency_code: string;
  contracted_demand_kw: number | string;
  off_peak_tariff_rate: number | string;
  mid_peak_tariff_rate: number | string;
  peak_tariff_rate: number | string;
}

export interface FacilityUpdate {
  code?: string;
  name?: string;
  location?: string;
  timezone?: string;
  currency_code?: string;
  contracted_demand_kw?: number | string;
  off_peak_tariff_rate?: number | string;
  mid_peak_tariff_rate?: number | string;
  peak_tariff_rate?: number | string;
}

export interface ZoneResponse {
  id: string;
  facility_id: string;
  slug: string;
  name: string;
  primary_meter_code: string;
  share_pct: DecimalValue;
  status: HealthStatus;
  is_active: boolean;
  deactivated_at: string | null;
  meter_count: number;
  active_meter_count: number;
}

export interface ZoneCreate {
  facility_id: string;
  slug: string;
  name: string;
  primary_meter_code: string;
  share_pct: number | string;
  status?: HealthStatus;
}

export interface ZoneUpdate {
  slug?: string;
  name?: string;
  primary_meter_code?: string;
  share_pct?: number | string;
  status?: HealthStatus;
}

export interface MeterResponse {
  id: string;
  facility_id: string;
  zone_id: string;
  meter_code: string;
  equipment_name: string;
  rated_kw: DecimalValue;
  nominal_interval_seconds: number;
  current_kw: DecimalValue;
  power_factor: DecimalValue;
  thd_pct: DecimalValue;
  status: HealthStatus;
  last_calibrated_at: string;
  is_active: boolean;
  deactivated_at: string | null;
}

export interface MeterCreate {
  facility_id: string;
  zone_id: string;
  meter_code: string;
  equipment_name: string;
  rated_kw: number | string;
  nominal_interval_seconds?: number;
  current_kw?: number | string;
  power_factor: number | string;
  thd_pct: number | string;
  status?: HealthStatus;
  last_calibrated_at: string;
}

export interface MeterUpdate {
  zone_id?: string;
  meter_code?: string;
  equipment_name?: string;
  rated_kw?: number | string;
  nominal_interval_seconds?: number;
  current_kw?: number | string;
  power_factor?: number | string;
  thd_pct?: number | string;
  status?: HealthStatus;
  last_calibrated_at?: string;
}

export interface TelemetryReadingResponse {
  id: number;
  facility_id: string;
  zone_id: string;
  meter_id: string;
  interval_start: string;
  recorded_at: string;
  interval_seconds: number;
  actual_kw: DecimalValue;
  energy_kwh: DecimalValue;
  baseline_kw: DecimalValue | null;
  std_dev_kw: DecimalValue | null;
  z_score: DecimalValue | null;
  baseline_status: BaselineStatus;
  power_factor: DecimalValue;
  tariff_period: TariffPeriod;
  ambient_temp_c: DecimalValue | null;
  quality_flag: QualityFlag;
  source: TelemetrySource;
}

export interface TelemetryReadingCreate {
  meter_id?: string;
  meter_code?: string;
  facility_id?: string;
  zone_id?: string;
  recorded_at: string;
  interval_start?: string;
  interval_seconds?: number;
  actual_kw: number | string;
  energy_kwh?: number | string;
  power_factor: number | string;
  ambient_temp_c?: number | string;
  tariff_period?: TariffPeriod;
  quality_flag?: QualityFlag;
  source?: TelemetrySource;
}

export interface TelemetryBulkIngestRequest {
  atomic?: boolean;
  readings: TelemetryReadingCreate[];
}

export interface IngestionRowError {
  row_index: number;
  row_number: number | null;
  meter_id: string | null;
  meter_code: string | null;
  recorded_at: string | null;
  code: string;
  message: string;
}

export interface TelemetryIngestionSummary {
  atomic: boolean;
  total_received: number;
  inserted_count: number;
  duplicate_count: number;
  overlap_count: number;
  failed_count: number;
  inserted_ids: number[];
  errors: IngestionRowError[];
}

export interface AnalyticsCursor {
  last_meter_id: string;
  last_recorded_at: string;
  last_reading_id: number;
}

export interface AnalyticsProcessRequest {
  facility_id?: string;
  zone_id?: string;
  meter_id?: string;
  start_at?: string;
  end_at?: string;
  reprocess?: boolean;
  retry_insufficient?: boolean;
  retry_exhausted?: boolean;
  max_readings?: number;
  include_insights?: boolean;
  cursor?: AnalyticsCursor;
}

export interface AnalyticsProcessSummary {
  processed_readings: number;
  baselines_ready: number;
  baselines_insufficient: number;
  anomalies_created: number;
  anomalies_reconciled: number;
  anomalies_unchanged: number;
  insights_created: number;
  insights_updated: number;
  exhausted_skipped_count: number;
  remaining_eligible_readings: number;
  has_more: boolean;
  next_cursor: AnalyticsCursor | null;
}

export interface AnalyticsSeriesBucketItem {
  timestamp: string;
  label: string;
  actual_kw: number;
  baseline_kw: number;
  std_dev_kw: number;
  has_baseline: boolean;
  power_factor: number;
  tariff_period: TariffPeriod;
  ambient_temp_c: number;
  z_score: number;
  zone_id: string;
}

export interface ZoneAnalyticsSummaryItem {
  zone_id: string;
  slug: string;
  name: string;
  primary_meter_code: string;
  kwh_used: number;
  share_pct: number;
  avg_kw: number;
  peak_kw: number;
  power_factor: number;
  delta_vs_baseline_pct: number;
  derived_status: HealthStatus;
  reading_count: number;
}

export interface MeterLiveSnapshotItem {
  meter_id: string;
  meter_code: string;
  zone_id: string;
  latest_recorded_at: string | null;
  latest_kw: number;
  avg_kw: number;
  peak_kw: number;
  latest_power_factor: number;
  reading_count: number;
  open_anomalies_count: number;
  derived_status: HealthStatus;
}

export interface AnalyticsSummaryResponse {
  facility_id: string;
  zone_id: string | null;
  time_window: string;
  include_simulated: boolean;
  window_start: string;
  window_end: string;
  latest_recorded_at: string | null;
  reading_count: number;
  baselined_reading_count: number;
  total_kwh: number;
  total_mwh: number;
  avg_demand_kw: number;
  peak_demand_kw: number;
  contracted_demand_kw: number;
  demand_headroom_pct: number;
  avg_power_factor: number;
  previous_total_kwh: number;
  consumption_trend_pct: number | null;
  open_anomalies_count: number;
  critical_anomalies_count: number;
  potential_annual_savings: number;
  has_quantified_savings: boolean;
  unquantified_insights_count: number;
  zone_breakdown: ZoneAnalyticsSummaryItem[];
  meter_snapshots: MeterLiveSnapshotItem[];
  series: AnalyticsSeriesBucketItem[];
  heatmap_matrix: number[][];
}

export interface AnomalyResponse {
  id: string;
  event_code: string;
  facility_id: string;
  zone_id: string;
  meter_id: string;
  reading_id: number | null;
  detected_at: string;
  severity: AnomalySeverity;
  status: AnomalyStatus;
  z_score: DecimalValue;
  actual_kw: DecimalValue;
  expected_kw: DecimalValue;
  deviation_pct: DecimalValue;
  duration_min: number;
  estimated_waste_kwh: DecimalValue;
  estimated_cost: DecimalValue | null;
  cost_estimate_status: CostEstimateStatus;
  signature: string;
  recommendation: string;
  assigned_to_user_id: string | null;
}

export interface AnomalyDetailResponse extends AnomalyResponse {
  waveform: number[];
  baseline_waveform: number[];
}

export interface AnomalyWorkflowLogResponse {
  id: string;
  anomaly_id: string;
  from_status: AnomalyStatus | null;
  to_status: AnomalyStatus;
  from_assignee_id: string | null;
  to_assignee_id: string | null;
  changed_by_user_id: string | null;
  note: string | null;
  changed_at: string;
}

export interface AnomalyAcknowledgeRequest {
  note?: string | null;
}

export interface AnomalyInvestigateRequest {
  assigned_to_user_id?: string | null;
  note?: string | null;
}

export interface AnomalyResolveRequest {
  note: string;
}

export interface AnomalyReopenRequest {
  note: string;
}

export interface InsightResponse {
  id: string;
  facility_id: string;
  zone_id: string;
  meter_id: string | null;
  rule_code: InsightRuleCode;
  dedupe_key: string;
  title: string;
  category: InsightCategory;
  summary: string;
  monthly_kwh_savings: DecimalValue;
  annual_cost_savings: DecimalValue | null;
  payback_months: DecimalValue | null;
  cost_estimate_status: CostEstimateStatus;
  savings_basis: InsightSavingsBasis;
  priority: InsightPriority;
  status: InsightStatus;
  updated_at: string;
}

export interface InsightDetailResponse extends InsightResponse {
  evidence: Record<string, unknown> | null;
}

export interface InsightWorkflowLogResponse {
  id: string;
  insight_id: string;
  from_status: InsightStatus | null;
  to_status: InsightStatus;
  changed_by_user_id: string | null;
  note: string | null;
  changed_at: string;
}

export interface InsightStatusUpdateRequest {
  status: InsightStatus;
  note?: string | null;
}

export type { AuthUser, UserRole };
