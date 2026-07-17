import { useState, useCallback, useMemo } from 'react';
import type { Field, Section } from '../types';

// ── Helpers ─────────────────────────────────────────────────────────────────

const TABLE_ROW_RE = /^(.+?)\s*[—–-]\s*Row\s+(\d+)\s*[—–-]\s*(.+)$/;
const CHECKBOX_VALS = new Set(['yes', 'no', 'true', 'false', '✓', '✗', '?']);

function isCheckbox(field: Field): boolean {
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

function parseDateToYmd(val: string): string {
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

function CheckboxIcon({ value }: { value: string }) {
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
  field, isSelected, onSelect, onValueChange,
}: {
  field: Field;
  isSelected: boolean;
  onSelect: () => void;
  onValueChange: (newVal: string) => void;
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

  const isMultiSelect = field.label.includes('2.1 ') || /^(4\.4 |4\.6 |8\.2 )/.test(field.label);

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
        
        if (lbl.includes('date of visit')) {
          // Convert current value (which might be DD-MMM-YYYY or raw text) to DD-MM-YYYY for editing
          const ymd = parseDateToYmd(field.value);
          let displayVal = field.value;
          if (ymd) {
            const parts = ymd.split('-');
            if (parts.length === 3) displayVal = `${parts[2]}-${parts[1]}-${parts[0]}`;
          }

          return (
            <div onMouseDown={(e) => e.stopPropagation()} style={{ marginTop: 4, display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>📅</span>
              <input
                type="text"
                placeholder="DD-MM-YYYY"
                defaultValue={displayVal}
                key={field.value}
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
        }


        const radioOpts = getRadioOptions(field.label);
        if (radioOpts) {
          return (
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
            </div>
          );
        }
        if (isCheckboxField && !field.label.startsWith('7.1 ') && !field.label.startsWith('6.1 ')) {
          const fv = (field.value ?? '').trim().toLowerCase();
          const isChecked = fv === 'yes' || fv === 'true' || fv === '✓';
          return (
            <div 
              onClick={(e) => { e.stopPropagation(); onValueChange(isChecked ? 'no' : 'yes'); }}
              style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 2, cursor: 'pointer' }}
            >
              <CheckboxIcon value={field.value} />
              <span style={{ fontSize: 13, color: 'var(--color-text)' }}>{field.value ?? 'empty'}</span>
            </div>
          );
        }
        if (editing) {
          return (
            <div style={{ flex: 1 }}>
              <InlineEditor value={field.value} onSave={handleSave} onCancel={handleCancel} multiline={field.label.includes('8.1') || field.label.includes('8.3')} />
            </div>
          );
        }
        return null;
      })() || (
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
          {hovered && (
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
      )}

      {field.reason && (
        <div style={{ fontSize: 10, color: 'var(--color-text-muted)', marginTop: 2 }}>
          {field.reason}
        </div>
      )}
    </div>
  );
}

function FieldRow({
  field, isSelected, onSelect, onValueChange,
}: {
  field: Field;
  isSelected: boolean;
  onSelect: () => void;
  onValueChange: (newVal: string) => void;
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
      />
    );
  }
  return (
    <FieldValue
      field={field}
      isSelected={isSelected}
      onSelect={onSelect}
      onValueChange={onValueChange}
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
  fields, selectedField, onFieldClick, onFieldUpdate,
}: {
  fields: Field[];
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
          <FieldRow key={f.label} field={f} isSelected={selectedField?.label === f.label} onSelect={() => onFieldClick(f)} onValueChange={(v) => onFieldUpdate(f, v)} />
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

  return (
    <div style={{ padding: '8px 12px 16px 12px' }}>
      {tableTitle && (
        <div style={{ fontSize: 13, fontWeight: 700, color: '#000000', marginBottom: 8 }}>
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
            <tr style={{ background: '#f8fafc' }}>
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
                <tr key={rowKey} style={{ background: isEven ? 'transparent' : '#f8fafc', borderBottom: '1px solid var(--color-border-light)' }}>
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

function SpecifyItem({ field, onFieldClick, onFieldUpdate }: {
  field: Field;
  onFieldClick: (f: Field) => void;
  onFieldUpdate: (f: Field, newVal: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [hovered, setHovered] = useState(false);

  if (editing) {
    return (
      <div style={{ padding: '2px 0' }}>
        <InlineEditor value={field.value} onSave={(v) => { onFieldUpdate(field, v); setEditing(false); }} onCancel={() => setEditing(false)} />
      </div>
    );
  }

  return (
    <div
      onClick={() => onFieldClick(field)}
      onDoubleClick={(e) => { e.stopPropagation(); setEditing(true); }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, cursor: 'pointer', position: 'relative' }}
    >
      <span style={{ color: 'var(--color-text-secondary)' }}>(specify)</span>
      <span style={{ color: 'var(--color-text)', borderBottom: '1px solid var(--color-border)', minWidth: 80, padding: '0 4px' }}>
        {field.value || <span style={{ fontStyle: 'italic', color: 'var(--color-text-placeholder)' }}>empty</span>}
      </span>
      {hovered && (
        <button
          onClick={(e) => { e.stopPropagation(); setEditing(true); }}
          style={{
            border: 'none', background: 'transparent', cursor: 'pointer',
            fontSize: 12, color: 'var(--color-text-muted)', padding: '1px 3px', borderRadius: 2,
            position: 'absolute', right: -24
          }}
          title="Edit value"
        >
          ✎
        </button>
      )}
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
  const groups = useMemo(() => {
    const map = new Map<string, Field[]>();
    fields.forEach(f => {
      const parts = f.label.split(/ — | - | – /);
      const prefix = parts[0];
      if (!map.has(prefix)) {
        map.set(prefix, []);
      }
      map.get(prefix)!.push(f);
    });
    return Array.from(map.entries());
  }, [fields]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', width: '100%' }}>
      {groups.map(([groupLabel, grpFields]) => {
        const isSingleSelectCol = /^(1\.3|3\.1|3\.2|3\.3|3\.4\.1|3\.5|3\.6|4\.3|4\.4|4\.6)/.test(groupLabel);
        return (
          <div
            key={groupLabel}
            style={{
              padding: '12px 16px',
              borderBottom: '1px solid var(--color-border)',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'stretch',
              gap: 8,
            }}
          >
            <label style={{ fontSize: 13, fontWeight: 700, color: '#000000', userSelect: 'none', flex: 'none', lineHeight: 1.4 }}>
              {groupLabel}
            </label>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16, flex: 1, alignItems: 'center' }}>
              {grpFields.map(f => {
                const parts = f.label.split(/ — | - | – /);
                const optName = parts.slice(1).join(' — ') || f.label;
                
                const hasSpecifySibling = grpFields.some(sibling => {
                  const sn = sibling.label.split(/ — | - | – /).slice(1).join(' — ').toLowerCase();
                  return sn.includes('specify');
                });
                const isOthersText = /^(other|others)\s*:?\s*$/i.test(optName.trim()) && !hasSpecifySibling;
                const isSpecify = optName.toLowerCase().includes('specify') || isOthersText;
                if (isSpecify) {
                  return (
                    <SpecifyItem
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

                  if (isSingleSelectCol && onBulkFieldUpdate) {
                    const willCheck = !isChecked;
                    if (willCheck) {
                      onBulkFieldUpdate(grpFields.map(sibling => ({
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
                      type="checkbox"
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
        );
      })}
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

  const pageFields = useMemo(() =>
    fields.filter(f => f.page === currentPage && !(f.page === 3 && f.label.startsWith('4.3.1'))),
    [fields, currentPage]
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
    onFieldsUpdated(fields.map(f => {
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
  }, [fields, onFieldsUpdated]);

  const handleBulkValueChange = useCallback((updates: {field: Field, newVal: string}[]) => {
    onFieldsUpdated(fields.map(f => {
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
  }, [fields, onFieldsUpdated]);

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
      
      // Filter out old aggregated parent fields that cause duplicates because they are now extracted individually
      if (lbl === '2.4 government id verified') return false;
      if (lbl === '4.5 income type') return false;

      // Deduplicate 4.4.1 fields — keep verbose labels, drop short duplicates
      if (lbl.startsWith('4.4.1') && !lbl.includes('if yes,')) return false;
      
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

      const flushTable = () => {
        if (currentTable) {
          blocks.push({ type: 'table', prefix: currentTable.prefix, fields: currentTable.fields });
          currentTable = null;
        }
      };
      const flushCheckboxGroup = () => {
        if (currentCheckboxGroup) {
          blocks.push({ type: 'checkbox_group', prefix: currentCheckboxGroup.prefix, fields: currentCheckboxGroup.fields });
          currentCheckboxGroup = null;
        }
      };

      for (const f of sortedSecFields) {
        const match = f.label.match(TABLE_ROW_RE);
        const is441 = f.label.includes('4.4.1');
        const is431 = f.label.includes('4.3.1');
        const is461 = f.label.includes('4.6.1');
        
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
        } else if (
          (f.label.includes(' — ') || f.label.includes(' - ') || f.label.includes(' – ')) &&
          !f.label.toLowerCase().includes('notes') &&
          !f.label.includes('2.2 Relationship Details')
        ) {
          flushTable();
          const parts = f.label.split(/ — | - | – /);
          const prefix = parts[0];
          if (currentCheckboxGroup && currentCheckboxGroup.prefix !== prefix) {
            flushCheckboxGroup();
          }
          if (!currentCheckboxGroup) {
            currentCheckboxGroup = { prefix, fields: [] };
          }
          currentCheckboxGroup.fields.push(f);
        } else {
          flushTable();
          flushCheckboxGroup();
          blocks.push({ type: 'field', field: f });
        }
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
    padding: '6px 10px',
    background: '#4b5563',
    borderBottom: '1px solid var(--color-border)',
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    cursor: 'pointer',
    userSelect: 'none',
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
              border: '1px solid #e5e7eb', 
              borderRadius: 'var(--radius-md)', 
              margin: '8px 12px', 
              background: '#f9fafb',
              overflow: 'hidden'
            }}>
              {/* Section header */}
              <div
                style={sectionTitleStyle}
                onClick={() => toggleSection(group.sectionNumber)}
                onMouseEnter={(e) => { e.currentTarget.style.background = '#6b7280'; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = '#4b5563'; }}
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
                <div style={{ padding: '4px 12px 8px' }}>
                  {group.blocks.map((block, idx) => {
                    if (block.type === 'field') {
                      return (
                        <FieldRow
                          key={block.field.label}
                          field={block.field}
                          isSelected={selectedField?.label === block.field.label}
                          onSelect={() => onFieldClick(block.field)}
                          onValueChange={(v) => handleValueChange(block.field, v)}
                        />
                      );
                    } else if (block.type === 'table') {
                      return (
                        <div key={`table-${idx}`} style={{ marginTop: 6, marginBottom: 6 }}>
                          <TableView
                            fields={block.fields}
                            selectedField={selectedField}
                            onFieldClick={onFieldClick}
                            onFieldUpdate={handleValueChange}
                          />
                        </div>
                      );
                    } else if (block.type === 'checkbox_group') {
                      return (
                        <div key={`cb-${idx}`} style={{ marginTop: 4, marginBottom: 4 }}>
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
