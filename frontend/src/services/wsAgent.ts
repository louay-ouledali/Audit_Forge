/**
 * WebSocket clients for AuditForge Connect.
 * - AgentWSClient: auditor-side session monitor (/ws/session/{id}/monitor)
 * - PortalWSClient: target-side portal monitor (/ws/portal/{code}/monitor)
 */

export type PortalInitAgent = {
  id: number;
  status: string;
  hostname: string | null;
  os_type: string | null;
  os_version: string | null;
  ip_address: string | null;
  system_info: Record<string, unknown> | null;
};

export type PortalInitScan = {
  compliance_percentage: number;
  passed: number;
  failed: number;
  errors: number;
  benchmark_name: string;
};

export type AgentEvent =
  | { type: 'agent_connected'; payload: { agent_id: number; hostname: string; os_type: string; ip_address: string } }
  | { type: 'agent_disconnected'; payload: { agent_id: number; reason?: string } }
  | { type: 'scan_progress'; payload: { agent_id: number; scan_id: number; completed: number; total: number; current_rule?: string } }
  | { type: 'scan_complete'; payload: { agent_id: number; scan_id: number; pass: number; fail: number; error: number; compliance_percentage?: number; total_rules_checked?: number; benchmark_name?: string } }
  | { type: 'agent_system_info'; payload: { agent_id: number; hostname: string; os: string; os_version: string; ip_addresses: string[]; open_ports: number[] } }
  | { type: 'portal_init'; payload: { agents: PortalInitAgent[]; last_scan: PortalInitScan | null } };

type EventCallback = (event: AgentEvent) => void;
type StatusCallback = (status: 'connecting' | 'connected' | 'disconnected' | 'error') => void;

/** Shared base logic for reconnecting WebSocket clients. */
abstract class BaseWSClient {
  protected ws: WebSocket | null = null;
  protected callbacks: EventCallback[] = [];
  protected statusCallbacks: StatusCallback[] = [];
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private maxReconnects = 5;
  private reconnectAttempts = 0;
  private disposed = false;

  protected abstract buildUrl(): string;

  connect(): void {
    if (this.disposed) return;
    this.setStatus('connecting');

    const url = this.buildUrl();

    try {
      this.ws = new WebSocket(url);
    } catch {
      this.setStatus('error');
      return;
    }

    this.ws.onopen = () => {
      this.reconnectAttempts = 0;
      this.setStatus('connected');
    };

    this.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data) as AgentEvent;
        this.callbacks.forEach(cb => cb(msg));
      } catch {
        // ignore malformed messages
      }
    };

    this.ws.onclose = () => {
      if (this.disposed) return;
      this.setStatus('disconnected');
      this.scheduleReconnect();
    };

    this.ws.onerror = () => {
      this.setStatus('error');
    };
  }

  private scheduleReconnect(): void {
    if (this.disposed || this.reconnectAttempts >= this.maxReconnects) return;
    this.reconnectAttempts++;
    const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000);
    this.reconnectTimer = setTimeout(() => this.connect(), delay);
  }

  private setStatus(status: 'connecting' | 'connected' | 'disconnected' | 'error'): void {
    this.statusCallbacks.forEach(cb => cb(status));
  }

  onEvent(callback: EventCallback): () => void {
    this.callbacks.push(callback);
    return () => {
      this.callbacks = this.callbacks.filter(cb => cb !== callback);
    };
  }

  onStatus(callback: StatusCallback): () => void {
    this.statusCallbacks.push(callback);
    return () => {
      this.statusCallbacks = this.statusCallbacks.filter(cb => cb !== callback);
    };
  }

  disconnect(): void {
    this.disposed = true;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    if (this.ws) {
      this.ws.onclose = null;
      this.ws.close();
      this.ws = null;
    }
  }
}

/** Auditor-side: connects to /ws/session/{id}/monitor */
export class AgentWSClient extends BaseWSClient {
  private sessionId: number;

  constructor(sessionId: number) {
    super();
    this.sessionId = sessionId;
  }

  protected buildUrl(): string {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${protocol}//${window.location.host}/ws/session/${this.sessionId}/monitor`;
  }
}

/** Target portal: connects to /ws/portal/{code}/monitor */
export class PortalWSClient extends BaseWSClient {
  private enrollmentCode: string;

  constructor(enrollmentCode: string) {
    super();
    this.enrollmentCode = enrollmentCode;
  }

  protected buildUrl(): string {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${protocol}//${window.location.host}/ws/portal/${this.enrollmentCode}/monitor`;
  }
}
