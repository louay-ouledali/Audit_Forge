import { useEffect, useState } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import Sidebar from './Sidebar';
import Header from './Header';

import Dashboard from '../../pages/Dashboard';
import Clients from '../../pages/Clients';
import Missions from '../../pages/Missions';
import Benchmarks from '../../pages/Benchmarks';
import Scans from '../../pages/Scans';
import Findings from '../../pages/Findings';
import Reports from '../../pages/Reports';
import Settings from '../../pages/Settings';

const PERSISTENT_PAGES: { path: string; Component: React.ComponentType }[] = [
  { path: '/', Component: Dashboard },
  { path: '/clients', Component: Clients },
  { path: '/missions', Component: Missions },
  { path: '/benchmarks', Component: Benchmarks },
  { path: '/scans', Component: Scans },
  { path: '/findings', Component: Findings },
  { path: '/reports', Component: Reports },
  { path: '/settings', Component: Settings },
];

const PERSISTENT_PATHS = new Set(PERSISTENT_PAGES.map((p) => p.path));

export default function MainLayout() {
  const location = useLocation();
  const currentPath = location.pathname;
  const isPersistent = PERSISTENT_PATHS.has(currentPath);

  const [activated, setActivated] = useState<Set<string>>(new Set(['/']));

  useEffect(() => {
    if (isPersistent && !activated.has(currentPath)) {
      setActivated((prev) => new Set(prev).add(currentPath));
    }
  }, [currentPath, isPersistent, activated]);

  return (
    <div className="flex min-h-screen bg-dark">
      <Sidebar />
      <div className="flex flex-1 flex-col pl-64">
        <Header />
        <main className="glow-ambient relative flex-1 overflow-y-auto p-6">
          {PERSISTENT_PAGES.map(({ path, Component }) => {
            if (!activated.has(path)) return null;
            return (
              <div key={path} style={{ display: currentPath === path ? undefined : 'none' }}>
                <Component />
              </div>
            );
          })}
          {!isPersistent && <Outlet />}
        </main>
      </div>
    </div>
  );
}
