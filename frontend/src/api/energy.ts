/**
 * EnergyGrid API client helpers for domain endpoints.
 *
 * All functions use the shared apiClient which automatically attaches
 * Bearer tokens and handles 401 → logout.
 */

import { apiClient } from './client';

// ---------------------------------------------------------------------------
// Paginated envelope (mirrors backend PaginatedResponse[T])
// ---------------------------------------------------------------------------
export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

// ---------------------------------------------------------------------------
// Facility
// ---------------------------------------------------------------------------
export interface ApiFacilityResponse {
  id: string;
  code: string;
  name: string;
  location: string;
  timezone: string;
  currency_code: string;
  contracted_demand_kw: string; // Decimal serialised as string
  off_peak_tariff_rate: string;
  mid_peak_tariff_rate: string;
  peak_tariff_rate: string;
  is_active: boolean;
  deactivated_at: string | null;
  created_at: string;
  zone_count: number;
  active_zone_count: number;
  meter_count: number;
  active_meter_count: number;
}

export async function fetchFacilities(
  pageSize = 100
): Promise<PaginatedResponse<ApiFacilityResponse>> {
  return apiClient.get<PaginatedResponse<ApiFacilityResponse>>(
    `/facilities?page=1&page_size=${pageSize}`
  );
}

// ---------------------------------------------------------------------------
// Anomalies
// ---------------------------------------------------------------------------
export interface ApiAnomalyResponse {
  id: string;
  event_code: string;
  facility_id: string;
  zone_id: string;
  meter_id: string;
  reading_id: number | null;
  detected_at: string;
  severity: 'Critical' | 'High' | 'Elevated';
  status: 'Open' | 'Acknowledged' | 'Assigned' | 'Resolved';
  z_score: string; // Decimal
  actual_kw: string; // Decimal
  expected_kw: string; // Decimal
  deviation_pct: string; // Decimal
  duration_min: number;
  estimated_waste_kwh: string; // Decimal
  estimated_cost: string | null; // Decimal
  cost_estimate_status: string;
  signature: string;
  recommendation: string;
  assigned_to_user_id: string | null;
  waveform: number[];
  baseline_waveform: number[];
}

export async function fetchAnomalies(
  facilityId?: string,
  pageSize = 100
): Promise<PaginatedResponse<ApiAnomalyResponse>> {
  const params = new URLSearchParams({ page: '1', page_size: String(pageSize) });
  if (facilityId) params.set('facility_id', facilityId);
  return apiClient.get<PaginatedResponse<ApiAnomalyResponse>>(`/anomalies?${params}`);
}

// ---------------------------------------------------------------------------
// Insights
// ---------------------------------------------------------------------------
export interface ApiInsightResponse {
  id: string;
  facility_id: string;
  zone_id: string;
  meter_id: string | null;
  rule_code: string;
  dedupe_key: string;
  title: string;
  category: 'Load Shifting' | 'Power Quality' | 'HVAC & Thermal' | 'Compressed Air';
  summary: string;
  monthly_kwh_savings: string; // Decimal
  annual_cost_savings: string | null; // Decimal
  payback_months: string | null; // Decimal
  cost_estimate_status: string;
  savings_basis: string;
  priority: 'High' | 'Medium';
  status: 'Recommended' | 'In Progress' | 'Implemented';
  updated_at: string;
}

export async function fetchInsights(
  facilityId?: string,
  pageSize = 100
): Promise<PaginatedResponse<ApiInsightResponse>> {
  const params = new URLSearchParams({ page: '1', page_size: String(pageSize) });
  if (facilityId) params.set('facility_id', facilityId);
  return apiClient.get<PaginatedResponse<ApiInsightResponse>>(`/insights?${params}`);
}

// ---------------------------------------------------------------------------
// Meters
// ---------------------------------------------------------------------------
export interface ApiMeterResponse {
  id: string;
  facility_id: string;
  zone_id: string;
  meter_code: string;
  equipment_name: string;
  rated_kw: string; // Decimal
  nominal_interval_seconds: number;
  current_kw: string; // Decimal
  power_factor: string; // Decimal
  thd_pct: string; // Decimal
  status: 'Nominal' | 'Warning' | 'Fault';
  last_calibrated_at: string; // date ISO
  is_active: boolean;
  deactivated_at: string | null;
}

export async function fetchMeters(
  facilityId?: string,
  pageSize = 100
): Promise<PaginatedResponse<ApiMeterResponse>> {
  const params = new URLSearchParams({ page: '1', page_size: String(pageSize) });
  if (facilityId) params.set('facility_id', facilityId);
  return apiClient.get<PaginatedResponse<ApiMeterResponse>>(`/meters?${params}`);
}
