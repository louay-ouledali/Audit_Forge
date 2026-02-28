import { useEffect, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Building2, Crosshair, FileText, Play, ArrowRight, Shield, Activity, BarChart3 } from 'lucide-react';
import { getDashboardStats } from '../services/api';

export default function Dashboard() {
  const [stats, setStats] = useState({ clients: 0, active_missions: 0, benchmarks: 0, scans: 0 });
  const [error, setError] = useState('');
  const location = useLocation();

  useEffect(() => {
    if (location.pathname === '/') {
      getDashboardStats().then(setStats).catch(() => {
        setError('Failed to load dashboard stats. Is the backend running?');
      });
    }
  }, [location.pathname]);

  const cards = [
    { label: 'Clients', value: stats.clients, icon: Building2, accent: 'text-ey-yellow', bg: 'bg-ey-yellow/10', link: '/clients' },
    { label: 'Active Missions', value: stats.active_missions, icon: Crosshair, accent: 'text-emerald-400', bg: 'bg-emerald-400/10', link: '/clients' },
    { label: 'Benchmarks', value: stats.benchmarks, icon: FileText, accent: 'text-purple-400', bg: 'bg-purple-400/10', link: '/benchmarks' },
    { label: 'Scans', value: stats.scans, icon: Play, accent: 'text-sky-400', bg: 'bg-sky-400/10', link: '/clients' },
  ];

  return (
    <div className="relative z-10 space-y-8">
      {/* Welcome Banner */}
      <div className="relative overflow-hidden rounded-xl border border-dark-border bg-dark-card p-8 text-center">
        <div className="absolute inset-0 bg-gradient-to-br from-ey-yellow/5 via-transparent to-ey-yellow/3" />
        <div className="relative">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-ey-yellow/10 shadow-[0_0_30px_rgba(255,230,0,0.1)]">
            <Shield className="h-7 w-7 text-ey-yellow" />
          </div>
          <h2 className="text-2xl font-bold text-white">
            Welcome to <span className="text-ey-yellow">AuditForge</span>
          </h2>
          <p className="mt-2 text-dark-secondary">
            Automated Configuration Review Platform — Offline-first security auditing
          </p>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-400">
          {error}
        </div>
      )}

      {/* Stat Cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {cards.map((stat) => {
          const Icon = stat.icon;
          return (
            <Link
              key={stat.label}
              to={stat.link}
              className="glow-card group flex items-center gap-4 rounded-xl border border-dark-border bg-dark-card p-5 transition-all duration-300"
            >
              <div className={`rounded-xl p-3 ${stat.bg}`}>
                <Icon className={`h-6 w-6 ${stat.accent}`} />
              </div>
              <div>
                <p className="text-2xl font-bold text-white">{stat.value}</p>
                <p className="text-sm text-dark-secondary">{stat.label}</p>
              </div>
            </Link>
          );
        })}
      </div>

      {/* Quick Actions */}
      <div className="rounded-xl border border-dark-border bg-dark-card p-6">
        <div className="mb-4 flex items-center gap-2">
          <Activity className="h-5 w-5 text-ey-yellow" />
          <h3 className="text-lg font-semibold text-white">Quick Actions</h3>
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {[
            { to: '/clients', icon: Building2, label: 'Manage Clients & Missions', accent: 'text-ey-yellow' },
            { to: '/benchmarks', icon: FileText, label: 'Import a Benchmark', accent: 'text-purple-400' },
            { to: '/reports', icon: BarChart3, label: 'Generate Reports', accent: 'text-sky-400' },
          ].map((action) => (
            <Link
              key={action.to}
              to={action.to}
              className="glow-card group flex items-center justify-between rounded-lg border border-dark-border bg-dark-elevated p-4 transition-all duration-300"
            >
              <div className="flex items-center gap-3">
                <action.icon className={`h-5 w-5 ${action.accent}`} />
                <span className="text-sm font-medium text-white">{action.label}</span>
              </div>
              <ArrowRight className="h-4 w-4 text-dark-muted transition-transform group-hover:translate-x-1 group-hover:text-ey-yellow" />
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}
