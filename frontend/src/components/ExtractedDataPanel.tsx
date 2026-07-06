import { useState, useCallback, useMemo } from 'react';
import type { Field, Section } from '../types';

// ── Helpers ─────────────────────────────────────────────────────────────────

const TABLE_ROW_RE = /^(.+?)\s*[—–-]\s*Row\s+(\d+)\s*[—–-]\s*(.+)$/;
const CHECKBOX_VALS = new Set(['yes', 'no', 'true', 'false', '✓', '✗', '?']);

function isCheckbox(field: Field): boolean {
  return CHECKBOX_VALS.has(field.value.trim().toLowerCase());
}

function confidenceColor(c: number): string {
  if (c >= 0.8) return '#16a34a';
  if (c >= 0.5) return '#d97706';
  return '#dc2626';
}

function confidenceLabel(c: number): string {
  if (c >= 0.9) return 'High';
  if (c >= 0.7) return 'Medium';
  if (c >= 0.4) return 'Low';
  return 'Very Low';
}

function checkboxDisplay(val: string): { icon: string; color: string } {
  const v = val.trim().toLowerCase();
  if (v === 'yes' || v === 'true' || v === '✓') return { icon: '✓', color: '#16a34a' };
  if (v === 'no' || v === 'false' || v === '✗') return { icon: '✗', color: '#dc2626' };
  return { icon: '?', color: '#94a3b8' };
}

function parseDateToYmd(val: string): string {
  if (!val) return '';
  if (/^\d{4}-\d{2}-\d{2}$/.test(val)) return val;
  const slashMatch = val.match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
  if (slashMatch) {
    return `${slashMatch[3]}-${slashMatch[2]}-${slashMatch[1]}`;
  }
  const dashMatch = val.match(/^(\d{2})-([a-zA-Z]{3})-(\d{4})$/);
  if (dashMatch) {
    const months = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'];
    const monthIndex = months.indexOf(dashMatch[2].toLowerCase());
    if (monthIndex !== -1) {
      const mm = String(monthIndex + 1).padStart(2, '0');
      return `${dashMatch[3]}-${mm}-${dashMatch[1]}`;
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
  if (lbl.includes('number of bedrooms')) {
    return ['0', '1', '2', '3', '4', 'More than 4', 'N/A'];
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
    lbl.includes('will you study college for three years') ||
    lbl.includes('ready to send your son/daughter') ||
    lbl.includes('photograph kept at home')
  ) {
    return ['Yes', 'No'];
  }
  if (lbl.includes('training program within 15 km')) {
    return ['Yes', 'No', 'Maybe'];
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
  value, onSave, onCancel,
}: {
  value: string;
  onSave: (v: string) => void;
  onCancel: () => void;
}) {
  const [editVal, setEditVal] = useState(value);

  const handleKey = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter') onSave(editVal);
    if (e.key === 'Escape') onCancel();
  }, [editVal, onSave, onCancel]);

  return (
    <input
      autoFocus
      value={editVal}
      onChange={e => setEditVal(e.target.value)}
      onKeyDown={handleKey}
      onBlur={() => onSave(editVal)}
      style={{
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
      }}
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
  const wasCorrected = field.original_value !== null;

  const containerStyle: React.CSSProperties = {
    border: `1px solid ${isSelected ? 'var(--color-primary)' : wasCorrected ? 'var(--color-success-border)' : 'var(--color-border)'}`,
    borderRadius: 'var(--radius-md)',
    padding: '6px 8px',
    marginBottom: 4,
    cursor: 'pointer',
    transition: 'border-color var(--transition-fast), box-shadow var(--transition-fast)',
    background: isSelected ? 'var(--color-primary-light)' : wasCorrected ? 'var(--color-success-light)' : hovered ? 'var(--color-surface-hover)' : 'var(--color-surface)',
    boxShadow: isSelected ? '0 0 0 1px rgba(37,99,235,0.15)' : 'none',
    fontFamily: 'var(--font-sans)',
  };

  const labelStyle: React.CSSProperties = {
    fontSize: 11,
    fontWeight: 500,
    color: 'var(--color-text-secondary)',
    marginBottom: 2,
    display: 'flex',
    alignItems: 'center',
    gap: 4,
    flexWrap: 'wrap',
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
        <span style={{ color: 'var(--color-label)' }}>{field.label}</span>
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
          return (
            <div onClick={(e) => e.stopPropagation()} style={{ marginTop: 4 }}>
              <input
                type="date"
                value={parseDateToYmd(field.value)}
                onChange={(e) => {
                  const ymd = e.target.value;
                  const formatted = formatYmdToDdMmmYyyy(ymd);
                  onValueChange(formatted);
                }}
                style={{
                  padding: '4px 6px',
                  borderRadius: 'var(--radius-sm)',
                  border: '1px solid var(--color-border)',
                  background: 'var(--color-surface)',
                  color: 'var(--color-text)',
                  fontSize: 13,
                  outline: 'none',
                }}
              />
            </div>
          );
        }

        if (lbl.includes('government id verified')) {
          const idOptions = ['Aadhaar Card', 'Ration Card', 'Voter ID', 'Driving Licence'];
          let currentSelection: string[] = [];
          try {
            if (field.value.startsWith('[')) {
              currentSelection = JSON.parse(field.value);
            } else if (field.value && field.value !== '—') {
              currentSelection = field.value.split(',').map((s: string) => s.trim());
            }
          } catch {
            currentSelection = [];
          }

          return (
            <div 
              style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 4 }}
              onClick={(e) => e.stopPropagation()}
            >
              {idOptions.map(opt => {
                const isChecked = currentSelection.includes(opt);
                const toggle = () => {
                  let next: string[];
                  if (isChecked) {
                    next = currentSelection.filter(s => s !== opt);
                  } else {
                    next = [...currentSelection, opt];
                  }
                  onValueChange(JSON.stringify(next));
                };
                return (
                  <div
                    key={opt}
                    onClick={toggle}
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: 4,
                      padding: '3px 6px',
                      borderRadius: 'var(--radius-sm)',
                      border: `1px solid ${isChecked ? 'var(--color-success-border)' : 'var(--color-border-light)'}`,
                      background: isChecked ? 'var(--color-success-light)' : 'var(--color-bg)',
                      fontSize: 11,
                      cursor: 'pointer',
                      userSelect: 'none',
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={isChecked}
                      readOnly
                      style={{ pointerEvents: 'none', marginRight: 2 }}
                    />
                    <span style={{ color: 'var(--color-text)' }}>{opt}</span>
                  </div>
                );
              })}
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
                const isChecked = field.value.trim().toLowerCase() === opt.toLowerCase();
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
                      type="radio"
                      name={field.label}
                      checked={isChecked}
                      onChange={() => onValueChange(opt)}
                    />
                    {opt}
                  </label>
                );
              })}
            </div>
          );
        }
        if (isCheckboxField) {
          return (
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 2 }}>
              <CheckboxIcon value={field.value} />
              <span style={{ fontSize: 13, color: 'var(--color-text)' }}>{field.value}</span>
            </div>
          );
        }
        if (editing) {
          return (
            <InlineEditor value={field.value} onSave={handleSave} onCancel={handleCancel} />
          );
        }
        return null;
      })() || (
        <div
          onDoubleClick={handleStartEdit}
          style={{
            fontSize: 13,
            color: 'var(--color-text)',
            lineHeight: 1.4,
            padding: '2px 0',
            minHeight: 18,
            wordBreak: 'break-word',
            display: 'flex',
            alignItems: 'center',
            gap: 6,
          }}
        >
          <span style={{ flex: 1 }}>
            {field.value || <span style={{ color: 'var(--color-text-placeholder)', fontStyle: 'italic' }}>empty</span>}
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
  const wasCorrected = field.original_value !== null;
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
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        padding: '4px 6px',
        borderBottom: '1px solid var(--color-border-light)',
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
    }
  }

  if (columns.size === 0 || rows.size === 0) {
    return (
      <div style={{ padding: '4px 0' }}>
        {fields.map(f => (
          <FieldRow key={f.label} field={f} isSelected={selectedField === f} onSelect={() => onFieldClick(f)} onValueChange={(v) => onFieldUpdate(f, v)} />
        ))}
      </div>
    );
  }

  const colArr = Array.from(columns);

  return (
    <div style={{ overflowX: 'auto', padding: '4px 0' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
        <thead>
          <tr>
            <th style={{ textAlign: 'left', padding: '4px 6px', borderBottom: '1px solid var(--color-border)', color: 'var(--color-text-secondary)', fontWeight: 600, whiteSpace: 'nowrap' }}>#</th>
            {colArr.map(col => (
              <th key={col} style={{ textAlign: 'left', padding: '4px 6px', borderBottom: '1px solid var(--color-border)', color: 'var(--color-text-secondary)', fontWeight: 600, whiteSpace: 'nowrap' }}>{col}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {Array.from(rows.entries()).map(([rowKey, cols]) => {
            const [, rowNum] = rowKey.split('|');
            return (
              <tr key={rowKey}>
                <td style={{ padding: '4px 6px', borderBottom: '1px solid var(--color-border-light)', color: 'var(--color-text-muted)', fontSize: 11, whiteSpace: 'nowrap', verticalAlign: 'top' }}>{rowNum}</td>
                {colArr.map(col => {
                  const f = cols.get(col);
                  if (!f) return <td key={col} style={{ padding: '4px 6px', borderBottom: '1px solid var(--color-border-light)' }}><span style={{ color: 'var(--color-text-placeholder)', fontStyle: 'italic' }}>—</span></td>;
                  return (
                    <TableCell
                      key={col}
                      field={f}
                      isSelected={selectedField === f}
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
  const wasCorrected = field.original_value !== null;

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
      <span style={{ color: 'var(--color-label)', fontWeight: 500 }}>{field.label}</span>
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 3, color: 'var(--color-text)' }}>
        <CheckboxIcon value={field.value} />
        {field.value}
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

function CheckboxDropdownGroup({
  groupLabel,
  fields,
  selectedField,
  onFieldClick,
  onFieldUpdate,
}: {
  groupLabel: string;
  fields: Field[];
  selectedField: Field | null;
  onFieldClick: (f: Field) => void;
  onFieldUpdate: (f: Field, newVal: string) => void;
}) {
  const activeSelected = fields.find(f => {
    const v = f.value.trim().toLowerCase();
    return v === 'yes' || v === 'true' || v === '✓';
  });

  const isGroupSelected = selectedField ? fields.includes(selectedField) : false;

  const handleChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const chosenLabel = e.target.value;
    fields.forEach(f => {
      const parts = f.label.split(' — ');
      const optName = parts[1] || parts[0];
      const isChosen = optName === chosenLabel;
      const newVal = isChosen ? 'yes' : 'no';
      if (f.value !== newVal) {
        onFieldUpdate(f, newVal);
      }
    });
  };

  const options = fields.map(f => {
    const parts = f.label.split(' — ');
    return parts[1] || parts[0];
  });

  const currentVal = activeSelected ? (activeSelected.label.split(' — ')[1] || activeSelected.label) : '';

  return (
    <div
      onClick={() => onFieldClick(activeSelected || fields[0])}
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 4,
        padding: '6px 10px',
        border: `1px solid ${isGroupSelected ? 'var(--color-primary)' : 'var(--color-border)'}`,
        borderRadius: 'var(--radius-md)',
        background: isGroupSelected ? 'var(--color-primary-light)' : 'var(--color-surface)',
        marginBottom: 6,
        cursor: 'pointer',
        boxSizing: 'border-box',
        width: '100%',
      }}
    >
      <label style={{ fontSize: 11, fontWeight: 600, color: 'var(--color-text-secondary)', userSelect: 'none' }}>
        {groupLabel}
      </label>
      <select
        value={currentVal}
        onChange={handleChange}
        onClick={(e) => e.stopPropagation()}
        style={{
          width: '100%',
          padding: '6px 8px',
          borderRadius: 'var(--radius-sm)',
          border: '1px solid var(--color-border)',
          background: 'var(--color-surface)',
          color: 'var(--color-text)',
          fontSize: 13,
          outline: 'none',
        }}
      >
        <option value="">-- Select Option --</option>
        {options.map(opt => (
          <option key={opt} value={opt}>
            {opt}
          </option>
        ))}
      </select>
    </div>
  );
}

function CheckboxMultiSelectGroup({
  groupLabel,
  fields,
  selectedField,
  onFieldClick,
  onFieldUpdate,
}: {
  groupLabel: string;
  fields: Field[];
  selectedField: Field | null;
  onFieldClick: (f: Field) => void;
  onFieldUpdate: (f: Field, newVal: string) => void;
}) {
  const isGroupSelected = selectedField ? fields.includes(selectedField) : false;

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 6,
        padding: '8px 10px',
        border: `1px solid ${isGroupSelected ? 'var(--color-primary)' : 'var(--color-border)'}`,
        borderRadius: 'var(--radius-md)',
        background: 'var(--color-surface)',
        marginBottom: 6,
        width: '100%',
        boxSizing: 'border-box',
      }}
    >
      <label style={{ fontSize: 11, fontWeight: 600, color: 'var(--color-text-secondary)', userSelect: 'none' }}>
        {groupLabel} (Multi-Select)
      </label>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
        {fields.map(f => {
          const optName = f.label.split(' — ')[1] || f.label;
          const isChecked = f.value.trim().toLowerCase() === 'yes' || f.value.trim().toLowerCase() === 'true' || f.value.trim().toLowerCase() === '✓';
          const isItemSel = selectedField === f;

          const toggleChecked = (e: React.MouseEvent) => {
            e.stopPropagation();
            onFieldClick(f);
            onFieldUpdate(f, isChecked ? 'no' : 'yes');
          };

          return (
            <div
              key={f.label}
              onClick={toggleChecked}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 4,
                padding: '4px 8px',
                borderRadius: 'var(--radius-sm)',
                border: `1px solid ${isItemSel ? 'var(--color-primary)' : isChecked ? 'var(--color-success-border)' : 'var(--color-border-light)'}`,
                background: isItemSel ? 'var(--color-primary-light)' : isChecked ? 'var(--color-success-light)' : 'var(--color-bg)',
                fontSize: 12,
                cursor: 'pointer',
                userSelect: 'none',
              }}
            >
              <input
                type="checkbox"
                checked={isChecked}
                readOnly
                style={{ pointerEvents: 'none', marginRight: 4 }}
              />
              <span style={{ color: 'var(--color-text)' }}>{optName}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function CheckboxGroupView({
  fields, selectedField, onFieldClick, onFieldUpdate,
}: {
  fields: Field[];
  selectedField: Field | null;
  onFieldClick: (f: Field) => void;
  onFieldUpdate: (f: Field, newVal: string) => void;
}) {
  const groups = useMemo(() => {
    const map = new Map<string, Field[]>();
    fields.forEach(f => {
      const parts = f.label.split(' — ');
      const prefix = parts[0];
      if (!map.has(prefix)) {
        map.set(prefix, []);
      }
      map.get(prefix)!.push(f);
    });
    return Array.from(map.entries());
  }, [fields]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, width: '100%', padding: '4px 0' }}>
      {groups.map(([groupLabel, grpFields]) => {
        const isMulti = groupLabel.toLowerCase().includes('assets at home');
        if (isMulti) {
          return (
            <CheckboxMultiSelectGroup
              key={groupLabel}
              groupLabel={groupLabel}
              fields={grpFields}
              selectedField={selectedField}
              onFieldClick={onFieldClick}
              onFieldUpdate={onFieldUpdate}
            />
          );
        }
        return (
          <CheckboxDropdownGroup
            key={groupLabel}
            groupLabel={groupLabel}
            fields={grpFields}
            selectedField={selectedField}
            onFieldClick={onFieldClick}
            onFieldUpdate={onFieldUpdate}
          />
        );
      })}
    </div>
  );
}

// ── Main component ──────────────────────────────────────────────────────────

interface SectionGroup {
  sectionNumber: number | null;
  sectionName: string;
  fields: Field[];
  tables: Field[][];
  checkboxGroups: Field[][];
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
    fields.filter(f => f.page === currentPage),
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
      if (f === field) {
        return {
          ...f,
          value: newVal,
          original_value: f.original_value ?? f.value,
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

    // Group fields by section_number and detect tables/checkbox groups
    const fieldsBySection = new Map<number | null, Field[]>();
    for (const f of pageFields) {
      const sn = f.section_number;
      if (!fieldsBySection.has(sn)) fieldsBySection.set(sn, []);
      fieldsBySection.get(sn)!.push(f);
    }

    for (const [sn, secFields] of fieldsBySection) {
      const name = sn !== null ? sectionNames.get(sn) || `Section ${sn}` : 'Header';

      // Detect tables: fields sharing the same section prefix in label
      const tableFields = new Map<string, Field[]>();
      const checkboxFields: Field[] = [];
      const otherFields: Field[] = [];

      for (const f of secFields) {
        const match = f.label.match(TABLE_ROW_RE);
        if (match) {
          const sectionPrefix = match[1];
          if (!tableFields.has(sectionPrefix)) tableFields.set(sectionPrefix, []);
          tableFields.get(sectionPrefix)!.push(f);
        } else if (isCheckbox(f) && (f.label.includes(' — ') || f.label.includes(' - ') || f.label.includes(' – '))) {
          checkboxFields.push(f);
        } else {
          otherFields.push(f);
        }
      }

      const cbPrefixes = new Set<string>();
      for (const f of checkboxFields) {
        const parts = f.label.split(' — ');
        cbPrefixes.add(parts[0]);
      }
      const filteredOtherFields = otherFields.filter(f => !cbPrefixes.has(f.label));

      map.set(sn, {
        sectionNumber: sn,
        sectionName: name,
        fields: filteredOtherFields,
        tables: Array.from(tableFields.values()),
        checkboxGroups: checkboxFields.length > 0 ? [checkboxFields] : [],
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
    fontSize: 12,
    fontWeight: 600,
    color: 'var(--color-text)',
    padding: '8px 12px',
    background: 'var(--color-bg)',
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
      <div style={{ flex: 1, overflowY: hideToolbar ? 'visible' : 'auto', overflowX: 'hidden' }}>
        {sectionGroups.length === 0 && (
          <div style={{ padding: 20, textAlign: 'center', color: 'var(--color-text-muted)', fontSize: 13 }}>
            No fields on this page.
          </div>
        )}

        {sectionGroups.map(group => {
          const isCollapsed = collapsedSections.has(group.sectionNumber);
          const hasContent = group.fields.length > 0 || group.tables.length > 0 || group.checkboxGroups.length > 0;

          return (
            <div key={group.sectionNumber ?? '__header__'} style={{ borderBottom: '1px solid var(--color-border)' }}>
              {/* Section header */}
              <div
                style={sectionTitleStyle}
                onClick={() => toggleSection(group.sectionNumber)}
                onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--color-surface-active)'; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = 'var(--color-bg)'; }}
              >
                <Chevron expanded={!isCollapsed} />
                <span>{group.sectionName}</span>
                {hasContent && (
                  <span style={{ color: 'var(--color-text-muted)', fontSize: 11, fontWeight: 400 }}>
                    ({group.fields.length + group.tables.reduce((s, t) => s + t.length, 0) + group.checkboxGroups.reduce((s, g) => s + g.length, 0)})
                  </span>
                )}
              </div>

              {/* Section content */}
              {!isCollapsed && hasContent && (
                <div style={{ padding: '4px 12px 8px' }}>
                  {/* Regular fields */}
                  {group.fields.map(f => (
                    <FieldRow
                      key={f.label}
                      field={f}
                      isSelected={selectedField === f}
                      onSelect={() => onFieldClick(f)}
                      onValueChange={(v) => handleValueChange(f, v)}
                    />
                  ))}

                  {/* Tables */}
                  {group.tables.map((tbl, idx) => (
                    <div key={`table-${idx}`} style={{ marginTop: 6 }}>
                      <div style={{ fontSize: 11, fontWeight: 600, color: '#64748b', marginBottom: 4 }}>
                        Table {idx + 1}
                      </div>
                      <TableView
                        fields={tbl}
                        selectedField={selectedField}
                        onFieldClick={onFieldClick}
                        onFieldUpdate={handleValueChange}
                      />
                    </div>
                  ))}

                  {/* Checkbox groups */}
                  {group.checkboxGroups.map((grp, idx) => (
                    <div key={`cb-${idx}`} style={{ marginTop: 4 }}>
                      <CheckboxGroupView
                        fields={grp}
                        selectedField={selectedField}
                        onFieldClick={onFieldClick}
                        onFieldUpdate={handleValueChange}
                      />
                    </div>
                  ))}
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
