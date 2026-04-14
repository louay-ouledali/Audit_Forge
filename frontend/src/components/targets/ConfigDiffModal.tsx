import { useEffect, useState } from 'react';
import ReactDiffViewer, { DiffMethod } from 'react-diff-viewer-continued';
import { X, Loader2 } from 'lucide-react';
import * as api from '@/services/api';

interface Props {
  snapshotAId: number;
  snapshotBId: number;
  onClose: () => void;
}

export default function ConfigDiffModal({ snapshotAId, snapshotBId, onClose }: Props) {
  const [loading, setLoading] = useState(true);
  const [oldText, setOldText] = useState('');
  const [newText, setNewText] = useState('');
  const [stats, setStats] = useState({ added: 0, removed: 0 });

  useEffect(() => {
    async function load() {
      setLoading(true);
      try {
        const [snapA, snapB] = await Promise.all([
          api.getConfigDetail(snapshotAId),
          api.getConfigDetail(snapshotBId),
        ]);
        setOldText(snapA.raw_config);
        setNewText(snapB.raw_config);

        const diff = await api.diffConfigs(snapshotAId, snapshotBId);
        setStats({ added: diff.lines_added, removed: diff.lines_removed });
      } catch (e) {
        console.error('Failed to load diff:', e);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [snapshotAId, snapshotBId]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="flex h-[85vh] w-full max-w-6xl flex-col rounded-xl border border-dark-border bg-dark-card shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-dark-border px-5 py-3">
          <div className="flex items-center gap-3">
            <h3 className="text-sm font-semibold text-white">Configuration Diff</h3>
            <span className="text-xs text-dark-muted">
              Snapshot #{snapshotAId} vs #{snapshotBId}
            </span>
            {!loading && (
              <span className="text-xs">
                <span className="text-green-400">+{stats.added}</span>
                {' / '}
                <span className="text-red-400">-{stats.removed}</span>
              </span>
            )}
          </div>
          <button onClick={onClose} className="rounded p-1 text-dark-muted hover:text-white">
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-auto">
          {loading ? (
            <div className="flex items-center justify-center py-20 text-dark-muted">
              <Loader2 className="mr-2 h-5 w-5 animate-spin" />
              Loading diff...
            </div>
          ) : (
            <ReactDiffViewer
              oldValue={oldText}
              newValue={newText}
              splitView
              compareMethod={DiffMethod.LINES}
              useDarkTheme
              leftTitle={`Snapshot #${snapshotAId}`}
              rightTitle={`Snapshot #${snapshotBId}`}
              styles={{
                variables: {
                  dark: {
                    diffViewerBackground: '#0d0d1a',
                    codeFoldBackground: '#1a1a2e',
                    emptyLineBackground: '#1a1a2e',
                    addedBackground: '#1a3a2a',
                    removedBackground: '#3a1a1a',
                    wordAddedBackground: '#264f36',
                    wordRemovedBackground: '#4f2626',
                    addedColor: '#86efac',
                    removedColor: '#fca5a5',
                  },
                },
              }}
            />
          )}
        </div>
      </div>
    </div>
  );
}
