import { Server, Radar } from 'lucide-react';
import type { Target } from '@/types';
import TargetCard from './TargetCard';

interface Props {
  targets: Target[];
  onConfigure: (target: Target) => void;
  onDelete: (targetId: number) => void;
  onScan: (target: Target) => void;
  onUsbExport: (target: Target) => void;
  onImportResults: (target: Target) => void;
  onSetupHelp: (target: Target) => void;
  onViewFindings: (target: Target) => void;
  scanningTargetIds?: Set<number>;
  scanProgressMap?: Map<number, number>;
}

export default function TargetCardGrid({
  targets,
  onConfigure,
  onDelete,
  onScan,
  onUsbExport,
  onImportResults,
  onSetupHelp,
  onViewFindings,
  scanningTargetIds = new Set(),
  scanProgressMap = new Map(),
}: Props) {
  if (targets.length === 0) {
    return (
      <div className="rounded-xl border-2 border-dashed border-dark-border bg-dark-card p-12 text-center">
        <Server className="mx-auto h-10 w-10 text-dark-muted" />
        <p className="mt-3 text-sm font-medium text-dark-secondary">No targets assigned to this mission.</p>
        <p className="mt-1.5 text-xs text-dark-muted leading-relaxed max-w-sm mx-auto">
          Use the <Radar className="inline h-3 w-3 text-ey-yellow mx-0.5" /> Discovery bar above to find devices on your network, 
          assign an existing client target, or bulk import targets via CSV.
        </p>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
      {targets.map(target => (
        <TargetCard
          key={target.id}
          target={target}
          onConfigure={onConfigure}
          onDelete={onDelete}
          onScan={onScan}
          onUsbExport={onUsbExport}
          onImportResults={onImportResults}
          onSetupHelp={onSetupHelp}
          onViewFindings={onViewFindings}
          isScanning={scanningTargetIds.has(target.id)}
          scanProgress={scanProgressMap.get(target.id)}
        />
      ))}
    </div>
  );
}
