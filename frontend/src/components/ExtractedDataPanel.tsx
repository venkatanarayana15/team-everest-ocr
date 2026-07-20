import { useState, useCallback, useMemo, useRef } from 'react';
import type { Field, Section } from '../types';
import { resolveHierarchy, schemaFieldType, mutexGroupFor, mutexOptionName, mutexMembersOfStem, radioGroupChildrenOf, optionsForLabel } from '../utils/schemaHierarchy';

// ── Helpers ─────────────────────────────────────────────────────────────────

const TABLE_ROW_RE = /^(.+?)\s*[—–-]\s*Row\s+(\d+)\s*[—–-]\s*(.+)$/;
const CHECKBOX_VALS = new Set(['yes', 'no', 'true', 'false', '✓', '✗', '?']);

type Bbox = [number, number, number, number];

// Union of a group's option boxes → one region covering the whole question block.
function unionBbox(fields: Field[]): Bbox | null {
  const boxes: Bbox[] = [];
  for (const f of fields) {
    if (f.bbox) boxes.push(f.bbox as Bbox);
    if (f.value_bbox) boxes.push(f.value_bbox as Bbox);
  }
  if (boxes.length === 0) return null;
  return [
    Math.min(...boxes.map(b => b[0])),
    Math.min(...boxes.map(b => b[1])),
    Math.max(...boxes.map(b => b[2])),
    Math.max(...boxes.map(b => b[3])),
  ];
}

// The question LABEL is printed above the first option row, but the form data only
// carries coordinates for the option boxes. To map the question itself in blue,
// extend the union's top upward by a margin so the label line is enclosed.
const QUESTION_LABEL_PAD = 50;
function questionRegion(fields: Field[]): Bbox | null {
  const u = unionBbox(fields);
  if (!u) return null;
  return [u[0], Math.max(0, u[1] - QUESTION_LABEL_PAD), u[2], u[3]];
}

const isYesVal = (v: string | null | undefined): boolean =>
  ['yes', 'true', '✓'].includes((v ?? '').trim().toLowerCase());

// Collapse a single-select radio group's member fields into one synthetic Field
// rendered exactly like 8.2 (one row, inline radios, click highlights the whole
// question region). `stem` is the question label; `nameOf` strips the stem to an
// option display name.
function buildRadioSyntheticField(
  stem: string,
  memberFields: Field[],
  nameOf: (memberLabel: string) => string,
  specifyChildren: Field[] = [],
): Field {
  const selected = memberFields.find(c => isYesVal(c.value));
  const union = unionBbox(memberFields);
  // Blue = the WHOLE question region (label + options); Green = only the
  // selected answer(s), so the question label area is mapped in blue and the
  // chosen answer(s) in green (mirrors a single-field radio like 8.2).
  const answerUnion = unionBbox(memberFields.filter(c => isYesVal(c.value)));
  const base = memberFields[0];
  return {
    label: stem,
    value: selected ? nameOf(selected.label) : '',
    confidence: selected ? selected.confidence
      : (memberFields.reduce((s, c) => s + (c.confidence || 0), 0) / Math.max(memberFields.length, 1)),
    page: base.page,
    section_number: base.section_number,
    // Union of all member boxes (extended upward to enclose the question label)
    // → clicking maps the WHOLE question region in blue (label) + green (value).
    bbox: questionRegion(memberFields),
    value_bbox: answerUnion,
    needs_clarification: memberFields.some(c => c.needs_clarification),
    reason: selected?.reason ?? null,
    is_verified: memberFields.every(c => c.is_verified),
    verifier_confidence: selected?.verifier_confidence ?? null,
    verification_note: selected?.verification_note ?? null,
    extracted_by: selected?.extracted_by ?? null,
    verified_by: selected?.verified_by ?? null,
    original_value: selected?.original_value ?? '',
    is_edited: memberFields.some(c => c.is_edited),
    parent_label: stem,
    field_type: 'radio',
    mutexMembers: memberFields,
    specifyChildren: specifyChildren.length ? specifyChildren : undefined,
  };
}

function isCheckbox(field: Field): boolean {
  if (field.field_type === 'checkbox') return true;
  return CHECKBOX_VALS.has((field.value ?? '').trim().toLowerCase());
}

function valuesEqual(a: string | null | undefined, b: string | null | undefined): boolean {
  const va = (a ?? '').trim();
  const vb = (b ?? '').trim();
  if (va === vb) return true;
  if (CHECKBOX_VALS.has(va.toLowerCase()) || CHECKBOX_VALS.has(vb.toLowerCase())) {
    return va.toLowerCase() === vb.toLowerCase();
  }
  return false;
}

function confidenceColor(c: number): string {
  if (c >= 0.8) return '#16a34a';
  if (c >= 0.5) return '#d97706';
  return '#dc2626';
}

function confidenceLabel(c: number): string {
  return `${c}%`;
}

function checkboxDisplay(val: string | null): { icon: string; color: string } {
  const v = (val ?? '').trim().toLowerCase();
  if (v === 'yes' || v === 'true' || v === '✓') return { icon: '✓', color: '#16a34a' };
  if (v === 'no' || v === 'false' || v === '✗') return { icon: '✗', color: '#dc2626' };
  return { icon: '?', color: '#94a3b8' };
}

function parseDateToYmd(val: string | null): string {
  if (!val) return '';
  const v = val.trim();
  
  const isoMatch = v.match(/(\d{4})-(\d{2})-(\d{2})/);
  if (isoMatch) return isoMatch[0];
  
  // Try DD/MM/YYYY, DD-MM-YYYY, DD.MM.YYYY (with 2 or 4 digit year)
  const slashMatch = v.match(/(\d{1,2})[\/\-\.](\d{1,2})[\/\-\.](\d{4}|\d{2})/);
  if (slashMatch) {
    const dd = slashMatch[1].padStart(2, '0');
    const mm = slashMatch[2].padStart(2, '0');
    let yy = slashMatch[3];
    if (yy.length === 2) yy = '20' + yy;
    return `${yy}-${mm}-${dd}`;
  }
  
  // Try DD-MMM-YYYY, DD MMM YYYY, etc.
  const dashMatch = v.match(/(\d{1,2})[\/\-\s]+([a-zA-Z]{3,})[\/\-\s]+(\d{4}|\d{2})/);
  if (dashMatch) {
    const months = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'];
    const monthIndex = months.findIndex(m => dashMatch[2].toLowerCase().startsWith(m));
    if (monthIndex !== -1) {
      const mm = String(monthIndex + 1).padStart(2, '0');
      const dd = dashMatch[1].padStart(2, '0');
      let yy = dashMatch[3];
      if (yy.length === 2) yy = '20' + yy;
      return `${yy}-${mm}-${dd}`;
    }
  }
  
  return '';
}

function formatYmdToDdMmmYyyy(ymd: string): string {
  if (!ymd) return '';
  const match = ymd.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return ymd;
  const months = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];
  const monthName = months[parseInt(match[2], 10) - 1] || 'JAN';
  return `${match[3]}-${monthName}-${match[1]}`;
}

function getRadioOptions(label: string): string[] | null {
  const lbl = label.toLowerCase();
  // Single-select radio groups collapsed into a single question (mutex OR parent_label-based,
  // e.g. 3.1, 3.5, 4.3, 3.2, 3.3). Derive options from the schema so they always render.
  const members = radioGroupChildrenOf(label) ?? mutexMembersOfStem(label);
  if (members) {
    const stem = label;
    return members.map(m => mutexOptionName(m, stem));
  }
  // Single radio field defined directly with an options array (e.g. 8.2, 4.4, 4.6).
  const opts = optionsForLabel(label);
  if (opts) return opts;
  if (lbl.includes('1.3 gender')) {
    return ['Male', 'Female', 'Others'];
  }
  if (lbl.includes('3.5 bathroom')) {
    return ['Separate', 'Common for Apartment', 'None', 'N/A'];
  }
  if (lbl.includes('2.1 family status')) {
    return ['Having both parents', 'Single Parent', 'Parentless'];
  }
  if (lbl.includes('3.1 house ownership')) {
    return ['Own', 'Rented'];
  }
  if (
    lbl.includes('do you own any other assets') ||
    lbl.includes('apart from your job') ||
    lbl.includes('do you have any loans') ||
    lbl.includes('does the student have any health issues') ||
    lbl.includes('ready to send your son/daughter') ||
    lbl.includes('photograph kept at home')
  ) {
    return ['Yes', 'No'];
  }
  if (lbl.includes('training program within 15 km')) {
    return ['Yes', 'No', 'Maybe'];
  }
  if (lbl.includes('8.2 will you recommend')) {
    return ['Yes', 'No', 'Not Sure'];
  }
  if (lbl.includes('4.5 income type')) {
    return ['Monthly', 'Daily', 'Weekly', 'Ad-Hoc'];
  }
  return null;
}

// ── Sub-components ──────────────────────────────────────────────────────────

function Chevron({ expanded }: { expanded: boolean }) {
  return (
    <span style={{
      display: 'inline-block',
      transition: 'transform 0.15s',
      transform: expanded ? 'rotate(90deg)' : 'rotate(0deg)',
      fontSize: 10,
      color: '#94a3b8',
      marginRight: 6,
    }}>
      ▶
    </span>
  );
}

function Badge({ children, color }: { children: string; color: string }) {
  return (
    <span style={{
      display: 'inline-block',
      padding: '1px 6px',
      borderRadius: 4,
      fontSize: 10,
      fontWeight: 600,
      color: '#fff',
      background: color,
      whiteSpace: 'nowrap',
    }}>
      {children}
    </span>
  );
}

function InlineEditor({
  value, onSave, onCancel, multiline,
}: {
  value: string | null;
  onSave: (v: string) => void;
  onCancel: () => void;
  multiline?: boolean;
}) {
  const [editVal, setEditVal] = useState(value ?? '');

  const handleKey = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); onSave(editVal); }
    if (e.key === 'Escape') onCancel();
  }, [editVal, onSave, onCancel]);

  const baseStyle: React.CSSProperties = {
    width: '100%',
    border: '2px solid var(--color-primary)',
    borderRadius: 'var(--radius-sm)',
    padding: '2px 6px',
    fontSize: 13,
    fontFamily: 'var(--font-sans)',
    outline: 'none',
    boxSizing: 'border-box',
    background: 'var(--color-surface)',
    boxShadow: '0 0 0 3px rgba(37,99,235,0.1)',
  };

  if (multiline) {
    return (
      <textarea
        autoFocus
        value={editVal}
        onChange={e => setEditVal(e.target.value)}
        onKeyDown={handleKey}
        onBlur={() => onSave(editVal)}
        rows={6}
        style={{ ...baseStyle, resize: 'vertical', minHeight: 120, fontFamily: 'var(--font-sans)', lineHeight: 1.5, padding: '6px 8px' }}
      />
    );
  }

  return (
    <input
      autoFocus
      value={editVal}
      onChange={e => setEditVal(e.target.value)}
      onKeyDown={handleKey}
      onBlur={() => onSave(editVal)}
      style={baseStyle}
    />
  );
}

function CheckboxIcon({ value }: { value: string | null }) {
  const { icon, color } = checkboxDisplay(value);
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
      width: 18, height: 18, borderRadius: 3,
      background: color === '#16a34a' ? '#dcfce7' : color === '#dc2626' ? '#fef2f2' : '#f1f5f9',
      color, fontWeight: 700, fontSize: 12,
      cursor: 'pointer', userSelect: 'none',
    }}>
      {icon}
    </span>
  );
}

function FieldValue({
  field, isSelected, onSelect, onValueChange, onFieldUpdate,
}: {
  field: Field;
  isSelected: boolean;
  onSelect: () => void;
  onValueChange: (newVal: string) => void;
  onFieldUpdate: (f: Field, newVal: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [hovered, setHovered] = useState(false);

  const handleStartEdit = useCallback((e?: React.MouseEvent) => {
    e?.stopPropagation();
    setEditing(true);
  }, []);

  const handleSave = useCallback((v: string) => {
    onValueChange(v);
    setEditing(false);
  }, [onValueChange]);

  const handleCancel = useCallback(() => {
    setEditing(false);
  }, []);

  const isCheckboxField = isCheckbox(field);
  const wasCorrected = field.is_edited === true;

  // Multi-select radios (e.g. 2.1, 4.4, 4.6, 8.2) render as checkboxes, not radios.
  const isMultiSelect =
    field.field_type === 'checkbox' ||
    field.label.includes('2.1 ') ||
    /^(4\.4 |4\.6 |8\.2 )/.test(field.label);

  const containerStyle: React.CSSProperties = {
    padding: '12px 16px',
    borderBottom: '1px solid var(--color-border)',
    cursor: 'pointer',
    background: isSelected ? 'var(--color-primary-light)' : wasCorrected ? 'var(--color-success-light)' : hovered ? 'var(--color-surface-hover)' : 'transparent',
    fontFamily: 'var(--font-sans)',
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
    transition: 'background var(--transition-fast)',
  };

  const labelStyle: React.CSSProperties = {
    fontSize: 13,
    fontWeight: 700,
    color: '#000000', // Absolute black color for questions
    display: 'flex',
    alignItems: 'flex-start',
    gap: 6,
    flexWrap: 'wrap',
    lineHeight: 1.4,
  };

  const editBtnStyle: React.CSSProperties = {
    border: 'none',
    background: 'transparent',
    cursor: 'pointer',
    fontSize: 13,
    color: 'var(--color-text-muted)',
    padding: '1px 4px',
    borderRadius: 3,
    lineHeight: 1,
    flexShrink: 0,
  };

  return (
    <div
      style={containerStyle}
      onClick={onSelect}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <div style={labelStyle}>
        <span style={{ color: '#000000', fontWeight: 700 }}>{field.label}</span>
        <Badge color={confidenceColor(field.confidence)}>
          {confidenceLabel(field.confidence)}
        </Badge>
        {wasCorrected && <Badge color="var(--color-success)">edited</Badge>}
        {field.needs_clarification && (
          <span style={{ color: 'var(--color-danger)', fontSize: 10 }}>⚠</span>
        )}
      </div>

      {(() => {
        const lbl = field.label.toLowerCase();
        // Only treat as a radio group when the backend marks it radio (single source of truth).
        const radioOpts = field.field_type === 'radio' ? getRadioOptions(field.label) : null;

        let valueContent: React.ReactNode = null;
        let isSpecial = false;

        if (lbl.includes('date of visit')) {
          isSpecial = true;
          const ymd = parseDateToYmd(field.value);
          let displayVal = field.value ?? '';
          if (ymd) {
            const parts = ymd.split('-');
            if (parts.length === 3) displayVal = `${parts[2]}-${parts[1]}-${parts[0]}`;
          }
          valueContent = (
            <div onMouseDown={(e) => e.stopPropagation()} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>📅</span>
              <input
                type="text"
                placeholder="DD-MM-YYYY"
                defaultValue={displayVal}
                onBlur={(e) => {
                  const val = e.target.value.replace(/\D/g, '').slice(0, 8);
                  if (!val) { onValueChange(''); return; }
                  let formatted = val;
                  if (val.length >= 5) formatted = `${val.slice(0, 2)}-${val.slice(2, 4)}-${val.slice(4)}`;
                  else if (val.length >= 3) formatted = `${val.slice(0, 2)}-${val.slice(2)}`;
                  onValueChange(formatted);
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
                }}
                onFocus={(e) => e.target.select()}
                onClick={(e) => e.stopPropagation()}
                style={{
                  padding: '6px 10px',
                  borderRadius: 6,
                  border: '1px solid var(--color-border)',
                  background: 'var(--color-surface)',
                  color: 'var(--color-text)',
                  fontSize: 14,
                  outline: 'none',
                  fontFamily: 'var(--font-mono)',
                  width: 120,
                }}
              />
            </div>
          );
        } else if (radioOpts) {
          isSpecial = true;
          valueContent = (
            <div 
              style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginTop: 4 }}
              onClick={(e) => e.stopPropagation()}
            >
              {radioOpts.map(opt => {
                const isChecked = (field.value ?? '').trim().toLowerCase() === opt.toLowerCase();
                return (
                  <label 
                    key={opt} 
                    style={{ 
                      display: 'inline-flex', 
                      alignItems: 'center', 
                      gap: 4, 
                      fontSize: 12, 
                      color: 'var(--color-text)',
                      cursor: 'pointer',
                      userSelect: 'none',
                    }}
                  >
                    <input
                      type={isMultiSelect ? "checkbox" : "radio"}
                      name={field.label}
                      checked={isChecked}
                      onChange={() => {
                        if (isMultiSelect && isChecked) onValueChange('');
                        else onValueChange(opt);
                      }}
                    />
                    {opt}
                  </label>
                );
              })}
              {/* "Others (specify)" style follow-ups: shown only when the matching option is selected */}
              {(field.specifyChildren ?? [])
                .filter(sf => (sf.parent_option_label ?? '').trim().toLowerCase() === (field.value ?? '').trim().toLowerCase())
                .map(sf => (
                  <SpecifyInput key={sf.label} field={sf} onFieldClick={onSelect} onFieldUpdate={onFieldUpdate} />
                ))}
            </div>
          );
        } else if (isCheckboxField && !field.label.startsWith('7.1 ') && !field.label.startsWith('6.1 ')) {
          isSpecial = true;
          const fv = (field.value ?? '').trim().toLowerCase();
          const isChecked = fv === 'yes' || fv === 'true' || fv === '✓';
          valueContent = (
            <div 
              onClick={(e) => { e.stopPropagation(); onValueChange(isChecked ? 'no' : 'yes'); }}
              style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 2, cursor: 'pointer' }}
            >
              <CheckboxIcon value={field.value} />
              <span style={{ fontSize: 13, color: 'var(--color-text)' }}>{field.value ?? 'empty'}</span>
            </div>
          );
        } else if (editing) {
          valueContent = (
            <div style={{ flex: 1 }}>
              <InlineEditor value={field.value} onSave={handleSave} onCancel={handleCancel} multiline={field.label.includes('8.1') || field.label.includes('8.3')} />
            </div>
          );
        } else {
          valueContent = (
            <div
              onDoubleClick={handleStartEdit}
              style={{
                flex: 1,
                fontSize: 14,
                color: 'var(--color-text)',
                lineHeight: 1.5,
                padding: '2px 0',
                minHeight: 20,
                wordBreak: 'break-word',
                display: 'flex',
                alignItems: 'center',
                gap: 8,
              }}
            >
              <span style={{ flex: 1, fontSize: 14, fontWeight: 500, color: field.value ? 'var(--color-primary-dark)' : 'var(--color-text-placeholder)', borderBottom: '1px solid var(--color-border-light)', paddingBottom: 2, minHeight: 20 }}>
                {field.value || <span style={{ fontStyle: 'italic' }}>empty</span>}
              </span>
            </div>
          );
        }

        return (
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8, width: '100%', marginTop: 4 }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              {valueContent}
            </div>
            {!editing && isSpecial && (
              <button
                onClick={handleStartEdit}
                style={editBtnStyle}
                title="Edit value"
                onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--color-border)'; e.currentTarget.style.color = 'var(--color-text-tertiary)'; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--color-text-muted)'; }}
              >
                ✎
              </button>
            )}
          </div>
        );
      })()}

      {field.reason && (
        <div style={{ fontSize: 10, color: 'var(--color-text-muted)', marginTop: 2 }}>
          {field.reason}
        </div>
      )}
    </div>
  );
}

function FieldRow({
  field, isSelected, onSelect, onValueChange, onFieldUpdate,
}: {
  field: Field;
  isSelected: boolean;
  onSelect: () => void;
  onValueChange: (newVal: string) => void;
  onFieldUpdate: (f: Field, newVal: string) => void;
}) {
  const match = field.label.match(TABLE_ROW_RE);
  if (match) {
    const [, section, rowNum, column] = match;
    const displayLabel = `${section} — Row ${rowNum} — ${column}`;
    return (
      <FieldValue
        field={{ ...field, label: displayLabel }}
        isSelected={isSelected}
        onSelect={onSelect}
        onValueChange={onValueChange}
        onFieldUpdate={onFieldUpdate}
      />
    );
  }
  return (
    <FieldValue
      field={field}
      isSelected={isSelected}
      onSelect={onSelect}
      onValueChange={onValueChange}
      onFieldUpdate={onFieldUpdate}
    />
  );
}

function TableCell({ field, isSelected, onFieldClick, onFieldUpdate }: {
  field: Field;
  isSelected: boolean;
  onFieldClick: (f: Field) => void;
  onFieldUpdate: (f: Field, newVal: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [hovered, setHovered] = useState(false);
  const wasCorrected = field.is_edited === true;
  const cb = isCheckbox(field);
  const { icon, color } = cb ? checkboxDisplay(field.value) : { icon: '', color: '' };

  const handleSave = useCallback((v: string) => {
    onFieldUpdate(field, v);
    setEditing(false);
  }, [field, onFieldUpdate]);

  if (editing) {
    return (
      <td style={{ padding: '4px 6px', borderBottom: '1px solid #f1f5f9' }}>
        <InlineEditor value={field.value} onSave={handleSave} onCancel={() => setEditing(false)} />
      </td>
    );
  }

  return (
    <td
      onClick={() => onFieldClick(field)}
      onDoubleClick={(e) => { e.stopPropagation(); setEditing(true); }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        padding: '4px 6px',
        cursor: 'pointer',
        background: isSelected ? 'var(--color-primary-light)' : wasCorrected ? 'var(--color-success-light)' : 'transparent',
        borderRadius: 'var(--radius-sm)',
      }}
    >
      {cb ? (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
          <CheckboxIcon value={field.value} />
          <span>{field.value}</span>
        </span>
      ) : (
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ flex: 1, color: 'var(--color-text)' }}>
            {field.value || <span style={{ color: 'var(--color-text-placeholder)', fontStyle: 'italic' }}>empty</span>}
          </span>
          {hovered && (
            <button
              onClick={(e) => { e.stopPropagation(); setEditing(true); }}
              style={{
                border: 'none', background: 'transparent', cursor: 'pointer',
                fontSize: 12, color: 'var(--color-text-muted)', padding: '1px 3px', borderRadius: 2, flexShrink: 0,
              }}
              title="Edit value"
              onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--color-border)'; e.currentTarget.style.color = 'var(--color-text-tertiary)'; }}
              onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--color-text-muted)'; }}
            >
              ✎
            </button>
          )}
        </div>
      )}
    </td>
  );
}

function TableView({
  fields, allFields, selectedField, onFieldClick, onFieldUpdate,
}: {
  fields: Field[];
  allFields: Field[];
  selectedField: Field | null;
  onFieldClick: (f: Field) => void;
  onFieldUpdate: (f: Field, newVal: string) => void;
}) {
  if (fields.length === 0) return null;

  const columns = new Set<string>();
  const rows = new Map<string, Map<string, Field>>();
  for (const f of fields) {
    const match = f.label.match(TABLE_ROW_RE);
    if (match) {
      const [, section, rowNum, column] = match;
      const rowKey = `${section}|${rowNum}`;
      columns.add(column);
      if (!rows.has(rowKey)) rows.set(rowKey, new Map());
      rows.get(rowKey)!.set(column, f);
    } else if (f.label.includes('4.4.1') || f.label.includes('4.3.1') || f.label.includes('4.6.1')) {
      // Special case for tables that might not have 'Row N'
      const parts = f.label.split(/ — | - | – /);
      if (parts.length >= 2) {
        const column = parts.slice(1).join(' ').trim();
        const prefix = parts[0].trim(); // e.g. 4.4.1 Income Sources
        const rowKey = `${prefix}|1`;
        columns.add(column);
        if (!rows.has(rowKey)) rows.set(rowKey, new Map());
        rows.get(rowKey)!.set(column, f);
      }
    }
  }

  if (columns.size === 0 || rows.size === 0) {
    return (
      <div style={{ padding: '4px 0' }}>
        {fields.map(f => (
          <FieldRow key={f.label} field={f} isSelected={selectedField?.label === f.label} onSelect={() => onFieldClick(f)} onValueChange={(v) => onFieldUpdate(f, v)} onFieldUpdate={onFieldUpdate} />
        ))}
      </div>
    );
  }

  const colArr = Array.from(columns);
  const firstMatch = fields[0]?.label.match(TABLE_ROW_RE);
  let tableTitle = firstMatch ? firstMatch[1] : '';
  if (!tableTitle) {
    const label = fields[0]?.label;
    if (label) {
      const parts = label.split(/ — | - | – /);
      if (parts.length >= 2) {
        tableTitle = parts.slice(0, -1).join(' — ');
      }
    }
  }

  // Find the actual table_header field across all available fields
  const tableHeaderLabel = fields[0]?.parent_label || tableTitle;
  // Search for the actual table_header field in the full fields array (passed as prop)
  // We look for a field whose label matches the table header label
  let tableHeaderField: Field | undefined;
  if (tableHeaderLabel) {
    tableHeaderField = allFields.find(f => f.label === tableHeaderLabel && (f.field_type === 'table_header' || f.field_type === undefined));
    if (!tableHeaderField) {
      tableHeaderField = allFields.find(f => f.label === tableHeaderLabel);
    }
  }

  return (
    <div style={{ padding: '8px 12px 16px 12px' }}>
      {tableTitle && (
        <div 
          style={{ 
            fontSize: 13, fontWeight: 700, color: '#000000', marginBottom: 8, 
            cursor: 'pointer',
            padding: '4px 8px',
            borderRadius: 'var(--radius-sm)',
            background: 'var(--color-bg)',
            border: '1px solid transparent',
            transition: 'background var(--transition-fast), border-color var(--transition-fast)',
          }}
          onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'var(--color-border)'; e.currentTarget.style.background = 'var(--color-surface)'; }}
          onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'transparent'; e.currentTarget.style.background = 'var(--color-bg)'; }}
          onClick={() => {
            const src = tableHeaderField || fields[0];
            // Prefer the header's own spatial grounding; otherwise fall back to the
            // union of the table's cell boxes so clicking the title still maps to a
            // real region on the PDF (mirrors CheckboxGroupView parent behaviour).
            const srcBbox = src?.bbox ?? null;
            const srcVBbox = src?.value_bbox ?? null;
            const union = srcBbox || srcVBbox ? null : questionRegion(fields);
            // Green = only the cells that actually contain an answer.
            const answeredUnion = unionBbox(
              fields.filter(f => (f.value ?? '').trim() !== '' && (f.value ?? '').trim().toLowerCase() !== 'n/a')
            );
            const targetField: Field = {
              label: tableHeaderLabel,
              parent_label: tableHeaderLabel,
              page: src?.page ?? 1,
              bbox: srcBbox ?? union,
              value_bbox: srcVBbox ?? answeredUnion,
              value: '',
              confidence: 0,
              section_number: src?.section_number ?? null,
              needs_clarification: false,
              reason: null,
              is_verified: false,
              verifier_confidence: null,
              verification_note: null,
              extracted_by: null,
              verified_by: null,
              original_value: '',
              is_edited: false,
            };
            onFieldClick(targetField);
          }}
          title="Click to locate on PDF"
        >
          {tableTitle}
        </div>
      )}
      <div style={{ 
        overflowX: 'auto', 
        border: '1px solid var(--color-border)', 
        borderRadius: 'var(--radius-md)',
        background: 'var(--color-surface)',
        boxShadow: '0 1px 3px rgba(0,0,0,0.05)'
      }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ background: 'var(--color-surface-alt)' }}>
              <th style={{ textAlign: 'left', padding: '8px 12px', borderBottom: '2px solid var(--color-border)', color: '#000000', fontWeight: 700, whiteSpace: 'nowrap' }}>#</th>
              {colArr.map(col => (
                <th key={col} style={{ textAlign: 'left', padding: '8px 12px', borderBottom: '2px solid var(--color-border)', color: '#000000', fontWeight: 700, whiteSpace: 'nowrap' }}>{col}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {Array.from(rows.entries()).map(([rowKey, cols], rowIdx) => {
              const [, rowNum] = rowKey.split('|');
              const isEven = rowIdx % 2 === 0;
              return (
                <tr key={rowKey} style={{ background: isEven ? 'transparent' : 'var(--color-surface-alt)', borderBottom: '1px solid var(--color-border-light)' }}>
                  <td style={{ padding: '8px 12px', color: 'var(--color-text-muted)', fontSize: 12, whiteSpace: 'nowrap', verticalAlign: 'top', fontWeight: 500 }}>{rowNum}</td>
                  {colArr.map(col => {
                    const f = cols.get(col);
                    if (!f) return <td key={col} style={{ padding: '8px 12px' }}><span style={{ color: 'var(--color-text-placeholder)', fontStyle: 'italic' }}>—</span></td>;
                    return (
                      <TableCell
                        key={col}
                        field={f}
                        isSelected={selectedField?.label === f.label}
                        onFieldClick={onFieldClick}
                        onFieldUpdate={onFieldUpdate}
                      />
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function CheckboxItem({ field, isSelected, onFieldClick, onFieldUpdate }: {
  field: Field;
  isSelected: boolean;
  onFieldClick: (f: Field) => void;
  onFieldUpdate: (f: Field, newVal: string) => void;
}) {
  const [cbEdit, setCbEdit] = useState(false);
  const [cbHover, setCbHover] = useState(false);
  const { icon, color } = checkboxDisplay(field.value);
  const wasCorrected = field.is_edited === true;

  if (cbEdit) {
    return (
      <div style={{ padding: '4px 10px', fontSize: 12 }}>
        <InlineEditor value={field.value} onSave={(v) => { onFieldUpdate(field, v); setCbEdit(false); }} onCancel={() => setCbEdit(false)} />
      </div>
    );
  }

  return (
    <div
      onClick={() => onFieldClick(field)}
      onDoubleClick={(e) => { e.stopPropagation(); setCbEdit(true); }}
      onMouseEnter={() => setCbHover(true)}
      onMouseLeave={() => setCbHover(false)}
      style={{
        display: 'flex', alignItems: 'center', gap: 6,
        padding: '4px 10px',
        border: `1px solid ${isSelected ? 'var(--color-primary)' : wasCorrected ? 'var(--color-success-border)' : 'var(--color-border)'}`,
        borderRadius: 'var(--radius-md)',
        cursor: 'pointer',
        background: isSelected ? 'var(--color-primary-light)' : wasCorrected ? 'var(--color-success-light)' : 'var(--color-surface)',
        fontSize: 12,
        transition: 'border-color var(--transition-fast)',
      }}
    >
      <span style={{ color: '#000000', fontWeight: 700 }}>{field.label}</span>
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 3, color: 'var(--color-text)' }}>
          <CheckboxIcon value={field.value} />
            {field.value ?? 'empty'}
      </span>
      {cbHover && (
        <button
          onClick={(e) => { e.stopPropagation(); setCbEdit(true); }}
          style={{
            border: 'none', background: 'transparent', cursor: 'pointer',
            fontSize: 12, color: 'var(--color-text-muted)', padding: '1px 3px', borderRadius: 2,
          }}
          title="Edit value"
        >
          ✎
        </button>
      )}
    </div>
  );
}

// Inline editable text input shown for "Others (specify)" / option specify fields,
// only when the associated option is selected.
function SpecifyInput({ field, onFieldClick, onFieldUpdate }: {
  field: Field;
  onFieldClick: (f: Field) => void;
  onFieldUpdate: (f: Field, newVal: string) => void;
}) {
  const [hovered, setHovered] = useState(false);
  return (
    <div
      onClick={() => onFieldClick(field)}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: 'flex', alignItems: 'center', gap: 6, fontSize: 13,
        padding: '4px 0', background: hovered ? 'var(--color-surface-hover)' : 'transparent',
        borderRadius: 4, width: '100%',
      }}
    >
      <span style={{ color: 'var(--color-text-secondary)', flexShrink: 0 }}>(specify)</span>
      <input
        type="text"
        value={field.value ?? ''}
        placeholder="Please specify"
        onClick={(e) => { e.stopPropagation(); onFieldClick(field); }}
        onChange={(e) => onFieldUpdate(field, e.target.value)}
        style={{
          flex: 1,
          minWidth: 120,
          padding: '6px 10px',
          borderRadius: 6,
          border: '1px solid var(--color-border)',
          background: 'var(--color-surface)',
          color: 'var(--color-text)',
          fontSize: 13,
          fontFamily: 'var(--font-sans)',
          outline: 'none',
        }}
      />
    </div>
  );
}

function CheckboxGroupView({
  fields, selectedField, onFieldClick, onFieldUpdate,
  onBulkFieldUpdate,
}: {
  fields: Field[];
  selectedField: Field | null;
  onFieldClick: (f: Field) => void;
  onFieldUpdate: (f: Field, newVal: string) => void;
  onBulkFieldUpdate?: (updates: {field: Field, newVal: string}[]) => void;
}) {
  if (fields.length === 0) return null;

  // The block is built upstream from backend hierarchy metadata:
  // fields[0] is the parent/header question, the rest are its child options.
  const parentField = fields[0];
  const optionFields = fields.slice(1);
  const groupLabel = parentField.label;

  // Single-select when the parent (or any child) is a radio group; otherwise multi-select.
  const isSingleSelect = optionFields.some(f => f.field_type === 'radio') ||
    parentField.field_type === 'radio';

  // Derive the option display name from the child label relative to the parent label.
  const parentPrefix = groupLabel;
  const optionName = (label: string): string => {
    let name = label;
    for (const sep of [' — ', ' - ', ' – ']) {
      if (label.startsWith(parentPrefix + sep)) {
        name = label.slice((parentPrefix + sep).length);
        break;
      }
    }
    if (name === label) {
      const parts = label.split(/ — | - | – /);
      name = parts.slice(1).join(' — ') || label;
    }
    return name;
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', width: '100%' }}>
      <div
        style={{
          padding: '12px 16px',
          borderBottom: '1px solid var(--color-border)',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'stretch',
          gap: 8,
        }}
      >
        <label
          style={{
            fontSize: 13, fontWeight: 700, color: '#000000', userSelect: 'none', flex: 'none', lineHeight: 1.4,
            cursor: 'pointer',
            padding: '4px 8px',
            borderRadius: 'var(--radius-sm)',
            background: 'var(--color-bg)',
            border: '1px solid transparent',
            transition: 'background var(--transition-fast), border-color var(--transition-fast)',
          }}
          onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'var(--color-border)'; e.currentTarget.style.background = 'var(--color-surface)'; }}
          onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'transparent'; e.currentTarget.style.background = 'var(--color-bg)'; }}
          onClick={() => {
            // Blue = the WHOLE question region (union of all option boxes);
            // Green = only the CHECKED answer(s). The parent has no spatial
            // grounding (common for checkbox groups), so union the option boxes.
            const union = unionBbox(optionFields);
            const checkedUnion = unionBbox(
              optionFields.filter(f => ['yes', 'true', '✓'].includes((f.value ?? '').trim().toLowerCase()))
            );
            const navTarget: Field = {
              ...parentField,
              bbox: parentField.bbox ?? questionRegion(optionFields),
              value_bbox: parentField.value_bbox ?? checkedUnion,
            };
            onFieldClick(navTarget);
          }}
          title="Click to locate on PDF"
        >
          {groupLabel}
        </label>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16, flex: 1, alignItems: 'center' }}>
          {optionFields.map(f => {
            const optName = optionName(f.label);

            // "Others (specify)" style follow-up: render an inline text input, but
            // ONLY when the associated option (parent_option_label) is selected.
            const isSpecify = optName.toLowerCase().includes('specify');
            if (isSpecify) {
              const ownerLabel = (f.parent_option_label ?? '')
                .trim().replace(/[:\s]+$/, '').toLowerCase();
              const ownerField = ownerLabel
                ? optionFields.find(sib =>
                    optionName(sib.label).trim().replace(/[:\s]+$/, '').toLowerCase() === ownerLabel &&
                    sib.label !== f.label)
                : undefined;
              // If no owner mapping, fall back to showing when any "Others/Other" option is checked.
              const ownerChecked = ownerField
                ? ['yes', 'true', '✓'].includes((ownerField.value ?? '').trim().toLowerCase())
                : optionFields.some(sib => {
                    const n = optionName(sib.label).trim().replace(/[:\s]+$/, '').toLowerCase();
                    return (n === 'others' || n === 'other') &&
                      ['yes', 'true', '✓'].includes((sib.value ?? '').trim().toLowerCase());
                  });
              if (!ownerChecked) return null;
              return (
                <SpecifyInput
                  key={f.label}
                  field={f}
                  onFieldClick={onFieldClick}
                  onFieldUpdate={onFieldUpdate}
                />
              );
            }

            const fv = (f.value ?? '').trim().toLowerCase();
            const isChecked = fv === 'yes' || fv === 'true' || fv === '✓';
            const isItemSel = selectedField?.label === f.label;

            const toggleChecked = () => {
              onFieldClick(f);

              if (isSingleSelect && onBulkFieldUpdate) {
                const willCheck = !isChecked;
                if (willCheck) {
                  onBulkFieldUpdate(optionFields.map(sibling => ({
                    field: sibling,
                    newVal: sibling === f ? 'yes' : 'no',
                  })));
                } else {
                  onFieldUpdate(f, 'no');
                }
              } else {
                onFieldUpdate(f, isChecked ? 'no' : 'yes');
              }
            };

            return (
              <label
                key={f.label}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 6,
                  fontSize: 14,
                  cursor: 'pointer',
                  color: isItemSel ? 'var(--color-primary)' : 'var(--color-text)',
                  userSelect: 'none',
                }}
              >
                <input
                  type={isSingleSelect ? 'radio' : 'checkbox'}
                  name={groupLabel}
                  checked={isChecked}
                  onChange={() => toggleChecked()}
                  style={{ width: 14, height: 14, margin: 0 }}
                />
                {optName}
              </label>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// ── Main component ──────────────────────────────────────────────────────────

function fieldSortKey(f: Field): number[] {
  const m = f.label.match(/^(\d+(?:\.\d+)*)/);
  if (m) {
    return m[1].split('.').map(Number);
  }
  return [-1];
}

function fieldCompare(a: Field, b: Field): number {
  const ka = fieldSortKey(a);
  const kb = fieldSortKey(b);
  for (let i = 0; i < Math.max(ka.length, kb.length); i++) {
    const va = ka[i] ?? 0;
    const vb = kb[i] ?? 0;
    if (va !== vb) return va - vb;
  }
  return 0;
}

type UIBlock =
  | { type: 'field'; field: Field }
  | { type: 'table'; prefix: string; fields: Field[] }
  | { type: 'checkbox_group'; prefix: string; fields: Field[] };

interface SectionGroup {
  sectionNumber: number | null;
  sectionName: string;
  blocks: UIBlock[];
}

interface Props {
  fields: Field[];
  sections: Section[];
  selectedField: Field | null;
  onFieldClick: (field: Field) => void;
  onPageClick: (page: number) => void;
  currentPage: number;
  numPages: number;
  jobId: string;
  onFieldsUpdated: (fields: Field[]) => void;
  hideToolbar?: boolean;
}

export default function ExtractedDataPanel({
  fields, sections, selectedField, onFieldClick, onPageClick,
  currentPage, numPages, jobId, onFieldsUpdated, hideToolbar,
}: Props) {
  const [collapsedSections, setCollapsedSections] = useState<Set<number | null>>(new Set());

  // Keep latest fields in a ref so the value-change callbacks stay referentially
  // stable across renders (field array identity changes on every store update).
  const fieldsRef = useRef(fields);
  fieldsRef.current = fields;

  // Resolve hierarchy (parent_label / field_type) from the form schema so grouping is
  // correct even when the API payload omits that metadata. Memoized on the raw fields.
  const resolvedFields = useMemo(() => {
    const resolved = resolveHierarchy(fields);
    // Drop duplicate labels: keep the entry carrying real content (value/bbox) and
    // discard empty placeholder stubs (e.g. a header row with no bbox duplicated by
    // the data extractor on a different page).
    const byLabel = new Map<string, Field>();
    for (const f of resolved) {
      const cur = byLabel.get(f.label);
      if (!cur) { byLabel.set(f.label, f); continue; }
      const fHasData = !!((f.value ?? '').trim()) || f.bbox || f.value_bbox;
      const curHasData = !!((cur.value ?? '').trim()) || cur.bbox || cur.value_bbox;
      if (fHasData && !curHasData) byLabel.set(f.label, f);
    }
    return resolved.filter(f => byLabel.get(f.label) === f);
  }, [fields]);

  const pageFields = useMemo(() =>
    resolvedFields.filter(f => f.page === currentPage),
    [resolvedFields, currentPage]
  );

  const toggleSection = useCallback((sectionNumber: number | null) => {
    setCollapsedSections(prev => {
      const next = new Set(prev);
      if (next.has(sectionNumber)) next.delete(sectionNumber);
      else next.add(sectionNumber);
      return next;
    });
  }, []);

  const handleValueChange = useCallback((field: Field, newVal: string) => {
    // Collapsed mutually-exclusive radio group: fan the single selection out to
    // its member child fields (selected member -> "yes", siblings -> "no").
    if (field.mutexMembers && field.mutexMembers.length > 0) {
      const targetLabel = newVal.trim().toLowerCase();
      onFieldsUpdated(fieldsRef.current.map(f => {
        const member = field.mutexMembers!.find(m => mutexOptionName(m.label, field.label).trim().toLowerCase() === targetLabel);
        if (member && f.label === member.label) {
          const next = 'yes';
          if (valuesEqual(next, f.value)) return f;
          const isReverted = f.original_value != null && valuesEqual(next, f.original_value);
          return { ...f, value: next, original_value: isReverted ? null : (f.original_value ?? f.value), is_edited: !isReverted };
        }
        if (field.mutexMembers!.some(m => m.label === f.label)) {
          const next = 'no';
          if (valuesEqual(next, f.value)) return f;
          const isReverted = f.original_value != null && valuesEqual(next, f.original_value);
          return { ...f, value: next, original_value: isReverted ? null : (f.original_value ?? f.value), is_edited: !isReverted };
        }
        return f;
      }));
      return;
    }
    onFieldsUpdated(fieldsRef.current.map(f => {
      if (f.label === field.label) {
        if (valuesEqual(newVal, f.value)) return f;
        const isReverted = f.original_value != null && valuesEqual(newVal, f.original_value);
        return {
          ...f,
          value: newVal,
          original_value: isReverted ? null : (f.original_value ?? f.value),
          is_edited: isReverted ? false : true,
        };
      }
      return f;
    }));
  }, [onFieldsUpdated]);

  const handleBulkValueChange = useCallback((updates: {field: Field, newVal: string}[]) => {
    onFieldsUpdated(fieldsRef.current.map(f => {
      const update = updates.find(u => u.field.label === f.label);
      if (update) {
        if (valuesEqual(update.newVal, f.value)) return f;
        const isReverted = f.original_value != null && valuesEqual(update.newVal, f.original_value);
        return {
          ...f,
          value: update.newVal,
          original_value: isReverted ? null : (f.original_value ?? f.value),
          is_edited: !isReverted,
        };
      }
      return f;
    }));
  }, [onFieldsUpdated]);

  const handlePrevPage = useCallback(() => {
    if (currentPage > 1) onPageClick(currentPage - 1);
  }, [currentPage, onPageClick]);

  const handleNextPage = useCallback(() => {
    if (currentPage < numPages) onPageClick(currentPage + 1);
  }, [currentPage, numPages, onPageClick]);

  // ── Build section list for current page ──

  const sectionGroups: SectionGroup[] = useMemo(() => {
    const map = new Map<number | null, SectionGroup>();

    // Build section number → section name map
    const sectionNames = new Map<number | null, string>();
    for (const s of sections) {
      sectionNames.set(s.number, s.name);
    }

    // Filter out hidden helpers or internal fields that don't correspond to PDF questions
    const visibleFields = pageFields.filter(f => {
      const lbl = f.label.trim().toLowerCase();
      if (lbl.includes('blank_text_below')) return false;
      if (lbl.endsWith('notes') && (lbl.includes(' - ') || lbl.includes(' — ') || lbl.includes(' – '))) return false;
      
      // Deduplicate 4.4.1 fields — only drop exact duplicates
      // The real 4.4.1 fields follow the pattern "4.4.1 If Yes, ..." with table rows having " — Row N — "
      // LLM sometimes emits "4.4.1 If Yes, list other sources of income: - Source of Income" without "Row 1"
      // Keep those; only drop if there's an exact duplicate label
      // (Deduplication is handled elsewhere; don't filter here)
      
      return true;
    });

    // Group fields by section_number and detect tables/checkbox groups
    const fieldsBySection = new Map<number | null, Field[]>();
    for (const f of visibleFields) {
      const sn = f.section_number;
      if (!fieldsBySection.has(sn)) fieldsBySection.set(sn, []);
      fieldsBySection.get(sn)!.push(f);
    }

    for (const [sn, secFields] of fieldsBySection) {
      const name = sn !== null ? sectionNames.get(sn) || `Section ${sn}` : 'Header';

      const blocks: UIBlock[] = [];
      let currentTable: { prefix: string; fields: Field[] } | null = null;
      let currentCheckboxGroup: { prefix: string; fields: Field[] } | null = null;

      const sortedSecFields = [...secFields].sort(fieldCompare);

      // Pre-compute hierarchy from backend metadata (parent_label / field_type),
      // NOT from fragile label-prefix string matching.
      const parentLabels = new Set<string>();
      for (const f of sortedSecFields) {
        if (f.parent_label) parentLabels.add(f.parent_label);
      }
      // A field is a "parent" if another field points at it via parent_label.
      const isParent = (label: string) => parentLabels.has(label);
      // Fields already consumed as a child of a parent group (skip in main loop).
      const consumed = new Set<string>();

      const flushTable = () => {
        if (currentTable) {
          blocks.push({ type: 'table', prefix: currentTable.prefix, fields: currentTable.fields });
          currentTable = null;
        }
      };
      const flushCheckboxGroup = () => {
        if (currentCheckboxGroup) {
          const grp = currentCheckboxGroup;
          // Single-select radio group (e.g. 3.2, 3.3) → collapse into one 8.2-style row.
          const isRadioGroup =
            grp.fields.some(f => f.field_type === 'radio') || schemaFieldType(grp.prefix) === 'radio';
          if (isRadioGroup) {
            const radioChildren = grp.fields.filter(f => f.field_type === 'radio');
            const otherChildren = grp.fields.filter(f => f.field_type !== 'radio');
            if (radioChildren.length > 0) {
              blocks.push({
                type: 'field',
                field: buildRadioSyntheticField(
                  grp.prefix,
                  radioChildren,
                  m => mutexOptionName(m, grp.prefix),
                  otherChildren,
                ),
              });
            } else {
              // No radio members (only specify follow-ups) — emit as standalone.
              for (const oc of otherChildren) {
                consumed.add(oc.label);
                blocks.push({ type: 'field', field: oc });
              }
            }
            currentCheckboxGroup = null;
            return;
          }
          // Synthesize a header field when the group parent is absent from the data
          // (pure group questions like "4.1 Assets at Home" are often not emitted as fields).
          const headerExists = grp.fields.some(f => f.label === grp.prefix);
          let outFields = grp.fields;
          if (!headerExists && grp.fields.length > 0) {
            const first = grp.fields[0];
            const synHeader: Field = {
              label: grp.prefix,
              value: '',
              confidence: 0,
              page: first.page,
              section_number: first.section_number,
              bbox: null,
              value_bbox: null,
              needs_clarification: false,
              reason: null,
              is_verified: false,
              verifier_confidence: null,
              verification_note: null,
              extracted_by: null,
              verified_by: null,
              original_value: '',
              is_edited: false,
              parent_label: grp.prefix,
              field_type: schemaFieldType(grp.prefix),
              group_id: null,
              row_index: null,
              column_name: null,
            };
            outFields = [synHeader, ...grp.fields];
          }
          blocks.push({ type: 'checkbox_group', prefix: grp.prefix, fields: outFields });
          currentCheckboxGroup = null;
        }
      };

      for (const f of sortedSecFields) {
        if (consumed.has(f.label)) continue;

        const match = f.label.match(TABLE_ROW_RE);
        const is441 = f.label.includes('4.4.1');
        const is431 = f.label.includes('4.3.1');
        const is461 = f.label.includes('4.6.1');

        // Table HEADER fields (bare title ending in ":" with nothing after it) are
        // not rows — they are looked up separately by TableView. Skipping them here
        // prevents a duplicate empty-prefix table block alongside the real one.
        // Actual rows (e.g. "4.4.1 ...: - Amount") keep their content after the colon
        // and must NOT be skipped.
        const afterColon = f.label.includes(':') ? f.label.split(':').slice(1).join(':').trim() : f.label;
        const isTableHeaderField = (is441 || is431 || is461) && !match && afterColon === '';
        if (isTableHeaderField) {
          flushCheckboxGroup();
          flushTable();
          continue;
        }

        // ── Table rows ──
        if (match || is441 || is431 || is461) {
          flushCheckboxGroup();
          let sectionPrefix = match ? match[1] : '';
          if (!sectionPrefix) {
            const parts = f.label.split(/ — | - | – /);
            if (parts.length >= 2) {
              sectionPrefix = parts.slice(0, -1).join(' — ');
            }
          }
          if (currentTable && currentTable.prefix !== sectionPrefix) {
            flushTable();
          }
          if (!currentTable) {
            currentTable = { prefix: sectionPrefix, fields: [] };
          }
          currentTable.fields.push(f);
          continue;
        }

        // ── Mutually-exclusive single-select radio group (e.g. 3.1, 3.5, 4.3) ──
        // Collapse into a single radio field rendered exactly like 8.2: one row
        // with inline radio choices, clicking highlights the whole question region.
        const mg = mutexGroupFor(f.label);
        if (mg) {
          flushTable();
          flushCheckboxGroup();
          const memberFields = sortedSecFields.filter(
            c => mg.members.includes(c.label) && !consumed.has(c.label)
          );
          for (const c of memberFields) consumed.add(c.label);
          blocks.push({
            type: 'field',
            field: buildRadioSyntheticField(mg.stem, memberFields, m => mutexOptionName(m, mg.stem)),
          });
          continue;
        }

        // ── Parent of a radio/checkbox/specify group ──
        // Group parents (e.g. "4.1 Assets at Home", "4.5 Income Type", "2.4 Government ID Verified")
        // have no separator in their own label, so they would otherwise fall through to a
        // standalone field row. Detect them via parent_label and emit a single group block.
        // NOTE: a parent may sort AFTER its children (stable sort, equal numeric prefix), so
        // some children could already be buffered in currentCheckboxGroup — absorb them here.
        if (isParent(f.label)) {
          flushTable();
          let children = sortedSecFields.filter(
            c => c.label !== f.label && c.parent_label === f.label
          );
          // Absorb any children already accumulated in the in-progress checkbox group.
          if (currentCheckboxGroup && currentCheckboxGroup.prefix === f.label) {
            const buffered = currentCheckboxGroup.fields.filter(c => !children.includes(c));
            children = [...children, ...buffered];
            currentCheckboxGroup = null;
          }
          // Single-select radio parent (e.g. 3.2, 3.3) → collapse into one 8.2-style row.
          const isRadioGroup =
            f.field_type === 'radio' || children.some(c => c.field_type === 'radio');
          if (isRadioGroup) {
            const radioChildren = children.filter(c => c.field_type === 'radio');
            const otherChildren = children.filter(c => c.field_type !== 'radio');
            if (radioChildren.length > 0) {
              blocks.push({
                type: 'field',
                field: buildRadioSyntheticField(
                  f.label,
                  radioChildren,
                  m => mutexOptionName(m, f.label),
                  otherChildren,
                ),
              });
            } else {
              for (const oc of otherChildren) {
                consumed.add(oc.label);
                blocks.push({ type: 'field', field: oc });
              }
            }
            continue;
          }
          for (const c of children) consumed.add(c.label);
          blocks.push({
            type: 'checkbox_group',
            prefix: f.label,
            fields: [f, ...children],
          });
          continue;
        }

        // ── Child of a group whose own label carries a separator ──
        // Prefer the backend parent_label. Fall back to legacy prefix grouping only when the
        // prefix is a real known group parent, OR when this is a checkbox/radio option child
        // (e.g. Yes/No pairs like 4.3/4.4/4.6 that use mutually_exclusive_with instead of
        // parent_label). Plain text children (e.g. "2.2 Relationship Details — ...") are NOT
        // grouped — they render as standalone fields.
        if (
          (f.label.includes(' — ') || f.label.includes(' - ') || f.label.includes(' – ')) &&
          !f.label.toLowerCase().includes('notes')
        ) {
          const prefix = f.parent_label || f.label.split(/ — | - | – /)[0];
          const isOptionChild = f.field_type === 'checkbox' || f.field_type === 'radio';
          if (parentLabels.has(prefix) || (isOptionChild && !f.parent_label)) {
            flushTable();
            if (currentCheckboxGroup && currentCheckboxGroup.prefix !== prefix) {
              flushCheckboxGroup();
            }
            if (!currentCheckboxGroup) {
              currentCheckboxGroup = { prefix, fields: [] };
            }
            currentCheckboxGroup.fields.push(f);
            continue;
          }
        }

        // ── Standalone field ──
        flushTable();
        flushCheckboxGroup();
        blocks.push({ type: 'field', field: f });
      }
      flushTable();
      flushCheckboxGroup();

      map.set(sn, {
        sectionNumber: sn,
        sectionName: name,
        blocks,
      });
    }

    // Sort sections: null first, then by section_number
    const sorted = Array.from(map.entries()).sort(([a], [b]) => {
      if (a === null && b === null) return 0;
      if (a === null) return -1;
      if (b === null) return 1;
      return a - b;
    });

    return sorted.map(([, group]) => group);
  }, [pageFields, sections]);

  const sectionTitleStyle: React.CSSProperties = {
    fontSize: 13,
    fontWeight: 700,
    color: '#ffffff',
    padding: '8px 12px',
    background: 'var(--color-section-header)',
    borderBottom: '1px solid var(--color-border)',
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    cursor: 'pointer',
    userSelect: 'none',
    position: 'sticky',
    top: 0,
    zIndex: 2,
    transition: 'background var(--transition-fast)',
  };

  return (
    <div style={{
      flex: 1,
      minHeight: 0,
      display: 'flex',
      flexDirection: 'column',
      fontFamily: 'var(--font-sans)',
      background: '#f3f4f6',
    }}>
      {/* ── Toolbar ── */}
      {!hideToolbar && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 8,
          padding: '8px 12px',
          borderBottom: '1px solid var(--color-border)',
          background: 'var(--color-surface)',
          flexShrink: 0,
        }}>
          <span style={{ fontWeight: 600, fontSize: 14, color: 'var(--color-text)' }}>
            Extracted Data
          </span>
          <div style={{ flex: 1 }} />
          <button
            onClick={handlePrevPage}
            disabled={currentPage <= 1}
            style={{
              padding: '4px 10px', fontSize: 12, fontWeight: 500,
              border: `1px solid ${currentPage <= 1 ? 'var(--color-border)' : 'var(--color-border-hover)'}`,
              borderRadius: 'var(--radius-sm)',
              background: currentPage <= 1 ? 'var(--color-bg)' : 'var(--color-surface)',
              color: currentPage <= 1 ? 'var(--color-text-placeholder)' : 'var(--color-text-secondary)',
              cursor: currentPage <= 1 ? 'default' : 'pointer',
              transition: 'all var(--transition-fast)',
            }}
          >
            Prev
          </button>
          <span style={{ fontSize: 12, color: 'var(--color-text-secondary)' }}>
            Page {currentPage} / {numPages}
          </span>
          <button
            onClick={handleNextPage}
            disabled={currentPage >= numPages}
            style={{
              padding: '4px 10px', fontSize: 12, fontWeight: 500,
              border: `1px solid ${currentPage >= numPages ? 'var(--color-border)' : 'var(--color-border-hover)'}`,
              borderRadius: 'var(--radius-sm)',
              background: currentPage >= numPages ? 'var(--color-bg)' : 'var(--color-surface)',
              color: currentPage >= numPages ? 'var(--color-text-placeholder)' : 'var(--color-text-secondary)',
              cursor: currentPage >= numPages ? 'default' : 'pointer',
              transition: 'all var(--transition-fast)',
            }}
          >
            Next
          </button>
        </div>
      )}

      {/* ── Section list ── */}
      <div style={{ flex: 1, overflowY: hideToolbar ? 'visible' : 'auto', overflowX: 'hidden', background: '#f3f4f6', border: '1px solid var(--color-border)' }}>
        {sectionGroups.length === 0 && (
          <div style={{ padding: 20, textAlign: 'center', color: 'var(--color-text-muted)', fontSize: 13 }}>
            No fields on this page.
          </div>
        )}

        {sectionGroups.map(group => {
          const isCollapsed = collapsedSections.has(group.sectionNumber);
          const hasContent = group.blocks.length > 0;

          return (
            <div key={group.sectionNumber ?? '__header__'} style={{ 
              border: '1px solid var(--color-card-border)', 
              borderRadius: 'var(--radius-md)', 
              margin: '8px 12px', 
              background: 'var(--color-surface)',
              overflow: 'hidden'
            }}>
              {/* Section header */}
              <div
                style={sectionTitleStyle}
                onClick={() => toggleSection(group.sectionNumber)}
                onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--color-section-header-hover)'; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = 'var(--color-section-header)'; }}
              >
                <Chevron expanded={!isCollapsed} />
                <span>{group.sectionName}</span>
                {hasContent && (
                  <span style={{ color: 'var(--color-text-muted)', fontSize: 11, fontWeight: 400 }}>
                    ({group.blocks.reduce((acc, b) => acc + (b.type === 'field' ? 1 : b.fields.length), 0)})
                  </span>
                )}
              </div>

              {/* Section content */}
              {!isCollapsed && hasContent && (
                <div style={{ padding: '0' }}>
                  {group.blocks.map((block, idx) => {
                    if (block.type === 'field') {
                      return (
                        <FieldRow
                          key={block.field.label}
                          field={block.field}
                          isSelected={selectedField?.label === block.field.label}
                          onSelect={() => onFieldClick(block.field)}
                          onValueChange={(v) => handleValueChange(block.field, v)}
                          onFieldUpdate={handleValueChange}
                        />
                      );
                    } else if (block.type === 'table') {
                      return (
                        <div key={`table-${idx}`} style={{ margin: '8px 12px' }}>
                          <TableView
                            fields={block.fields}
                            allFields={resolvedFields}
                            selectedField={selectedField}
                            onFieldClick={onFieldClick}
                            onFieldUpdate={handleValueChange}
                          />
                        </div>
                      );
                    } else if (block.type === 'checkbox_group') {
                      return (
                        <div key={`cb-${idx}`} style={{ margin: '4px 0' }}>
                          <CheckboxGroupView
                            fields={block.fields}
                            selectedField={selectedField}
                            onFieldClick={onFieldClick}
                            onFieldUpdate={handleValueChange}
                            onBulkFieldUpdate={handleBulkValueChange}
                          />
                        </div>
                      );
                    }
                    return null;
                  })}
                </div>
              )}

              {/* Empty section */}
              {!isCollapsed && !hasContent && (
                <div style={{ padding: '8px 12px', color: 'var(--color-text-placeholder)', fontSize: 12, fontStyle: 'italic' }}>
                  No fields in this section.
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
