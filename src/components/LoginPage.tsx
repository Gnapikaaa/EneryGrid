import React, { useState } from 'react';
import {
  AlertCircle,
  ArrowRight,
  CheckCircle2,
  Eye,
  EyeOff,
  Loader2,
  RefreshCw,
} from 'lucide-react';
import { ApiError } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { AuthLayout } from './AuthLayout';

interface LoginPageProps {
  onNavigateToRegister: () => void;
  initialEmail?: string;
  registrationNotice?: string | null;
}

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export const LoginPage: React.FC<LoginPageProps> = ({
  onNavigateToRegister,
  initialEmail = '',
  registrationNotice = null,
}) => {
  const {
    signIn,
    sessionNotice,
    sessionError,
    canRetrySession,
    retrySessionValidation,
    clearMessages,
  } = useAuth();

  const [email, setEmail] = useState(initialEmail);
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isRetryingSession, setIsRetryingSession] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  const validate = (): Record<string, string> => {
    const errors: Record<string, string> = {};
    const trimmedEmail = email.trim();

    if (!trimmedEmail) {
      errors.email = 'Email address is required.';
    } else if (!EMAIL_PATTERN.test(trimmedEmail)) {
      errors.email = 'Enter a valid email address.';
    }

    if (!password) {
      errors.password = 'Password is required.';
    }

    return errors;
  };

  const clearFieldError = (field: string) => {
    if (fieldErrors[field]) {
      setFieldErrors((prev) => {
        const next = { ...prev };
        delete next[field];
        return next;
      });
    }
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setFormError(null);
    clearMessages();

    const validationErrors = validate();
    if (Object.keys(validationErrors).length > 0) {
      setFieldErrors(validationErrors);
      setFormError('Please correct the highlighted fields and try again.');
      return;
    }

    setFieldErrors({});
    setIsSubmitting(true);

    try {
      await signIn({ email: email.trim(), password });
    } catch (error) {
      if (error instanceof ApiError) {
        setFormError(error.message);
        if (Object.keys(error.fieldErrors).length > 0) {
          setFieldErrors(error.fieldErrors);
        }
      } else if (error instanceof Error) {
        setFormError(error.message);
      } else {
        setFormError('Unable to complete sign-in due to an unexpected error.');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleRetrySession = async () => {
    setIsRetryingSession(true);
    try {
      await retrySessionValidation();
    } finally {
      setIsRetryingSession(false);
    }
  };

  const activeError = formError ?? sessionError;
  const activeNotice = registrationNotice ?? sessionNotice;

  return (
    <AuthLayout>
      <div className="space-y-6">
        <div className="space-y-1.5">
          <div className="flex items-center justify-between gap-4">
            <h2 className="text-xl font-bold tracking-tight text-white">Sign in to EnergyGrid</h2>
            <button
              type="button"
              onClick={() => {
                clearMessages();
                onNavigateToRegister();
              }}
              className="text-xs font-medium text-sky-400 hover:text-sky-300 hover:underline whitespace-nowrap shrink-0"
            >
              Create account
            </button>
          </div>
          <p className="text-xs sm:text-sm text-slate-400">
            Enter your credentials to access facility telemetry and anomaly workflows.
          </p>
        </div>

        {activeNotice && (
          <div
            role="status"
            className="flex items-start gap-2.5 p-3 rounded-md border text-xs bg-sky-950/60 border-sky-800/80 text-sky-200"
          >
            <CheckCircle2 className="w-4 h-4 text-sky-400 shrink-0 mt-0.5" aria-hidden="true" />
            <div className="leading-relaxed">{activeNotice}</div>
          </div>
        )}

        {activeError && (
          <div
            role="alert"
            className="flex items-start gap-2.5 p-3 rounded-md border text-xs bg-red-950/60 border-red-800/80 text-red-200"
          >
            <AlertCircle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" aria-hidden="true" />
            <div className="flex-1 space-y-2 leading-relaxed">
              <div>{activeError}</div>
              {canRetrySession && !formError && (
                <button
                  type="button"
                  onClick={handleRetrySession}
                  disabled={isRetryingSession}
                  className="inline-flex items-center gap-1.5 font-semibold text-red-200 underline hover:text-white disabled:opacity-50"
                >
                  <RefreshCw
                    className={`w-3.5 h-3.5 ${isRetryingSession ? 'animate-spin' : ''}`}
                    aria-hidden="true"
                  />
                  {isRetryingSession ? 'Retrying session check...' : 'Retry session validation'}
                </button>
              )}
            </div>
          </div>
        )}

        <form onSubmit={handleSubmit} noValidate className="space-y-4">
          <div>
            <label htmlFor="login-email" className="block text-xs font-medium text-slate-200 mb-1.5">
              Work Email
            </label>
            <input
              id="login-email"
              name="email"
              type="email"
              autoComplete="email"
              value={email}
              onChange={(e) => {
                setEmail(e.target.value);
                clearFieldError('email');
              }}
              placeholder="user@example.com"
              aria-invalid={Boolean(fieldErrors.email)}
              aria-describedby={fieldErrors.email ? 'login-email-error' : undefined}
              className={`w-full min-h-[42px] px-3 py-2 text-sm bg-slate-950 border rounded-md text-slate-100 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-sky-500/25 transition-colors ${
                fieldErrors.email
                  ? 'border-red-500 focus:border-red-400'
                  : 'border-slate-700 focus:border-sky-500'
              }`}
            />
            {fieldErrors.email && (
              <p id="login-email-error" className="mt-1.5 text-xs text-red-400">
                {fieldErrors.email}
              </p>
            )}
          </div>

          <div>
            <label
              htmlFor="login-password"
              className="block text-xs font-medium text-slate-200 mb-1.5"
            >
              Password
            </label>
            <div className="relative">
              <input
                id="login-password"
                name="password"
                type={showPassword ? 'text' : 'password'}
                autoComplete="current-password"
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value);
                  clearFieldError('password');
                }}
                placeholder="Enter your password"
                aria-invalid={Boolean(fieldErrors.password)}
                aria-describedby={fieldErrors.password ? 'login-password-error' : undefined}
                className={`w-full min-h-[42px] px-3 py-2 pr-11 text-sm bg-slate-950 border rounded-md text-slate-100 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-sky-500/25 transition-colors ${
                  fieldErrors.password
                    ? 'border-red-500 focus:border-red-400'
                    : 'border-slate-700 focus:border-sky-500'
                }`}
              />
              <button
                type="button"
                onClick={() => setShowPassword((prev) => !prev)}
                aria-label={showPassword ? 'Hide password' : 'Show password'}
                className="absolute inset-y-0 right-0 px-3 flex items-center text-slate-400 hover:text-slate-200 focus-visible:outline-none focus-visible:text-sky-400"
              >
                {showPassword ? (
                  <EyeOff className="w-4 h-4" aria-hidden="true" />
                ) : (
                  <Eye className="w-4 h-4" aria-hidden="true" />
                )}
              </button>
            </div>
            {fieldErrors.password && (
              <p id="login-password-error" className="mt-1.5 text-xs text-red-400">
                {fieldErrors.password}
              </p>
            )}
          </div>

          <button
            type="submit"
            disabled={isSubmitting}
            className="w-full min-h-[42px] inline-flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-semibold bg-sky-600 text-white rounded-md hover:bg-sky-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400 disabled:opacity-60 disabled:cursor-not-allowed transition-colors whitespace-nowrap"
          >
            {isSubmitting ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />
                <span>Signing in...</span>
              </>
            ) : (
              <>
                <span>Sign In</span>
                <ArrowRight className="w-4 h-4" aria-hidden="true" />
              </>
            )}
          </button>
        </form>

        <div className="pt-4 border-t border-slate-800 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-400">
          <span>New engineer or facility operator?</span>
          <button
            type="button"
            onClick={() => {
              clearMessages();
              onNavigateToRegister();
            }}
            className="font-semibold text-sky-400 hover:text-sky-300 hover:underline whitespace-nowrap"
          >
            Create an account
          </button>
        </div>
      </div>
    </AuthLayout>
  );
};
