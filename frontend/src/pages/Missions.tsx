import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Plus, Pencil, Trash2 } from 'lucide-react';
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

export default function Missions() {
  const navigate = useNavigate();
  const [missions, setMissions] = useState<Mission[]>([]);
  const [clients, setClients] = useState<Client[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState<MissionForm>(emptyForm);
  const [error, setError] = useState('');

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
    fetchData();
  }, []);

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
    return <div className="flex items-center justify-center py-12 text-gray-500">Loading…</div>;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold text-gray-900">All Missions</h2>
        <button
          onClick={() => { setShowForm(true); setEditingId(null); setForm(emptyForm); }}
          className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
        >
          <Plus className="h-4 w-4" />
          New Mission
        </button>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {showForm && (
        <form onSubmit={handleSubmit} className="rounded-lg border border-gray-200 bg-white p-6 space-y-4">
          <h3 className="text-lg font-medium text-gray-900">
            {editingId ? 'Edit Mission' : 'New Mission'}
          </h3>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="sm:col-span-2">
              <label className="block text-sm font-medium text-gray-700">Client *</label>
              <select
                name="client_id"
                value={form.client_id}
                onChange={handleChange}
                required
                className="mt-1 block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 focus:outline-none"
              >
                <option value="">Select a client…</option>
                {clients.map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
            </div>
            <div className="sm:col-span-2">
              <label className="block text-sm font-medium text-gray-700">Name *</label>
              <input
                name="name"
                value={form.name}
                onChange={handleChange}
                required
                className="mt-1 block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 focus:outline-none"
              />
            </div>
            <div className="sm:col-span-2">
              <label className="block text-sm font-medium text-gray-700">Description</label>
              <textarea
                name="description"
                value={form.description}
                onChange={handleChange}
                rows={2}
                className="mt-1 block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">Start Date</label>
              <input
                name="start_date"
                type="date"
                value={form.start_date}
                onChange={handleChange}
                className="mt-1 block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">End Date</label>
              <input
                name="end_date"
                type="date"
                value={form.end_date}
                onChange={handleChange}
                className="mt-1 block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 focus:outline-none"
              />
            </div>
            {editingId && (
              <div>
                <label className="block text-sm font-medium text-gray-700">Status</label>
                <select
                  name="status"
                  value={form.status}
                  onChange={handleChange}
                  className="mt-1 block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 focus:outline-none"
                >
                  <option value="in_progress">In Progress</option>
                  <option value="completed">Completed</option>
                  <option value="cancelled">Cancelled</option>
                </select>
              </div>
            )}
          </div>
          <div className="flex gap-3">
            <button
              type="submit"
              className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
            >
              {editingId ? 'Update' : 'Create'}
            </button>
            <button
              type="button"
              onClick={handleCancel}
              className="rounded-lg bg-gray-200 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-300"
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      {missions.length === 0 ? (
        <div className="rounded-lg border border-gray-200 bg-white p-12 text-center text-gray-500">
          No missions yet. Create your first mission to get started.
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Name</th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Client</th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Status</th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Dates</th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Targets</th>
                <th className="px-6 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {missions.map((mission, idx) => (
                <tr key={mission.id} className={idx % 2 === 1 ? 'bg-gray-50' : 'bg-white'}>
                  <td className="whitespace-nowrap px-6 py-4 font-medium text-gray-900">
                    {mission.name}
                  </td>
                  <td className="whitespace-nowrap px-6 py-4 text-sm">
                    <button
                      onClick={() => navigate(`/clients/${mission.client_id}`)}
                      className="text-blue-600 hover:text-blue-800 hover:underline"
                    >
                      {mission.client_name ?? `Client #${mission.client_id}`}
                    </button>
                  </td>
                  <td className="whitespace-nowrap px-6 py-4">
                    <span className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ${
                      mission.status === 'completed'
                        ? 'bg-blue-100 text-blue-800'
                        : mission.status === 'cancelled'
                        ? 'bg-gray-100 text-gray-800'
                        : 'bg-green-100 text-green-800'
                    }`}>
                      {mission.status}
                    </span>
                  </td>
                  <td className="whitespace-nowrap px-6 py-4 text-sm text-gray-500">
                    {mission.start_date ?? '—'} → {mission.end_date ?? '—'}
                  </td>
                  <td className="whitespace-nowrap px-6 py-4 text-sm text-gray-500">
                    {mission.target_count}
                  </td>
                  <td className="whitespace-nowrap px-6 py-4 text-right">
                    <button
                      onClick={() => handleEdit(mission)}
                      className="mr-2 inline-flex items-center rounded-md p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
                      title="Edit"
                      aria-label={`Edit mission ${mission.name}`}
                    >
                      <Pencil className="h-4 w-4" />
                    </button>
                    <button
                      onClick={() => handleDelete(mission.id)}
                      className="inline-flex items-center rounded-md p-1.5 text-gray-400 hover:bg-red-50 hover:text-red-600"
                      title="Delete"
                      aria-label={`Delete mission ${mission.name}`}
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
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
