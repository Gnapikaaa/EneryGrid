import { apiClient } from './client';
import { buildQueryString } from './query';
import {
  FacilityCreate,
  FacilityResponse,
  FacilityUpdate,
  PaginatedResponse,
} from '../types/api';

export interface ListFacilitiesParams {
  page?: number;
  page_size?: number;
  is_active?: boolean;
  search?: string;
}

export function listFacilities(
  params: ListFacilitiesParams = {},
  signal?: AbortSignal
): Promise<PaginatedResponse<FacilityResponse>> {
  const qs = buildQueryString({
    page: params.page ?? 1,
    page_size: params.page_size ?? 100,
    is_active: params.is_active,
    search: params.search,
  });
  return apiClient.get<PaginatedResponse<FacilityResponse>>(`/facilities${qs}`, { signal });
}

export function getFacility(facilityId: string, signal?: AbortSignal): Promise<FacilityResponse> {
  return apiClient.get<FacilityResponse>(`/facilities/${encodeURIComponent(facilityId)}`, { signal });
}

export function createFacility(payload: FacilityCreate): Promise<FacilityResponse> {
  return apiClient.post<FacilityResponse>('/facilities', payload);
}

export function updateFacility(
  facilityId: string,
  payload: FacilityUpdate
): Promise<FacilityResponse> {
  return apiClient.patch<FacilityResponse>(
    `/facilities/${encodeURIComponent(facilityId)}`,
    payload
  );
}

export function deactivateFacility(facilityId: string): Promise<FacilityResponse> {
  return apiClient.post<FacilityResponse>(
    `/facilities/${encodeURIComponent(facilityId)}/deactivate`
  );
}

export function deleteFacility(facilityId: string): Promise<void> {
  return apiClient.delete<void>(`/facilities/${encodeURIComponent(facilityId)}`);
}
