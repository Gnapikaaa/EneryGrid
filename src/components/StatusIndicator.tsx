import React from 'react';
import { AlertTriangle, CheckCircle2, XCircle } from 'lucide-react';

export type HealthStatus = 'Nominal' | 'Warning' | 'Fault';

interface StatusIndicatorProps {
  status: HealthStatus;
}

export const StatusIndicator: React.FC<StatusIndicatorProps> = ({ status }) => {
  if (status === 'Fault') {
    return (
      <span className="inline-flex items-center gap-1 text-xs font-medium text-red-700">
        <XCircle className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />
        Fault
      </span>
    );
  }
  if (status === 'Warning') {
    return (
      <span className="inline-flex items-center gap-1 text-xs font-medium text-amber-700">
        <AlertTriangle className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />
        Warning
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-700">
      <CheckCircle2 className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />
      Nominal
    </span>
  );
};
