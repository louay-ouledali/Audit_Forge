import { useEffect, useState } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import Navbar from './Navbar';
import AmbientSpotlight from './AmbientSpotlight';

import Dashboard from '../../pages/Dashboard';
import Clients from '../../pages/Clients';
import Benchmarks from '../../pages/Benchmarks';
import Reports from '../../pages/Reports';
import Settings from '../../pages/Settings';

const PERSISTENT_PAGES: { path: string; Component: React.ComponentType }[] = [
  { path: '/', Component: Dashboard },
  { path: '/clients', Component: Clients },
  { path: '/benchmarks', Component: Benchmarks },
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
    <div className="flex min-h-screen bg-dark overflow-hidden flex-col">
      <AmbientSpotlight />
      <Navbar />
      <div className="flex min-w-0 flex-1 flex-col pt-24 px-4 pb-4">
        <main className="relative flex-1 overflow-y-auto overflow-x-hidden rounded-2xl border border-dark-border/30 bg-dark/50 p-6 backdrop-blur-sm shadow-xl">
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
