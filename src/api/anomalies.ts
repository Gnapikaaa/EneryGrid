import { apiClient } from './client';
import { buildQueryString } from './query';
import {
  AnomalyAcknowledgeRequest,
  AnomalyDetailResponse,
  AnomalyInvestigateRequest,
  AnomalyReopenRequest,
  AnomalyResolveRequest,
  AnomalyResponse,
  AnomalySeverity,
  AnomalyStatus,
  AnomalyWorkflowLogResponse,
  PaginatedResponse,
} from '../types/api';

export interface ListAnomaliesParams {
  page?: number;
  page_size?: number;
  facility_id?: string;
  zone_id?: string;
  meter_id?: string;
  status?: AnomalyStatus;
  severity?: AnomalySeverity;
  min_z_score?: number;
  start_at?: string;
  end_at?: string;
}

export function listAnomalies(
  params: ListAnomaliesParams = {},
  signal?: AbortSignal
): Promise<PaginatedResponse<AnomalyResponse>> {
  const qs = buildQueryString({
    page: params.page ?? 1,
    page_size: params.page_size ?? 100,
    facility_id: params.facility_id,
    zone_id: params.zone_id,
    meter_id: params.meter_id,
    status: params.status,
    severity: params.severity,
    min_z_score: params.min_z_score,
    start_at: params.start_at,
    end_at: params.end_at,
  });
  return apiClient.get<PaginatedResponse<AnomalyResponse>>(`/anomalies${qs}`, { signal });
}

export function getAnomaly(
  anomalyId: string,
  signal?: AbortSignal
): Promise<AnomalyDetailResponse> {
  return apiClient.get<AnomalyDetailResponse>(`/anomalies/${encodeURIComponent(anomalyId)}`, {
    signal,
  });
}

export function getAnomalyHistory(
  anomalyId: string,
  signal?: AbortSignal
): Promise<AnomalyWorkflowLogResponse[]> {
  return apiClient.get<AnomalyWorkflowLogResponse[]>(
    `/anomalies/${encodeURIComponent(anomalyId)}/history`,
    { signal }
  );
}

export function acknowledgeAnomaly(
  anomalyId: string,
  payload: AnomalyAcknowledgeRequest = {}
): Promise<AnomalyDetailResponse> {
  return apiClient.post<AnomalyDetailResponse>(
    `/anomalies/${encodeURIComponent(anomalyId)}/acknowledge`,
    payload
  );
}

export function investigateAnomaly(
  anomalyId: string,
  payload: AnomalyInvestigateRequest = {}
): Promise<AnomalyDetailResponse> {
  return apiClient.post<AnomalyDetailResponse>(
    `/anomalies/${encodeURIComponent(anomalyId)}/investigate`,
    payload
  );
}

export function resolveAnomaly(
  anomalyId: string,
  payload: AnomalyResolveRequest
): Promise<AnomalyDetailResponse> {
  return apiClient.post<AnomalyDetailResponse>(
    `/anomalies/${encodeURIComponent(anomalyId)}/resolve`,
    payload
  );
}

export function reopenAnomaly(
  anomalyId: string,
  payload: AnomalyReopenRequest
): Promise<AnomalyDetailResponse> {
  return apiClient.post<AnomalyDetailResponse>(
    `/anomalies/${encodeURIComponent(anomalyId)}/reopen`,
    payload
  );
}
