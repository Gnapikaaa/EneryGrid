import { apiClient } from './client';
import { buildQueryString } from './query';
import {
  AnalyticsProcessRequest,
  AnalyticsProcessSummary,
  AnalyticsSummaryResponse,
} from '../types/api';

export interface GetAnalyticsSummaryParams {
  facility_id: string;
  zone_id?: string;
  time_window?: '24h' | '7d' | '30d' | 'custom';
  start_at?: string;
  end_at?: string;
  include_simulated?: boolean;
}

export function getAnalyticsSummary(
  params: GetAnalyticsSummaryParams,
  signal?: AbortSignal
): Promise<AnalyticsSummaryResponse> {
  const qs = buildQueryString({
    facility_id: params.facility_id,
    zone_id: params.zone_id,
    time_window: params.time_window ?? '24h',
    start_at: params.start_at,
    end_at: params.end_at,
    include_simulated: params.include_simulated ?? false,
  });
  return apiClient.get<AnalyticsSummaryResponse>(`/analytics/summary${qs}`, { signal });
}

export function processAnalytics(
  payload: AnalyticsProcessRequest = {}
): Promise<AnalyticsProcessSummary> {
  return apiClient.post<AnalyticsProcessSummary>('/analytics/process', payload);
}
