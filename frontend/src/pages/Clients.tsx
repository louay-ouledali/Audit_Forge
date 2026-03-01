import { useEffect, useState, useMemo } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Plus, Pencil, Trash2, Search, Building2, Mail, User, X, LayoutGrid, List, ArrowUpDown, ArrowRight } from 'lucide-react';
import type { Client } from '@/types';
import * as api from '@/services/api';

interface ClientForm {
  name: string;
  industry: string;
  contact_name: string;
  contact_email: string;
  notes: string;
}

const emptyForm: ClientForm = { name: '', industry: '', contact_name: '', contact_email: '', notes: '' };

type SortOption = 'name_asc' | 'name_desc' | 'missions_desc' | 'missions_asc' | 'newest';
type ViewMode = 'grid' | 'list';

export default function Clients() {
  const navigate = useNavigate();
  const location = useLocation();
  const [clients, setClients] = useState<Client[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState<ClientForm>(emptyForm);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');

  // New State for UI/UX Improvements
  const [sortBy, setSortBy] = useState<SortOption>('name_asc');
  const [viewMode, setViewMode] = useState<ViewMode>('grid');

  const fetchClients = async () => {
    try { setClients(await api.getClients()); }
    catch { setError('Failed to load clients'); }
    finally { setLoading(false); }
  };

  useEffect(() => { if (location.pathname === '/clients') fetchClients(); }, [location.pathname]);

  const filteredAndSortedClients = useMemo(() => {
    let result = clients;

    // 1. Filter
    if (search.trim()) {
      const q = search.toLowerCase();
      result = result.filter(c =>
        c.name.toLowerCase().includes(q) ||
        (c.industry ?? '').toLowerCase().includes(q) ||
        (c.contact_name ?? '').toLowerCase().includes(q) ||
        (c.contact_email ?? '').toLowerCase().includes(q),
      );
    }

    // 2. Sort
    return [...result].sort((a, b) => {
      switch (sortBy) {
        case 'name_asc': return a.name.localeCompare(b.name);
        case 'name_desc': return b.name.localeCompare(a.name);
        case 'missions_desc': return b.mission_count - a.mission_count;
        case 'missions_asc': return a.mission_count - b.mission_count;
        case 'newest': return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
        default: return 0;
      }
    });
  }, [clients, search, sortBy]);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => {
    setForm({ ...form, [e.target.name]: e.target.value });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    try {
      if (editingId) await api.updateClient(editingId, form);
      else await api.createClient(form);
      setShowForm(false); setEditingId(null); setForm(emptyForm);
      await fetchClients();
    } catch { setError(editingId ? 'Failed to update client' : 'Failed to create client'); }
  };

  const handleEdit = (client: Client) => {
    setForm({ name: client.name, industry: client.industry ?? '', contact_name: client.contact_name ?? '', contact_email: client.contact_email ?? '', notes: client.notes ?? '' });
    setEditingId(client.id); setShowForm(true);
  };

  const handleDelete = async (id: number) => {
    if (!window.confirm('Delete this client and all associated data?')) return;
    try { await api.deleteClient(id); await fetchClients(); }
    catch { setError('Failed to delete client'); }
  };

  const handleCancel = () => { setShowForm(false); setEditingId(null); setForm(emptyForm); setError(''); };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-ey-yellow border-t-transparent" />
      </div>
    );
  }

  return (
    <div className="relative z-10 space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-2xl font-bold text-white">Clients</h2>
          <p className="mt-1 text-sm text-dark-secondary">{clients.length} client{clients.length !== 1 ? 's' : ''} registered</p>
        </div>
        <button
          onClick={() => { setShowForm(true); setEditingId(null); setForm(emptyForm); }}
          className="inline-flex items-center gap-2 rounded-lg bg-ey-yellow px-4 py-2.5 text-sm font-semibold text-black shadow-sm transition-colors hover:bg-ey-yellow-hover"
        >
          <Plus className="h-4 w-4" /> New Client
        </button>
      </div>

      {/* Search, Sort & View Toggle Toolbar */}
      {clients.length > 0 && (
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="relative w-full sm:max-w-md">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-dark-muted" />
            <input
              type="text" placeholder="Search clients by name, industry, contact…" value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full rounded-lg border border-dark-border bg-dark-card py-2.5 pl-10 pr-4 text-sm text-white placeholder:text-dark-muted focus:border-ey-yellow/50 focus:outline-none focus:ring-1 focus:ring-ey-yellow/30 transition-all"
            />
            {search && (
              <button onClick={() => setSearch('')} className="absolute right-3 top-1/2 -translate-y-1/2 text-dark-muted hover:text-white">
                <X className="h-4 w-4" />
              </button>
            )}
          </div>

          <div className="flex items-center gap-3 self-end sm:self-auto">
            <div className="flex items-center gap-2 rounded-lg border border-dark-border bg-dark-card px-3 py-2">
              <ArrowUpDown className="h-4 w-4 text-dark-muted" />
              <select
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value as SortOption)}
                className="bg-transparent text-sm text-dark-secondary focus:outline-none focus:text-white transition-colors cursor-pointer appearance-none pr-4"
              >
                <option value="name_asc">Name (A-Z)</option>
                <option value="name_desc">Name (Z-A)</option>
                <option value="missions_desc">Most Missions</option>
                <option value="missions_asc">Least Missions</option>
                <option value="newest">Recently Added</option>
              </select>
            </div>

            <div className="flex items-center rounded-lg border border-dark-border bg-dark-card p-1">
              <button
                onClick={() => setViewMode('grid')}
                className={`rounded p-1.5 transition-colors ${viewMode === 'grid' ? 'bg-dark-elevated text-ey-yellow' : 'text-dark-muted hover:text-white'}`}
                title="Grid View"
              >
                <LayoutGrid className="h-4 w-4" />
              </button>
              <button
                onClick={() => setViewMode('list')}
                className={`rounded p-1.5 transition-colors ${viewMode === 'list' ? 'bg-dark-elevated text-ey-yellow' : 'text-dark-muted hover:text-white'}`}
                title="List View"
              >
                <List className="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>
      )}

      {error && <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-400">{error}</div>}

      {/* Modal */}
      {showForm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
          <form onSubmit={handleSubmit} className="w-full max-w-lg rounded-xl border border-dark-border bg-dark-elevated p-6 shadow-2xl space-y-5 animate-in fade-in zoom-in-95 duration-200">
            <div className="flex items-center justify-between border-b border-dark-border pb-4">
              <h3 className="text-xl font-semibold text-white">{editingId ? 'Edit Client' : 'New Client'}</h3>
              <button type="button" onClick={handleCancel} className="rounded-md p-1.5 text-dark-muted hover:bg-dark-overlay hover:text-white transition-colors"><X className="h-5 w-5" /></button>
            </div>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 pt-2">
              <div className="sm:col-span-2">
                <label className="mb-1 block text-sm font-medium text-dark-secondary">Name *</label>
                <input name="name" value={form.name} onChange={handleChange} required placeholder="e.g. Acme Corporation"
                  className="block w-full rounded-lg border border-dark-border bg-dark-card px-3 py-2 text-sm text-white placeholder:text-dark-muted focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30 focus:outline-none transition-all" />
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium text-dark-secondary">Industry</label>
                <input name="industry" value={form.industry} onChange={handleChange} placeholder="e.g. Finance, Healthcare"
                  className="block w-full rounded-lg border border-dark-border bg-dark-card px-3 py-2 text-sm text-white placeholder:text-dark-muted focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30 focus:outline-none transition-all" />
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium text-dark-secondary">Contact Name</label>
                <input name="contact_name" value={form.contact_name} onChange={handleChange} placeholder="Primary contact"
                  className="block w-full rounded-lg border border-dark-border bg-dark-card px-3 py-2 text-sm text-white placeholder:text-dark-muted focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30 focus:outline-none transition-all" />
              </div>
              <div className="sm:col-span-2">
                <label className="mb-1 block text-sm font-medium text-dark-secondary">Contact Email</label>
                <input name="contact_email" type="email" value={form.contact_email} onChange={handleChange} placeholder="email@company.com"
                  className="block w-full rounded-lg border border-dark-border bg-dark-card px-3 py-2 text-sm text-white placeholder:text-dark-muted focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30 focus:outline-none transition-all" />
              </div>
              <div className="sm:col-span-2">
                <label className="mb-1 block text-sm font-medium text-dark-secondary">Notes</label>
                <textarea name="notes" value={form.notes} onChange={handleChange} rows={3} placeholder="Internal notes about this client…"
                  className="block w-full rounded-lg border border-dark-border bg-dark-card px-3 py-2 text-sm text-white placeholder:text-dark-muted focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30 focus:outline-none transition-all resize-none custom-scrollbar" />
              </div>
            </div>
            <div className="flex justify-end gap-3 border-t border-dark-border pt-5">
              <button type="button" onClick={handleCancel} className="rounded-lg border border-dark-border bg-dark-card px-4 py-2 text-sm font-medium text-dark-secondary hover:bg-dark-overlay hover:text-white transition-colors">Cancel</button>
              <button type="submit" className="rounded-lg bg-ey-yellow px-5 py-2 text-sm font-semibold text-black hover:bg-ey-yellow-hover shadow-lg shadow-ey-yellow/10 transition-all">{editingId ? 'Save Changes' : 'Create Client'}</button>
            </div>
          </form>
        </div>
      )}

      {/* Empty State vs Client List */}
      {filteredAndSortedClients.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-xl border-2 border-dashed border-dark-border bg-dark-card/50 py-24 text-center">
          <div className="rounded-full bg-dark-elevated p-4 mb-4 ring-1 ring-dark-border">
            <Building2 className="h-10 w-10 text-dark-muted" />
          </div>
          <h3 className="text-lg font-semibold text-white">{search ? 'No clients found' : 'No clients yet'}</h3>
          <p className="mt-2 text-sm text-dark-secondary max-w-sm">
            {search
              ? `We couldn't find any clients matching "${search}". Try adjusting your filters or search terms.`
              : 'Get started by creating your first client profile to manage missions and targets.'}
          </p>
          {!search && (
            <button onClick={() => { setShowForm(true); setEditingId(null); setForm(emptyForm); }}
              className="mt-6 inline-flex items-center gap-2 rounded-lg bg-ey-yellow px-5 py-2.5 text-sm font-semibold text-black hover:bg-ey-yellow-hover shadow-lg shadow-ey-yellow/10 transition-all">
              <Plus className="h-4 w-4" /> Create First Client
            </button>
          )}
        </div>
      ) : (
        <div className={
          viewMode === 'grid'
            ? "grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4"
            : "flex flex-col gap-3"
        }>
          {filteredAndSortedClients.map((client) => (
            <div
              key={client.id}
              onClick={() => navigate(`/clients/${client.id}`)}
              className={`glow-card group relative rounded-xl border border-dark-border bg-dark-card transition-all duration-300 hover:border-dark-hover cursor-pointer ${viewMode === 'grid' ? 'p-5' : 'p-4 flex items-center justify-between'
                }`}
            >
              {/* Actions */}
              <div className={`absolute right-3 ${viewMode === 'grid' ? 'top-3' : 'top-1/2 -translate-y-1/2'} flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity`}>
                <button onClick={(e) => { e.stopPropagation(); handleEdit(client); }} className="rounded-md p-1.5 text-dark-muted hover:bg-ey-yellow/10 hover:text-ey-yellow transition-colors" title="Edit"><Pencil className="h-4 w-4" /></button>
                <button onClick={(e) => { e.stopPropagation(); handleDelete(client.id); }} className="rounded-md p-1.5 text-dark-muted hover:bg-red-500/10 hover:text-red-400 transition-colors" title="Delete"><Trash2 className="h-4 w-4" /></button>
              </div>

              {/* Grid View specific layout */}
              {viewMode === 'grid' && (
                <>
                  <div className="flex items-start gap-3">
                    <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-ey-yellow/10 border border-ey-yellow/20 text-ey-yellow shadow-sm">
                      <Building2 className="h-6 w-6" />
                    </div>
                    <div className="min-w-0 flex-1 pr-12">
                      <h3 className="truncate text-base font-semibold text-white group-hover:text-ey-yellow transition-colors">{client.name}</h3>
                      {client.industry && <span className="mt-1 inline-block rounded-md bg-dark-overlay px-2 py-0.5 text-xs font-medium text-dark-secondary ring-1 ring-dark-border">{client.industry}</span>}
                    </div>
                  </div>
                  <div className="mt-5 space-y-2">
                    {client.contact_name && <div className="flex items-center gap-2 text-sm text-dark-secondary"><User className="h-4 w-4 text-dark-muted" /><span className="truncate">{client.contact_name}</span></div>}
                    {client.contact_email && <div className="flex items-center gap-2 text-sm text-dark-secondary"><Mail className="h-4 w-4 text-dark-muted" /><span className="truncate">{client.contact_email}</span></div>}
                  </div>
                  <div className="mt-5 flex items-center justify-between border-t border-dark-border pt-4">
                    <span className="text-sm font-medium text-dark-secondary bg-dark-elevated px-2.5 py-1 rounded-md">{client.mission_count} mission{client.mission_count !== 1 ? 's' : ''}</span>
                    <span className="text-sm font-semibold text-ey-yellow opacity-0 group-hover:opacity-100 transition-opacity flex items-center">View <ArrowRight className="ml-1 h-3 w-3" /></span>
                  </div>
                </>
              )}

              {/* List View specific layout */}
              {viewMode === 'list' && (
                <>
                  <div className="flex items-center gap-4 flex-1 min-w-0 pr-20">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-ey-yellow/10 border border-ey-yellow/20 text-ey-yellow shadow-sm">
                      <Building2 className="h-5 w-5" />
                    </div>
                    <div className="flex flex-col min-w-0 pr-4 w-1/4">
                      <h3 className="truncate text-base font-semibold text-white group-hover:text-ey-yellow transition-colors">{client.name}</h3>
                      {client.industry && <span className="truncate text-xs text-dark-secondary">{client.industry}</span>}
                    </div>
                    <div className="hidden md:flex flex-col min-w-0 w-1/4">
                      {client.contact_name && <span className="truncate text-sm text-dark-secondary flex items-center"><User className="mr-1.5 h-3.5 w-3.5 text-dark-muted" />{client.contact_name}</span>}
                    </div>
                    <div className="hidden lg:flex flex-col min-w-0 w-1/4">
                      {client.contact_email && <span className="truncate text-sm text-dark-secondary flex items-center"><Mail className="mr-1.5 h-3.5 w-3.5 text-dark-muted" />{client.contact_email}</span>}
                    </div>
                    <div className="flex items-center justify-end flex-1 pl-4">
                      <span className="text-sm font-medium text-dark-secondary bg-dark-elevated px-2.5 py-1 rounded-md mr-4">{client.mission_count} mission{client.mission_count !== 1 ? 's' : ''}</span>
                    </div>
                  </div>
                </>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
