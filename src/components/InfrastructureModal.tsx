import React, { useEffect, useState } from 'react';
import { Building2, Cpu, Layers, Loader2, X } from 'lucide-react';
import { createFacility, deactivateFacility } from '../api/facilities';
import { deactivateMeter, registerMeter } from '../api/meters';
import { createZone, deactivateZone } from '../api/zones';
import { HealthStatus, MeterResponse, ZoneResponse } from '../types/api';
import { MappedFacility } from '../utils/energyMappers';

interface InfrastructureModalProps {
  isOpen: boolean;
  onClose: () => void;
  facilities: MappedFacility[];
  activeFacilityId: string | null;
  zones: ZoneResponse[];
  meters: MeterResponse[];
  onChanged: (preferredFacilityId?: string) => void | Promise<void>;
}

type InfraTab = 'facilities' | 'zones' | 'meters';

export const InfrastructureModal: React.FC<InfrastructureModalProps> = ({
  isOpen,
  onClose,
  facilities,
  activeFacilityId,
  zones,
  meters,
  onChanged,
}) => {
  const [tab, setTab] = useState<InfraTab>('facilities');
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  // Facility form state
  const [facId, setFacId] = useState('');
  const [facCode, setFacCode] = useState('');
  const [facName, setFacName] = useState('');
  const [facLocation, setFacLocation] = useState('');
  const [facTimezone, setFacTimezone] = useState('UTC');
  const [facCurrency, setFacCurrency] = useState('USD');
  const [facDemand, setFacDemand] = useState('1500');
  const [facOffPeak, setFacOffPeak] = useState('0.1100');
  const [facMidPeak, setFacMidPeak] = useState('0.1500');
  const [facPeak, setFacPeak] = useState('0.2100');

  // Zone form state
  const [zoneSlug, setZoneSlug] = useState('');
  const [zoneName, setZoneName] = useState('');
  const [zonePrimaryMeter, setZonePrimaryMeter] = useState('');
  const [zoneSharePct, setZoneSharePct] = useState('25');
  const [zoneStatus, setZoneStatus] = useState<HealthStatus>('Nominal');

  // Meter form state
  const [meterZoneId, setMeterZoneId] = useState('');
  const [meterCode, setMeterCode] = useState('');
  const [meterEquipment, setMeterEquipment] = useState('');
  const [meterRatedKw, setMeterRatedKw] = useState('500');
  const [meterPf, setMeterPf] = useState('0.94');
  const [meterThd, setMeterThd] = useState('2.8');
  const [meterCalibrated, setMeterCalibrated] = useState(() =>
    new Date().toISOString().slice(0, 10)
  );

  useEffect(() => {
    if (isOpen) {
      setErrorMessage(null);
      setSuccessMessage(null);
      const firstActiveZone = zones.find((z) => z.is_active) ?? zones[0];
      setMeterZoneId(firstActiveZone?.id ?? '');
    }
  }, [isOpen, zones]);

  if (!isOpen) return null;

  const handleCreateFacility = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setErrorMessage(null);
    setSuccessMessage(null);
    try {
      const created = await createFacility({
        id: facId.trim().toLowerCase(),
        code: facCode.trim(),
        name: facName.trim(),
        location: facLocation.trim(),
        timezone: facTimezone.trim(),
        currency_code: facCurrency.trim().toUpperCase(),
        contracted_demand_kw: Number(facDemand),
        off_peak_tariff_rate: Number(facOffPeak),
        mid_peak_tariff_rate: Number(facMidPeak),
        peak_tariff_rate: Number(facPeak),
      });
      setSuccessMessage(`Created facility ${created.name} (${created.code}).`);
      setFacId('');
      setFacCode('');
      setFacName('');
      setFacLocation('');
      await onChanged(created.id);
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : 'Unable to create facility.');
    } finally {
      setSubmitting(false);
    }
  };

  const handleCreateZone = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeFacilityId) return;
    setSubmitting(true);
    setErrorMessage(null);
    setSuccessMessage(null);
    try {
      const created = await createZone({
        facility_id: activeFacilityId,
        slug: zoneSlug.trim().toLowerCase(),
        name: zoneName.trim(),
        primary_meter_code: zonePrimaryMeter.trim(),
        share_pct: Number(zoneSharePct),
        status: zoneStatus,
      });
      setSuccessMessage(`Created zone ${created.name}.`);
      setZoneSlug('');
      setZoneName('');
      setZonePrimaryMeter('');
      await onChanged();
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : 'Unable to create zone.');
    } finally {
      setSubmitting(false);
    }
  };

  const handleCreateMeter = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeFacilityId || !meterZoneId) {
      setErrorMessage('Select an active facility and zone first.');
      return;
    }
    setSubmitting(true);
    setErrorMessage(null);
    setSuccessMessage(null);
    try {
      const created = await registerMeter({
        facility_id: activeFacilityId,
        zone_id: meterZoneId,
        meter_code: meterCode.trim(),
        equipment_name: meterEquipment.trim(),
        rated_kw: Number(meterRatedKw),
        power_factor: Number(meterPf),
        thd_pct: Number(meterThd),
        last_calibrated_at: meterCalibrated,
      });
      setSuccessMessage(`Registered meter ${created.meter_code}.`);
      setMeterCode('');
      setMeterEquipment('');
      await onChanged();
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : 'Unable to register meter.');
    } finally {
      setSubmitting(false);
    }
  };

  const handleDeactivateFacility = async (id: string) => {
    setSubmitting(true);
    setErrorMessage(null);
    setSuccessMessage(null);
    try {
      await deactivateFacility(id);
      setSuccessMessage(`Deactivated facility ${id}.`);
      await onChanged();
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : 'Unable to deactivate facility.');
    } finally {
      setSubmitting(false);
    }
  };

  const handleDeactivateZone = async (id: string) => {
    setSubmitting(true);
    setErrorMessage(null);
    setSuccessMessage(null);
    try {
      await deactivateZone(id);
      setSuccessMessage('Zone deactivated while preserving historical records.');
      await onChanged();
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : 'Unable to deactivate zone.');
    } finally {
      setSubmitting(false);
    }
  };

  const handleDeactivateMeter = async (id: string) => {
    setSubmitting(true);
    setErrorMessage(null);
    setSuccessMessage(null);
    try {
      await deactivateMeter(id);
      setSuccessMessage('Meter deactivated while preserving telemetry history.');
      await onChanged();
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : 'Unable to deactivate meter.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="infra-modal-title"
        className="bg-white border border-slate-200 rounded-lg shadow-xl w-full max-w-2xl max-h-[90vh] flex flex-col overflow-hidden"
      >
        <div className="px-5 py-4 border-b border-slate-200 flex items-start justify-between gap-4">
          <div>
            <h2 id="infra-modal-title" className="text-base font-semibold text-slate-900">
              Admin Infrastructure Management
            </h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Create or soft-deactivate facilities, sub-meter zones, and meters
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close infrastructure modal"
            className="p-1.5 text-slate-400 hover:text-slate-700 rounded-md hover:bg-slate-100"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="px-5 pt-3 border-b border-slate-100 flex gap-2">
          {[
            { id: 'facilities' as const, label: 'Facilities', icon: Building2 },
            { id: 'zones' as const, label: 'Zones', icon: Layers },
            { id: 'meters' as const, label: 'Meters', icon: Cpu },
          ].map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => {
                  setTab(item.id);
                  setErrorMessage(null);
                  setSuccessMessage(null);
                }}
                className={`inline-flex items-center gap-1.5 px-3 py-2 text-xs font-medium border-b-2 transition-colors ${
                  tab === item.id
                    ? 'border-sky-700 text-sky-800'
                    : 'border-transparent text-slate-500 hover:text-slate-800'
                }`}
              >
                <Icon className="w-3.5 h-3.5" aria-hidden="true" />
                {item.label}
              </button>
            );
          })}
        </div>

        <div className="p-5 overflow-y-auto space-y-5">
          {errorMessage && (
            <div
              role="alert"
              className="px-3.5 py-2.5 rounded-md bg-red-50 border border-red-200 text-xs text-red-700"
            >
              {errorMessage}
            </div>
          )}
          {successMessage && (
            <div className="px-3.5 py-2.5 rounded-md bg-emerald-50 border border-emerald-200 text-xs text-emerald-800">
              {successMessage}
            </div>
          )}

          {tab === 'facilities' && (
            <div className="space-y-5">
              <form onSubmit={handleCreateFacility} className="space-y-3">
                <div className="text-xs font-semibold text-slate-900">Register New Facility</div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                  <input
                    required
                    placeholder="Slug ID (e.g. east-foundry)"
                    value={facId}
                    onChange={(e) => setFacId(e.target.value)}
                    className="px-3 py-2 border border-slate-200 rounded-md"
                  />
                  <input
                    required
                    placeholder="Code (e.g. PLT-EF04)"
                    value={facCode}
                    onChange={(e) => setFacCode(e.target.value)}
                    className="px-3 py-2 border border-slate-200 rounded-md"
                  />
                  <input
                    required
                    placeholder="Facility Name"
                    value={facName}
                    onChange={(e) => setFacName(e.target.value)}
                    className="px-3 py-2 border border-slate-200 rounded-md"
                  />
                  <input
                    required
                    placeholder="Location"
                    value={facLocation}
                    onChange={(e) => setFacLocation(e.target.value)}
                    className="px-3 py-2 border border-slate-200 rounded-md"
                  />
                  <input
                    required
                    placeholder="IANA Timezone (e.g. America/Detroit)"
                    value={facTimezone}
                    onChange={(e) => setFacTimezone(e.target.value)}
                    className="px-3 py-2 border border-slate-200 rounded-md"
                  />
                  <input
                    required
                    maxLength={3}
                    placeholder="Currency (e.g. USD)"
                    value={facCurrency}
                    onChange={(e) => setFacCurrency(e.target.value)}
                    className="px-3 py-2 border border-slate-200 rounded-md"
                  />
                  <input
                    required
                    type="number"
                    step="0.01"
                    placeholder="Contracted Demand kW"
                    value={facDemand}
                    onChange={(e) => setFacDemand(e.target.value)}
                    className="px-3 py-2 border border-slate-200 rounded-md font-mono"
                  />
                  <div className="grid grid-cols-3 gap-1.5">
                    <input
                      required
                      type="number"
                      step="0.0001"
                      placeholder="Off-peak"
                      value={facOffPeak}
                      onChange={(e) => setFacOffPeak(e.target.value)}
                      aria-label="Off-peak tariff rate"
                      className="px-2 py-2 border border-slate-200 rounded-md font-mono"
                    />
                    <input
                      required
                      type="number"
                      step="0.0001"
                      placeholder="Mid"
                      value={facMidPeak}
                      onChange={(e) => setFacMidPeak(e.target.value)}
                      aria-label="Mid-peak tariff rate"
                      className="px-2 py-2 border border-slate-200 rounded-md font-mono"
                    />
                    <input
                      required
                      type="number"
                      step="0.0001"
                      placeholder="Peak"
                      value={facPeak}
                      onChange={(e) => setFacPeak(e.target.value)}
                      aria-label="Peak tariff rate"
                      className="px-2 py-2 border border-slate-200 rounded-md font-mono"
                    />
                  </div>
                </div>
                <button
                  type="submit"
                  disabled={submitting}
                  className="inline-flex items-center gap-1.5 px-3.5 py-2 text-xs font-medium bg-slate-900 text-white rounded-md hover:bg-slate-800 disabled:opacity-50"
                >
                  {submitting && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                  Create Facility
                </button>
              </form>

              <div className="border-t border-slate-100 pt-3">
                <div className="text-xs font-semibold text-slate-900 mb-2">Existing Facilities</div>
                <ul className="divide-y divide-slate-100 text-xs">
                  {facilities.map((fac) => (
                    <li key={fac.id} className="py-2 flex items-center justify-between gap-3">
                      <div>
                        <span className="font-medium text-slate-900">{fac.name}</span>{' '}
                        <span className="font-mono text-slate-500">({fac.code})</span>
                        {!fac.isActive && (
                          <span className="ml-2 text-slate-400">[Deactivated]</span>
                        )}
                      </div>
                      {fac.isActive && (
                        <button
                          type="button"
                          disabled={submitting}
                          onClick={() => void handleDeactivateFacility(fac.id)}
                          className="px-2.5 py-1 text-xs text-red-700 border border-red-200 rounded hover:bg-red-50 disabled:opacity-50"
                        >
                          Deactivate
                        </button>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}

          {tab === 'zones' && (
            <div className="space-y-5">
              <form onSubmit={handleCreateZone} className="space-y-3">
                <div className="text-xs font-semibold text-slate-900">
                  Add Zone to Active Facility ({activeFacilityId ?? 'None'})
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                  <input
                    required
                    placeholder="Zone Slug (e.g. chiller-bank)"
                    value={zoneSlug}
                    onChange={(e) => setZoneSlug(e.target.value)}
                    className="px-3 py-2 border border-slate-200 rounded-md"
                  />
                  <input
                    required
                    placeholder="Zone Name"
                    value={zoneName}
                    onChange={(e) => setZoneName(e.target.value)}
                    className="px-3 py-2 border border-slate-200 rounded-md"
                  />
                  <input
                    required
                    placeholder="Primary Meter Code (e.g. MTR-301)"
                    value={zonePrimaryMeter}
                    onChange={(e) => setZonePrimaryMeter(e.target.value)}
                    className="px-3 py-2 border border-slate-200 rounded-md font-mono"
                  />
                  <div className="grid grid-cols-2 gap-2">
                    <input
                      required
                      type="number"
                      min="0"
                      max="100"
                      step="0.01"
                      placeholder="Share %"
                      value={zoneSharePct}
                      onChange={(e) => setZoneSharePct(e.target.value)}
                      className="px-3 py-2 border border-slate-200 rounded-md font-mono"
                    />
                    <select
                      value={zoneStatus}
                      onChange={(e) => setZoneStatus(e.target.value as HealthStatus)}
                      className="px-2.5 py-2 border border-slate-200 rounded-md"
                    >
                      <option value="Nominal">Nominal</option>
                      <option value="Warning">Warning</option>
                      <option value="Fault">Fault</option>
                    </select>
                  </div>
                </div>
                <button
                  type="submit"
                  disabled={submitting || !activeFacilityId}
                  className="inline-flex items-center gap-1.5 px-3.5 py-2 text-xs font-medium bg-slate-900 text-white rounded-md hover:bg-slate-800 disabled:opacity-50"
                >
                  Create Zone
                </button>
              </form>

              <div className="border-t border-slate-100 pt-3">
                <div className="text-xs font-semibold text-slate-900 mb-2">Facility Zones</div>
                <ul className="divide-y divide-slate-100 text-xs">
                  {zones.map((z) => (
                    <li key={z.id} className="py-2 flex items-center justify-between gap-3">
                      <div>
                        <span className="font-medium text-slate-900">{z.name}</span>{' '}
                        <span className="font-mono text-slate-500">({z.primary_meter_code})</span>
                        {!z.is_active && <span className="ml-2 text-slate-400">[Deactivated]</span>}
                      </div>
                      {z.is_active && (
                        <button
                          type="button"
                          disabled={submitting}
                          onClick={() => void handleDeactivateZone(z.id)}
                          className="px-2.5 py-1 text-xs text-red-700 border border-red-200 rounded hover:bg-red-50 disabled:opacity-50"
                        >
                          Deactivate
                        </button>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}

          {tab === 'meters' && (
            <div className="space-y-5">
              <form onSubmit={handleCreateMeter} className="space-y-3">
                <div className="text-xs font-semibold text-slate-900">Register Meter</div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                  <select
                    value={meterZoneId}
                    onChange={(e) => setMeterZoneId(e.target.value)}
                    className="px-3 py-2 border border-slate-200 rounded-md"
                  >
                    {zones
                      .filter((z) => z.is_active)
                      .map((z) => (
                        <option key={z.id} value={z.id}>
                          {z.name}
                        </option>
                      ))}
                  </select>
                  <input
                    required
                    placeholder="Meter Code (e.g. MTR-302)"
                    value={meterCode}
                    onChange={(e) => setMeterCode(e.target.value)}
                    className="px-3 py-2 border border-slate-200 rounded-md font-mono"
                  />
                  <input
                    required
                    placeholder="Equipment Name"
                    value={meterEquipment}
                    onChange={(e) => setMeterEquipment(e.target.value)}
                    className="px-3 py-2 border border-slate-200 rounded-md"
                  />
                  <input
                    required
                    type="number"
                    step="0.01"
                    min="1"
                    placeholder="Rated kW"
                    value={meterRatedKw}
                    onChange={(e) => setMeterRatedKw(e.target.value)}
                    className="px-3 py-2 border border-slate-200 rounded-md font-mono"
                  />
                  <div className="grid grid-cols-2 gap-2">
                    <input
                      required
                      type="number"
                      step="0.01"
                      min="0"
                      max="1"
                      placeholder="PF"
                      value={meterPf}
                      onChange={(e) => setMeterPf(e.target.value)}
                      className="px-3 py-2 border border-slate-200 rounded-md font-mono"
                    />
                    <input
                      required
                      type="number"
                      step="0.1"
                      min="0"
                      placeholder="THD %"
                      value={meterThd}
                      onChange={(e) => setMeterThd(e.target.value)}
                      className="px-3 py-2 border border-slate-200 rounded-md font-mono"
                    />
                  </div>
                  <input
                    required
                    type="date"
                    value={meterCalibrated}
                    onChange={(e) => setMeterCalibrated(e.target.value)}
                    className="px-3 py-2 border border-slate-200 rounded-md font-mono"
                  />
                </div>
                <button
                  type="submit"
                  disabled={submitting || !meterZoneId}
                  className="inline-flex items-center gap-1.5 px-3.5 py-2 text-xs font-medium bg-slate-900 text-white rounded-md hover:bg-slate-800 disabled:opacity-50"
                >
                  Register Meter
                </button>
              </form>

              <div className="border-t border-slate-100 pt-3">
                <div className="text-xs font-semibold text-slate-900 mb-2">Facility Meters</div>
                <ul className="divide-y divide-slate-100 text-xs">
                  {meters.map((m) => (
                    <li key={m.id} className="py-2 flex items-center justify-between gap-3">
                      <div>
                        <span className="font-mono font-medium text-slate-900">
                          {m.meter_code}
                        </span>{' '}
                        <span className="text-slate-600">— {m.equipment_name}</span>
                        {!m.is_active && <span className="ml-2 text-slate-400">[Deactivated]</span>}
                      </div>
                      {m.is_active && (
                        <button
                          type="button"
                          disabled={submitting}
                          onClick={() => void handleDeactivateMeter(m.id)}
                          className="px-2.5 py-1 text-xs text-red-700 border border-red-200 rounded hover:bg-red-50 disabled:opacity-50"
                        >
                          Deactivate
                        </button>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
