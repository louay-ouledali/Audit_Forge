import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Lock, AlertCircle } from 'lucide-react';
import { login } from '@/services/auth';
import logoImg from '@/assets/logo-transparent.png';

export default function Login() {
  const navigate = useNavigate();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await login(username, password);
      navigate('/', { replace: true });
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Login failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-dark-bg">
      {/* Ambient glow */}
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute left-1/2 top-1/3 h-[600px] w-[600px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-ey-yellow/5 blur-[150px]" />
      </div>

      <div className="relative z-10 w-full max-w-md px-4">
        {/* Logo */}
        <div className="mb-8 flex flex-col items-center gap-3">
          <img src={logoImg} alt="AuditForge" className="h-16 w-16" />
          <h1 className="text-2xl font-bold text-white">
            Audit<span className="text-ey-yellow">Forge</span>
          </h1>
          <p className="text-sm text-dark-muted">Sign in to continue</p>
        </div>

        {/* Card */}
        <form
          onSubmit={handleSubmit}
          className="rounded-2xl border border-dark-border/50 bg-dark-surface/80 p-8 shadow-2xl backdrop-blur-sm"
        >
          {error && (
            <div className="mb-4 flex items-center gap-2 rounded-lg bg-red-500/10 px-4 py-3 text-sm text-red-400">
              <AlertCircle className="h-4 w-4 shrink-0" />
              {error}
            </div>
          )}

          <div className="space-y-4">
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-dark-muted">
                Username
              </label>
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="w-full rounded-lg border border-dark-border/50 bg-dark-bg/50 px-4 py-2.5 text-white placeholder-dark-muted outline-none transition focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/25"
                placeholder="admin"
                autoFocus
                required
              />
            </div>

            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-dark-muted">
                Password
              </label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full rounded-lg border border-dark-border/50 bg-dark-bg/50 px-4 py-2.5 text-white placeholder-dark-muted outline-none transition focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/25"
                placeholder="••••••••"
                required
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="mt-6 flex w-full items-center justify-center gap-2 rounded-lg bg-ey-yellow px-4 py-2.5 text-sm font-semibold text-dark-bg transition hover:bg-ey-yellow/90 disabled:opacity-50"
          >
            <Lock className="h-4 w-4" />
            {loading ? 'Signing in...' : 'Sign In'}
          </button>
        </form>

        <p className="mt-6 text-center text-xs text-dark-muted">
          Forge Gatekeeper &mdash; Authenticated Access Only
        </p>
      </div>
    </div>
  );
}
