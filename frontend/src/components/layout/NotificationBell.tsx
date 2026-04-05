import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Bell, Check, CheckCheck, X, ShieldAlert, TrendingDown, CheckCircle, Info, AlertTriangle, FileText } from 'lucide-react';
import { cn } from '@/lib/utils';
import { formatTimeAgo } from '@/utils/time';
import * as api from '@/services/api';
import type { AppNotification } from '@/types';

const TYPE_STYLES: Record<string, { icon: typeof Bell; color: string }> = {
  critical: { icon: ShieldAlert, color: 'text-red-400' },
  warning: { icon: TrendingDown, color: 'text-amber-400' },
  success: { icon: CheckCircle, color: 'text-emerald-400' },
  info: { icon: Info, color: 'text-sky-400' },
};

export default function NotificationBell() {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [notifications, setNotifications] = useState<AppNotification[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);

  const fetchUnreadCount = useCallback(async () => {
    try {
      const { count } = await api.getUnreadNotificationCount();
      setUnreadCount(count);
    } catch { /* silent */ }
  }, []);

  const fetchNotifications = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.getNotifications(0, 30);
      setNotifications(Array.isArray(data) ? data : data.data ?? []);
    } catch { /* silent */ }
    setLoading(false);
  }, []);

  // Poll unread count every 30 seconds
  useEffect(() => {
    fetchUnreadCount();
    const interval = setInterval(fetchUnreadCount, 30000);
    return () => clearInterval(interval);
  }, [fetchUnreadCount]);

  // Fetch full list when panel opens
  useEffect(() => {
    if (open) fetchNotifications();
  }, [open, fetchNotifications]);

  // Close on click outside
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const handleMarkRead = async (id: number) => {
    try {
      await api.markNotificationRead(id);
      setNotifications(prev => prev.map(n => n.id === id ? { ...n, is_read: true } : n));
      setUnreadCount(prev => Math.max(0, prev - 1));
    } catch (err) {
      console.error('Failed to mark notification as read:', err);
    }
  };

  const handleMarkAllRead = async () => {
    try {
      await api.markAllNotificationsRead();
      setNotifications(prev => prev.map(n => ({ ...n, is_read: true })));
      setUnreadCount(0);
    } catch (err) {
      console.error('Failed to mark all notifications as read:', err);
    }
  };

  const handleDismiss = async (id: number, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      const notif = notifications.find(n => n.id === id);
      await api.dismissNotification(id);
      setNotifications(prev => prev.filter(n => n.id !== id));
      // Only decrement unread count if the dismissed notification was actually unread
      if (notif && !notif.is_read) {
        setUnreadCount(prev => Math.max(0, prev - 1));
      }
    } catch (err) {
      console.error('Failed to dismiss notification:', err);
    }
  };

  const handleClick = (n: AppNotification) => {
    if (!n.is_read) handleMarkRead(n.id);
    if (n.link) {
      navigate(n.link);
      setOpen(false);
    }
  };

  return (
    <div className="relative" ref={panelRef}>
      {/* Bell button */}
      <button
        onClick={() => setOpen(!open)}
        className="relative flex items-center justify-center rounded-full p-2 text-dark-muted transition-colors hover:text-ey-yellow hover:bg-ey-yellow/10"
        title="Notifications"
      >
        <Bell className="h-4 w-4" />
        {unreadCount > 0 && (
          <span className="absolute -top-0.5 -right-0.5 flex h-4 min-w-[16px] items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-bold text-white shadow-lg">
            {unreadCount > 99 ? '99+' : unreadCount}
          </span>
        )}
      </button>

      {/* Dropdown panel */}
      {open && (
        <div className="absolute right-0 top-full mt-2 w-96 overflow-hidden rounded-xl border border-dark-border bg-dark-surface shadow-2xl z-[100]">
          {/* Header */}
          <div className="flex items-center justify-between border-b border-dark-border px-4 py-3">
            <h3 className="text-sm font-semibold text-white">Notifications</h3>
            {unreadCount > 0 && (
              <button
                onClick={handleMarkAllRead}
                className="flex items-center gap-1 text-xs text-dark-muted hover:text-ey-yellow transition-colors"
              >
                <CheckCheck className="h-3 w-3" />
                Mark all read
              </button>
            )}
          </div>

          {/* List */}
          <div className="max-h-96 overflow-y-auto">
            {loading && notifications.length === 0 ? (
              <div className="p-8 text-center text-sm text-dark-muted">Loading...</div>
            ) : notifications.length === 0 ? (
              <div className="p-8 text-center">
                <Bell className="mx-auto h-8 w-8 text-dark-muted/50 mb-2" />
                <p className="text-sm text-dark-muted">No notifications</p>
              </div>
            ) : (
              notifications.map(n => {
                const style = TYPE_STYLES[n.type] ?? TYPE_STYLES.info;
                const Icon = style.icon;
                return (
                  <div
                    key={n.id}
                    onClick={() => handleClick(n)}
                    className={cn(
                      'group flex items-start gap-3 px-4 py-3 transition-colors cursor-pointer border-b border-dark-border/50 last:border-0',
                      n.is_read ? 'opacity-60 hover:opacity-80' : 'bg-ey-yellow/5 hover:bg-ey-yellow/10',
                    )}
                  >
                    <div className={cn('mt-0.5 flex-shrink-0', style.color)}>
                      <Icon className="h-4 w-4" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className={cn('text-sm leading-tight', n.is_read ? 'text-dark-secondary' : 'text-white font-medium')}>
                        {n.title}
                      </p>
                      {n.body && (
                        <p className="mt-0.5 text-xs text-dark-muted line-clamp-2">
                          {n.body.replace(/\n\n📄 Report:.*$/, '')}
                        </p>
                      )}
                      {n.body && /\/api\/schedules\/reports\//.test(n.body) && (() => {
                        const match = n.body!.match(/(\/api\/schedules\/reports\/[^\s]+)/);
                        return match ? (
                          <a
                            href={match[1]}
                            target="_blank"
                            rel="noopener noreferrer"
                            onClick={(e) => e.stopPropagation()}
                            className="mt-1 inline-flex items-center gap-1 text-[11px] text-ey-yellow hover:text-ey-yellow/80 transition-colors"
                          >
                            <FileText className="h-3 w-3" />
                            View Report
                          </a>
                        ) : null;
                      })()}
                      <p className="mt-1 text-[10px] text-dark-muted">{n.created_at ? formatTimeAgo(n.created_at) : ''}</p>
                    </div>
                    <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                      {!n.is_read && (
                        <button
                          onClick={(e) => { e.stopPropagation(); handleMarkRead(n.id); }}
                          className="rounded p-1 text-dark-muted hover:text-ey-yellow hover:bg-dark-elevated"
                          title="Mark as read"
                        >
                          <Check className="h-3 w-3" />
                        </button>
                      )}
                      <button
                        onClick={(e) => handleDismiss(n.id, e)}
                        className="rounded p-1 text-dark-muted hover:text-red-400 hover:bg-dark-elevated"
                        title="Dismiss"
                      >
                        <X className="h-3 w-3" />
                      </button>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}
