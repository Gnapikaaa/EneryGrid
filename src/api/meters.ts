import { apiClient } from './client';
import { buildQueryString } from './query';
import {
  HealthStatus,
  MeterCreate,
  MeterResponse,
  MeterUpdate,
  PaginatedResponse,
} from '../types/api';

export interface ListMetersParams {
  page?: number;
  page_size?: number;
  facility_id?: string;
  zone_id?: string;
  status?: HealthStatus;
  is_active?: boolean;
  search?: string;
}

export function listMeters(
  params: ListMetersParams = {},
  signal?: AbortSignal
): Promise<PaginatedResponse<MeterResponse>> {
  const qs = buildQueryString({
    page: params.page ?? 1,
    page_size: params.page_size ?? 100,
    facility_id: params.facility_id,
    zone_id: params.zone_id,
    status: params.status,
    is_active: params.is_active,
    search: params.search,
  });
  return apiClient.get<PaginatedResponse<MeterResponse>>(`/meters${qs}`, { signal });
}

export function registerMeter(payload: MeterCreate): Promise<MeterResponse> {
  return apiClient.post<MeterResponse>('/meters', payload);
}

export function updateMeter(meterId: string, payload: MeterUpdate): Promise<MeterResponse> {
  return apiClient.patch<MeterResponse>(`/meters/${encodeURIComponent(meterId)}`, payload);
}

export function deactivateMeter(meterId: string): Promise<MeterResponse> {
  return apiClient.post<MeterResponse>(`/meters/${encodeURIComponent(meterId)}/deactivate`);
}

export function deleteMeter(meterId: string): Promise<void> {
  return apiClient.delete<void>(`/meters/${encodeURIComponent(meterId)}`);
}
