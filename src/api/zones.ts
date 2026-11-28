import { apiClient } from './client';
import { buildQueryString } from './query';
import {
  HealthStatus,
  PaginatedResponse,
  ZoneCreate,
  ZoneResponse,
  ZoneUpdate,
} from '../types/api';

export interface ListZonesParams {
  page?: number;
  page_size?: number;
  facility_id?: string;
  status?: HealthStatus;
  is_active?: boolean;
  search?: string;
}

export function listZones(
  params: ListZonesParams = {},
  signal?: AbortSignal
): Promise<PaginatedResponse<ZoneResponse>> {
  const qs = buildQueryString({
    page: params.page ?? 1,
    page_size: params.page_size ?? 100,
    facility_id: params.facility_id,
    status: params.status,
    is_active: params.is_active,
    search: params.search,
  });
  return apiClient.get<PaginatedResponse<ZoneResponse>>(`/zones${qs}`, { signal });
}

export function createZone(payload: ZoneCreate): Promise<ZoneResponse> {
  return apiClient.post<ZoneResponse>('/zones', payload);
}

export function updateZone(zoneId: string, payload: ZoneUpdate): Promise<ZoneResponse> {
  return apiClient.patch<ZoneResponse>(`/zones/${encodeURIComponent(zoneId)}`, payload);
}

export function deactivateZone(zoneId: string): Promise<ZoneResponse> {
  return apiClient.post<ZoneResponse>(`/zones/${encodeURIComponent(zoneId)}/deactivate`);
}

export function deleteZone(zoneId: string): Promise<void> {
  return apiClient.delete<void>(`/zones/${encodeURIComponent(zoneId)}`);
}
