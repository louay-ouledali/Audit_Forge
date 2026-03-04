import { useState, useRef, useEffect } from 'react';
import { Check, X, Pencil } from 'lucide-react';

interface InlineEditFieldProps {
  label: string;
  value: string;
  onSave: (newValue: string) => Promise<void>;
  multiline?: boolean;
  editable?: boolean;
  placeholder?: string;
  /** Render as select with these options */
  options?: { value: string; label: string }[];
}

export default function InlineEditField({
  label,
  value,
  onSave,
  multiline = false,
  editable = true,
  placeholder = 'Click to edit…',
  options,
}: InlineEditFieldProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const [saving, setSaving] = useState(false);
  const inputRef = useRef<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>(null);

  useEffect(() => {
    if (editing && inputRef.current) {
      inputRef.current.focus();
    }
  }, [editing]);

  // Sync draft with value when not editing
  useEffect(() => {
    if (!editing) setDraft(value);
  }, [value, editing]);

  const handleSave = async () => {
    if (draft === value) { setEditing(false); return; }
    setSaving(true);
    try {
      await onSave(draft);
      setEditing(false);
    } catch {
      // keep editing on error
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = () => {
    setDraft(value);
    setEditing(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !multiline) { e.preventDefault(); handleSave(); }
    if (e.key === 'Enter' && multiline && (e.ctrlKey || e.metaKey)) { e.preventDefault(); handleSave(); }
    if (e.key === 'Escape') handleCancel();
  };

  if (!editable) {
    return (
      <div>
        <span className="text-xs font-medium text-dark-secondary">{label}:</span>
        <p className="mt-1 text-sm text-gray-300">{value || <span className="italic text-dark-muted">Not set</span>}</p>
      </div>
    );
  }

  if (editing) {
    return (
      <div>
        <span className="text-xs font-medium text-dark-secondary">{label}:</span>
        <div className="mt-1 flex gap-2">
          <div className="flex-1">
            {options ? (
              <select
                ref={inputRef as React.Ref<HTMLSelectElement>}
                value={draft}
                onChange={e => setDraft(e.target.value)}
                onKeyDown={handleKeyDown}
                className="w-full rounded-lg border border-ey-yellow/30 bg-dark-card px-3 py-1.5 text-sm text-white focus:border-ey-yellow/50 focus:outline-none focus:ring-1 focus:ring-ey-yellow/20"
              >
                {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            ) : multiline ? (
              <textarea
                ref={inputRef as React.Ref<HTMLTextAreaElement>}
                value={draft}
                onChange={e => setDraft(e.target.value)}
                onKeyDown={handleKeyDown}
                rows={4}
                placeholder={placeholder}
                className="w-full rounded-lg border border-ey-yellow/30 bg-dark-card px-3 py-2 text-sm text-white placeholder-dark-muted focus:border-ey-yellow/50 focus:outline-none focus:ring-1 focus:ring-ey-yellow/20 resize-y"
              />
            ) : (
              <input
                ref={inputRef as React.Ref<HTMLInputElement>}
                type="text"
                value={draft}
                onChange={e => setDraft(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={placeholder}
                className="w-full rounded-lg border border-ey-yellow/30 bg-dark-card px-3 py-1.5 text-sm text-white placeholder-dark-muted focus:border-ey-yellow/50 focus:outline-none focus:ring-1 focus:ring-ey-yellow/20"
              />
            )}
          </div>
          <div className="flex items-start gap-1">
            <button
              onClick={handleSave}
              disabled={saving}
              className="rounded-md bg-emerald-500/20 p-1.5 text-emerald-400 hover:bg-emerald-500/30 disabled:opacity-50"
              title="Save (Enter)"
            >
              <Check className="h-3.5 w-3.5" />
            </button>
            <button
              onClick={handleCancel}
              disabled={saving}
              className="rounded-md bg-dark-overlay p-1.5 text-dark-secondary hover:text-white disabled:opacity-50"
              title="Cancel (Esc)"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
        {multiline && <p className="mt-1 text-[10px] text-dark-muted">Ctrl+Enter to save, Esc to cancel</p>}
      </div>
    );
  }

  return (
    <div className="group/edit cursor-pointer" onClick={() => setEditing(true)}>
      <span className="text-xs font-medium text-dark-secondary">{label}:</span>
      <div className="mt-1 flex items-start gap-2">
        <p className="flex-1 text-sm text-gray-300 rounded px-1 -mx-1 group-hover/edit:bg-dark-overlay/50 transition-colors">
          {value || <span className="italic text-dark-muted">{placeholder}</span>}
        </p>
        <Pencil className="h-3.5 w-3.5 text-dark-muted opacity-0 group-hover/edit:opacity-100 transition-opacity mt-0.5 shrink-0" />
      </div>
    </div>
  );
}
