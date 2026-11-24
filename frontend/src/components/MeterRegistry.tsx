import React, { useMemo, useState } from 'react';
import { Search } from 'lucide-react';
import { MeterAsset } from '../data/energyData';
import { SegmentedControl } from './SegmentedControl';
import { StatusIndicator } from './StatusIndicator';

interface MeterRegistryProps {
  meters: MeterAsset[];
  selectedZoneName: string | null;
  auditedDates?: Record<string, string>;
  onLogAudit?: (meterId: string) => void;
}

export const MeterRegistry: React.FC<MeterRegistryProps> = ({
  meters,
  selectedZoneName,
  auditedDates,
  onLogAudit,
}) => {
  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<'All' | MeterAsset['status']>('All');
  const [localAuditedIds, setLocalAuditedIds] = useState<Record<string, string>>({});

  const effectiveAuditedDates = auditedDates ?? localAuditedIds;

  const filteredMeters = useMemo(() => {
    return meters.filter((m) => {
      if (selectedZoneName && m.zone !== selectedZoneName) return false;
      if (statusFilter !== 'All' && m.status !== statusFilter) return false;
      if (query.trim()) {
        const q = query.toLowerCase();
        return (
          m.meterCode.toLowerCase().includes(q) ||
          m.equipmentName.toLowerCase().includes(q) ||
          m.zone.toLowerCase().includes(q)
        );
      }
      return true;
    });
  }, [meters, selectedZoneName, statusFilter, query]);

  const handleLogCalibration = (meterId: string) => {
    if (onLogAudit) {
      onLogAudit(meterId);
    } else {
      const today = new Date().toISOString().slice(0, 10);
      setLocalAuditedIds((prev) => ({ ...prev, [meterId]: today }));
    }
  };

  return (
    <div className="bg-white border border-slate-200 rounded-lg p-5">
      <div className="flex flex-wrap items-center justify-between gap-4 pb-4 border-b border-slate-100">
        <div>
          <h2 className="text-base font-semibold text-slate-900">
            Sub-Meter & Equipment Health Registry
            {selectedZoneName ? ` · ${selectedZoneName}` : ''}
          </h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Real-time load factor, power quality (PF / THD%), and calibration audit status
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <div className="relative w-full sm:w-52">
            <Search
              className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2"
              aria-hidden="true"
            />
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search meter or asset..."
              className="pl-8 pr-3 py-1.5 text-xs bg-white border border-slate-200 rounded-md text-slate-900 placeholder:text-slate-400 focus:outline-none focus:border-sky-600 w-full"
              aria-label="Search meters and equipment"
            />
          </div>

          <SegmentedControl
            options={['All', 'Nominal', 'Warning', 'Fault'] as const}
            value={statusFilter}
            onChange={setStatusFilter}
            ariaLabel="Filter meters by health status"
          />
        </div>
      </div>

      {filteredMeters.length === 0 ? (
        <div className="py-10 text-center text-xs text-slate-500">
          No meters match the current search or zone filter.
        </div>
      ) : (
        <div className="overflow-x-auto mt-2">
          <table className="w-full text-left border-collapse min-w-[740px]">
            <thead>
              <tr className="border-b border-slate-200 text-xs font-medium text-slate-500">
                <th className="py-2.5 pr-3">Meter ID</th>
                <th className="py-2.5 px-3">Equipment & Zone</th>
                <th className="py-2.5 px-3 text-right">Load / Rated</th>
                <th className="py-2.5 px-3 text-right">Power Factor</th>
                <th className="py-2.5 px-3 text-right">THD %</th>
                <th className="py-2.5 px-3">Health Status</th>
                <th className="py-2.5 px-3">Last Calibrated</th>
                <th className="py-2.5 pl-3 text-right">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-xs">
              {filteredMeters.map((m) => {
                const utilizationPct = Math.round((m.currentKw / m.ratedKw) * 100);
                const isAudited = Boolean(effectiveAuditedDates[m.id]);
                const calibratedDate = effectiveAuditedDates[m.id] ?? m.lastCalibrated;
                return (
                  <tr key={m.id} className="hover:bg-slate-50">
                    <td className="py-2.5 pr-3 font-mono tabular-nums font-medium text-slate-900">
                      {m.meterCode}
                    </td>
                    <td className="py-2.5 px-3">
                      <div className="font-medium text-slate-900">{m.equipmentName}</div>
                      <div className="text-slate-500">{m.zone}</div>
                    </td>
                    <td className="py-2.5 px-3 text-right font-mono tabular-nums">
                      <span className="font-semibold text-slate-900">
                        {m.currentKw.toLocaleString()}
                      </span>
                      <span className="text-slate-400"> / {m.ratedKw.toLocaleString()} kW</span>
                      <span className="text-slate-500 ml-1.5">({utilizationPct}%)</span>
                    </td>
                    <td
                      className={`py-2.5 px-3 text-right font-mono tabular-nums font-medium ${
                        m.powerFactor < 0.88 ? 'text-amber-700' : 'text-slate-900'
                      }`}
                    >
                      {m.powerFactor.toFixed(2)}
                    </td>
                    <td
                      className={`py-2.5 px-3 text-right font-mono tabular-nums ${
                        m.thdPct > 5.0 ? 'text-red-600 font-semibold' : 'text-slate-700'
                      }`}
                    >
                      {m.thdPct.toFixed(1)}%
                    </td>
                    <td className="py-2.5 px-3">
                      <StatusIndicator status={m.status} />
                    </td>
                    <td className="py-2.5 px-3 font-mono tabular-nums text-slate-600">
                      {calibratedDate}
                    </td>
                    <td className="py-2.5 pl-3 text-right">
                      <button
                        type="button"
                        onClick={() => handleLogCalibration(m.id)}
                        disabled={isAudited}
                        className="px-2.5 py-1 text-xs font-medium border border-slate-200 rounded text-slate-700 hover:bg-slate-100 disabled:opacity-50 disabled:cursor-default whitespace-nowrap"
                      >
                        {isAudited ? 'Audited Today' : 'Log Audit'}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
