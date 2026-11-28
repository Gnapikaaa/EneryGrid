export type KnownUserRole = 'admin' | 'facility_manager' | 'utility_engineer' | 'viewer';

export type UserRole = KnownUserRole | (string & {});

export interface AuthUser {
  id: string;
  email: string;
  full_name: string;
  role: UserRole;
  is_active: boolean;
  created_at: string;
}

export interface RegisterRequest {
  email: string;
  full_name: string;
  password: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: 'bearer';
  expires_in: number;
  user: AuthUser;
}

export interface FastApiValidationErrorItem {
  type?: string;
  loc?: Array<string | number>;
  msg: string;
  input?: unknown;
}

export interface ApiErrorPayload {
  detail?: string | FastApiValidationErrorItem[];
  message?: string;
}
