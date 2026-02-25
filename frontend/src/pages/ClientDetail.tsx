import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, Plus, Pencil, Trash2, X } from 'lucide-react';
import type { Client, Mission } from '@/types';
import * as api from '@/services/api';

const STATUS_STYLES: Record<string, string> = {
  in_progress: 'bg-emerald-500/10 text-emerald-400 ring-emerald-500/20',
  completed: 'bg-sky-500/10 text-sky-400 ring-sky-500/20',
  cancelled: 'bg-dark-overlay text-dark-secondary ring-dark-border',
};
const STATUS_LABELS: Record<string, string> = { in_progress: 'In Progress', completed: 'Completed', cancelled: 'Cancelled' };

interface MissionForm { name: string; description: string; start_date: string; end_date: string; }
const emptyForm: MissionForm = { name: '', description: '', start_date: '', end_date: '' };

export default function ClientDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const clientId = Number(id);
  const [client, setClient] = useState<Client | null>(null);
  const [missions, setMissions] = useState<Mission[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState<MissionForm>(emptyForm);
  const [error, setError] = useState('');

  const fetchData = async () => {
    try {
      const [c, m] = await Promise.all([api.getClient(clientId), api.getMissions(clientId)]);
      setClient(c); setMissions(m);
    } catch { setError('Failed to load client data'); }
    finally { setLoading(false); }
  };

  useEffect(() => { fetchData(); }, [clientId]);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    setForm({ ...form, [e.target.name]: e.target.value });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault(); setError('');
    try {
      const payload = { ...form, client_id: clientId, start_date: form.start_date || null, end_date: form.end_date || null };
      if (editingId) await api.updateMission(editingId, payload);
      else await api.createMission(payload);
      setShowForm(false); setEditingId(null); setForm(emptyForm); await fetchData();
    } catch { setError(editingId ? 'Failed to update mission' : 'Failed to create mission'); }
  };

  const handleEdit = (mission: Mission) => {
    setForm({ name: mission.name, description: mission.description ?? '', start_date: mission.start_date ?? '', end_date: mission.end_date ?? '' });
    setEditingId(mission.id); setShowForm(true);
  };

  const handleDelete = async (missionId: number) => {
    if (!window.confirm('Delete this mission and all associated data?')) return;
    try { await api.deleteMission(missionId); await fetchData(); }
    catch { setError('Failed to delete mission'); }
  };

  const handleCancel = () => { setShowForm(false); setEditingId(null); setForm(emptyForm); setError(''); };

  if (loading) return <div className="flex items-center justify-center py-12 text-dark-secondary">Loading…</div>;
  if (!client) return (
    <div className="py-12 text-center text-dark-secondary">
      Client not found. <button onClick={() => navigate('/clients')} className="text-ey-yellow hover:underline">Go back</button>
    </div>
  );

  return (
    <div className="space-y-6">
      <button onClick={() => navigate('/clients')} className="inline-flex items-center gap-1 text-sm text-dark-secondary hover:text-ey-yellow">
        <ArrowLeft className="h-4 w-4" /> Back to Clients
      </button>

      {/* Client Info */}
      <div className="rounded-xl border border-dark-border bg-dark-card p-6">
        <h2 className="text-xl font-semibold text-white">{client.name}</h2>
        <div className="mt-3 grid grid-cols-1 gap-2 text-sm sm:grid-cols-3">
          <div><span className="font-medium text-dark-secondary">Industry:</span> <span className="text-white">{client.industry ?? '—'}</span></div>
          <div><span className="font-medium text-dark-secondary">Contact:</span> <span className="text-white">{client.contact_name ?? '—'}</span></div>
          <div><span className="font-medium text-dark-secondary">Email:</span> <span className="text-white">{client.contact_email ?? '—'}</span></div>
        </div>
        {client.notes && <p className="mt-3 text-sm text-dark-secondary">{client.notes}</p>}
      </div>

      {/* Missions Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold text-white">Missions</h3>
        <button onClick={() => { setShowForm(true); setEditingId(null); setForm(emptyForm); }}
          className="inline-flex items-center gap-2 rounded-lg bg-ey-yellow px-4 py-2 text-sm font-medium text-black hover:bg-ey-yellow-hover">
          <Plus className="h-4 w-4" /> New Mission
        </button>
      </div>

      {error && <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">{error}</div>}

      {/* Form Modal */}
      {showForm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
          <form onSubmit={handleSubmit} className="w-full max-w-lg rounded-xl border border-dark-border bg-dark-elevated p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-medium text-white">{editingId ? 'Edit Mission' : 'New Mission'}</h3>
              <button type="button" onClick={handleCancel} className="rounded-md p-1 text-dark-muted hover:bg-dark-overlay hover:text-white"><X className="h-5 w-5" /></button>
            </div>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="sm:col-span-2">
                <label className="block text-sm font-medium text-dark-secondary">Name *</label>
                <input name="name" value={form.name} onChange={handleChange} required
                  className="mt-1 block w-full rounded-lg border border-dark-border bg-dark-card px-3 py-2 text-sm text-white focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30 focus:outline-none" />
              </div>
              <div className="sm:col-span-2">
                <label className="block text-sm font-medium text-dark-secondary">Description</label>
                <textarea name="description" value={form.description} onChange={handleChange} rows={2}
                  className="mt-1 block w-full rounded-lg border border-dark-border bg-dark-card px-3 py-2 text-sm text-white focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30 focus:outline-none" />
              </div>
              <div>
                <label className="block text-sm font-medium text-dark-secondary">Start Date</label>
                <input name="start_date" type="date" value={form.start_date} onChange={handleChange}
                  className="mt-1 block w-full rounded-lg border border-dark-border bg-dark-card px-3 py-2 text-sm text-white focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30 focus:outline-none [color-scheme:dark]" />
              </div>
              <div>
                <label className="block text-sm font-medium text-dark-secondary">End Date</label>
                <input name="end_date" type="date" value={form.end_date} onChange={handleChange}
                  className="mt-1 block w-full rounded-lg border border-dark-border bg-dark-card px-3 py-2 text-sm text-white focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30 focus:outline-none [color-scheme:dark]" />
              </div>
            </div>
            <div className="flex justify-end gap-3 border-t border-dark-border pt-4">
              <button type="button" onClick={handleCancel} className="rounded-lg border border-dark-border bg-dark-card px-4 py-2 text-sm font-medium text-dark-secondary hover:bg-dark-overlay hover:text-white">Cancel</button>
              <button type="submit" className="rounded-lg bg-ey-yellow px-4 py-2 text-sm font-medium text-black hover:bg-ey-yellow-hover">{editingId ? 'Update' : 'Create'}</button>
            </div>
          </form>
        </div>
      )}

      {/* Missions Table */}
      {missions.length === 0 ? (
        <div className="rounded-xl border-2 border-dashed border-dark-border bg-dark-card p-12 text-center">
          <p className="text-dark-secondary">No missions yet. Create one to get started.</p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-dark-border bg-dark-card">
          <table className="min-w-full divide-y divide-dark-border">
            <thead className="bg-dark-elevated">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-dark-muted">Name</th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-dark-muted">Status</th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-dark-muted">Dates</th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-dark-muted">Targets</th>
                <th className="px-6 py-3 text-right text-xs font-medium uppercase tracking-wider text-dark-muted">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-dark-border">
              {missions.map((m) => (
                <tr key={m.id} className="hover:bg-dark-elevated/50 transition-colors">
                  <td className="whitespace-nowrap px-6 py-4 text-sm font-medium text-white">{m.name}</td>
                  <td className="whitespace-nowrap px-6 py-4">
                    <span className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${STATUS_STYLES[m.status] ?? STATUS_STYLES.in_progress}`}>
                      {STATUS_LABELS[m.status] ?? m.status}
                    </span>
                  </td>
                  <td className="whitespace-nowrap px-6 py-4 text-sm text-dark-secondary">
                    {m.start_date || m.end_date ? `${m.start_date ?? '—'} → ${m.end_date ?? '—'}` : '—'}
                  </td>
                  <td className="whitespace-nowrap px-6 py-4 text-sm text-dark-secondary">{m.target_count}</td>
                  <td className="whitespace-nowrap px-6 py-4 text-right">
                    <div className="flex justify-end gap-1">
                      <button onClick={() => handleEdit(m)} className="rounded p-1.5 text-dark-muted hover:bg-ey-yellow/10 hover:text-ey-yellow"><Pencil className="h-4 w-4" /></button>
                      <button onClick={() => handleDelete(m.id)} className="rounded p-1.5 text-dark-muted hover:bg-red-500/10 hover:text-red-400"><Trash2 className="h-4 w-4" /></button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
