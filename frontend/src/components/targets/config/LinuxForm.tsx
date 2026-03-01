import { useState } from 'react';
import type { Benchmark } from '@/types';
import type { TargetFormState } from './useTargetForm';
import { FormSection, HintBox, CodeBlock, fieldInput, fieldSelect, fieldLabel } from './FormParts';

interface Props {
  form: TargetFormState;
  setField: <K extends keyof TargetFormState>(key: K, value: TargetFormState[K]) => void;
  setConnectionMethod: (m: string) => void;
  benchmarks: Benchmark[];
}

type AuthMethod = 'password' | 'key';

const DISTROS = [
  'ubuntu', 'debian', 'rhel', 'centos', 'rocky', 'alma',
  'fedora', 'suse', 'amazon-linux', 'oracle-linux', 'arch',
];

export default function LinuxForm({ form, setField, setConnectionMethod: _setCM, benchmarks }: Props) {
  const [authMethod, setAuthMethod] = useState<AuthMethod>(
    form.ssh_key_path ? 'key' : 'password',
  );

  // Filter benchmarks relevant to Linux
  const linuxBenchmarks = benchmarks.filter(
    b => b.platform_family?.toLowerCase() === 'linux' ||
         b.platform?.toLowerCase().includes('linux') ||
         b.platform?.toLowerCase().includes('ubuntu') ||
         b.platform?.toLowerCase().includes('debian') ||
         b.platform?.toLowerCase().includes('rhel') ||
         b.platform?.toLowerCase().includes('centos'),
  );

  return (
    <div className="space-y-3">
      {/* ── Connection ─────────────────────────────────────── */}
      <FormSection title="Connection">
        <div>
          <label className={fieldLabel}>Protocol</label>
          <select value="ssh" disabled className={`${fieldSelect} opacity-60`}>
            <option value="ssh">SSH</option>
          </select>
        </div>
        <div className="grid grid-cols-3 gap-2">
          <div className="col-span-2">
            <label className={fieldLabel}>IP Address</label>
            <input
              value={form.ip_address}
              onChange={e => setField('ip_address', e.target.value)}
              placeholder="192.168.1.20"
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
      </FormSection>

      {/* ── Credentials ────────────────────────────────────── */}
      <FormSection title="Credentials">
        {/* Auth method toggle */}
        <div className="flex items-center gap-4">
          <label className="flex items-center gap-1.5 text-xs text-dark-secondary cursor-pointer">
            <input
              type="radio"
              name="auth-method"
              checked={authMethod === 'password'}
              onChange={() => setAuthMethod('password')}
              className="accent-ey-yellow"
            />
            Password
          </label>
          <label className="flex items-center gap-1.5 text-xs text-dark-secondary cursor-pointer">
            <input
              type="radio"
              name="auth-method"
              checked={authMethod === 'key'}
              onChange={() => setAuthMethod('key')}
              className="accent-ey-yellow"
            />
            SSH Key
          </label>
        </div>

        <div>
          <label className={fieldLabel}>Username</label>
          <input
            value={form.ssh_username}
            onChange={e => setField('ssh_username', e.target.value)}
            placeholder="root"
            className={fieldInput}
          />
        </div>

        {authMethod === 'password' ? (
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
        ) : (
          <>
            <div>
              <label className={fieldLabel}>SSH Key Path</label>
              <input
                value={form.ssh_key_path}
                onChange={e => setField('ssh_key_path', e.target.value)}
                placeholder="/path/to/private_key.pem"
                className={fieldInput}
              />
            </div>
            <HintBox>
              Enter the path to the private key on the <strong>AuditForge server</strong>. The public key must be in <code className="text-ey-yellow/70">~/.ssh/authorized_keys</code> on the target.
            </HintBox>
          </>
        )}

        <HintBox>
          Root or a user with <strong>NOPASSWD sudo</strong> access. Commands will be auto-wrapped in <code className="text-ey-yellow/70">sudo</code> if needed.
        </HintBox>
      </FormSection>

      {/* ── Benchmark ──────────────────────────────────────── */}
      <FormSection title="Benchmark">
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className={fieldLabel}>Default Benchmark</label>
            <select
              value={form.default_benchmark_id ?? ''}
              onChange={e => setField('default_benchmark_id', e.target.value ? Number(e.target.value) : null)}
              className={fieldSelect}
            >
              <option value="">Select benchmark…</option>
              {linuxBenchmarks.map(b => (
                <option key={b.id} value={b.id}>{b.name}</option>
              ))}
              {linuxBenchmarks.length === 0 && benchmarks.length > 0 && (
                <>
                  <option disabled>── All benchmarks ──</option>
                  {benchmarks.map(b => (
                    <option key={b.id} value={b.id}>{b.name}</option>
                  ))}
                </>
              )}
            </select>
          </div>
          <div>
            <label className={fieldLabel}>Distribution</label>
            <select
              value={form.platform_subtype}
              onChange={e => setField('platform_subtype', e.target.value)}
              className={fieldSelect}
            >
              <option value="">Auto-detect</option>
              {DISTROS.map(d => (
                <option key={d} value={d}>{d.charAt(0).toUpperCase() + d.slice(1)}</option>
              ))}
            </select>
          </div>
        </div>
      </FormSection>

      {/* ── Prerequisites ──────────────────────────────────── */}
      <FormSection title="Prerequisites">
        <p className="text-[11px] text-emerald-400 font-medium">
          ✅ SSH is typically enabled by default on Linux servers.
        </p>
        <div>
          <p className="text-[11px] text-dark-muted mb-1.5 font-medium">If SSH is not running:</p>
          <CodeBlock>sudo systemctl enable --now sshd</CodeBlock>
        </div>
        {authMethod === 'key' && (
          <div>
            <p className="text-[11px] text-dark-muted mb-1.5 font-medium">Copy your public key to the target:</p>
            <CodeBlock>{`ssh-copy-id ${form.ssh_username || 'root'}@${form.ip_address || '192.168.1.20'}`}</CodeBlock>
          </div>
        )}
      </FormSection>
    </div>
  );
}
