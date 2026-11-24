import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import App from '../App';
import {
  ACCESS_TOKEN_STORAGE_KEY,
  apiClient,
  ApiError,
  DEFAULT_API_BASE_URL,
} from '../api/client';
import { AuthUser, TokenResponse } from '../types/auth';

const SAMPLE_USER: AuthUser = {
  id: '8f14e45f-eaab-4c4e-9b2d-111111111111',
  email: 'engineer@plant.io',
  full_name: 'Aarav Kulkarni',
  role: 'viewer',
  is_active: true,
  created_at: '2026-11-23T09:00:00Z',
};

const SAMPLE_TOKEN_RESPONSE: TokenResponse = {
  access_token: 'jwt-token-xyz',
  token_type: 'bearer',
  expires_in: 3600,
  user: SAMPLE_USER,
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('EnergyGrid authentication flow', () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    window.localStorage.clear();
    window.history.replaceState(null, '', '/');
  });

  afterEach(() => {
    vi.restoreAllMocks();
    window.sessionStorage.clear();
    window.localStorage.clear();
  });

  it('authenticates via POST /auth/login, calls GET /auth/me with Bearer token, and stores JWT in sessionStorage', async () => {
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(jsonResponse(SAMPLE_TOKEN_RESPONSE, 200))
      .mockResolvedValueOnce(jsonResponse(SAMPLE_USER, 200));

    render(<App />);

    expect(screen.getByRole('heading', { name: 'Sign in to EnergyGrid' })).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText('Work Email'), {
      target: { value: 'engineer@plant.io' },
    });
    fireEvent.change(screen.getByLabelText('Password'), {
      target: { value: 'SuperSecret123!' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Sign In' }));

    await waitFor(() => {
      expect(
        screen.getByRole('heading', { name: 'Load Profile & Statistical Baseline Envelope' })
      ).toBeInTheDocument();
    });

    expect(fetchSpy).toHaveBeenNthCalledWith(
      1,
      `${DEFAULT_API_BASE_URL}/auth/login`,
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          email: 'engineer@plant.io',
          password: 'SuperSecret123!',
        }),
      })
    );

    const [meUrl, meInit] = fetchSpy.mock.calls[1];
    expect(meUrl).toBe(`${DEFAULT_API_BASE_URL}/auth/me`);
    expect(new Headers(meInit?.headers).get('Authorization')).toBe('Bearer jwt-token-xyz');

    expect(window.sessionStorage.getItem(ACCESS_TOKEN_STORAGE_KEY)).toBe('jwt-token-xyz');
    expect(window.localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY)).toBeNull();
    expect(screen.getByText('Aarav Kulkarni')).toBeInTheDocument();
    expect(screen.getByText('Role: Viewer')).toBeInTheDocument();
  });

  it('persists session across refreshes via sessionStorage token + GET /auth/me and clears token on logout', async () => {
    window.sessionStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, 'stored-jwt-abc');

    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(jsonResponse(SAMPLE_USER, 200));

    render(<App />);

    await waitFor(() => {
      expect(
        screen.getByRole('heading', { name: 'Load Profile & Statistical Baseline Envelope' })
      ).toBeInTheDocument();
    });

    const [url, init] = fetchSpy.mock.calls[0];
    expect(url).toBe(`${DEFAULT_API_BASE_URL}/auth/me`);
    expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer stored-jwt-abc');

    fireEvent.click(screen.getByRole('button', { name: 'Sign Out' }));

    expect(window.sessionStorage.getItem(ACCESS_TOKEN_STORAGE_KEY)).toBeNull();
    expect(screen.getByRole('heading', { name: 'Sign in to EnergyGrid' })).toBeInTheDocument();
  });

  it('clears invalid sessionStorage token on startup 401 from /auth/me and shows session notice', async () => {
    window.sessionStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, 'expired-jwt');

    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      jsonResponse({ detail: 'Invalid or expired authentication token.' }, 401)
    );

    render(<App />);

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Sign in to EnergyGrid' })).toBeInTheDocument();
    });

    expect(window.sessionStorage.getItem(ACCESS_TOKEN_STORAGE_KEY)).toBeNull();
    expect(screen.getByRole('status')).toHaveTextContent(
      /previous session expired or is invalid/i
    );
  });

  it('navigates between login and registration, validates fields, registers via /auth/register, and authenticates via /auth/login + /auth/me', async () => {
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(jsonResponse(SAMPLE_USER, 201))
      .mockResolvedValueOnce(jsonResponse(SAMPLE_TOKEN_RESPONSE, 200))
      .mockResolvedValueOnce(jsonResponse(SAMPLE_USER, 200));

    render(<App />);

    fireEvent.click(screen.getByRole('button', { name: 'Create an account' }));
    expect(screen.getByRole('heading', { name: 'Create an account' })).toBeInTheDocument();
    expect(window.location.pathname).toBe('/register');

    // Navigate back and forth cleanly
    fireEvent.click(screen.getByRole('button', { name: 'Sign in instead' }));
    expect(screen.getByRole('heading', { name: 'Sign in to EnergyGrid' })).toBeInTheDocument();
    expect(window.location.pathname).toBe('/login');

    fireEvent.click(screen.getByRole('button', { name: 'Create an account' }));

    // Client-side validation catches blank/invalid inputs matching RegisterRequest
    fireEvent.click(screen.getByRole('button', { name: 'Create Account' }));
    expect(screen.getByText('Full name cannot be blank.')).toBeInTheDocument();
    expect(screen.getByText('Email address is required.')).toBeInTheDocument();
    expect(screen.getByText('Password cannot be blank.')).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText('Full Name'), {
      target: { value: 'Aarav Kulkarni' },
    });
    fireEvent.change(screen.getByLabelText('Work Email'), {
      target: { value: 'engineer@plant.io' },
    });
    fireEvent.change(screen.getByLabelText('Password'), {
      target: { value: 'StrongPass123' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Create Account' }));

    await waitFor(() => {
      expect(
        screen.getByRole('heading', { name: 'Load Profile & Statistical Baseline Envelope' })
      ).toBeInTheDocument();
    });

    expect(fetchSpy).toHaveBeenNthCalledWith(
      1,
      `${DEFAULT_API_BASE_URL}/auth/register`,
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          email: 'engineer@plant.io',
          full_name: 'Aarav Kulkarni',
          password: 'StrongPass123',
        }),
      })
    );
    expect(fetchSpy).toHaveBeenNthCalledWith(
      2,
      `${DEFAULT_API_BASE_URL}/auth/login`,
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          email: 'engineer@plant.io',
          password: 'StrongPass123',
        }),
      })
    );
    expect(fetchSpy).toHaveBeenNthCalledWith(
      3,
      `${DEFAULT_API_BASE_URL}/auth/me`,
      expect.objectContaining({
        method: 'GET',
      })
    );
    expect(window.sessionStorage.getItem(ACCESS_TOKEN_STORAGE_KEY)).toBe('jwt-token-xyz');
  });

  it('displays invalid credentials, duplicate email (409), and Pydantic validation (422) errors', async () => {
    vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(jsonResponse({ detail: 'Invalid email or password.' }, 401))
      .mockResolvedValueOnce(
        jsonResponse({ detail: 'An account with this email already exists.' }, 409)
      )
      .mockResolvedValueOnce(
        jsonResponse(
          {
            detail: [
              {
                type: 'value_error',
                loc: ['body', 'password'],
                msg: 'Value error, Password must be at least 8 characters long.',
              },
            ],
          },
          422
        )
      );

    render(<App />);

    fireEvent.change(screen.getByLabelText('Work Email'), {
      target: { value: 'engineer@plant.io' },
    });
    fireEvent.change(screen.getByLabelText('Password'), {
      target: { value: 'wrongpass' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Sign In' }));

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('Invalid email or password.');
    });

    // Switch to registration to test 409 duplicate email and 422 backend validation
    fireEvent.click(screen.getByRole('button', { name: 'Create an account' }));

    fireEvent.change(screen.getByLabelText('Full Name'), {
      target: { value: 'Aarav Kulkarni' },
    });
    fireEvent.change(screen.getByLabelText('Work Email'), {
      target: { value: 'engineer@plant.io' },
    });
    fireEvent.change(screen.getByLabelText('Password'), {
      target: { value: 'StrongPass123' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Create Account' }));

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(
        'An account with this email already exists.'
      );
    });

    fireEvent.click(screen.getByRole('button', { name: 'Create Account' }));

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(
        'Password: Password must be at least 8 characters long.'
      );
    });
  });

  it('injects Authorization Bearer token automatically on authenticated apiClient calls', async () => {
    window.sessionStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, 'api-client-jwt');

    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(jsonResponse({ ok: true }, 200))
      .mockResolvedValueOnce(jsonResponse({ detail: 'Forbidden' }, 403));

    const data = await apiClient.get<{ ok: boolean }>('/facilities');
    expect(data).toEqual({ ok: true });

    const [url, init] = fetchSpy.mock.calls[0];
    expect(url).toBe(`${DEFAULT_API_BASE_URL}/facilities`);
    expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer api-client-jwt');

    await expect(apiClient.get('/admin/users')).rejects.toMatchObject<Partial<ApiError>>({
      status: 403,
      message: 'Forbidden',
    });
  });

  it('supports direct navigation to /login, /register, and /register/', () => {
    window.history.replaceState(null, '', '/register');
    const firstRender = render(<App />);
    expect(screen.getByRole('heading', { name: 'Create an account' })).toBeInTheDocument();
    firstRender.unmount();

    window.history.replaceState(null, '', '/register/');
    const secondRender = render(<App />);
    expect(screen.getByRole('heading', { name: 'Create an account' })).toBeInTheDocument();
    secondRender.unmount();

    window.history.replaceState(null, '', '/login');
    render(<App />);
    expect(screen.getByRole('heading', { name: 'Sign in to EnergyGrid' })).toBeInTheDocument();
  });
});
