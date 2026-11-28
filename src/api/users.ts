import { apiClient } from './client';
import { AuthUser, UserAdminUpdateRequest } from '../types/api';

export function listUsers(signal?: AbortSignal): Promise<AuthUser[]> {
  return apiClient.get<AuthUser[]>('/users', { signal });
}

export function updateUserRoleOrStatus(
  userId: string,
  payload: UserAdminUpdateRequest
): Promise<AuthUser> {
  return apiClient.patch<AuthUser>(`/users/${encodeURIComponent(userId)}`, payload);
}
