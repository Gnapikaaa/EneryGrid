import React, { useEffect, useMemo, useState } from 'react';
import { AlertOctagon, AlertTriangle, Check, CheckCircle2, Info, Wrench } from 'lucide-react';
import { AnomalyRecord, AnomalySeverity, AnomalyStatus } from '../data/energyData';
import { SegmentedControl } from './SegmentedControl';
import { fetchAnomalies, ApiAnomalyResponse } from '../api/energy';
import { getStoredAccessToken } from '../api/client';

/** Map a backend AnomalyResponse to the frontend AnomalyRecord shape. */
function mapApiAnomaly(a: ApiAnomalyResponse): AnomalyRecord {
  const actualKw = parseFloat(a.actual_kw);
  const expectedKw = parseFloat(a.expected_kw);

  return {
    id: a.event_code,
    pointId: a.event_code,
    timestamp: new Date(a.detected_at).toLocaleString(),
    meterCode: a.meter_id.slice(0, 8), // UUID short ref until zone name is available
    zone: a.zone_id.slice(0, 8),       // UUID short ref; a full zones fetch would map this
    severity: a.severity,
    zScore: parseFloat(a.z_score),
    actualKw,
    expectedKw,
    deviationPct: Math.round(parseFloat(a.deviation_pct)),
    durationMin: a.duration_min,
    estimatedWasteKwh: parseFloat(a.estimated_waste_kwh),
    estimatedCostUsd: a.estimated_cost != null ? parseFloat(a.estimated_cost) : 0,
    signature: a.signature,
    recommendation: a.recommendation,
    status: a.status,
    // Use real waveform arrays stored by the backend during detection/reconciliation.
    waveform: Array.isArray(a.waveform) ? a.waveform.map(Number) : [actualKw],
    baselineWaveform: Array.isArray(a.baseline_waveform)
      ? a.baseline_waveform.map(Number)
      : [expectedKw],
  };
}

interface AnomalyTableProps {
  anomalies: AnomalyRecord[];
  sigmaThreshold: number;
  onSigmaChange: (sigma: number) => void;
  selectedAnomalyId: string | null;
  onSelectAnomaly: (anomaly: AnomalyRecord | null) => void;
  onUpdateStatus: (anomalyId: string, status: AnomalyStatus) => void;
  scopeLabel?: string;
  /** If provided, attempt to fetch live anomalies from the API for this facility */
  facilityId?: string;
}

export const AnomalyTable: React.FC<AnomalyTableProps> = ({
  anomalies: mockAnomalies,
  sigmaThreshold,
  onSigmaChange,
  selectedAnomalyId,
  onSelectAnomaly,
  onUpdateStatus,
  scopeLabel,
  facilityId,
}) => {
  const [severityFilter, setSeverityFilter] = useState<'All' | AnomalySeverity>('All');
  const [statusFilter, setStatusFilter] = useState<'All' | 'Active' | 'Resolved'>('All');
  // Live API data — null means "not yet fetched / fetch failed"
  const [liveAnomalies, setLiveAnomalies] = useState<AnomalyRecord[] | null>(null);

  useEffect(() => {
    setLiveAnomalies(null);
    if (!facilityId || !getStoredAccessToken()) return;
    let cancelled = false;
    fetchAnomalies(facilityId, 100)
      .then((resp) => {
        if (!cancelled && resp.items.length > 0) {
          setLiveAnomalies(resp.items.map(mapApiAnomaly));
        }
      })
      .catch(() => {
        // API unavailable — fall through to mock data silently
      });
    return () => {
      cancelled = true;
    };
  }, [facilityId]);

  // Prefer live data; fall back to mock data passed from parent
  const anomalies = liveAnomalies ?? mockAnomalies;

  const filteredAnomalies = useMemo(() => {
    return anomalies.filter((item) => {
      if (severityFilter !== 'All' && item.severity !== severityFilter) return false;
      if (statusFilter === 'Active' && item.status === 'Resolved') return false;
      if (statusFilter === 'Resolved' && item.status !== 'Resolved') return false;
      return true;
    });
  }, [anomalies, severityFilter, statusFilter]);

  const activeDetail = useMemo(
    () =>
      filteredAnomalies.find((a) => a.id === selectedAnomalyId) ?? filteredAnomalies[0] ?? null,
    [selectedAnomalyId, filteredAnomalies]
  );

  const renderSeverity = (severity: AnomalySeverity) => {
    if (severity === 'Critical') {
      return (
        <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-red-700">
          <AlertOctagon className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />
          Critical
        </span>
      );
    }
    if (severity === 'High') {
      return (
        <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-amber-700">
          <AlertTriangle className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />
          High
        </span>
      );
    }
    return (
      <span className="inline-flex items-center gap-1.5 text-xs font-medium text-sky-700">
        <Info className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />
        Elevated
      </span>
    );
  };

  return (
    <div className="space-y-5">
      <div className="bg-white border border-slate-200 rounded-lg p-5">
        {/* Controls Header */}
        <div className="flex flex-wrap items-center justify-between gap-4 pb-4 border-b border-slate-100">
          <div>
            <h2 className="text-base font-semibold text-slate-900">
              Statistical Anomaly Detection Queue{scopeLabel ? ` · ${scopeLabel}` : ''}
            </h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Intervals exceeding rolling Z-score threshold ({sigmaThreshold.toFixed(1)}σ)
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3 sm:gap-4">
            <label className="flex items-center gap-2.5 text-xs text-slate-700">
              <span className="font-medium whitespace-nowrap">Sensitivity:</span>
              <input
                type="range"
                min={1.5}
                max={3.5}
                step={0.1}
                value={sigmaThreshold}
                onChange={(e) => onSigmaChange(parseFloat(e.target.value))}
                className="w-28 accent-sky-700 cursor-pointer"
                aria-label="Z-score sensitivity threshold"
              />
              <span className="font-mono tabular-nums font-semibold text-slate-900 w-10">
                {sigmaThreshold.toFixed(1)}σ
              </span>
            </label>

            <SegmentedControl
              options={['All', 'Critical', 'High', 'Elevated'] as const}
              value={severityFilter}
              onChange={setSeverityFilter}
              ariaLabel="Filter anomalies by severity"
            />

            <SegmentedControl
              options={['All', 'Active', 'Resolved'] as const}
              value={statusFilter}
              onChange={setStatusFilter}
              ariaLabel="Filter anomalies by workflow status"
            />
          </div>
        </div>

        {/* Table */}
        {filteredAnomalies.length === 0 ? (
          <div className="py-12 text-center">
            <CheckCircle2 className="w-8 h-8 text-emerald-600 mx-auto mb-2" aria-hidden="true" />
            <p className="text-sm font-medium text-slate-900">
              No anomalies detected at {sigmaThreshold.toFixed(1)}σ threshold
            </p>
            <p className="text-xs text-slate-500 mt-1">
              Lower the sensitivity slider or inject a test spike from the toolbar to evaluate alerting.
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto mt-2">
            <table className="w-full text-left border-collapse min-w-[780px]">
              <thead>
                <tr className="border-b border-slate-200 text-xs font-medium text-slate-500">
                  <th className="py-2.5 pr-3">Event</th>
                  <th className="py-2.5 px-3">Severity</th>
                  <th className="py-2.5 px-3">Timestamp</th>
                  <th className="py-2.5 px-3">Meter / Zone</th>
                  <th className="py-2.5 px-3 text-right">Actual vs Exp</th>
                  <th className="py-2.5 px-3 text-right">Z-Score</th>
                  <th className="py-2.5 px-3 text-right">Est. Waste</th>
                  <th className="py-2.5 pl-3 text-right">Workflow</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-sm">
                {filteredAnomalies.map((item) => {
                  const isSelected = activeDetail?.id === item.id;
                  return (
                    <tr
                      key={item.id}
                      tabIndex={0}
                      onClick={() => onSelectAnomaly(item)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault();
                          onSelectAnomaly(item);
                        }
                      }}
                      className={`cursor-pointer transition-colors focus-visible:outline-2 focus-visible:outline-sky-600 ${
                        isSelected ? 'bg-sky-50/70' : 'hover:bg-slate-50'
                      }`}
                    >
                      <td className="py-2.5 pr-3 font-mono tabular-nums text-xs font-medium text-slate-900">
                        {item.id}
                      </td>
                      <td className="py-2.5 px-3">{renderSeverity(item.severity)}</td>
                      <td className="py-2.5 px-3 font-mono tabular-nums text-xs text-slate-600">
                        {item.timestamp}
                      </td>
                      <td className="py-2.5 px-3">
                        <div className="text-xs font-medium text-slate-900">{item.zone}</div>
                        <div className="text-[11px] font-mono text-slate-500">{item.meterCode}</div>
                      </td>
                      <td className="py-2.5 px-3 text-right font-mono tabular-nums text-xs">
                        <span className="font-semibold text-slate-900">
                          {item.actualKw.toLocaleString()}
                        </span>{' '}
                        <span className="text-slate-400">/ {item.expectedKw.toLocaleString()} kW</span>
                        <div className="text-[11px] text-red-600">+{item.deviationPct}%</div>
                      </td>
                      <td className="py-2.5 px-3 text-right font-mono tabular-nums text-xs font-semibold text-slate-900">
                        {item.zScore.toFixed(2)}σ
                      </td>
                      <td className="py-2.5 px-3 text-right font-mono tabular-nums text-xs">
                        <div className="text-slate-900 font-medium">
                          {item.estimatedWasteKwh.toLocaleString()} kWh
                        </div>
                        <div className="text-[11px] text-slate-500">
                          ${item.estimatedCostUsd.toFixed(2)}
                        </div>
                      </td>
                      <td
                        className="py-2.5 pl-3 text-right"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <div className="inline-flex items-center gap-1.5">
                          <span className="text-xs text-slate-600 mr-1">{item.status}</span>
                          {item.status === 'Open' && (
                            <button
                              type="button"
                              onClick={() => onUpdateStatus(item.id, 'Acknowledged')}
                              className="px-2 py-1 text-xs font-medium text-slate-700 border border-slate-200 rounded hover:bg-slate-100 whitespace-nowrap"
                            >
                              Acknowledge
                            </button>
                          )}
                          {item.status !== 'Assigned' && item.status !== 'Resolved' && (
                            <button
                              type="button"
                              onClick={() => onUpdateStatus(item.id, 'Assigned')}
                              className="inline-flex items-center gap-1 px-2 py-1 text-xs font-medium text-sky-700 border border-sky-200 rounded hover:bg-sky-50 whitespace-nowrap"
                            >
                              <Wrench className="w-3 h-3" aria-hidden="true" />
                              Assign
                            </button>
                          )}
                          {item.status !== 'Resolved' && (
                            <button
                              type="button"
                              onClick={() => onUpdateStatus(item.id, 'Resolved')}
                              className="inline-flex items-center gap-1 px-2 py-1 text-xs font-medium text-emerald-700 border border-emerald-200 rounded hover:bg-emerald-50 whitespace-nowrap"
                            >
                              <Check className="w-3 h-3" aria-hidden="true" />
                              Resolve
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Anomaly Diagnostic Inspection Panel */}
      {activeDetail && (
        <div className="bg-white border border-slate-200 rounded-lg p-5">
          <div className="flex flex-wrap items-start justify-between gap-4 pb-4 border-b border-slate-100">
            <div>
              <div className="flex items-center gap-2 text-xs text-slate-500">
                <span className="font-mono tabular-nums font-semibold text-slate-900">
                  {activeDetail.id}
                </span>
                <span aria-hidden="true">·</span>
                <span>{activeDetail.meterCode}</span>
                <span aria-hidden="true">·</span>
                <span>{activeDetail.timestamp}</span>
              </div>
              <h3 className="text-base font-semibold text-slate-900 mt-1">
                {activeDetail.signature}
              </h3>
            </div>
            {renderSeverity(activeDetail.severity)}
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 pt-4 items-center">
            <div className="lg:col-span-7">
              <div className="text-xs font-medium text-slate-600 mb-2">
                Isolated 12-Sample Interval Waveform (Actual vs Expected Baseline)
              </div>
              <WaveformMiniChart
                actual={activeDetail.waveform}
                baseline={activeDetail.baselineWaveform}
              />
            </div>
            <div className="lg:col-span-5 space-y-3 text-sm">
              <div className="grid grid-cols-2 gap-3 pb-3 border-b border-slate-100 font-mono tabular-nums">
                <div>
                  <div className="text-xs font-sans text-slate-500">Peak Excursion</div>
                  <div className="text-base font-semibold text-slate-900">
                    +{activeDetail.deviationPct}% ({activeDetail.actualKw.toLocaleString()} kW)
                  </div>
                </div>
                <div>
                  <div className="text-xs font-sans text-slate-500">Duration / Cost</div>
                  <div className="text-base font-semibold text-slate-900">
                    {activeDetail.durationMin}m · ${activeDetail.estimatedCostUsd.toFixed(2)}
                  </div>
                </div>
              </div>
              <div>
                <div className="text-xs font-medium text-slate-500 mb-1">
                  Recommended Engineering Action
                </div>
                <p className="text-sm text-slate-700 leading-relaxed">
                  {activeDetail.recommendation}
                </p>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

const WaveformMiniChart: React.FC<{ actual: number[]; baseline: number[] }> = ({
  actual,
  baseline,
}) => {
  const width = 460;
  const height = 130;
  const pad = 16;
  const max = Math.max(...actual, ...baseline) * 1.06;
  const min = Math.min(...actual, ...baseline) * 0.92;
  const range = Math.max(1, max - min);

  const toPoints = (arr: number[]) =>
    arr
      .map((val, idx) => {
        const x = pad + (idx / Math.max(1, arr.length - 1)) * (width - pad * 2);
        const y = pad + (height - pad * 2) - ((val - min) / range) * (height - pad * 2);
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(' ');

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="w-full h-auto bg-slate-50 border border-slate-200 rounded-md"
      role="img"
      aria-label="Isolated anomaly waveform comparison"
    >
      <polyline
        fill="none"
        stroke="#64748B"
        strokeWidth={1.5}
        strokeDasharray="4 3"
        points={toPoints(baseline)}
      />
      <polyline fill="none" stroke="#DC2626" strokeWidth={2.25} points={toPoints(actual)} />
    </svg>
  );
};
