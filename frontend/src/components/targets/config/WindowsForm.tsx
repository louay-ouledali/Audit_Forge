import type { Benchmark } from '@/types';
import type { TargetFormState } from './useTargetForm';
import { FormSection, HintBox, CodeBlock, fieldInput, fieldSelect, fieldLabel } from './FormParts';

interface Props {
  form: TargetFormState;
  setField: <K extends keyof TargetFormState>(key: K, value: TargetFormState[K]) => void;
  setConnectionMethod: (m: string) => void;
  benchmarks: Benchmark[];
}

export default function WindowsForm({ form, setField, setConnectionMethod, benchmarks }: Props) {
  const winBenchmarks = benchmarks.filter(
    b => b.platform_family?.toLowerCase() === 'windows' || b.platform?.toLowerCase().includes('windows'),
  );

  return (
    <div className="space-y-3">
      {/* ── Connection ─────────────────────────────────────── */}
      <FormSection title="Connection">
        <div>
          <label className={fieldLabel}>Protocol</label>
          <select
            value={form.connection_method}
            onChange={e => setConnectionMethod(e.target.value)}
            className={fieldSelect}
          >
            <option value="winrm">WinRM (recommended)</option>
            <option value="ssh">SSH (Windows OpenSSH)</option>
          </select>
        </div>
        <div className="grid grid-cols-3 gap-2">
          <div className="col-span-2">
            <label className={fieldLabel}>IP Address</label>
            <input
              value={form.ip_address}
              onChange={e => setField('ip_address', e.target.value)}
              placeholder="192.168.1.10"
              className={fieldInput}
            />
          </div>
          <div>
            <label className={fieldLabel}>Port</label>
            <input
              value={form.port}
              onChange={e => setField('port', e.target.value)}
              placeholder={form.connection_method === 'winrm' ? '5986' : '22'}
              className={fieldInput}
            />
          </div>
        </div>
        <HintBox>
          WinRM uses ports <strong>5985</strong> (HTTP) or <strong>5986</strong> (HTTPS).
          HTTPS is strongly recommended. For domain-joined machines, use 5985 with NTLM.
        </HintBox>
      </FormSection>

      {/* ── Credentials ────────────────────────────────────── */}
      <FormSection title="Credentials">
        <div>
          <label className={fieldLabel}>Username</label>
          <input
            value={form.ssh_username}
            onChange={e => setField('ssh_username', e.target.value)}
            placeholder="Administrator"
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
        <HintBox>
          Needs <strong>local admin</strong> or <strong>domain admin</strong> rights.<br />
          For domain: <code className="text-ey-yellow/70">DOMAIN\username</code> or <code className="text-ey-yellow/70">user@domain.com</code>
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
            {winBenchmarks.map(b => (
              <option key={b.id} value={b.id}>{b.name}</option>
            ))}
            {winBenchmarks.length === 0 && benchmarks.length > 0 && (
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

      {/* ── Prerequisites ──────────────────────────────────── */}
      <FormSection title="Prerequisites">
        <div className="space-y-3">
          <p className="text-[11px] text-dark-secondary">
            <span className="text-amber-400 font-semibold">⚠ WinRM may need to be enabled</span> on the target machine.
          </p>

          <div>
            <p className="text-[11px] text-dark-muted mb-1.5 font-medium">For standalone machines, run on the target:</p>
            <CodeBlock>{`Enable-PSRemoting -Force\nwinrm quickconfig -q\nSet-Item WSMan:\\localhost\\Service\\Auth\\Basic -Value $true`}</CodeBlock>
          </div>

          <div>
            <p className="text-[11px] text-dark-muted mb-1.5 font-medium">For domain machines via GPO:</p>
            <p className="text-[11px] text-dark-secondary leading-relaxed">
              Computer Config → Policies → Admin Templates → Windows Components → Windows Remote Management → WinRM Service → <em>Allow remote server management</em>
            </p>
          </div>

          <HintBox>
            Our Hardening Script enables WinRM automatically. See <strong>Enable_WinRM_After_Hardening.ps1</strong> in the project root.
          </HintBox>
        </div>
      </FormSection>
    </div>
  );
}
