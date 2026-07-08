import { useState, useEffect } from 'react';
import { deleteJob, subscribeNewJobs } from '../api/client';

interface JobEntry {
  job_id: string;
  status: string;
  filename: string;
  overall_confidence?: number | null;
  num_pages?: number | null;
  num_pdfs?: number | null;
  pdf_names: string[];
  created_at?: number;
  processing_time?: number | null;
}

interface Props {
  onSelectBatch: (jobId: string) => void;
}

const STATUS_COLORS: Record<string, string> = {
  done: '#16a34a',
  error: '#ef4444',
  incomplete: '#eab308',
  queued: '#64748b',
  preprocessing: '#3b82f6',
  primary_extraction: '#8b5cf6',
  field_mapping: '#f59e0b',
  secondary_verification: '#06b6d4',
};

function statusBadge(s: string): { bg: string; label: string } {
  const c = STATUS_COLORS[s] || '#64748b';
  return { bg: c, label: s.replace(/_/g, ' ') };
}

export default function DashboardPage({ onSelectBatch }: Props) {
  const [jobs, setJobs] = useState<JobEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [sortOrder, setSortOrder] = useState<'latest' | 'oldest'>('latest');
  const [selectedJobIds, setSelectedJobIds] = useState<string[]>([]);

  // Subscribe to SSE — snapshot populates dashboard, new jobs auto-navigate
  useEffect(() => {
    let knownIds = new Set<string>();

    const unsub = subscribeNewJobs(
      (snapshot) => {
        setJobs(snapshot);
        knownIds = new Set(snapshot.map((j: any) => j.job_id));
        setLoading(false);
      },
      (jobId) => {
        if (!knownIds.has(jobId)) {
          onSelectBatch(jobId);
        }
      },
    );

    return unsub;
  }, [onSelectBatch]);

  const handleDeleteSelected = async () => {
    if (selectedJobIds.length === 0) return;
    if (!window.confirm(`Are you sure you want to delete the selected ${selectedJobIds.length} batch(es)?`)) {
      return;
    }
    try {
      await Promise.all(selectedJobIds.map(id => deleteJob(id)));
      setJobs(prev => prev.filter(j => !selectedJobIds.includes(j.job_id)));
      setSelectedJobIds([]);
    } catch (e) {
      alert('Failed to delete some batches');
    }
  };

  const handleDeleteOne = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!window.confirm('Are you sure you want to delete this batch?')) {
      return;
    }
    try {
      await deleteJob(id);
      setJobs(prev => prev.filter(j => j.job_id !== id));
    } catch (e) {
      alert('Failed to delete batch');
    }
  };

  const sorted = [...jobs].sort((a, b) => {
    const cmp = (a.created_at || 0) - (b.created_at || 0);
    return sortOrder === 'latest' ? -cmp : cmp;
  });

  return (
    <div style={{
      flex: 1, display: 'flex', flexDirection: 'column',
      fontFamily: 'var(--font-sans)', background: 'var(--color-primary-light)',
      overflow: 'hidden',
    }}>
      <header style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '16px 24px', borderBottom: '1px solid var(--color-border)',
        background: 'var(--color-surface)',
      }}>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 700, color: 'var(--color-text)', margin: 0 }}>
            OCR Dashboard
          </h1>
          <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: '2px 0 0' }}>
            {jobs.length} batch{jobs.length !== 1 ? 'es' : ''}
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          {selectedJobIds.length > 0 && (
            <button
              onClick={handleDeleteSelected}
              style={{
                padding: '8px 16px', fontSize: 13, fontWeight: 600,
                border: 'none', borderRadius: 'var(--radius-lg)',
                background: 'var(--color-danger)', color: '#fff',
                cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6,
                transition: 'all var(--transition-fast)',
                boxShadow: '0 2px 8px rgba(239,68,68,0.3)',
              }}
              onMouseEnter={(e) => { e.currentTarget.style.filter = 'brightness(1.08)'; }}
              onMouseLeave={(e) => { e.currentTarget.style.filter = 'none'; }}
            >
              🗑️ Delete Selected ({selectedJobIds.length})
            </button>
          )}
          <div style={{ display: 'flex', gap: 2, background: 'var(--color-bg)', borderRadius: 'var(--radius-md)', padding: 2 }}>
            {(['latest', 'oldest'] as const).map((opt) => (
              <button
                key={opt}
                onClick={() => setSortOrder(opt)}
                style={{
                  padding: '4px 10px', fontSize: 11, fontWeight: 600,
                  border: 'none', borderRadius: 'var(--radius-sm)',
                  background: sortOrder === opt ? 'var(--color-surface)' : 'transparent',
                  color: sortOrder === opt ? 'var(--color-text)' : 'var(--color-text-muted)',
                  cursor: 'pointer', textTransform: 'capitalize',
                  transition: 'all var(--transition-fast)',
                  boxShadow: sortOrder === opt ? 'var(--shadow-xs)' : 'none',
                }}
              >
                {opt}
              </button>
            ))}
          </div>

        </div>
      </header>

      <div style={{ flex: 1, overflow: 'auto', padding: 24 }}>
        {loading ? (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 200 }}>
            <div className="spinner" />
          </div>
        ) : jobs.length === 0 ? (
          <div style={{
            display: 'flex', flexDirection: 'column', alignItems: 'center',
            justifyContent: 'center', height: 300, color: 'var(--color-text-muted)',
          }}>
            <div style={{ fontSize: 48, marginBottom: 12 }}>📂</div>
            <p style={{ fontSize: 15, fontWeight: 500, color: 'var(--color-text-secondary)' }}>
              No completed batches yet
            </p>
            <p style={{ fontSize: 12, marginTop: 4 }}>
              Batches will appear here once processed from Zoho Creator.
            </p>
          </div>
        ) : (
          <div style={{
            display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
            gap: 16,
          }}>
            {sorted.map((j) => {
              const badge = statusBadge(j.status);
              const displayName = j.filename && j.filename !== j.job_id
                ? j.filename : j.pdf_names?.[0] || j.job_id?.slice(0, 20);
              const isChecked = selectedJobIds.includes(j.job_id);
              return (
                <div
                  key={j.job_id}
                  onClick={() => onSelectBatch(j.job_id)}
                  style={{
                    padding: 16, borderRadius: 'var(--radius-xl)',
                    border: isChecked ? '1px solid var(--color-primary)' : '1px solid var(--color-border)',
                    background: 'var(--color-surface)',
                    cursor: 'pointer',
                    transition: 'all var(--transition-fast)',
                    boxShadow: isChecked ? '0 0 0 1px var(--color-primary), var(--shadow-sm)' : 'var(--shadow-sm)',
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.boxShadow = 'var(--shadow-md)';
                    e.currentTarget.style.borderColor = 'var(--color-primary)';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.boxShadow = isChecked ? '0 0 0 1px var(--color-primary), var(--shadow-sm)' : 'var(--shadow-sm)';
                    e.currentTarget.style.borderColor = isChecked ? 'var(--color-primary)' : 'var(--color-border)';
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }} onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        checked={isChecked}
                        onChange={(e) => {
                          setSelectedJobIds(prev =>
                            e.target.checked
                              ? [...prev, j.job_id]
                              : prev.filter(id => id !== j.job_id)
                          );
                        }}
                        style={{ width: 15, height: 15, cursor: 'pointer' }}
                      />
                      <span style={{ fontSize: 24 }}>📁</span>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <span style={{
                        padding: '2px 8px', borderRadius: 10,
                        fontSize: 10, fontWeight: 600, color: '#fff',
                        background: badge.bg, whiteSpace: 'nowrap',
                      }}>
                        {badge.label}
                      </span>
                      <button
                        onClick={(e) => handleDeleteOne(j.job_id, e)}
                        style={{
                          background: 'transparent', border: 'none', cursor: 'pointer',
                          fontSize: 12, padding: '2px 4px', borderRadius: 4,
                          display: 'flex', alignItems: 'center', justifyContent: 'center',
                          color: 'var(--color-text-muted)',
                        }}
                        title="Delete batch"
                      >
                        🗑️
                      </button>
                    </div>
                  </div>
                  <h3 style={{
                    fontSize: 13, fontWeight: 600, color: 'var(--color-text)',
                    margin: 0, overflow: 'hidden', textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }} title={displayName}>
                    {displayName}
                  </h3>
                  {j.created_at && (
                    <div style={{ fontSize: 10, color: 'var(--color-text-muted)', marginTop: 2 }}>
                      {new Date(j.created_at * 1000).toLocaleDateString(undefined, {
                        month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
                      })}
                    </div>
                  )}
                  <div style={{ display: 'flex', gap: 12, marginTop: 8, fontSize: 11, color: 'var(--color-text-muted)' }}>
                    {j.num_pages != null && <span>{j.num_pages} page{j.num_pages !== 1 ? 's' : ''}</span>}
                    {j.num_pdfs != null && <span>{j.num_pdfs} PDF{j.num_pdfs !== 1 ? 's' : ''}</span>}
                    {j.processing_time != null && <span>⏱️ {j.processing_time}s</span>}
                    {j.overall_confidence != null && (
                      <span style={{
                        fontWeight: 600,
                        color: j.overall_confidence >= 70 ? 'var(--color-success)' : j.overall_confidence >= 40 ? '#d97706' : 'var(--color-danger)',
                      }}>
                        {j.overall_confidence}% conf
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
