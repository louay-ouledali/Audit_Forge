import { Plus, Upload, Crosshair, Package, FileSearch } from 'lucide-react';
import { inputClass } from '../mission/badgeHelpers';
import type { Target } from '@/types';

interface Props {
  unassignedTargets: Target[];
  assignTargetId: number | '';
  onAssignChange: (id: number | '') => void;
  onAssign: () => void;
  onBulkImportToggle: () => void;
  showImport: boolean;
  onScanAll: () => void;
  onUsbAll: () => void;
  onSmartImport?: () => void;
  targetCount: number;
  hasScannable: boolean;
}

export default function TargetActionBar({
  unassignedTargets,
  assignTargetId,
  onAssignChange,
  onAssign,
  onBulkImportToggle,
  showImport,
  onScanAll,
  onUsbAll,
  onSmartImport,
  targetCount,
  hasScannable,
}: Props) {
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      {/* Left side: assign + import */}
      <div className="flex flex-wrap items-center gap-2">
        {unassignedTargets.length > 0 && (
          <div className="flex items-center gap-2">
            <select
              value={assignTargetId}
              onChange={e => onAssignChange(e.target.value ? Number(e.target.value) : '')}
              className={`${inputClass} max-w-[180px] text-xs`}
            >
              <option value="">Assign existing…</option>
              {unassignedTargets.map(t => (
                <option key={t.id} value={t.id}>
                  {t.hostname || t.ip_address || `#${t.id}`} ({t.target_type})
                </option>
              ))}
            </select>
            <button
              onClick={onAssign}
              disabled={!assignTargetId}
              className="rounded-lg bg-ey-yellow px-3 py-2 text-xs font-semibold text-black hover:bg-ey-yellow-hover disabled:opacity-40 transition-colors whitespace-nowrap"
            >
              <Plus className="mr-1 inline h-3 w-3" />
              Assign
            </button>
          </div>
        )}

        <button
          onClick={onBulkImportToggle}
          className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-2 text-xs font-medium transition-colors ${
            showImport
              ? 'border-ey-yellow text-ey-yellow bg-ey-yellow/10'
              : 'border-dark-border bg-dark-card text-dark-secondary hover:text-white hover:bg-dark-elevated'
          }`}
        >
          <Upload className="h-3.5 w-3.5" /> Bulk Import
        </button>

        {onSmartImport && (
          <button
            onClick={onSmartImport}
            className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs font-medium text-emerald-400 transition-colors hover:bg-emerald-500/20 hover:text-emerald-300"
            title="Import scan results (.csv, .html, .nessus, .xml, .json, .zip) with auto-detection"
          >
            <FileSearch className="h-3.5 w-3.5" /> Smart Import
          </button>
        )}
      </div>

      {/* Right side: scan all + usb all */}
      {targetCount > 0 && (
        <div className="flex items-center gap-2">
          <button
            onClick={onScanAll}
            disabled={!hasScannable}
            className="inline-flex items-center gap-1.5 rounded-lg bg-ey-yellow px-4 py-2 text-xs font-bold text-black transition-colors hover:bg-ey-yellow-hover disabled:opacity-40 shadow-sm shadow-ey-yellow/10"
          >
            <Crosshair className="h-3.5 w-3.5" /> Scan All
          </button>
          <button
            onClick={onUsbAll}
            className="inline-flex items-center gap-1.5 rounded-lg border border-dark-border bg-dark-elevated px-4 py-2 text-xs font-medium text-dark-secondary transition-colors hover:text-white hover:bg-dark-overlay"
          >
            <Package className="h-3.5 w-3.5" /> USB All
          </button>
        </div>
      )}
    </div>
  );
}
