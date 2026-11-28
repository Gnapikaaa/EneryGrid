import { apiClient } from './client';
import { buildQueryString } from './query';
import {
  PaginatedResponse,
  QualityFlag,
  TelemetryBulkIngestRequest,
  TelemetryIngestionSummary,
  TelemetryReadingCreate,
  TelemetryReadingResponse,
  TelemetrySource,
} from '../types/api';

export interface ListTelemetryReadingsParams {
  page?: number;
  page_size?: number;
  facility_id?: string;
  zone_id?: string;
  meter_id?: string;
  start_at?: string;
  end_at?: string;
  quality_flag?: QualityFlag;
  source?: TelemetrySource;
}

export function listTelemetryReadings(
  params: ListTelemetryReadingsParams = {},
  signal?: AbortSignal
): Promise<PaginatedResponse<TelemetryReadingResponse>> {
  const qs = buildQueryString({
    page: params.page ?? 1,
    page_size: params.page_size ?? 100,
    facility_id: params.facility_id,
    zone_id: params.zone_id,
    meter_id: params.meter_id,
    start_at: params.start_at,
    end_at: params.end_at,
    quality_flag: params.quality_flag,
    source: params.source,
  });
  return apiClient.get<PaginatedResponse<TelemetryReadingResponse>>(
    `/telemetry/readings${qs}`,
    { signal }
  );
}

export async function fetchAllTelemetryReadings(
  params: Omit<ListTelemetryReadingsParams, 'page'>,
  options: { maxPages?: number; signal?: AbortSignal } = {}
): Promise<{ items: TelemetryReadingResponse[]; total: number; truncated: boolean }> {
  const maxPages = options.maxPages ?? 10;
  const pageSize = params.page_size ?? 100;
  const firstPage = await listTelemetryReadings(
    { ...params, page: 1, page_size: pageSize },
    options.signal
  );

  const allItems = [...firstPage.items];
  const targetPages = Math.min(firstPage.pages, maxPages);

  for (let page = 2; page <= targetPages; page += 1) {
    const nextPage = await listTelemetryReadings(
      { ...params, page, page_size: pageSize },
      options.signal
    );
    allItems.push(...nextPage.items);
  }

  return {
    items: allItems,
    total: firstPage.total,
    truncated: firstPage.pages > targetPages,
  };
}

export function ingestTelemetryReading(
  payload: TelemetryReadingCreate
): Promise<TelemetryReadingResponse> {
  return apiClient.post<TelemetryReadingResponse>('/telemetry/readings', payload);
}

export function ingestTelemetryBulk(
  payload: TelemetryBulkIngestRequest
): Promise<TelemetryIngestionSummary> {
  return apiClient.post<TelemetryIngestionSummary>('/telemetry/readings/bulk', payload);
}

export function uploadTelemetryCsv(
  file: File,
  atomic = false
): Promise<TelemetryIngestionSummary> {
  const formData = new FormData();
  formData.append('file', file);
  const qs = buildQueryString({ atomic });
  return apiClient.post<TelemetryIngestionSummary>(`/telemetry/readings/upload${qs}`, formData);
}
