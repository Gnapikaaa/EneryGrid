import React, { useEffect, useMemo, useState } from 'react';
import {
  Activity,
  AlertOctagon,
  BarChart3,
  Cpu,
  Download,
  Lightbulb,
  LogOut,
  Menu,
  SlidersHorizontal,
  UserCheck,
  X,
  Zap,
} from 'lucide-react';
import {
  AnomalyRecord,
  AnomalyStatus,
  FACILITIES,
  FacilityId,
  FacilityProfile,
  InsightStatus,
  TimeWindow,
  calculateKpis,
  detectAnomaliesFromSeries,
  generateTelemetrySeries,
  getAnomalyStatusKey,
  getScopedDemandCeilingKw,
  getScopedHeatmapMatrix,
} from '../data/energyData';
import { AuthUser } from '../types/auth';
import { LoadProfileChart } from './LoadProfileChart';
import { ConsumptionHeatmap } from './ConsumptionHeatmap';
import { ZoneBreakdown } from './ZoneBreakdown';
import { AnomalyTable } from './AnomalyTable';
import { InsightsPanel } from './InsightsPanel';
import { MeterRegistry } from './MeterRegistry';
import { SegmentedControl } from './SegmentedControl';
import { ExportCsvModal } from './ExportCsvModal';
import { fetchFacilities, ApiFacilityResponse } from '../api/energy';
import { getStoredAccessToken } from '../api/client';

type NavSection = 'overview' | 'patterns' | 'anomalies' | 'insights' | 'meters';

interface DashboardProps {
  user: AuthUser;
  onLogout: () => void;
}

function formatRoleLabel(role: string): string {
  return role
    .split('_')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

export const Dashboard: React.FC<DashboardProps> = ({ user, onLogout }) => {
  const [activeNav, setActiveNav] = useState<NavSection>('overview');
  const [facilityId, setFacilityId] = useState<FacilityId>('north-assembly');
  const [timeWindow, setTimeWindow] = useState<TimeWindow>('24h');
  const [sigmaThreshold, setSigmaThreshold] = useState<number>(2.0);
  const [selectedZoneId, setSelectedZoneId] = useState<string | null>(null);
  const [selectedAnomalyId, setSelectedAnomalyId] = useState<string | null>(null);
  const [anomalyStatuses, setAnomalyStatuses] = useState<Record<string, AnomalyStatus>>({});
  const [insightStatuses, setInsightStatuses] = useState<Record<string, InsightStatus>>({});
  const [auditedMeterDates, setAuditedMeterDates] = useState<Record<string, string>>({});
  const [injectedSpikeKw, setInjectedSpikeKw] = useState<number>(0);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [exportModalOpen, setExportModalOpen] = useState(false);
  // Live facilities from API (null = not yet loaded or failed → fall back to FACILITIES mock)
  const [apiFacilities, setApiFacilities] = useState<ApiFacilityResponse[] | null>(null);

  // Fetch real facilities from backend on mount when authenticated
  useEffect(() => {
    if (!getStoredAccessToken()) return;
    let cancelled = false;
    fetchFacilities(100)
      .then((resp) => {
        if (!cancelled && resp.items.length > 0) {
          setApiFacilities(resp.items);
        }
      })
      .catch(() => {
        // Backend unavailable — silent fallback to mock data
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const facilitiesMap = useMemo<Record<FacilityId, FacilityProfile>>(() => {
    if (!apiFacilities || apiFacilities.length === 0) {
      return FACILITIES;
    }
    const merged: Record<string, FacilityProfile> = { ...FACILITIES };
    for (const apiFac of apiFacilities) {
      const existing = merged[apiFac.id];
      if (!existing) continue;
      const contractedDemandKw = parseFloat(apiFac.contracted_demand_kw);
      const tariffRateUsd = parseFloat(apiFac.off_peak_tariff_rate);
      const peakTariffRateUsd = parseFloat(apiFac.peak_tariff_rate);
      merged[apiFac.id] = {
        ...existing,
        name: apiFac.name,
        code: apiFac.code,
        location: apiFac.location,
        contractedDemandKw: Number.isFinite(contractedDemandKw)
          ? contractedDemandKw
          : existing.contractedDemandKw,
        tariffRateUsd: Number.isFinite(tariffRateUsd) ? tariffRateUsd : existing.tariffRateUsd,
        peakTariffRateUsd: Number.isFinite(peakTariffRateUsd)
          ? peakTariffRateUsd
          : existing.peakTariffRateUsd,
      };
    }
    return merged as Record<FacilityId, FacilityProfile>;
  }, [apiFacilities]);

  const facility = facilitiesMap[facilityId];

  const selectedZone = useMemo(
    () => facility.zones.find((z) => z.id === selectedZoneId) ?? null,
    [facility, selectedZoneId]
  );

  const series = useMemo(
    () => generateTelemetrySeries(facilityId, timeWindow, injectedSpikeKw, selectedZoneId),
    [facilityId, timeWindow, injectedSpikeKw, selectedZoneId]
  );

  const scopedHeatmapMatrix = useMemo(
    () => getScopedHeatmapMatrix(facility, selectedZoneId),
    [facility, selectedZoneId]
  );

  const scopedDemandCeilingKw = useMemo(
    () => getScopedDemandCeilingKw(facility, selectedZoneId),
    [facility, selectedZoneId]
  );

  const scopedAnomalies = useMemo(
    () =>
      detectAnomaliesFromSeries(
        facility,
        series,
        sigmaThreshold,
        anomalyStatuses,
        timeWindow
      ),
    [facility, series, sigmaThreshold, anomalyStatuses, timeWindow]
  );

  const kpis = useMemo(
    () => calculateKpis(facility, series, timeWindow, scopedAnomalies, selectedZone),
    [facility, series, timeWindow, scopedAnomalies, selectedZone]
  );

  const handleUpdateAnomalyStatus = (anomalyId: string, status: AnomalyStatus) => {
    const key = getAnomalyStatusKey(facilityId, timeWindow, anomalyId);
    setAnomalyStatuses((prev) => ({ ...prev, [key]: status }));
  };

  const handleSelectAnomaly = (anomaly: AnomalyRecord | null) => {
    setSelectedAnomalyId(anomaly?.id ?? null);
  };

  const handleSelectZone = (zoneId: string | null) => {
    setSelectedZoneId(zoneId);
    setSelectedAnomalyId(null);
  };

  const handleSelectChartPoint = (pointId: string) => {
    const matching = scopedAnomalies.find((a) => a.pointId === pointId);
    if (matching) {
      setSelectedAnomalyId(matching.id);
      if (activeNav === 'overview') {
        setActiveNav('anomalies');
      }
    }
  };

  const handleChangeInsightStatus = (id: string, status: InsightStatus) => {
    setInsightStatuses((prev) => ({ ...prev, [id]: status }));
  };

  const handleLogMeterAudit = (meterId: string) => {
    const today = new Date().toISOString().slice(0, 10);
    setAuditedMeterDates((prev) => ({ ...prev, [meterId]: today }));
  };

  const handleFacilityChange = (id: FacilityId) => {
    setFacilityId(id);
    setSelectedZoneId(null);
    setSelectedAnomalyId(null);
    setInjectedSpikeKw(0);
  };

  const navItems: { id: NavSection; label: string; icon: React.ReactNode; count?: number }[] = [
    { id: 'overview', label: 'Overview', icon: <Activity className="w-4 h-4" aria-hidden="true" /> },
    {
      id: 'patterns',
      label: 'Consumption Patterns',
      icon: <BarChart3 className="w-4 h-4" aria-hidden="true" />,
    },
    {
      id: 'anomalies',
      label: 'Anomaly Detection',
      icon: <AlertOctagon className="w-4 h-4" aria-hidden="true" />,
      count: kpis.openAnomaliesCount,
    },
    {
      id: 'insights',
      label: 'Actionable Insights',
      icon: <Lightbulb className="w-4 h-4" aria-hidden="true" />,
    },
    {
      id: 'meters',
      label: 'Meters & Equipment',
      icon: <Cpu className="w-4 h-4" aria-hidden="true" />,
    },
  ];

  const selectedAnomalyPointId = useMemo(() => {
    return scopedAnomalies.find((a) => a.id === selectedAnomalyId)?.pointId ?? null;
  }, [scopedAnomalies, selectedAnomalyId]);

  const scopeLabel = selectedZone?.name;

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 flex">
      {/* Mobile Sidebar Backdrop */}
      {mobileNavOpen && (
        <div
          className="fixed inset-0 bg-slate-900/30 z-30 lg:hidden"
          onClick={() => setMobileNavOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* Left Sidebar (248px) */}
      <aside
        className={`fixed inset-y-0 left-0 z-40 w-[248px] bg-white border-r border-slate-200 flex flex-col transition-transform duration-150 lg:static lg:translate-x-0 ${
          mobileNavOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <div className="h-14 px-5 border-b border-slate-200 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <Zap className="w-5 h-5 text-sky-700 shrink-0" aria-hidden="true" />
            <span className="text-base font-bold tracking-tight text-slate-900 whitespace-nowrap">
              EneryGrid
            </span>
          </div>
          <button
            type="button"
            onClick={() => setMobileNavOpen(false)}
            className="lg:hidden p-1 text-slate-500 hover:text-slate-900"
            aria-label="Close navigation menu"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-4 border-b border-slate-100">
          <label htmlFor="facility-select" className="block text-xs font-medium text-slate-500 mb-1.5">
            Monitored Facility
          </label>
          <select
            id="facility-select"
            value={facilityId}
            onChange={(e) => handleFacilityChange(e.target.value as FacilityId)}
            className="w-full px-2.5 py-2 text-xs font-medium bg-slate-50 border border-slate-200 rounded-md text-slate-900 focus:outline-none focus:border-sky-600"
          >
            {Object.values(facilitiesMap).map((fac) => (
              <option key={fac.id} value={fac.id}>
                {fac.name} ({fac.code})
              </option>
            ))}
          </select>
          <div className="mt-2 text-xs text-slate-500">
            {facility.location} · Ceiling {facility.contractedDemandKw.toLocaleString()} kW
          </div>
        </div>

        <nav className="flex-1 p-3 space-y-1" aria-label="Dashboard sections">
          {navItems.map((item) => {
            const isActive = activeNav === item.id;
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => {
                  setActiveNav(item.id);
                  setMobileNavOpen(false);
                }}
                className={`w-full flex items-center justify-between gap-2.5 px-3 py-2 text-sm font-medium rounded-md transition-colors whitespace-nowrap ${
                  isActive
                    ? 'bg-slate-900 text-white'
                    : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
                }`}
              >
                <span className="flex items-center gap-2.5 truncate">
                  {item.icon}
                  <span className="truncate">{item.label}</span>
                </span>
                {typeof item.count === 'number' && item.count > 0 && (
                  <span
                    className={`font-mono tabular-nums text-xs ${
                      isActive ? 'text-sky-300' : 'text-red-600 font-semibold'
                    }`}
                  >
                    {item.count}
                  </span>
                )}
              </button>
            );
          })}
        </nav>

        <div className="p-4 border-t border-slate-100 text-xs text-slate-500 space-y-2">
          <div className="font-medium text-slate-700">Anomaly Engine Test</div>
          <p className="leading-relaxed">
            Inject a synthetic +480 kW inductive load excursion to test threshold detection.
          </p>
          <button
            type="button"
            onClick={() => setInjectedSpikeKw((prev) => (prev > 0 ? 0 : 480))}
            className={`w-full px-3 py-1.5 text-xs font-medium rounded-md border transition-colors whitespace-nowrap ${
              injectedSpikeKw > 0
                ? 'bg-red-50 text-red-700 border-red-200 hover:bg-red-100'
                : 'bg-white text-slate-700 border-slate-200 hover:bg-slate-50'
            }`}
          >
            {injectedSpikeKw > 0 ? 'Clear Simulated Spike' : 'Simulate Load Spike (+480 kW)'}
          </button>
        </div>

        <div className="p-4 border-t border-slate-200 bg-slate-50/70 space-y-1">
          <div className="flex items-center gap-2 text-xs font-semibold text-slate-900 truncate">
            <UserCheck className="w-3.5 h-3.5 text-sky-700 shrink-0" aria-hidden="true" />
            <span className="truncate">{user.full_name}</span>
          </div>
          <div className="text-[11px] text-slate-500 truncate">{user.email}</div>
          <div className="text-[11px] font-mono text-slate-600">
            Role: {formatRoleLabel(user.role)}
          </div>
        </div>
      </aside>

      {/* Main Content Area */}
      <div className="flex-1 min-w-0 flex flex-col">
        {/* Top Bar Contract */}
        <header className="h-14 bg-white border-b border-slate-200 px-4 sm:px-6 flex items-center justify-between gap-3 sm:gap-6 sticky top-0 z-20">
          <div className="flex items-center gap-2.5 sm:gap-3 min-w-0">
            <button
              type="button"
              onClick={() => setMobileNavOpen(true)}
              className="lg:hidden p-1.5 text-slate-600 hover:text-slate-900 border border-slate-200 rounded-md shrink-0"
              aria-label="Open navigation menu"
            >
              <Menu className="w-4 h-4" />
            </button>
            <div className="flex items-center gap-2 text-sm truncate min-w-0">
              <span className="text-slate-500 hidden sm:inline">EneryGrid</span>
              <span className="text-slate-300 hidden sm:inline" aria-hidden="true">
                /
              </span>
              <span className="font-semibold text-slate-900 truncate">{facility.name}</span>
              {selectedZone && (
                <>
                  <span className="text-slate-300 hidden md:inline" aria-hidden="true">
                    /
                  </span>
                  <span className="text-sky-700 font-medium truncate hidden md:inline">
                    {selectedZone.name}
                  </span>
                </>
              )}
            </div>
          </div>

          <div className="flex items-center gap-2 sm:gap-3 shrink-0">
            <SegmentedControl
              options={['24h', '7d', '30d'] as const}
              value={timeWindow}
              onChange={setTimeWindow}
              ariaLabel="Select telemetry time window"
              buttonClassName="font-mono"
            />

            <button
              type="button"
              onClick={() => setExportModalOpen(true)}
              className="inline-flex items-center gap-1.5 px-3 sm:px-3.5 py-1.5 text-xs font-medium bg-slate-900 text-white rounded-md hover:bg-slate-800 transition-colors whitespace-nowrap shrink-0"
            >
              <Download className="w-3.5 h-3.5" aria-hidden="true" />
              <span className="hidden sm:inline">Export CSV</span>
              <span className="sm:hidden">CSV</span>
            </button>

            <button
              type="button"
              onClick={onLogout}
              aria-label="Sign Out"
              title={`Signed in as ${user.full_name} (${user.email})`}
              className="inline-flex items-center gap-1.5 px-2.5 sm:px-3 py-1.5 text-xs font-medium bg-white text-slate-700 border border-slate-200 rounded-md hover:bg-slate-50 hover:text-slate-900 transition-colors whitespace-nowrap shrink-0"
            >
              <LogOut className="w-3.5 h-3.5" aria-hidden="true" />
              <span className="hidden sm:inline">Sign Out</span>
            </button>
          </div>
        </header>

        {/* Viewport Content */}
        <main className="flex-1 p-4 sm:p-6 max-w-[1360px] w-full mx-auto space-y-6">
          {/* 4-Column KPI Summary Row */}
          <section
            aria-label="Key Energy Metrics"
            className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4"
          >
            <div className="bg-white border border-slate-200 rounded-lg p-4">
              <div className="text-xs font-medium text-slate-500">
                Total Consumption ({timeWindow}){selectedZone ? ' · Zone' : ''}
              </div>
              <div className="mt-1.5 text-2xl font-bold font-mono tabular-nums text-slate-900">
                {kpis.totalMwh.toFixed(1)} MWh
              </div>
              <div className="mt-1 text-xs text-slate-500 font-mono tabular-nums">
                Tariff ${facility.tariffRateUsd.toFixed(3)} / ${facility.peakTariffRateUsd.toFixed(3)} peak
              </div>
            </div>

            <div className="bg-white border border-slate-200 rounded-lg p-4">
              <div className="text-xs font-medium text-slate-500">Peak Demand vs Ceiling</div>
              <div className="mt-1.5 text-2xl font-bold font-mono tabular-nums text-slate-900">
                {kpis.peakDemandKw.toLocaleString()} kW
              </div>
              <div
                className={`mt-1 text-xs font-mono tabular-nums ${
                  kpis.demandHeadroomPct >= 95 ? 'text-red-600 font-semibold' : 'text-slate-500'
                }`}
              >
                {kpis.demandHeadroomPct}% of {kpis.demandCeilingKw.toLocaleString()} kW limit
              </div>
            </div>

            <div className="bg-white border border-slate-200 rounded-lg p-4">
              <div className="text-xs font-medium text-slate-500">Average Power Factor</div>
              <div className="mt-1.5 text-2xl font-bold font-mono tabular-nums text-slate-900">
                {kpis.avgPf.toFixed(2)} PF
              </div>
              <div
                className={`mt-1 text-xs ${
                  kpis.avgPf < 0.9 ? 'text-amber-700 font-medium' : 'text-emerald-700'
                }`}
              >
                {kpis.avgPf < 0.9 ? 'Below 0.90 utility penalty threshold' : 'Compliant (>= 0.90 target)'}
              </div>
            </div>

            <div className="bg-white border border-slate-200 rounded-lg p-4">
              <div className="text-xs font-medium text-slate-500">
                Active Anomalies & Savings Opportunity
              </div>
              <div className="mt-1.5 flex items-baseline gap-2.5">
                <span className="text-2xl font-bold font-mono tabular-nums text-slate-900">
                  {kpis.openAnomaliesCount}
                </span>
                <span className="text-xs font-medium text-red-600">
                  {kpis.criticalCount} Critical
                </span>
              </div>
              <div className="mt-1 text-xs text-slate-500 font-mono tabular-nums">
                ${kpis.potentialSavingsUsd.toLocaleString()}/yr identified savings
              </div>
            </div>
          </section>

          {/* Active Zone Filter Banner */}
          {selectedZone && (
            <div className="bg-sky-50 border border-sky-200 rounded-lg px-4 py-2.5 flex flex-wrap items-center justify-between gap-2 sm:gap-4 text-xs">
              <span className="text-sky-900">
                <SlidersHorizontal className="w-3.5 h-3.5 inline mr-1.5" aria-hidden="true" />
                Filtered by sub-meter zone: <strong>{selectedZone.name}</strong> (
                {selectedZone.meterCode})
              </span>
              <button
                type="button"
                onClick={() => handleSelectZone(null)}
                className="font-medium text-sky-800 hover:text-sky-950 underline whitespace-nowrap"
              >
                Show All Zones
              </button>
            </div>
          )}

          {/* Section Views */}
          {activeNav === 'overview' && (
            <>
              <LoadProfileChart
                series={series}
                contractedDemandKw={scopedDemandCeilingKw}
                sigmaThreshold={sigmaThreshold}
                selectedAnomalyPointId={selectedAnomalyPointId}
                onSelectPoint={handleSelectChartPoint}
                scopeLabel={scopeLabel}
              />

              <div className="grid grid-cols-1 xl:grid-cols-12 gap-6 items-start">
                <div className="xl:col-span-5">
                  <ZoneBreakdown
                    zones={facility.zones}
                    selectedZoneId={selectedZoneId}
                    onSelectZone={handleSelectZone}
                  />
                </div>
                <div className="xl:col-span-7">
                  <ConsumptionHeatmap
                    matrix={scopedHeatmapMatrix}
                    contractedDemandKw={scopedDemandCeilingKw}
                    scopeLabel={scopeLabel}
                  />
                </div>
              </div>

              <AnomalyTable
                anomalies={scopedAnomalies}
                sigmaThreshold={sigmaThreshold}
                onSigmaChange={setSigmaThreshold}
                selectedAnomalyId={selectedAnomalyId}
                onSelectAnomaly={handleSelectAnomaly}
                onUpdateStatus={handleUpdateAnomalyStatus}
                scopeLabel={scopeLabel}
                facilityId={facilityId}
              />

              <InsightsPanel
                insights={facility.insights}
                insightStatuses={insightStatuses}
                onChangeInsightStatus={handleChangeInsightStatus}
                selectedZoneName={selectedZone?.name ?? null}
                facilityId={facilityId}
              />
            </>
          )}

          {activeNav === 'patterns' && (
            <>
              <LoadProfileChart
                series={series}
                contractedDemandKw={scopedDemandCeilingKw}
                sigmaThreshold={sigmaThreshold}
                selectedAnomalyPointId={selectedAnomalyPointId}
                onSelectPoint={handleSelectChartPoint}
                scopeLabel={scopeLabel}
              />
              <ConsumptionHeatmap
                matrix={scopedHeatmapMatrix}
                contractedDemandKw={scopedDemandCeilingKw}
                scopeLabel={scopeLabel}
              />
              <ZoneBreakdown
                zones={facility.zones}
                selectedZoneId={selectedZoneId}
                onSelectZone={handleSelectZone}
              />
            </>
          )}

          {activeNav === 'anomalies' && (
            <>
              <LoadProfileChart
                series={series}
                contractedDemandKw={scopedDemandCeilingKw}
                sigmaThreshold={sigmaThreshold}
                selectedAnomalyPointId={selectedAnomalyPointId}
                onSelectPoint={handleSelectChartPoint}
                scopeLabel={scopeLabel}
              />
              <AnomalyTable
                anomalies={scopedAnomalies}
                sigmaThreshold={sigmaThreshold}
                onSigmaChange={setSigmaThreshold}
                selectedAnomalyId={selectedAnomalyId}
                onSelectAnomaly={handleSelectAnomaly}
                onUpdateStatus={handleUpdateAnomalyStatus}
                scopeLabel={scopeLabel}
                facilityId={facilityId}
              />
            </>
          )}

          {activeNav === 'insights' && (
            <InsightsPanel
              insights={facility.insights}
              insightStatuses={insightStatuses}
              onChangeInsightStatus={handleChangeInsightStatus}
              selectedZoneName={selectedZone?.name ?? null}
              facilityId={facilityId}
            />
          )}

          {activeNav === 'meters' && (
            <>
              <ZoneBreakdown
                zones={facility.zones}
                selectedZoneId={selectedZoneId}
                onSelectZone={handleSelectZone}
              />
              <MeterRegistry
                meters={facility.meters}
                selectedZoneName={selectedZone?.name ?? null}
                auditedDates={auditedMeterDates}
                onLogAudit={handleLogMeterAudit}
                facilityId={facilityId}
              />
            </>
          )}
        </main>
      </div>

      <ExportCsvModal
        isOpen={exportModalOpen}
        onClose={() => setExportModalOpen(false)}
        dashboardFacilityId={facilityId}
        dashboardZoneId={selectedZoneId}
        dashboardTimeWindow={timeWindow}
        dashboardSigmaThreshold={sigmaThreshold}
        dashboardInjectedSpikeKw={injectedSpikeKw}
        dashboardAnomalyStatuses={anomalyStatuses}
      />
    </div>
  );
};
