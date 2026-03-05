import { useEffect, useState, useMemo, useRef } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { Building2, Crosshair, FileText, Play, Activity, BarChart3, Clock, CheckCircle, Plus, Upload, Search } from 'lucide-react';
import { getDashboardStats, getScans, getAllMissions } from '../services/api';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import type { ScanDetail } from '../types';
import logoImg from '../assets/logo.png';

// Helper for Progress Ring
function ProgressRing({ radius, stroke, progress, colorClass }: { radius: number, stroke: number, progress: number, colorClass: string }) {
  const normalizedRadius = radius - stroke * 2;
  const circumference = normalizedRadius * 2 * Math.PI;
  const strokeDashoffset = circumference - (progress / 100) * circumference;

  return (
    <div className="relative flex items-center justify-center">
      <svg height={radius * 2} width={radius * 2} className="-rotate-90 transform">
        <circle
          stroke="rgba(255,255,255,0.1)"
          fill="transparent"
          strokeWidth={stroke}
          r={normalizedRadius}
          cx={radius}
          cy={radius}
        />
        <circle
          className={colorClass}
          stroke="currentColor"
          fill="transparent"
          strokeWidth={stroke}
          strokeDasharray={circumference + ' ' + circumference}
          style={{ strokeDashoffset }}
          strokeLinecap="round"
          r={normalizedRadius}
          cx={radius}
          cy={radius}
        />
      </svg>
    </div>
  );
}

export default function Dashboard() {
  const [stats, setStats] = useState({ clients: 0, active_missions: 0, benchmarks: 0, scans: 0 });
  const [totalMissions, setTotalMissions] = useState(0);
  const [recentScans, setRecentScans] = useState<ScanDetail[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const location = useLocation();
  const navigate = useNavigate();
  const pollRef = useRef<ReturnType<typeof setInterval>>();

  const loadDashboard = () => {
    Promise.all([
      getDashboardStats(),
      getScans({}),
      getAllMissions()
    ])
      .then(([statsData, scansData, missionsData]) => {
        setStats(statsData);
        setTotalMissions(missionsData.length);
        const sortedScans = scansData.data
          .filter(s => s.status === 'completed' && s.completed_at)
          .sort((a, b) => new Date(b.completed_at!).getTime() - new Date(a.completed_at!).getTime());
        setRecentScans(sortedScans.slice(0, 5));
      })
      .catch(() => {
        setError('Failed to load dashboard data. Is the backend running?');
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    if (location.pathname === '/') {
      loadDashboard();
      // Auto-refresh every 30s
      pollRef.current = setInterval(loadDashboard, 30_000);
      return () => clearInterval(pollRef.current);
    }
  }, [location.pathname]);

  // Generate chart data from recent scans — only real data, no fabrication
  const chartData = useMemo(() => {
    if (!recentScans.length) return [];

    // Group by date
    const dailyScores: Record<string, { total: number; count: number }> = {};

    recentScans.forEach(scan => {
      if (scan.completed_at && scan.compliance_percentage !== null) {
        const date = new Date(scan.completed_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
        if (!dailyScores[date]) dailyScores[date] = { total: 0, count: 0 };
        dailyScores[date].total += scan.compliance_percentage;
        dailyScores[date].count += 1;
      }
    });

    const entries = Object.entries(dailyScores);
    // Require at least 3 real data points for a meaningful chart
    if (entries.length < 3) return [];

    return entries.map(([date, v]) => ({
      date,
      compliance: Math.round(v.total / v.count),
    }));
  }, [recentScans]);

  const cards = [
    { label: 'Clients', value: stats.clients, icon: Building2, accent: 'text-ey-yellow', bg: 'bg-ey-yellow/10', link: '/clients', progress: 100 },
    { label: 'Active Missions', value: stats.active_missions, icon: Crosshair, accent: 'text-emerald-400', bg: 'bg-emerald-400/10', link: '/clients', progress: totalMissions > 0 ? Math.round((stats.active_missions / totalMissions) * 100) : 0 },
    { label: 'Benchmarks', value: stats.benchmarks, icon: FileText, accent: 'text-purple-400', bg: 'bg-purple-400/10', link: '/benchmarks', progress: 100 },
    { label: 'Total Scans', value: stats.scans, icon: Play, accent: 'text-sky-400', bg: 'bg-sky-400/10', link: recentScans[0] ? `/missions/${recentScans[0].mission_id}` : '/clients', progress: 100 },
  ];

  /* ── Loading skeleton ──────────────────────────────────────── */
  if (loading) {
    return (
      <div className="relative z-10 space-y-8 pb-10 animate-pulse">
        {/* Banner skeleton */}
        <div className="rounded-xl border border-dark-border bg-dark-card p-8 h-32" />
        {/* Stat cards */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[1,2,3,4].map(i => (
            <div key={i} className="h-24 rounded-xl border border-dark-border bg-dark-card" />
          ))}
        </div>
        {/* Chart + feed */}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <div className="col-span-1 lg:col-span-2 h-96 rounded-xl border border-dark-border bg-dark-card" />
          <div className="h-96 rounded-xl border border-dark-border bg-dark-card" />
        </div>
      </div>
    );
  }

  return (
    <div className="relative z-10 space-y-8 pb-10">
      {/* Welcome Banner */}
      <div className="relative overflow-hidden rounded-xl border border-dark-border bg-dark-card p-8 text-center">
        <div className="absolute inset-0 bg-gradient-to-br from-ey-yellow/5 via-transparent to-ey-yellow/3" />
        <div className="relative">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-ey-yellow/10 shadow-[0_0_30px_rgba(255,230,0,0.1)]">
            <img src={logoImg} alt="AuditForge Logo" className="h-7 w-7 object-contain opacity-90 drop-shadow-[0_0_8px_rgba(255,230,0,0.5)]" />
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

      {/* Stat Cards with Progress Rings */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {cards.map((stat) => {
          const Icon = stat.icon;
          return (
            <Link
              key={stat.label}
              to={stat.link}
              className="glow-card group relative flex items-center justify-between overflow-hidden rounded-xl border border-dark-border bg-dark-card p-5 transition-all duration-300 hover:border-dark-hover"
            >
              <div className="z-10">
                <p className="text-sm font-medium text-dark-secondary">{stat.label}</p>
                <div className="mt-1 flex items-baseline gap-2">
                  <p className="text-3xl font-bold text-white tracking-tight">{stat.value}</p>
                  {stat.label === 'Active Missions' && (
                    <span className="text-xs text-dark-muted">/ {totalMissions} total</span>
                  )}
                </div>
              </div>

              <div className="relative z-10">
                <ProgressRing radius={28} stroke={4} progress={stat.progress || 100} colorClass={stat.accent.replace('text-', 'text-')} />
                <div className={`absolute inset-0 flex items-center justify-center rounded-full`}>
                  <Icon className={`h-5 w-5 ${stat.accent}`} />
                </div>
              </div>
            </Link>
          );
        })}
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Compliance Overview Chart */}
        <div className="col-span-1 lg:col-span-2 rounded-xl border border-dark-border bg-dark-card p-6">
          <div className="mb-6 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <BarChart3 className="h-5 w-5 text-ey-yellow" />
              <h3 className="text-lg font-semibold text-white">Compliance Overview (30 Days)</h3>
            </div>
          </div>
          <div className="h-[300px] w-full">
            {chartData.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={chartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <defs>
                    <linearGradient id="colorCompliance" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#FFE600" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#FFE600" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#2A2A2A" vertical={false} />
                  <XAxis dataKey="date" stroke="#666" tick={{ fill: '#888', fontSize: 12 }} axisLine={false} tickLine={false} />
                  <YAxis stroke="#666" tick={{ fill: '#888', fontSize: 12 }} axisLine={false} tickLine={false} domain={[0, 100]} />
                  <Tooltip
                    contentStyle={{ backgroundColor: '#1A1A1A', borderColor: '#333', borderRadius: '8px', color: '#fff' }}
                    itemStyle={{ color: '#FFE600' }}
                    formatter={(value: any) => [`${value}%`, 'Avg. Compliance']}
                  />
                  <Area
                    type="monotone"
                    dataKey="compliance"
                    stroke="#FFE600"
                    strokeWidth={2}
                    fillOpacity={1}
                    fill="url(#colorCompliance)"
                    animationDuration={1500}
                  />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <div className="flex h-full flex-col items-center justify-center gap-2">
                <BarChart3 className="h-8 w-8 text-dark-muted" />
                <p className="text-dark-muted text-sm">Not enough data to display a trend chart</p>
                <p className="text-xs text-dark-muted">At least 3 scans on different days are needed.</p>
              </div>
            )}
          </div>
        </div>

        {/* Recent Activity Feed */}
        <div className="col-span-1 rounded-xl border border-dark-border bg-dark-card p-6 flex flex-col">
          <div className="mb-6 flex items-center gap-2">
            <Activity className="h-5 w-5 text-sky-400" />
            <h3 className="text-lg font-semibold text-white">Recent Scans</h3>
          </div>

          <div className="flex-1 space-y-4 overflow-y-auto pr-2 custom-scrollbar">
            {recentScans.length > 0 ? (
              recentScans.map((scan) => (
                <div key={scan.id} className="relative pl-6 before:absolute before:left-[11px] before:top-2 before:bottom-[-16px] before:w-[2px] before:bg-dark-border last:before:hidden">
                  <div className="absolute left-0 top-1 rounded-full bg-dark-card p-0.5 border border-dark-border z-10">
                    <CheckCircle className="h-4 w-4 text-emerald-400" />
                  </div>
                  <div className="rounded-lg border border-dark-border bg-dark-elevated p-3 transition-colors hover:border-dark-hover">
                    <div className="flex justify-between items-start mb-1">
                      <p className="text-sm font-medium text-white truncate pr-2">
                        {scan.target_hostname || `Target #${scan.target_id}`}
                      </p>
                      <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${(scan.compliance_percentage || 0) >= 80 ? 'bg-emerald-400/10 text-emerald-400' :
                        (scan.compliance_percentage || 0) >= 50 ? 'bg-ey-yellow/10 text-ey-yellow' :
                          'bg-red-400/10 text-red-400'
                        }`}>
                        {scan.compliance_percentage}%
                      </span>
                    </div>
                    <p className="text-xs text-dark-secondary truncate mb-2">
                      {scan.benchmark_name || `Benchmark #${scan.benchmark_id}`}
                    </p>
                    <div className="flex items-center text-[10px] text-dark-muted">
                      <Clock className="w-3 h-3 mr-1" />
                      {new Date(scan.completed_at!).toLocaleString()}
                    </div>
                  </div>
                </div>
              ))
            ) : (
              <div className="flex h-full flex-col items-center justify-center text-center">
                <div className="rounded-full bg-dark-elevated p-3 mb-3">
                  <Play className="h-6 w-6 text-dark-muted" />
                </div>
                <p className="text-sm text-dark-secondary">No recent scans found</p>
                <Link to="/clients" className="mt-4 text-xs text-ey-yellow hover:underline">
                  Start a scan →
                </Link>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Quick Actions */}
      <div className="rounded-xl border border-dark-border bg-dark-card p-5">
        <h3 className="mb-4 text-sm font-semibold text-white uppercase tracking-wider">Quick Actions</h3>
        <div className="flex flex-wrap gap-3">
          <button onClick={() => navigate('/clients', { state: { openNew: true } })} className="inline-flex items-center gap-2 rounded-lg border border-dark-border bg-dark-elevated px-4 py-2.5 text-sm font-medium text-dark-secondary hover:text-white hover:border-ey-yellow/30 transition-colors">
            <Plus className="h-4 w-4" /> New Client
          </button>
          <button onClick={() => navigate('/benchmarks')} className="inline-flex items-center gap-2 rounded-lg border border-dark-border bg-dark-elevated px-4 py-2.5 text-sm font-medium text-dark-secondary hover:text-white hover:border-purple-400/30 transition-colors">
            <Upload className="h-4 w-4" /> Import Benchmark
          </button>
          {recentScans[0] && (
            <button onClick={() => navigate(`/missions/${recentScans[0].mission_id}`, { state: { tab: 'findings' } })} className="inline-flex items-center gap-2 rounded-lg border border-dark-border bg-dark-elevated px-4 py-2.5 text-sm font-medium text-dark-secondary hover:text-white hover:border-sky-400/30 transition-colors">
              <Search className="h-4 w-4" /> Latest Findings
            </button>
          )}
        </div>
      </div>

    </div>
  );
}
