import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { Dashboard } from './components/Dashboard';
import { AuthUser } from './types/auth';

const TEST_USER: AuthUser = {
  id: '00000000-0000-0000-0000-000000000001',
  email: 'engineer@energygrid.local',
  full_name: 'Plant Utility Engineer',
  role: 'utility_engineer',
  is_active: true,
  created_at: '2026-11-20T00:00:00Z',
};

const renderDashboard = (onLogout = vi.fn()) =>
  render(<Dashboard user={TEST_USER} onLogout={onLogout} />);

describe('EneryGrid dashboard integration', () => {
  it('applies zone-scoped filtering consistently across chart, heatmap, anomalies, insights, and meters', () => {
    renderDashboard();

    expect(
      screen.getByRole('heading', { name: 'Load Profile & Statistical Baseline Envelope' })
    ).toBeInTheDocument();

    // Select Compressed Air Header zone
    fireEvent.click(screen.getByRole('button', { name: /Compressed Air Header/i }));

    expect(
      screen.getByRole('heading', {
        name: /Load Profile & Statistical Baseline Envelope · Compressed Air Header/,
      })
    ).toBeInTheDocument();
    expect(
      screen.getByRole('heading', {
        name: /Weekly Load Intensity Matrix \(Day × Hour\) · Compressed Air Header/,
      })
    ).toBeInTheDocument();
    expect(
      screen.getByRole('heading', {
        name: /Statistical Anomaly Detection Queue · Compressed Air Header/,
      })
    ).toBeInTheDocument();
    expect(
      screen.getByRole('heading', {
        name: /Actionable Engineering Insights & Load Optimization · Compressed Air Header/,
      })
    ).toBeInTheDocument();

    // Verify Meters tab respects active zone filter
    fireEvent.click(screen.getByRole('button', { name: /Meters & Equipment/i }));
    expect(
      screen.getByRole('heading', {
        name: /Sub-Meter & Equipment Health Registry · Compressed Air Header/,
      })
    ).toBeInTheDocument();
    expect(screen.getByText('Rotary Screw Compressor #2')).toBeInTheDocument();
    expect(screen.queryByText('5-Axis CNC Bank A')).not.toBeInTheDocument();

    // Clear filter restores all meters
    fireEvent.click(screen.getByRole('button', { name: 'Show All Zones' }));
    expect(screen.getByText('5-Axis CNC Bank A')).toBeInTheDocument();
  });

  it('persists meter calibration audits across tab navigation', () => {
    renderDashboard();

    fireEvent.click(screen.getByRole('button', { name: /Meters & Equipment/i }));
    const auditButtons = screen.getAllByRole('button', { name: 'Log Audit' });
    fireEvent.click(auditButtons[0]);

    expect(screen.getByRole('button', { name: 'Audited Today' })).toBeDisabled();

    // Switch away and back
    fireEvent.click(screen.getByRole('button', { name: /Overview/i }));
    fireEvent.click(screen.getByRole('button', { name: /Meters & Equipment/i }));

    expect(screen.getByRole('button', { name: 'Audited Today' })).toBeDisabled();
  });

  it('updates anomaly workflow counts and prevents cross-facility state leakage', () => {
    renderDashboard();

    fireEvent.click(screen.getByRole('button', { name: /Anomaly Detection/i }));
    const resolveButtons = screen.getAllByRole('button', { name: 'Resolve' });
    const initialCount = resolveButtons.length;
    expect(initialCount).toBeGreaterThan(0);

    fireEvent.click(resolveButtons[0]);
    expect(screen.getAllByRole('button', { name: 'Resolve' })).toHaveLength(initialCount - 1);

    // Switch facility and ensure its anomalies remain Open
    fireEvent.change(screen.getByLabelText('Monitored Facility'), {
      target: { value: 'foundry-press' },
    });
    const foundryResolveButtons = screen.getAllByRole('button', { name: 'Resolve' });
    expect(foundryResolveButtons.length).toBeGreaterThan(0);
  });

  it('updates implemented savings when toggling insight status and detects simulated spike', () => {
    renderDashboard();

    const insightsSection = screen
      .getByRole('heading', { name: /Actionable Engineering Insights/i })
      .closest('div')!.parentElement!.parentElement!;

    expect(within(insightsSection).getByText('$0/yr')).toBeInTheDocument();

    const implementedButtons = within(insightsSection).getAllByRole('button', {
      name: 'Implemented',
    });
    fireEvent.click(implementedButtons[0]);
    expect(within(insightsSection).queryByText('$0/yr')).not.toBeInTheDocument();

    // Test synthetic load spike simulation
    const beforeAnomalies = screen.getAllByRole('button', { name: 'Resolve' }).length;
    fireEvent.click(screen.getByRole('button', { name: /Simulate Load Spike/i }));
    expect(screen.getAllByRole('button', { name: 'Resolve' }).length).toBe(beforeAnomalies + 1);
  });

  it('opens CSV export modal synced to active dashboard filters and exports filtered kWh/MWh data', () => {
    const createObjectURLSpy = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:mock-csv');
    const revokeObjectURLSpy = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
    const anchorClickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => {});

    try {
      renderDashboard();

      // Configure dashboard filters: Foundry facility + 7d window + Hydraulic Stamping Presses zone
      fireEvent.change(screen.getByLabelText('Monitored Facility'), {
        target: { value: 'foundry-press' },
      });
      fireEvent.click(screen.getByRole('button', { name: '7d' }));
      fireEvent.click(screen.getByRole('button', { name: /Hydraulic Stamping Presses/i }));

      // Capture KPI total MWh from dashboard to verify exact parity
      const kpiSection = screen.getByLabelText('Key Energy Metrics');
      const totalMwhText = within(kpiSection).getByText(/MWh$/).textContent!;
      const dashboardMwh = parseFloat(totalMwhText);

      // Open Export CSV modal
      fireEvent.click(screen.getByRole('button', { name: /Export CSV/i }));
      const dialog = screen.getByRole('dialog');
      expect(within(dialog).getByText('Export Energy Consumption CSV')).toBeInTheDocument();

      // Verify modal filters match dashboard selection
      expect((within(dialog).getByLabelText('Facility') as HTMLSelectElement).value).toBe(
        'foundry-press'
      );
      expect((within(dialog).getByLabelText('Zone') as HTMLSelectElement).value).toBe('stamping');
      expect((within(dialog).getByLabelText('Start Date') as HTMLInputElement).value).toBe(
        '2026-11-12'
      );
      expect((within(dialog).getByLabelText('End Date') as HTMLInputElement).value).toBe(
        '2026-11-18'
      );

      // Verify MWh total in export summary matches dashboard KPI
      const modalMwhText = within(dialog).getByText(/^\d+\.\d{3} MWh$/).textContent!;
      expect(parseFloat(modalMwhText)).toBeCloseTo(dashboardMwh, 1);

      // Change meter & date range inside modal, verify Reset to Dashboard Filters appears
      fireEvent.change(within(dialog).getByLabelText('Meter'), {
        target: { value: 'MTR-604' },
      });
      fireEvent.change(within(dialog).getByLabelText('Start Date'), {
        target: { value: '2026-11-14' },
      });
      fireEvent.change(within(dialog).getByLabelText('End Date'), {
        target: { value: '2026-11-15' },
      });
      expect(within(dialog).getByText('8 rows')).toBeInTheDocument();

      // Download CSV
      fireEvent.click(within(dialog).getByRole('button', { name: /Download CSV/i }));
      expect(createObjectURLSpy).toHaveBeenCalledTimes(1);
      expect(anchorClickSpy).toHaveBeenCalledTimes(1);
      expect(
        within(dialog).getByText(
          /Downloaded enerygrid-plt-fp02-stamping-mtr-604-2026-11-14-to-2026-11-15\.csv \(8 rows\)/
        )
      ).toBeInTheDocument();

      // Invalid date range disables download
      fireEvent.change(within(dialog).getByLabelText('Start Date'), {
        target: { value: '2026-11-20' },
      });
      expect(within(dialog).getByRole('button', { name: /Download CSV/i })).toBeDisabled();

      // Reset snaps back to dashboard filters
      fireEvent.click(within(dialog).getByRole('button', { name: /Reset to Dashboard Filters/i }));
      expect((within(dialog).getByLabelText('Start Date') as HTMLInputElement).value).toBe(
        '2026-11-12'
      );
      expect((within(dialog).getByLabelText('Meter') as HTMLSelectElement).value).toBe('');
    } finally {
      createObjectURLSpy.mockRestore();
      revokeObjectURLSpy.mockRestore();
      anchorClickSpy.mockRestore();
    }
  });
});

