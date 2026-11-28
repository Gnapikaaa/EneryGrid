import React, { useEffect, useMemo, useState } from 'react';
import { Download, RotateCcw, X } from 'lucide-react';
import {
  AnomalyStatus,
  EnergyUnitMode,
  FACILITIES,
  FacilityId,
  FacilityProfile,
  TELEMETRY_MAX_DATE,
  TELEMETRY_MIN_DATE,
  TimeWindow,
  exportConsumptionCsv,
  getAvailableMetersForFilter,
  getFilteredConsumptionData,
  getTimeWindowDateBounds,
} from '../data/energyData';
import { SegmentedControl } from './SegmentedControl';

interface ExportCsvModalProps {
  isOpen: boolean;
  onClose: () => void;
  dashboardFacilityId: FacilityId;
  dashboardZoneId: string | null;
  dashboardTimeWindow: TimeWindow;
  dashboardSigmaThreshold: number;
  dashboardInjectedSpikeKw: number;
  dashboardAnomalyStatuses: Record<string, AnomalyStatus>;
  /** Live facilities merged from the API — when provided, the facility selector uses these instead of mock-only data */
  facilitiesMap?: Record<string, FacilityProfile>;
}

export const ExportCsvModal: React.FC<ExportCsvModalProps> = ({
  isOpen,
  onClose,
  dashboardFacilityId,
  dashboardZoneId,
  dashboardTimeWindow,
  dashboardSigmaThreshold,
  dashboardInjectedSpikeKw,
  dashboardAnomalyStatuses,
  facilitiesMap,
}) => {
  const [facilityId, setFacilityId] = useState<FacilityId>(dashboardFacilityId);
  const [zoneId, setZoneId] = useState<string>(dashboardZoneId ?? '');
  const [meterCode, setMeterCode] = useState<string>('');
  const [startDate, setStartDate] = useState<string>(
    () => getTimeWindowDateBounds(dashboardTimeWindow).startDate
  );
  const [endDate, setEndDate] = useState<string>(
    () => getTimeWindowDateBounds(dashboardTimeWindow).endDate
  );
  const [unitMode, setUnitMode] = useState<EnergyUnitMode>('both');
  const [exportedMessage, setExportedMessage] = useState<string | null>(null);

  const syncWithDashboard = () => {
    const bounds = getTimeWindowDateBounds(dashboardTimeWindow);
    setFacilityId(dashboardFacilityId);
    setZoneId(dashboardZoneId ?? '');
    setMeterCode('');
    setStartDate(bounds.startDate);
    setEndDate(bounds.endDate);
    setUnitMode('both');
    setExportedMessage(null);
  };

  useEffect(() => {
    if (isOpen) {
      syncWithDashboard();
    }
  }, [isOpen, dashboardFacilityId, dashboardZoneId, dashboardTimeWindow]);

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

  // Use the merged live+mock facilities map for the selector; fall back to static FACILITIES.
  const resolvedFacilitiesMap = facilitiesMap ?? FACILITIES;
  const selectedFacility = resolvedFacilitiesMap[facilityId] ?? FACILITIES[facilityId];
  const selectedZone = useMemo(
    () => selectedFacility.zones.find((z) => z.id === zoneId) ?? null,
    [selectedFacility, zoneId]
  );

  const availableMeters = useMemo(() => {
    const meters = getAvailableMetersForFilter(selectedFacility, zoneId || null);
    if (meters.length > 0) {
      return meters.map((m) => ({
        meterCode: m.meterCode,
        label: `${m.meterCode} — ${m.equipmentName}`,
      }));
    }
    if (selectedZone) {
      return [
        {
          meterCode: selectedZone.meterCode,
          label: `${selectedZone.meterCode} — ${selectedZone.name}`,
        },
      ];
    }
    return [];
  }, [selectedFacility, zoneId, selectedZone]);

  const dashboardBounds = getTimeWindowDateBounds(dashboardTimeWindow);
  const isSyncedWithDashboard =
    facilityId === dashboardFacilityId &&
    (zoneId || null) === dashboardZoneId &&
    meterCode === '' &&
    startDate === dashboardBounds.startDate &&
    endDate === dashboardBounds.endDate;

  const isMatchingDashboardScope =
    facilityId === dashboardFacilityId && (zoneId || null) === dashboardZoneId;

  const exportFilters = useMemo(
    () => ({
      facilityId,
      zoneId: zoneId || null,
      meterCode: meterCode || null,
      startDate,
      endDate,
      timeWindow: dashboardTimeWindow,
      injectedSpikeKw: isMatchingDashboardScope ? dashboardInjectedSpikeKw : 0,
      sigmaThreshold: dashboardSigmaThreshold,
      anomalyStatuses: dashboardAnomalyStatuses,
    }),
    [
      facilityId,
      zoneId,
      meterCode,
      startDate,
      endDate,
      dashboardTimeWindow,
      isMatchingDashboardScope,
      dashboardInjectedSpikeKw,
      dashboardSigmaThreshold,
      dashboardAnomalyStatuses,
    ]
  );

  const previewData = useMemo(
    () => getFilteredConsumptionData(exportFilters),
    [exportFilters]
  );

  if (!isOpen) return null;

  const handleFacilitySelect = (nextFacilityId: FacilityId) => {
    setFacilityId(nextFacilityId);
    setZoneId('');
    setMeterCode('');
    setExportedMessage(null);
  };

  const handleZoneSelect = (nextZoneId: string) => {
    setZoneId(nextZoneId);
    if (nextZoneId && meterCode) {
      const nextMeters = getAvailableMetersForFilter(selectedFacility, nextZoneId);
      const nextZoneObj = selectedFacility.zones.find((z) => z.id === nextZoneId);
      const meterStillValid =
        nextMeters.some((m) => m.meterCode === meterCode) ||
        (nextMeters.length === 0 && nextZoneObj?.meterCode === meterCode);
      if (!meterStillValid) {
        setMeterCode('');
      }
    }
    setExportedMessage(null);
  };

  const handleDownload = () => {
    if (previewData.rows.length === 0) return;
    const result = exportConsumptionCsv(exportFilters, unitMode);
    setExportedMessage(`Downloaded ${result.filename} (${result.rows.length} rows)`);
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
              Filter by facility, zone, meter, and date range with verified kWh and MWh totals
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
                onChange={(e) => handleFacilitySelect(e.target.value as FacilityId)}
                className="w-full px-3 py-2 text-xs bg-white border border-slate-200 rounded-md text-slate-900 focus:outline-none focus:border-sky-600"
              >
                {Object.values(resolvedFacilitiesMap).map((fac) => (
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
                <option value="">All Zones ({selectedFacility.zones.length})</option>
                {selectedFacility.zones.map((z) => (
                  <option key={z.id} value={z.id}>
                    {z.name} ({z.meterCode})
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
                value={meterCode}
                onChange={(e) => {
                  setMeterCode(e.target.value);
                  setExportedMessage(null);
                }}
                className="w-full px-3 py-2 text-xs bg-white border border-slate-200 rounded-md text-slate-900 focus:outline-none focus:border-sky-600"
              >
                <option value="">All Meters ({availableMeters.length})</option>
                {availableMeters.map((m) => (
                  <option key={m.meterCode} value={m.meterCode}>
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
                  min={TELEMETRY_MIN_DATE}
                  max={TELEMETRY_MAX_DATE}
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
                  min={TELEMETRY_MIN_DATE}
                  max={TELEMETRY_MAX_DATE}
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

          {/* Unit Selector & Sync Bar */}
          <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
            <div className="flex items-center gap-3">
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

          {/* Summary Strip */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 bg-slate-50 border border-slate-200 rounded-md p-3.5">
            <div>
              <div className="text-xs text-slate-500">Total Energy Consumption</div>
              <div className="mt-1 text-sm font-semibold font-mono tabular-nums text-slate-900">
                {previewData.totalKwh.toLocaleString(undefined, { maximumFractionDigits: 1 })} kWh
              </div>
              <div className="text-xs font-mono tabular-nums text-slate-600">
                {previewData.totalMwh.toFixed(3)} MWh
              </div>
            </div>
            <div>
              <div className="text-xs text-slate-500">Peak Interval Demand</div>
              <div className="mt-1 text-sm font-semibold font-mono tabular-nums text-slate-900">
                {previewData.peakKw.toLocaleString()} kW
              </div>
              <div className="text-xs font-mono tabular-nums text-slate-600">
                {previewData.anomalyCount} anomalous interval
                {previewData.anomalyCount === 1 ? '' : 's'}
              </div>
            </div>
            <div>
              <div className="text-xs text-slate-500">Export Resolution</div>
              <div className="mt-1 text-sm font-semibold font-mono tabular-nums text-slate-900">
                {previewData.rows.length} rows
              </div>
              <div className="text-xs font-mono tabular-nums text-slate-600">
                {previewData.intervalHours}h interval ({previewData.effectiveWindow})
              </div>
            </div>
          </div>

          {/* Preview Table */}
          {previewData.rows.length === 0 ? (
            <div className="border border-slate-200 rounded-md py-8 px-4 text-center text-xs text-slate-500">
              No consumption intervals match the selected date range and filters. Verify that Start
              Date is on or before End Date within {TELEMETRY_MIN_DATE} to {TELEMETRY_MAX_DATE}.
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
                    {previewData.rows.slice(0, 5).map((row) => (
                      <tr key={`${row.timestamp}-${row.meterCode}`} className="hover:bg-slate-50">
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
              {previewData.rows.length > 5 && (
                <div className="px-3 py-2 bg-slate-50 border-t border-slate-100 text-xs text-slate-500 font-mono tabular-nums">
                  Showing first 5 of {previewData.rows.length} intervals
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-5 py-3.5 border-t border-slate-200 bg-slate-50 flex flex-wrap items-center justify-between gap-3">
          <div className="text-xs text-slate-600 font-mono truncate max-w-full sm:max-w-[360px]">
            {exportedMessage ?? previewData.filename}
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
              disabled={previewData.rows.length === 0}
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
