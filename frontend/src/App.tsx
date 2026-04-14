import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { lazy, Suspense } from 'react';
import MainLayout from './components/layout/MainLayout';
import AuthGuard from './components/layout/AuthGuard';
import Login from './pages/Login';
import ConnectPortal from './pages/ConnectPortal';
import { ToastProvider } from './components/common/Toast';
import { ErrorBoundary } from './components/common/ErrorBoundary';

// Code-split heavy workspace pages
const ClientWorkspace = lazy(() => import('./pages/ClientWorkspace'));
const MissionWorkspace = lazy(() => import('./pages/MissionWorkspace'));
const BenchmarkDetail = lazy(() => import('./pages/BenchmarkDetail'));
const FindingDetail = lazy(() => import('./pages/FindingDetail'));
const MissionAnalysis = lazy(() => import('./pages/MissionAnalysis'));

function LazyFallback() {
  return (
    <div className="flex min-h-[40vh] items-center justify-center">
      <div className="h-8 w-8 animate-spin rounded-full border-2 border-ey-yellow border-t-transparent" />
    </div>
  );
}

function App() {
  return (
    <ToastProvider>
    <ErrorBoundary>
    <BrowserRouter>
      <Suspense fallback={<LazyFallback />}>
      <Routes>
        {/* Standalone pages — outside MainLayout */}
        <Route path="/login" element={<Login />} />
        <Route path="/connect/:code" element={<ConnectPortal />} />

        <Route path="/" element={<AuthGuard><MainLayout /></AuthGuard>}>
          {/* Persistent pages are rendered by MainLayout via keep-alive.
              We still need index + catch-all so React Router matches them. */}
          <Route index element={<></>} />
          <Route path="clients" element={<></>} />
          <Route path="benchmarks" element={<></>} />
          <Route path="reports" element={<></>} />
          <Route path="settings" element={<></>} />

          {/* Drill-down workspace pages — rendered via <Outlet /> */}
          <Route path="clients/:id" element={<ClientWorkspace />} />
          <Route path="missions/:id" element={<MissionWorkspace />} />
          <Route path="benchmarks/:id" element={<BenchmarkDetail />} />
          <Route path="findings/:id" element={<FindingDetail />} />
          <Route path="missions/:missionId/analysis" element={<MissionAnalysis />} />

          {/* 404 catch-all */}
          <Route path="*" element={
            <div className="flex min-h-[60vh] flex-col items-center justify-center text-center">
              <h1 className="text-4xl font-bold text-white">404</h1>
              <p className="mt-2 text-dark-secondary">Page not found</p>
              <a href="/" className="mt-4 text-ey-yellow hover:underline">Back to Dashboard</a>
            </div>
          } />
        </Route>
      </Routes>
      </Suspense>
    </BrowserRouter>
    </ErrorBoundary>
    </ToastProvider>
  );
}

export default App;
