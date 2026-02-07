import { useEffect, useState } from 'react';
import { Building2, Crosshair, FileText, Play } from 'lucide-react';
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
    { label: 'Clients', value: stats.clients, icon: Building2, color: 'text-blue-600 bg-blue-50' },
    { label: 'Active Missions', value: stats.active_missions, icon: Crosshair, color: 'text-green-600 bg-green-50' },
    { label: 'Benchmarks', value: stats.benchmarks, icon: FileText, color: 'text-purple-600 bg-purple-50' },
    { label: 'Scans', value: stats.scans, icon: Play, color: 'text-orange-600 bg-orange-50' },
  ];

  return (
    <div className="space-y-8">
      <div className="rounded-lg border border-gray-200 bg-white p-8 text-center">
        <h2 className="text-2xl font-bold text-gray-900">Welcome to AditForge</h2>
        <p className="mt-2 text-gray-500">
          Get started by importing a CIS Benchmark or creating a client
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
            <div
              key={stat.label}
              className="flex items-center gap-4 rounded-lg border border-gray-200 bg-white p-6"
            >
              <div className={`rounded-lg p-3 ${stat.color}`}>
                <Icon className="h-6 w-6" />
              </div>
              <div>
                <p className="text-2xl font-bold text-gray-900">{stat.value}</p>
                <p className="text-sm text-gray-500">{stat.label}</p>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
