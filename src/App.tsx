import React, { useEffect, useState } from 'react';
import { Loader2, Zap } from 'lucide-react';
import { AuthProvider, useAuth } from './auth/AuthContext';
import { Dashboard } from './components/Dashboard';
import { LoginPage } from './components/LoginPage';
import { RegisterPage } from './components/RegisterPage';

type AuthRoute = 'login' | 'register';

function resolveRouteFromPath(pathname: string): AuthRoute {
  const normalized = pathname.replace(/\/+$/, '').toLowerCase();
  return normalized === '/register' ? 'register' : 'login';
}

const AppContent: React.FC = () => {
  const { user, status, signOut } = useAuth();
  const [authRoute, setAuthRoute] = useState<AuthRoute>(() =>
    resolveRouteFromPath(window.location.pathname)
  );
  const [loginPrefill, setLoginPrefill] = useState<{ email?: string; notice?: string } | null>(
    null
  );

  useEffect(() => {
    const handlePopState = () => {
      setAuthRoute(resolveRouteFromPath(window.location.pathname));
    };
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  const navigateAuth = (nextRoute: AuthRoute, prefill?: { email?: string; notice?: string }) => {
    setLoginPrefill(prefill ?? null);
    setAuthRoute(nextRoute);
    const targetPath = nextRoute === 'register' ? '/register' : '/login';
    if (window.location.pathname !== targetPath) {
      window.history.pushState(null, '', targetPath);
    }
  };

  if (status === 'initializing') {
    return (
      <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col items-center justify-center px-4">
        <div className="bg-slate-900 border border-slate-800 rounded-lg px-6 py-5 shadow-lg flex items-center gap-3">
          <Zap className="w-5 h-5 text-sky-400 shrink-0" aria-hidden="true" />
          <Loader2 className="w-4 h-4 text-slate-300 animate-spin shrink-0" aria-hidden="true" />
          <span className="text-sm font-medium text-slate-200">
            Validating EnergyGrid session...
          </span>
        </div>
      </div>
    );
  }

  if (status !== 'authenticated' || !user) {
    if (authRoute === 'register') {
      return (
        <RegisterPage
          onNavigateToLogin={(prefill) => navigateAuth('login', prefill)}
        />
      );
    }

    return (
      <LoginPage
        onNavigateToRegister={() => navigateAuth('register')}
        initialEmail={loginPrefill?.email}
        registrationNotice={loginPrefill?.notice}
      />
    );
  }

  return (
    <Dashboard
      user={user}
      onLogout={() => {
        signOut();
        navigateAuth('login');
      }}
    />
  );
};

export default function App() {
  return (
    <AuthProvider>
      <AppContent />
    </AuthProvider>
  );
}
