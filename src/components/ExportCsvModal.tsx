import React, { useEffect, useMemo, useState } from 'react';
import { Download, Loader2, RotateCcw, X } from 'lucide-react';
import { listMeters } from '../api/meters';
import { fetchAllTelemetryReadings } from '../api/telemetry';
import { listZones } from '../api/zones';
import { DataSourceScope, EnergyUnitMode, TimeWindow } from '../types/energy';
import {
  MeterResponse,
  TelemetryReadingResponse,
  ZoneResponse,
} from '../types/api';
import {
  MappedAnomaly,
  MappedFacility,
  buildBackendCsvExportRows,
  filterReadingsBySourceScope,
  serializeBackendCsv,
} from '../utils/energyMappers';
import { SegmentedControl } from './SegmentedControl';

interface ExportCsvModalProps {
  isOpen: boolean;
  onClose: () => void;
  facilities: MappedFacility[];
  dashboardFacilityId: string | null;
  dashboardZones: ZoneResponse[];
  dashboardMeters: MeterResponse[];
  dashboardZoneId: string | null;
  dashboardTimeWindow: TimeWindow;
  dashboardSourceScope?: DataSourceScope;
  dashboardAnomalies: MappedAnomaly[];
  latestTelemetryTimestamp?: string | null;
}

function getDefaultDateBounds(
  timeWindow: TimeWindow,
  anchorIso?: string | null
): { startDate: string; endDate: string } {
  const anchor = anchorIso ? new Date(anchorIso) : new Date();
  const safeAnchor = Number.isNaN(anchor.getTime()) ? new Date() : anchor;
  const endDate = safeAnchor.toISOString().slice(0, 10);
  const daysBack = timeWindow === '24h' ? 0 : timeWindow === '7d' ? 6 : 29;
  const start = new Date(safeAnchor.getTime() - daysBack * 24 * 60 * 60 * 1000);
  return {
    startDate: start.toISOString().slice(0, 10),
    endDate,
  };
}

export const ExportCsvModal: React.FC<ExportCsvModalProps> = ({
  isOpen,
  onClose,
  facilities,
  dashboardFacilityId,
  dashboardZones,
  dashboardMeters,
  dashboardZoneId,
  dashboardTimeWindow,
  dashboardSourceScope = 'measured',
  dashboardAnomalies,
  latestTelemetryTimestamp,
}) => {
  const [facilityId, setFacilityId] = useState<string>(dashboardFacilityId ?? '');
  const [zoneId, setZoneId] = useState<string>(dashboardZoneId ?? '');
  const [meterId, setMeterId] = useState<string>('');
  const [sourceScope, setSourceScope] = useState<DataSourceScope>(dashboardSourceScope);
  const [startDate, setStartDate] = useState<string>(
    () => getDefaultDateBounds(dashboardTimeWindow, latestTelemetryTimestamp).startDate
  );
  const [endDate, setEndDate] = useState<string>(
    () => getDefaultDateBounds(dashboardTimeWindow, latestTelemetryTimestamp).endDate
  );
  const [unitMode, setUnitMode] = useState<EnergyUnitMode>('both');

  const [modalZones, setModalZones] = useState<ZoneResponse[]>(dashboardZones);
  const [modalMeters, setModalMeters] = useState<MeterResponse[]>(dashboardMeters);
  const [readings, setReadings] = useState<TelemetryReadingResponse[]>([]);
  const [totalAvailable, setTotalAvailable] = useState<number>(0);
  const [truncated, setTruncated] = useState<boolean>(false);
  const [loading, setLoading] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [exportedMessage, setExportedMessage] = useState<string | null>(null);
  const [reloadNonce, setReloadNonce] = useState(0);

  const syncWithDashboard = () => {
    const bounds = getDefaultDateBounds(dashboardTimeWindow, latestTelemetryTimestamp);
    setFacilityId(dashboardFacilityId ?? facilities[0]?.id ?? '');
    setZoneId(dashboardZoneId ?? '');
    setMeterId('');
    setSourceScope(dashboardSourceScope);
    setStartDate(bounds.startDate);
    setEndDate(bounds.endDate);
    setUnitMode('both');
    setModalZones(dashboardZones);
    setModalMeters(dashboardMeters);
    setExportedMessage(null);
    setErrorMessage(null);
  };

  useEffect(() => {
    if (isOpen) {
      syncWithDashboard();
    }
  }, [
    isOpen,
    dashboardFacilityId,
    dashboardZoneId,
    dashboardTimeWindow,
    dashboardSourceScope,
    latestTelemetryTimestamp,
  ]);

  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  // Load zones & meters when facility selection differs from dashboard
  useEffect(() => {
    if (!isOpen || !facilityId) return;
    if (facilityId === dashboardFacilityId) {
      setModalZones(dashboardZones);
      setModalMeters(dashboardMeters);
      return;
    }

    const controller = new AbortController();
    Promise.all([
      listZones({ facility_id: facilityId, page_size: 100 }, controller.signal),
      listMeters({ facility_id: facilityId, page_size: 100 }, controller.signal),
    ])
      .then(([zRes, mRes]) => {
        setModalZones(zRes.items);
        setModalMeters(mRes.items);
      })
      .catch((err) => {
        if (err instanceof DOMException && err.name === 'AbortError') return;
        setErrorMessage(err instanceof Error ? err.message : 'Unable to load facility meters.');
      });

    return () => controller.abort();
  }, [isOpen, facilityId, dashboardFacilityId, dashboardZones, dashboardMeters]);

  const isDateRangeValid = Boolean(startDate && endDate && startDate <= endDate);

  // Fetch filtered telemetry readings from backend
  useEffect(() => {
    if (!isOpen || !facilityId) return;
    if (!isDateRangeValid) {
      setReadings([]);
      setTotalAvailable(0);
      setTruncated(false);
      setErrorMessage(null);
      return;
    }

    const controller = new AbortController();
    setLoading(true);
    setErrorMessage(null);

    const startAt = `${startDate}T00:00:00Z`;
    const endAt = `${endDate}T23:59:59Z`;

    fetchAllTelemetryReadings(
      {
        facility_id: facilityId,
        zone_id: zoneId || undefined,
        meter_id: meterId || undefined,
        start_at: startAt,
        end_at: endAt,
        source: sourceScope === 'simulation' ? 'simulation' : undefined,
        page_size: 100,
      },
      { maxPages: 10, signal: controller.signal }
    )
      .then((res) => {
        setReadings(res.items);
        setTotalAvailable(res.total);
        setTruncated(res.truncated);
      })
      .catch((err) => {
        if (err instanceof DOMException && err.name === 'AbortError') return;
        setReadings([]);
        setTotalAvailable(0);
        setTruncated(false);
        setErrorMessage(
          err instanceof Error ? err.message : 'Failed to fetch telemetry readings for export.'
        );
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      });

    return () => controller.abort();
  }, [isOpen, facilityId, zoneId, meterId, sourceScope, startDate, endDate, isDateRangeValid, reloadNonce]);

  const selectedFacility = useMemo(
    () => facilities.find((f) => f.id === facilityId) ?? facilities[0] ?? null,
    [facilities, facilityId]
  );

  const availableMeters = useMemo(() => {
    const scoped = zoneId ? modalMeters.filter((m) => m.zone_id === zoneId) : modalMeters;
    return scoped.map((m) => ({
      id: m.id,
      meterCode: m.meter_code,
      label: `${m.meter_code} — ${m.equipment_name}`,
    }));
  }, [modalMeters, zoneId]);

  const dashboardBounds = getDefaultDateBounds(dashboardTimeWindow, latestTelemetryTimestamp);
  const isSyncedWithDashboard =
    facilityId === (dashboardFacilityId ?? '') &&
    (zoneId || null) === dashboardZoneId &&
    meterId === '' &&
    sourceScope === dashboardSourceScope &&
    startDate === dashboardBounds.startDate &&
    endDate === dashboardBounds.endDate;

  const scopedReadings = useMemo(
    () => filterReadingsBySourceScope(readings, sourceScope),
    [readings, sourceScope]
  );

  const previewRows = useMemo(() => {
    if (!selectedFacility) return [];
    return buildBackendCsvExportRows({
      readings: scopedReadings,
      facility: selectedFacility,
      zones: modalZones,
      meters: modalMeters,
      anomalies: dashboardAnomalies,
    });
  }, [scopedReadings, selectedFacility, modalZones, modalMeters, dashboardAnomalies]);

  const summary = useMemo(() => {
    const totalKwh = Number(
      previewRows.reduce((sum, r) => sum + r.consumptionKwh, 0).toFixed(2)
    );
    const totalMwh = Number((totalKwh / 1000).toFixed(4));
    const peakKw = previewRows.length > 0 ? Math.max(...previewRows.map((r) => r.actualKw)) : 0;
    const anomalyCount = previewRows.filter((r) => r.anomalyFlag === 'ANOMALY').length;
    const facilitySlug = selectedFacility?.code.toLowerCase() ?? 'facility';
    const zoneSlug = zoneId
      ? `-${modalZones.find((z) => z.id === zoneId)?.slug ?? 'zone'}`
      : '';
    const meterSlug = meterId
      ? `-${(modalMeters.find((m) => m.id === meterId)?.meter_code ?? 'meter').toLowerCase()}`
      : '';
    const filename = `energygrid-${facilitySlug}${zoneSlug}${meterSlug}-${startDate}-to-${endDate}.csv`;

    return { totalKwh, totalMwh, peakKw, anomalyCount, filename };
  }, [previewRows, selectedFacility, zoneId, meterId, modalZones, modalMeters, startDate, endDate]);

  if (!isOpen) return null;

  const handleFacilitySelect = (nextFacilityId: string) => {
    setFacilityId(nextFacilityId);
    setZoneId('');
    setMeterId('');
    setExportedMessage(null);
  };

  const handleZoneSelect = (nextZoneId: string) => {
    setZoneId(nextZoneId);
    if (nextZoneId && meterId) {
      const stillValid = modalMeters.some((m) => m.id === meterId && m.zone_id === nextZoneId);
      if (!stillValid) {
        setMeterId('');
      }
    }
    setExportedMessage(null);
  };

  const handleDownload = () => {
    if (previewRows.length === 0) return;
    const csvContent = serializeBackendCsv(previewRows, unitMode);
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.setAttribute('download', summary.filename);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
    setExportedMessage(`Downloaded ${summary.filename} (${previewRows.length} rows)`);
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"
      onClick={(e) => {
        if (e.target === e.currentTarget) {
          onClose();
        }
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="export-csv-dialog-title"
        className="bg-white border border-slate-200 rounded-lg shadow-xl w-full max-w-3xl max-h-[90vh] flex flex-col overflow-hidden"
      >
        {/* Header */}
        <div className="px-5 py-4 border-b border-slate-200 flex items-start justify-between gap-4">
          <div>
            <h2 id="export-csv-dialog-title" className="text-base font-semibold text-slate-900">
              Export Energy Consumption CSV
            </h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Query backend telemetry readings by facility, zone, meter, and UTC date range
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 text-slate-400 hover:text-slate-700 rounded-md hover:bg-slate-100 transition-colors"
            aria-label="Close export dialog"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Body */}
        <div className="p-5 overflow-y-auto space-y-5">
          {/* Filters Grid */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label
                htmlFor="export-facility"
                className="block text-xs font-medium text-slate-700 mb-1.5"
              >
                Facility
              </label>
              <select
                id="export-facility"
                value={facilityId}
                onChange={(e) => handleFacilitySelect(e.target.value)}
                disabled={facilities.length === 0}
                className="w-full px-3 py-2 text-xs bg-white border border-slate-200 rounded-md text-slate-900 focus:outline-none focus:border-sky-600"
              >
                {facilities.map((fac) => (
                  <option key={fac.id} value={fac.id}>
                    {fac.name} ({fac.code})
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label htmlFor="export-zone" className="block text-xs font-medium text-slate-700 mb-1.5">
                Zone
              </label>
              <select
                id="export-zone"
                value={zoneId}
                onChange={(e) => handleZoneSelect(e.target.value)}
                className="w-full px-3 py-2 text-xs bg-white border border-slate-200 rounded-md text-slate-900 focus:outline-none focus:border-sky-600"
              >
                <option value="">All Zones ({modalZones.length})</option>
                {modalZones.map((z) => (
                  <option key={z.id} value={z.id}>
                    {z.name} ({z.primary_meter_code})
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label
                htmlFor="export-meter"
                className="block text-xs font-medium text-slate-700 mb-1.5"
              >
                Meter
              </label>
              <select
                id="export-meter"
                value={meterId}
                onChange={(e) => {
                  setMeterId(e.target.value);
                  setExportedMessage(null);
                }}
                className="w-full px-3 py-2 text-xs bg-white border border-slate-200 rounded-md text-slate-900 focus:outline-none focus:border-sky-600"
              >
                <option value="">All Meters ({availableMeters.length})</option>
                {availableMeters.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.label}
                  </option>
                ))}
              </select>
            </div>

            <div className="grid grid-cols-2 gap-2.5">
              <div>
                <label
                  htmlFor="export-start-date"
                  className="block text-xs font-medium text-slate-700 mb-1.5"
                >
                  Start Date
                </label>
                <input
                  id="export-start-date"
                  type="date"
                  value={startDate}
                  onChange={(e) => {
                    setStartDate(e.target.value);
                    setExportedMessage(null);
                  }}
                  className="w-full px-2.5 py-2 text-xs font-mono tabular-nums bg-white border border-slate-200 rounded-md text-slate-900 focus:outline-none focus:border-sky-600"
                />
              </div>
              <div>
                <label
                  htmlFor="export-end-date"
                  className="block text-xs font-medium text-slate-700 mb-1.5"
                >
                  End Date
                </label>
                <input
                  id="export-end-date"
                  type="date"
                  value={endDate}
                  onChange={(e) => {
                    setEndDate(e.target.value);
                    setExportedMessage(null);
                  }}
                  className="w-full px-2.5 py-2 text-xs font-mono tabular-nums bg-white border border-slate-200 rounded-md text-slate-900 focus:outline-none focus:border-sky-600"
                />
              </div>
            </div>
          </div>

          {/* Unit & Source Selectors */}
          <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
            <div className="flex flex-wrap items-center gap-4">
              <div className="flex items-center gap-2.5">
                <span className="text-xs font-medium text-slate-700">Energy Units</span>
                <SegmentedControl
                  options={
                    [
                      { value: 'both', label: 'kWh & MWh' },
                      { value: 'kwh', label: 'kWh Only' },
                      { value: 'mwh', label: 'MWh Only' },
                    ] as const
                  }
                  value={unitMode}
                  onChange={(next) => {
                    setUnitMode(next);
                    setExportedMessage(null);
                  }}
                  ariaLabel="Select exported energy units"
                />
              </div>

              <div className="flex items-center gap-2.5">
                <span className="text-xs font-medium text-slate-700">Source</span>
                <SegmentedControl
                  options={
                    [
                      { value: 'measured', label: 'Measured' },
                      { value: 'all', label: 'All' },
                      { value: 'simulation', label: 'Sim' },
                    ] as const
                  }
                  value={sourceScope}
                  onChange={(next) => {
                    setSourceScope(next);
                    setExportedMessage(null);
                  }}
                  ariaLabel="Filter exported readings by source"
                />
              </div>
            </div>

            {isSyncedWithDashboard ? (
              <span className="text-xs text-slate-500">
                Synced with active dashboard filters ({dashboardTimeWindow})
              </span>
            ) : (
              <button
                type="button"
                onClick={syncWithDashboard}
                className="inline-flex items-center gap-1.5 text-xs font-medium text-sky-700 hover:text-sky-900 underline whitespace-nowrap"
              >
                <RotateCcw className="w-3.5 h-3.5" aria-hidden="true" />
                Reset to Dashboard Filters
              </button>
            )}
          </div>

          {errorMessage && (
            <div
              role="alert"
              className="px-3.5 py-2.5 rounded-md bg-red-50 border border-red-200 flex items-center justify-between gap-3 text-xs text-red-700"
            >
              <span>{errorMessage}</span>
              <button
                type="button"
                onClick={() => setReloadNonce((n) => n + 1)}
                className="font-medium underline shrink-0"
              >
                Retry
              </button>
            </div>
          )}

          {/* Summary Strip */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 bg-slate-50 border border-slate-200 rounded-md p-3.5">
            <div>
              <div className="text-xs text-slate-500">Total Energy Consumption</div>
              <div className="mt-1 text-sm font-semibold font-mono tabular-nums text-slate-900">
                {summary.totalKwh.toLocaleString(undefined, { maximumFractionDigits: 1 })} kWh
              </div>
              <div className="text-xs font-mono tabular-nums text-slate-600">
                {summary.totalMwh.toFixed(3)} MWh
              </div>
            </div>
            <div>
              <div className="text-xs text-slate-500">Peak Interval Demand</div>
              <div className="mt-1 text-sm font-semibold font-mono tabular-nums text-slate-900">
                {summary.peakKw.toLocaleString()} kW
              </div>
              <div className="text-xs font-mono tabular-nums text-slate-600">
                {summary.anomalyCount} anomalous interval
                {summary.anomalyCount === 1 ? '' : 's'}
              </div>
            </div>
            <div>
              <div className="text-xs text-slate-500">Export Resolution</div>
              <div className="mt-1 text-sm font-semibold font-mono tabular-nums text-slate-900">
                {previewRows.length} rows
              </div>
              <div className="text-xs font-mono tabular-nums text-slate-600">
                {truncated
                  ? `Showing 1,000 of ${totalAvailable} readings`
                  : `${totalAvailable} total matched`}
              </div>
            </div>
          </div>

          {/* Preview Table */}
          {loading ? (
            <div className="border border-slate-200 rounded-md py-8 px-4 flex items-center justify-center gap-2 text-xs text-slate-500">
              <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />
              Fetching telemetry readings from server...
            </div>
          ) : !isDateRangeValid ? (
            <div className="border border-slate-200 rounded-md py-8 px-4 text-center text-xs text-slate-500">
              Invalid date range: Start Date must be on or before End Date.
            </div>
          ) : previewRows.length === 0 ? (
            <div className="border border-slate-200 rounded-md py-8 px-4 text-center text-xs text-slate-500">
              No telemetry readings found for the selected facility, zone, meter, and date range.
            </div>
          ) : (
            <div className="border border-slate-200 rounded-md overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse text-xs">
                  <thead>
                    <tr className="bg-slate-50 border-b border-slate-200 text-slate-500 font-medium">
                      <th className="py-2 px-3">Timestamp</th>
                      <th className="py-2 px-3">Zone</th>
                      <th className="py-2 px-3">Meter</th>
                      <th className="py-2 px-3 text-right">Demand (kW)</th>
                      {unitMode !== 'mwh' && (
                        <th className="py-2 px-3 text-right">Consumption (kWh)</th>
                      )}
                      {unitMode !== 'kwh' && (
                        <th className="py-2 px-3 text-right">Consumption (MWh)</th>
                      )}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {previewRows.slice(0, 5).map((row, idx) => (
                      <tr
                        key={`${row.timestamp}-${row.meterCode}-${idx}`}
                        className="hover:bg-slate-50"
                      >
                        <td className="py-2 px-3 font-mono tabular-nums text-slate-700 whitespace-nowrap">
                          {row.timestamp}
                        </td>
                        <td className="py-2 px-3 text-slate-900 truncate max-w-[180px]">
                          {row.zone}
                        </td>
                        <td className="py-2 px-3 font-mono tabular-nums text-slate-700">
                          {row.meterCode}
                        </td>
                        <td className="py-2 px-3 text-right font-mono tabular-nums text-slate-900">
                          {row.actualKw.toLocaleString()}
                        </td>
                        {unitMode !== 'mwh' && (
                          <td className="py-2 px-3 text-right font-mono tabular-nums font-medium text-slate-900">
                            {row.consumptionKwh.toLocaleString()}
                          </td>
                        )}
                        {unitMode !== 'kwh' && (
                          <td className="py-2 px-3 text-right font-mono tabular-nums font-medium text-slate-900">
                            {row.consumptionMwh.toFixed(4)}
                          </td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {previewRows.length > 5 && (
                <div className="px-3 py-2 bg-slate-50 border-t border-slate-100 text-xs text-slate-500 font-mono tabular-nums">
                  Showing first 5 of {previewRows.length} intervals
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-5 py-3.5 border-t border-slate-200 bg-slate-50 flex flex-wrap items-center justify-between gap-3">
          <div className="text-xs text-slate-600 font-mono truncate max-w-full sm:max-w-[360px]">
            {exportedMessage ?? summary.filename}
          </div>
          <div className="flex items-center gap-2.5 ml-auto">
            <button
              type="button"
              onClick={onClose}
              className="px-3.5 py-2 text-xs font-medium text-slate-700 bg-white border border-slate-200 rounded-md hover:bg-slate-100 transition-colors whitespace-nowrap"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleDownload}
              disabled={loading || previewRows.length === 0 || !isDateRangeValid}
              className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-medium bg-slate-900 text-white rounded-md hover:bg-slate-800 disabled:opacity-50 disabled:cursor-not-allowed transition-colors whitespace-nowrap"
            >
              <Download className="w-3.5 h-3.5" aria-hidden="true" />
              Download CSV
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
