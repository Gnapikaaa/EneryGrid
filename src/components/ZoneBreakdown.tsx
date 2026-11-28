import React from 'react';
import { SubMeterZone } from '../types/energy';
import { StatusIndicator } from './StatusIndicator';

interface ZoneBreakdownProps {
  zones: Pick<
    SubMeterZone,
    'id' | 'name' | 'meterCode' | 'kwhUsed' | 'sharePct' | 'peakKw' | 'powerFactor' | 'deltaVsBaselinePct' | 'status'
  >[];
  selectedZoneId: string | null;
  onSelectZone: (zoneId: string | null) => void;
  loading?: boolean;
}

export const ZoneBreakdown: React.FC<ZoneBreakdownProps> = ({
  zones,
  selectedZoneId,
  onSelectZone,
  loading = false,
}) => {
  return (
    <div className="bg-white border border-slate-200 rounded-lg p-5">
      <div className="flex items-center justify-between gap-4 mb-4">
        <div>
          <h2 className="text-base font-semibold text-slate-900">Sub-Meter Zone Breakdown</h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Click a zone row to scope charts, heatmap, anomalies, and meters
          </p>
        </div>
        {selectedZoneId && (
          <button
            type="button"
            onClick={() => onSelectZone(null)}
            className="text-xs font-medium text-sky-700 hover:text-sky-900 underline whitespace-nowrap shrink-0"
          >
            Clear Zone Filter
          </button>
        )}
      </div>

      {loading && zones.length === 0 ? (
        <div className="py-10 text-center text-xs text-slate-500">Loading facility zones...</div>
      ) : zones.length === 0 ? (
        <div className="py-10 text-center text-xs text-slate-500">
          No sub-meter zones configured for this facility.
        </div>
      ) : (
        <div className="divide-y divide-slate-100">
          {zones.map((zone) => {
            const isSelected = selectedZoneId === zone.id;
            return (
              <button
                key={zone.id}
                type="button"
                aria-pressed={isSelected}
                onClick={() => onSelectZone(isSelected ? null : zone.id)}
                className={`w-full text-left py-3 px-2.5 -mx-2.5 rounded-md transition-colors ${
                  isSelected ? 'bg-sky-50' : 'hover:bg-slate-50'
                }`}
              >
                <div className="flex items-center justify-between gap-3 mb-1.5">
                  <div className="min-w-0">
                    <div className="text-sm font-medium text-slate-900 truncate">{zone.name}</div>
                    <div className="text-xs text-slate-500 font-mono tabular-nums mt-0.5">
                      {zone.meterCode} · Peak {zone.peakKw.toLocaleString()} kW · PF{' '}
                      {zone.powerFactor.toFixed(2)}
                    </div>
                  </div>
                  <div className="text-right shrink-0">
                    <div className="text-sm font-mono tabular-nums font-semibold text-slate-900">
                      {zone.kwhUsed.toLocaleString()} kWh
                    </div>
                    <div className="flex items-center justify-end gap-2 mt-0.5">
                      <span
                        className={`text-xs font-mono tabular-nums ${
                          zone.deltaVsBaselinePct > 5
                            ? 'text-red-600'
                            : zone.deltaVsBaselinePct < 0
                              ? 'text-emerald-700'
                              : 'text-slate-500'
                        }`}
                      >
                        {zone.deltaVsBaselinePct > 0 ? '+' : ''}
                        {zone.deltaVsBaselinePct.toFixed(1)}% vs base
                      </span>
                      <span className="text-slate-300" aria-hidden="true">
                        ·
                      </span>
                      <StatusIndicator status={zone.status} />
                    </div>
                  </div>
                </div>

                <div className="w-full h-1.5 bg-slate-100 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full ${
                      zone.status === 'Fault'
                        ? 'bg-red-600'
                        : zone.status === 'Warning'
                          ? 'bg-amber-500'
                          : 'bg-sky-600'
                    }`}
                    style={{ width: `${Math.min(100, zone.sharePct)}%` }}
                  />
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
};
