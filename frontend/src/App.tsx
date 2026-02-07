import { BrowserRouter, Routes, Route } from 'react-router-dom';
import MainLayout from './components/layout/MainLayout';
import Dashboard from './pages/Dashboard';
import Clients from './pages/Clients';
import ClientDetail from './pages/ClientDetail';
import Settings from './pages/Settings';
import Benchmarks from './pages/Benchmarks';
import BenchmarkDetail from './pages/BenchmarkDetail';
import Scans from './pages/Scans';
import Findings from './pages/Findings';
import FindingDetail from './pages/FindingDetail';

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<MainLayout />}>
          <Route index element={<Dashboard />} />
          <Route path="clients" element={<Clients />} />
          <Route path="clients/:id" element={<ClientDetail />} />
          <Route path="benchmarks" element={<Benchmarks />} />
          <Route path="benchmarks/:id" element={<BenchmarkDetail />} />
          <Route path="scans" element={<Scans />} />
          <Route path="findings" element={<Findings />} />
          <Route path="findings/:id" element={<FindingDetail />} />
          <Route path="settings" element={<Settings />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

export default App;
