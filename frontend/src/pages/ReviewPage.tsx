import { useState, useEffect, useCallback, useMemo } from 'react';
import { getResult, saveToDB, getStatus, subscribeToBatch } from '../api/client';
import type { Field, JobResult, StatusResponse } from '../types';
import DocumentReview from '../components/DocumentReview';
import TextViewer from '../components/TextViewer';
import StatusHeader from '../components/StatusHeader';

interface Props {
  jobIds: string[];
  selectedJobId: string;
  onBack: () => void;
  onJobChange: (jobId: string) => void;
  onJobsUpdate: (jobIds: string[]) => void;
}

interface BatchStatus {
  filename: string;
  status: string;
  message: string;
  overall_confidence?: number | null;
  input_type?: string;
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

function Sidebar({ jobs, currentJobId, onSelect }: {
  jobs: Record<string, BatchStatus>;
  currentJobId: string;
  onSelect: (jobId: string) => void;
}) {
  const entries = Object.entries(jobs);
  return (
    <div style={{
      width: 260,
      borderRight: '1px solid var(--color-border)',
      background: 'linear-gradient(180deg, #ffffff 0%, #f8fafc 100%)',
      display: 'flex',
      flexDirection: 'column',
      overflow: 'hidden',
      flexShrink: 0,
      boxShadow: '2px 0 12px rgba(15, 23, 42, 0.03)',
      position: 'relative',
      zIndex: 5,
    }}>
      <div style={{
        padding: '16px 18px',
        borderBottom: '1px solid var(--color-border)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        background: '#ffffff',
      }}>
        <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--color-text)', letterSpacing: '0.03em', textTransform: 'uppercase' }}>
          Batch Documents
        </span>
        <span style={{
          fontSize: 10,
          fontWeight: 700,
          color: 'var(--color-primary)',
          background: 'var(--color-primary-light)',
          padding: '2px 8px',
          borderRadius: 'var(--radius-full)',
        }}>
          {entries.length}
        </span>
      </div>
      <div style={{ flex: 1, overflow: 'auto', padding: '10px 8px' }}>
        {entries.length === 0 ? (
          <div style={{ padding: 24, textAlign: 'center', fontSize: 13, color: 'var(--color-text-muted)', fontStyle: 'italic' }}>
            No jobs found
          </div>
        ) : entries.map(([jid, info]) => {
          const isActive = jid === currentJobId;
          const s = info.status;
          const statusColor = STATUS_COLORS[s] || '#64748b';
          const isProcessing = s !== 'done' && s !== 'error' && s !== 'incomplete';
          const typeIcon = info.input_type === 'image_set' ? '📸' : '📄';
          const displayName = info.filename || jid.slice(0, 12) + '…';

          // Curated status chip background
          const statusBg = s === 'done' ? '#dcfce7' : s === 'error' ? '#fee2e2' : '#f1f5f9';

          return (
            <div
              key={jid}
              onClick={() => jid !== currentJobId && onSelect(jid)}
              style={{
                padding: '12px 14px',
                borderRadius: 'var(--radius-lg)',
                cursor: 'pointer',
                marginBottom: 6,
                background: isActive ? '#ffffff' : 'transparent',
                border: isActive ? '1px solid var(--color-primary-border)' : '1px solid transparent',
                boxShadow: isActive ? '0 4px 12px rgba(37, 99, 235, 0.08)' : 'none',
                transition: 'all 0.2s cubic-bezier(0.4, 0, 0.2, 1)',
                display: 'flex',
                flexDirection: 'column',
                gap: 6,
                transform: isActive ? 'translateX(2px)' : 'none',
              }}
              onMouseEnter={(e) => {
                if (!isActive) {
                  e.currentTarget.style.background = '#ffffff';
                  e.currentTarget.style.borderColor = 'var(--color-border)';
                  e.currentTarget.style.boxShadow = '0 2px 8px rgba(15, 23, 42, 0.04)';
                }
              }}
              onMouseLeave={(e) => {
                if (!isActive) {
                  e.currentTarget.style.background = 'transparent';
                  e.currentTarget.style.borderColor = 'transparent';
                  e.currentTarget.style.boxShadow = 'none';
                }
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 14, filter: 'grayscale(0.2)' }}>{typeIcon}</span>
                <span style={{
                  fontSize: 12,
                  fontWeight: isActive ? 600 : 500,
                  color: isActive ? 'var(--color-primary-dark)' : 'var(--color-text)',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                  flex: 1,
                }}>
                  {displayName}
                </span>
                {isProcessing && (
                  <span className="spinner-sm" style={{ flexShrink: 0 }} />
                )}
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 2 }}>
                <span style={{
                  color: statusColor,
                  background: statusBg,
                  padding: '2px 8px',
                  borderRadius: 'var(--radius-sm)',
                  fontSize: 10,
                  fontWeight: 700,
                  textTransform: 'uppercase',
                  letterSpacing: '0.02em',
                }}>
                  {s.replace(/_/g, ' ')}
                </span>
                {info.overall_confidence != null && (
                  <span style={{
                    fontSize: 11,
                    fontWeight: 600,
                    color: 'var(--color-text-secondary)',
                    background: 'var(--color-border-light)',
                    padding: '1px 6px',
                    borderRadius: 4,
                  }}>
                    {info.overall_confidence}%
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function ReviewPage({ jobIds, selectedJobId, onBack, onJobChange, onJobsUpdate }: Props) {
  const [result, setResult] = useState<JobResult | null>(null);
  const [fields, setFields] = useState<Field[]>([]);
  const [sections, setSections] = useState<import('../types').Section[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedField, setSelectedField] = useState<Field | null>(null);
  const [currentPage, setCurrentPage] = useState(1);

  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [textView, setTextView] = useState(false);
  const [rightPanelFormat, setRightPanelFormat] = useState<'fields' | 'txt'>('fields');
  const [priorityFilter, setPriorityFilter] = useState<'all' | 'high' | 'medium' | 'low'>('all');
  const [jobStatuses, setJobStatuses] = useState<Record<string, BatchStatus>>({});

  const filteredFields = useMemo(() => {
    return fields.filter(f => {
      if (priorityFilter === 'all') return true;
      const isHigh = f.confidence < 0.7 || f.needs_clarification;
      const isMedium = f.confidence >= 0.7 && f.confidence < 0.9 && !f.needs_clarification;
      const isLow = f.confidence >= 0.9 && !f.needs_clarification;
      
      if (priorityFilter === 'high') return isHigh;
      if (priorityFilter === 'medium') return isMedium;
      if (priorityFilter === 'low') return isLow;
      return true;
    });
  }, [fields, priorityFilter]);

  const fetchResult = useCallback(async (jid: string) => {
    setLoading(true);
    setResult(null);
    setFields([]);
    setSections([]);
    setSelectedField(null);
    setCurrentPage(1);
    try {
      const data = await getResult(jid);
      if (data.status !== 'done') {
        setLoading(false);
        return;
      }
      setResult(data.result);
      setFields(data.result.fields);
      setSections(data.result.sections || []);
      if (data.result.fields.length > 0) {
        setCurrentPage(data.result.fields[0].page);
      }
    } catch (e: any) {
      console.error(e);
    }
    setLoading(false);
  }, []);

  const fetchStatuses = useCallback(async () => {
    const updates: Record<string, BatchStatus> = {};
    for (const jid of jobIds) {
      try {
        const s: StatusResponse = await getStatus(jid);
        updates[jid] = {
          filename: '',
          status: s.status,
          message: s.message || '',
          overall_confidence: null,
        };
      } catch {
        updates[jid] = { filename: '', status: 'unknown', message: '', overall_confidence: null };
      }
    }
    setJobStatuses(prev => {
      const next = { ...prev, ...updates };
      // Preserve filenames from /pdfs enrichFilenames
      for (const jid of jobIds) {
        const existing = prev[jid];
        const upd = updates[jid];
        if (upd && existing?.filename && !upd.filename) {
          next[jid] = { ...upd, filename: existing.filename };
        }
      }
      return next;
    });
  }, [jobIds]);

  const enrichFromResult = useCallback(async () => {
    const updates: Record<string, BatchStatus> = {};
    for (const jid of jobIds) {
      try {
        const data = await getResult(jid);
        if (data.status === 'done' && data.result) {
          updates[jid] = {
            filename: '',
            status: 'done',
            message: '',
            overall_confidence: data.result.overall_confidence,
            input_type: data.result.input_type,
          };
        }
      } catch { /* ignore */ }
    }
    if (Object.keys(updates).length > 0) {
      setJobStatuses(prev => ({ ...prev, ...updates }));
    }
  }, [jobIds]);

  const enrichFilenames = useCallback(async () => {
    try {
      const res = await fetch('/pdfs');
      const pdfs = await res.json();
      if (Array.isArray(pdfs)) {
        const updates: Record<string, BatchStatus> = {};
        for (const p of pdfs) {
          if (p.job_id && jobIds.includes(p.job_id)) {
            updates[p.job_id] = {
              filename: p.filename || p.job_id,
              status: p.status || '',
              message: '',
              overall_confidence: p.overall_confidence,
              input_type: p.input_type,
            };
          }
        }
        if (Object.keys(updates).length > 0) {
          setJobStatuses(prev => ({ ...prev, ...updates }));
        }
      }
    } catch { /* ignore */ }
  }, [jobIds]);

  useEffect(() => {
    fetchResult(selectedJobId);
  }, [selectedJobId, fetchResult]);

  useEffect(() => {
    enrichFilenames();
    fetchStatuses();

    const unsub = subscribeToBatch(jobIds, (data: any) => {
      if (data._batch_complete) {
        enrichFromResult();
        return;
      }
      const jid = data.job_id;
      if (!jid) return;
      setJobStatuses(prev => ({
        ...prev,
        [jid]: {
          filename: prev[jid]?.filename || '',
          status: data.status,
          message: data.message || data.progress?.message || '',
          overall_confidence: null,
          input_type: data.progress?.input_type,
        },
      }));
      if (data.status === 'done') {
        enrichFromResult();
      }
    });

    return () => {
      if (unsub) unsub();
    };
  }, [jobIds, fetchStatuses, enrichFromResult, enrichFilenames]);

  const handleFieldClick = useCallback((field: Field) => {
    setSelectedField(field);
    setCurrentPage(field.page);
  }, []);

  const handleFieldsUpdated = useCallback((updated: Field[]) => {
    setFields(updated);
  }, []);

  const handleRawTextUpdated = useCallback(async (newRawText: string) => {
    setResult(prev => prev ? { ...prev, raw_text: newRawText } : null);
    try {
      const res = await fetch(`/update-raw-text/${selectedJobId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ raw_text: newRawText }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
    } catch (e) {
      console.error('Failed to update raw text:', e);
    }
  }, [selectedJobId]);

  const currentJobInfo = jobStatuses[selectedJobId];
  const currentStatus = currentJobInfo?.status || '';
  const isJobDone = currentStatus === 'done';
  const isJobError = currentStatus === 'error' || currentStatus === 'incomplete';

  if (loading && !result) {
    return (
      <div style={{
        flex: 1, display: 'flex', fontFamily: 'var(--font-sans)', overflow: 'hidden',
      }}>
        {sidebarOpen && (
          <Sidebar jobs={jobStatuses} currentJobId={selectedJobId} onSelect={onJobChange} />
        )}
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          {currentJobInfo?.status && currentJobInfo.status !== 'done' ? (
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 14, color: 'var(--color-text-secondary)', marginBottom: 8, textTransform: 'capitalize' }}>
                {currentJobInfo.status.replace(/_/g, ' ')}
              </div>
              <div style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>{currentJobInfo.message}</div>
              <div style={{ marginTop: 20 }} className="spinner" />
            </div>
          ) : (
            <div style={{ textAlign: 'center' }}>
              <div className="spinner" style={{ margin: '0 auto 16px' }} />
              <span style={{ fontSize: 14, color: 'var(--color-text-secondary)' }}>Loading results...</span>
            </div>
          )}
        </div>
      </div>
    );
  }

  if (!isJobDone && result) {
    // result was loaded from cache, still valid
  } else if (!isJobDone) {
    return (
      <div style={{
        flex: 1, display: 'flex', fontFamily: 'var(--font-sans)', overflow: 'hidden',
      }}>
        {sidebarOpen && (
          <Sidebar jobs={jobStatuses} currentJobId={selectedJobId} onSelect={onJobChange} />
        )}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
          <StatusHeader
            jobId={selectedJobId}
            overallConfidence={null}
            totalFields={0}
            processingTime={null}
            numPages={0}
            currentPage={1}
            onPageChange={() => {}}
            onBack={onBack}
            onToggleSidebar={() => setSidebarOpen(o => !o)}
            sidebarOpen={sidebarOpen}
            tokenUsage={null}
          />
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <div style={{ textAlign: 'center' }}>
              <div style={{
                width: 48, height: 48, borderRadius: 'var(--radius-lg)',
                background: isJobError ? 'var(--color-danger-light)' : 'var(--color-primary-light)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                margin: '0 auto 16px', fontSize: 20,
              }}>
                {isJobError ? '❌' : <div className="spinner" />}
              </div>
              <p style={{ color: 'var(--color-text-secondary)', fontSize: 14, marginBottom: 4, fontWeight: 500 }}>
                {isJobError ? 'Job failed' : 'Processing...'}
              </p>
              <p style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>
                {currentJobInfo?.message || currentStatus || 'No status available'}
              </p>
              {isJobError && (
                <button onClick={onBack} style={{
                  marginTop: 12, padding: '8px 16px', border: 'none', borderRadius: 'var(--radius-md)',
                  background: 'var(--color-primary)', color: '#fff', cursor: 'pointer', fontSize: 14, fontWeight: 600,
                }}>← Dashboard</button>
              )}
            </div>
          </div>
        </div>
      </div>
    );
  }

  const totalCorrected = fields.filter((f) => f.original_value !== null).length;

  return (
    <div style={{ flex: 1, display: 'flex', fontFamily: 'var(--font-sans)', overflow: 'hidden' }}>
      {sidebarOpen && (
        <Sidebar jobs={jobStatuses} currentJobId={selectedJobId} onSelect={onJobChange} />
      )}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        <StatusHeader
          jobId={selectedJobId}
          overallConfidence={result?.overall_confidence ?? null}
          totalFields={fields.length}
          processingTime={result?.processing_time ?? null}
          numPages={result?.num_pages ?? 0}
          currentPage={currentPage}
          onPageChange={setCurrentPage}
          onBack={onBack}
          onToggleSidebar={() => setSidebarOpen(o => !o)}
          sidebarOpen={sidebarOpen}
          tokenUsage={result?.token_usage?.total ?? null}
        />

        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          padding: '10px 20px',
          background: '#ffffff',
          borderBottom: '1px solid var(--color-border)',
          boxShadow: '0 1px 3px rgba(15, 23, 42, 0.02)',
          flexWrap: 'wrap',
        }}>
          <span style={{ fontSize: 13, color: 'var(--color-text-secondary)', display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ fontWeight: 700, color: 'var(--color-text)', fontSize: 14 }}>{filteredFields.length}</span>
            <span style={{ color: 'var(--color-text-muted)' }}>/</span>
            <span style={{ color: 'var(--color-text-secondary)', fontWeight: 500 }}>{fields.length}</span>
            <span style={{ color: 'var(--color-text-muted)', marginLeft: 2 }}>fields</span>
            {totalCorrected > 0 && (
              <>
                <span style={{ color: 'var(--color-text-muted)', margin: '0 4px' }}>•</span>
                <span style={{
                  color: 'var(--color-success)',
                  background: 'var(--color-success-light)',
                  padding: '2px 8px',
                  borderRadius: 'var(--radius-full)',
                  fontSize: 11,
                  fontWeight: 600,
                }}>
                  {totalCorrected} corrected
                </span>
              </>
            )}
          </span>

          <div style={{ flex: 1 }} />

          {/* Priority filter */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-text-secondary)', textTransform: 'uppercase', letterSpacing: '0.02em' }}>Filter:</span>
            <div style={{
              display: 'flex',
              padding: 2,
              background: '#f1f5f9',
              borderRadius: 'var(--radius-lg)',
              gap: 2,
            }}>
              {[
                { id: 'all', label: 'All', activeColor: 'var(--color-text)', activeBg: '#ffffff', textColor: 'var(--color-text-secondary)' },
                { id: 'high', label: '🔴 High', activeColor: '#dc2626', activeBg: '#fee2e2', textColor: '#b91c1c' },
                { id: 'medium', label: '🟡 Med', activeColor: '#d97706', activeBg: '#fef3c7', textColor: '#b45309' },
                { id: 'low', label: '🟢 Low', activeColor: '#16a34a', activeBg: '#dcfce7', textColor: '#15803d' },
              ].map(item => {
                const isActive = priorityFilter === item.id;
                return (
                  <button
                    key={item.id}
                    onClick={() => setPriorityFilter(item.id as any)}
                    style={{
                      padding: '5px 12px',
                      fontSize: 11,
                      fontWeight: 700,
                      border: 'none',
                      borderRadius: '6px',
                      cursor: 'pointer',
                      background: isActive ? item.activeBg : 'transparent',
                      color: isActive ? item.activeColor : 'var(--color-text-secondary)',
                      boxShadow: isActive && item.id === 'all' ? '0 1px 3px rgba(0,0,0,0.06)' : 'none',
                      transition: 'all 0.15s ease',
                    }}
                  >
                    {item.label}
                  </button>
                );
              })}
            </div>
          </div>

          <div style={{ width: 1, height: 20, background: 'var(--color-border)' }} />

          {/* View toggle */}
          <button
            onClick={() => setTextView(v => !v)}
            style={{
              padding: '7px 14px',
              fontSize: 12,
              fontWeight: 700,
              border: '1px solid var(--color-border)',
              borderRadius: 'var(--radius-lg)',
              cursor: 'pointer',
              background: textView ? 'var(--color-primary-light)' : '#ffffff',
              color: textView ? 'var(--color-primary)' : 'var(--color-text-secondary)',
              boxShadow: '0 1px 2px rgba(15, 23, 42, 0.02)',
              transition: 'all 0.15s ease',
              display: 'flex',
              alignItems: 'center',
              gap: 6,
            }}
            onMouseEnter={e => {
              if (!textView) {
                e.currentTarget.style.borderColor = 'var(--color-border-hover)';
                e.currentTarget.style.background = 'var(--color-bg)';
              }
            }}
            onMouseLeave={e => {
              if (!textView) {
                e.currentTarget.style.borderColor = 'var(--color-border)';
                e.currentTarget.style.background = '#ffffff';
              }
            }}
          >
            {textView ? '📖 Side-by-Side' : '📝 Full Text View'}
          </button>

          <div style={{ width: 1, height: 20, background: 'var(--color-border)' }} />

          {/* Left panel format selector */}
          {!textView && (
            <div style={{
              display: 'flex',
              padding: 2,
              background: '#f1f5f9',
              borderRadius: 'var(--radius-lg)',
              gap: 2,
            }}>
              <button
                onClick={() => setRightPanelFormat('fields')}
                style={{
                  padding: '5px 12px',
                  fontSize: 11,
                  fontWeight: 700,
                  border: 'none',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  background: rightPanelFormat === 'fields' ? '#ffffff' : 'transparent',
                  color: rightPanelFormat === 'fields' ? 'var(--color-primary)' : 'var(--color-text-secondary)',
                  boxShadow: rightPanelFormat === 'fields' ? '0 1px 3px rgba(0,0,0,0.06)' : 'none',
                  transition: 'all 0.15s ease',
                }}
              >
                Form Fields
              </button>
              <button
                onClick={() => setRightPanelFormat('txt')}
                style={{
                  padding: '5px 12px',
                  fontSize: 11,
                  fontWeight: 700,
                  border: 'none',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  background: rightPanelFormat === 'txt' ? '#ffffff' : 'transparent',
                  color: rightPanelFormat === 'txt' ? 'var(--color-primary)' : 'var(--color-text-secondary)',
                  boxShadow: rightPanelFormat === 'txt' ? '0 1px 3px rgba(0,0,0,0.06)' : 'none',
                  transition: 'all 0.15s ease',
                }}
              >
                ✏️ Edit Raw Text
              </button>
            </div>
          )}

          <div style={{ width: 1, height: 20, background: 'var(--color-border)' }} />

          {/* Save to DB */}
          <button
            onClick={async () => {
              try {
                await saveToDB(selectedJobId);
                alert('Saved to database successfully!');
              } catch (e: any) {
                alert('Failed to save to database: ' + (e.message || 'Unknown error'));
              }
            }}
            style={{
              padding: '7px 16px',
              fontSize: 12,
              fontWeight: 700,
              border: 'none',
              borderRadius: 'var(--radius-lg)',
              cursor: 'pointer',
              background: 'linear-gradient(135deg, #10b981 0%, #059669 100%)',
              color: '#ffffff',
              boxShadow: '0 2px 6px rgba(16, 185, 129, 0.2)',
              transition: 'all 0.15s ease',
              display: 'flex',
              alignItems: 'center',
              gap: 6,
            }}
            onMouseEnter={e => {
              e.currentTarget.style.filter = 'brightness(1.05)';
              e.currentTarget.style.transform = 'translateY(-1px)';
              e.currentTarget.style.boxShadow = '0 4px 12px rgba(16, 185, 129, 0.3)';
            }}
            onMouseLeave={e => {
              e.currentTarget.style.filter = 'none';
              e.currentTarget.style.transform = 'none';
              e.currentTarget.style.boxShadow = '0 2px 6px rgba(16, 185, 129, 0.2)';
            }}
          >
            💾 Save to Database
          </button>
        </div>

        <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
          {textView && result?.raw_text ? (
            <TextViewer
              rawText={result.raw_text}
              fields={filteredFields}
              sections={sections}
              selectedField={selectedField}
              currentPage={currentPage}
              jobId={selectedJobId}
              onFieldClick={handleFieldClick}
              onFieldsUpdated={handleFieldsUpdated}
              onPageChange={setCurrentPage}
              numPages={result?.num_pages ?? 0}
            />
          ) : (
            <DocumentReview
              jobId={selectedJobId}
              numPages={result?.num_pages ?? 0}
              fields={filteredFields}
              sections={sections}
              selectedField={selectedField}
              currentPage={currentPage}
              onFieldClick={handleFieldClick}
              onFieldsUpdated={handleFieldsUpdated}
              rawText={result?.raw_text}
              rightPanelFormat={rightPanelFormat}
              onRawTextUpdated={handleRawTextUpdated}
            />
          )}
        </div>
      </div>
    </div>
  );
}
