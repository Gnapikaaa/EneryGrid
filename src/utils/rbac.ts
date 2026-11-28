import { UserRole } from '../types/auth';

export function canOperateAnalytics(role: UserRole | string): boolean {
  return role === 'admin' || role === 'utility_engineer';
}

export function canUpdateMeters(role: UserRole | string): boolean {
  return role === 'admin' || role === 'utility_engineer';
}

export function canIngestTelemetry(role: UserRole | string): boolean {
  return role === 'admin' || role === 'utility_engineer';
}

export function canManageInfrastructure(role: UserRole | string): boolean {
  return role === 'admin';
}

export function isReadOnlyRole(role: UserRole | string): boolean {
  return role === 'facility_manager' || role === 'viewer';
}

export function formatRoleLabel(role: string): string {
  return role
    .split('_')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}
