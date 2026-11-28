import { apiClient } from './client';
import { buildQueryString } from './query';
import {
  InsightCategory,
  InsightDetailResponse,
  InsightPriority,
  InsightResponse,
  InsightStatus,
  InsightStatusUpdateRequest,
  InsightWorkflowLogResponse,
  PaginatedResponse,
} from '../types/api';

export interface ListInsightsParams {
  page?: number;
  page_size?: number;
  facility_id?: string;
  zone_id?: string;
  meter_id?: string;
  status?: InsightStatus;
  priority?: InsightPriority;
  category?: InsightCategory;
}

export function listInsights(
  params: ListInsightsParams = {},
  signal?: AbortSignal
): Promise<PaginatedResponse<InsightResponse>> {
  const qs = buildQueryString({
    page: params.page ?? 1,
    page_size: params.page_size ?? 100,
    facility_id: params.facility_id,
    zone_id: params.zone_id,
    meter_id: params.meter_id,
    status: params.status,
    priority: params.priority,
    category: params.category,
  });
  return apiClient.get<PaginatedResponse<InsightResponse>>(`/insights${qs}`, { signal });
}

export function getInsight(
  insightId: string,
  signal?: AbortSignal
): Promise<InsightDetailResponse> {
  return apiClient.get<InsightDetailResponse>(`/insights/${encodeURIComponent(insightId)}`, {
    signal,
  });
}

export function getInsightHistory(
  insightId: string,
  signal?: AbortSignal
): Promise<InsightWorkflowLogResponse[]> {
  return apiClient.get<InsightWorkflowLogResponse[]>(
    `/insights/${encodeURIComponent(insightId)}/history`,
    { signal }
  );
}

export function updateInsightStatus(
  insightId: string,
  payload: InsightStatusUpdateRequest
): Promise<InsightDetailResponse> {
  return apiClient.patch<InsightDetailResponse>(
    `/insights/${encodeURIComponent(insightId)}`,
    payload
  );
}
