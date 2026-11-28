import React, { useMemo, useState } from 'react';
import { ChevronDown, ChevronUp, History } from 'lucide-react';
import { InsightStatus, InsightWorkflowLogResponse } from '../types/api';
import {
  MappedInsight,
  formatCurrency,
  formatTimestampInZone,
  getCostEstimateStatusLabel,
  getSavingsBasisLabel,
} from '../utils/energyMappers';
import { SegmentedControl } from './SegmentedControl';

interface InsightsPanelProps {
  insights: MappedInsight[];
  currencyCode: string;
  timeZone?: string;
  selectedZoneName?: string | null;
  canOperate: boolean;
  loading?: boolean;
  updatingInsightId?: string | null;
  actionError?: string | null;
  selectedInsightDetail?: MappedInsight | null;
  selectedInsightHistory?: InsightWorkflowLogResponse[];
  detailLoading?: boolean;
  onSelectInsight?: (insight: MappedInsight | null) => void;
  onChangeInsightStatus: (id: string, status: InsightStatus) => void | Promise<void>;
}

const INSIGHT_STATUS_OPTIONS = [
  { value: 'Recommended', label: 'Recommended' },
  { value: 'In Progress', label: 'In Progress' },
  {
    value: 'Implemented',
    label: 'Implemented',
    activeClassName: 'bg-emerald-700 text-white',
  },
] as const;

export const InsightsPanel: React.FC<InsightsPanelProps> = ({
  insights,
  currencyCode,
  timeZone = 'UTC',
  selectedZoneName,
  canOperate,
  loading = false,
  updatingInsightId = null,
  actionError = null,
  selectedInsightDetail = null,
  selectedInsightHistory = [],
  detailLoading = false,
  onSelectInsight,
  onChangeInsightStatus,
}) => {
  const [expandedInsightId, setExpandedInsightId] = useState<string | null>(null);

  const scopedInsights = useMemo(() => {
    if (!selectedZoneName) return insights;
    return insights.filter((item) => item.zone === selectedZoneName);
  }, [insights, selectedZoneName]);

  const totals = scopedInsights.reduce(
    (acc, item) => {
      acc.potentialKwh += item.monthlyKwhSavings;
      if (item.annualCostSavings !== null) {
        acc.potentialCost += item.annualCostSavings;
        acc.hasQuantified = true;
        if (item.status === 'Implemented') {
          acc.capturedCost += item.annualCostSavings;
        }
      } else {
        acc.unquantifiedCount += 1;
      }
      return acc;
    },
    { potentialCost: 0, potentialKwh: 0, capturedCost: 0, hasQuantified: false, unquantifiedCount: 0 }
  );

  const toggleDetails = (insight: MappedInsight) => {
    const nextId = expandedInsightId === insight.id ? null : insight.id;
    setExpandedInsightId(nextId);
    onSelectInsight?.(nextId ? insight : null);
  };

  return (
    <div className="bg-white border border-slate-200 rounded-lg p-5">
      <div className="flex flex-wrap items-center justify-between gap-4 pb-4 border-b border-slate-100">
        <div>
          <h2 className="text-base font-semibold text-slate-900">
            Actionable Engineering Insights & Load Optimization
            {selectedZoneName ? ` · ${selectedZoneName}` : ''}
          </h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Prioritized interventions ranked by annual cost savings and payback period
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-xs font-mono tabular-nums">
          <div>
            <span className="text-slate-500 font-sans">Identified Opportunity: </span>
            <strong className="text-slate-900">
              {totals.hasQuantified
                ? `${formatCurrency(totals.potentialCost, currencyCode)}/yr`
                : totals.unquantifiedCount > 0
                  ? `${totals.potentialKwh.toLocaleString()} kWh/mo (Unquantified)`
                  : `${formatCurrency(0, currencyCode)}/yr`}
            </strong>
          </div>
          <div>
            <span className="text-slate-500 font-sans">Implemented Savings: </span>
            <strong className="text-emerald-700">
              {formatCurrency(totals.capturedCost, currencyCode)}/yr
            </strong>
          </div>
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

      {loading && insights.length === 0 ? (
        <div className="py-10 text-center text-xs text-slate-500">
          Loading optimization insights...
        </div>
      ) : scopedInsights.length === 0 ? (
        <div className="py-10 text-center text-xs text-slate-500">
          {selectedZoneName
            ? `No optimization insights logged for ${selectedZoneName}.`
            : 'No optimization insights logged for this facility.'}
        </div>
      ) : (
        <div className="divide-y divide-slate-100">
          {scopedInsights.map((insight) => {
            const isExpanded = expandedInsightId === insight.id;
            const detail =
              isExpanded && selectedInsightDetail?.id === insight.id
                ? selectedInsightDetail
                : insight;
            const costLabel =
              insight.annualCostSavings !== null && insight.costEstimateStatus === 'available'
                ? `${formatCurrency(insight.annualCostSavings, currencyCode)}/yr`
                : insight.annualCostSavings !== null
                  ? `${formatCurrency(insight.annualCostSavings, currencyCode)}/yr (${getCostEstimateStatusLabel(insight.costEstimateStatus)})`
                  : getCostEstimateStatusLabel(insight.costEstimateStatus);

            return (
              <div key={insight.id} className="py-4 space-y-3">
                <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
                  <div className="space-y-1 max-w-3xl">
                    <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                      <span className="font-medium text-slate-700">{insight.category}</span>
                      <span aria-hidden="true">·</span>
                      <span>{insight.zone}</span>
                      {insight.meterCode && (
                        <>
                          <span aria-hidden="true">·</span>
                          <span className="font-mono">{insight.meterCode}</span>
                        </>
                      )}
                      <span aria-hidden="true">·</span>
                      <span
                        className={
                          insight.priority === 'High'
                            ? 'text-amber-700 font-medium'
                            : 'text-slate-600'
                        }
                      >
                        {insight.priority} Priority
                      </span>
                      <span aria-hidden="true">·</span>
                      <span className="text-slate-500">
                        {getSavingsBasisLabel(insight.savingsBasis)}
                      </span>
                    </div>
                    <h3 className="text-sm font-semibold text-slate-900">{insight.title}</h3>
                    <p className="text-xs text-slate-600 leading-relaxed">{insight.summary}</p>
                    <button
                      type="button"
                      onClick={() => toggleDetails(insight)}
                      aria-expanded={isExpanded}
                      className="inline-flex items-center gap-1 text-xs font-medium text-sky-700 hover:text-sky-900 pt-1"
                    >
                      {isExpanded ? (
                        <>
                          <ChevronUp className="w-3.5 h-3.5" aria-hidden="true" />
                          Hide Evidence & History
                        </>
                      ) : (
                        <>
                          <ChevronDown className="w-3.5 h-3.5" aria-hidden="true" />
                          View Evidence & History
                        </>
                      )}
                    </button>
                  </div>

                  <div className="flex flex-wrap items-center gap-4 sm:gap-6 shrink-0">
                    <div className="text-left sm:text-right font-mono tabular-nums">
                      <div className="text-sm font-semibold text-slate-900">{costLabel}</div>
                      <div className="text-xs text-slate-500">
                        {insight.monthlyKwhSavings.toLocaleString()} kWh/mo ·{' '}
                        {insight.paybackMonths !== null
                          ? `${insight.paybackMonths} mo payback`
                          : 'Payback N/A'}
                      </div>
                    </div>

                    {canOperate ? (
                      <div className={updatingInsightId === insight.id ? 'opacity-60 pointer-events-none' : ''}>
                        <SegmentedControl
                          options={INSIGHT_STATUS_OPTIONS}
                          value={insight.status}
                          onChange={(status) => void onChangeInsightStatus(insight.id, status)}
                          ariaLabel={`Status for ${insight.title}`}
                        />
                      </div>
                    ) : (
                      <span className="px-2.5 py-1 text-xs font-medium rounded-md border border-slate-200 bg-slate-50 text-slate-700">
                        {insight.status}
                      </span>
                    )}
                  </div>
                </div>

                {isExpanded && (
                  <div className="bg-slate-50 border border-slate-200 rounded-md p-3.5 space-y-3 text-xs">
                    <div className="flex flex-wrap items-center justify-between gap-2 text-slate-500">
                      <span>
                        Rule: <strong className="font-mono text-slate-800">{detail.ruleCode}</strong>
                      </span>
                      <span className="font-mono">
                        Updated: {formatTimestampInZone(detail.updatedAt, timeZone)}
                      </span>
                    </div>

                    {detailLoading && !detail.evidence ? (
                      <div className="text-slate-500">Loading supporting rule evidence...</div>
                    ) : detail.evidence ? (
                      <div>
                        <div className="font-medium text-slate-700 mb-1">Rule Evidence</div>
                        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 font-mono tabular-nums">
                          {Object.entries(detail.evidence).map(([key, val]) => (
                            <div
                              key={key}
                              className="bg-white border border-slate-200 rounded px-2.5 py-1.5"
                            >
                              <div className="text-[10px] font-sans text-slate-500 truncate">
                                {key.replace(/_/g, ' ')}
                              </div>
                              <div className="text-xs font-medium text-slate-900 truncate">
                                {typeof val === 'object' ? JSON.stringify(val) : String(val)}
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    ) : (
                      <div className="text-slate-500">No structured evidence recorded.</div>
                    )}

                    <div>
                      <div className="flex items-center gap-1.5 font-medium text-slate-700 mb-1">
                        <History className="w-3.5 h-3.5" aria-hidden="true" />
                        Status History
                      </div>
                      {detailLoading && selectedInsightHistory.length === 0 ? (
                        <div className="text-slate-400">Loading history...</div>
                      ) : selectedInsightHistory.length === 0 ? (
                        <div className="text-slate-400">No workflow transitions logged.</div>
                      ) : (
                        <ul className="space-y-1">
                          {selectedInsightHistory.map((log) => (
                            <li
                              key={log.id}
                              className="flex flex-wrap items-center justify-between gap-2 bg-white border border-slate-100 rounded px-2.5 py-1"
                            >
                              <span className="text-slate-700">
                                {log.from_status
                                  ? `${log.from_status} -> ${log.to_status}`
                                  : log.to_status}
                                {log.note ? ` — ${log.note}` : ''}
                              </span>
                              <span className="font-mono text-[11px] text-slate-400">
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
          })}
        </div>
      )}
    </div>
  );
};
