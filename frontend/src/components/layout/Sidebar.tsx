import { Link, useLocation } from 'react-router-dom';
import {
  LayoutDashboard,
  Building2,
  Crosshair,
  FileText,
  Play,
  AlertTriangle,
  BarChart3,
  Settings,
  Shield,
} from 'lucide-react';
import { cn } from '@/lib/utils';

const navItems = [
  { label: 'Dashboard', icon: LayoutDashboard, path: '/' },
  { label: 'Clients', icon: Building2, path: '/clients' },
  { label: 'Missions', icon: Crosshair, path: '/missions' },
  { label: 'Benchmarks', icon: FileText, path: '/benchmarks' },
  { label: 'Scans', icon: Play, path: '/scans' },
  { label: 'Findings', icon: AlertTriangle, path: '/findings' },
  { label: 'Reports', icon: BarChart3, path: '/reports' },
  { label: 'Settings', icon: Settings, path: '/settings' },
];

export default function Sidebar() {
  const location = useLocation();

  return (
    <aside className="fixed inset-y-0 left-0 z-50 flex w-64 flex-col bg-dark border-r border-dark-border">
      {/* Logo */}
      <div className="flex h-16 items-center gap-3 border-b border-dark-border px-6">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-ey-yellow/10">
          <Shield className="h-5 w-5 text-ey-yellow" />
        </div>
        <span className="text-xl font-bold tracking-tight text-white">
          Audit<span className="text-ey-yellow">Forge</span>
        </span>
      </div>

      {/* Navigation */}
      <nav className="mt-6 flex flex-1 flex-col gap-1 px-3">
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive =
            item.path === '/'
              ? location.pathname === '/'
              : location.pathname.startsWith(item.path);

          return (
            <Link
              key={item.path}
              to={item.path}
              className={cn(
                'relative flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-all duration-200',
                isActive
                  ? 'bg-ey-yellow/10 text-ey-yellow'
                  : 'text-dark-secondary hover:bg-dark-elevated hover:text-white',
              )}
            >
              {isActive && <div className="sidebar-active-bar" />}
              <Icon className={cn('h-5 w-5', isActive ? 'text-ey-yellow' : '')} />
              {item.label}
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="border-t border-dark-border p-4">
        <div className="flex items-center gap-2">
          <div className="h-2 w-2 rounded-full bg-ey-yellow shadow-[0_0_6px_rgba(255,230,0,0.5)]" />
          <span className="text-xs text-dark-muted">AuditForge v1.0</span>
        </div>
      </div>
    </aside>
  );
}
