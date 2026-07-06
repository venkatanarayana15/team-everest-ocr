import { useState, useCallback, useMemo } from 'react';
import type { Field, Section } from '../types';

// ── Helpers ─────────────────────────────────────────────────────────────────

const TABLE_ROW_RE = /^(.+?)\s*[—–-]\s*Row\s+(\d+)\s*[—–-]\s*(.+)$/;
const CHECKBOX_VALS = new Set(['yes', 'no', 'true', 'false', '✓', '✗', '?']);

function isCheckbox(field: Field): boolean {
  if (TABLE_ROW_RE.test(field.label)) return false;
  const isValCheckbox = CHECKBOX_VALS.has(field.value.trim().toLowerCase());
  const hasSeparator = field.label.includes('\u2014') || field.label.includes('\u2013') || field.label.includes(' — ') || field.label.includes(' - ');
  return isValCheckbox && hasSeparator;
}

function parseCheckboxLabel(label: string): { parent: string; option: string } {
  const parts = label.split(/\s*[\u2014\u2013-]\s*/);
  if (parts.length >= 2) {
    const option = parts.pop() || '';
    const parent = parts.join(' — ');
    return { parent, option };
  }
  return { parent: label, option: '' };
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

      {isCheckboxField ? (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 2 }}>
          <CheckboxIcon value={field.value} />
          <span style={{ fontSize: 13, color: 'var(--color-text)' }}>{field.value}</span>
        </div>
      ) : editing ? (
        <InlineEditor value={field.value} onSave={handleSave} onCancel={handleCancel} />
      ) : (
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

function CheckboxGroupView({
  fields, selectedField, onFieldClick, onFieldsUpdate,
}: {
  fields: Field[];
  selectedField: Field | null;
  onFieldClick: (f: Field) => void;
  onFieldsUpdate: (updates: Array<{ field: Field; newVal: string }>) => void;
}) {
  if (fields.length === 0) return null;
  const { parent } = parseCheckboxLabel(fields[0].label);

  // Find the selected/checked option
  const activeField = fields.find(f => {
    const v = f.value.trim().toLowerCase();
    return v === 'yes' || v === 'true' || v === '✓';
  });

  const handleChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const selectedLabel = e.target.value;
    if (!selectedLabel) return;
    const targetField = fields.find(f => parseCheckboxLabel(f.label).option === selectedLabel);
    if (!targetField) return;

    // Trigger field selection in document review panel
    onFieldClick(targetField);

    // Prepare batch updates
    const updates: Array<{ field: Field; newVal: string }> = [];
    fields.forEach(f => {
      const isTarget = f === targetField;
      const currentVal = f.value.trim().toLowerCase();
      let positiveVal = '✓';
      let negativeVal = '✗';
      if (currentVal === 'yes' || currentVal === 'no') {
        positiveVal = 'yes';
        negativeVal = 'no';
      } else if (currentVal === 'true' || currentVal === 'false') {
        positiveVal = 'true';
        negativeVal = 'false';
      }
      updates.push({ field: f, newVal: isTarget ? positiveVal : negativeVal });
    });
    onFieldsUpdate(updates);
  };

  const isGroupSelected = fields.some(f => f === selectedField);

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      gap: 6,
      padding: '8px 10px',
      border: `1px solid ${isGroupSelected ? 'var(--color-primary)' : 'var(--color-border)'}`,
      borderRadius: 'var(--radius-md)',
      background: isGroupSelected ? 'var(--color-primary-light)' : 'var(--color-surface)',
      marginBottom: 6,
      fontFamily: 'var(--font-sans)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 4, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 11, fontWeight: 500, color: 'var(--color-label)' }}>{parent}</span>
        {activeField && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <Badge color={confidenceColor(activeField.confidence)}>
              {confidenceLabel(activeField.confidence)}
            </Badge>
            {activeField.original_value !== null && <Badge color="var(--color-success)">edited</Badge>}
          </div>
        )}
      </div>
      <select
        value={activeField ? parseCheckboxLabel(activeField.label).option : ''}
        onChange={handleChange}
        style={{
          width: '100%',
          padding: '6px 8px',
          borderRadius: 'var(--radius-sm)',
          border: '1px solid var(--color-border)',
          background: 'var(--color-surface)',
          color: 'var(--color-text)',
          fontSize: 13,
          outline: 'none',
          cursor: 'pointer',
        }}
      >
        <option value="">-- Select option --</option>
        {fields.map(f => {
          const { option } = parseCheckboxLabel(f.label);
          return (
            <option key={f.label} value={option}>
              {option}
            </option>
          );
        })}
      </select>
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

  const handleBatchValueChange = useCallback((updates: Array<{ field: Field; newVal: string }>) => {
    const updateMap = new Map<Field, string>();
    for (const u of updates) {
      updateMap.set(u.field, u.newVal);
    }
    onFieldsUpdated(fields.map(f => {
      if (updateMap.has(f)) {
        const newVal = updateMap.get(f)!;
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
      const checkboxFieldsMap = new Map<string, Field[]>();
      const otherFields: Field[] = [];

      for (const f of secFields) {
        const match = f.label.match(TABLE_ROW_RE);
        if (match) {
          const sectionPrefix = match[1];
          if (!tableFields.has(sectionPrefix)) tableFields.set(sectionPrefix, []);
          tableFields.get(sectionPrefix)!.push(f);
        } else if (isCheckbox(f)) {
          const { parent } = parseCheckboxLabel(f.label);
          if (!checkboxFieldsMap.has(parent)) {
            checkboxFieldsMap.set(parent, []);
          }
          checkboxFieldsMap.get(parent)!.push(f);
        } else {
          otherFields.push(f);
        }
      }

      map.set(sn, {
        sectionNumber: sn,
        sectionName: name,
        fields: otherFields,
        tables: Array.from(tableFields.values()),
        checkboxGroups: Array.from(checkboxFieldsMap.values()),
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
      <div style={{ flex: 1, overflowY: 'auto', overflowX: 'hidden' }}>
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
                        onFieldsUpdate={handleBatchValueChange}
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
