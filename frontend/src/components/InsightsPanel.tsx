import React, { useMemo } from 'react';
import { ActionableInsight, InsightStatus } from '../data/energyData';
import { SegmentedControl } from './SegmentedControl';

interface InsightsPanelProps {
  insights: ActionableInsight[];
  insightStatuses: Record<string, InsightStatus>;
  onChangeInsightStatus: (id: string, status: InsightStatus) => void;
  selectedZoneName?: string | null;
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
  insightStatuses,
  onChangeInsightStatus,
  selectedZoneName,
}) => {
  const scopedInsights = useMemo(() => {
    if (!selectedZoneName) return insights;
    return insights.filter((item) => item.zone === selectedZoneName);
  }, [insights, selectedZoneName]);

  const totals = scopedInsights.reduce(
    (acc, item) => {
      const currentStatus = insightStatuses[item.id] ?? item.status;
      acc.potentialUsd += item.annualUsdSavings;
      acc.potentialKwh += item.monthlyKwhSavings;
      if (currentStatus === 'Implemented') {
        acc.capturedUsd += item.annualUsdSavings;
      }
      return acc;
    },
    { potentialUsd: 0, potentialKwh: 0, capturedUsd: 0 }
  );

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
            <strong className="text-slate-900">${totals.potentialUsd.toLocaleString()}/yr</strong>
          </div>
          <div>
            <span className="text-slate-500 font-sans">Implemented Savings: </span>
            <strong className="text-emerald-700">${totals.capturedUsd.toLocaleString()}/yr</strong>
          </div>
        </div>
      </div>

      {scopedInsights.length === 0 ? (
        <div className="py-10 text-center text-xs text-slate-500">
          No open optimization insights logged for {selectedZoneName}.
        </div>
      ) : (
        <div className="divide-y divide-slate-100">
          {scopedInsights.map((insight) => {
            const currentStatus = insightStatuses[insight.id] ?? insight.status;
            return (
              <div
                key={insight.id}
                className="py-4 flex flex-col lg:flex-row lg:items-center justify-between gap-4"
              >
                <div className="space-y-1 max-w-3xl">
                  <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                    <span className="font-medium text-slate-700">{insight.category}</span>
                    <span aria-hidden="true">·</span>
                    <span>{insight.zone}</span>
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
                  </div>
                  <h3 className="text-sm font-semibold text-slate-900">{insight.title}</h3>
                  <p className="text-xs text-slate-600 leading-relaxed">{insight.summary}</p>
                </div>

                <div className="flex flex-wrap items-center gap-4 sm:gap-6 shrink-0">
                  <div className="text-left sm:text-right font-mono tabular-nums">
                    <div className="text-sm font-semibold text-slate-900">
                      ${insight.annualUsdSavings.toLocaleString()}/yr
                    </div>
                    <div className="text-xs text-slate-500">
                      {insight.monthlyKwhSavings.toLocaleString()} kWh/mo · {insight.paybackMonths}{' '}
                      mo payback
                    </div>
                  </div>

                  <SegmentedControl
                    options={INSIGHT_STATUS_OPTIONS}
                    value={currentStatus}
                    onChange={(status) => onChangeInsightStatus(insight.id, status)}
                    ariaLabel={`Status for ${insight.title}`}
                  />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
