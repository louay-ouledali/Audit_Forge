import { useLocation } from 'react-router-dom';
import { Shield } from 'lucide-react';

const pageTitles: Record<string, string> = {
  '/': 'Dashboard',
  '/clients': 'Clients',
  '/missions': 'Missions',
  '/benchmarks': 'Benchmarks',
  '/scans': 'Scans',
  '/findings': 'Findings',
  '/reports': 'Reports',
  '/settings': 'Settings',
};

export default function Header() {
  const location = useLocation();

  const title =
    pageTitles[location.pathname] ??
    (location.pathname.startsWith('/clients/') ? 'Client Detail' :
     location.pathname.startsWith('/benchmarks/') ? 'Benchmark Detail' :
     location.pathname.startsWith('/findings/') ? 'Finding Detail' :
     location.pathname.includes('/analysis') ? 'AI Analysis' :
     'AuditForge');

  return (
    <header className="flex h-14 items-center justify-between border-b border-dark-border bg-dark-surface/80 px-6 backdrop-blur-sm">
      <h1 className="text-sm font-semibold text-white tracking-wide uppercase">{title}</h1>
      <div className="flex items-center gap-2 text-dark-muted">
        <Shield className="h-4 w-4 text-ey-yellow/40" />
        <span className="text-xs">Offline-First Security Auditing</span>
      </div>
    </header>
  );
}
