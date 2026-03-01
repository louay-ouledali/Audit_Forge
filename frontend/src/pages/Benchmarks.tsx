import { useEffect, useState, useRef, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Upload, Trash2, RefreshCw, ChevronRight, ChevronLeft, Database,
  Monitor, Server, Network, Cloud, AppWindow, Smartphone, GitBranch,
  Box, Shield, Laptop, Globe, HardDrive, Flame, Router,
  Search, CheckCircle2, Clock, AlertTriangle, X, LayoutGrid, List
} from 'lucide-react';
import type { CatalogCategory, CatalogVendor, ProductLine, BenchmarkCatalog, CatalogBenchmark } from '@/types';
import * as api from '@/services/api';

/* ═══════════════════════════════════════════════════════════════════════════
   Icon mapping — maps icon strings from the backend classifier to Lucide icons
   ═══════════════════════════════════════════════════════════════════════════ */

const ICON_MAP: Record<string, React.ComponentType<{ className?: string }>> = {
  monitor: Monitor, server: Server, network: Network, cloud: Cloud,
  'app-window': AppWindow, smartphone: Smartphone, 'git-branch': GitBranch,
  box: Box, shield: Shield, laptop: Laptop, globe: Globe,
  database: HardDrive, firewall: Flame, router: Router,
  container: Box, switch: Network, loadbalancer: Server,
  collaboration: AppWindow, email: AppWindow, dns: Globe,
  windows: Monitor, linux: Monitor, vmware: Server, docker: Box,
  kubernetes: Box, apple: Monitor, unix: Monitor,
  cisco: Network, paloalto: Shield, fortinet: Shield, checkpoint: Shield,
  juniper: Router, netgate: Flame, sophos: Shield, f5: Server,
  aruba: Network, extreme: Network,
  postgresql: HardDrive, mongodb: HardDrive, mariadb: HardDrive,
  oracle: HardDrive, ibm: Server, apache: Globe, nginx: Globe,
  aws: Cloud, azure: Cloud, gcp: Cloud, google: Cloud,
  github: GitBranch, gitlab: GitBranch,
  redhat: Monitor, ubuntu: Monitor, debian: Monitor, suse: Monitor,
  rocky: Monitor, almalinux: Monitor,
  chrome: AppWindow, firefox: AppWindow, office: AppWindow,
  vscode: AppWindow,
};

/* ═══════════════════════════════════════════════════════════════════════════
   Color palettes for categories
   ═══════════════════════════════════════════════════════════════════════════ */

const CATEGORY_COLORS: Record<string, { bg: string; border: string; icon: string; glow: string }> = {
  'Operating Systems': { bg: 'bg-sky-500/8', border: 'border-sky-500/20', icon: 'text-sky-400', glow: 'hover:shadow-sky-500/10' },
  'Server Software': { bg: 'bg-emerald-500/8', border: 'border-emerald-500/20', icon: 'text-emerald-400', glow: 'hover:shadow-emerald-500/10' },
  'Network Devices': { bg: 'bg-orange-500/8', border: 'border-orange-500/20', icon: 'text-orange-400', glow: 'hover:shadow-orange-500/10' },
  'Cloud Providers': { bg: 'bg-violet-500/8', border: 'border-violet-500/20', icon: 'text-violet-400', glow: 'hover:shadow-violet-500/10' },
  'Desktop Software': { bg: 'bg-pink-500/8', border: 'border-pink-500/20', icon: 'text-pink-400', glow: 'hover:shadow-pink-500/10' },
  'DevSecOps': { bg: 'bg-amber-500/8', border: 'border-amber-500/20', icon: 'text-amber-400', glow: 'hover:shadow-amber-500/10' },
  'Mobile Devices': { bg: 'bg-teal-500/8', border: 'border-teal-500/20', icon: 'text-teal-400', glow: 'hover:shadow-teal-500/10' },
  'Other': { bg: 'bg-gray-500/8', border: 'border-gray-500/20', icon: 'text-gray-400', glow: 'hover:shadow-gray-500/10' },
};

const DEFAULT_COLOR = CATEGORY_COLORS['Other'];

/* ═══════════════════════════════════════════════════════════════════════════
   Phase badge helpers
   ═══════════════════════════════════════════════════════════════════════════ */

const PHASE_LABELS: Record<string, string> = {
  not_started: 'Not Started', pending: 'Pending', processing: 'Processing',
  completed: 'Completed', failed: 'Failed', paused: 'Paused',
};
const PHASE_STYLES: Record<string, string> = {
  not_started: 'bg-dark-overlay text-dark-muted',
  pending: 'bg-amber-500/10 text-amber-400',
  processing: 'bg-sky-500/10 text-sky-400',
  completed: 'bg-emerald-500/10 text-emerald-400',
  failed: 'bg-red-500/10 text-red-400',
  paused: 'bg-amber-500/10 text-amber-400',
};

function PhaseBadge({ status }: { status: string }) {
  return (
    <span className={`inline-flex rounded-full px-2 py-0.5 text-[10px] font-medium ${PHASE_STYLES[status] ?? PHASE_STYLES.not_started}`}>
      {PHASE_LABELS[status] ?? status}
    </span>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   Utility: get icon component
   ═══════════════════════════════════════════════════════════════════════════ */

function getIcon(iconKey: string) {
  return ICON_MAP[iconKey] ?? Box;
}

/* ═══════════════════════════════════════════════════════════════════════════
   Breadcrumbs
   ═══════════════════════════════════════════════════════════════════════════ */

interface BreadcrumbItem { label: string; onClick?: () => void }

function Breadcrumbs({ items }: { items: BreadcrumbItem[] }) {
  return (
    <nav className="flex items-center gap-1 text-sm">
      {items.map((item, i) => (
        <span key={i} className="flex items-center gap-1">
          {i > 0 && <ChevronRight className="h-3 w-3 text-dark-muted" />}
          {item.onClick ? (
            <button onClick={item.onClick} className="text-dark-secondary hover:text-ey-yellow transition-colors">{item.label}</button>
          ) : (
            <span className="text-white font-medium">{item.label}</span>
          )}
        </span>
      ))}
    </nav>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   Category Card
   ═══════════════════════════════════════════════════════════════════════════ */

function CategoryCard({ category, onClick }: { category: CatalogCategory; onClick: () => void }) {
  const colors = CATEGORY_COLORS[category.name] ?? DEFAULT_COLOR;
  const Icon = getIcon(category.icon);

  return (
    <button
      onClick={onClick}
      className={`group relative flex flex-col items-start gap-4 rounded-xl border ${colors.border} ${colors.bg} p-6 text-left transition-all duration-200 hover:scale-[1.02] ${colors.glow} hover:shadow-lg`}
    >
      <div className={`rounded-xl p-3 ${colors.bg} ring-1 ring-inset ring-white/5`}>
        <Icon className={`h-8 w-8 ${colors.icon}`} />
      </div>
      <div className="flex-1">
        <h3 className="text-lg font-semibold text-white">{category.name}</h3>
        <p className="mt-1 text-sm text-dark-secondary">
          {category.benchmark_count} benchmark{category.benchmark_count !== 1 ? 's' : ''}
          <span className="mx-1.5 text-dark-muted">&middot;</span>
          {category.vendors.length} vendor{category.vendors.length !== 1 ? 's' : ''}
        </p>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {category.vendors.slice(0, 5).map((v) => (
          <span key={v.name} className="inline-flex items-center rounded-md bg-dark-elevated px-2 py-0.5 text-[11px] text-dark-secondary ring-1 ring-inset ring-dark-border">
            {v.name}
          </span>
        ))}
        {category.vendors.length > 5 && (
          <span className="inline-flex items-center rounded-md bg-dark-elevated px-2 py-0.5 text-[11px] text-dark-muted ring-1 ring-inset ring-dark-border">
            +{category.vendors.length - 5} more
          </span>
        )}
      </div>
      <ChevronRight className="absolute right-4 top-1/2 h-5 w-5 -translate-y-1/2 text-dark-muted opacity-0 transition-opacity group-hover:opacity-100" />
    </button>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   Vendor Card
   ═══════════════════════════════════════════════════════════════════════════ */

function VendorCard({ vendor, categoryName, onClick }: { vendor: CatalogVendor; categoryName: string; onClick: () => void }) {
  const colors = CATEGORY_COLORS[categoryName] ?? DEFAULT_COLOR;
  const Icon = getIcon(vendor.icon);

  return (
    <button
      onClick={onClick}
      className="group relative flex flex-col gap-3 rounded-xl border border-dark-border bg-dark-card p-5 text-left transition-all duration-200 hover:border-dark-border-hover hover:bg-dark-elevated/50 hover:scale-[1.01]"
    >
      <div className="flex items-center gap-3">
        <div className={`rounded-lg p-2 ${colors.bg}`}>
          <Icon className={`h-6 w-6 ${colors.icon}`} />
        </div>
        <div className="flex-1 min-w-0">
          <h4 className="text-base font-semibold text-white truncate">{vendor.name}</h4>
          <p className="text-xs text-dark-secondary">
            {vendor.benchmark_count} benchmark{vendor.benchmark_count !== 1 ? 's' : ''}
          </p>
        </div>
        <ChevronRight className="h-4 w-4 text-dark-muted opacity-0 transition-opacity group-hover:opacity-100 shrink-0" />
      </div>
      <div className="flex flex-wrap gap-1.5">
        {vendor.product_lines.slice(0, 4).map((pl) => (
          <span key={pl.name} className="inline-flex items-center gap-1 rounded-md bg-dark-overlay px-2 py-0.5 text-[11px] text-dark-secondary">
            {pl.name} <span className="text-dark-muted">({pl.benchmarks.length})</span>
          </span>
        ))}
        {vendor.product_lines.length > 4 && (
          <span className="inline-flex items-center rounded-md bg-dark-overlay px-2 py-0.5 text-[11px] text-dark-muted">
            +{vendor.product_lines.length - 4}
          </span>
        )}
      </div>
    </button>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   Product Line Card
   ═══════════════════════════════════════════════════════════════════════════ */

function ProductLineCard({ productLine, categoryName, onClick }: { productLine: ProductLine; categoryName: string; onClick: () => void }) {
  const colors = CATEGORY_COLORS[categoryName] ?? DEFAULT_COLOR;
  const Icon = getIcon(productLine.icon);
  const readyCount = productLine.benchmarks.filter((b) => b.is_ready).length;
  const totalRules = productLine.benchmarks.reduce((s, b) => s + b.total_rules, 0);

  return (
    <button
      onClick={onClick}
      className="group relative flex items-center gap-4 rounded-xl border border-dark-border bg-dark-card p-4 text-left transition-all duration-200 hover:border-dark-border-hover hover:bg-dark-elevated/50"
    >
      <div className={`rounded-lg p-2.5 ${colors.bg} shrink-0`}>
        <Icon className={`h-5 w-5 ${colors.icon}`} />
      </div>
      <div className="flex-1 min-w-0">
        <h5 className="text-sm font-semibold text-white truncate">{productLine.name}</h5>
        <div className="mt-0.5 flex items-center gap-2 text-xs text-dark-secondary">
          <span>{productLine.benchmarks.length} version{productLine.benchmarks.length !== 1 ? 's' : ''}</span>
          <span className="text-dark-muted">&middot;</span>
          <span>{totalRules} rules</span>
          {readyCount > 0 && (
            <>
              <span className="text-dark-muted">&middot;</span>
              <span className="text-emerald-400">{readyCount} ready</span>
            </>
          )}
        </div>
      </div>
      <ChevronRight className="h-4 w-4 text-dark-muted opacity-0 transition-opacity group-hover:opacity-100 shrink-0" />
    </button>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   Benchmark Row (final drill-down — individual benchmarks)
   ═══════════════════════════════════════════════════════════════════════════ */

function BenchmarkRow({ benchmark, onNavigate, onDelete }: { benchmark: CatalogBenchmark; onNavigate: (id: number) => void; onDelete: (id: number) => void }) {
  const StatusIcon = benchmark.is_ready ? CheckCircle2 : benchmark.phase1_status === 'failed' ? AlertTriangle : Clock;
  const statusColor = benchmark.is_ready ? 'text-emerald-400' : benchmark.phase1_status === 'failed' ? 'text-red-400' : 'text-amber-400';

  return (
    <div
      onClick={() => onNavigate(benchmark.id)}
      className="group flex items-center gap-4 rounded-lg border border-dark-border bg-dark-card p-4 cursor-pointer transition-all hover:border-dark-border-hover hover:bg-dark-elevated/50"
    >
      <StatusIcon className={`h-5 w-5 shrink-0 ${statusColor}`} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-white truncate">{benchmark.name}</span>
          <span className="shrink-0 rounded bg-dark-overlay px-1.5 py-0.5 text-[10px] text-dark-secondary">{benchmark.version}</span>
          {benchmark.source === 'preloaded' && (
            <span className="shrink-0 rounded bg-ey-yellow/10 px-1.5 py-0.5 text-[10px] font-medium text-ey-yellow">Preloaded</span>
          )}
        </div>
        <div className="mt-1 flex items-center gap-3 text-xs text-dark-secondary">
          <span>{benchmark.total_rules} rules</span>
          <span className="text-dark-muted">&middot;</span>
          <span className="flex items-center gap-1">P1: <PhaseBadge status={benchmark.phase1_status} /></span>
          <span className="flex items-center gap-1">P2: <PhaseBadge status={benchmark.phase2_status} /></span>
          <span className="flex items-center gap-1">Verify: <PhaseBadge status={benchmark.verification_status} /></span>
        </div>
      </div>
      <div className="flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100" onClick={(e) => e.stopPropagation()}>
        <button onClick={() => onDelete(benchmark.id)} className="rounded p-1.5 text-dark-muted hover:bg-red-500/10 hover:text-red-400"><Trash2 className="h-4 w-4" /></button>
        <button onClick={() => onNavigate(benchmark.id)} className="rounded p-1.5 text-dark-muted hover:bg-ey-yellow/10 hover:text-ey-yellow"><ChevronRight className="h-4 w-4" /></button>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   Stats bar
   ═══════════════════════════════════════════════════════════════════════════ */

function StatsBar({ catalog }: { catalog: BenchmarkCatalog }) {
  const allBenchmarks = catalog.categories.flatMap((c) => c.vendors.flatMap((v) => v.product_lines.flatMap((p) => p.benchmarks)));
  const totalBenchmarks = allBenchmarks.length;
  const totalVendors = catalog.categories.reduce((s, c) => s + c.vendors.length, 0);
  const readyCount = allBenchmarks.filter((b) => b.is_ready).length;
  const totalRules = allBenchmarks.reduce((s, b) => s + b.total_rules, 0);

  const stats = [
    { label: 'Benchmarks', value: totalBenchmarks },
    { label: 'Categories', value: catalog.categories.length },
    { label: 'Vendors', value: totalVendors },
    { label: 'Rules', value: totalRules.toLocaleString() },
    { label: 'Ready', value: readyCount },
  ];

  return (
    <div className="grid grid-cols-5 divide-x divide-dark-border rounded-xl border border-dark-border bg-dark-card">
      {stats.map((s) => (
        <div key={s.label} className="px-4 py-3 text-center">
          <div className="text-lg font-bold text-white">{s.value}</div>
          <div className="text-[11px] text-dark-muted uppercase tracking-wider">{s.label}</div>
        </div>
      ))}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   Navigation state
   ═══════════════════════════════════════════════════════════════════════════ */

type NavLevel = 'categories' | 'vendors' | 'products' | 'benchmarks';
interface NavState { level: NavLevel; categoryIdx?: number; vendorIdx?: number; productIdx?: number }

/* ═══════════════════════════════════════════════════════════════════════════
   Main Benchmarks Page
   ═══════════════════════════════════════════════════════════════════════════ */

export default function Benchmarks() {
  const navigate = useNavigate();
  const fileRef = useRef<HTMLInputElement>(null);

  const [catalog, setCatalog] = useState<BenchmarkCatalog | null>(null);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [nav, setNav] = useState<NavState>({ level: 'categories' });
  const [viewMode, setViewMode] = useState<'hierarchy' | 'flat'>('hierarchy');

  const allBenchmarksFlat = useMemo(() => {
    if (!catalog) return [];
    return catalog.categories.flatMap(c => c.vendors.flatMap(v => v.product_lines.flatMap(p => p.benchmarks)));
  }, [catalog]);

  /* Fetch catalog */
  const fetchCatalog = () =>
    api.getBenchmarkCatalog()
      .then(setCatalog)
      .catch(() => setError('Failed to load benchmark catalog'))
      .finally(() => setLoading(false));

  useEffect(() => { fetchCatalog(); const interval = setInterval(fetchCatalog, 8000); return () => clearInterval(interval); }, []);

  /* Upload */
  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]; if (!file) return;
    setUploading(true); setError('');
    try { await api.importBenchmark(file); await fetchCatalog(); }
    catch { setError('Benchmark import failed. Ensure it is a valid CIS benchmark PDF.'); }
    finally { setUploading(false); if (fileRef.current) fileRef.current.value = ''; }
  };

  /* Delete */
  const handleDelete = async (id: number) => {
    if (!window.confirm('Delete this benchmark and all associated data?')) return;
    try { await api.deleteBenchmark(id); await fetchCatalog(); }
    catch { setError('Failed to delete benchmark'); }
  };

  /* Navigation helpers */
  const goCategories = () => setNav({ level: 'categories' });
  const goVendors = (catIdx: number) => setNav({ level: 'vendors', categoryIdx: catIdx });
  const goProducts = (catIdx: number, vendIdx: number) => setNav({ level: 'products', categoryIdx: catIdx, vendorIdx: vendIdx });
  const goBenchmarks = (catIdx: number, vendIdx: number, prodIdx: number) => setNav({ level: 'benchmarks', categoryIdx: catIdx, vendorIdx: vendIdx, productIdx: prodIdx });

  /* Resolve current context from catalog */
  const currentCategory = catalog && nav.categoryIdx !== undefined ? catalog.categories[nav.categoryIdx] : null;
  const currentVendor = currentCategory && nav.vendorIdx !== undefined ? currentCategory.vendors[nav.vendorIdx] : null;
  const currentProduct = currentVendor && nav.productIdx !== undefined ? currentVendor.product_lines[nav.productIdx] : null;

  /* Global search */
  const searchResults = useMemo(() => {
    if (!catalog || !searchQuery.trim()) return null;
    const q = searchQuery.toLowerCase();
    const results: CatalogBenchmark[] = [];
    for (const cat of catalog.categories)
      for (const v of cat.vendors)
        for (const pl of v.product_lines)
          for (const b of pl.benchmarks)
            if (b.name.toLowerCase().includes(q) || b.platform.toLowerCase().includes(q) || b.version.toLowerCase().includes(q) || v.name.toLowerCase().includes(q) || pl.name.toLowerCase().includes(q))
              results.push(b);
    return results;
  }, [catalog, searchQuery]);

  /* Breadcrumbs */
  const breadcrumbs: BreadcrumbItem[] = [{ label: 'Benchmarks', onClick: nav.level !== 'categories' ? goCategories : undefined }];
  if (currentCategory && nav.level !== 'categories')
    breadcrumbs.push({ label: currentCategory.name, onClick: nav.level !== 'vendors' ? () => goVendors(nav.categoryIdx!) : undefined });
  if (currentVendor && nav.level !== 'vendors' && nav.level !== 'categories')
    breadcrumbs.push({ label: currentVendor.name, onClick: nav.level !== 'products' ? () => goProducts(nav.categoryIdx!, nav.vendorIdx!) : undefined });
  if (currentProduct && nav.level === 'benchmarks')
    breadcrumbs.push({ label: currentProduct.name });

  if (loading) return <div className="flex items-center justify-center py-12 text-dark-secondary">Loading...</div>;

  return (
    <div className="space-y-6">
      {/* ── Header ── */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Benchmarks</h1>
          <p className="mt-1 text-sm text-dark-secondary">CIS benchmark library — organized by category, vendor, and platform</p>
        </div>
        <div className="flex gap-2">
          <button onClick={fetchCatalog} className="rounded-lg border border-dark-border bg-dark-card px-3 py-2 text-sm text-dark-secondary hover:bg-dark-elevated hover:text-white transition-colors">
            <RefreshCw className="h-4 w-4" />
          </button>
          <button onClick={() => fileRef.current?.click()} disabled={uploading}
            className="inline-flex items-center gap-2 rounded-lg bg-ey-yellow px-4 py-2 text-sm font-medium text-black hover:bg-ey-yellow-hover disabled:opacity-50 transition-colors">
            <Upload className="h-4 w-4" /> {uploading ? 'Uploading...' : 'Import PDF'}
          </button>
          <input ref={fileRef} type="file" accept=".pdf" className="hidden" onChange={handleUpload} />
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <span className="flex-1">{error}</span>
          <button onClick={() => setError('')} className="shrink-0 p-0.5 hover:text-red-300"><X className="h-3.5 w-3.5" /></button>
        </div>
      )}

      {/* ── Stats + Search + View Toggle ── */}
      {catalog && catalog.categories.length > 0 && (
        <>
          <StatsBar catalog={catalog} />
          <div className="flex flex-col sm:flex-row gap-3">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-dark-muted" />
              <input
                type="text"
                placeholder="Search across all benchmarks..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full rounded-lg border border-dark-border bg-dark-card py-2.5 pl-10 pr-10 text-sm text-white placeholder-dark-muted focus:border-ey-yellow/30 focus:outline-none focus:ring-1 focus:ring-ey-yellow/20 transition-colors"
              />
              {searchQuery && (
                <button onClick={() => setSearchQuery('')} className="absolute right-3 top-1/2 -translate-y-1/2 text-dark-muted hover:text-white">
                  <X className="h-4 w-4" />
                </button>
              )}
            </div>

            {/* View Mode Toggle */}
            <div className="flex rounded-lg border border-dark-border bg-dark-card p-1 shadow-sm shrink-0">
              <button
                onClick={() => setViewMode('hierarchy')}
                className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${viewMode === 'hierarchy' ? 'bg-dark-elevated text-ey-yellow shadow-sm' : 'text-dark-secondary hover:text-white'
                  }`}
              >
                <LayoutGrid className="h-4 w-4" /> Hierarchy
              </button>
              <button
                onClick={() => setViewMode('flat')}
                className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${viewMode === 'flat' ? 'bg-dark-elevated text-ey-yellow shadow-sm' : 'text-dark-secondary hover:text-white'
                  }`}
              >
                <List className="h-4 w-4" /> Flat List
              </button>
            </div>
          </div>
        </>
      )}

      {/* ── Search Results ── */}
      {searchResults ? (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-medium text-dark-secondary">
              {searchResults.length} result{searchResults.length !== 1 ? 's' : ''} for &ldquo;{searchQuery}&rdquo;
            </h2>
            <button onClick={() => setSearchQuery('')} className="text-xs text-dark-muted hover:text-ey-yellow">Clear search</button>
          </div>
          {searchResults.length === 0 ? (
            <div className="rounded-xl border-2 border-dashed border-dark-border bg-dark-card p-8 text-center">
              <Search className="mx-auto h-8 w-8 text-dark-muted" />
              <p className="mt-2 text-sm text-dark-secondary">No benchmarks match your search.</p>
            </div>
          ) : (
            <div className="space-y-2">
              {searchResults.map((b) => (
                <BenchmarkRow key={b.id} benchmark={b} onNavigate={(id) => navigate(`/benchmarks/${id}`)} onDelete={handleDelete} />
              ))}
            </div>
          )}
        </div>
      ) : !catalog || catalog.categories.length === 0 ? (
        /* ── Empty state ── */
        <div className="rounded-xl border-2 border-dashed border-dark-border bg-dark-card p-12 text-center">
          <Database className="mx-auto h-10 w-10 text-dark-muted" />
          <p className="mt-3 text-dark-secondary">No benchmarks yet. Upload a CIS PDF to begin.</p>
        </div>
      ) : (
        /* ── Catalog Navigation or Flat List ── */
        <div className="space-y-4">

          {viewMode === 'flat' ? (
            <div className="space-y-4 animate-in fade-in slide-in-from-top-2 duration-300">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-lg font-bold text-white">All Benchmarks</h2>
                <span className="text-xs text-dark-secondary bg-dark-elevated px-2 py-1 rounded-md">{allBenchmarksFlat.length} items</span>
              </div>
              <div className="space-y-2 max-h-[70vh] overflow-y-auto custom-scrollbar pr-2">
                {allBenchmarksFlat.map((b) => (
                  <BenchmarkRow key={b.id} benchmark={b} onNavigate={(id) => navigate(`/benchmarks/${id}`)} onDelete={handleDelete} />
                ))}
              </div>
            </div>
          ) : (
            <>
              {/* Breadcrumbs + back */}
              {nav.level !== 'categories' && (
                <div className="flex items-center gap-3">
                  <button
                    onClick={() => {
                      if (nav.level === 'vendors') goCategories();
                      else if (nav.level === 'products') goVendors(nav.categoryIdx!);
                      else if (nav.level === 'benchmarks') goProducts(nav.categoryIdx!, nav.vendorIdx!);
                    }}
                    className="flex items-center gap-1 rounded-lg border border-dark-border bg-dark-card px-3 py-1.5 text-xs text-dark-secondary hover:bg-dark-elevated hover:text-white transition-colors"
                  >
                    <ChevronLeft className="h-3.5 w-3.5" /> Back
                  </button>
                  <Breadcrumbs items={breadcrumbs} />
                </div>
              )}

              {/* Level: Categories */}
              {nav.level === 'categories' && (
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  {catalog.categories.map((cat, i) => (
                    <CategoryCard key={cat.name} category={cat} onClick={() => goVendors(i)} />
                  ))}
                </div>
              )}

              {/* Level: Vendors */}
              {nav.level === 'vendors' && currentCategory && (
                <div>
                  <div className="mb-4 flex items-center gap-3">
                    {(() => {
                      const CatIcon = getIcon(currentCategory.icon); const colors = CATEGORY_COLORS[currentCategory.name] ?? DEFAULT_COLOR;
                      return <div className={`rounded-xl p-2.5 ${colors.bg}`}><CatIcon className={`h-6 w-6 ${colors.icon}`} /></div>;
                    })()}
                    <div>
                      <h2 className="text-xl font-bold text-white">{currentCategory.name}</h2>
                      <p className="text-xs text-dark-secondary">{currentCategory.benchmark_count} benchmarks across {currentCategory.vendors.length} vendors</p>
                    </div>
                  </div>
                  {currentCategory.vendors.length === 1 ? (
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                      {currentCategory.vendors[0].product_lines.map((pl, pIdx) => (
                        <ProductLineCard key={pl.name} productLine={pl} categoryName={currentCategory.name} onClick={() => goBenchmarks(nav.categoryIdx!, 0, pIdx)} />
                      ))}
                    </div>
                  ) : (
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                      {currentCategory.vendors.map((vendor, vIdx) => (
                        <VendorCard key={vendor.name} vendor={vendor} categoryName={currentCategory.name}
                          onClick={() => {
                            if (vendor.product_lines.length === 1 && vendor.product_lines[0].benchmarks.length <= 3)
                              goBenchmarks(nav.categoryIdx!, vIdx, 0);
                            else goProducts(nav.categoryIdx!, vIdx);
                          }}
                        />
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Level: Product Lines */}
              {nav.level === 'products' && currentVendor && currentCategory && (
                <div>
                  <div className="mb-4 flex items-center gap-3">
                    {(() => {
                      const VIcon = getIcon(currentVendor.icon); const colors = CATEGORY_COLORS[currentCategory.name] ?? DEFAULT_COLOR;
                      return <div className={`rounded-xl p-2.5 ${colors.bg}`}><VIcon className={`h-6 w-6 ${colors.icon}`} /></div>;
                    })()}
                    <div>
                      <h2 className="text-xl font-bold text-white">{currentVendor.name}</h2>
                      <p className="text-xs text-dark-secondary">{currentVendor.benchmark_count} benchmarks</p>
                    </div>
                  </div>
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                    {currentVendor.product_lines.map((pl, pIdx) => (
                      <ProductLineCard key={pl.name} productLine={pl} categoryName={currentCategory.name} onClick={() => goBenchmarks(nav.categoryIdx!, nav.vendorIdx!, pIdx)} />
                    ))}
                  </div>
                </div>
              )}

              {/* Level: Benchmarks (final list) */}
              {nav.level === 'benchmarks' && currentProduct && currentCategory && (
                <div>
                  <div className="mb-4 flex items-center gap-3">
                    {(() => {
                      const PIcon = getIcon(currentProduct.icon); const colors = CATEGORY_COLORS[currentCategory.name] ?? DEFAULT_COLOR;
                      return <div className={`rounded-xl p-2.5 ${colors.bg}`}><PIcon className={`h-6 w-6 ${colors.icon}`} /></div>;
                    })()}
                    <div>
                      <h2 className="text-xl font-bold text-white">{currentProduct.name}</h2>
                      <p className="text-xs text-dark-secondary">{currentProduct.benchmarks.length} benchmark version{currentProduct.benchmarks.length !== 1 ? 's' : ''}</p>
                    </div>
                  </div>
                  <div className="space-y-2">
                    {currentProduct.benchmarks.map((b) => (
                      <BenchmarkRow key={b.id} benchmark={b} onNavigate={(id) => navigate(`/benchmarks/${id}`)} onDelete={handleDelete} />
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
