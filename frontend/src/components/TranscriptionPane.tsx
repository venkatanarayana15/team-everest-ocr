import { useState, useCallback, useMemo, useRef, useEffect } from 'react';
import type { Field } from '../types';

interface Props {
  rawText: string;
  fields: Field[];
  currentPage: number;
  onFieldClick: (field: Field) => void;
  jobId: string;
  onFieldsUpdated: (fields: Field[]) => void;
}

function getPageText(rawText: string, pageNum: number): string {
  const parts = rawText.split(/--- Page \d+ ---/);
  if (parts.length === 1) return rawText;
  if (pageNum < parts.length) return parts[pageNum]?.trim() || '';
  return parts[parts.length - 1]?.trim() || '';
}

export default function TranscriptionPane({ rawText, fields, currentPage, onFieldClick, jobId, onFieldsUpdated }: Props) {
  const [editingLabel, setEditingLabel] = useState<string | null>(null);
  const [editValue, setEditValue] = useState('');
  const [saving, setSaving] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const [focusIdx, setFocusIdx] = useState<number | null>(null);

  const pageFields = useMemo(
    () => fields.filter((f) => f.page === currentPage),
    [fields, currentPage],
  );

  const pageText = useMemo(
    () => getPageText(rawText, currentPage),
    [rawText, currentPage],
  );

  const fieldByLabel = useMemo(() => {
    const m = new Map<string, Field>();
    for (const f of pageFields) m.set(f.label, f);
    return m;
  }, [pageFields]);

  // ── Match fields to lines in raw_text (flexible, no regex required) ──

  const lineToField = useMemo(() => {
    const map = new Map<number, Field>();
    if (!pageText || fieldByLabel.size === 0) return map;

    const lines = pageText.split('\n');
    const assigned = new Set<string>();

    // First pass: exact label match (case-insensitive)
    for (let i = 0; i < lines.length; i++) {
      const lineLower = lines[i].toLowerCase();
      for (const [label, field] of fieldByLabel) {
        if (assigned.has(label)) continue;
        if (lineLower.includes(label.toLowerCase())) {
          map.set(i, field);
          assigned.add(label);
          break;
        }
      }
    }

    // Second pass: partial label match (label is a substring of the line)
    for (let i = 0; i < lines.length; i++) {
      if (map.has(i)) continue;
      const lineLower = lines[i].toLowerCase();
      for (const [label, field] of fieldByLabel) {
        if (assigned.has(label)) continue;
        // Check if any word in the label appears in the line
        const labelWords = label.toLowerCase().split(/[\s,]+/).filter(Boolean);
        const matches = labelWords.filter((w) => w.length > 2 && lineLower.includes(w));
        if (matches.length >= Math.min(2, labelWords.length)) {
          map.set(i, field);
          assigned.add(label);
          break;
        }
      }
    }

    return map;
  }, [pageText, fieldByLabel]);

  // ── Build segments: alternating text ↔ field ────────────────────

  const segments = useMemo(() => {
    const segs: Array<{ key: number; type: 'text' | 'field'; content: string; field?: Field }> = [];
    const lines = pageText.split('\n');
    let key = 0;

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      const field = lineToField.get(i);

      if (field) {
        // Find where the label appears in the line
        const labelLower = field.label.toLowerCase();
        const lineLower = line.toLowerCase();
        const labelIdx = lineLower.indexOf(labelLower);

        if (labelIdx >= 0) {
          // Text before the label
          if (labelIdx > 0) {
            segs.push({ key: key++, type: 'text', content: line.slice(0, labelIdx) });
          }
          // The label itself — include everything up to where the value starts
          const afterLabel = labelIdx + field.label.length;
          let labelEnd = afterLabel;
          // Skip separators: `:**`, `:`, `**`, spaces, `|`
          while (labelEnd < line.length && /[:\s*|]/.test(line[labelEnd])) {
            if (line[labelEnd] === '|' && labelEnd < line.length - 1 && line[labelEnd + 1] === ' ') {
              // Table cell boundary — stop before the pipe
              break;
            }
            labelEnd++;
          }
          // Also stop if we hit another bold marker or pipe
          const labelPortion = line.slice(labelIdx, labelEnd);
          segs.push({ key: key++, type: 'field', content: labelPortion, field });
          // Text after the label + value area — skip to next line's content
          // Don't add trailing text if it's just whitespace/pipes
          const rest = line.slice(labelEnd).trim();
          if (rest && !/^[\s|]+$/.test(rest)) {
            segs.push({ key: key++, type: 'text', content: rest + '\n' });
          } else {
            segs.push({ key: key++, type: 'text', content: '\n' });
          }
          continue;
        }
      }

      segs.push({ key: key++, type: 'text', content: line + '\n' });
    }

    return segs;
  }, [pageText, lineToField]);

  // ── Edit handlers ──────────────────────────────────────────────

  const handleStartEdit = useCallback((field: Field) => {
    setEditingLabel(field.label);
    setEditValue(field.value);
  }, []);

  useEffect(() => {
    if (editingLabel && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [editingLabel]);

  const handleSave = useCallback(async () => {
    if (!editingLabel) return;
    setSaving(true);
    try {
      const res = await fetch(`/correct/${jobId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ label: editingLabel, correct_value: editValue }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const updated = fields.map((f) =>
        f.label === editingLabel ? { ...f, value: editValue } : f,
      );
      onFieldsUpdated(updated);
      setEditingLabel(null);
    } catch (e) {
      console.error('Failed to save correction:', e);
    }
    setSaving(false);
  }, [editingLabel, editValue, jobId, fields, onFieldsUpdated]);

  const handleCancel = useCallback(() => {
    setEditingLabel(null);
  }, []);

  const handleKeyDown = useCallback((e: React.KeyboardEvent, field: Field) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleSave();
    } else if (e.key === 'Escape') {
      handleCancel();
    }
  }, [handleSave, handleCancel]);

  // ── Tab navigation between fields ──────────────────────────────

  const editableFields = useMemo(
    () => segments.filter((s) => s.type === 'field').map((s) => s.field!),
    [segments],
  );

  useEffect(() => {
    if (focusIdx !== null && focusIdx < editableFields.length) {
      const f = editableFields[focusIdx];
      if (f) handleStartEdit(f);
      setFocusIdx(null);
    }
  }, [focusIdx, editableFields, handleStartEdit]);

  const handleTabNav = useCallback((e: React.KeyboardEvent) => {
    if (!editingLabel || e.key !== 'Tab') return;
    e.preventDefault();
    const currentIdx = editableFields.findIndex((f) => f.label === editingLabel);
    if (e.shiftKey) {
      if (currentIdx > 0) setFocusIdx(currentIdx - 1);
    } else {
      if (currentIdx < editableFields.length - 1) setFocusIdx(currentIdx + 1);
    }
  }, [editingLabel, editableFields]);

  // ── Render segments into JSX ───────────────────────────────────

  const rendered = useMemo(() => {
    let fieldIdx = -1;
    const els: React.ReactNode[] = [];

    for (const seg of segments) {
      if (seg.type === 'text' && !seg.field) {
        els.push(<span key={seg.key} style={{ whiteSpace: 'pre-wrap' }}>{seg.content}</span>);
        continue;
      }
      if (seg.type === 'field' && seg.field) {
        fieldIdx++;
        const f = seg.field;
        const isEditing = editingLabel === f.label;
        const lowConf = f.confidence < 80 || f.needs_clarification;

        els.push(
          <span key={seg.key} style={{ whiteSpace: 'pre-wrap' }}>
            <span
              onClick={() => onFieldClick(f)}
              style={{
                cursor: 'pointer',
                color: '#1e293b',
                fontWeight: 700,
                borderBottom: lowConf ? '2px solid #eab308' : '2px solid transparent',
              }}
              title={`${f.label} (${f.confidence}%)`}
            >
              {seg.content}
            </span>

            {isEditing ? (
              <span
                onClick={(e) => e.stopPropagation()}
                style={{
                  background: '#eff6ff',
                  borderRadius: 4,
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 4,
                }}
              >
                <input
                  ref={inputRef}
                  value={editValue}
                  onChange={(e) => setEditValue(e.target.value)}
                  onKeyDown={(e) => handleKeyDown(e, f)}
                  style={{
                    padding: '2px 6px',
                    borderRadius: 4,
                    border: '2px solid #2563eb',
                    fontSize: 14,
                    outline: 'none',
                    background: '#fff',
                    minWidth: 100,
                  }}
                />
                <button
                  onClick={handleSave}
                  disabled={saving}
                  style={{
                    padding: '2px 8px',
                    border: 'none',
                    borderRadius: 4,
                    background: '#2563eb',
                    color: '#fff',
                    fontSize: 11,
                    fontWeight: 600,
                    cursor: 'pointer',
                  }}
                >
                  {saving ? '...' : 'Save'}
                </button>
                <button
                  onClick={handleCancel}
                  style={{
                    padding: '2px 8px',
                    border: '1px solid #cbd5e1',
                    borderRadius: 4,
                    background: '#fff',
                    cursor: 'pointer',
                    fontSize: 11,
                  }}
                >
                  Cancel
                </button>
              </span>
            ) : (
              <span
                onClick={() => onFieldClick(f)}
                onDoubleClick={() => handleStartEdit(f)}
                style={{
                  cursor: 'pointer',
                  background: f.original_value ? '#f0fdf4' : lowConf ? '#fffbeb' : 'transparent',
                  borderRadius: 2,
                  padding: '0 2px',
                  borderBottom: f.original_value
                    ? '2px solid #16a34a'
                    : lowConf
                      ? '2px dashed #eab308'
                      : '2px solid transparent',
                }}
                title={
                  f.original_value
                    ? `Corrected from "${f.original_value}" — double-click to edit`
                    : lowConf
                      ? 'Low confidence — double-click to edit'
                      : 'Double-click to edit'
                }
              >
                {f.original_value && (
                  <span style={{ textDecoration: 'line-through', color: '#94a3b8', marginRight: 4 }}>
                    {f.original_value}
                  </span>
                )}
                {f.value}
              </span>
            )}
          </span>,
        );
      }
    }

    return els;
  }, [segments, editingLabel, editValue, saving, onFieldClick, handleStartEdit, handleKeyDown, handleSave, handleCancel]);

  // ── Unmatched fields (not found in raw_text) ───────────────────

  const unmatched = useMemo(() => {
    const assignedLabels = new Set(Array.from(lineToField.values()).map((f) => f.label));
    return pageFields.filter((f) => !assignedLabels.has(f.label));
  }, [pageFields, lineToField]);

  return (
    <div
      onKeyDown={handleTabNav}
      style={{
        flex: 1,
        overflow: 'auto',
        padding: '20px 24px',
        background: 'var(--color-surface)',
        fontFamily: 'var(--font-mono)',
        fontSize: 13,
        lineHeight: 1.65,
        whiteSpace: 'pre-wrap',
      }}
    >
      {/* Hint bar */}
      <div style={{
        marginBottom: 12,
        padding: '6px 12px',
        borderRadius: 'var(--radius-md)',
        background: 'var(--color-bg)',
        border: '1px solid var(--color-border)',
        fontSize: 11,
        color: 'var(--color-text-secondary)',
        display: 'flex',
        gap: 16,
        alignItems: 'center',
        fontFamily: 'var(--font-sans)',
        flexWrap: 'wrap',
      }}>
        <span>🖱️ Click label → highlight on image</span>
        <span>✏️ Double-click value to edit</span>
        <span>⭾ Tab to next field</span>
        <span style={{ marginLeft: 'auto', color: 'var(--color-text-muted)' }}>
          {editingLabel ? `Editing: ${editingLabel}` : `${fieldByLabel.size} fields on page ${currentPage}`}
        </span>
      </div>

      {/* Transcription body */}
      <div style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
        {rendered}
      </div>

      {/* Unmatched fields */}
      {unmatched.length > 0 && (
        <div style={{ marginTop: 20, padding: 12, background: 'var(--color-bg)', borderRadius: 'var(--radius-lg)', border: '1px solid var(--color-border)' }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-text-secondary)', marginBottom: 8 }}>
            Unmatched fields (not found in transcription text)
          </div>
          {unmatched.map((f, i) => (
            <div
              key={i}
              onClick={() => onFieldClick(f)}
              style={{
                padding: '6px 10px', cursor: 'pointer', borderRadius: 'var(--radius-sm)',
                background: 'var(--color-surface)', border: '1px solid var(--color-border)', marginBottom: 4,
                fontFamily: 'var(--font-sans)',
              }}
            >
              <span style={{ fontWeight: 600, fontSize: 13, color: 'var(--color-text)' }}>{f.label}</span>
              <span style={{ marginLeft: 8, color: 'var(--color-text-tertiary)', fontSize: 13 }}>{f.value}</span>
              <span style={{ marginLeft: 8, fontSize: 11, color: 'var(--color-text-muted)' }}>{f.confidence}%</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
