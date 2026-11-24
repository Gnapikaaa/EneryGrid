import React from 'react';
import { Zap } from 'lucide-react';

interface AuthLayoutProps {
  children: React.ReactNode;
}

const CAPABILITIES = [
  {
    title: 'Load Profile & Baseline Modeling',
    detail: 'Track 15-minute facility demand against statistical baseline envelopes and contracted demand ceilings.',
  },
  {
    title: 'Statistical Anomaly Detection',
    detail: 'Isolate inductive surges, sustained off-shift baseload drift, and power factor deviations across zones.',
  },
  {
    title: 'Actionable Efficiency Insights',
    detail: 'Quantify tariff-aware peak shaving opportunities and track equipment calibration audits.',
  },
];

export const AuthLayout: React.FC<AuthLayoutProps> = ({ children }) => {
  return (
    <div
      className="min-h-screen bg-slate-950 text-slate-100 flex flex-col justify-center px-4 py-8 sm:px-6 lg:px-8"
      style={{
        backgroundImage:
          'linear-gradient(to right, rgba(148, 163, 184, 0.05) 1px, transparent 1px), linear-gradient(to bottom, rgba(148, 163, 184, 0.05) 1px, transparent 1px)',
        backgroundSize: '40px 40px',
      }}
    >
      <div className="w-full max-w-5xl mx-auto grid grid-cols-1 lg:grid-cols-12 gap-8 lg:gap-12 items-center">
        {/* Left Industrial Context Column */}
        <section className="lg:col-span-6 space-y-6">
          <div className="inline-flex items-center gap-2.5">
            <Zap className="w-5 h-5 text-sky-400 shrink-0" aria-hidden="true" />
            <span className="text-lg font-bold tracking-tight text-white">EnergyGrid</span>
          </div>

          <div className="space-y-3">
            <h1 className="text-3xl sm:text-4xl font-bold tracking-tight text-white text-balance leading-tight">
              Industrial Energy Telemetry &amp; Anomaly Analytics
            </h1>
            <p className="text-sm sm:text-base text-slate-300 leading-relaxed max-w-xl">
              Unified monitoring for plant utility engineers and facility managers. Inspect sub-meter demand curves, detect threshold excursions, and manage corrective workflows.
            </p>
          </div>

          <div className="border-t border-slate-800 pt-5 space-y-4">
            {CAPABILITIES.map((item, idx) => (
              <div
                key={item.title}
                className={idx > 0 ? 'pt-4 border-t border-slate-800/80' : undefined}
              >
                <div className="flex items-baseline gap-2.5">
                  <span className="text-xs font-mono tabular-nums text-sky-400 shrink-0">
                    0{idx + 1}.
                  </span>
                  <h2 className="text-sm font-semibold text-slate-100">{item.title}</h2>
                </div>
                <p className="mt-1 pl-7 text-xs sm:text-sm text-slate-400 leading-relaxed">
                  {item.detail}
                </p>
              </div>
            ))}
          </div>

          <div className="pt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs font-mono text-slate-400">
            <span>Sub-meter telemetry</span>
            <span aria-hidden="true">·</span>
            <span>Tariff-aware costing</span>
            <span aria-hidden="true">·</span>
            <span>Role-based access</span>
          </div>
        </section>

        {/* Right Form Panel */}
        <section className="lg:col-span-6 w-full max-w-md mx-auto lg:max-w-none">
          <div className="bg-slate-900 border border-slate-800 rounded-lg p-6 sm:p-8 shadow-xl shadow-slate-950/50">
            {children}
          </div>
        </section>
      </div>
    </div>
  );
};
