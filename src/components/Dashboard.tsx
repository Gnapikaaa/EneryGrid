import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Activity,
  AlertOctagon,
  AlertTriangle,
  BarChart3,
  Building2,
  Cpu,
  Download,
  Lightbulb,
  Loader2,
  LogOut,
  Menu,
  Play,
  RefreshCw,
  Settings2,
  SlidersHorizontal,
  UserCheck,
  X,
  Zap,
} from 'lucide-react';
import { getAnalyticsSummary, processAnalytics } from '../api/analytics';
import {
  acknowledgeAnomaly,
  getAnomaly,
  getAnomalyHistory,
  investigateAnomaly,
  listAnomalies,
  reopenAnomaly,
  resolveAnomaly,
} from '../api/anomalies';
import { listFacilities } from '../api/facilities';
import {
  getInsight,
  getInsightHistory,
  listInsights,
  updateInsightStatus,
} from '../api/insights';
import { listMeters, updateMeter } from '../api/meters';
import { fetchAllTelemetryReadings } from '../api/telemetry';
import { listUsers } from '../api/users';
import { listZones } from '../api/zones';
import { DataSourceScope, TimeWindow } from '../types/energy';
import {
  AnalyticsSummaryResponse,
  AnomalyResponse,
  AnomalyWorkflowLogResponse,
  AuthUser,
  FacilityResponse,
  InsightResponse,
  InsightStatus,
  InsightWorkflowLogResponse,
  MeterResponse,
  TelemetryReadingResponse,
  ZoneResponse,
} from '../types/api';
import {
  MappedAnomaly,
  MappedInsight,
  buildHeatmapMatrixFromReadings,
  calculateLiveDashboardKpis,
  filterAnomaliesByTimeWindow,
  filterReadingsBySourceScope,
  filterReadingsByTimeWindow,
  formatCurrency,
  formatTimestampInZone,
  getLiveScopedDemandCeilingKw,
  mapAnomalyResponse,
  mapFacilityResponse,
  mapInsightResponse,
  mapMetersToAssets,
  mapSummarySeriesToTelemetryPoints,
  mapSummaryZonesToSubMeters,
  mapTelemetryReadingsToSeries,
  mapZonesToSubMeters,
} from '../utils/energyMappers';
import {
  canIngestTelemetry,
  canManageInfrastructure,
  canOperateAnalytics,
  canUpdateMeters,
  formatRoleLabel,
} from '../utils/rbac';
import { AnomalyTable } from './AnomalyTable';
import { ConsumptionHeatmap } from './ConsumptionHeatmap';
import { ExportCsvModal } from './ExportCsvModal';
import { InfrastructureModal } from './InfrastructureModal';
import { InsightsPanel } from './InsightsPanel';
import { LoadProfileChart } from './LoadProfileChart';
import { MeterRegistry } from './MeterRegistry';
import { SegmentedControl } from './SegmentedControl';
import { TelemetryIngestModal } from './TelemetryIngestModal';
import { ZoneBreakdown } from './ZoneBreakdown';

type NavSection = 'overview' | 'patterns' | 'anomalies' | 'insights' | 'meters';

interface DashboardProps {
  user: AuthUser;
  onLogout: () => void;
}

export const Dashboard: React.FC<DashboardProps> = ({ user, onLogout }) => {
  const [activeNav, setActiveNav] = useState<NavSection>('overview');
  const [timeWindow, setTimeWindow] = useState<TimeWindow>('24h');
  const [sourceScope, setSourceScope] = useState<DataSourceScope>('measured');
  const [sigmaThreshold, setSigmaThreshold] = useState<number>(2.0);
  const [selectedZoneId, setSelectedZoneId] = useState<string | null>(null);
  const [selectedAnomalyId, setSelectedAnomalyId] = useState<string | null>(null);
  const [selectedInsightId, setSelectedInsightId] = useState<string | null>(null);

  const [facilitiesRaw, setFacilitiesRaw] = useState<FacilityResponse[]>([]);
  const [facilityId, setFacilityId] = useState<string | null>(null);
  const [facilitiesLoading, setFacilitiesLoading] = useState<boolean>(true);
  const [facilitiesError, setFacilitiesError] = useState<string | null>(null);

  const [zonesRaw, setZonesRaw] = useState<ZoneResponse[]>([]);
  const [metersRaw, setMetersRaw] = useState<MeterResponse[]>([]);
  const [readingsRaw, setReadingsRaw] = useState<TelemetryReadingResponse[]>([]);
  const [summaryRaw, setSummaryRaw] = useState<AnalyticsSummaryResponse | null>(null);
  const [anomaliesRaw, setAnomaliesRaw] = useState<AnomalyResponse[]>([]);
  const [insightsRaw, setInsightsRaw] = useState<InsightResponse[]>([]);
  const [users, setUsers] = useState<AuthUser[]>([]);

  const [facilityDataLoading, setFacilityDataLoading] = useState<boolean>(false);
  const [facilityDataError, setFacilityDataError] = useState<string | null>(null);
  const [refreshNonce, setRefreshNonce] = useState<number>(0);

  const [selectedAnomalyDetail, setSelectedAnomalyDetail] = useState<MappedAnomaly | null>(null);
  const [selectedAnomalyHistory, setSelectedAnomalyHistory] = useState<
    AnomalyWorkflowLogResponse[]
  >([]);
  const [anomalyDetailLoading, setAnomalyDetailLoading] = useState<boolean>(false);
  const [anomalyActionLoadingId, setAnomalyActionLoadingId] = useState<string | null>(null);
  const [anomalyActionError, setAnomalyActionError] = useState<string | null>(null);

  const [selectedInsightDetail, setSelectedInsightDetail] = useState<MappedInsight | null>(null);
  const [selectedInsightHistory, setSelectedInsightHistory] = useState<
    InsightWorkflowLogResponse[]
  >([]);
  const [insightDetailLoading, setInsightDetailLoading] = useState<boolean>(false);
  const [updatingInsightId, setUpdatingInsightId] = useState<string | null>(null);
  const [insightActionError, setInsightActionError] = useState<string | null>(null);

  const [updatingMeterId, setUpdatingMeterId] = useState<string | null>(null);
  const [meterActionError, setMeterActionError] = useState<string | null>(null);

  const [runningQuickAnalytics, setRunningQuickAnalytics] = useState<boolean>(false);
  const [analyticsBanner, setAnalyticsBanner] = useState<string | null>(null);

  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [exportModalOpen, setExportModalOpen] = useState(false);
  const [ingestModalOpen, setIngestModalOpen] = useState(false);
  const [infraModalOpen, setInfraModalOpen] = useState(false);

  const userCanOperate = canOperateAnalytics(user.role);
  const userCanUpdateMeters = canUpdateMeters(user.role);
  const userCanIngest = canIngestTelemetry(user.role);
  const userCanManageInfra = canManageInfrastructure(user.role);

  const loadFacilities = useCallback(
    async (signal?: AbortSignal, preferredFacilityId?: string) => {
      setFacilitiesLoading(true);
      setFacilitiesError(null);
      try {
        const res = await listFacilities({ page_size: 100 }, signal);
        setFacilitiesRaw(res.items);

        setFacilityId((current) => {
          if (preferredFacilityId && res.items.some((f) => f.id === preferredFacilityId)) {
            return preferredFacilityId;
          }
          if (current && res.items.some((f) => f.id === current)) {
            return current;
          }
          const firstActive = res.items.find((f) => f.is_active);
          return firstActive?.id ?? res.items[0]?.id ?? null;
        });
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return;
        setFacilitiesError(
          err instanceof Error ? err.message : 'Unable to load facilities from EnergyGrid API.'
        );
      } finally {
        if (!signal?.aborted) {
          setFacilitiesLoading(false);
        }
      }
    },
    []
  );

  // Initial facilities (+ admin user list) load
  useEffect(() => {
    const controller = new AbortController();
    void loadFacilities(controller.signal);

    if (userCanManageInfra) {
      listUsers(controller.signal)
        .then((list) => setUsers(list))
        .catch(() => {
          // Non-critical user directory lookup
        });
    }

    return () => controller.abort();
  }, [loadFacilities, userCanManageInfra]);

  // Load facility-scoped zones, meters, server analytics summary, telemetry, anomalies, and insights
  useEffect(() => {
    if (!facilityId) {
      setZonesRaw([]);
      setMetersRaw([]);
      setReadingsRaw([]);
      setSummaryRaw(null);
      setAnomaliesRaw([]);
      setInsightsRaw([]);
      return;
    }

    const controller = new AbortController();
    setFacilityDataLoading(true);
    setFacilityDataError(null);
    setAnomalyActionError(null);
    setInsightActionError(null);
    setMeterActionError(null);

    Promise.all([
      listZones({ facility_id: facilityId, page_size: 100 }, controller.signal),
      listMeters({ facility_id: facilityId, page_size: 100 }, controller.signal),
      fetchAllTelemetryReadings(
        {
          facility_id: facilityId,
          page_size: 100,
          source: sourceScope === 'simulation' ? 'simulation' : undefined,
        },
        { maxPages: 5, signal: controller.signal }
      ),
      listAnomalies({ facility_id: facilityId, page_size: 100 }, controller.signal),
      listInsights({ facility_id: facilityId, page_size: 100 }, controller.signal),
      sourceScope === 'simulation'
        ? Promise.resolve(null)
        : getAnalyticsSummary(
            {
              facility_id: facilityId,
              zone_id: selectedZoneId ?? undefined,
              time_window: timeWindow,
              include_simulated: sourceScope === 'all',
            },
            controller.signal
          ).catch(() => null),
    ])
      .then(([zonesRes, metersRes, telemetryRes, anomaliesRes, insightsRes, summaryRes]) => {
        if (controller.signal.aborted) return;
        setZonesRaw(zonesRes.items);
        setMetersRaw(metersRes.items);
        setReadingsRaw(telemetryRes.items);
        setAnomaliesRaw(anomaliesRes.items);
        setInsightsRaw(insightsRes.items);
        setSummaryRaw(summaryRes);
      })
      .catch((err) => {
        if (err instanceof DOMException && err.name === 'AbortError') return;
        setFacilityDataError(
          err instanceof Error ? err.message : 'Unable to load facility telemetry and analytics.'
        );
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setFacilityDataLoading(false);
        }
      });

    return () => controller.abort();
  }, [facilityId, selectedZoneId, timeWindow, sourceScope, refreshNonce]);

  const facilities = useMemo(() => facilitiesRaw.map(mapFacilityResponse), [facilitiesRaw]);
  const activeFacility = useMemo(
    () => facilities.find((f) => f.id === facilityId) ?? null,
    [facilities, facilityId]
  );

  const facilityTimezone = activeFacility?.timezone ?? 'UTC';
  const facilityCurrency = activeFacility?.currencyCode ?? 'USD';

  const activeSummary = sourceScope !== 'simulation' ? summaryRaw : null;

  const mappedMeters = useMemo(
    () => mapMetersToAssets(metersRaw, zonesRaw, activeSummary?.meter_snapshots ?? []),
    [metersRaw, zonesRaw, activeSummary]
  );

  const sourceFilteredReadings = useMemo(
    () => filterReadingsBySourceScope(readingsRaw, sourceScope),
    [readingsRaw, sourceScope]
  );

  const windowedReadings = useMemo(
    () => filterReadingsByTimeWindow(sourceFilteredReadings, timeWindow),
    [sourceFilteredReadings, timeWindow]
  );

  const scopedReadings = useMemo(() => {
    if (!selectedZoneId) return windowedReadings;
    return windowedReadings.filter((r) => r.zone_id === selectedZoneId);
  }, [windowedReadings, selectedZoneId]);

  const mappedZones = useMemo(() => {
    if (activeSummary && activeSummary.zone_breakdown.length > 0) {
      return mapSummaryZonesToSubMeters(activeSummary.zone_breakdown, zonesRaw);
    }
    return mapZonesToSubMeters(zonesRaw, windowedReadings, metersRaw);
  }, [activeSummary, zonesRaw, windowedReadings, metersRaw]);

  const selectedZone = useMemo(
    () => mappedZones.find((z) => z.id === selectedZoneId) ?? null,
    [mappedZones, selectedZoneId]
  );

  const series = useMemo(() => {
    if (activeSummary) {
      return mapSummarySeriesToTelemetryPoints(
        activeSummary.series,
        zonesRaw,
        scopedReadings,
        facilityTimezone
      );
    }
    return mapTelemetryReadingsToSeries(scopedReadings, zonesRaw, timeWindow, facilityTimezone);
  }, [activeSummary, scopedReadings, zonesRaw, timeWindow, facilityTimezone]);

  const scopedHeatmapMatrix = useMemo(() => {
    if (activeSummary) {
      return activeSummary.heatmap_matrix;
    }
    return buildHeatmapMatrixFromReadings(scopedReadings, facilityTimezone);
  }, [activeSummary, scopedReadings, facilityTimezone]);

  const scopedDemandCeilingKw = useMemo(() => {
    if (activeSummary) return activeSummary.contracted_demand_kw;
    if (!activeFacility) return 0;
    return getLiveScopedDemandCeilingKw(activeFacility, mappedMeters, selectedZoneId);
  }, [activeSummary, activeFacility, mappedMeters, selectedZoneId]);

  const mappedAnomalies = useMemo(() => {
    const allMapped = anomaliesRaw.map((a) =>
      mapAnomalyResponse(a, zonesRaw, metersRaw, facilityTimezone, scopedReadings)
    );
    const zoneScoped = selectedZoneId
      ? allMapped.filter((a) => a.zoneId === selectedZoneId)
      : allMapped;
    return filterAnomaliesByTimeWindow(zoneScoped, scopedReadings, timeWindow);
  }, [anomaliesRaw, zonesRaw, metersRaw, facilityTimezone, scopedReadings, selectedZoneId, timeWindow]);

  const mappedInsights = useMemo(
    () => insightsRaw.map((ins) => mapInsightResponse(ins, zonesRaw, metersRaw)),
    [insightsRaw, zonesRaw, metersRaw]
  );

  const kpis = useMemo(() => {
    if (!activeFacility) {
      return {
        totalMwh: 0,
        avgDemandKw: 0,
        consumptionTrendPct: null,
        peakDemandKw: 0,
        demandCeilingKw: 0,
        demandHeadroomPct: 0,
        avgPf: 0,
        openAnomaliesCount: 0,
        criticalCount: 0,
        potentialSavingsAmount: 0,
        hasQuantifiedSavings: false,
        unquantifiedInsightsCount: 0,
      };
    }
    const baseKpis = calculateLiveDashboardKpis({
      facility: activeFacility,
      readings: scopedReadings,
      series,
      anomalies: mappedAnomalies.filter((a) => a.zScore >= sigmaThreshold),
      insights: mappedInsights,
      meters: mappedMeters,
      selectedZoneId,
    });
    if (!activeSummary) {
      return baseKpis;
    }
    return {
      ...baseKpis,
      totalMwh: activeSummary.total_mwh,
      avgDemandKw: activeSummary.avg_demand_kw,
      consumptionTrendPct: activeSummary.consumption_trend_pct,
      peakDemandKw: Math.round(activeSummary.peak_demand_kw),
      demandCeilingKw: activeSummary.contracted_demand_kw,
      demandHeadroomPct: Math.round(activeSummary.demand_headroom_pct),
      avgPf: activeSummary.avg_power_factor,
      potentialSavingsAmount: activeSummary.potential_annual_savings,
      hasQuantifiedSavings: activeSummary.has_quantified_savings,
      unquantifiedInsightsCount: activeSummary.unquantified_insights_count,
    };
  }, [
    activeFacility,
    activeSummary,
    scopedReadings,
    series,
    mappedAnomalies,
    sigmaThreshold,
    mappedInsights,
    mappedMeters,
    selectedZoneId,
  ]);

  const effectiveSelectedAnomalyId = useMemo(() => {
    const visible = mappedAnomalies.filter((a) => a.zScore >= sigmaThreshold);
    if (selectedAnomalyId && visible.some((a) => a.id === selectedAnomalyId)) {
      return selectedAnomalyId;
    }
    return visible[0]?.id ?? null;
  }, [mappedAnomalies, sigmaThreshold, selectedAnomalyId]);

  // Load anomaly detail (waveform) & history whenever active anomaly changes
  useEffect(() => {
    if (!effectiveSelectedAnomalyId) {
      setSelectedAnomalyDetail(null);
      setSelectedAnomalyHistory([]);
      return;
    }

    const controller = new AbortController();
    setAnomalyDetailLoading(true);

    Promise.all([
      getAnomaly(effectiveSelectedAnomalyId, controller.signal),
      getAnomalyHistory(effectiveSelectedAnomalyId, controller.signal),
    ])
      .then(([detail, history]) => {
        setSelectedAnomalyDetail(
          mapAnomalyResponse(detail, zonesRaw, metersRaw, facilityTimezone, scopedReadings)
        );
        setSelectedAnomalyHistory(history);
      })
      .catch((err) => {
        if (err instanceof DOMException && err.name === 'AbortError') return;
        // Keep table row data visible even if detail/history fetch fails
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setAnomalyDetailLoading(false);
        }
      });

    return () => controller.abort();
  }, [effectiveSelectedAnomalyId, zonesRaw, metersRaw, facilityTimezone]);

  // Load insight detail (evidence) & history when expanded
  useEffect(() => {
    if (!selectedInsightId) {
      setSelectedInsightDetail(null);
      setSelectedInsightHistory([]);
      return;
    }

    const controller = new AbortController();
    setInsightDetailLoading(true);

    Promise.all([
      getInsight(selectedInsightId, controller.signal),
      getInsightHistory(selectedInsightId, controller.signal),
    ])
      .then(([detail, history]) => {
        setSelectedInsightDetail(mapInsightResponse(detail, zonesRaw, metersRaw));
        setSelectedInsightHistory(history);
      })
      .catch((err) => {
        if (err instanceof DOMException && err.name === 'AbortError') return;
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setInsightDetailLoading(false);
        }
      });

    return () => controller.abort();
  }, [selectedInsightId, zonesRaw, metersRaw]);

  const applyUpdatedAnomaly = async (updated: AnomalyResponse) => {
    setAnomaliesRaw((prev) => prev.map((a) => (a.id === updated.id ? updated : a)));
    setSelectedAnomalyDetail(
      mapAnomalyResponse(updated, zonesRaw, metersRaw, facilityTimezone, scopedReadings)
    );
    try {
      const history = await getAnomalyHistory(updated.id);
      setSelectedAnomalyHistory(history);
    } catch {
      // Non-fatal
    }
  };

  const handleAcknowledgeAnomaly = async (anomalyId: string, note?: string | null) => {
    setAnomalyActionLoadingId(anomalyId);
    setAnomalyActionError(null);
    try {
      const updated = await acknowledgeAnomaly(anomalyId, { note: note ?? null });
      await applyUpdatedAnomaly(updated);
    } catch (err) {
      setAnomalyActionError(
        err instanceof Error ? err.message : 'Unable to acknowledge anomaly.'
      );
    } finally {
      setAnomalyActionLoadingId(null);
    }
  };

  const handleInvestigateAnomaly = async (
    anomalyId: string,
    assignedToUserId?: string | null,
    note?: string | null
  ) => {
    setAnomalyActionLoadingId(anomalyId);
    setAnomalyActionError(null);
    try {
      const updated = await investigateAnomaly(anomalyId, {
        assigned_to_user_id: assignedToUserId ?? null,
        note: note ?? null,
      });
      await applyUpdatedAnomaly(updated);
    } catch (err) {
      setAnomalyActionError(
        err instanceof Error ? err.message : 'Unable to assign anomaly for investigation.'
      );
    } finally {
      setAnomalyActionLoadingId(null);
    }
  };

  const handleResolveAnomaly = async (anomalyId: string, note: string) => {
    setAnomalyActionLoadingId(anomalyId);
    setAnomalyActionError(null);
    try {
      const updated = await resolveAnomaly(anomalyId, { note });
      await applyUpdatedAnomaly(updated);
    } catch (err) {
      setAnomalyActionError(err instanceof Error ? err.message : 'Unable to resolve anomaly.');
    } finally {
      setAnomalyActionLoadingId(null);
    }
  };

  const handleReopenAnomaly = async (anomalyId: string, note: string) => {
    setAnomalyActionLoadingId(anomalyId);
    setAnomalyActionError(null);
    try {
      const updated = await reopenAnomaly(anomalyId, { note });
      await applyUpdatedAnomaly(updated);
    } catch (err) {
      setAnomalyActionError(err instanceof Error ? err.message : 'Unable to reopen anomaly.');
    } finally {
      setAnomalyActionLoadingId(null);
    }
  };

  const handleChangeInsightStatus = async (id: string, status: InsightStatus) => {
    setUpdatingInsightId(id);
    setInsightActionError(null);
    try {
      const updated = await updateInsightStatus(id, { status });
      setInsightsRaw((prev) => prev.map((ins) => (ins.id === updated.id ? updated : ins)));
      if (selectedInsightId === updated.id) {
        setSelectedInsightDetail(mapInsightResponse(updated, zonesRaw, metersRaw));
        try {
          const history = await getInsightHistory(updated.id);
          setSelectedInsightHistory(history);
        } catch {
          // Non-fatal
        }
      }
    } catch (err) {
      setInsightActionError(
        err instanceof Error ? err.message : 'Unable to update insight status.'
      );
    } finally {
      setUpdatingInsightId(null);
    }
  };

  const handleLogMeterAudit = async (meterId: string) => {
    const today = new Date().toISOString().slice(0, 10);
    setUpdatingMeterId(meterId);
    setMeterActionError(null);
    try {
      const updated = await updateMeter(meterId, { last_calibrated_at: today });
      setMetersRaw((prev) => prev.map((m) => (m.id === updated.id ? updated : m)));
      setRefreshNonce((n) => n + 1);
    } catch (err) {
      setMeterActionError(
        err instanceof Error ? err.message : 'Unable to record meter calibration audit.'
      );
    } finally {
      setUpdatingMeterId(null);
    }
  };

  const handleRunQuickAnalytics = async () => {
    if (!facilityId) return;
    setRunningQuickAnalytics(true);
    setAnalyticsBanner(null);
    setFacilityDataError(null);
    try {
      const summary = await processAnalytics({
        facility_id: facilityId,
        zone_id: selectedZoneId ?? undefined,
        include_insights: true,
      });
      setAnalyticsBanner(
        `Analytics complete: ${summary.processed_readings} readings processed, ${summary.anomalies_created} new anomalies, ${summary.insights_created + summary.insights_updated} insights updated.`
      );
      setRefreshNonce((n) => n + 1);
    } catch (err) {
      setFacilityDataError(
        err instanceof Error ? err.message : 'Failed to run analytics engine.'
      );
    } finally {
      setRunningQuickAnalytics(false);
    }
  };

  const handleSelectZone = (zoneId: string | null) => {
    setSelectedZoneId(zoneId);
    setSelectedAnomalyId(null);
  };

  const handleSelectChartPoint = (pointId: string) => {
    const matching = mappedAnomalies.find((a) => a.pointId === pointId);
    if (matching) {
      setSelectedAnomalyId(matching.id);
      if (activeNav === 'overview') {
        setActiveNav('anomalies');
      }
    }
  };

  const handleFacilityChange = (id: string) => {
    setFacilityId(id);
    setSelectedZoneId(null);
    setSelectedAnomalyId(null);
    setSelectedInsightId(null);
    setAnalyticsBanner(null);
  };

  const latestTelemetryTimestamp = useMemo(() => {
    if (readingsRaw.length === 0) return null;
    return readingsRaw.reduce((latest, r) => (r.recorded_at > latest ? r.recorded_at : latest), readingsRaw[0].recorded_at);
  }, [readingsRaw]);

  const selectedAnomalyPointId = useMemo(() => {
    return mappedAnomalies.find((a) => a.id === effectiveSelectedAnomalyId)?.pointId ?? null;
  }, [mappedAnomalies, effectiveSelectedAnomalyId]);

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
            value={facilityId ?? ''}
            disabled={facilitiesLoading || facilities.length === 0}
            onChange={(e) => handleFacilityChange(e.target.value)}
            className="w-full px-2.5 py-2 text-xs font-medium bg-slate-50 border border-slate-200 rounded-md text-slate-900 focus:outline-none focus:border-sky-600 disabled:opacity-60"
          >
            {facilities.length === 0 ? (
              <option value="">
                {facilitiesLoading ? 'Loading facilities...' : 'No facilities available'}
              </option>
            ) : (
              facilities.map((fac) => (
                <option key={fac.id} value={fac.id}>
                  {fac.name} ({fac.code})
                </option>
              ))
            )}
          </select>
          {activeFacility && (
            <div className="mt-2 text-xs text-slate-500">
              {activeFacility.location} · Ceiling{' '}
              {activeFacility.contractedDemandKw.toLocaleString()} kW
            </div>
          )}
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

        {userCanIngest ? (
          <div className="p-4 border-t border-slate-100 text-xs text-slate-500 space-y-2">
            <div className="font-medium text-slate-700">Telemetry & Analytics</div>
            <p className="leading-relaxed">
              Ingest live/simulated readings or process rolling baselines and anomaly detection.
            </p>
            <div className="flex flex-col gap-1.5">
              <button
                type="button"
                disabled={!activeFacility}
                onClick={() => setIngestModalOpen(true)}
                className="w-full px-3 py-1.5 text-xs font-medium rounded-md border bg-white text-slate-700 border-slate-200 hover:bg-slate-50 disabled:opacity-50 whitespace-nowrap"
              >
                Ingest Telemetry
              </button>
              <button
                type="button"
                disabled={!activeFacility || runningQuickAnalytics}
                onClick={() => void handleRunQuickAnalytics()}
                className="w-full inline-flex items-center justify-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md border bg-slate-900 text-white border-slate-900 hover:bg-slate-800 disabled:opacity-50 whitespace-nowrap"
              >
                {runningQuickAnalytics ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden="true" />
                ) : (
                  <Play className="w-3.5 h-3.5" aria-hidden="true" />
                )}
                Run Analytics
              </button>
              {userCanManageInfra && (
                <button
                  type="button"
                  onClick={() => setInfraModalOpen(true)}
                  className="w-full inline-flex items-center justify-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md border bg-white text-slate-700 border-slate-200 hover:bg-slate-50 whitespace-nowrap"
                >
                  <Settings2 className="w-3.5 h-3.5" aria-hidden="true" />
                  Manage Assets
                </button>
              )}
            </div>
          </div>
        ) : (
          <div className="p-4 border-t border-slate-100 text-xs text-slate-500">
            <div className="font-medium text-slate-700 mb-1">Read-Only Monitoring</div>
            <p className="leading-relaxed">
              Signed in as {formatRoleLabel(user.role)}. Operational mutations require Utility
              Engineer or Admin privileges.
            </p>
          </div>
        )}

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
        <header className="min-h-14 sm:h-14 bg-white border-b border-slate-200 px-4 sm:px-6 py-2 sm:py-0 flex flex-wrap sm:flex-nowrap items-center justify-between gap-2.5 sm:gap-6 sticky top-0 z-20">
          <div className="flex items-center gap-2.5 sm:gap-3 min-w-0 flex-1 sm:flex-initial">
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
              <span className="font-semibold text-slate-900 truncate">
                {activeFacility?.name ?? 'Facility Workspace'}
              </span>
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

          <div className="flex items-center justify-end gap-2 sm:gap-3 shrink-0 w-full sm:w-auto">
            <SegmentedControl
              options={['24h', '7d', '30d'] as const}
              value={timeWindow}
              onChange={setTimeWindow}
              ariaLabel="Select telemetry time window"
              buttonClassName="font-mono"
            />

            <button
              type="button"
              onClick={() => setRefreshNonce((n) => n + 1)}
              disabled={!facilityId || facilityDataLoading}
              aria-label="Refresh telemetry data"
              title="Refresh data from backend"
              className="p-1.5 text-slate-600 bg-white border border-slate-200 rounded-md hover:bg-slate-50 disabled:opacity-50"
            >
              <RefreshCw
                className={`w-3.5 h-3.5 ${facilityDataLoading ? 'animate-spin' : ''}`}
                aria-hidden="true"
              />
            </button>

            <button
              type="button"
              disabled={!activeFacility}
              onClick={() => setExportModalOpen(true)}
              className="inline-flex items-center gap-1.5 px-3 sm:px-3.5 py-1.5 text-xs font-medium bg-slate-900 text-white rounded-md hover:bg-slate-800 disabled:opacity-50 transition-colors whitespace-nowrap shrink-0"
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
          {(facilitiesError || facilityDataError) && (
            <div
              role="alert"
              className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 flex flex-wrap items-center justify-between gap-3 text-xs text-red-800"
            >
              <div className="flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 shrink-0" aria-hidden="true" />
                <span>{facilitiesError ?? facilityDataError}</span>
              </div>
              <button
                type="button"
                onClick={() => {
                  if (facilitiesError) {
                    void loadFacilities();
                  } else {
                    setRefreshNonce((n) => n + 1);
                  }
                }}
                className="font-semibold underline whitespace-nowrap"
              >
                Retry Request
              </button>
            </div>
          )}

          {analyticsBanner && (
            <div className="bg-emerald-50 border border-emerald-200 rounded-lg px-4 py-2.5 flex items-center justify-between gap-3 text-xs text-emerald-800">
              <span>{analyticsBanner}</span>
              <button
                type="button"
                onClick={() => setAnalyticsBanner(null)}
                className="underline font-medium"
              >
                Dismiss
              </button>
            </div>
          )}

          {!facilitiesLoading && !facilitiesError && facilities.length === 0 ? (
            <div className="bg-white border border-slate-200 rounded-lg p-10 text-center space-y-3">
              <Building2 className="w-8 h-8 text-slate-400 mx-auto" aria-hidden="true" />
              <h2 className="text-base font-semibold text-slate-900">
                No Facilities Configured Yet
              </h2>
              <p className="text-xs text-slate-500 max-w-md mx-auto">
                The EnergyGrid database currently has no registered facilities.
                {userCanManageInfra
                  ? ' Register a facility, zone, and meters to begin ingesting telemetry.'
                  : ' Ask an administrator to configure monitored facilities and meters.'}
              </p>
              {userCanManageInfra && (
                <button
                  type="button"
                  onClick={() => setInfraModalOpen(true)}
                  className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-medium bg-slate-900 text-white rounded-md hover:bg-slate-800"
                >
                  <Settings2 className="w-3.5 h-3.5" aria-hidden="true" />
                  Register Facility
                </button>
              )}
            </div>
          ) : (
            <>
              {/* Telemetry Source Scope & Provenance Bar */}
              <div className="bg-white border border-slate-200 rounded-lg px-4 py-2.5 flex flex-wrap items-center justify-between gap-3 text-xs">
                <div className="flex flex-wrap items-center gap-2.5">
                  <span className="font-medium text-slate-700">Telemetry Source Scope:</span>
                  <SegmentedControl
                    options={
                      [
                        { value: 'measured', label: 'Measured & Imported' },
                        { value: 'all', label: 'All Sources' },
                        { value: 'simulation', label: 'Simulation Only' },
                      ] as const
                    }
                    value={sourceScope}
                    onChange={setSourceScope}
                    ariaLabel="Filter telemetry by ingestion source"
                  />
                </div>
                <div className="text-slate-500 font-mono tabular-nums">
                  {activeSummary ? (
                    <span>
                      {activeSummary.reading_count.toLocaleString()} intervals
                      {activeSummary.latest_recorded_at
                        ? ` · Latest ${formatTimestampInZone(activeSummary.latest_recorded_at, facilityTimezone)}`
                        : ' · No readings in range'}
                    </span>
                  ) : (
                    <span>
                      {scopedReadings.length.toLocaleString()} interval(s) loaded
                      {latestTelemetryTimestamp
                        ? ` · Latest ${formatTimestampInZone(latestTelemetryTimestamp, facilityTimezone)}`
                        : ''}
                    </span>
                  )}
                </div>
              </div>

              {/* 4-Column KPI Summary Row */}
              <section
                aria-label="Key Energy Metrics"
                className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4"
              >
                <div className="bg-white border border-slate-200 rounded-lg p-4">
                  <div className="text-xs font-medium text-slate-500">
                    Total & Avg Consumption ({timeWindow}){selectedZone ? ' · Zone' : ''}
                  </div>
                  <div className="mt-1.5 flex items-baseline gap-2.5 flex-wrap">
                    <span className="text-2xl font-bold font-mono tabular-nums text-slate-900">
                      {kpis.totalMwh.toFixed(1)} MWh
                    </span>
                    <span className="text-xs font-mono tabular-nums text-slate-600">
                      Avg {kpis.avgDemandKw.toLocaleString()} kW
                    </span>
                  </div>
                  <div className="mt-1 text-xs text-slate-500 font-mono tabular-nums">
                    {kpis.consumptionTrendPct !== null
                      ? `${kpis.consumptionTrendPct >= 0 ? '+' : ''}${kpis.consumptionTrendPct.toFixed(1)}% vs prior ${timeWindow}`
                      : activeFacility
                        ? `Tariff ${formatCurrency(activeFacility.offPeakTariffRate, facilityCurrency, {
                            minimumFractionDigits: 3,
                            maximumFractionDigits: 3,
                          })} / ${formatCurrency(activeFacility.peakTariffRate, facilityCurrency, {
                            minimumFractionDigits: 3,
                            maximumFractionDigits: 3,
                          })} peak`
                        : 'Loading tariff...'}
                  </div>
                </div>

                <div className="bg-white border border-slate-200 rounded-lg p-4">
                  <div className="text-xs font-medium text-slate-500">Peak Demand vs Ceiling</div>
                  <div className="mt-1.5 text-2xl font-bold font-mono tabular-nums text-slate-900">
                    {kpis.peakDemandKw.toLocaleString()} kW
                  </div>
                  <div
                    className={`mt-1 text-xs font-mono tabular-nums ${
                      kpis.demandHeadroomPct >= 95
                        ? 'text-red-600 font-semibold'
                        : 'text-slate-500'
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
                      (activeSummary ? activeSummary.reading_count === 0 : scopedReadings.length === 0)
                        ? 'text-slate-400'
                        : kpis.avgPf < 0.9
                          ? 'text-amber-700 font-medium'
                          : 'text-emerald-700'
                    }`}
                  >
                    {(activeSummary ? activeSummary.reading_count === 0 : scopedReadings.length === 0)
                      ? 'Awaiting interval telemetry'
                      : kpis.avgPf < 0.9
                        ? 'Below 0.90 utility penalty threshold'
                        : 'Compliant (>= 0.90 target)'}
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
                    {kpis.hasQuantifiedSavings
                      ? `${formatCurrency(kpis.potentialSavingsAmount, facilityCurrency)}/yr identified savings`
                      : kpis.unquantifiedInsightsCount > 0
                        ? `${kpis.unquantifiedInsightsCount} insight(s) awaiting tariff quantification`
                        : `${formatCurrency(0, facilityCurrency)}/yr identified savings`}
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
                    loading={facilityDataLoading}
                  />

                  <div className="grid grid-cols-1 xl:grid-cols-12 gap-6 items-start">
                    <div className="xl:col-span-5">
                      <ZoneBreakdown
                        zones={mappedZones}
                        selectedZoneId={selectedZoneId}
                        onSelectZone={handleSelectZone}
                        loading={facilityDataLoading}
                      />
                    </div>
                    <div className="xl:col-span-7">
                      <ConsumptionHeatmap
                        matrix={scopedHeatmapMatrix}
                        contractedDemandKw={scopedDemandCeilingKw}
                        scopeLabel={scopeLabel}
                        loading={facilityDataLoading}
                      />
                    </div>
                  </div>

                  <AnomalyTable
                    anomalies={mappedAnomalies}
                    currencyCode={facilityCurrency}
                    timeZone={facilityTimezone}
                    sigmaThreshold={sigmaThreshold}
                    onSigmaChange={setSigmaThreshold}
                    selectedAnomalyId={effectiveSelectedAnomalyId}
                    selectedAnomalyDetail={selectedAnomalyDetail}
                    selectedAnomalyHistory={selectedAnomalyHistory}
                    detailLoading={anomalyDetailLoading}
                    loading={facilityDataLoading}
                    canOperate={userCanOperate}
                    users={users}
                    actionLoadingId={anomalyActionLoadingId}
                    actionError={anomalyActionError}
                    onSelectAnomaly={(a) => setSelectedAnomalyId(a?.id ?? null)}
                    onAcknowledge={handleAcknowledgeAnomaly}
                    onInvestigate={handleInvestigateAnomaly}
                    onResolve={handleResolveAnomaly}
                    onReopen={handleReopenAnomaly}
                    scopeLabel={scopeLabel}
                  />

                  <InsightsPanel
                    insights={mappedInsights}
                    currencyCode={facilityCurrency}
                    timeZone={facilityTimezone}
                    selectedZoneName={selectedZone?.name ?? null}
                    canOperate={userCanOperate}
                    loading={facilityDataLoading}
                    updatingInsightId={updatingInsightId}
                    actionError={insightActionError}
                    selectedInsightDetail={selectedInsightDetail}
                    selectedInsightHistory={selectedInsightHistory}
                    detailLoading={insightDetailLoading}
                    onSelectInsight={(ins) => setSelectedInsightId(ins?.id ?? null)}
                    onChangeInsightStatus={handleChangeInsightStatus}
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
                    loading={facilityDataLoading}
                  />
                  <ConsumptionHeatmap
                    matrix={scopedHeatmapMatrix}
                    contractedDemandKw={scopedDemandCeilingKw}
                    scopeLabel={scopeLabel}
                    loading={facilityDataLoading}
                  />
                  <ZoneBreakdown
                    zones={mappedZones}
                    selectedZoneId={selectedZoneId}
                    onSelectZone={handleSelectZone}
                    loading={facilityDataLoading}
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
                    loading={facilityDataLoading}
                  />
                  <AnomalyTable
                    anomalies={mappedAnomalies}
                    currencyCode={facilityCurrency}
                    timeZone={facilityTimezone}
                    sigmaThreshold={sigmaThreshold}
                    onSigmaChange={setSigmaThreshold}
                    selectedAnomalyId={effectiveSelectedAnomalyId}
                    selectedAnomalyDetail={selectedAnomalyDetail}
                    selectedAnomalyHistory={selectedAnomalyHistory}
                    detailLoading={anomalyDetailLoading}
                    loading={facilityDataLoading}
                    canOperate={userCanOperate}
                    users={users}
                    actionLoadingId={anomalyActionLoadingId}
                    actionError={anomalyActionError}
                    onSelectAnomaly={(a) => setSelectedAnomalyId(a?.id ?? null)}
                    onAcknowledge={handleAcknowledgeAnomaly}
                    onInvestigate={handleInvestigateAnomaly}
                    onResolve={handleResolveAnomaly}
                    onReopen={handleReopenAnomaly}
                    scopeLabel={scopeLabel}
                  />
                </>
              )}

              {activeNav === 'insights' && (
                <InsightsPanel
                  insights={mappedInsights}
                  currencyCode={facilityCurrency}
                  timeZone={facilityTimezone}
                  selectedZoneName={selectedZone?.name ?? null}
                  canOperate={userCanOperate}
                  loading={facilityDataLoading}
                  updatingInsightId={updatingInsightId}
                  actionError={insightActionError}
                  selectedInsightDetail={selectedInsightDetail}
                  selectedInsightHistory={selectedInsightHistory}
                  detailLoading={insightDetailLoading}
                  onSelectInsight={(ins) => setSelectedInsightId(ins?.id ?? null)}
                  onChangeInsightStatus={handleChangeInsightStatus}
                />
              )}

              {activeNav === 'meters' && (
                <>
                  <ZoneBreakdown
                    zones={mappedZones}
                    selectedZoneId={selectedZoneId}
                    onSelectZone={handleSelectZone}
                    loading={facilityDataLoading}
                  />
                  <MeterRegistry
                    meters={mappedMeters}
                    selectedZoneName={selectedZone?.name ?? null}
                    canUpdateMeters={userCanUpdateMeters}
                    canManageInfrastructure={userCanManageInfra}
                    loading={facilityDataLoading}
                    updatingMeterId={updatingMeterId}
                    actionError={meterActionError}
                    onLogAudit={handleLogMeterAudit}
                    onOpenManageAssets={() => setInfraModalOpen(true)}
                  />
                </>
              )}
            </>
          )}
        </main>
      </div>

      <ExportCsvModal
        isOpen={exportModalOpen}
        onClose={() => setExportModalOpen(false)}
        facilities={facilities}
        dashboardFacilityId={facilityId}
        dashboardZones={zonesRaw}
        dashboardMeters={metersRaw}
        dashboardZoneId={selectedZoneId}
        dashboardTimeWindow={timeWindow}
        dashboardSourceScope={sourceScope}
        dashboardAnomalies={mappedAnomalies}
        latestTelemetryTimestamp={activeSummary?.latest_recorded_at ?? latestTelemetryTimestamp}
      />

      {userCanIngest && (
        <TelemetryIngestModal
          isOpen={ingestModalOpen}
          onClose={() => setIngestModalOpen(false)}
          facilityId={facilityId}
          facilityName={activeFacility?.name ?? 'Facility'}
          selectedZoneId={selectedZoneId}
          meters={mappedMeters}
          onDataUpdated={() => setRefreshNonce((n) => n + 1)}
        />
      )}

      {userCanManageInfra && (
        <InfrastructureModal
          isOpen={infraModalOpen}
          onClose={() => setInfraModalOpen(false)}
          facilities={facilities}
          activeFacilityId={facilityId}
          zones={zonesRaw}
          meters={metersRaw}
          onChanged={async (preferredId) => {
            await loadFacilities(undefined, preferredId);
            setRefreshNonce((n) => n + 1);
          }}
        />
      )}
    </div>
  );
};
