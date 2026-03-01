import type { Benchmark } from '@/types';
import type { TargetFormState } from './useTargetForm';
import { defaultPortFor } from './useTargetForm';
import { FormSection, HintBox, WarningBox, CodeBlock, fieldInput, fieldSelect, fieldLabel } from './FormParts';

interface Props {
  form: TargetFormState;
  setField: <K extends keyof TargetFormState>(key: K, value: TargetFormState[K]) => void;
  setConnectionMethod: (m: string) => void;
  benchmarks: Benchmark[];
}

const DB_TYPES = [
  { value: 'postgresql', label: 'PostgreSQL', defaultPort: 5432 },
  { value: 'mssql', label: 'Microsoft SQL Server', defaultPort: 1433 },
  { value: 'oracle', label: 'Oracle Database', defaultPort: 1521 },
];

export default function DatabaseForm({ form, setField, setConnectionMethod, benchmarks }: Props) {
  const dbType = form.connection_method || 'postgresql';

  const dbBenchmarks = benchmarks.filter(
    b => b.platform_family?.toLowerCase() === 'database' ||
         b.platform?.toLowerCase().includes('postgres') ||
         b.platform?.toLowerCase().includes('mssql') ||
         b.platform?.toLowerCase().includes('sql server') ||
         b.platform?.toLowerCase().includes('oracle') ||
         b.platform?.toLowerCase().includes('mysql'),
  );

  const handleDbTypeChange = (value: string) => {
    setConnectionMethod(value);
    setField('platform_subtype', value);
    setField('port', defaultPortFor(value).toString());
  };

  return (
    <div className="space-y-3">
      {/* ── Connection ─────────────────────────────────────── */}
      <FormSection title="Connection">
        <div>
          <label className={fieldLabel}>Database Type</label>
          <select
            value={dbType}
            onChange={e => handleDbTypeChange(e.target.value)}
            className={fieldSelect}
          >
            {DB_TYPES.map(dt => (
              <option key={dt.value} value={dt.value}>{dt.label}</option>
            ))}
          </select>
        </div>
        <div className="grid grid-cols-3 gap-2">
          <div className="col-span-2">
            <label className={fieldLabel}>Host</label>
            <input
              value={form.ip_address}
              onChange={e => setField('ip_address', e.target.value)}
              placeholder="192.168.1.50"
              className={fieldInput}
            />
          </div>
          <div>
            <label className={fieldLabel}>Port</label>
            <input
              value={form.port}
              onChange={e => setField('port', e.target.value)}
              placeholder={defaultPortFor(dbType).toString()}
              className={fieldInput}
            />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className={fieldLabel}>Database Name</label>
            <input
              value={form.db_name}
              onChange={e => setField('db_name', e.target.value)}
              placeholder={dbType === 'postgresql' ? 'postgres' : dbType === 'oracle' ? 'ORCL' : 'master'}
              className={fieldInput}
            />
          </div>
          {dbType === 'mssql' && (
            <div>
              <label className={fieldLabel}>Instance <span className="text-dark-muted">(optional)</span></label>
              <input
                value={form.db_instance}
                onChange={e => setField('db_instance', e.target.value)}
                placeholder="MSSQLSERVER"
                className={fieldInput}
              />
            </div>
          )}
        </div>
      </FormSection>

      {/* ── Credentials ────────────────────────────────────── */}
      <FormSection title="Credentials">
        <div>
          <label className={fieldLabel}>Username</label>
          <input
            value={form.ssh_username}
            onChange={e => setField('ssh_username', e.target.value)}
            placeholder={dbType === 'postgresql' ? 'postgres' : dbType === 'mssql' ? 'sa' : 'sys'}
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
          {dbType === 'postgresql' && (
            <>Use a privileged user (<strong>superuser</strong> or <code className="text-ey-yellow/70">pg_read_all_settings</code> role).</>
          )}
          {dbType === 'mssql' && (
            <>Use <strong>sa</strong> or a <code className="text-ey-yellow/70">sysadmin</code> role member.</>
          )}
          {dbType === 'oracle' && (
            <>Use <strong>SYSDBA</strong> or <code className="text-ey-yellow/70">DBA</code> role.</>
          )}
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
            {dbBenchmarks.map(b => (
              <option key={b.id} value={b.id}>{b.name}</option>
            ))}
            {dbBenchmarks.length === 0 && benchmarks.length > 0 && (
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
        Database audits execute SQL queries directly on the server. There is no way to export SQL queries as a standalone script.
        Use <strong>Scan Now</strong> for this target.
      </WarningBox>

      {/* ── Prerequisites ──────────────────────────────────── */}
      <FormSection title="Prerequisites">
        <p className="text-[11px] text-dark-secondary mb-2">
          Ensure the database accepts remote connections from the AuditForge server.
        </p>

        {dbType === 'postgresql' && (
          <div>
            <p className="text-[11px] text-dark-muted mb-1.5 font-medium">Edit <code className="text-ey-yellow/70">pg_hba.conf</code>:</p>
            <CodeBlock>{`host  all  postgres  192.168.1.0/24  md5`}</CodeBlock>
            <p className="mt-1.5 text-[11px] text-dark-muted">Then reload: <code className="text-ey-yellow/70">sudo systemctl reload postgresql</code></p>
          </div>
        )}

        {dbType === 'mssql' && (
          <div>
            <p className="text-[11px] text-dark-secondary leading-relaxed">
              Enable <strong>TCP/IP</strong> in SQL Server Configuration Manager and ensure port <strong>1433</strong> is open in the firewall.
            </p>
          </div>
        )}

        {dbType === 'oracle' && (
          <div>
            <p className="text-[11px] text-dark-muted mb-1.5 font-medium">Verify listener is running:</p>
            <CodeBlock>lsnrctl status</CodeBlock>
          </div>
        )}
      </FormSection>
    </div>
  );
}
