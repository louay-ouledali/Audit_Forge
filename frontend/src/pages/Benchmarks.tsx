import { useEffect, useState, useRef, useMemo, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Upload, Trash2, RefreshCw, ChevronRight, ChevronLeft, Database,
  Monitor, Server, Network, Cloud, AppWindow, Smartphone, GitBranch,
  Box, Shield, Laptop, Globe, HardDrive, Flame, Router,
  Search, CheckCircle2, Clock, AlertTriangle, X, LayoutGrid, List, Plus, MoreVertical, Filter, Sparkles
} from 'lucide-react';
import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import type { CatalogCategory, CatalogVendor, ProductLine, BenchmarkCatalog, CatalogBenchmark } from '@/types';
import * as api from '@/services/api';
import ConfirmDialog from '@/components/common/ConfirmDialog';

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
  const versionCount = productLine.version_count ?? productLine.benchmarks.length;
  const frameworks = productLine.frameworks ?? [...new Set(productLine.benchmarks.map(b => b.framework ?? 'cis'))];

  const FW_COLORS: Record<string, string> = {
    cis: 'bg-sky-500/15 text-sky-300',
    stig: 'bg-amber-500/15 text-amber-300',
    nist: 'bg-green-500/15 text-green-300',
    iso: 'bg-purple-500/15 text-purple-300',
    disa: 'bg-orange-500/15 text-orange-300',
    custom: 'bg-gray-500/15 text-gray-300',
  };

  return (
    <button
      onClick={onClick}
      className="group relative flex items-center gap-4 rounded-xl border border-dark-border bg-dark-card p-4 text-left transition-all duration-200 hover:border-dark-border-hover hover:bg-dark-elevated/50"
    >
      <div className={`rounded-lg p-2.5 ${colors.bg} shrink-0`}>
        <Icon className={`h-5 w-5 ${colors.icon}`} />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <h5 className="text-sm font-semibold text-white truncate">{productLine.name}</h5>
          {versionCount > 1 && (
            <span className="shrink-0 rounded-full bg-ey-yellow/15 px-1.5 py-0.5 text-[10px] font-semibold text-ey-yellow">{versionCount}v</span>
          )}
          {frameworks.filter(fw => fw !== 'cis').map(fw => (
            <span key={fw} className={`shrink-0 rounded px-1 py-0.5 text-[9px] font-semibold uppercase tracking-wider ${FW_COLORS[fw] ?? FW_COLORS.custom}`}>{fw}</span>
          ))}
        </div>
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
          {benchmark.source === 'nessus_reconstructed' && (
            <span className="shrink-0 rounded bg-emerald-500/10 px-1.5 py-0.5 text-[10px] font-medium text-emerald-400">Nessus Import</span>
          )}
          {benchmark.source === 'imported' && (
            <span className="shrink-0 rounded bg-sky-500/10 px-1.5 py-0.5 text-[10px] font-medium text-sky-400">Imported</span>
          )}
          {benchmark.source === 'custom' && (
            <span className="shrink-0 rounded bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-400">Custom</span>
          )}
          {benchmark.framework && benchmark.framework !== 'cis' && (
            <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
              benchmark.framework === 'stig' ? 'bg-amber-500/15 text-amber-300' :
              benchmark.framework === 'nist' ? 'bg-green-500/15 text-green-300' :
              benchmark.framework === 'iso' ? 'bg-purple-500/15 text-purple-300' :
              benchmark.framework === 'disa' ? 'bg-orange-500/15 text-orange-300' :
              'bg-gray-500/15 text-gray-300'
            }`}>{benchmark.framework}</span>
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
      <div className="flex items-center gap-1 opacity-100" onClick={(e) => e.stopPropagation()}>
        <DropdownMenu.Root>
          <DropdownMenu.Trigger asChild>
            <button className="rounded-md p-1.5 text-dark-muted hover:bg-dark-elevated hover:text-white data-[state=open]:bg-dark-elevated data-[state=open]:text-white transition-colors">
              <MoreVertical className="h-4 w-4" />
            </button>
          </DropdownMenu.Trigger>
          <DropdownMenu.Portal>
            <DropdownMenu.Content
              className="min-w-[160px] bg-dark-card border border-dark-border rounded-xl p-1 shadow-xl animate-in fade-in zoom-in-95 z-50"
              sideOffset={5}
              align="end"
              onClick={(e) => e.stopPropagation()}
            >
              <DropdownMenu.Item
                className="flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm text-dark-secondary outline-none hover:bg-dark-elevated hover:text-white"
                onClick={() => onNavigate(benchmark.id)}
              >
                <ChevronRight className="h-4 w-4" /> Open Details
              </DropdownMenu.Item>
              <DropdownMenu.Separator className="my-1 h-px bg-dark-border" />
              <DropdownMenu.Item
                className="flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm text-red-400 outline-none hover:bg-red-500/10"
                onClick={() => onDelete(benchmark.id)}
              >
                <Trash2 className="h-4 w-4" /> Delete
              </DropdownMenu.Item>
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        </DropdownMenu.Root>
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
  const [viewMode, setViewMode] = useState<'hierarchy' | 'flat'>('flat');
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [newBenchmarkName, setNewBenchmarkName] = useState('');
  const [newBenchmarkPlatform, setNewBenchmarkPlatform] = useState('Windows');
  const [newBenchmarkFamily, setNewBenchmarkFamily] = useState('windows');
  const [creating, setCreating] = useState(false);
  const [deletingBenchmarkId, setDeletingBenchmarkId] = useState<number | null>(null);
  const [frameworkFilter, setFrameworkFilter] = useState<string>('all');

  /* Platform → family auto-link map (values must match backend: linux, windows, network, cloud, database, other) */
  const PLATFORM_TO_FAMILY: Record<string, string> = {
    Windows: 'windows', Linux: 'linux', macOS: 'linux',
    Network: 'network', Cloud: 'cloud', Database: 'database', Other: 'other',
  };
  const handlePlatformChange = useCallback((platform: string) => {
    setNewBenchmarkPlatform(platform);
    const mapped = PLATFORM_TO_FAMILY[platform];
    if (mapped) setNewBenchmarkFamily(mapped);
  }, []);

  const allBenchmarksFlat = useMemo(() => {
    if (!catalog) return [];
    return catalog.categories.flatMap(c => c.vendors.flatMap(v => v.product_lines.flatMap(p => p.benchmarks)));
  }, [catalog]);

  /* Collect unique frameworks for filter dropdown */
  const availableFrameworks = useMemo(() => {
    const fws = new Set<string>();
    for (const b of allBenchmarksFlat) fws.add(b.framework ?? 'cis');
    return Array.from(fws).sort();
  }, [allBenchmarksFlat]);

  /* Apply framework filter to catalog (returns a pruned copy) */
  const filteredCatalog = useMemo(() => {
    if (!catalog || frameworkFilter === 'all') return catalog;
    const filtered: BenchmarkCatalog = {
      ...catalog,
      categories: catalog.categories.map(cat => ({
        ...cat,
        vendors: cat.vendors.map(v => ({
          ...v,
          product_lines: v.product_lines.map(pl => ({
            ...pl,
            benchmarks: pl.benchmarks.filter(b => (b.framework ?? 'cis') === frameworkFilter),
          })).filter(pl => pl.benchmarks.length > 0),
        })).filter(v => v.product_lines.length > 0),
      })).filter(cat => cat.vendors.length > 0),
    };
    return filtered;
  }, [catalog, frameworkFilter]);

  /* Fetch catalog */
  const fetchCatalog = () =>
    api.getBenchmarkCatalog()
      .then(setCatalog)
      .catch(() => setError('Failed to load benchmark catalog'))
      .finally(() => setLoading(false));

  // Check if any benchmark is currently processing (needs polling)
  const hasProcessing = useMemo(() => {
    if (!catalog) return false;
    return catalog.categories.some(c =>
      c.vendors.some(v =>
        v.product_lines.some(p =>
          p.benchmarks.some(b =>
            b.phase1_status === 'processing' || b.phase2_status === 'processing' || b.verification_status === 'processing'
          )
        )
      )
    );
  }, [catalog]);

  useEffect(() => {
    fetchCatalog();
  }, []);

  // Only poll when something is actively processing
  useEffect(() => {
    if (!hasProcessing) return;
    const interval = setInterval(() => {
      if (!document.hidden) fetchCatalog();
    }, 8000);
    return () => clearInterval(interval);
  }, [hasProcessing]);

  /* Upload */
  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]; if (!file) return;
    setUploading(true); setError('');
    try { await api.importBenchmark(file); await fetchCatalog(); }
    catch { setError('Benchmark import failed. Ensure it is a valid CIS benchmark PDF, Nessus CSV, or HTML export.'); }
    finally { setUploading(false); if (fileRef.current) fileRef.current.value = ''; }
  };

  /* Delete */
  const handleDelete = async (id: number) => {
    setDeletingBenchmarkId(id);
  };
  const confirmDelete = async () => {
    if (deletingBenchmarkId == null) return;
    try { await api.deleteBenchmark(deletingBenchmarkId); await fetchCatalog(); }
    catch { setError('Failed to delete benchmark'); }
    finally { setDeletingBenchmarkId(null); }
  };

  /* Create Custom Benchmark */
  const handleCreateCustom = async (aiAssisted = false) => {
    if (!newBenchmarkName.trim()) return;
    setCreating(true); setError('');
    try {
      const result = await api.createCustomBenchmark({
        name: newBenchmarkName.trim(),
        platform: newBenchmarkPlatform,
        platform_family: newBenchmarkFamily,
      });
      setShowCreateDialog(false);
      setNewBenchmarkName('');
      await fetchCatalog();
      navigate(`/benchmarks/${result.benchmark_id}`, { state: { openCopilot: aiAssisted } });
    } catch (err: unknown) {
      setError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Failed to create benchmark');
    } finally {
      setCreating(false);
    }
  };

  /* Navigation helpers */
  const goCategories = () => setNav({ level: 'categories' });
  const goVendors = (catIdx: number) => setNav({ level: 'vendors', categoryIdx: catIdx });
  const goProducts = (catIdx: number, vendIdx: number) => setNav({ level: 'products', categoryIdx: catIdx, vendorIdx: vendIdx });
  const goBenchmarks = (catIdx: number, vendIdx: number, prodIdx: number) => setNav({ level: 'benchmarks', categoryIdx: catIdx, vendorIdx: vendIdx, productIdx: prodIdx });

  /* Resolve current context from catalog */
  const currentCategory = filteredCatalog && nav.categoryIdx !== undefined ? filteredCatalog.categories[nav.categoryIdx] : null;
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
            if (
              (frameworkFilter === 'all' || (b.framework ?? 'cis') === frameworkFilter) &&
              (b.name.toLowerCase().includes(q) || b.platform.toLowerCase().includes(q) || b.version.toLowerCase().includes(q) || v.name.toLowerCase().includes(q) || pl.name.toLowerCase().includes(q))
            )
              results.push(b);
    return results;
  }, [catalog, searchQuery, frameworkFilter]);

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
        {/* ── Branded Header: Benchmark Studio ── */}
        <div className="relative overflow-hidden rounded-2xl border border-violet-500/20 bg-dark-card/60 p-8 shadow-[0_0_40px_rgba(139,92,246,0.05)] backdrop-blur-md">
          {/* Subtle violet knowledge node motif */}
          <div className="absolute top-0 right-0 -mr-16 -mt-16 h-64 w-64 rounded-full bg-violet-600/10 blur-[80px] pointer-events-none" />
          <div className="absolute inset-0 bg-[url('data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMjAiIGhlaWdodD0iMjAiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+PGNpcmNsZSBjeD0iMiIgY3k9IjIiIHI9IjEiIGZpbGw9InJnYmEoMTM5LCA5MiwgMjQ2LCAwLjE1KSIvPjwvc3ZnPg==')] pointer-events-none mask-image:linear-gradient(to_bottom,white,transparent)" />
          
          <div className="relative z-10 flex flex-col md:flex-row md:items-center justify-between gap-6">
            <div className="flex flex-row items-center gap-5">
              <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-violet-500/10 border border-violet-500/20 shadow-[0_0_20px_rgba(139,92,246,0.15)]">
                <Database className="h-7 w-7 text-violet-400" />
              </div>
              <div>
                <h1 className="text-3xl font-bold text-white tracking-tight">Benchmark Studio</h1>
                <p className="mt-1 text-sm text-dark-secondary max-w-md">Import, enrich, and manage security frameworks and knowledge bases</p>
              </div>
            </div>
            <div className="flex flex-wrap gap-3">
              <button onClick={fetchCatalog} className="h-10 rounded-xl border border-dark-border bg-dark-card/80 px-4 py-2 text-sm text-dark-secondary hover:border-violet-500/30 hover:bg-violet-500/5 hover:text-violet-300 transition-all shadow-sm">
                <RefreshCw className="h-4 w-4" />
              </button>
              <button onClick={() => setShowCreateDialog(true)}
                className="h-10 inline-flex items-center gap-2 rounded-xl border border-violet-500/30 bg-violet-500/10 px-5 py-2 text-sm font-medium text-violet-300 hover:bg-violet-500/20 transition-all shadow-sm">
                <Plus className="h-4 w-4" /> Custom Base
              </button>
              <button onClick={() => fileRef.current?.click()} disabled={uploading}
                className="h-10 inline-flex items-center gap-2 rounded-xl bg-ey-yellow px-5 py-2 text-sm font-medium text-black hover:bg-ey-yellow-hover disabled:opacity-50 transition-all shadow-[0_0_15px_rgba(255,230,0,0.2)] hover:shadow-[0_0_20px_rgba(255,230,0,0.3)]">
                <Upload className="h-4 w-4" /> {uploading ? 'Importing...' : 'Import Framework'}
              </button>
              <input ref={fileRef} type="file" accept=".pdf,.csv,.html,.htm,.json,.nessus,.xml" className="hidden" onChange={handleUpload} />
            </div>
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <span className="flex-1">{error}</span>
          <button onClick={() => setError('')} className="shrink-0 p-0.5 hover:text-red-300"><X className="h-3.5 w-3.5" /></button>
        </div>
      )}

      {/* Create Custom Benchmark Dialog */}
      {showCreateDialog && (
        <div className="rounded-xl border border-ey-yellow/30 bg-dark-card p-5 space-y-4">
          <h3 className="text-base font-semibold text-white flex items-center gap-2">
            <Plus className="h-5 w-5 text-ey-yellow" /> Create Custom Benchmark
          </h3>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div className="sm:col-span-3">
              <label className="block text-xs text-dark-secondary mb-1">Benchmark Name *</label>
              <input type="text" value={newBenchmarkName} onChange={(e) => setNewBenchmarkName(e.target.value)}
                placeholder="e.g. My Custom Windows Hardening v1.0"
                className="w-full rounded-lg border border-dark-border bg-dark-elevated px-3 py-2 text-sm text-white placeholder-dark-muted focus:border-ey-yellow/30 focus:outline-none focus:ring-1 focus:ring-ey-yellow/20" />
            </div>
            <div>
              <label className="block text-xs text-dark-secondary mb-1">Platform</label>
              <select value={newBenchmarkPlatform} onChange={(e) => handlePlatformChange(e.target.value)}
                className="w-full rounded-lg border border-dark-border bg-dark-elevated px-3 py-2 text-sm text-white focus:border-ey-yellow/30 focus:outline-none focus:ring-1 focus:ring-ey-yellow/20">
                <option value="Windows">Windows</option>
                <option value="Linux">Linux</option>
                <option value="macOS">macOS</option>
                <option value="Network">Network Device</option>
                <option value="Cloud">Cloud Provider</option>
                <option value="Database">Database</option>
                <option value="Other">Other</option>
              </select>
            </div>
            <div>
              <label className="block text-xs text-dark-secondary mb-1">Platform Family</label>
              <select value={newBenchmarkFamily} onChange={(e) => setNewBenchmarkFamily(e.target.value)}
                className="w-full rounded-lg border border-dark-border bg-dark-elevated px-3 py-2 text-sm text-white focus:border-ey-yellow/30 focus:outline-none focus:ring-1 focus:ring-ey-yellow/20">
                <option value="windows">Windows</option>
                <option value="linux">Linux / Unix / macOS</option>
                <option value="network">Network</option>
                <option value="cloud">Cloud</option>
                <option value="database">Database</option>
                <option value="other">Other</option>
              </select>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <button onClick={() => handleCreateCustom(false)} disabled={creating || !newBenchmarkName.trim()}
              className="inline-flex items-center gap-2 rounded-lg bg-ey-yellow px-4 py-2 text-sm font-medium text-black hover:bg-ey-yellow-hover disabled:opacity-50 transition-colors">
              {creating ? 'Creating...' : 'Create Empty'}
            </button>
            <button onClick={() => handleCreateCustom(true)} disabled={creating || !newBenchmarkName.trim()}
              className="inline-flex items-center gap-2 rounded-lg bg-amber-500/15 border border-amber-500/40 px-4 py-2 text-sm font-medium text-amber-400 hover:bg-amber-500/25 disabled:opacity-50 transition-colors">
              <Sparkles className="h-3.5 w-3.5" /> {creating ? 'Creating...' : 'AI-Assisted'}
            </button>
            <button onClick={() => { setShowCreateDialog(false); setNewBenchmarkName(''); }}
              className="rounded-lg border border-dark-border px-4 py-2 text-sm text-dark-secondary hover:bg-dark-overlay hover:text-white transition-colors">
              Cancel
            </button>
          </div>
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

            {/* Framework Filter */}
            {availableFrameworks.length > 1 && (
              <div className="flex items-center gap-1.5 rounded-lg border border-dark-border bg-dark-card px-3 py-2 shrink-0">
                <Filter className="h-3.5 w-3.5 text-dark-muted" />
                <select
                  value={frameworkFilter}
                  onChange={(e) => setFrameworkFilter(e.target.value)}
                  className="bg-transparent text-xs font-medium text-dark-secondary outline-none cursor-pointer"
                >
                  <option value="all">All Frameworks</option>
                  {availableFrameworks.map(fw => (
                    <option key={fw} value={fw}>{fw.toUpperCase()}</option>
                  ))}
                </select>
              </div>
            )}

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
                <span className="text-xs text-dark-secondary bg-dark-elevated px-2 py-1 rounded-md">
                  {(frameworkFilter === 'all' ? allBenchmarksFlat : allBenchmarksFlat.filter(b => (b.framework ?? 'cis') === frameworkFilter)).length} items
                </span>
              </div>
              <div className="space-y-2 max-h-[70vh] overflow-y-auto custom-scrollbar pr-2">
                {(frameworkFilter === 'all' ? allBenchmarksFlat : allBenchmarksFlat.filter(b => (b.framework ?? 'cis') === frameworkFilter)).map((b) => (
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
              {nav.level === 'categories' && filteredCatalog && (
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  {filteredCatalog.categories.map((cat, i) => (
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

      {/* Delete confirmation dialog */}
      <ConfirmDialog
        open={deletingBenchmarkId != null}
        title="Delete Benchmark"
        message="Delete this benchmark and all associated data? This action cannot be undone."
        confirmLabel="Delete"
        variant="danger"
        onConfirm={confirmDelete}
        onCancel={() => setDeletingBenchmarkId(null)}
      />
    </div>
  );
}
