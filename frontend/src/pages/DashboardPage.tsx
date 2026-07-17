import { useState, useEffect, useCallback } from 'react';
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

  const [showMetrics, setShowMetrics] = useState(false);
  const [metricsData, setMetricsData] = useState<any>(null);
  const [metricsLoading, setMetricsLoading] = useState(false);

  const loadMetrics = useCallback(async () => {
    setMetricsLoading(true);
    try {
      const res = await fetch('/analytics/frequently-edited?limit=20');
      const data = await res.json();
      setMetricsData(data);
    } catch {
      setMetricsData(null);
    }
    setMetricsLoading(false);
  }, []);

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

  const allSelected = jobs.length > 0 && selectedJobIds.length === jobs.length;

  const handleSelectAll = () => {
    if (allSelected) {
      setSelectedJobIds([]);
    } else {
      setSelectedJobIds(jobs.map(j => j.job_id));
    }
  };

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
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {selectedJobIds.length > 0 && (
            <button
              onClick={handleSelectAll}
              style={{
                padding: '6px 12px', fontSize: 12, fontWeight: 600,
                border: 'none', borderRadius: 'var(--radius-lg)',
                background: allSelected ? 'var(--color-bg)' : 'var(--color-primary)',
                color: allSelected ? 'var(--color-text-muted)' : '#fff',
                cursor: 'pointer',
                transition: 'all var(--transition-fast)',
              }}
            >
              {allSelected ? 'Deselect All' : 'Select All'}
            </button>
          )}
          {selectedJobIds.length > 0 && (
            <button
              onClick={handleDeleteSelected}
              style={{
                padding: '6px 12px', fontSize: 12, fontWeight: 600,
                border: 'none', borderRadius: 'var(--radius-lg)',
                background: 'var(--color-danger)', color: '#fff',
                cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4,
                transition: 'all var(--transition-fast)',
                boxShadow: '0 2px 8px rgba(239,68,68,0.3)',
              }}
              onMouseEnter={(e) => { e.currentTarget.style.filter = 'brightness(1.08)'; }}
              onMouseLeave={(e) => { e.currentTarget.style.filter = 'none'; }}
            >
              🗑️ Delete ({selectedJobIds.length})
            </button>
          )}
          <button
            onClick={() => { loadMetrics(); setShowMetrics(true); }}
            style={{
              padding: '6px 12px', fontSize: 12, fontWeight: 600,
              border: '1px solid var(--color-border)',
              borderRadius: 'var(--radius-lg)',
              background: 'var(--color-surface)',
              color: 'var(--color-text)',
              cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4,
              transition: 'all var(--transition-fast)',
              boxShadow: 'var(--shadow-xs)',
            }}
            title="View frequently corrected fields"
          >
            📊 Metrics
          </button>
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

      {showMetrics && (
        <div style={{
          position: 'fixed', inset: 0, zIndex: 1000,
          background: 'rgba(0,0,0,0.4)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }} onClick={() => setShowMetrics(false)}>
          <div style={{
            background: 'var(--color-surface)', borderRadius: 'var(--radius-lg)',
            padding: 24, maxWidth: 650, width: '90%', maxHeight: '80vh',
            overflow: 'auto', boxShadow: '0 8px 32px rgba(0,0,0,0.2)',
          }} onClick={e => e.stopPropagation()}>
            <div style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              marginBottom: 16,
            }}>
              <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700 }}>
                📊 Field Correction Analysis
              </h2>
              <button onClick={() => setShowMetrics(false)} style={{
                background: 'none', border: 'none', cursor: 'pointer',
                fontSize: 20, color: 'var(--color-text-muted)',
              }}>✕</button>
            </div>

            {metricsLoading && <p style={{ color: 'var(--color-text-secondary)', fontSize: 14 }}>Loading...</p>}

            {!metricsLoading && !metricsData && (
              <p style={{ color: 'var(--color-text-secondary)', fontSize: 14 }}>Failed to load metrics.</p>
            )}

            {!metricsLoading && metricsData && metricsData.total_fields === 0 && (
              <p style={{ color: 'var(--color-text-secondary)', fontSize: 14 }}>
                No corrections recorded yet. Corrections will appear here after you start editing fields.
              </p>
            )}

            {!metricsLoading && metricsData && metricsData.total_fields > 0 && (
              <>
                <p style={{ fontSize: 13, color: 'var(--color-text-secondary)', marginBottom: 12 }}>
                  Top fields by correction frequency across all jobs.
                </p>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                  <thead>
                    <tr style={{ borderBottom: '2px solid var(--color-border)' }}>
                      <th style={{ textAlign: 'left', padding: '6px 8px', fontWeight: 700 }}>#</th>
                      <th style={{ textAlign: 'left', padding: '6px 8px', fontWeight: 700 }}>Field Label</th>
                      <th style={{ textAlign: 'right', padding: '6px 8px', fontWeight: 700 }}>Edit Count</th>
                      <th style={{ textAlign: 'right', padding: '6px 8px', fontWeight: 700 }}>Last Edited</th>
                      <th style={{ textAlign: 'center', padding: '6px 8px', fontWeight: 700 }}>Flag</th>
                    </tr>
                  </thead>
                  <tbody>
                    {metricsData.frequently_edited.map((item: any, i: number) => {
                      const now = Date.now();
                      const lastEdit = item.last_edited ? new Date(item.last_edited).getTime() : 0;
                      const daysSinceEdit = lastEdit ? (now - lastEdit) / 86400000 : 999;
                      const isFrequent = item.edit_count > 10;
                      const isRecent = daysSinceEdit < 7;
                      let flag = '';
                      let flagColor = 'transparent';
                      if (isFrequent && isRecent) {
                        flag = '🔴';
                        flagColor = '#fef2f2';
                      } else if (isFrequent) {
                        flag = '🔴';
                        flagColor = 'transparent';
                      } else if (item.edit_count > 3 && isRecent) {
                        flag = '🟡';
                        flagColor = '#fffbeb';
                      } else if (item.edit_count < 3) {
                        flag = '🟢';
                        flagColor = '#f0fdf4';
                      }
                      return (
                        <tr key={item.field_label} style={{
                          borderBottom: '1px solid var(--color-border-light)',
                          background: i % 2 === 0 ? 'transparent' : 'var(--color-bg)',
                        }}>
                          <td style={{ padding: '6px 8px', color: 'var(--color-text-muted)' }}>{i + 1}</td>
                          <td style={{ padding: '6px 8px', fontWeight: 500 }}>{item.field_label}</td>
                          <td style={{
                            padding: '6px 8px', textAlign: 'right',
                            color: item.edit_count > 10 ? '#dc2626' : item.edit_count < 3 ? '#16a34a' : 'var(--color-text)',
                            fontWeight: item.edit_count > 10 ? 700 : 400,
                          }}>{item.edit_count}</td>
                          <td style={{
                            padding: '6px 8px', textAlign: 'right',
                            color: 'var(--color-text-muted)', fontSize: 12,
                          }}>
                            {lastEdit ? new Date(lastEdit).toLocaleDateString(undefined, {
                              month: 'short', day: 'numeric', year: 'numeric',
                            }) : '-'}
                          </td>
                          <td style={{
                            padding: '6px 8px', textAlign: 'center', fontSize: 16,
                          }}>{flag}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                <div style={{
                  marginTop: 16, padding: '12px 16px', borderRadius: 'var(--radius-md)',
                  background: 'var(--color-bg)', fontSize: 12, color: 'var(--color-text-secondary)',
                  lineHeight: 1.6,
                }}>
                  <strong>Legend:</strong><br />
                  🟢 <strong>Stable</strong> — edited fewer than 3 times<br />
                  🟡 <strong>Active</strong> — edited &gt;3 times in the last 7 days<br />
                  🔴 <strong>High frequency</strong> — edited 10+ times across all jobs<br />
                  Fields with 🔴 flags indicate a persistent extraction issue.
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
