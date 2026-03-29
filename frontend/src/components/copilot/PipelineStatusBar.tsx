import { CheckCircle2, Loader2, Circle, AlertTriangle, ArrowRight } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { EnrichStatus, VerifyStatus, ValidateStatus } from '@/types';

interface PipelineStatusBarProps {
  phase1Status: string;
  enrichStatus: EnrichStatus | null;
  verifyStatus: VerifyStatus | null;
  validateStatus: ValidateStatus | null;
  onQuickMessage: (message: string) => void;
}

type PhaseState = 'idle' | 'processing' | 'completed' | 'failed' | 'paused';

function resolveState(status: string | undefined): PhaseState {
  if (!status) return 'idle';
  const s = status.toLowerCase();
  if (s === 'completed' || s === 'done') return 'completed';
  if (s === 'processing' || s === 'running') return 'processing';
  if (s === 'failed' || s === 'error') return 'failed';
  if (s === 'paused') return 'paused';
  return 'idle';
}

function PhaseIndicator({
  label,
  state,
  detail,
  onClick,
}: {
  label: string;
  state: PhaseState;
  detail?: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        'flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-medium transition-colors',
        'border hover:border-amber-500/30',
        state === 'completed' && 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
        state === 'processing' && 'bg-amber-500/10 text-amber-400 border-amber-500/20',
        state === 'failed' && 'bg-red-500/10 text-red-400 border-red-500/20',
        state === 'paused' && 'bg-yellow-500/10 text-yellow-400 border-yellow-500/20',
        state === 'idle' && 'bg-dark-elevated text-dark-muted border-dark-border',
      )}
    >
      {state === 'completed' && <CheckCircle2 className="h-3 w-3" />}
      {state === 'processing' && <Loader2 className="h-3 w-3 animate-spin" />}
      {state === 'failed' && <AlertTriangle className="h-3 w-3" />}
      {state === 'paused' && <Circle className="h-3 w-3" />}
      {state === 'idle' && <Circle className="h-3 w-3" />}
      <span>{label}</span>
      {detail && <span className="text-[10px] opacity-70">{detail}</span>}
    </button>
  );
}

export default function PipelineStatusBar({
  phase1Status,
  enrichStatus,
  verifyStatus,
  validateStatus,
  onQuickMessage,
}: PipelineStatusBarProps) {
  const p1 = resolveState(phase1Status);
  const p2 = resolveState(enrichStatus?.status);
  const ver = resolveState(verifyStatus?.status);
  const p3 = resolveState(validateStatus?.status);

  // Don't show if nothing has happened yet
  if (p1 === 'idle' && p2 === 'idle' && ver === 'idle' && p3 === 'idle') return null;

  const enrichDetail = enrichStatus
    ? `${enrichStatus.processed}/${enrichStatus.total}`
    : undefined;
  const verifyDetail = verifyStatus
    ? `${verifyStatus.passed}/${verifyStatus.total}`
    : undefined;
  const validateDetail = validateStatus
    ? `${validateStatus.processed}/${validateStatus.total}`
    : undefined;

  return (
    <div className="flex items-center gap-1 px-3 py-1.5 border-b border-dark-border bg-dark-card/50 overflow-x-auto">
      <PhaseIndicator
        label="Import"
        state={p1}
        onClick={() => onQuickMessage('What is the current pipeline status?')}
      />
      <ArrowRight className="h-3 w-3 text-dark-muted shrink-0" />
      <PhaseIndicator
        label="Enrich"
        state={p2}
        detail={enrichDetail}
        onClick={() => onQuickMessage('What is the Phase 2 enrichment status?')}
      />
      <ArrowRight className="h-3 w-3 text-dark-muted shrink-0" />
      <PhaseIndicator
        label="Verify"
        state={ver}
        detail={verifyDetail}
        onClick={() => onQuickMessage('What are the verification results?')}
      />
      <ArrowRight className="h-3 w-3 text-dark-muted shrink-0" />
      <PhaseIndicator
        label="Validate"
        state={p3}
        detail={validateDetail}
        onClick={() => onQuickMessage('Show me the Phase 3 validation corrections')}
      />
    </div>
  );
}
