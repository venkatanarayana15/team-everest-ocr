import { useState } from 'react';
import type { Field } from '../types';
import { correctField } from '../api/client';
import ConfidenceBar from './ConfidenceBar';

interface Props {
  field: Field;
  isSelected: boolean;
  onClick: () => void;
  jobId: string;
  onCorrected: (label: string, newValue: string) => void;
}

function confidencePill(conf: number): { label: string; color: string; bg: string } {
  if (conf >= 80) return { label: 'High', color: '#166534', bg: '#dcfce7' };
  if (conf >= 50) return { label: 'Medium', color: '#854d0e', bg: '#fef9c3' };
  return { label: 'Low', color: '#991b1b', bg: '#fee2e2' };
}

function provenanceBadge(field: Field): { label: string; color: string } | null {
  const parts: string[] = [];
  if (field.extracted_by) parts.push(field.extracted_by);
  if (field.verified_by && field.verified_by !== field.extracted_by) parts.push(`→ ${field.verified_by}`);
  if (parts.length === 0) return null;
  return { label: parts.join(' '), color: '#6366f1' };
}

function statusBadge(field: Field): { label: string; color: string } | null {
  if (!field.is_verified) return null;
  if (field.original_value) return { label: '✓ Corrected', color: '#16a34a' };
  if (field.verification_note && field.verifier_confidence !== null && field.verifier_confidence < 60) {
    return { label: '⚠ Discrepant', color: '#eab308' };
  }
  return { label: '✓ Verified', color: '#22c55e' };
}

const CHECKBOX_VALUES = new Set(['✓', '✗', '?', '[✓]', '[✗]', '[—]', 'yes', 'no']);

function isCheckbox(val: string | null): boolean {
  return CHECKBOX_VALUES.has((val ?? '').toLowerCase().trim());
}

function CheckboxDisplay({ value }: { value: string | null }) {
  const v = (value ?? '').trim();
  if (v === '✓' || v === '[✓]') {
    return (
      <span style={{
        display: 'inline-flex', alignItems: 'center', gap: 6,
        color: '#16a34a', fontWeight: 700, fontSize: 16,
      }}>
        <span style={{
          width: 20, height: 20, borderRadius: 4,
          background: '#16a34a', color: '#fff',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 13, fontWeight: 700,
        }}>✓</span>
        Checked
      </span>
    );
  }
  if (v === '✗' || v === '[✗]') {
    return (
      <span style={{
        display: 'inline-flex', alignItems: 'center', gap: 6,
        color: '#dc2626', fontWeight: 600, fontSize: 16,
      }}>
        <span style={{
          width: 20, height: 20, borderRadius: 4,
          border: '2px solid #dc2626', color: '#dc2626',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 13, fontWeight: 700,
        }}>✗</span>
        Unchecked
      </span>
    );
  }
  if (v === '?' || v === '[—]') {
    return (
      <span style={{
        display: 'inline-flex', alignItems: 'center', gap: 6,
        color: '#d97706', fontWeight: 600, fontSize: 16,
      }}>
        <span style={{
          width: 20, height: 20, borderRadius: 4,
          border: '2px solid #d97706', color: '#d97706',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 14, fontWeight: 700,
        }}>?</span>
        Uncertain
      </span>
    );
  }
  if (v.toLowerCase() === 'yes') {
    return (
      <span style={{ color: '#16a34a', fontWeight: 600, fontSize: 15 }}>Yes ✓</span>
    );
  }
  if (v.toLowerCase() === 'no') {
    return (
      <span style={{ color: '#dc2626', fontWeight: 600, fontSize: 15 }}>No ✗</span>
    );
  }
  return <>{value}</>;
}

const FONT_BASE = 16;

export default function FieldCard({ field, isSelected, onClick, jobId, onCorrected }: Props) {
  const [editing, setEditing] = useState(false);
  const [editValue, setEditValue] = useState(field.value ?? '');
  const [saving, setSaving] = useState(false);
  const checkbox = isCheckbox(field.value);

  const badge = statusBadge(field);
  const prov = provenanceBadge(field);
  const pill = confidencePill(field.confidence);
  const lowConfidence = field.confidence < 80 || field.needs_clarification;
  const isCorrected = field.original_value !== null && field.original_value !== '';

  const toggleCheckbox = () => {
    const newVal = (field.value ?? '').trim() === '✓' ? '✗' : '✓';
    setEditValue(newVal);
    correctField(jobId, field.label, newVal).then(
      () => onCorrected(field.label, newVal),
      (e) => console.error('Toggle checkbox failed:', e),
    );
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await correctField(jobId, field.label, editValue);
      onCorrected(field.label, editValue);
      setEditing(false);
    } catch (e) {
      console.error('Save correction failed:', e);
      alert('Failed to save correction. Please try again.');
    }
    setSaving(false);
  };

  const handleCancel = () => {
    setEditValue(field.value ?? '');
    setEditing(false);
  };

  return (
    <div
      onClick={!editing ? onClick : undefined}
      style={{
        padding: '10px 12px',
        borderRadius: 'var(--radius-lg)',
        border: `1px solid ${
          isCorrected ? 'var(--color-success-border)' : isSelected ? 'var(--color-primary)' : lowConfidence ? 'var(--color-warning-border)' : 'var(--color-border)'
        }`,
        background: isCorrected ? 'var(--color-success-light)' : isSelected ? 'var(--color-primary-light)' : lowConfidence ? 'var(--color-warning-light)' : 'var(--color-surface)',
        cursor: editing ? 'default' : 'pointer',
        transition: 'border-color var(--transition-fast), background var(--transition-fast), box-shadow var(--transition-fast)',
        boxShadow: isSelected ? '0 0 0 1px rgba(37,99,235,0.15)' : 'var(--shadow-xs)',
      }}
      onMouseEnter={(e) => { if (!isSelected && !editing) e.currentTarget.style.background = 'var(--color-surface-hover)'; }}
      onMouseLeave={(e) => { if (!isSelected && !editing) e.currentTarget.style.background = isCorrected ? 'var(--color-success-light)' : 'var(--color-surface)'; }}
    >
      {/* ── Header: label + badge + edit + page ───────────────────── */}
      <div style={{ fontSize: FONT_BASE, color: 'var(--color-text-secondary)', marginBottom: 2, display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 4, flexWrap: 'wrap' }}>
        <span style={{ fontWeight: 500 }}>{field.label}</span>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
          {prov && (
            <span style={{ fontSize: 13, color: prov.color, fontWeight: 600 }}>
              {prov.label}
            </span>
          )}
          <span style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>p.{field.page}</span>
          {!editing && !checkbox && (
            <button
              onClick={(e) => { e.stopPropagation(); setEditing(true); }}
              style={{
                padding: '4px 10px',
                border: `1px solid ${lowConfidence ? 'var(--color-warning)' : 'var(--color-border-hover)'}`,
                borderRadius: 'var(--radius-sm)',
                background: lowConfidence ? 'var(--color-warning-light)' : 'var(--color-surface)',
                cursor: 'pointer',
                fontSize: 13,
                fontWeight: 600,
                color: lowConfidence ? 'var(--color-warning-dark)' : 'var(--color-text-secondary)',
                transition: 'all var(--transition-fast)',
              }}
            >
              ✎ Edit
            </button>
          )}
        </div>
      </div>

      {/* ── Value / Edit input ──────────────────────────────────── */}
      {editing && !checkbox ? (
        <div onClick={(e) => e.stopPropagation()} style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <input
            value={editValue}
            onChange={(e) => setEditValue(e.target.value)}
            style={{
              padding: '8px 10px',
              borderRadius: 'var(--radius-sm)',
              border: '2px solid var(--color-primary)',
              fontSize: FONT_BASE,
              width: '100%',
              boxSizing: 'border-box',
              outline: 'none',
              boxShadow: '0 0 0 3px rgba(37,99,235,0.1)',
            }}
            autoFocus
          />
          <div style={{ display: 'flex', gap: 4 }}>
            <button
              onClick={handleSave}
              disabled={saving}
              style={{
                padding: '6px 14px',
                border: 'none',
                borderRadius: 'var(--radius-sm)',
                background: 'var(--color-primary)',
                color: '#fff',
                cursor: 'pointer',
                fontSize: 14,
                fontWeight: 600,
                transition: 'all var(--transition-fast)',
              }}
            >
              {saving ? 'Saving...' : 'Save'}
            </button>
            <button
              onClick={handleCancel}
              style={{
                padding: '6px 14px',
                border: '1px solid var(--color-border-hover)',
                borderRadius: 'var(--radius-sm)',
                background: 'var(--color-surface)',
                cursor: 'pointer',
                fontSize: 14,
                color: 'var(--color-text-tertiary)',
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <>
          <div style={{ fontSize: FONT_BASE, fontWeight: 600, color: 'var(--color-text)', marginBottom: 4, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            {field.original_value && (
              <span style={{ textDecoration: 'line-through', color: 'var(--color-text-muted)', fontWeight: 400, fontSize: 14 }}>
                {field.original_value}
              </span>
            )}
            {field.value != null && field.value !== '' ? <CheckboxDisplay value={field.value} /> : <span style={{ color: 'var(--color-text-muted)', fontStyle: 'italic' }}>empty</span>}
            <span style={{ fontSize: 12, fontWeight: 600, color: pill.color, background: pill.bg, padding: '2px 8px', borderRadius: 999 }}>
              {field.confidence}%
            </span>
          </div>

          <ConfidenceBar confidence={field.confidence} />

          {checkbox && (
            <div style={{ marginTop: 4, display: 'flex', gap: 6 }}>
              <button
                onClick={(e) => { e.stopPropagation(); toggleCheckbox(); }}
                style={{
                  padding: '6px 12px', fontSize: 14, fontWeight: 600,
                  border: '1px solid var(--color-border-hover)', borderRadius: 'var(--radius-sm)',
                  background: 'var(--color-surface)', color: 'var(--color-text-tertiary)', cursor: 'pointer',
                  transition: 'all var(--transition-fast)',
                }}
              >
                Toggle ✓/✗
              </button>
            </div>
          )}

          {/* ── Badges and metadata ─────────────────────────────── */}
          <div style={{ display: 'flex', gap: 10, marginTop: 4, flexWrap: 'wrap', alignItems: 'center' }}>
            {badge && (
              <span style={{ fontSize: 13, color: badge.color, fontWeight: 600 }}>
                {badge.label}
              </span>
            )}
            {field.needs_clarification && (
              <span style={{ fontSize: 13, color: 'var(--color-danger)', fontWeight: 600 }}>
                Needs review
              </span>
            )}
            {field.bbox && (
              <span style={{ fontSize: 13, color: 'var(--color-label)' }}>📍 Label</span>
            )}
            {field.value_bbox && (
              <span style={{ fontSize: 13, color: 'var(--color-value)' }}>📍 Value</span>
            )}
          {field.bbox && (
            <span style={{ fontSize: 12, color: 'var(--color-text-muted)', fontFamily: 'var(--font-mono)' }}>
              y={field.bbox[1]}
            </span>
          )}
          </div>

          {/* ── Reason for low confidence ────────────────────────── */}
          {field.reason && (
            <div style={{
              marginTop: 6, padding: '6px 10px',
              background: 'var(--color-warning-light)', borderRadius: 'var(--radius-sm)',
              border: '1px solid var(--color-warning-border)',
              fontSize: 14, color: 'var(--color-warning-dark)',
              lineHeight: 1.5,
            }}>
              ⚠ {field.reason}
            </div>
          )}

          {/* ── Verification note ────────────────────────────────── */}
          {field.verification_note && field.verification_note !== 'High confidence, auto-accepted' && (
            <div style={{
              marginTop: 4, fontSize: 14, color: 'var(--color-text-secondary)',
              fontStyle: 'italic',
            }}>
              {field.verification_note}
            </div>
          )}
        </>
      )}
    </div>
  );
}
