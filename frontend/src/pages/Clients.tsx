import { useEffect, useState, useMemo } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Plus, Pencil, Trash2, Search, Building2, Mail, User, X } from 'lucide-react';
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

  const fetchClients = async () => {
    try { setClients(await api.getClients()); }
    catch { setError('Failed to load clients'); }
    finally { setLoading(false); }
  };

  useEffect(() => { if (location.pathname === '/clients') fetchClients(); }, [location.pathname]);

  const filteredClients = useMemo(() => {
    if (!search.trim()) return clients;
    const q = search.toLowerCase();
    return clients.filter(c =>
      c.name.toLowerCase().includes(q) ||
      (c.industry ?? '').toLowerCase().includes(q) ||
      (c.contact_name ?? '').toLowerCase().includes(q) ||
      (c.contact_email ?? '').toLowerCase().includes(q),
    );
  }, [clients, search]);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
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

      {/* Search */}
      {clients.length > 0 && (
        <div className="relative">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-dark-muted" />
          <input
            type="text" placeholder="Search clients by name, industry, contact…" value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full rounded-lg border border-dark-border bg-dark-card py-2.5 pl-10 pr-4 text-sm text-white placeholder:text-dark-muted focus:border-ey-yellow/50 focus:outline-none focus:ring-1 focus:ring-ey-yellow/30"
          />
          {search && (
            <button onClick={() => setSearch('')} className="absolute right-3 top-1/2 -translate-y-1/2 text-dark-muted hover:text-white">
              <X className="h-4 w-4" />
            </button>
          )}
        </div>
      )}

      {error && <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">{error}</div>}

      {/* Modal */}
      {showForm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
          <form onSubmit={handleSubmit} className="w-full max-w-lg rounded-xl border border-dark-border bg-dark-elevated p-6 shadow-2xl space-y-5">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-semibold text-white">{editingId ? 'Edit Client' : 'New Client'}</h3>
              <button type="button" onClick={handleCancel} className="rounded-md p-1 text-dark-muted hover:bg-dark-overlay hover:text-white"><X className="h-5 w-5" /></button>
            </div>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="sm:col-span-2">
                <label className="mb-1 block text-sm font-medium text-dark-secondary">Name *</label>
                <input name="name" value={form.name} onChange={handleChange} required placeholder="e.g. Acme Corporation"
                  className="block w-full rounded-lg border border-dark-border bg-dark-card px-3 py-2 text-sm text-white placeholder:text-dark-muted focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30 focus:outline-none" />
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium text-dark-secondary">Industry</label>
                <input name="industry" value={form.industry} onChange={handleChange} placeholder="e.g. Finance, Healthcare"
                  className="block w-full rounded-lg border border-dark-border bg-dark-card px-3 py-2 text-sm text-white placeholder:text-dark-muted focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30 focus:outline-none" />
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium text-dark-secondary">Contact Name</label>
                <input name="contact_name" value={form.contact_name} onChange={handleChange} placeholder="Primary contact"
                  className="block w-full rounded-lg border border-dark-border bg-dark-card px-3 py-2 text-sm text-white placeholder:text-dark-muted focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30 focus:outline-none" />
              </div>
              <div className="sm:col-span-2">
                <label className="mb-1 block text-sm font-medium text-dark-secondary">Contact Email</label>
                <input name="contact_email" type="email" value={form.contact_email} onChange={handleChange} placeholder="email@company.com"
                  className="block w-full rounded-lg border border-dark-border bg-dark-card px-3 py-2 text-sm text-white placeholder:text-dark-muted focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30 focus:outline-none" />
              </div>
              <div className="sm:col-span-2">
                <label className="mb-1 block text-sm font-medium text-dark-secondary">Notes</label>
                <textarea name="notes" value={form.notes} onChange={handleChange} rows={2} placeholder="Internal notes about this client…"
                  className="block w-full rounded-lg border border-dark-border bg-dark-card px-3 py-2 text-sm text-white placeholder:text-dark-muted focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30 focus:outline-none" />
              </div>
            </div>
            <div className="flex justify-end gap-3 border-t border-dark-border pt-4">
              <button type="button" onClick={handleCancel} className="rounded-lg border border-dark-border bg-dark-card px-4 py-2 text-sm font-medium text-dark-secondary hover:bg-dark-overlay hover:text-white">Cancel</button>
              <button type="submit" className="rounded-lg bg-ey-yellow px-5 py-2 text-sm font-semibold text-black hover:bg-ey-yellow-hover">{editingId ? 'Save Changes' : 'Create Client'}</button>
            </div>
          </form>
        </div>
      )}

      {/* Client Cards */}
      {filteredClients.length === 0 ? (
        <div className="rounded-xl border-2 border-dashed border-dark-border bg-dark-card p-16 text-center">
          <Building2 className="mx-auto h-12 w-12 text-dark-muted" />
          <h3 className="mt-4 text-base font-medium text-white">{search ? 'No matching clients' : 'No clients yet'}</h3>
          <p className="mt-1 text-sm text-dark-secondary">{search ? 'Try a different search term.' : 'Create your first client to get started.'}</p>
          {!search && (
            <button onClick={() => { setShowForm(true); setEditingId(null); setForm(emptyForm); }}
              className="mt-4 inline-flex items-center gap-1.5 rounded-lg bg-ey-yellow px-4 py-2 text-sm font-medium text-black hover:bg-ey-yellow-hover">
              <Plus className="h-4 w-4" /> Add Client
            </button>
          )}
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filteredClients.map((client) => (
            <div key={client.id} className="glow-card group relative rounded-xl border border-dark-border bg-dark-card p-5 transition-all duration-300">
              {/* Actions */}
              <div className="absolute right-3 top-3 flex gap-1 opacity-0 transition-opacity group-hover:opacity-100">
                <button onClick={(e) => { e.stopPropagation(); handleEdit(client); }} className="rounded-md p-1.5 text-dark-muted hover:bg-ey-yellow/10 hover:text-ey-yellow" title="Edit"><Pencil className="h-4 w-4" /></button>
                <button onClick={(e) => { e.stopPropagation(); handleDelete(client.id); }} className="rounded-md p-1.5 text-dark-muted hover:bg-red-500/10 hover:text-red-400" title="Delete"><Trash2 className="h-4 w-4" /></button>
              </div>
              <button onClick={() => navigate(`/clients/${client.id}`)} className="block w-full text-left">
                <div className="flex items-start gap-3">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-ey-yellow/10 text-ey-yellow">
                    <Building2 className="h-5 w-5" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <h3 className="truncate text-sm font-semibold text-white group-hover:text-ey-yellow">{client.name}</h3>
                    {client.industry && <span className="mt-0.5 inline-block rounded-full bg-dark-overlay px-2 py-0.5 text-xs text-dark-secondary">{client.industry}</span>}
                  </div>
                </div>
                <div className="mt-4 space-y-1.5">
                  {client.contact_name && <div className="flex items-center gap-2 text-xs text-dark-secondary"><User className="h-3.5 w-3.5" /><span className="truncate">{client.contact_name}</span></div>}
                  {client.contact_email && <div className="flex items-center gap-2 text-xs text-dark-secondary"><Mail className="h-3.5 w-3.5" /><span className="truncate">{client.contact_email}</span></div>}
                </div>
                <div className="mt-4 flex items-center justify-between border-t border-dark-border pt-3">
                  <span className="text-xs text-dark-muted">{client.mission_count} mission{client.mission_count !== 1 ? 's' : ''}</span>
                  <span className="text-xs font-medium text-ey-yellow opacity-0 transition-opacity group-hover:opacity-100">View details →</span>
                </div>
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
