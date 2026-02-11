import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Building2, Crosshair, FileText, Play, ArrowRight, Shield } from 'lucide-react';
import { getDashboardStats } from '../services/api';

export default function Dashboard() {
  const [stats, setStats] = useState({ clients: 0, active_missions: 0, benchmarks: 0, scans: 0 });
  const [error, setError] = useState('');

  useEffect(() => {
    getDashboardStats().then(setStats).catch(() => {
      setError('Failed to load dashboard stats. Is the backend running?');
    });
  }, []);

  const cards = [
    { label: 'Clients', value: stats.clients, icon: Building2, color: 'text-blue-600 bg-blue-50', link: '/clients' },
    { label: 'Active Missions', value: stats.active_missions, icon: Crosshair, color: 'text-green-600 bg-green-50', link: '/missions' },
    { label: 'Benchmarks', value: stats.benchmarks, icon: FileText, color: 'text-purple-600 bg-purple-50', link: '/benchmarks' },
    { label: 'Scans', value: stats.scans, icon: Play, color: 'text-orange-600 bg-orange-50', link: '/scans' },
  ];

  return (
    <div className="space-y-8">
      <div className="rounded-lg border border-gray-200 bg-gradient-to-r from-blue-50 to-purple-50 p-8 text-center">
        <Shield className="mx-auto h-10 w-10 text-blue-600 mb-3" />
        <h2 className="text-2xl font-bold text-gray-900">Welcome to AditForge</h2>
        <p className="mt-2 text-gray-600">
          Automated Configuration Review Platform — Offline-first security auditing
        </p>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
        {cards.map((stat) => {
          const Icon = stat.icon;
          return (
            <Link
              key={stat.label}
              to={stat.link}
              className="flex items-center gap-4 rounded-lg border border-gray-200 bg-white p-6 transition-shadow hover:shadow-md"
            >
              <div className={`rounded-lg p-3 ${stat.color}`}>
                <Icon className="h-6 w-6" />
              </div>
              <div>
                <p className="text-2xl font-bold text-gray-900">{stat.value}</p>
                <p className="text-sm text-gray-500">{stat.label}</p>
              </div>
            </Link>
          );
        })}
      </div>

      {/* Quick Actions */}
      <div className="rounded-lg border border-gray-200 bg-white p-6">
        <h3 className="mb-4 text-lg font-semibold text-gray-900">Quick Actions</h3>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Link
            to="/clients"
            className="flex items-center justify-between rounded-lg border border-gray-200 p-4 transition-colors hover:bg-blue-50 hover:border-blue-200"
          >
            <div className="flex items-center gap-3">
              <Building2 className="h-5 w-5 text-blue-600" />
              <span className="text-sm font-medium text-gray-900">Create a Client</span>
            </div>
            <ArrowRight className="h-4 w-4 text-gray-400" />
          </Link>
          <Link
            to="/benchmarks"
            className="flex items-center justify-between rounded-lg border border-gray-200 p-4 transition-colors hover:bg-purple-50 hover:border-purple-200"
          >
            <div className="flex items-center gap-3">
              <FileText className="h-5 w-5 text-purple-600" />
              <span className="text-sm font-medium text-gray-900">Import a Benchmark</span>
            </div>
            <ArrowRight className="h-4 w-4 text-gray-400" />
          </Link>
          <Link
            to="/scans"
            className="flex items-center justify-between rounded-lg border border-gray-200 p-4 transition-colors hover:bg-orange-50 hover:border-orange-200"
          >
            <div className="flex items-center gap-3">
              <Play className="h-5 w-5 text-orange-600" />
              <span className="text-sm font-medium text-gray-900">Run a Scan</span>
            </div>
            <ArrowRight className="h-4 w-4 text-gray-400" />
          </Link>
        </div>
      </div>
    </div>
  );
}
