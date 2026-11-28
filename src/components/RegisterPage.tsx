import React, { useState } from 'react';
import { AlertCircle, ArrowRight, Eye, EyeOff, Loader2 } from 'lucide-react';
import { ApiError } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { AuthLayout } from './AuthLayout';

interface RegisterPageProps {
  onNavigateToLogin: (prefill?: { email?: string; notice?: string }) => void;
}

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const MIN_PASSWORD_LENGTH = 8;
const MAX_PASSWORD_LENGTH = 128;
const MAX_FULL_NAME_LENGTH = 120;

export const RegisterPage: React.FC<RegisterPageProps> = ({ onNavigateToLogin }) => {
  const { signUp, clearMessages } = useAuth();

  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  const validate = (): Record<string, string> => {
    const errors: Record<string, string> = {};
    const trimmedName = fullName.trim();
    const trimmedEmail = email.trim();

    if (!trimmedName) {
      errors.full_name = 'Full name cannot be blank.';
    } else if (trimmedName.length > MAX_FULL_NAME_LENGTH) {
      errors.full_name = `Full name must not exceed ${MAX_FULL_NAME_LENGTH} characters.`;
    }

    if (!trimmedEmail) {
      errors.email = 'Email address is required.';
    } else if (!EMAIL_PATTERN.test(trimmedEmail)) {
      errors.email = 'Enter a valid email address.';
    }

    if (!password || !password.trim()) {
      errors.password = 'Password cannot be blank.';
    } else if (password.length < MIN_PASSWORD_LENGTH) {
      errors.password = `Password must be at least ${MIN_PASSWORD_LENGTH} characters long.`;
    } else if (password.length > MAX_PASSWORD_LENGTH) {
      errors.password = `Password must not exceed ${MAX_PASSWORD_LENGTH} characters.`;
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
      const result = await signUp({
        full_name: fullName.trim(),
        email: email.trim(),
        password,
      });

      if (!result.autoSignedIn) {
        onNavigateToLogin({
          email: result.user.email,
          notice: `Account created for ${result.user.email}. ${result.loginErrorMessage ?? 'Please sign in to continue.'}`,
        });
      }
    } catch (error) {
      if (error instanceof ApiError) {
        setFormError(error.message);
        if (Object.keys(error.fieldErrors).length > 0) {
          setFieldErrors(error.fieldErrors);
        }
      } else if (error instanceof Error) {
        setFormError(error.message);
      } else {
        setFormError('Unable to complete registration due to an unexpected error.');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <AuthLayout>
      <div className="space-y-6">
        <div className="space-y-1.5">
          <div className="flex items-center justify-between gap-4">
            <h2 className="text-xl font-bold tracking-tight text-white">Create an account</h2>
            <button
              type="button"
              onClick={() => {
                clearMessages();
                onNavigateToLogin();
              }}
              className="text-xs font-medium text-sky-400 hover:text-sky-300 hover:underline whitespace-nowrap shrink-0"
            >
              Sign in
            </button>
          </div>
          <p className="text-xs sm:text-sm text-slate-400">
            Register an EnergyGrid operator account to monitor facility consumption and anomalies.
          </p>
        </div>

        {formError && (
          <div
            role="alert"
            className="flex items-start gap-2.5 p-3 rounded-md border text-xs bg-red-950/60 border-red-800/80 text-red-200"
          >
            <AlertCircle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" aria-hidden="true" />
            <div className="leading-relaxed">{formError}</div>
          </div>
        )}

        <form onSubmit={handleSubmit} noValidate className="space-y-4">
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label
                htmlFor="register-full-name"
                className="block text-xs font-medium text-slate-200"
              >
                Full Name
              </label>
              <span className="text-[11px] font-mono tabular-nums text-slate-400">
                Max {MAX_FULL_NAME_LENGTH} chars
              </span>
            </div>
            <input
              id="register-full-name"
              name="full_name"
              type="text"
              autoComplete="name"
              maxLength={MAX_FULL_NAME_LENGTH}
              value={fullName}
              onChange={(e) => {
                setFullName(e.target.value);
                clearFieldError('full_name');
              }}
              placeholder="Aarav Kulkarni"
              aria-invalid={Boolean(fieldErrors.full_name)}
              aria-describedby={fieldErrors.full_name ? 'register-full-name-error' : undefined}
              className={`w-full min-h-[42px] px-3 py-2 text-sm bg-slate-950 border rounded-md text-slate-100 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-sky-500/25 transition-colors ${
                fieldErrors.full_name
                  ? 'border-red-500 focus:border-red-400'
                  : 'border-slate-700 focus:border-sky-500'
              }`}
            />
            {fieldErrors.full_name && (
              <p id="register-full-name-error" className="mt-1.5 text-xs text-red-400">
                {fieldErrors.full_name}
              </p>
            )}
          </div>

          <div>
            <label
              htmlFor="register-email"
              className="block text-xs font-medium text-slate-200 mb-1.5"
            >
              Work Email
            </label>
            <input
              id="register-email"
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
              aria-describedby={fieldErrors.email ? 'register-email-error' : undefined}
              className={`w-full min-h-[42px] px-3 py-2 text-sm bg-slate-950 border rounded-md text-slate-100 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-sky-500/25 transition-colors ${
                fieldErrors.email
                  ? 'border-red-500 focus:border-red-400'
                  : 'border-slate-700 focus:border-sky-500'
              }`}
            />
            {fieldErrors.email && (
              <p id="register-email-error" className="mt-1.5 text-xs text-red-400">
                {fieldErrors.email}
              </p>
            )}
          </div>

          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label
                htmlFor="register-password"
                className="block text-xs font-medium text-slate-200"
              >
                Password
              </label>
              <span className="text-[11px] font-mono tabular-nums text-slate-400">
                8–128 characters
              </span>
            </div>
            <div className="relative">
              <input
                id="register-password"
                name="password"
                type={showPassword ? 'text' : 'password'}
                autoComplete="new-password"
                maxLength={MAX_PASSWORD_LENGTH}
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value);
                  clearFieldError('password');
                }}
                placeholder="Create a strong password"
                aria-invalid={Boolean(fieldErrors.password)}
                aria-describedby={fieldErrors.password ? 'register-password-error' : undefined}
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
              <p id="register-password-error" className="mt-1.5 text-xs text-red-400">
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
                <span>Creating account...</span>
              </>
            ) : (
              <>
                <span>Create Account</span>
                <ArrowRight className="w-4 h-4" aria-hidden="true" />
              </>
            )}
          </button>
        </form>

        <div className="pt-4 border-t border-slate-800 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-400">
          <span>Already have an EnergyGrid account?</span>
          <button
            type="button"
            onClick={() => {
              clearMessages();
              onNavigateToLogin();
            }}
            className="font-semibold text-sky-400 hover:text-sky-300 hover:underline whitespace-nowrap"
          >
            Sign in instead
          </button>
        </div>
      </div>
    </AuthLayout>
  );
};
