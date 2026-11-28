import { ApiErrorPayload, FastApiValidationErrorItem } from '../types/auth';

export const DEFAULT_API_BASE_URL = 'http://localhost:8000/api/v1';

export function getApiBaseUrl(): string {
  const configured = import.meta.env.VITE_API_BASE_URL;
  const raw = typeof configured === 'string' && configured.trim().length > 0
    ? configured.trim()
    : DEFAULT_API_BASE_URL;
  return raw.replace(/\/+$/, '');
}

export const API_BASE_URL = getApiBaseUrl();
export const ACCESS_TOKEN_STORAGE_KEY = 'energygrid_access_token';

type UnauthorizedListener = () => void;

let unauthorizedListener: UnauthorizedListener | null = null;

export function setUnauthorizedHandler(listener: UnauthorizedListener | null): void {
  unauthorizedListener = listener;
}

export function getStoredAccessToken(): string | null {
  try {
    const token = window.sessionStorage.getItem(ACCESS_TOKEN_STORAGE_KEY);
    return token && token.trim().length > 0 ? token : null;
  } catch {
    return null;
  }
}

export function setStoredAccessToken(token: string): void {
  try {
    window.sessionStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, token);
  } catch {
    // Ignore storage failures in restricted browser contexts
  }
}

export function clearStoredAccessToken(): void {
  try {
    window.sessionStorage.removeItem(ACCESS_TOKEN_STORAGE_KEY);
  } catch {
    // Ignore storage failures in restricted browser contexts
  }
}

export class ApiError extends Error {
  readonly status: number;
  readonly fieldErrors: Record<string, string>;
  readonly details: ApiErrorPayload | null;

  constructor(
    message: string,
    status: number,
    options?: {
      fieldErrors?: Record<string, string>;
      details?: ApiErrorPayload | null;
    }
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.fieldErrors = options?.fieldErrors ?? {};
    this.details = options?.details ?? null;
  }
}

function cleanValidationMessage(rawMessage: string): string {
  return rawMessage.replace(/^Value error,\s*/i, '').trim();
}

function formatFieldLabel(fieldName: string): string {
  switch (fieldName) {
    case 'full_name':
      return 'Full name';
    case 'email':
      return 'Email';
    case 'password':
      return 'Password';
    default:
      return fieldName.replace(/_/g, ' ');
  }
}

function parseValidationErrors(items: FastApiValidationErrorItem[]): {
  message: string;
  fieldErrors: Record<string, string>;
} {
  const fieldErrors: Record<string, string> = {};
  const messages: string[] = [];

  for (const item of items) {
    const cleaned = cleanValidationMessage(item.msg || 'Invalid input.');
    const locParts = Array.isArray(item.loc) ? item.loc : [];
    const lastPart = locParts.length > 0 ? String(locParts[locParts.length - 1]) : null;

    if (lastPart && lastPart !== 'body') {
      if (!fieldErrors[lastPart]) {
        fieldErrors[lastPart] = cleaned;
      }
      messages.push(`${formatFieldLabel(lastPart)}: ${cleaned}`);
    } else {
      messages.push(cleaned);
    }
  }

  return {
    message: messages.length > 0 ? messages.join(' ') : 'Please check the submitted form fields.',
    fieldErrors,
  };
}

function buildApiErrorFromPayload(
  status: number,
  statusText: string,
  payload: unknown
): ApiError {
  if (payload && typeof payload === 'object') {
    const data = payload as ApiErrorPayload;

    if (typeof data.detail === 'string' && data.detail.trim().length > 0) {
      return new ApiError(data.detail.trim(), status, { details: data });
    }

    if (Array.isArray(data.detail) && data.detail.length > 0) {
      const parsed = parseValidationErrors(data.detail);
      return new ApiError(parsed.message, status, {
        fieldErrors: parsed.fieldErrors,
        details: data,
      });
    }

    if (typeof data.message === 'string' && data.message.trim().length > 0) {
      return new ApiError(data.message.trim(), status, { details: data });
    }
  }

  if (status >= 500) {
    return new ApiError(
      'The EnergyGrid server encountered an unexpected error. Please try again shortly.',
      status
    );
  }

  return new ApiError(statusText || `Request failed with status ${status}.`, status);
}

export interface ApiRequestOptions extends Omit<RequestInit, 'body'> {
  body?: unknown;
  /** Set to false to omit Authorization header even if a token is stored. Defaults to true. */
  auth?: boolean;
  /** Optional explicit token override. */
  token?: string;
  /** Trigger global unauthorized handler on 401 responses. Defaults to true when authenticated. */
  handleUnauthorized?: boolean;
}

function buildEndpointUrl(path: string): string {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  return `${getApiBaseUrl()}${normalizedPath}`;
}

export async function apiRequest<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
  const {
    body,
    auth = true,
    token,
    handleUnauthorized = auth,
    headers: customHeaders,
    ...fetchOptions
  } = options;

  const headers = new Headers(customHeaders);
  if (!headers.has('Accept')) {
    headers.set('Accept', 'application/json');
  }

  let serializedBody: BodyInit | undefined;
  if (body !== undefined) {
    if (
      typeof body === 'string' ||
      body instanceof FormData ||
      body instanceof URLSearchParams ||
      body instanceof Blob
    ) {
      serializedBody = body;
    } else {
      if (!headers.has('Content-Type')) {
        headers.set('Content-Type', 'application/json');
      }
      serializedBody = JSON.stringify(body);
    }
  }

  const resolvedToken = token ?? (auth ? getStoredAccessToken() : null);
  if (auth && resolvedToken) {
    headers.set('Authorization', `Bearer ${resolvedToken}`);
  }

  let response: Response;
  try {
    response = await fetch(buildEndpointUrl(path), {
      ...fetchOptions,
      headers,
      body: serializedBody,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw err;
    }
    throw new ApiError(
      `Unable to reach the EnergyGrid API at ${getApiBaseUrl()}. Confirm the backend service is running.`,
      0
    );
  }

  const contentType = response.headers.get('content-type') ?? '';
  const isJson = contentType.toLowerCase().includes('application/json');

  let parsedBody: unknown = null;
  if (response.status !== 204) {
    if (isJson) {
      try {
        parsedBody = await response.json();
      } catch {
        parsedBody = null;
      }
    } else {
      const textBody = await response.text().catch(() => '');
      if (textBody.trim()) {
        try {
          parsedBody = JSON.parse(textBody);
        } catch {
          parsedBody = { message: textBody.trim() };
        }
      }
    }
  }

  if (!response.ok) {
    if (response.status === 401 && handleUnauthorized) {
      clearStoredAccessToken();
      unauthorizedListener?.();
    }
    throw buildApiErrorFromPayload(response.status, response.statusText, parsedBody);
  }

  return parsedBody as T;
}

export const apiClient = {
  get<T>(path: string, options?: Omit<ApiRequestOptions, 'method' | 'body'>): Promise<T> {
    return apiRequest<T>(path, { ...options, method: 'GET' });
  },
  post<T>(
    path: string,
    body?: unknown,
    options?: Omit<ApiRequestOptions, 'method' | 'body'>
  ): Promise<T> {
    return apiRequest<T>(path, { ...options, method: 'POST', body });
  },
  put<T>(
    path: string,
    body?: unknown,
    options?: Omit<ApiRequestOptions, 'method' | 'body'>
  ): Promise<T> {
    return apiRequest<T>(path, { ...options, method: 'PUT', body });
  },
  patch<T>(
    path: string,
    body?: unknown,
    options?: Omit<ApiRequestOptions, 'method' | 'body'>
  ): Promise<T> {
    return apiRequest<T>(path, { ...options, method: 'PATCH', body });
  },
  delete<T>(path: string, options?: Omit<ApiRequestOptions, 'method' | 'body'>): Promise<T> {
    return apiRequest<T>(path, { ...options, method: 'DELETE' });
  },
};
