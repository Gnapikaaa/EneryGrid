import React, { useMemo, useState } from 'react';

interface ConsumptionHeatmapProps {
  matrix: number[][];
  contractedDemandKw: number;
  scopeLabel?: string;
}

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

export const ConsumptionHeatmap: React.FC<ConsumptionHeatmapProps> = ({
  matrix,
  contractedDemandKw,
  scopeLabel,
}) => {
  const [hoveredCell, setHoveredCell] = useState<{ day: number; hour: number; kw: number } | null>(
    null
  );

  const { maxKw, minKw } = useMemo(() => {
    const flat = matrix.flat();
    return {
      maxKw: Math.max(...flat, 1),
      minKw: Math.min(...flat, 0),
    };
  }, [matrix]);

  const getCellStyle = (kw: number) => {
    const ratio = (kw - minKw) / Math.max(1, maxKw - minKw);
    if (ratio >= 0.85) return 'bg-red-600 text-white';
    if (ratio >= 0.68) return 'bg-amber-500 text-white';
    if (ratio >= 0.48) return 'bg-sky-600 text-white';
    if (ratio >= 0.28) return 'bg-sky-200 text-slate-900';
    return 'bg-slate-100 text-slate-600';
  };

  return (
    <div className="bg-white border border-slate-200 rounded-lg p-5">
      <div className="flex flex-wrap items-center justify-between gap-4 mb-4">
        <div>
          <h2 className="text-base font-semibold text-slate-900">
            Weekly Load Intensity Matrix (Day × Hour){scopeLabel ? ` · ${scopeLabel}` : ''}
          </h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Reveals off-shift baseload drift (01:00–04:00) and weekday peak tariff overlap
          </p>
        </div>

        <div className="text-xs font-mono tabular-nums text-slate-600">
          {hoveredCell ? (
            <span>
              {DAYS[hoveredCell.day]} {String(hoveredCell.hour).padStart(2, '0')}:00 ·{' '}
              <strong className="text-slate-900">{hoveredCell.kw.toLocaleString()} kW</strong> (
              {((hoveredCell.kw / Math.max(1, contractedDemandKw)) * 100).toFixed(0)}% ceiling)
            </span>
          ) : (
            <span className="text-slate-400">Hover any hour cell to inspect kW load</span>
          )}
        </div>
      </div>

      <div className="overflow-x-auto" onMouseLeave={() => setHoveredCell(null)}>
        <div className="min-w-[680px]">
          {/* Hour header */}
          <div className="grid grid-cols-[44px_repeat(24,minmax(0,1fr))] gap-1 mb-1">
            <div />
            {Array.from({ length: 24 }, (_, h) => (
              <div
                key={h}
                className="text-[10px] font-mono tabular-nums text-slate-400 text-center"
              >
                {h % 3 === 0 ? String(h).padStart(2, '0') : ''}
              </div>
            ))}
          </div>

          {/* Matrix rows */}
          <div className="space-y-1">
            {matrix.map((row, dayIdx) => (
              <div
                key={DAYS[dayIdx]}
                className="grid grid-cols-[44px_repeat(24,minmax(0,1fr))] gap-1 items-center"
              >
                <div className="text-xs font-medium text-slate-600 pr-2">{DAYS[dayIdx]}</div>
                {row.map((kw, hourIdx) => (
                  <button
                    key={`${dayIdx}-${hourIdx}`}
                    type="button"
                    onMouseEnter={() => setHoveredCell({ day: dayIdx, hour: hourIdx, kw })}
                    onFocus={() => setHoveredCell({ day: dayIdx, hour: hourIdx, kw })}
                    aria-label={`${DAYS[dayIdx]} ${String(hourIdx).padStart(2, '0')}:00 — ${kw} kW`}
                    className={`h-6 rounded-xs transition-opacity hover:opacity-85 focus-visible:outline-2 focus-visible:outline-sky-600 ${getCellStyle(
                      kw
                    )}`}
                  />
                ))}
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="mt-4 pt-3 border-t border-slate-100 flex flex-wrap items-center justify-between gap-3 text-xs text-slate-500">
        <div className="flex items-center gap-3">
          <span>Low Baseload</span>
          <div className="flex items-center gap-1">
            <span className="w-4 h-3 rounded-xs bg-slate-100 border border-slate-200 inline-block" />
            <span className="w-4 h-3 rounded-xs bg-sky-200 inline-block" />
            <span className="w-4 h-3 rounded-xs bg-sky-600 inline-block" />
            <span className="w-4 h-3 rounded-xs bg-amber-500 inline-block" />
            <span className="w-4 h-3 rounded-xs bg-red-600 inline-block" />
          </div>
          <span>Peak / Anomaly Surge</span>
        </div>
        <span className="font-mono tabular-nums">
          Range: {minKw.toLocaleString()}–{maxKw.toLocaleString()} kW
        </span>
      </div>
    </div>
  );
};
