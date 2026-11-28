import { apiClient } from './client';
import { AuthUser, LoginRequest, RegisterRequest, TokenResponse } from '../types/auth';

export function registerUser(payload: RegisterRequest): Promise<AuthUser> {
  return apiClient.post<AuthUser>('/auth/register', payload, {
    auth: false,
    handleUnauthorized: false,
  });
}

export function loginUser(payload: LoginRequest): Promise<TokenResponse> {
  return apiClient.post<TokenResponse>('/auth/login', payload, {
    auth: false,
    handleUnauthorized: false,
  });
}

export function fetchCurrentUser(token?: string): Promise<AuthUser> {
  return apiClient.get<AuthUser>('/auth/me', {
    auth: true,
    token,
    handleUnauthorized: false,
  });
}
