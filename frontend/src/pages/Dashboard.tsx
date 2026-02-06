import { Building2, Crosshair, FileText, Play } from 'lucide-react';

const stats = [
  { label: 'Clients', value: '0', icon: Building2, color: 'text-blue-600 bg-blue-50' },
  { label: 'Active Missions', value: '0', icon: Crosshair, color: 'text-green-600 bg-green-50' },
  { label: 'Benchmarks', value: '0', icon: FileText, color: 'text-purple-600 bg-purple-50' },
  { label: 'Recent Scans', value: '0', icon: Play, color: 'text-orange-600 bg-orange-50' },
];

export default function Dashboard() {
  return (
    <div className="space-y-8">
      <div className="rounded-lg border border-gray-200 bg-white p-8 text-center">
        <h2 className="text-2xl font-bold text-gray-900">Welcome to AditForge</h2>
        <p className="mt-2 text-gray-500">
          Get started by importing a CIS Benchmark or creating a client
        </p>
      </div>

      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
        {stats.map((stat) => {
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
