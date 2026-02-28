import { BrowserRouter, Routes, Route } from 'react-router-dom';
import MainLayout from './components/layout/MainLayout';
import ClientWorkspace from './pages/ClientWorkspace';
import MissionWorkspace from './pages/MissionWorkspace';
import BenchmarkDetail from './pages/BenchmarkDetail';
import FindingDetail from './pages/FindingDetail';
import MissionAnalysis from './pages/MissionAnalysis';

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<MainLayout />}>
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
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

export default App;
