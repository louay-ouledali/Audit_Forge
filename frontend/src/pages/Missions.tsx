import { useEffect, useState, useMemo } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Plus, Pencil, Trash2, Search, Crosshair, Calendar, X, Building2 } from 'lucide-react';
import type { Client, Mission } from '@/types';
import * as api from '@/services/api';

interface MissionForm {
  client_id: number | '';
  name: string;
  description: string;
  start_date: string;
  end_date: string;
  status: string;
}

const emptyForm: MissionForm = {
  client_id: '',
  name: '',
  description: '',
  start_date: '',
  end_date: '',
  status: 'in_progress',
};

const STATUS_STYLES: Record<string, string> = {
  in_progress: 'bg-emerald-50 text-emerald-700 ring-emerald-600/20',
  completed: 'bg-blue-50 text-blue-700 ring-blue-600/20',
  cancelled: 'bg-gray-50 text-gray-600 ring-gray-500/20',
};

const STATUS_LABELS: Record<string, string> = {
  in_progress: 'In Progress',
  completed: 'Completed',
  cancelled: 'Cancelled',
};

export default function Missions() {
  const navigate = useNavigate();
  const location = useLocation();
  const [missions, setMissions] = useState<Mission[]>([]);
  const [clients, setClients] = useState<Client[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState<MissionForm>(emptyForm);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('');

  const fetchData = async () => {
    try {
      const [m, c] = await Promise.all([api.getAllMissions(), api.getClients()]);
      setMissions(m);
      setClients(c);
    } catch {
      setError('Failed to load missions');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (location.pathname === '/missions') fetchData();
  }, [location.pathname]);

  const filteredMissions = useMemo(() => {
    let result = missions;
    if (statusFilter) {
      result = result.filter((m) => m.status === statusFilter);
    }
    if (search.trim()) {
      const q = search.toLowerCase();
      result = result.filter(
        (m) =>
          m.name.toLowerCase().includes(q) ||
          (m.client_name ?? '').toLowerCase().includes(q) ||
          (m.description ?? '').toLowerCase().includes(q),
      );
    }
    return result;
  }, [missions, search, statusFilter]);

  const statusCounts = useMemo(() => {
    const counts: Record<string, number> = { in_progress: 0, completed: 0, cancelled: 0 };
    for (const m of missions) {
      counts[m.status] = (counts[m.status] || 0) + 1;
    }
    return counts;
  }, [missions]);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => {
    setForm({ ...form, [e.target.name]: e.target.value });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    if (!form.client_id) {
      setError('Please select a client');
      return;
    }
    try {
      const payload = {
        ...form,
        client_id: Number(form.client_id),
        start_date: form.start_date || null,
        end_date: form.end_date || null,
      };
      if (editingId) {
        await api.updateMission(editingId, payload);
      } else {
        await api.createMission(payload);
      }
      setShowForm(false);
      setEditingId(null);
      setForm(emptyForm);
      await fetchData();
    } catch {
      setError(editingId ? 'Failed to update mission' : 'Failed to create mission');
    }
  };

  const handleEdit = (mission: Mission) => {
    setForm({
      client_id: mission.client_id,
      name: mission.name,
      description: mission.description ?? '',
      start_date: mission.start_date ?? '',
      end_date: mission.end_date ?? '',
      status: mission.status,
    });
    setEditingId(mission.id);
    setShowForm(true);
  };

  const handleDelete = async (id: number) => {
    if (!window.confirm('Are you sure you want to delete this mission?')) return;
    try {
      await api.deleteMission(id);
      await fetchData();
    } catch {
      setError('Failed to delete mission');
    }
  };

  const handleCancel = () => {
    setShowForm(false);
    setEditingId(null);
    setForm(emptyForm);
    setError('');
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-600 border-t-transparent" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">Missions</h2>
          <p className="mt-1 text-sm text-gray-500">
            {missions.length} mission{missions.length !== 1 ? 's' : ''} total
          </p>
        </div>
        <button
          onClick={() => { setShowForm(true); setEditingId(null); setForm(emptyForm); }}
          className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
        >
          <Plus className="h-4 w-4" />
          New Mission
        </button>
      </div>

      {/* Status filter chips */}
      {missions.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={() => setStatusFilter('')}
            className={`rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${
              !statusFilter
                ? 'bg-gray-900 text-white'
                : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
            }`}
          >
            All ({missions.length})
          </button>
          {Object.entries(STATUS_LABELS).map(([key, label]) => (
            <button
              key={key}
              onClick={() => setStatusFilter(statusFilter === key ? '' : key)}
              className={`rounded-full px-3 py-1.5 text-xs font-medium ring-1 ring-inset transition-colors ${
                statusFilter === key
                  ? STATUS_STYLES[key]
                  : 'bg-white text-gray-600 ring-gray-200 hover:bg-gray-50'
              }`}
            >
              {label} ({statusCounts[key] || 0})
            </button>
          ))}
        </div>
      )}

      {/* Search */}
      {missions.length > 0 && (
        <div className="relative">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            placeholder="Search missions by name, client, description…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full rounded-lg border border-gray-300 bg-white py-2.5 pl-10 pr-4 text-sm placeholder:text-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
          {search && (
            <button onClick={() => setSearch('')} className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">
              <X className="h-4 w-4" />
            </button>
          )}
        </div>
      )}

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>
      )}

      {/* Create/Edit Form — Modal overlay */}
      {showForm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <form
            onSubmit={handleSubmit}
            className="w-full max-w-lg rounded-xl border border-gray-200 bg-white p-6 shadow-2xl space-y-5"
          >
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-semibold text-gray-900">
                {editingId ? 'Edit Mission' : 'New Mission'}
              </h3>
              <button type="button" onClick={handleCancel} className="rounded-md p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600">
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="sm:col-span-2">
                <label className="mb-1 block text-sm font-medium text-gray-700">Client *</label>
                <select
                  name="client_id"
                  value={form.client_id}
                  onChange={handleChange}
                  required
                  className="block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 focus:outline-none"
                >
                  <option value="">Select a client…</option>
                  {clients.map((c) => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
                </select>
              </div>
              <div className="sm:col-span-2">
                <label className="mb-1 block text-sm font-medium text-gray-700">Name *</label>
                <input
                  name="name"
                  value={form.name}
                  onChange={handleChange}
                  required
                  placeholder="e.g. Q1 2026 Security Audit"
                  className="block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 focus:outline-none"
                />
              </div>
              <div className="sm:col-span-2">
                <label className="mb-1 block text-sm font-medium text-gray-700">Description</label>
                <textarea
                  name="description"
                  value={form.description}
                  onChange={handleChange}
                  rows={2}
                  placeholder="Brief description of the mission scope…"
                  className="block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 focus:outline-none"
                />
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-700">Start Date</label>
                <input
                  name="start_date"
                  type="date"
                  value={form.start_date}
                  onChange={handleChange}
                  className="block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 focus:outline-none"
                />
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-700">End Date</label>
                <input
                  name="end_date"
                  type="date"
                  value={form.end_date}
                  onChange={handleChange}
                  className="block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 focus:outline-none"
                />
              </div>
              {editingId && (
                <div className="sm:col-span-2">
                  <label className="mb-1 block text-sm font-medium text-gray-700">Status</label>
                  <select
                    name="status"
                    value={form.status}
                    onChange={handleChange}
                    className="block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 focus:outline-none"
                  >
                    <option value="in_progress">In Progress</option>
                    <option value="completed">Completed</option>
                    <option value="cancelled">Cancelled</option>
                  </select>
                </div>
              )}
            </div>

            <div className="flex justify-end gap-3 border-t border-gray-100 pt-4">
              <button
                type="button"
                onClick={handleCancel}
                className="rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                type="submit"
                className="rounded-lg bg-blue-600 px-5 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700"
              >
                {editingId ? 'Save Changes' : 'Create Mission'}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Mission Cards */}
      {filteredMissions.length === 0 ? (
        <div className="rounded-xl border-2 border-dashed border-gray-200 bg-white p-16 text-center">
          <Crosshair className="mx-auto h-12 w-12 text-gray-300" />
          <h3 className="mt-4 text-base font-medium text-gray-900">
            {search || statusFilter ? 'No matching missions' : 'No missions yet'}
          </h3>
          <p className="mt-1 text-sm text-gray-500">
            {search || statusFilter
              ? 'Try adjusting your filters.'
              : 'Create your first mission to get started.'}
          </p>
          {!search && !statusFilter && (
            <button
              onClick={() => { setShowForm(true); setEditingId(null); setForm(emptyForm); }}
              className="mt-4 inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
            >
              <Plus className="h-4 w-4" />
              Add Mission
            </button>
          )}
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {filteredMissions.map((mission) => (
            <div
              key={mission.id}
              className="group relative rounded-xl border border-gray-200 bg-white p-5 shadow-sm transition-all hover:shadow-md hover:border-blue-200"
            >
              {/* Actions */}
              <div className="absolute right-3 top-3 flex gap-1 opacity-0 transition-opacity group-hover:opacity-100">
                <button
                  onClick={(e) => { e.stopPropagation(); handleEdit(mission); }}
                  className="rounded-md p-1.5 text-gray-400 hover:bg-blue-50 hover:text-blue-600"
                  title="Edit"
                >
                  <Pencil className="h-4 w-4" />
                </button>
                <button
                  onClick={(e) => { e.stopPropagation(); handleDelete(mission.id); }}
                  className="rounded-md p-1.5 text-gray-400 hover:bg-red-50 hover:text-red-600"
                  title="Delete"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>

              {/* Card body */}
              <div className="flex items-start gap-4">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-green-50 text-green-600">
                  <Crosshair className="h-5 w-5" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <h3 className="truncate text-sm font-semibold text-gray-900">
                      {mission.name}
                    </h3>
                    <span
                      className={`inline-flex shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${
                        STATUS_STYLES[mission.status] ?? STATUS_STYLES.in_progress
                      }`}
                    >
                      {STATUS_LABELS[mission.status] ?? mission.status}
                    </span>
                  </div>

                  <button
                    onClick={() => navigate(`/clients/${mission.client_id}`)}
                    className="mt-1 flex items-center gap-1 text-xs text-blue-600 hover:text-blue-800"
                  >
                    <Building2 className="h-3 w-3" />
                    {mission.client_name ?? `Client #${mission.client_id}`}
                  </button>

                  {mission.description && (
                    <p className="mt-2 line-clamp-2 text-xs text-gray-500">{mission.description}</p>
                  )}

                  <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-gray-100 pt-3">
                    {(mission.start_date || mission.end_date) && (
                      <div className="flex items-center gap-1 text-xs text-gray-500">
                        <Calendar className="h-3 w-3" />
                        {mission.start_date ?? '—'} → {mission.end_date ?? '—'}
                      </div>
                    )}
                    <span className="text-xs text-gray-500">
                      {mission.target_count} target{mission.target_count !== 1 ? 's' : ''}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
