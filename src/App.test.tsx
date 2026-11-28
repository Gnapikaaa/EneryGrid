import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { setStoredAccessToken, clearStoredAccessToken } from './api/client';
import { Dashboard } from './components/Dashboard';
import {
  AnalyticsSummaryResponse,
  AnomalyDetailResponse,
  AnomalyResponse,
  AnomalyWorkflowLogResponse,
  FacilityResponse,
  InsightDetailResponse,
  InsightResponse,
  InsightWorkflowLogResponse,
  MeterResponse,
  TelemetryReadingResponse,
  ZoneResponse,
} from './types/api';
import { AuthUser } from './types/auth';

const ENGINEER_USER: AuthUser = {
  id: '00000000-0000-0000-0000-000000000001',
  email: 'engineer@energygrid.local',
  full_name: 'Plant Utility Engineer',
  role: 'utility_engineer',
  is_active: true,
  created_at: '2026-11-20T00:00:00Z',
};

const VIEWER_USER: AuthUser = {
  ...ENGINEER_USER,
  id: '00000000-0000-0000-0000-000000000002',
  email: 'viewer@energygrid.local',
  full_name: 'Plant Viewer',
  role: 'viewer',
};

const ADMIN_USER: AuthUser = {
  ...ENGINEER_USER,
  id: '00000000-0000-0000-0000-000000000003',
  email: 'admin@energygrid.local',
  full_name: 'Grid Admin',
  role: 'admin',
};

const FACILITIES_FIXTURE: FacilityResponse[] = [
  {
    id: 'north-assembly',
    code: 'PLT-NA01',
    name: 'North Assembly Plant',
    location: 'Detroit Sector B',
    timezone: 'UTC',
    currency_code: 'USD',
    contracted_demand_kw: '1850.00',
    off_peak_tariff_rate: '0.1180',
    mid_peak_tariff_rate: '0.1550',
    peak_tariff_rate: '0.2140',
    is_active: true,
    deactivated_at: null,
    created_at: '2026-11-01T00:00:00Z',
    zone_count: 2,
    active_zone_count: 2,
    meter_count: 2,
    active_meter_count: 2,
  },
  {
    id: 'foundry-press',
    code: 'PLT-FP02',
    name: 'Foundry & Press Hall',
    location: 'Toledo Heavy Wing',
    timezone: 'UTC',
    currency_code: 'USD',
    contracted_demand_kw: '2600.00',
    off_peak_tariff_rate: '0.1120',
    mid_peak_tariff_rate: '0.1500',
    peak_tariff_rate: '0.2050',
    is_active: true,
    deactivated_at: null,
    created_at: '2026-11-01T00:00:00Z',
    zone_count: 1,
    active_zone_count: 1,
    meter_count: 1,
    active_meter_count: 1,
  },
];

const ZONES_BY_FACILITY: Record<string, ZoneResponse[]> = {
  'north-assembly': [
    {
      id: '11111111-1111-1111-1111-111111111111',
      facility_id: 'north-assembly',
      slug: 'cnc',
      name: 'CNC Machining Line 1–4',
      primary_meter_code: 'MTR-104',
      share_pct: '60.00',
      status: 'Nominal',
      is_active: true,
      deactivated_at: null,
      meter_count: 1,
      active_meter_count: 1,
    },
    {
      id: '22222222-2222-2222-2222-222222222222',
      facility_id: 'north-assembly',
      slug: 'air',
      name: 'Compressed Air Header',
      primary_meter_code: 'MTR-208',
      share_pct: '40.00',
      status: 'Fault',
      is_active: true,
      deactivated_at: null,
      meter_count: 1,
      active_meter_count: 1,
    },
  ],
  'foundry-press': [
    {
      id: '33333333-3333-3333-3333-333333333333',
      facility_id: 'foundry-press',
      slug: 'stamping',
      name: 'Hydraulic Stamping Presses',
      primary_meter_code: 'MTR-604',
      share_pct: '100.00',
      status: 'Warning',
      is_active: true,
      deactivated_at: null,
      meter_count: 1,
      active_meter_count: 1,
    },
  ],
};

const METERS_BY_FACILITY: Record<string, MeterResponse[]> = {
  'north-assembly': [
    {
      id: 'aaaa1111-1111-1111-1111-111111111111',
      facility_id: 'north-assembly',
      zone_id: '11111111-1111-1111-1111-111111111111',
      meter_code: 'MTR-104',
      equipment_name: '5-Axis CNC Bank A',
      rated_kw: '800.00',
      nominal_interval_seconds: 3600,
      current_kw: '618.00',
      power_factor: '0.940',
      thd_pct: '3.10',
      status: 'Nominal',
      last_calibrated_at: '2026-09-14',
      is_active: true,
      deactivated_at: null,
    },
    {
      id: 'aaaa2222-2222-2222-2222-222222222222',
      facility_id: 'north-assembly',
      zone_id: '22222222-2222-2222-2222-222222222222',
      meter_code: 'MTR-208',
      equipment_name: 'Rotary Screw Compressor #2',
      rated_kw: '450.00',
      nominal_interval_seconds: 3600,
      current_kw: '438.00',
      power_factor: '0.840',
      thd_pct: '6.80',
      status: 'Fault',
      last_calibrated_at: '2026-08-02',
      is_active: true,
      deactivated_at: null,
    },
  ],
  'foundry-press': [
    {
      id: 'bbbb1111-1111-1111-1111-111111111111',
      facility_id: 'foundry-press',
      zone_id: '33333333-3333-3333-3333-333333333333',
      meter_code: 'MTR-604',
      equipment_name: '1,200T Hydraulic Press B',
      rated_kw: '750.00',
      nominal_interval_seconds: 3600,
      current_kw: '672.00',
      power_factor: '0.850',
      thd_pct: '6.10',
      status: 'Warning',
      last_calibrated_at: '2026-08-29',
      is_active: true,
      deactivated_at: null,
    },
  ],
};

const READINGS_BY_FACILITY: Record<string, TelemetryReadingResponse[]> = {
  'north-assembly': [
    {
      id: 101,
      facility_id: 'north-assembly',
      zone_id: '11111111-1111-1111-1111-111111111111',
      meter_id: 'aaaa1111-1111-1111-1111-111111111111',
      interval_start: '2026-11-18T13:00:00Z',
      recorded_at: '2026-11-18T14:00:00Z',
      interval_seconds: 3600,
      actual_kw: '600.00',
      energy_kwh: '600.0000',
      baseline_kw: '590.00',
      std_dev_kw: '25.00',
      z_score: '0.40',
      baseline_status: 'ready',
      power_factor: '0.940',
      tariff_period: 'Peak',
      ambient_temp_c: '21.00',
      quality_flag: 'valid',
      source: 'meter_feed',
    },
    {
      id: 102,
      facility_id: 'north-assembly',
      zone_id: '22222222-2222-2222-2222-222222222222',
      meter_id: 'aaaa2222-2222-2222-2222-222222222222',
      interval_start: '2026-11-18T13:00:00Z',
      recorded_at: '2026-11-18T14:00:00Z',
      interval_seconds: 3600,
      actual_kw: '438.00',
      energy_kwh: '438.0000',
      baseline_kw: '260.00',
      std_dev_kw: '22.00',
      z_score: '8.09',
      baseline_status: 'ready',
      power_factor: '0.840',
      tariff_period: 'Peak',
      ambient_temp_c: '21.00',
      quality_flag: 'valid',
      source: 'meter_feed',
    },
    {
      id: 103,
      facility_id: 'north-assembly',
      zone_id: '11111111-1111-1111-1111-111111111111',
      meter_id: 'aaaa1111-1111-1111-1111-111111111111',
      interval_start: '2026-11-18T14:00:00Z',
      recorded_at: '2026-11-18T15:00:00Z',
      interval_seconds: 3600,
      actual_kw: '910.00',
      energy_kwh: '910.0000',
      baseline_kw: '590.00',
      std_dev_kw: '25.00',
      z_score: '12.80',
      baseline_status: 'ready',
      power_factor: '0.910',
      tariff_period: 'Peak',
      ambient_temp_c: '21.00',
      quality_flag: 'valid',
      source: 'simulation',
    },
  ],
  'foundry-press': [
    {
      id: 201,
      facility_id: 'foundry-press',
      zone_id: '33333333-3333-3333-3333-333333333333',
      meter_id: 'bbbb1111-1111-1111-1111-111111111111',
      interval_start: '2026-11-18T13:00:00Z',
      recorded_at: '2026-11-18T14:00:00Z',
      interval_seconds: 3600,
      actual_kw: '672.00',
      energy_kwh: '672.0000',
      baseline_kw: '520.00',
      std_dev_kw: '30.00',
      z_score: '5.07',
      baseline_status: 'ready',
      power_factor: '0.850',
      tariff_period: 'Peak',
      ambient_temp_c: '23.00',
      quality_flag: 'valid',
      source: 'meter_feed',
    },
  ],
};

function createBackendFetchMock(options?: { failInsightsPatchWith409?: boolean }) {
  let anomaliesState: Record<string, AnomalyResponse[]> = {
    'north-assembly': [
      {
        id: 'c1111111-1111-1111-1111-111111111111',
        event_code: 'ANM-102',
        facility_id: 'north-assembly',
        zone_id: '22222222-2222-2222-2222-222222222222',
        meter_id: 'aaaa2222-2222-2222-2222-222222222222',
        reading_id: 102,
        detected_at: '2026-11-18T14:00:00Z',
        severity: 'Critical',
        status: 'Open',
        z_score: '8.09',
        actual_kw: '438.00',
        expected_kw: '260.00',
        deviation_pct: '68.5',
        duration_min: 60,
        estimated_waste_kwh: '178.00',
        estimated_cost: '38.09',
        cost_estimate_status: 'available',
        signature: 'Off-shift compressor header short-cycling',
        recommendation: 'Inspect solenoid valve on Bay 4',
        assigned_to_user_id: null,
      },
    ],
    'foundry-press': [
      {
        id: 'c2222222-2222-2222-2222-222222222222',
        event_code: 'ANM-201',
        facility_id: 'foundry-press',
        zone_id: '33333333-3333-3333-3333-333333333333',
        meter_id: 'bbbb1111-1111-1111-1111-111111111111',
        reading_id: 201,
        detected_at: '2026-11-18T14:00:00Z',
        severity: 'High',
        status: 'Open',
        z_score: '5.07',
        actual_kw: '672.00',
        expected_kw: '520.00',
        deviation_pct: '29.2',
        duration_min: 60,
        estimated_waste_kwh: '152.00',
        estimated_cost: null,
        cost_estimate_status: 'unavailable_tariff',
        signature: 'Hydraulic pump idle draw excursion',
        recommendation: 'Engage VFD idle ramp-down',
        assigned_to_user_id: null,
      },
    ],
  };

  let insightsState: Record<string, InsightResponse[]> = {
    'north-assembly': [
      {
        id: 'd1111111-1111-1111-1111-111111111111',
        facility_id: 'north-assembly',
        zone_id: '22222222-2222-2222-2222-222222222222',
        meter_id: 'aaaa2222-2222-2222-2222-222222222222',
        rule_code: 'OFF_PEAK_BASELOAD_PATTERN',
        dedupe_key: 'north:air:baseload',
        title: 'Eliminate off-shift compressor short-cycling',
        category: 'Compressed Air',
        summary: 'Compressor draws 260 kW in 18-minute bursts overnight.',
        monthly_kwh_savings: '19400.00',
        annual_cost_savings: '27470.00',
        payback_months: '1.5',
        cost_estimate_status: 'available',
        savings_basis: 'estimated_excess_avoidance',
        priority: 'High',
        status: 'Recommended',
        updated_at: '2026-11-18T14:00:00Z',
      },
      {
        id: 'd2222222-2222-2222-2222-222222222222',
        facility_id: 'north-assembly',
        zone_id: '11111111-1111-1111-1111-111111111111',
        meter_id: 'aaaa1111-1111-1111-1111-111111111111',
        rule_code: 'LOW_POWER_FACTOR',
        dedupe_key: 'north:cnc:pf',
        title: 'Engage Capacitor Bank Stage 3 on CNC feeder',
        category: 'Power Quality',
        summary: 'Correct lagging reactive power factor.',
        monthly_kwh_savings: '3100.00',
        annual_cost_savings: null,
        payback_months: null,
        cost_estimate_status: 'not_quantifiable',
        savings_basis: 'unquantified_telemetry',
        priority: 'Medium',
        status: 'Recommended',
        updated_at: '2026-11-18T14:00:00Z',
      },
    ],
    'foundry-press': [],
  };

  let metersState: Record<string, MeterResponse[]> = {
    'north-assembly': [...METERS_BY_FACILITY['north-assembly']],
    'foundry-press': [...METERS_BY_FACILITY['foundry-press']],
  };

  const paginate = <T,>(items: T[]) => ({
    items,
    total: items.length,
    page: 1,
    page_size: 100,
    pages: items.length > 0 ? 1 : 0,
  });

  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const urlStr = typeof input === 'string' ? input : input.toString();
    const url = new URL(urlStr);
    const path = url.pathname.replace(/^\/api\/v1/, '');
    const method = (init?.method ?? 'GET').toUpperCase();

    const json = (data: unknown, status = 200) =>
      new Response(JSON.stringify(data), {
        status,
        headers: { 'Content-Type': 'application/json' },
      });

    if (path === '/facilities' && method === 'GET') {
      return json(paginate(FACILITIES_FIXTURE));
    }

    if (path === '/users' && method === 'GET') {
      return json([ENGINEER_USER, ADMIN_USER]);
    }

    if (path === '/zones' && method === 'GET') {
      const facId = url.searchParams.get('facility_id') ?? 'north-assembly';
      return json(paginate(ZONES_BY_FACILITY[facId] ?? []));
    }

    if (path === '/meters' && method === 'GET') {
      const facId = url.searchParams.get('facility_id') ?? 'north-assembly';
      return json(paginate(metersState[facId] ?? []));
    }

    if (path.startsWith('/meters/') && method === 'PATCH') {
      const meterId = path.split('/')[2];
      const body = JSON.parse(String(init?.body ?? '{}')) as { last_calibrated_at?: string };
      for (const facId of Object.keys(metersState)) {
        const idx = metersState[facId].findIndex((m) => m.id === meterId);
        if (idx >= 0) {
          const updated = {
            ...metersState[facId][idx],
            last_calibrated_at: body.last_calibrated_at ?? metersState[facId][idx].last_calibrated_at,
          };
          metersState[facId][idx] = updated;
          return json(updated);
        }
      }
      return json({ detail: 'Meter not found' }, 404);
    }

    if (path === '/telemetry/readings' && method === 'GET') {
      const facId = url.searchParams.get('facility_id') ?? 'north-assembly';
      const zoneId = url.searchParams.get('zone_id');
      const meterId = url.searchParams.get('meter_id');
      let list = READINGS_BY_FACILITY[facId] ?? [];
      if (zoneId) list = list.filter((r) => r.zone_id === zoneId);
      if (meterId) list = list.filter((r) => r.meter_id === meterId);
      return json(paginate(list));
    }

    if (path === '/analytics/summary' && method === 'GET') {
      const facId = url.searchParams.get('facility_id') ?? 'north-assembly';
      const timeWindow = url.searchParams.get('time_window') ?? '24h';
      const includeSimulated = url.searchParams.get('include_simulated') === 'true';
      const raw = READINGS_BY_FACILITY[facId] ?? [];
      const scoped = includeSimulated ? raw : raw.filter((r) => r.source !== 'simulation');
      const totalKwh = scoped.reduce((sum, r) => sum + Number(r.energy_kwh), 0);
      const avgKw =
        scoped.length > 0
          ? Number(
              (scoped.reduce((sum, r) => sum + Number(r.actual_kw), 0) / scoped.length).toFixed(1)
            )
          : 0;
      const peakKw = scoped.reduce((mx, r) => Math.max(mx, Number(r.actual_kw)), 0);
      const summary: AnalyticsSummaryResponse = {
        facility_id: facId,
        zone_id: url.searchParams.get('zone_id'),
        time_window: timeWindow,
        include_simulated: includeSimulated,
        window_start: '2026-11-17T15:00:00Z',
        window_end: '2026-11-18T15:00:00Z',
        latest_recorded_at: scoped.length > 0 ? scoped[scoped.length - 1].recorded_at : null,
        reading_count: scoped.length,
        baselined_reading_count: scoped.filter((r) => r.baseline_kw !== null).length,
        total_kwh: Number(totalKwh.toFixed(2)),
        total_mwh: Number((totalKwh / 1000).toFixed(3)),
        avg_demand_kw: avgKw,
        peak_demand_kw: peakKw,
        contracted_demand_kw: 1850,
        demand_headroom_pct: Number((((1850 - peakKw) / 1850) * 100).toFixed(1)),
        avg_power_factor: 0.89,
        previous_total_kwh: 900,
        consumption_trend_pct: Number((((totalKwh - 900) / 900) * 100).toFixed(1)),
        open_anomalies_count: (anomaliesState[facId] ?? []).filter((a) => a.status !== 'Resolved').length,
        critical_anomalies_count: (anomaliesState[facId] ?? []).filter(
          (a) => a.status !== 'Resolved' && a.severity === 'Critical'
        ).length,
        potential_annual_savings: 27470,
        has_quantified_savings: true,
        unquantified_insights_count: 1,
        zone_breakdown: (ZONES_BY_FACILITY[facId] ?? []).map((z, idx) => ({
          zone_id: z.id,
          slug: z.slug,
          name: z.name,
          primary_meter_code: z.primary_meter_code,
          kwh_used: idx === 0 ? 600 : 438,
          share_pct: idx === 0 ? 57.8 : 42.2,
          avg_kw: idx === 0 ? 600 : 438,
          peak_kw: idx === 0 ? 600 : 438,
          power_factor: idx === 0 ? 0.94 : 0.84,
          delta_vs_baseline_pct: idx === 0 ? 1.7 : 68.5,
          derived_status: z.status,
          reading_count: 1,
        })),
        meter_snapshots: (metersState[facId] ?? []).map((m) => ({
          meter_id: m.id,
          meter_code: m.meter_code,
          zone_id: m.zone_id,
          latest_recorded_at: '2026-11-18T14:00:00Z',
          latest_kw: Number(m.current_kw),
          avg_kw: Number(m.current_kw),
          peak_kw: Number(m.current_kw),
          latest_power_factor: Number(m.power_factor),
          reading_count: 1,
          open_anomalies_count: 0,
          derived_status: m.status,
        })),
        series: [],
        heatmap_matrix: Array.from({ length: 7 }, () => Array.from({ length: 24 }, () => 0)),
      };
      return json(summary);
    }

    if (path === '/anomalies' && method === 'GET') {
      const facId = url.searchParams.get('facility_id') ?? 'north-assembly';
      return json(paginate(anomaliesState[facId] ?? []));
    }

    if (path.match(/^\/anomalies\/[^/]+$/) && method === 'GET') {
      const id = path.split('/')[2];
      const found = Object.values(anomaliesState)
        .flat()
        .find((a) => a.id === id);
      if (!found) return json({ detail: 'Not found' }, 404);
      const detail: AnomalyDetailResponse = {
        ...found,
        waveform: [260, 270, 410, 438, 390, 280],
        baseline_waveform: [255, 258, 260, 260, 262, 259],
      };
      return json(detail);
    }

    if (path.match(/^\/anomalies\/[^/]+\/history$/) && method === 'GET') {
      const id = path.split('/')[2];
      const logs: AnomalyWorkflowLogResponse[] = [
        {
          id: 'log-1',
          anomaly_id: id,
          from_status: null,
          to_status: 'Open',
          from_assignee_id: null,
          to_assignee_id: null,
          changed_by_user_id: null,
          note: 'Detected by analytics engine',
          changed_at: '2026-11-18T14:00:00Z',
        },
      ];
      return json(logs);
    }

    if (path.match(/^\/anomalies\/[^/]+\/(acknowledge|investigate|resolve|reopen)$/) && method === 'POST') {
      const [, , id, action] = path.split('/');
      for (const facId of Object.keys(anomaliesState)) {
        const idx = anomaliesState[facId].findIndex((a) => a.id === id);
        if (idx >= 0) {
          const nextStatus =
            action === 'acknowledge'
              ? 'Acknowledged'
              : action === 'investigate'
                ? 'Assigned'
                : action === 'resolve'
                  ? 'Resolved'
                  : 'Open';
          const updated: AnomalyResponse = {
            ...anomaliesState[facId][idx],
            status: nextStatus,
          };
          anomaliesState[facId][idx] = updated;
          return json({
            ...updated,
            waveform: [260, 270, 410, 438, 390, 280],
            baseline_waveform: [255, 258, 260, 260, 262, 259],
          });
        }
      }
      return json({ detail: 'Anomaly not found' }, 404);
    }

    if (path === '/insights' && method === 'GET') {
      const facId = url.searchParams.get('facility_id') ?? 'north-assembly';
      return json(paginate(insightsState[facId] ?? []));
    }

    if (path.match(/^\/insights\/[^/]+$/) && method === 'GET') {
      const id = path.split('/')[2];
      const found = Object.values(insightsState)
        .flat()
        .find((i) => i.id === id);
      if (!found) return json({ detail: 'Not found' }, 404);
      const detail: InsightDetailResponse = {
        ...found,
        evidence: { avg_excess_kw: 178, affected_intervals: 4 },
      };
      return json(detail);
    }

    if (path.match(/^\/insights\/[^/]+\/history$/) && method === 'GET') {
      const id = path.split('/')[2];
      const logs: InsightWorkflowLogResponse[] = [
        {
          id: 'ilog-1',
          insight_id: id,
          from_status: null,
          to_status: 'Recommended',
          changed_by_user_id: null,
          note: 'Rule triggered',
          changed_at: '2026-11-18T14:00:00Z',
        },
      ];
      return json(logs);
    }

    if (path.match(/^\/insights\/[^/]+$/) && method === 'PATCH') {
      if (options?.failInsightsPatchWith409) {
        return json(
          { detail: 'Cannot reactivate insight while an active insight with the same dedupe_key exists.' },
          409
        );
      }
      const id = path.split('/')[2];
      const body = JSON.parse(String(init?.body ?? '{}')) as { status: InsightResponse['status'] };
      for (const facId of Object.keys(insightsState)) {
        const idx = insightsState[facId].findIndex((i) => i.id === id);
        if (idx >= 0) {
          const updated: InsightResponse = {
            ...insightsState[facId][idx],
            status: body.status,
          };
          insightsState[facId][idx] = updated;
          return json({ ...updated, evidence: null });
        }
      }
      return json({ detail: 'Insight not found' }, 404);
    }

    return json({ detail: `Unhandled mock route: ${method} ${path}` }, 404);
  });
}

describe('EneryGrid backend-integrated dashboard', () => {
  beforeEach(() => {
    setStoredAccessToken('valid-test-jwt');
  });

  afterEach(() => {
    clearStoredAccessToken();
    vi.restoreAllMocks();
  });

  it('loads real facilities, zones, meters, telemetry, anomalies, and insights and applies zone filtering consistently', async () => {
    const fetchMock = createBackendFetchMock();
    vi.stubGlobal('fetch', fetchMock);

    render(<Dashboard user={ENGINEER_USER} onLogout={vi.fn()} />);

    // Wait for backend facility data to hydrate
    await waitFor(() => {
      expect(screen.getAllByText('ANM-102').length).toBeGreaterThanOrEqual(1);
    });

    expect(screen.getByText('Not quantifiable')).toBeInTheDocument();

    // Scope by Compressed Air Header zone
    fireEvent.click(screen.getByRole('button', { name: /Compressed Air Header/i }));

    expect(
      screen.getByRole('heading', {
        name: /Load Profile & Statistical Baseline Envelope · Compressed Air Header/,
      })
    ).toBeInTheDocument();
    expect(
      screen.getByRole('heading', {
        name: /Actionable Engineering Insights & Load Optimization · Compressed Air Header/,
      })
    ).toBeInTheDocument();

    // Switch to Meters & Equipment and verify zone filter & backend calibration audit PATCH
    fireEvent.click(screen.getByRole('button', { name: /Meters & Equipment/i }));
    expect(screen.getByText('Rotary Screw Compressor #2')).toBeInTheDocument();
    expect(screen.queryByText('5-Axis CNC Bank A')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Log Audit' }));
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Audited Today' })).toBeDisabled();
    });

    expect(
      fetchMock.mock.calls.some(
        ([u, init]) =>
          String(u).includes('/meters/aaaa2222-2222-2222-2222-222222222222') &&
          init?.method === 'PATCH'
      )
    ).toBe(true);
  });

  it('enforces required resolution notes for anomalies and executes resolve workflow', async () => {
    const fetchMock = createBackendFetchMock();
    vi.stubGlobal('fetch', fetchMock);

    render(<Dashboard user={ENGINEER_USER} onLogout={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getAllByText('ANM-102').length).toBeGreaterThanOrEqual(1);
    });

    fireEvent.click(screen.getByRole('button', { name: /Anomaly Detection/i }));
    fireEvent.click(screen.getByRole('button', { name: 'Resolve' }));

    // Blank submission blocked by client validation
    fireEvent.click(screen.getByRole('button', { name: 'Confirm Resolution' }));
    expect(
      screen.getByText('A resolution note is required to close this anomaly.')
    ).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Resolution Note (Required)'), {
      target: { value: 'Replaced leaking Bay 4 solenoid valve.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Confirm Resolution' }));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Reopen' })).toBeInTheDocument();
    });

    expect(
      fetchMock.mock.calls.some(
        ([u, init]) =>
          String(u).includes('/anomalies/c1111111-1111-1111-1111-111111111111/resolve') &&
          init?.method === 'POST'
      )
    ).toBe(true);
  });

  it('persists insight status via PATCH /insights/{id} and surfaces 409 conflicts clearly', async () => {
    const fetchMock = createBackendFetchMock({ failInsightsPatchWith409: true });
    vi.stubGlobal('fetch', fetchMock);

    render(<Dashboard user={ENGINEER_USER} onLogout={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText('Eliminate off-shift compressor short-cycling')).toBeInTheDocument();
    });

    const insightsSection = screen
      .getByRole('heading', { name: /Actionable Engineering Insights/i })
      .closest('div')!.parentElement!.parentElement!;

    const implementedButtons = within(insightsSection).getAllByRole('button', {
      name: 'Implemented',
    });
    fireEvent.click(implementedButtons[0]);

    await waitFor(() => {
      expect(
        within(insightsSection).getByText(/Cannot reactivate insight/i)
      ).toBeInTheDocument();
    });
  });

  it('enforces RBAC read-only view for viewer users and shows Manage Assets only for admins', async () => {
    vi.stubGlobal('fetch', createBackendFetchMock());

    const { unmount } = render(<Dashboard user={VIEWER_USER} onLogout={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getAllByText('ANM-102').length).toBeGreaterThanOrEqual(1);
    });

    expect(screen.getByText('Read-Only Monitoring')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Resolve' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Ingest Telemetry' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Manage Assets' })).not.toBeInTheDocument();

    unmount();

    render(<Dashboard user={ADMIN_USER} onLogout={vi.fn()} />);
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Manage Assets' })).toBeInTheDocument();
    });
  });

  it('handles API errors with retry recovery and exports CSV from GET /telemetry/readings', async () => {
    const createObjectURLSpy = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:mock-csv');
    const revokeObjectURLSpy = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
    const anchorClickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => {});

    try {
      const mockFetch = createBackendFetchMock();
      let shouldFailFacilities = true;
      vi.stubGlobal(
        'fetch',
        vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
          const url = typeof input === 'string' ? input : input.toString();
          if (shouldFailFacilities && url.includes('/facilities')) {
            return new Response(JSON.stringify({ detail: 'Database temporarily unavailable.' }), {
              status: 503,
              headers: { 'Content-Type': 'application/json' },
            });
          }
          return mockFetch(input, init);
        })
      );

      render(<Dashboard user={ENGINEER_USER} onLogout={vi.fn()} />);

      await waitFor(() => {
        expect(screen.getByText('Database temporarily unavailable.')).toBeInTheDocument();
      });

      shouldFailFacilities = false;
      fireEvent.click(screen.getByRole('button', { name: 'Retry Request' }));

      await waitFor(() => {
        expect(screen.getAllByText('ANM-102').length).toBeGreaterThanOrEqual(1);
      });

      // Open Export CSV modal and download backend readings
      fireEvent.click(screen.getByRole('button', { name: /Export CSV/i }));
      const dialog = screen.getByRole('dialog');
      await waitFor(() => {
        expect(within(dialog).getByText('2 rows')).toBeInTheDocument();
      });

      fireEvent.click(within(dialog).getByRole('button', { name: /Download CSV/i }));
      expect(createObjectURLSpy).toHaveBeenCalledTimes(1);
      expect(anchorClickSpy).toHaveBeenCalledTimes(1);
    } finally {
      createObjectURLSpy.mockRestore();
      revokeObjectURLSpy.mockRestore();
      anchorClickSpy.mockRestore();
    }
  });

  it('separates measured/imported telemetry from simulation readings and hydrates server analytics summary KPIs', async () => {
    const fetchMock = createBackendFetchMock();
    vi.stubGlobal('fetch', fetchMock);

    render(<Dashboard user={ENGINEER_USER} onLogout={vi.fn()} />);

    // Default source_scope is 'measured' -> excludes simulated reading #103 (910 kW)
    await waitFor(() => {
      expect(screen.getByText(/Avg 519 kW/i)).toBeInTheDocument();
    });
    expect(screen.getByText(/\+15\.3% vs prior 24h/i)).toBeInTheDocument();
    expect(screen.getByText(/2 intervals/i)).toBeInTheDocument();

    // Switching Telemetry Source Scope to Simulation Only computes KPIs from simulated reading #103 only
    fireEvent.click(screen.getByRole('button', { name: 'Simulation Only' }));
    await waitFor(() => {
      expect(screen.getByText(/Avg 910 kW/i)).toBeInTheDocument();
    });
    expect(screen.getByText(/1 interval\(s\) loaded/i)).toBeInTheDocument();
  });
});

