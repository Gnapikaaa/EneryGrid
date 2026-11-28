import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { fetchCurrentUser, loginUser, registerUser } from '../api/auth';
import {
  ApiError,
  clearStoredAccessToken,
  getStoredAccessToken,
  setStoredAccessToken,
  setUnauthorizedHandler,
} from '../api/client';
import { AuthUser, LoginRequest, RegisterRequest } from '../types/auth';

export type AuthStatus = 'initializing' | 'authenticated' | 'unauthenticated';

export interface SignUpResult {
  user: AuthUser;
  autoSignedIn: boolean;
  loginErrorMessage?: string;
}

interface AuthContextValue {
  user: AuthUser | null;
  token: string | null;
  status: AuthStatus;
  sessionNotice: string | null;
  sessionError: string | null;
  canRetrySession: boolean;
  signIn: (payload: LoginRequest) => Promise<AuthUser>;
  signUp: (payload: RegisterRequest) => Promise<SignUpResult>;
  signOut: () => void;
  retrySessionValidation: () => Promise<void>;
  clearMessages: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [token, setToken] = useState<string | null>(() => getStoredAccessToken());
  const [status, setStatus] = useState<AuthStatus>(() =>
    getStoredAccessToken() ? 'initializing' : 'unauthenticated'
  );
  const [sessionNotice, setSessionNotice] = useState<string | null>(null);
  const [sessionError, setSessionError] = useState<string | null>(null);
  const [canRetrySession, setCanRetrySession] = useState(false);

  const validateStoredToken = useCallback(async (storedToken: string, isCancelled?: () => boolean) => {
    setStatus('initializing');
    setSessionError(null);
    setCanRetrySession(false);

    try {
      const authenticatedUser = await fetchCurrentUser(storedToken);
      if (isCancelled?.()) return;

      setUser(authenticatedUser);
      setToken(storedToken);
      setSessionNotice(null);
      setSessionError(null);
      setCanRetrySession(false);
      setStatus('authenticated');
    } catch (error) {
      if (isCancelled?.()) return;

      if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
        clearStoredAccessToken();
        setToken(null);
        setUser(null);
        setCanRetrySession(false);
        setSessionNotice(
          error.status === 403
            ? error.message
            : 'Your previous session expired or is invalid. Please sign in again.'
        );
        setStatus('unauthenticated');
        return;
      }

      const message =
        error instanceof Error
          ? error.message
          : 'Unable to validate your existing session with the EnergyGrid backend.';
      setUser(null);
      setSessionError(message);
      setCanRetrySession(true);
      setStatus('unauthenticated');
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    const storedToken = getStoredAccessToken();

    if (!storedToken) {
      setStatus('unauthenticated');
      return () => {
        cancelled = true;
      };
    }

    void validateStoredToken(storedToken, () => cancelled);

    return () => {
      cancelled = true;
    };
  }, [validateStoredToken]);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setToken(null);
      setUser(null);
      setCanRetrySession(false);
      setSessionError(null);
      setSessionNotice('Your session expired. Please sign in again.');
      setStatus('unauthenticated');
    });

    return () => {
      setUnauthorizedHandler(null);
    };
  }, []);

  const signIn = useCallback(async (payload: LoginRequest): Promise<AuthUser> => {
    const response = await loginUser({
      email: payload.email.trim(),
      password: payload.password,
    });

    setStoredAccessToken(response.access_token);

    try {
      const verifiedUser = await fetchCurrentUser(response.access_token);
      setToken(response.access_token);
      setUser(verifiedUser);
      setSessionNotice(null);
      setSessionError(null);
      setCanRetrySession(false);
      setStatus('authenticated');
      return verifiedUser;
    } catch (error) {
      clearStoredAccessToken();
      setToken(null);
      setUser(null);
      setStatus('unauthenticated');
      throw error;
    }
  }, []);

  const signUp = useCallback(
    async (payload: RegisterRequest): Promise<SignUpResult> => {
      const normalizedEmail = payload.email.trim();
      const normalizedFullName = payload.full_name.trim();

      const createdUser = await registerUser({
        email: normalizedEmail,
        full_name: normalizedFullName,
        password: payload.password,
      });

      try {
        const verifiedUser = await signIn({
          email: normalizedEmail,
          password: payload.password,
        });
        return { user: verifiedUser, autoSignedIn: true };
      } catch (loginErr) {
        const loginErrorMessage =
          loginErr instanceof Error
            ? loginErr.message
            : 'Please sign in with your new account credentials.';
        return {
          user: createdUser,
          autoSignedIn: false,
          loginErrorMessage,
        };
      }
    },
    [signIn]
  );

  const signOut = useCallback(() => {
    clearStoredAccessToken();
    setToken(null);
    setUser(null);
    setSessionNotice(null);
    setSessionError(null);
    setCanRetrySession(false);
    setStatus('unauthenticated');
  }, []);

  const retrySessionValidation = useCallback(async () => {
    const storedToken = getStoredAccessToken();
    if (!storedToken) {
      setToken(null);
      setCanRetrySession(false);
      setStatus('unauthenticated');
      return;
    }
    await validateStoredToken(storedToken);
  }, [validateStoredToken]);

  const clearMessages = useCallback(() => {
    setSessionNotice(null);
    setSessionError(null);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      token,
      status,
      sessionNotice,
      sessionError,
      canRetrySession,
      signIn,
      signUp,
      signOut,
      retrySessionValidation,
      clearMessages,
    }),
    [
      user,
      token,
      status,
      sessionNotice,
      sessionError,
      canRetrySession,
      signIn,
      signUp,
      signOut,
      retrySessionValidation,
      clearMessages,
    ]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return ctx;
}
