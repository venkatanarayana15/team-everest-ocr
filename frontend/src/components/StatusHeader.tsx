interface Props {
  jobId: string;
  overallConfidence: number | null;
  totalFields: number;
  processingTime: number | null;
  numPages: number;
  currentPage: number;
  onPageChange: (page: number) => void;
  onBack: () => void;
  onToggleSidebar?: () => void;
  sidebarOpen?: boolean;
}

function confidenceColor(conf: number): string {
  if (conf >= 80) return '#22c55e';
  if (conf >= 60) return '#eab308';
  return '#ef4444';
}

export default function StatusHeader({
  overallConfidence,
  totalFields,
  processingTime,
  numPages,
  currentPage,
  onPageChange,
  onBack,
  onToggleSidebar,
  sidebarOpen,
}: Props) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: '6px 12px',
        background: 'var(--color-surface)',
        borderBottom: '1px solid var(--color-border)',
        fontFamily: 'var(--font-sans)',
        position: 'relative',
        zIndex: 10,
        boxShadow: 'var(--shadow-xs)',
      }}
    >
      <button
        onClick={onBack}
        style={{
          padding: '6px 12px',
          border: '1px solid var(--color-border-hover)',
          borderRadius: 'var(--radius-md)',
          background: 'var(--color-surface)',
          cursor: 'pointer',
          fontSize: 14,
          fontWeight: 500,
          color: 'var(--color-text-tertiary)',
          transition: 'all var(--transition-fast)',
          display: 'inline-flex',
          alignItems: 'center',
          gap: 4,
        }}
        onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--color-surface-hover)'; e.currentTarget.style.borderColor = 'var(--color-text-muted)'; }}
        onMouseLeave={(e) => { e.currentTarget.style.background = 'var(--color-surface)'; e.currentTarget.style.borderColor = 'var(--color-border-hover)'; }}
      >
        &larr; Back
      </button>

      {onToggleSidebar && (
        <button
          onClick={onToggleSidebar}
          style={{
            padding: '6px 10px',
            border: `1px solid ${sidebarOpen ? 'var(--color-primary)' : 'var(--color-border-hover)'}`,
            borderRadius: 'var(--radius-md)',
            background: sidebarOpen ? 'var(--color-primary-light)' : 'var(--color-surface)',
            cursor: 'pointer',
            fontSize: 13,
            fontWeight: 500,
            color: sidebarOpen ? 'var(--color-primary)' : 'var(--color-text-secondary)',
            transition: 'all var(--transition-fast)',
            display: 'inline-flex',
            alignItems: 'center',
            gap: 4,
          }}
          title={sidebarOpen ? 'Hide sidebar' : 'Show sidebar'}
        >
          {sidebarOpen ? '◁' : '▷'} Docs
        </button>
      )}

      {overallConfidence != null && (
        <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--color-text)', display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{
            width: 8, height: 8, borderRadius: '50%',
            background: confidenceColor(overallConfidence),
            display: 'inline-block',
          }} />
          {overallConfidence}%
        </span>
      )}

      <div style={{
        display: 'flex', alignItems: 'center', gap: 4,
        color: 'var(--color-text-secondary)', fontSize: 13,
      }}>
        <span style={{
          display: 'inline-flex', alignItems: 'center', gap: 3,
          padding: '2px 8px', background: 'var(--color-bg)', borderRadius: 'var(--radius-sm)',
        }}>
          <span style={{ fontWeight: 500, color: 'var(--color-text-secondary)' }}>{totalFields}</span>
          <span style={{ color: 'var(--color-text-muted)' }}>fields</span>
        </span>
        <span style={{
          display: 'inline-flex', alignItems: 'center', gap: 3,
          padding: '2px 8px', background: 'var(--color-bg)', borderRadius: 'var(--radius-sm)',
        }}>
          <span style={{ fontWeight: 500, color: 'var(--color-text-secondary)' }}>{processingTime != null ? processingTime.toFixed(1) : '—'}</span>
          <span style={{ color: 'var(--color-text-muted)' }}>s</span>
        </span>
      </div>

      <div style={{ flex: 1 }} />

      <div style={{ display: 'flex', gap: 2, alignItems: 'center', flexShrink: 0 }}>
        {currentPage > 1 && (
          <button
            onClick={() => onPageChange(currentPage - 1)}
            style={{
              padding: '3px 8px', fontSize: 13, fontWeight: 500,
              border: '1px solid var(--color-border-hover)', borderRadius: 'var(--radius-sm)',
              background: 'var(--color-surface)', cursor: 'pointer',
              color: 'var(--color-text-tertiary)',
              transition: 'all var(--transition-fast)',
              lineHeight: 1,
            }}
          >
            &lsaquo;
          </button>
        )}

        <select
          value={currentPage}
          onChange={(e) => onPageChange(Number(e.target.value))}
          style={{
            height: 28, fontSize: 13, fontWeight: 500,
            border: '1px solid var(--color-border-hover)', borderRadius: 'var(--radius-sm)',
            background: 'var(--color-surface)', color: 'var(--color-text-tertiary)',
            cursor: 'pointer', padding: '0 4px',
            marginRight: 2,
          }}
        >
          {Array.from({ length: numPages }, (_, i) => {
            const p = i + 1;
            return <option key={p} value={p}>Page {p} / {numPages}</option>;
          })}
        </select>

        <div style={{
          display: 'flex', gap: 2,
          overflowX: 'auto', overflowY: 'hidden',
          maxWidth: 220, flexShrink: 0,
          scrollBehavior: 'smooth',
        }}>
          {Array.from({ length: numPages }, (_, i) => {
            const p = i + 1;
            const isActive = p === currentPage;
            return (
              <button
                key={p}
                onClick={() => {
                  onPageChange(p);
                  const btn = document.getElementById(`page-btn-${p}`);
                  btn?.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
                }}
                id={`page-btn-${p}`}
                style={{
                  minWidth: 30, height: 28, padding: '0 4px',
                  fontSize: 12, fontWeight: isActive ? 700 : 500,
                  border: `1px solid ${isActive ? 'var(--color-primary)' : 'var(--color-border-hover)'}`,
                  borderRadius: 'var(--radius-sm)',
                  background: isActive ? 'var(--color-primary-light)' : 'var(--color-surface)',
                  color: isActive ? 'var(--color-primary)' : 'var(--color-text-tertiary)',
                  cursor: 'pointer', flexShrink: 0,
                  transition: 'all var(--transition-fast)',
                }}
              >
                {p}
              </button>
            );
          })}
        </div>
        {currentPage < numPages && (
          <button
            onClick={() => onPageChange(currentPage + 1)}
            style={{
              padding: '3px 8px', fontSize: 13, fontWeight: 500,
              border: '1px solid var(--color-border-hover)', borderRadius: 'var(--radius-sm)',
              background: 'var(--color-surface)', cursor: 'pointer',
              color: 'var(--color-text-tertiary)',
              transition: 'all var(--transition-fast)',
              lineHeight: 1,
            }}
          >
            &rsaquo;
          </button>
        )}
      </div>
    </div>
  );
}
