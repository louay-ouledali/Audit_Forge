import { useState, useEffect } from 'react';
import { Plus, Copy, Trash2, Clock, Wifi, Link2, ExternalLink, Loader2, ChevronDown, ChevronUp } from 'lucide-react';
import type { ConnectSession } from '@/types';
import * as api from '@/services/api';
import { useToast } from '@/components/common/Toast';
import ConnectedAgentsPanel from './ConnectedAgentsPanel';
import BrandLockup from '@/components/common/BrandLockup';

interface Props {
  clientId: number;
  missionId?: number;
}

const inputClass = 'block w-full rounded-lg border border-dark-border bg-dark-elevated px-3 py-2 text-sm text-white placeholder-dark-muted focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30 focus:outline-none transition-all';

export default function ConnectSessionManager({ clientId, missionId }: Props) {
  const [sessions, setSessions] = useState<ConnectSession[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const toast = useToast();

  // Form state
  const [expiryHours, setExpiryHours] = useState(24);
  const [maxLifetime, setMaxLifetime] = useState(4);
  const [notes, setNotes] = useState('');

  const loadSessions = async () => {
    try {
      const data = await api.getConnectSessions(clientId, missionId);
      setSessions(data);
    } catch {
      toast.error('Failed to load connect sessions');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadSessions(); }, [clientId, missionId]);

  // Poll for updates every 10 seconds
  useEffect(() => {
    const interval = setInterval(loadSessions, 10000);
    return () => clearInterval(interval);
  }, [clientId, missionId]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreating(true);
    try {
      const session = await api.createConnectSession({
        client_id: clientId,
        mission_id: missionId,
        expires_in_hours: expiryHours,
        max_agent_lifetime_seconds: maxLifetime * 3600,
        notes: notes || undefined,
      });
      setSessions(prev => [session, ...prev]);
      setShowForm(false);
      setNotes('');
      setExpandedId(session.id);
      toast.success('Connect session created');
    } catch {
      toast.error('Failed to create session');
    } finally {
      setCreating(false);
    }
  };

  const handleTerminate = async (sessionId: number) => {
    try {
      await api.terminateConnectSession(sessionId);
      setSessions(prev => prev.map(s => s.id === sessionId ? { ...s, status: 'terminated' as const } : s));
      toast.success('Session terminated');
    } catch {
      toast.error('Failed to terminate session');
    }
  };

  const copyPortalUrl = (code: string) => {
    const url = `${window.location.origin}/connect/${code}`;
    navigator.clipboard.writeText(url);
    toast.success('Portal URL copied to clipboard');
  };

  const statusColor = (status: string) => {
    if (status === 'active') return 'bg-emerald-500/10 text-emerald-400 ring-emerald-500/20';
    if (status === 'expired') return 'bg-amber-500/10 text-amber-400 ring-amber-500/20';
    return 'bg-dark-overlay text-dark-secondary ring-dark-border';
  };

  const formatDate = (iso: string) => {
    try { return new Date(iso).toLocaleString(); } catch { return iso; }
  };

  const activeSessions = sessions.filter(s => s.status === 'active');
  const pastSessions = sessions.filter(s => s.status !== 'active');

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="h-6 w-6 animate-spin text-ey-yellow" />
      </div>
    );
  }

  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-bottom-2 duration-300">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <BrandLockup service="connect" size="lg" />
          <p className="text-sm text-dark-secondary mt-2 max-w-lg">
            Create enrollment sessions for external targets to connect securely to AuditForge
          </p>
        </div>
        <button
          onClick={() => setShowForm(!showForm)}
          className="flex items-center gap-2 rounded-lg bg-ey-yellow px-4 py-2 text-sm font-semibold text-black hover:bg-ey-yellow-hover shadow-lg shadow-ey-yellow/10 transition-all"
        >
          <Plus className="h-4 w-4" />
          New Session
        </button>
      </div>

      {/* Create form */}
      {showForm && (
        <div className="rounded-xl border border-dark-border bg-dark-card p-6 shadow-xl animate-in fade-in zoom-in-95 duration-200">
          <h4 className="mb-4 text-base font-semibold text-white border-b border-dark-border pb-3">New Connect Session</h4>
          <form onSubmit={handleCreate} className="space-y-4">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <label className="mb-1 block text-sm font-medium text-dark-secondary">Session Expiry (hours)</label>
                <input
                  type="number" min={1} max={168} value={expiryHours}
                  onChange={e => setExpiryHours(Number(e.target.value))}
                  className={inputClass}
                />
                <p className="mt-1 text-xs text-dark-muted">How long the enrollment code stays valid</p>
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium text-dark-secondary">Max Agent Lifetime (hours)</label>
                <input
                  type="number" min={1} max={24} value={maxLifetime}
                  onChange={e => setMaxLifetime(Number(e.target.value))}
                  className={inputClass}
                />
                <p className="mt-1 text-xs text-dark-muted">Agent self-terminates after this period</p>
              </div>
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium text-dark-secondary">Notes (optional)</label>
              <input
                value={notes} onChange={e => setNotes(e.target.value)}
                className={inputClass} placeholder="e.g. IT department workstations review"
              />
            </div>
            <div className="flex gap-3 justify-end pt-3 border-t border-dark-border">
              <button type="button" onClick={() => setShowForm(false)}
                className="rounded-lg border border-dark-border bg-dark-card px-4 py-2 text-sm font-medium text-dark-secondary hover:bg-dark-overlay hover:text-white transition-colors">
                Cancel
              </button>
              <button type="submit" disabled={creating}
                className="rounded-lg bg-ey-yellow px-5 py-2 text-sm font-semibold text-black hover:bg-ey-yellow-hover shadow-lg shadow-ey-yellow/10 transition-all disabled:opacity-50">
                {creating ? 'Creating...' : 'Create Session'}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Active sessions */}
      {activeSessions.length > 0 && (
        <div className="space-y-3">
          <h4 className="text-sm font-semibold text-dark-secondary uppercase tracking-wider">Active Sessions</h4>
          {activeSessions.map(session => (
            <SessionCard
              key={session.id}
              session={session}
              expanded={expandedId === session.id}
              onToggle={() => setExpandedId(expandedId === session.id ? null : session.id)}
              onCopyUrl={() => copyPortalUrl(session.enrollment_code)}
              onTerminate={() => handleTerminate(session.id)}
              statusColor={statusColor}
              formatDate={formatDate}
            />
          ))}
        </div>
      )}

      {/* Past sessions */}
      {pastSessions.length > 0 && (
        <div className="space-y-3">
          <h4 className="text-sm font-semibold text-dark-secondary uppercase tracking-wider">Past Sessions</h4>
          {pastSessions.map(session => (
            <SessionCard
              key={session.id}
              session={session}
              expanded={expandedId === session.id}
              onToggle={() => setExpandedId(expandedId === session.id ? null : session.id)}
              onCopyUrl={() => copyPortalUrl(session.enrollment_code)}
              onTerminate={() => handleTerminate(session.id)}
              statusColor={statusColor}
              formatDate={formatDate}
            />
          ))}
        </div>
      )}

      {/* Empty state */}
      {sessions.length === 0 && (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <Link2 className="h-12 w-12 text-dark-muted mb-4" />
          <h4 className="text-lg font-semibold text-white">No Connect Sessions</h4>
          <p className="mt-2 text-sm text-dark-secondary max-w-sm">
            Create a session to generate an enrollment code. Share the portal URL with targets
            so they can connect their devices for review.
          </p>
        </div>
      )}
    </div>
  );
}

function SessionCard({
  session, expanded, onToggle, onCopyUrl, onTerminate, statusColor, formatDate,
}: {
  session: ConnectSession;
  expanded: boolean;
  onToggle: () => void;
  onCopyUrl: () => void;
  onTerminate: () => void;
  statusColor: (s: string) => string;
  formatDate: (s: string) => string;
}) {
  const portalUrl = `${window.location.origin}/connect/${session.enrollment_code}`;
  const isActive = session.status === 'active';

  return (
    <div className="rounded-xl border border-dark-border bg-dark-card overflow-hidden transition-all">
      <div
        className="flex items-center gap-4 p-4 cursor-pointer hover:bg-dark-elevated/30 transition-colors"
        onClick={onToggle}
      >
        {/* Enrollment code */}
        <div className="rounded-lg bg-dark-elevated border border-dark-border px-3 py-2 font-mono text-lg font-bold text-ey-yellow tracking-wider">
          {session.enrollment_code}
        </div>

        {/* Info */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${statusColor(session.status)}`}>
              {session.status}
            </span>
            <span className="text-xs text-dark-muted flex items-center gap-1">
              <Wifi className="h-3 w-3" /> {session.agent_count} agent{session.agent_count !== 1 ? 's' : ''}
            </span>
          </div>
          {session.notes && <p className="mt-0.5 text-sm text-dark-secondary truncate">{session.notes}</p>}
          <p className="text-xs text-dark-muted mt-0.5 flex items-center gap-1">
            <Clock className="h-3 w-3" /> Expires: {formatDate(session.expires_at)}
          </p>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-2" onClick={e => e.stopPropagation()}>
          {isActive && (
            <>
              <button onClick={onCopyUrl} title="Copy portal URL"
                className="rounded-lg border border-dark-border bg-dark-elevated p-2 text-dark-secondary hover:text-ey-yellow hover:border-ey-yellow/30 transition-colors">
                <Copy className="h-4 w-4" />
              </button>
              <a href={portalUrl} target="_blank" rel="noopener noreferrer" title="Open portal"
                className="rounded-lg border border-dark-border bg-dark-elevated p-2 text-dark-secondary hover:text-ey-yellow hover:border-ey-yellow/30 transition-colors">
                <ExternalLink className="h-4 w-4" />
              </a>
              <button onClick={onTerminate} title="Terminate session"
                className="rounded-lg border border-dark-border bg-dark-elevated p-2 text-dark-secondary hover:text-red-400 hover:border-red-400/30 transition-colors">
                <Trash2 className="h-4 w-4" />
              </button>
            </>
          )}
        </div>

        {expanded ? <ChevronUp className="h-4 w-4 text-dark-muted" /> : <ChevronDown className="h-4 w-4 text-dark-muted" />}
      </div>

      {/* Expanded: agents panel */}
      {expanded && (
        <div className="border-t border-dark-border p-4 bg-dark-elevated/20">
          <ConnectedAgentsPanel sessionId={session.id} isActive={isActive} />
        </div>
      )}
    </div>
  );
}
