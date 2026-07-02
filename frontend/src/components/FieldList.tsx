import { useMemo } from 'react';
import type { Field, Section } from '../types';

const FONT_SIZE = 18;

const KNOWN_SECTIONS: Section[] = [
  { number: 1, name: 'Student Profile', page: 1 },
  { number: 2, name: 'Family Background', page: 1 },
  { number: 3, name: 'Housing Condition', page: 2 },
  { number: 4, name: 'Financial Background', page: 3 },
  { number: 5, name: 'Health Information', page: 5 },
  { number: 6, name: 'Student Commitment', page: 5 },
  { number: 7, name: 'Scholarship Information', page: 6 },
  { number: 8, name: 'Volunteer Observation', page: 6 },
];

interface Props {
  fields: Field[];
  sections: Section[];
  rawText: string;
  selectedField: Field | null;
  onFieldClick: (field: Field) => void;
  jobId: string;
  onFieldsUpdated: (fields: Field[]) => void;
  currentPage: number;
}

function confidenceColor(conf: number): string {
  if (conf >= 80) return '#16a34a';
  if (conf >= 50) return '#d97706';
  return '#dc2626';
}

function confidenceLabel(conf: number): string {
  if (conf >= 80) return 'High';
  if (conf >= 50) return 'Med';
  return 'Low';
}

function inferSection(label: string): number | null {
  const m = label.match(/^(\d+)\./);
  return m ? parseInt(m[1], 10) : null;
}

// Sort key for logical form order: extract leading numbers (e.g. "2.1", "4.6.1")
// then sort numerically, falling back to Y-position.
function fieldSortKey(f: Field): number[] {
  const m = f.label.match(/^(\d+(?:\.\d+)*)/);
  if (m) {
    return m[1].split('.').map(Number);
  }
  // Header fields go first
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
  // Tiebreaker: Y-position (lower = higher on page)
  const ay = a.bbox ? a.bbox[1] : 999999;
  const by = b.bbox ? b.bbox[1] : 999999;
  return ay - by;
}

function effectiveSection(f: Field): number | null {
  return f.section_number != null ? f.section_number : inferSection(f.label);
}

export default function FieldList({ fields, sections, rawText, selectedField, onClick, jobId, currentPage }: Omit<Props, 'onFieldClick' | 'onFieldsUpdated'> & { onClick: (f: Field) => void }) {
  // Build section map
  const sectionMap = useMemo(() => {
    const map = new Map<number, Section>();
    for (const s of sections) map.set(s.number, s);
    for (const ks of KNOWN_SECTIONS) {
      if (!map.has(ks.number)) map.set(ks.number, ks);
    }
    if (rawText) {
      const lines = rawText.split('\n');
      let page = 1;
      for (const line of lines) {
        const pm = line.match(/---\s*Page\s+(\d+)\s*---/i);
        if (pm) { page = parseInt(pm[1], 10); continue; }
        const sm = line.match(/(?:##\s*)?Section\s+(\d+)\s*[—–\-:.]\s*(.+)/i);
        if (sm && !map.has(parseInt(sm[1], 10))) {
          map.set(parseInt(sm[1], 10), { number: parseInt(sm[1], 10), name: sm[2].trim(), page });
        }
      }
    }
    for (const f of fields) {
      const sn = f.section_number;
      if (sn != null && !map.has(sn)) {
        map.set(sn, { number: sn, name: `Section ${sn}`, page: f.page });
      }
    }
    for (const f of fields) {
      const inf = inferSection(f.label);
      if (inf != null && !map.has(inf)) {
        map.set(inf, { number: inf, name: `Section ${inf}`, page: f.page });
      }
    }
    return map;
  }, [sections, rawText, fields]);

  const { headerFields, sectionFields } = useMemo(() => {
    const hf = fields.filter(f => effectiveSection(f) == null);
    const sf = new Map<number, Field[]>();
    for (const f of fields) {
      const sn = effectiveSection(f);
      if (sn == null) continue;
      if (!sf.has(sn)) sf.set(sn, []);
      sf.get(sn)!.push(f);
    }
    for (const [, flds] of sf) {
      flds.sort(fieldCompare);
    }
    return { headerFields: hf, sectionFields: sf };
  }, [fields]);

  const sortedSections = useMemo(() => {
    return Array.from(sectionMap.values())
      .filter(s => sectionFields.has(s.number))
      .sort((a, b) => a.number - b.number);
  }, [sectionMap, sectionFields]);

  const renderField = (f: Field) => {
    const isSelected = selectedField === f;
    const conf = f.confidence;
    const clr = confidenceColor(conf);
    const isCorrected = f.original_value !== null && f.original_value !== '';

    return (
        <div
          key={f.label}
          onClick={() => onClick(f)}
          style={{
            display: 'flex',
            alignItems: 'flex-start',
            gap: 12,
            padding: '8px 12px',
            borderRadius: 'var(--radius-md)',
            border: `1px solid ${isSelected ? 'var(--color-primary)' : isCorrected ? 'var(--color-success-border)' : 'var(--color-border)'}`,
            background: isSelected ? 'var(--color-primary-light)' : isCorrected ? 'var(--color-success-light)' : 'var(--color-surface)',
            cursor: 'pointer',
            transition: 'all var(--transition-fast)',
            fontSize: FONT_SIZE,
            lineHeight: 1.5,
          }}
          onMouseEnter={e => { if (!isSelected) e.currentTarget.style.background = 'var(--color-surface-hover)'; }}
          onMouseLeave={e => { if (!isSelected) e.currentTarget.style.background = isCorrected ? 'var(--color-success-light)' : 'var(--color-surface)'; }}
        >
          <div style={{ flex: 1, minWidth: 0, color: 'var(--color-text)' }}>
            <span style={{ fontSize: FONT_SIZE, fontWeight: 500 }}>{f.label}</span>
            <span style={{ fontSize: 12, color: 'var(--color-text-muted)', fontFamily: 'var(--font-mono)', fontWeight: 400, marginLeft: 8 }}>
              p.{f.page}
            </span>
          </div>

          <div style={{
            textAlign: 'right',
            flexShrink: 0,
            maxWidth: '45%',
            wordBreak: 'break-word',
            fontWeight: 600,
            color: f.value ? 'var(--color-value)' : 'var(--color-text-muted)',
            fontSize: FONT_SIZE,
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            flexWrap: 'wrap',
            justifyContent: 'flex-end',
          }}>
            {f.original_value && (
              <span style={{ textDecoration: 'line-through', color: 'var(--color-text-muted)', fontWeight: 400, fontSize: 14 }}>
                {f.original_value}
              </span>
            )}
            <span>{f.value || <span style={{ fontStyle: 'italic', color: 'var(--color-text-muted)', fontWeight: 400 }}>empty</span>}</span>

            <span style={{
              fontSize: 11, fontWeight: 700, color: '#fff', background: clr,
              padding: '2px 7px', borderRadius: 'var(--radius-full)', lineHeight: '16px',
            }}>
              {confidenceLabel(conf)}
            </span>
          </div>
        </div>
    );
  };

  const renderSection = (sec: Section) => {
    const allFlds = sectionFields.get(sec.number) || [];
    const pageFlds = allFlds.filter(f => f.page === currentPage);
    if (pageFlds.length === 0) return null;

    return (
      <div key={`sec-${sec.number}`} style={{ marginBottom: 16, flexShrink: 0 }}>
        <div style={{
          fontSize: 18, fontWeight: 700, color: 'var(--color-text)',
          padding: '8px 12px', marginBottom: 8,
          background: 'var(--color-primary-light)', borderRadius: 'var(--radius-md)',
          borderLeft: '4px solid var(--color-primary)',
        }}>
          Section {sec.number} — {sec.name}
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {pageFlds.map(renderField)}
        </div>
      </div>
    );
  };

  return (
    <div style={{
      flex: 1,
      overflowY: 'auto',
      minHeight: 0,
      padding: 16,
      display: 'flex',
      flexDirection: 'column',
      gap: 8,
      background: 'var(--color-bg)',
      scrollBehavior: 'smooth',
      position: 'relative',
    }}>
      <div style={{
        fontSize: 14, color: 'var(--color-text-secondary)',
        padding: '0 4px 8px 4px', borderBottom: '2px solid var(--color-border)',
        marginBottom: 8, flexShrink: 0,
        fontWeight: 500,
      }}>
        Page {currentPage}
      </div>

      {/* Header Fields (section=null, page=currentPage) */}
      {(() => {
        const hf = headerFields.filter(f => f.page === currentPage);
        if (hf.length === 0) return null;
        return (
          <div style={{ marginBottom: 16, flexShrink: 0 }}>
            <div style={{
              fontSize: 16, fontWeight: 700, color: 'var(--color-text-tertiary)',
              padding: '6px 12px', marginBottom: 8,
              background: 'var(--color-surface-active)', borderRadius: 'var(--radius-md)',
            }}>
              Header Fields
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {hf.map(renderField)}
            </div>
          </div>
        );
      })()}

      {/* All sections with fields on current page */}
      {sortedSections
        .map(renderSection)
        .filter(Boolean)
      }

      {fields.length === 0 && (
        <p style={{ color: 'var(--color-text-muted)', fontSize: 16, textAlign: 'center', padding: 32 }}>
          No fields extracted yet.
        </p>
      )}
    </div>
  );
}
