import React, { useMemo, useState } from 'react';
import {
  AlertOctagon,
  AlertTriangle,
  Check,
  CheckCircle2,
  History,
  Info,
  RotateCcw,
  Wrench,
} from 'lucide-react';
import {
  AnomalySeverity,
  AnomalyStatus,
  AnomalyWorkflowLogResponse,
  AuthUser,
} from '../types/api';
import {
  MappedAnomaly,
  formatCurrency,
  formatTimestampInZone,
  getCostEstimateStatusLabel,
} from '../utils/energyMappers';
import { SegmentedControl } from './SegmentedControl';

type PendingWorkflowAction = 'assign' | 'resolve' | 'reopen';

interface AnomalyTableProps {
  anomalies: MappedAnomaly[];
  currencyCode: string;
  timeZone?: string;
  sigmaThreshold: number;
  onSigmaChange: (sigma: number) => void;
  selectedAnomalyId: string | null;
  selectedAnomalyDetail: MappedAnomaly | null;
  selectedAnomalyHistory: AnomalyWorkflowLogResponse[];
  detailLoading?: boolean;
  loading?: boolean;
  canOperate: boolean;
  users?: AuthUser[];
  actionLoadingId?: string | null;
  actionError?: string | null;
  onSelectAnomaly: (anomaly: MappedAnomaly | null) => void;
  onAcknowledge: (anomalyId: string, note?: string | null) => Promise<void> | void;
  onInvestigate: (
    anomalyId: string,
    assignedToUserId?: string | null,
    note?: string | null
  ) => Promise<void> | void;
  onResolve: (anomalyId: string, note: string) => Promise<void> | void;
  onReopen: (anomalyId: string, note: string) => Promise<void> | void;
  scopeLabel?: string;
}

export const AnomalyTable: React.FC<AnomalyTableProps> = ({
  anomalies,
  currencyCode,
  timeZone = 'UTC',
  sigmaThreshold,
  onSigmaChange,
  selectedAnomalyId,
  selectedAnomalyDetail,
  selectedAnomalyHistory,
  detailLoading = false,
  loading = false,
  canOperate,
  users = [],
  actionLoadingId = null,
  actionError = null,
  onSelectAnomaly,
  onAcknowledge,
  onInvestigate,
  onResolve,
  onReopen,
  scopeLabel,
}) => {
  const [severityFilter, setSeverityFilter] = useState<'All' | AnomalySeverity>('All');
  const [statusFilter, setStatusFilter] = useState<'All' | 'Active' | 'Resolved'>('All');
  const [pendingAction, setPendingAction] = useState<{
    anomalyId: string;
    type: PendingWorkflowAction;
  } | null>(null);
  const [noteInput, setNoteInput] = useState('');
  const [assigneeInput, setAssigneeInput] = useState('');
  const [formError, setFormError] = useState<string | null>(null);

  const filteredAnomalies = useMemo(() => {
    return anomalies.filter((item) => {
      if (item.zScore < sigmaThreshold) return false;
      if (severityFilter !== 'All' && item.severity !== severityFilter) return false;
      if (statusFilter === 'Active' && item.status === 'Resolved') return false;
      if (statusFilter === 'Resolved' && item.status !== 'Resolved') return false;
      return true;
    });
  }, [anomalies, sigmaThreshold, severityFilter, statusFilter]);

  const activeRow = useMemo(
    () =>
      filteredAnomalies.find((a) => a.id === selectedAnomalyId) ?? filteredAnomalies[0] ?? null,
    [selectedAnomalyId, filteredAnomalies]
  );

  const activeDetail =
    activeRow && selectedAnomalyDetail && selectedAnomalyDetail.id === activeRow.id
      ? selectedAnomalyDetail
      : activeRow;

  const userNameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const u of users) {
      map.set(u.id, `${u.full_name} (${u.role})`);
    }
    return map;
  }, [users]);

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

  const renderCostCell = (item: MappedAnomaly) => {
    if (item.estimatedCost !== null && item.costEstimateStatus === 'available') {
      return formatCurrency(item.estimatedCost, currencyCode, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      });
    }
    if (item.estimatedCost !== null) {
      return `${formatCurrency(item.estimatedCost, currencyCode, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      })} (${getCostEstimateStatusLabel(item.costEstimateStatus)})`;
    }
    return getCostEstimateStatusLabel(item.costEstimateStatus) || 'Unavailable';
  };

  const openPendingAction = (anomaly: MappedAnomaly, type: PendingWorkflowAction) => {
    onSelectAnomaly(anomaly);
    setPendingAction({ anomalyId: anomaly.id, type });
    setNoteInput('');
    setAssigneeInput(anomaly.assignedToUserId ?? '');
    setFormError(null);
  };

  const handleSubmitPendingAction = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!pendingAction) return;

    const trimmedNote = noteInput.trim();
    if (
      (pendingAction.type === 'resolve' || pendingAction.type === 'reopen') &&
      trimmedNote.length === 0
    ) {
      setFormError(
        pendingAction.type === 'resolve'
          ? 'A resolution note is required to close this anomaly.'
          : 'A reason note is required to reopen this anomaly.'
      );
      return;
    }

    setFormError(null);
    if (pendingAction.type === 'assign') {
      await onInvestigate(
        pendingAction.anomalyId,
        assigneeInput.trim() || null,
        trimmedNote || null
      );
    } else if (pendingAction.type === 'resolve') {
      await onResolve(pendingAction.anomalyId, trimmedNote);
    } else {
      await onReopen(pendingAction.anomalyId, trimmedNote);
    }
    setPendingAction(null);
    setNoteInput('');
  };

  const formatStatusBadge = (status: AnomalyStatus) => {
    if (status === 'Resolved') return 'text-emerald-700 font-medium';
    if (status === 'Assigned') return 'text-sky-700 font-medium';
    if (status === 'Acknowledged') return 'text-amber-700 font-medium';
    return 'text-slate-600';
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

        {actionError && (
          <div
            role="alert"
            className="mt-3 px-3 py-2 rounded-md bg-red-50 border border-red-200 text-xs text-red-700"
          >
            {actionError}
          </div>
        )}

        {/* Table */}
        {loading && anomalies.length === 0 ? (
          <div className="py-12 text-center text-xs text-slate-500">
            Loading detected anomalies...
          </div>
        ) : filteredAnomalies.length === 0 ? (
          <div className="py-12 text-center">
            <CheckCircle2 className="w-8 h-8 text-emerald-600 mx-auto mb-2" aria-hidden="true" />
            <p className="text-sm font-medium text-slate-900">
              No anomalies detected at {sigmaThreshold.toFixed(1)}σ threshold
            </p>
            <p className="text-xs text-slate-500 mt-1">
              Lower the sensitivity slider or ingest telemetry intervals and run analytics to evaluate excursions.
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
                  const isBusy = actionLoadingId === item.id;
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
                        {item.eventCode}
                      </td>
                      <td className="py-2.5 px-3">{renderSeverity(item.severity)}</td>
                      <td className="py-2.5 px-3 font-mono tabular-nums text-xs text-slate-600 whitespace-nowrap">
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
                        <div className="text-[11px] text-slate-500">{renderCostCell(item)}</div>
                      </td>
                      <td
                        className="py-2.5 pl-3 text-right"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <div className="inline-flex items-center gap-1.5">
                          <span className={`text-xs mr-1 ${formatStatusBadge(item.status)}`}>
                            {item.status}
                          </span>
                          {canOperate && item.status === 'Open' && (
                            <button
                              type="button"
                              disabled={isBusy}
                              onClick={() => void onAcknowledge(item.id, null)}
                              className="px-2 py-1 text-xs font-medium text-slate-700 border border-slate-200 rounded hover:bg-slate-100 disabled:opacity-50 whitespace-nowrap"
                            >
                              Acknowledge
                            </button>
                          )}
                          {canOperate &&
                            item.status !== 'Assigned' &&
                            item.status !== 'Resolved' && (
                              <button
                                type="button"
                                disabled={isBusy}
                                onClick={() => openPendingAction(item, 'assign')}
                                className="inline-flex items-center gap-1 px-2 py-1 text-xs font-medium text-sky-700 border border-sky-200 rounded hover:bg-sky-50 disabled:opacity-50 whitespace-nowrap"
                              >
                                <Wrench className="w-3 h-3" aria-hidden="true" />
                                Assign
                              </button>
                            )}
                          {canOperate && item.status !== 'Resolved' && (
                            <button
                              type="button"
                              disabled={isBusy}
                              onClick={() => openPendingAction(item, 'resolve')}
                              className="inline-flex items-center gap-1 px-2 py-1 text-xs font-medium text-emerald-700 border border-emerald-200 rounded hover:bg-emerald-50 disabled:opacity-50 whitespace-nowrap"
                            >
                              <Check className="w-3 h-3" aria-hidden="true" />
                              Resolve
                            </button>
                          )}
                          {canOperate && item.status === 'Resolved' && (
                            <button
                              type="button"
                              disabled={isBusy}
                              onClick={() => openPendingAction(item, 'reopen')}
                              className="inline-flex items-center gap-1 px-2 py-1 text-xs font-medium text-amber-700 border border-amber-200 rounded hover:bg-amber-50 disabled:opacity-50 whitespace-nowrap"
                            >
                              <RotateCcw className="w-3 h-3" aria-hidden="true" />
                              Reopen
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

      {/* Inline Workflow Action Form (Assign / Resolve / Reopen) */}
      {canOperate && pendingAction && activeDetail && pendingAction.anomalyId === activeDetail.id && (
        <form
          onSubmit={handleSubmitPendingAction}
          aria-label="Anomaly workflow action form"
          className="bg-white border border-sky-200 rounded-lg p-4 space-y-3"
        >
          <div className="flex items-center justify-between gap-3">
            <div className="text-xs font-semibold text-slate-900">
              {pendingAction.type === 'assign'
                ? `Assign Investigation · ${activeDetail.eventCode}`
                : pendingAction.type === 'resolve'
                  ? `Resolve Anomaly · ${activeDetail.eventCode}`
                  : `Reopen Anomaly · ${activeDetail.eventCode}`}
            </div>
            <button
              type="button"
              onClick={() => {
                setPendingAction(null);
                setFormError(null);
              }}
              className="text-xs text-slate-500 hover:text-slate-800"
            >
              Cancel
            </button>
          </div>

          {pendingAction.type === 'assign' && users.length > 0 && (
            <div>
              <label
                htmlFor="anomaly-assignee-select"
                className="block text-xs font-medium text-slate-700 mb-1"
              >
                Assign To (Optional)
              </label>
              <select
                id="anomaly-assignee-select"
                value={assigneeInput}
                onChange={(e) => setAssigneeInput(e.target.value)}
                className="w-full sm:w-80 px-2.5 py-1.5 text-xs bg-white border border-slate-200 rounded-md text-slate-900 focus:outline-none focus:border-sky-600"
              >
                <option value="">Unassigned (Investigating)</option>
                {users
                  .filter((u) => u.is_active && (u.role === 'admin' || u.role === 'utility_engineer'))
                  .map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.full_name} ({u.role})
                    </option>
                  ))}
              </select>
            </div>
          )}

          <div>
            <label
              htmlFor="anomaly-workflow-note"
              className="block text-xs font-medium text-slate-700 mb-1"
            >
              {pendingAction.type === 'resolve'
                ? 'Resolution Note (Required)'
                : pendingAction.type === 'reopen'
                  ? 'Reopen Reason (Required)'
                  : 'Investigation Note (Optional)'}
            </label>
            <textarea
              id="anomaly-workflow-note"
              rows={2}
              value={noteInput}
              onChange={(e) => {
                setNoteInput(e.target.value);
                if (formError) setFormError(null);
              }}
              placeholder={
                pendingAction.type === 'resolve'
                  ? 'Describe corrective action taken and root cause verified...'
                  : pendingAction.type === 'reopen'
                    ? 'Explain why this incident requires further investigation...'
                    : 'Optional diagnostic note for investigation...'
              }
              className="w-full px-3 py-2 text-xs bg-white border border-slate-200 rounded-md text-slate-900 focus:outline-none focus:border-sky-600"
            />
            {formError && (
              <p role="alert" className="text-xs text-red-600 mt-1">
                {formError}
              </p>
            )}
          </div>

          <div className="flex justify-end gap-2">
            <button
              type="submit"
              disabled={actionLoadingId === pendingAction.anomalyId}
              className="px-3.5 py-1.5 text-xs font-medium bg-slate-900 text-white rounded-md hover:bg-slate-800 disabled:opacity-50"
            >
              {actionLoadingId === pendingAction.anomalyId
                ? 'Submitting...'
                : pendingAction.type === 'assign'
                  ? 'Confirm Assignment'
                  : pendingAction.type === 'resolve'
                    ? 'Confirm Resolution'
                    : 'Confirm Reopen'}
            </button>
          </div>
        </form>
      )}

      {/* Anomaly Diagnostic Inspection Panel */}
      {activeDetail && (
        <div className="bg-white border border-slate-200 rounded-lg p-5">
          <div className="flex flex-wrap items-start justify-between gap-4 pb-4 border-b border-slate-100">
            <div>
              <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                <span className="font-mono tabular-nums font-semibold text-slate-900">
                  {activeDetail.eventCode}
                </span>
                <span aria-hidden="true">·</span>
                <span>{activeDetail.meterCode}</span>
                <span aria-hidden="true">·</span>
                <span>{activeDetail.timestamp}</span>
                {activeDetail.assignedToUserId && (
                  <>
                    <span aria-hidden="true">·</span>
                    <span className="text-sky-700 font-medium">
                      Assigned:{' '}
                      {userNameById.get(activeDetail.assignedToUserId) ??
                        activeDetail.assignedToUserId}
                    </span>
                  </>
                )}
              </div>
              <h3 className="text-base font-semibold text-slate-900 mt-1">
                {activeDetail.signature}
              </h3>
            </div>
            {renderSeverity(activeDetail.severity)}
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 pt-4 items-start">
            <div className="lg:col-span-7">
              <div className="text-xs font-medium text-slate-600 mb-2">
                Isolated Interval Waveform (Actual vs Expected Baseline)
              </div>
              {detailLoading && activeDetail.waveform.length === 0 ? (
                <div className="h-[130px] flex items-center justify-center bg-slate-50 border border-slate-200 rounded-md text-xs text-slate-500">
                  Loading waveform telemetry...
                </div>
              ) : activeDetail.waveform.length > 0 && activeDetail.baselineWaveform.length > 0 ? (
                <WaveformMiniChart
                  actual={activeDetail.waveform}
                  baseline={activeDetail.baselineWaveform}
                />
              ) : (
                <div className="h-[130px] flex items-center justify-center bg-slate-50 border border-slate-200 rounded-md text-xs text-slate-500">
                  No interval waveform trace attached to this event.
                </div>
              )}
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
                    {activeDetail.durationMin}m · {renderCostCell(activeDetail)}
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

          {/* Workflow Audit History */}
          <div className="mt-5 pt-4 border-t border-slate-100">
            <div className="flex items-center gap-1.5 text-xs font-medium text-slate-600 mb-2">
              <History className="w-3.5 h-3.5" aria-hidden="true" />
              Workflow Audit Trail
            </div>
            {detailLoading && selectedAnomalyHistory.length === 0 ? (
              <div className="text-xs text-slate-400">Loading workflow history...</div>
            ) : selectedAnomalyHistory.length === 0 ? (
              <div className="text-xs text-slate-400">No workflow transitions recorded yet.</div>
            ) : (
              <ul className="space-y-1.5 text-xs">
                {selectedAnomalyHistory.map((log) => (
                  <li
                    key={log.id}
                    className="flex flex-wrap items-baseline justify-between gap-2 py-1 px-2.5 bg-slate-50 rounded border border-slate-100"
                  >
                    <div className="text-slate-700">
                      <span className="font-medium text-slate-900">
                        {log.from_status ? `${log.from_status} -> ${log.to_status}` : log.to_status}
                      </span>
                      {log.note && <span className="text-slate-600"> — {log.note}</span>}
                    </div>
                    <span className="font-mono tabular-nums text-[11px] text-slate-400">
                      {formatTimestampInZone(log.changed_at, timeZone)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
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
