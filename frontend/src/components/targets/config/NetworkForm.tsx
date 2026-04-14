import type { Benchmark } from '@/types';
import type { TargetFormState } from './useTargetForm';
import { FormSection, HintBox, WarningBox, CodeBlock, fieldInput, fieldSelect, fieldLabel } from './FormParts';

interface Props {
  form: TargetFormState;
  setField: <K extends keyof TargetFormState>(key: K, value: TargetFormState[K]) => void;
  setConnectionMethod: (m: string) => void;
  benchmarks: Benchmark[];
}

const DEVICE_TYPES = [
  { value: 'cisco_ios', label: 'Cisco IOS' },
  { value: 'cisco_asa', label: 'Cisco ASA' },
  { value: 'cisco_nxos', label: 'Cisco NX-OS' },
  { value: 'juniper', label: 'Juniper' },
  { value: 'juniper_junos', label: 'Juniper JunOS' },
  { value: 'fortinet', label: 'Fortinet FortiOS' },
  { value: 'paloalto_panos', label: 'Palo Alto PAN-OS' },
  { value: 'arista_eos', label: 'Arista EOS' },
  { value: 'hp_procurve', label: 'HP ProCurve' },
];

export default function NetworkForm({ form, setField, setConnectionMethod: _setCM, benchmarks }: Props) {
  const netBenchmarks = benchmarks.filter(
    b => b.platform_family?.toLowerCase() === 'network' ||
         b.platform?.toLowerCase().includes('cisco') ||
         b.platform?.toLowerCase().includes('juniper') ||
         b.platform?.toLowerCase().includes('palo') ||
         b.platform?.toLowerCase().includes('fortinet'),
  );

  return (
    <div className="space-y-3">
      {/* ── Connection ─────────────────────────────────────── */}
      <FormSection title="Connection">
        <div>
          <label className={fieldLabel}>Protocol</label>
          <select value="ssh" disabled className={`${fieldSelect} opacity-60`}>
            <option value="ssh">SSH (Netmiko)</option>
          </select>
        </div>
        <div className="grid grid-cols-3 gap-2">
          <div className="col-span-2">
            <label className={fieldLabel}>IP Address</label>
            <input
              value={form.ip_address}
              onChange={e => setField('ip_address', e.target.value)}
              placeholder="10.0.0.1"
              className={fieldInput}
            />
          </div>
          <div>
            <label className={fieldLabel}>Port</label>
            <input
              value={form.port}
              onChange={e => setField('port', e.target.value)}
              placeholder="22"
              className={fieldInput}
            />
          </div>
        </div>
        <div>
          <label className={fieldLabel}>Device Type <span className="text-red-400">*</span></label>
          <select
            value={form.device_type}
            onChange={e => {
              setField('device_type', e.target.value);
              setField('platform_subtype', e.target.value);
            }}
            className={fieldSelect}
          >
            <option value="">Select device type…</option>
            {DEVICE_TYPES.map(dt => (
              <option key={dt.value} value={dt.value}>{dt.label}</option>
            ))}
          </select>
        </div>
      </FormSection>

      {/* ── Credentials ────────────────────────────────────── */}
      <FormSection title="Credentials">
        <div>
          <label className={fieldLabel}>Username</label>
          <input
            value={form.ssh_username}
            onChange={e => setField('ssh_username', e.target.value)}
            placeholder="admin"
            className={fieldInput}
          />
        </div>
        <div>
          <label className={fieldLabel}>Password</label>
          <input
            type="password"
            value={form.ssh_password}
            onChange={e => setField('ssh_password', e.target.value)}
            placeholder="••••••••"
            className={fieldInput}
          />
        </div>
        <div>
          <label className={fieldLabel}>Enable Secret <span className="text-dark-muted">(optional)</span></label>
          <input
            type="password"
            value={form.enable_password}
            onChange={e => setField('enable_password', e.target.value)}
            placeholder="••••••••"
            className={fieldInput}
          />
        </div>
        <HintBox>
          Some devices require an <strong>enable password</strong> to enter privileged exec mode (Cisco IOS, HP ProCurve).
          Palo Alto and Juniper typically don't need one.
        </HintBox>
        {(form.device_type === 'paloalto_panos' || form.device_type === 'fortinet') && (
          <div className="space-y-1.5">
            <label className="flex items-center gap-3 cursor-pointer select-none">
              <div
                onClick={() => setField('verify_tls', !form.verify_tls)}
                className={`relative h-5 w-9 rounded-full transition-colors ${form.verify_tls ? 'bg-emerald-500' : 'bg-dark-border'}`}
              >
                <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform ${form.verify_tls ? 'translate-x-4' : 'translate-x-0.5'}`} />
              </div>
              <span className="text-xs text-dark-secondary">Verify HTTPS certificate (REST API)</span>
            </label>
            {!form.verify_tls && (
              <p className="text-[11px] text-amber-400/80">TLS verification disabled — accepts self-signed certificates on the management interface.</p>
            )}
          </div>
        )}
      </FormSection>

      {/* ── Benchmark ──────────────────────────────────────── */}
      <FormSection title="Benchmark">
        <div>
          <label className={fieldLabel}>Default Benchmark</label>
          <select
            value={form.default_benchmark_id ?? ''}
            onChange={e => setField('default_benchmark_id', e.target.value ? Number(e.target.value) : null)}
            className={fieldSelect}
          >
            <option value="">Select benchmark…</option>
            {netBenchmarks.map(b => (
              <option key={b.id} value={b.id}>{b.name}</option>
            ))}
            {netBenchmarks.length === 0 && benchmarks.length > 0 && (
              <>
                <option disabled>── All benchmarks ──</option>
                {benchmarks.map(b => (
                  <option key={b.id} value={b.id}>{b.name}</option>
                ))}
              </>
            )}
          </select>
        </div>
      </FormSection>

      {/* ── Important Notes ────────────────────────────────── */}
      <HintBox>
        <strong>Offline Config Audit:</strong> Upload a device configuration to evaluate CIS benchmarks
        offline without a live connection. Live scans still work for rules that need runtime data.
      </HintBox>

      {/* ── Config Audit Mode ─────────────────────────────── */}
      <FormSection title="Config Audit">
        <div>
          <label className={fieldLabel}>Config Pull Mode</label>
          <select
            value={form.config_pull_method ?? 'auto'}
            onChange={e => setField('config_pull_method', e.target.value)}
            className={fieldSelect}
          >
            <option value="auto">Auto-pull on scan (recommended)</option>
            <option value="upload_only">Upload only (no auto-pull)</option>
            <option value="disabled">Disabled</option>
          </select>
        </div>
        <div>
          <label className={fieldLabel}>Upload Configuration <span className="text-dark-muted">(optional)</span></label>
          <textarea
            value={form.config_upload_text ?? ''}
            onChange={e => setField('config_upload_text', e.target.value)}
            placeholder="Paste full running-config here..."
            rows={6}
            className={`${fieldInput} font-mono text-[11px] resize-y`}
          />
          <p className="mt-1 text-[10px] text-dark-muted">
            Supported: Cisco IOS/ASA, FortiGate, PAN-OS XML, JunOS, Check Point, pfSense XML
          </p>
        </div>
      </FormSection>

      {/* ── Prerequisites ──────────────────────────────────── */}
      <FormSection title="Prerequisites">
        <div>
          <p className="text-[11px] text-dark-muted mb-1.5 font-medium">Cisco IOS — enable SSH:</p>
          <CodeBlock>{`conf t\nip domain-name example.com\ncrypto key generate rsa modulus 2048\nip ssh version 2\nline vty 0 4\n transport input ssh`}</CodeBlock>
        </div>
        <p className="text-[11px] text-dark-secondary">
          <strong>Palo Alto:</strong> SSH is enabled by default on the management port.<br />
          <strong>Juniper:</strong> SSH is enabled by default.
        </p>
      </FormSection>
    </div>
  );
}
