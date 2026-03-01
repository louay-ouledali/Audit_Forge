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
    <div className="space-y-4">
      {/* ── Connection ─────────────────────────────────────── */}
      <FormSection title="Connection">
        <div>
          <label className={fieldLabel}>Protocol</label>
          <select value="ssh" disabled className={`${fieldSelect} opacity-60`}>
            <option value="ssh">SSH (Netmiko)</option>
          </select>
        </div>
        <div className="grid grid-cols-3 gap-3">
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
      <WarningBox>
        <strong>USB Air-Gap NOT Supported.</strong><br />
        Network devices require a live SSH session to execute <code className="text-amber-200">show running-config</code>,{' '}
        <code className="text-amber-200">show ip route</code>, and similar commands. Use <strong>Scan Now</strong> for this target.
      </WarningBox>

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
