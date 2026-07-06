interface TokenDisplay {
  total_tokens: number;
  prompt_tokens: number;
  completion_tokens: number;
}

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
  tokenUsage?: TokenDisplay | null;
}

function confidenceColor(conf: number): string {
  if (conf >= 80) return '#22c55e';
  if (conf >= 60) return '#eab308';
  return '#ef4444';
}

function confidenceBg(conf: number): string {
  if (conf >= 80) return '#dcfce7';
  if (conf >= 60) return '#fef9c3';
  return '#fee2e2';
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
  tokenUsage,
}: Props) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '12px 20px',
        background: '#ffffff',
        borderBottom: '1px solid var(--color-border)',
        fontFamily: 'var(--font-sans)',
        position: 'relative',
        zIndex: 10,
        boxShadow: '0 1px 3px rgba(15, 23, 42, 0.02)',
      }}
    >
      <button
        onClick={onBack}
        style={{
          padding: '7px 14px',
          border: '1px solid var(--color-border)',
          borderRadius: 'var(--radius-lg)',
          background: '#ffffff',
          cursor: 'pointer',
          fontSize: 13,
          fontWeight: 700,
          color: 'var(--color-text-secondary)',
          transition: 'all 0.15s ease',
          display: 'inline-flex',
          alignItems: 'center',
          gap: 6,
          boxShadow: '0 1px 2px rgba(15, 23, 42, 0.02)',
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.background = 'var(--color-bg)';
          e.currentTarget.style.borderColor = 'var(--color-border-hover)';
          e.currentTarget.style.color = 'var(--color-text)';
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.background = '#ffffff';
          e.currentTarget.style.borderColor = 'var(--color-border)';
          e.currentTarget.style.color = 'var(--color-text-secondary)';
        }}
      >
        ← Back
      </button>

      {onToggleSidebar && (
        <button
          onClick={onToggleSidebar}
          style={{
            padding: '7px 12px',
            border: `1px solid ${sidebarOpen ? 'var(--color-primary-border)' : 'var(--color-border)'}`,
            borderRadius: 'var(--radius-lg)',
            background: sidebarOpen ? 'var(--color-primary-light)' : '#ffffff',
            cursor: 'pointer',
            fontSize: 13,
            fontWeight: 700,
            color: sidebarOpen ? 'var(--color-primary)' : 'var(--color-text-secondary)',
            transition: 'all 0.15s ease',
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            boxShadow: '0 1px 2px rgba(15, 23, 42, 0.02)',
          }}
          onMouseEnter={(e) => {
            if (!sidebarOpen) {
              e.currentTarget.style.background = 'var(--color-bg)';
              e.currentTarget.style.borderColor = 'var(--color-border-hover)';
            }
          }}
          onMouseLeave={(e) => {
            if (!sidebarOpen) {
              e.currentTarget.style.background = '#ffffff';
              e.currentTarget.style.borderColor = 'var(--color-border)';
            }
          }}
          title={sidebarOpen ? 'Hide sidebar' : 'Show sidebar'}
        >
          {sidebarOpen ? '◂' : '▸'} Sidebar
        </button>
      )}

      {overallConfidence != null && (
        <span style={{
          fontSize: 12,
          fontWeight: 700,
          color: confidenceColor(overallConfidence),
          background: confidenceBg(overallConfidence),
          display: 'inline-flex',
          alignItems: 'center',
          gap: 6,
          padding: '4px 10px',
          borderRadius: 'var(--radius-full)',
        }}>
          <span style={{
            width: 6,
            height: 6,
            borderRadius: '50%',
            background: confidenceColor(overallConfidence),
            display: 'inline-block',
          }} />
          {overallConfidence}% Accuracy
        </span>
      )}

      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: 6,
        color: 'var(--color-text-secondary)',
        fontSize: 13,
      }}>
        <span style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 4,
          padding: '4px 10px',
          background: '#f1f5f9',
          borderRadius: 'var(--radius-md)',
          fontSize: 12,
          fontWeight: 600,
        }}>
          <span style={{ color: 'var(--color-text)' }}>{totalFields}</span>
          <span style={{ color: 'var(--color-text-muted)', fontWeight: 500 }}>fields</span>
        </span>

        <span style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 4,
          padding: '4px 10px',
          background: '#f1f5f9',
          borderRadius: 'var(--radius-md)',
          fontSize: 12,
          fontWeight: 600,
        }}>
          <span style={{ color: 'var(--color-text-muted)' }}>⏱️</span>
          <span style={{ color: 'var(--color-text)' }}>{processingTime != null ? `${processingTime.toFixed(1)}s` : '—'}</span>
        </span>
      </div>

      {tokenUsage && (
        <span style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 4,
          padding: '4px 10px',
          background: '#f1f5f9',
          borderRadius: 'var(--radius-md)',
          fontSize: 12,
          color: 'var(--color-text-secondary)',
          fontFamily: 'var(--font-mono)',
          fontWeight: 600,
        }}
          title={`Prompt: ${tokenUsage.prompt_tokens} · Completion: ${tokenUsage.completion_tokens}`}
        >
          <span style={{ color: 'var(--color-warning)' }}>⚡</span>
          <span>{tokenUsage.total_tokens.toLocaleString()}</span>
          <span style={{ color: 'var(--color-text-muted)', fontFamily: 'var(--font-sans)', fontWeight: 500 }}>tokens</span>
        </span>
      )}

      <div style={{ flex: 1 }} />

      <div style={{ display: 'flex', gap: 4, alignItems: 'center', flexShrink: 0 }}>
        {currentPage > 1 && (
          <button
            onClick={() => onPageChange(currentPage - 1)}
            style={{
              padding: '6px 10px',
              fontSize: 14,
              fontWeight: 700,
              border: '1px solid var(--color-border)',
              borderRadius: 'var(--radius-md)',
              background: '#ffffff',
              cursor: 'pointer',
              color: 'var(--color-text-tertiary)',
              transition: 'all 0.15s ease',
              lineHeight: 1,
              boxShadow: '0 1px 2px rgba(15, 23, 42, 0.02)',
            }}
            onMouseEnter={e => { e.currentTarget.style.background = 'var(--color-bg)'; e.currentTarget.style.borderColor = 'var(--color-border-hover)'; }}
            onMouseLeave={e => { e.currentTarget.style.background = '#ffffff'; e.currentTarget.style.borderColor = 'var(--color-border)'; }}
          >
            ‹
          </button>
        )}

        <select
          value={currentPage}
          onChange={(e) => onPageChange(Number(e.target.value))}
          style={{
            height: 28,
            fontSize: 12,
            fontWeight: 700,
            border: '1px solid var(--color-border)',
            borderRadius: 'var(--radius-md)',
            background: '#ffffff',
            color: 'var(--color-text)',
            cursor: 'pointer',
            padding: '0 8px',
            outline: 'none',
            boxShadow: '0 1px 2px rgba(15, 23, 42, 0.02)',
            marginRight: 4,
          }}
        >
          {Array.from({ length: numPages }, (_, i) => {
            const p = i + 1;
            return <option key={p} value={p}>Page {p} of {numPages}</option>;
          })}
        </select>

        <div style={{
          display: 'flex',
          gap: 3,
          overflowX: 'auto',
          overflowY: 'hidden',
          maxWidth: 220,
          flexShrink: 0,
          scrollBehavior: 'smooth',
          padding: '2px 0',
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
                  minWidth: 28,
                  height: 28,
                  padding: '0 6px',
                  fontSize: 11,
                  fontWeight: isActive ? 700 : 600,
                  border: `1px solid ${isActive ? 'var(--color-primary-border)' : 'var(--color-border)'}`,
                  borderRadius: 'var(--radius-md)',
                  background: isActive ? 'var(--color-primary-light)' : '#ffffff',
                  color: isActive ? 'var(--color-primary)' : 'var(--color-text-secondary)',
                  cursor: 'pointer',
                  flexShrink: 0,
                  transition: 'all 0.15s ease',
                  boxShadow: isActive ? 'none' : '0 1px 2px rgba(15, 23, 42, 0.02)',
                }}
                onMouseEnter={e => {
                  if (!isActive) {
                    e.currentTarget.style.background = 'var(--color-bg)';
                    e.currentTarget.style.borderColor = 'var(--color-border-hover)';
                  }
                }}
                onMouseLeave={e => {
                  if (!isActive) {
                    e.currentTarget.style.background = '#ffffff';
                    e.currentTarget.style.borderColor = 'var(--color-border)';
                  }
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
              padding: '6px 10px',
              fontSize: 14,
              fontWeight: 700,
              border: '1px solid var(--color-border)',
              borderRadius: 'var(--radius-md)',
              background: '#ffffff',
              cursor: 'pointer',
              color: 'var(--color-text-tertiary)',
              transition: 'all 0.15s ease',
              lineHeight: 1,
              boxShadow: '0 1px 2px rgba(15, 23, 42, 0.02)',
            }}
            onMouseEnter={e => { e.currentTarget.style.background = 'var(--color-bg)'; e.currentTarget.style.borderColor = 'var(--color-border-hover)'; }}
            onMouseLeave={e => { e.currentTarget.style.background = '#ffffff'; e.currentTarget.style.borderColor = 'var(--color-border)'; }}
          >
            ›
          </button>
        )}
      </div>
    </div>
  );
}
