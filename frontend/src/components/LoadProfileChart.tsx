import React, { useMemo, useState } from 'react';
import { TelemetryPoint } from '../data/energyData';

interface LoadProfileChartProps {
  series: TelemetryPoint[];
  contractedDemandKw: number;
  sigmaThreshold: number;
  selectedAnomalyPointId: string | null;
  onSelectPoint?: (pointId: string) => void;
  scopeLabel?: string;
}

export const LoadProfileChart: React.FC<LoadProfileChartProps> = ({
  series,
  contractedDemandKw,
  sigmaThreshold,
  selectedAnomalyPointId,
  onSelectPoint,
  scopeLabel,
}) => {
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null);
  const [showBaselineBand, setShowBaselineBand] = useState(true);
  const [showDemandCeiling, setShowDemandCeiling] = useState(true);

  const width = 920;
  const height = 310;
  const padLeft = 58;
  const padRight = 24;
  const padTop = 24;
  const padBottom = 38;
  const plotW = width - padLeft - padRight;
  const plotH = height - padTop - padBottom;

  const { maxVal, minVal } = useMemo(() => {
    const allValues = series.flatMap((p) => [
      p.actualKw,
      p.baselineKw + p.stdDevKw * sigmaThreshold,
      p.baselineKw - p.stdDevKw * 1.5,
    ]);
    if (showDemandCeiling) {
      allValues.push(contractedDemandKw);
    }
    const maxRaw = Math.max(...allValues, 20);
    const minRaw = Math.min(...allValues, 0);
    const step = maxRaw < 250 ? 25 : 100;
    const maxVal = Math.ceil((maxRaw * 1.08) / step) * step;
    const minVal = Math.max(0, Math.floor((minRaw * 0.85) / step) * step);
    return { maxVal, minVal };
  }, [series, contractedDemandKw, sigmaThreshold, showDemandCeiling]);

  const xFor = (idx: number) =>
    series.length <= 1 ? padLeft : padLeft + (idx / (series.length - 1)) * plotW;

  const yFor = (val: number) => {
    const range = Math.max(1, maxVal - minVal);
    return padTop + plotH - ((val - minVal) / range) * plotH;
  };

  const { actualPath, baselinePath, bandPolygon } = useMemo(() => {
    if (series.length === 0) {
      return { actualPath: '', baselinePath: '', bandPolygon: '' };
    }
    const range = Math.max(1, maxVal - minVal);
    const getX = (idx: number) =>
      series.length <= 1 ? padLeft : padLeft + (idx / (series.length - 1)) * plotW;
    const getY = (val: number) => padTop + plotH - ((val - minVal) / range) * plotH;

    const actual = series
      .map((p, i) => `${i === 0 ? 'M' : 'L'} ${getX(i).toFixed(1)} ${getY(p.actualKw).toFixed(1)}`)
      .join(' ');

    const baseline = series
      .map((p, i) => `${i === 0 ? 'M' : 'L'} ${getX(i).toFixed(1)} ${getY(p.baselineKw).toFixed(1)}`)
      .join(' ');

    const upper = series.map(
      (p, i) =>
        `${getX(i).toFixed(1)},${getY(p.baselineKw + p.stdDevKw * sigmaThreshold).toFixed(1)}`
    );
    const lower = [...series]
      .reverse()
      .map(
        (p, revIdx) =>
          `${getX(series.length - 1 - revIdx).toFixed(1)},${getY(
            Math.max(0, p.baselineKw - p.stdDevKw * 1.5)
          ).toFixed(1)}`
      );

    return {
      actualPath: actual,
      baselinePath: baseline,
      bandPolygon: [...upper, ...lower].join(' '),
    };
  }, [series, sigmaThreshold, maxVal, minVal, plotW, plotH]);

  const yTicks = useMemo(() => {
    const steps = 4;
    const arr: number[] = [];
    for (let i = 0; i <= steps; i++) {
      arr.push(Math.round(minVal + ((maxVal - minVal) * i) / steps));
    }
    return arr;
  }, [minVal, maxVal]);

  const activePoint =
    hoveredIdx !== null && hoveredIdx >= 0 && hoveredIdx < series.length ? series[hoveredIdx] : null;
  const ceilingY = yFor(contractedDemandKw);

  return (
    <div className="bg-white border border-slate-200 rounded-lg p-5">
      <div className="flex flex-wrap items-center justify-between gap-4 mb-4">
        <div>
          <h2 className="text-base font-semibold text-slate-900">
            Load Profile & Statistical Baseline Envelope
            {scopeLabel ? ` · ${scopeLabel}` : ''}
          </h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Actual demand (kW) against rolling 30-day baseline and {sigmaThreshold.toFixed(1)}σ anomaly threshold
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => setShowBaselineBand((v) => !v)}
            className={`px-3 py-1.5 text-xs font-medium rounded-md border transition-colors whitespace-nowrap shrink-0 ${
              showBaselineBand
                ? 'bg-slate-900 text-white border-slate-900'
                : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'
            }`}
          >
            {showBaselineBand ? 'Hide Envelope' : 'Show Envelope'}
          </button>
          <button
            type="button"
            onClick={() => setShowDemandCeiling((v) => !v)}
            className={`px-3 py-1.5 text-xs font-medium rounded-md border transition-colors whitespace-nowrap shrink-0 ${
              showDemandCeiling
                ? 'bg-sky-50 text-sky-800 border-sky-200'
                : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'
            }`}
          >
            {showDemandCeiling ? 'Hide Demand Ceiling' : 'Show Demand Ceiling'}
          </button>
        </div>
      </div>

      <div className="relative w-full overflow-x-auto">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="w-full h-auto min-w-[640px] select-none"
          role="img"
          aria-label="Industrial energy load profile and statistical anomaly chart"
          onMouseLeave={() => setHoveredIdx(null)}
        >
          {/* Horizontal Grid Lines */}
          {yTicks.map((tick) => {
            const y = yFor(tick);
            return (
              <g key={tick}>
                <line
                  x1={padLeft}
                  y1={y}
                  x2={width - padRight}
                  y2={y}
                  stroke="#E2E8F0"
                  strokeWidth={1}
                />
                <text
                  x={padLeft - 10}
                  y={y + 4}
                  textAnchor="end"
                  className="fill-slate-500 text-[11px] font-mono tabular-nums"
                >
                  {tick.toLocaleString()}
                </text>
              </g>
            );
          })}

          {/* Peak Tariff Shaded Windows */}
          {series.map((pt, idx) => {
            if (pt.tariffPeriod !== 'Peak' || idx === series.length - 1) return null;
            const x1 = xFor(idx);
            const x2 = xFor(idx + 1);
            return (
              <rect
                key={`peak-${pt.id}`}
                x={x1}
                y={padTop}
                width={Math.max(1, x2 - x1)}
                height={plotH}
                fill="#FEF3C7"
                fillOpacity={0.35}
              />
            );
          })}

          {/* Baseline Statistical Envelope */}
          {showBaselineBand && bandPolygon && (
            <polygon points={bandPolygon} fill="#0284C7" fillOpacity={0.1} />
          )}

          {/* Contracted Demand Ceiling */}
          {showDemandCeiling && ceilingY >= padTop && ceilingY <= padTop + plotH && (
            <g>
              <line
                x1={padLeft}
                y1={ceilingY}
                x2={width - padRight}
                y2={ceilingY}
                stroke="#DC2626"
                strokeWidth={1.25}
                strokeDasharray="5 4"
              />
              <text
                x={width - padRight - 4}
                y={ceilingY - 6}
                textAnchor="end"
                className="fill-red-600 text-[10px] font-mono tabular-nums font-medium"
              >
                Contract Ceiling: {contractedDemandKw.toLocaleString()} kW
              </text>
            </g>
          )}

          {/* Baseline Mean Line */}
          <path
            d={baselinePath}
            fill="none"
            stroke="#64748B"
            strokeWidth={1.5}
            strokeDasharray="4 4"
          />

          {/* Actual Demand Line */}
          <path d={actualPath} fill="none" stroke="#0F172A" strokeWidth={2.25} />

          {/* Hover Vertical Guide */}
          {hoveredIdx !== null && (
            <line
              x1={xFor(hoveredIdx)}
              y1={padTop}
              x2={xFor(hoveredIdx)}
              y2={padTop + plotH}
              stroke="#94A3B8"
              strokeWidth={1}
              strokeDasharray="3 3"
            />
          )}

          {/* Data Points & Anomaly Markers */}
          {series.map((pt, idx) => {
            const cx = xFor(idx);
            const cy = yFor(pt.actualKw);
            const isAnomaly = pt.zScore >= sigmaThreshold;
            const isSelected = pt.id === selectedAnomalyPointId;
            const isHovered = hoveredIdx === idx;

            return (
              <g key={pt.id}>
                {isAnomaly && (
                  <circle
                    cx={cx}
                    cy={cy}
                    r={isSelected ? 8 : 6}
                    fill="#DC2626"
                    fillOpacity={0.18}
                    stroke="#DC2626"
                    strokeWidth={1.5}
                  />
                )}
                {(isAnomaly || isHovered || isSelected) && (
                  <circle
                    cx={cx}
                    cy={cy}
                    r={isHovered ? 4.5 : 3.5}
                    fill={isAnomaly ? '#DC2626' : '#0284C7'}
                    stroke="#FFFFFF"
                    strokeWidth={1.5}
                  />
                )}
                {/* Invisible hover hit column */}
                {(() => {
                  const colW = plotW / Math.max(1, series.length);
                  const rawX = cx - colW / 2;
                  const clampedX = Math.max(padLeft, rawX);
                  const maxRight = width - padRight;
                  const clampedW = Math.max(1, Math.min(maxRight - clampedX, rawX + colW - clampedX));
                  return (
                    <rect
                      x={clampedX}
                      y={padTop}
                      width={clampedW}
                      height={plotH}
                      fill="transparent"
                      className="cursor-pointer"
                      onMouseEnter={() => setHoveredIdx(idx)}
                      onClick={() => onSelectPoint?.(pt.id)}
                    />
                  );
                })()}
              </g>
            );
          })}

          {/* X Axis Labels */}
          {series.map((pt, idx) => {
            const stride = series.length > 24 ? 4 : 3;
            if (idx % stride !== 0 && idx !== series.length - 1) return null;
            return (
              <text
                key={`x-${pt.id}`}
                x={xFor(idx)}
                y={height - 12}
                textAnchor="middle"
                className="fill-slate-500 text-[11px] font-mono tabular-nums"
              >
                {pt.label}
              </text>
            );
          })}
        </svg>
      </div>

      {/* Legend & Live Inspection Strip */}
      <div className="mt-4 pt-3 border-t border-slate-100 flex flex-wrap items-center justify-between gap-4 text-xs">
        <div className="flex flex-wrap items-center gap-5 text-slate-600">
          <span className="inline-flex items-center gap-2">
            <span className="w-4 h-0.5 bg-slate-900 inline-block" />
            Actual Load (kW)
          </span>
          <span className="inline-flex items-center gap-2">
            <span className="w-4 border-t-2 border-dashed border-slate-500 inline-block" />
            Expected Baseline
          </span>
          <span className="inline-flex items-center gap-2">
            <span className="w-3 h-3 bg-sky-600/15 border border-sky-600/30 inline-block rounded-xs" />
            Normal Envelope ({sigmaThreshold.toFixed(1)}σ)
          </span>
          <span className="inline-flex items-center gap-2">
            <span className="w-3 h-3 bg-amber-200/60 inline-block rounded-xs" />
            Peak Tariff Window
          </span>
          <span className="inline-flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full bg-red-600 inline-block" />
            Detected Anomaly
          </span>
        </div>

        <div className="font-mono tabular-nums text-slate-700">
          {activePoint ? (
            <span>
              {activePoint.timestamp} · Actual{' '}
              <strong className="text-slate-900">{activePoint.actualKw.toLocaleString()} kW</strong> ·
              Baseline {activePoint.baselineKw.toLocaleString()} kW ·{' '}
              <span
                className={
                  activePoint.zScore >= sigmaThreshold ? 'text-red-600 font-semibold' : 'text-slate-600'
                }
              >
                Z={activePoint.zScore.toFixed(2)}σ
              </span>{' '}
              · PF {activePoint.powerFactor.toFixed(2)}
            </span>
          ) : (
            <span className="text-slate-400">Hover chart to inspect interval telemetry</span>
          )}
        </div>
      </div>
    </div>
  );
};
