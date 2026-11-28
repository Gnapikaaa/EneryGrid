import React, { useEffect, useState } from 'react';
import { Activity, CheckCircle2, FileUp, Loader2, Play, X } from 'lucide-react';
import { processAnalytics } from '../api/analytics';
import { ingestTelemetryReading, uploadTelemetryCsv } from '../api/telemetry';
import {
  AnalyticsProcessSummary,
  QualityFlag,
  TelemetryIngestionSummary,
  TelemetrySource,
} from '../types/api';
import { MappedMeter } from '../utils/energyMappers';

interface TelemetryIngestModalProps {
  isOpen: boolean;
  onClose: () => void;
  facilityId: string | null;
  facilityName: string;
  selectedZoneId: string | null;
  meters: MappedMeter[];
  onDataUpdated: () => void | Promise<void>;
}

type IngestTab = 'single' | 'csv' | 'analytics';

export const TelemetryIngestModal: React.FC<TelemetryIngestModalProps> = ({
  isOpen,
  onClose,
  facilityId,
  facilityName,
  selectedZoneId,
  meters,
  onDataUpdated,
}) => {
  const activeMeters = meters.filter((m) => m.isActive);
  const [tab, setTab] = useState<IngestTab>('single');
  const [meterId, setMeterId] = useState<string>(activeMeters[0]?.id ?? '');
  const [recordedAt, setRecordedAt] = useState<string>(() =>
    new Date().toISOString().slice(0, 16)
  );
  const [actualKw, setActualKw] = useState<string>('480');
  const [powerFactor, setPowerFactor] = useState<string>('0.92');
  const [ambientTempC, setAmbientTempC] = useState<string>('22.5');
  const [source, setSource] = useState<TelemetrySource>('meter_feed');
  const qualityFlag: QualityFlag = source === 'simulation' ? 'simulated' : 'valid';
  const [runAnalyticsAfter, setRunAnalyticsAfter] = useState<boolean>(true);

  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [atomicCsv, setAtomicCsv] = useState<boolean>(false);

  const [reprocess, setReprocess] = useState<boolean>(false);
  const [includeInsights, setIncludeInsights] = useState<boolean>(true);

  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [uploadSummary, setUploadSummary] = useState<TelemetryIngestionSummary | null>(null);
  const [analyticsSummary, setAnalyticsSummary] = useState<AnalyticsProcessSummary | null>(null);

  useEffect(() => {
    if (isOpen) {
      const scoped = selectedZoneId
        ? activeMeters.filter((m) => m.zoneId === selectedZoneId)
        : activeMeters;
      setMeterId(scoped[0]?.id ?? activeMeters[0]?.id ?? '');
      setErrorMessage(null);
      setSuccessMessage(null);
      setUploadSummary(null);
      setAnalyticsSummary(null);
    }
  }, [isOpen, selectedZoneId, meters]);

  if (!isOpen) return null;

  const handleSingleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!meterId) {
      setErrorMessage('Select an active meter before submitting a reading.');
      return;
    }
    const numericKw = Number(actualKw);
    const numericPf = Number(powerFactor);
    if (!Number.isFinite(numericKw) || numericKw < 0) {
      setErrorMessage('Actual demand (kW) must be a non-negative number.');
      return;
    }
    if (!Number.isFinite(numericPf) || numericPf < 0 || numericPf > 1) {
      setErrorMessage('Power factor must be between 0.00 and 1.00.');
      return;
    }

    const parsedDate = new Date(recordedAt);
    if (Number.isNaN(parsedDate.getTime())) {
      setErrorMessage('Provide a valid timestamp.');
      return;
    }

    setSubmitting(true);
    setErrorMessage(null);
    setSuccessMessage(null);
    setAnalyticsSummary(null);

    try {
      const created = await ingestTelemetryReading({
        meter_id: meterId,
        recorded_at: parsedDate.toISOString(),
        actual_kw: numericKw,
        power_factor: numericPf,
        ambient_temp_c: ambientTempC.trim() ? Number(ambientTempC) : undefined,
        source,
        quality_flag: source === 'simulation' ? 'simulated' : qualityFlag,
      });

      if (runAnalyticsAfter && facilityId) {
        const proc = await processAnalytics({
          facility_id: facilityId,
          meter_id: meterId,
          include_insights: true,
        });
        setAnalyticsSummary(proc);
      }

      setSuccessMessage(
        `Ingested reading #${created.id} (${created.actual_kw} kW, ${created.energy_kwh} kWh).`
      );
      await onDataUpdated();
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : 'Failed to ingest telemetry reading.');
    } finally {
      setSubmitting(false);
    }
  };

  const handleCsvSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!csvFile) {
      setErrorMessage('Choose a CSV file to upload.');
      return;
    }

    setSubmitting(true);
    setErrorMessage(null);
    setSuccessMessage(null);
    setUploadSummary(null);
    setAnalyticsSummary(null);

    try {
      const summary = await uploadTelemetryCsv(csvFile, atomicCsv);
      setUploadSummary(summary);
      if (summary.inserted_count > 0 && runAnalyticsAfter && facilityId) {
        const proc = await processAnalytics({
          facility_id: facilityId,
          zone_id: selectedZoneId ?? undefined,
          include_insights: true,
        });
        setAnalyticsSummary(proc);
      }
      await onDataUpdated();
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : 'CSV upload failed.');
    } finally {
      setSubmitting(false);
    }
  };

  const handleRunAnalytics = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!facilityId) return;

    setSubmitting(true);
    setErrorMessage(null);
    setSuccessMessage(null);
    setAnalyticsSummary(null);

    try {
      const summary = await processAnalytics({
        facility_id: facilityId,
        zone_id: selectedZoneId ?? undefined,
        reprocess,
        include_insights: includeInsights,
      });
      setAnalyticsSummary(summary);
      setSuccessMessage(
        `Processed ${summary.processed_readings} reading(s): ${summary.anomalies_created} anomalies created, ${summary.insights_created + summary.insights_updated} insights updated.`
      );
      await onDataUpdated();
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : 'Analytics processing failed.');
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
        aria-labelledby="telemetry-ingest-title"
        className="bg-white border border-slate-200 rounded-lg shadow-xl w-full max-w-2xl max-h-[90vh] flex flex-col overflow-hidden"
      >
        <div className="px-5 py-4 border-b border-slate-200 flex items-start justify-between gap-4">
          <div>
            <h2 id="telemetry-ingest-title" className="text-base font-semibold text-slate-900">
              Telemetry Ingestion & Analytics Engine
            </h2>
            <p className="text-xs text-slate-500 mt-0.5">
              {facilityName} · Real FastAPI ingestion and rolling-baseline processing
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close telemetry modal"
            className="p-1.5 text-slate-400 hover:text-slate-700 rounded-md hover:bg-slate-100"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="px-5 pt-3 border-b border-slate-100 flex gap-2">
          {[
            { id: 'single' as const, label: 'Single Interval', icon: Activity },
            { id: 'csv' as const, label: 'CSV Upload', icon: FileUp },
            { id: 'analytics' as const, label: 'Run Analytics', icon: Play },
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

        <div className="p-5 overflow-y-auto space-y-4">
          {errorMessage && (
            <div
              role="alert"
              className="px-3.5 py-2.5 rounded-md bg-red-50 border border-red-200 text-xs text-red-700"
            >
              {errorMessage}
            </div>
          )}

          {successMessage && (
            <div className="px-3.5 py-2.5 rounded-md bg-emerald-50 border border-emerald-200 text-xs text-emerald-800 flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 shrink-0" aria-hidden="true" />
              <span>{successMessage}</span>
            </div>
          )}

          {tab === 'single' && (
            <form onSubmit={handleSingleSubmit} className="space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label
                    htmlFor="ingest-meter"
                    className="block text-xs font-medium text-slate-700 mb-1"
                  >
                    Active Meter
                  </label>
                  <select
                    id="ingest-meter"
                    value={meterId}
                    onChange={(e) => setMeterId(e.target.value)}
                    className="w-full px-3 py-2 text-xs bg-white border border-slate-200 rounded-md text-slate-900"
                  >
                    {activeMeters.length === 0 ? (
                      <option value="">No active meters available</option>
                    ) : (
                      activeMeters.map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.meterCode} — {m.equipmentName}
                        </option>
                      ))
                    )}
                  </select>
                </div>

                <div>
                  <label
                    htmlFor="ingest-recorded-at"
                    className="block text-xs font-medium text-slate-700 mb-1"
                  >
                    Recorded At (Local → UTC)
                  </label>
                  <input
                    id="ingest-recorded-at"
                    type="datetime-local"
                    value={recordedAt}
                    onChange={(e) => setRecordedAt(e.target.value)}
                    className="w-full px-3 py-2 text-xs font-mono bg-white border border-slate-200 rounded-md text-slate-900"
                  />
                </div>

                <div>
                  <label
                    htmlFor="ingest-actual-kw"
                    className="block text-xs font-medium text-slate-700 mb-1"
                  >
                    Actual Demand (kW)
                  </label>
                  <input
                    id="ingest-actual-kw"
                    type="number"
                    step="0.01"
                    min="0"
                    value={actualKw}
                    onChange={(e) => setActualKw(e.target.value)}
                    className="w-full px-3 py-2 text-xs font-mono bg-white border border-slate-200 rounded-md text-slate-900"
                  />
                </div>

                <div>
                  <label
                    htmlFor="ingest-pf"
                    className="block text-xs font-medium text-slate-700 mb-1"
                  >
                    Power Factor (0.00–1.00)
                  </label>
                  <input
                    id="ingest-pf"
                    type="number"
                    step="0.01"
                    min="0"
                    max="1"
                    value={powerFactor}
                    onChange={(e) => setPowerFactor(e.target.value)}
                    className="w-full px-3 py-2 text-xs font-mono bg-white border border-slate-200 rounded-md text-slate-900"
                  />
                </div>

                <div>
                  <label
                    htmlFor="ingest-source"
                    className="block text-xs font-medium text-slate-700 mb-1"
                  >
                    Telemetry Source
                  </label>
                  <select
                    id="ingest-source"
                    value={source}
                    onChange={(e) => setSource(e.target.value as TelemetrySource)}
                    className="w-full px-3 py-2 text-xs bg-white border border-slate-200 rounded-md text-slate-900"
                  >
                    <option value="meter_feed">Meter Feed (valid)</option>
                    <option value="simulation">Simulation (simulated load test)</option>
                  </select>
                </div>

                <div>
                  <label
                    htmlFor="ingest-temp"
                    className="block text-xs font-medium text-slate-700 mb-1"
                  >
                    Ambient Temp °C (Optional)
                  </label>
                  <input
                    id="ingest-temp"
                    type="number"
                    step="0.1"
                    value={ambientTempC}
                    onChange={(e) => setAmbientTempC(e.target.value)}
                    className="w-full px-3 py-2 text-xs font-mono bg-white border border-slate-200 rounded-md text-slate-900"
                  />
                </div>
              </div>

              <label className="flex items-center gap-2 text-xs text-slate-700">
                <input
                  type="checkbox"
                  checked={runAnalyticsAfter}
                  onChange={(e) => setRunAnalyticsAfter(e.target.checked)}
                />
                Trigger analytics baseline & anomaly processing immediately after ingestion
              </label>

              <div className="flex justify-end gap-2">
                <button
                  type="submit"
                  disabled={submitting || activeMeters.length === 0}
                  className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-medium bg-slate-900 text-white rounded-md hover:bg-slate-800 disabled:opacity-50"
                >
                  {submitting && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                  Submit Reading
                </button>
              </div>
            </form>
          )}

          {tab === 'csv' && (
            <form onSubmit={handleCsvSubmit} className="space-y-4">
              <div>
                <label
                  htmlFor="telemetry-csv-file"
                  className="block text-xs font-medium text-slate-700 mb-1.5"
                >
                  Telemetry CSV File
                </label>
                <input
                  id="telemetry-csv-file"
                  type="file"
                  accept=".csv,text/csv"
                  onChange={(e) => setCsvFile(e.target.files?.[0] ?? null)}
                  className="block w-full text-xs text-slate-600 file:mr-3 file:py-2 file:px-3 file:rounded-md file:border file:border-slate-200 file:text-xs file:font-medium file:bg-slate-50 file:text-slate-700 hover:file:bg-slate-100"
                />
                <p className="text-[11px] text-slate-500 mt-1">
                  Required columns: meter_code (or meter_id), recorded_at (ISO-8601 with TZ),
                  actual_kw, power_factor.
                </p>
              </div>

              <label className="flex items-center gap-2 text-xs text-slate-700">
                <input
                  type="checkbox"
                  checked={atomicCsv}
                  onChange={(e) => setAtomicCsv(e.target.checked)}
                />
                Atomic mode (reject entire file if any row fails validation)
              </label>

              {uploadSummary && (
                <div className="bg-slate-50 border border-slate-200 rounded-md p-3 text-xs space-y-2">
                  <div className="font-semibold text-slate-900">
                    Upload Summary: {uploadSummary.inserted_count} inserted ·{' '}
                    {uploadSummary.duplicate_count} duplicates · {uploadSummary.overlap_count}{' '}
                    overlaps · {uploadSummary.failed_count} failed
                  </div>
                  {uploadSummary.errors.length > 0 && (
                    <ul className="space-y-1 text-red-700 max-h-32 overflow-y-auto">
                      {uploadSummary.errors.slice(0, 10).map((err, i) => (
                        <li key={i}>
                          Row {err.row_number ?? err.row_index}: [{err.code}] {err.message}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}

              <div className="flex justify-end">
                <button
                  type="submit"
                  disabled={submitting || !csvFile}
                  className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-medium bg-slate-900 text-white rounded-md hover:bg-slate-800 disabled:opacity-50"
                >
                  {submitting && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                  Upload CSV
                </button>
              </div>
            </form>
          )}

          {tab === 'analytics' && (
            <form onSubmit={handleRunAnalytics} className="space-y-4">
              <p className="text-xs text-slate-600 leading-relaxed">
                Runs the backend Phase 2E rolling baseline, Z-score anomaly detection, and insight
                rule evaluation for <strong>{facilityName}</strong>.
              </p>

              <div className="space-y-2">
                <label className="flex items-center gap-2 text-xs text-slate-700">
                  <input
                    type="checkbox"
                    checked={reprocess}
                    onChange={(e) => setReprocess(e.target.checked)}
                  />
                  Reprocess existing baseline-ready readings
                </label>
                <label className="flex items-center gap-2 text-xs text-slate-700">
                  <input
                    type="checkbox"
                    checked={includeInsights}
                    onChange={(e) => setIncludeInsights(e.target.checked)}
                  />
                  Evaluate actionable optimization insights after anomaly scan
                </label>
              </div>

              <div className="flex justify-end">
                <button
                  type="submit"
                  disabled={submitting || !facilityId}
                  className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-medium bg-slate-900 text-white rounded-md hover:bg-slate-800 disabled:opacity-50"
                >
                  {submitting && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                  Run Analytics Process
                </button>
              </div>
            </form>
          )}

          {analyticsSummary && (
            <div className="bg-sky-50 border border-sky-200 rounded-md p-3 text-xs text-sky-900 font-mono tabular-nums">
              Processed: {analyticsSummary.processed_readings} · Baselines Ready:{' '}
              {analyticsSummary.baselines_ready} · Anomalies Created:{' '}
              {analyticsSummary.anomalies_created} · Insights Created/Updated:{' '}
              {analyticsSummary.insights_created + analyticsSummary.insights_updated}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
