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

/**
 * Pages that stay mounted (keep-alive) so state is preserved when
 * the user switches between sidebar tabs and comes back.
 */
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

  // Track which persistent pages have been visited so we lazily mount them
  const [activated, setActivated] = useState<Set<string>>(new Set(['/']));

  useEffect(() => {
    if (isPersistent && !activated.has(currentPath)) {
      setActivated((prev) => new Set(prev).add(currentPath));
    }
  }, [currentPath, isPersistent, activated]);

  return (
    <div className="flex min-h-screen bg-gray-50">
      <Sidebar />
      <div className="flex flex-1 flex-col pl-64">
        <Header />
        <main className="flex-1 p-6">
          {/* Persistent (keep-alive) pages — stay mounted once visited */}
          {PERSISTENT_PAGES.map(({ path, Component }) => {
            if (!activated.has(path)) return null;
            return (
              <div key={path} style={{ display: currentPath === path ? undefined : 'none' }}>
                <Component />
              </div>
            );
          })}

          {/* Detail / dynamic pages — normal React Router outlet */}
          {!isPersistent && <Outlet />}
        </main>
      </div>
    </div>
  );
}
