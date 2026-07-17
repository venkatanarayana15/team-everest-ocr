import { useState, useEffect, useCallback, useMemo } from 'react';
import { getResult, saveToDB, getStatus, subscribeToBatch, listPDFs, updateRawText, correctField } from '../api/client';
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
      width: 240, borderRight: '1px solid var(--color-border)', background: 'var(--color-surface)',
      display: 'flex', flexDirection: 'column', overflow: 'hidden', flexShrink: 0,
    }}>
      <div style={{
        padding: '10px 12px', borderBottom: '1px solid var(--color-border)',
        display: 'flex', alignItems: 'center', gap: 6,
      }}>
        <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-text)' }}>Batch Jobs</span>
        <span style={{ fontSize: 10, color: 'var(--color-text-muted)', background: 'var(--color-bg)', padding: '1px 6px', borderRadius: 8 }}>
          {entries.length}
        </span>
      </div>
      <div style={{ flex: 1, overflow: 'auto', padding: 4 }}>
        {entries.length === 0 ? (
          <div style={{ padding: 16, textAlign: 'center', fontSize: 11, color: 'var(--color-text-muted)' }}>
            No jobs
          </div>
        ) : entries.map(([jid, info]) => {
          const isActive = jid === currentJobId;
          const s = info.status;
          const statusColor = STATUS_COLORS[s] || '#64748b';
          const isProcessing = s !== 'done' && s !== 'error' && s !== 'incomplete';
          const typeIcon = info.input_type === 'image_set' ? '🖼️' : '📄';
          const displayName = info.filename || jid.slice(0, 12) + '…';
          return (
            <div
              key={jid}
              onClick={() => jid !== currentJobId && onSelect(jid)}
              style={{
                padding: '7px 8px', borderRadius: 'var(--radius-md)', cursor: 'pointer',
                borderBottom: '1px solid var(--color-border-light)',
                background: isActive ? 'var(--color-primary-light)' : 'transparent',
                borderLeft: isActive ? '3px solid var(--color-primary)' : '3px solid transparent',
                transition: 'background var(--transition-fast)',
              }}
              onMouseEnter={(e) => { if (!isActive) e.currentTarget.style.background = 'var(--color-bg)'; }}
              onMouseLeave={(e) => { if (!isActive) e.currentTarget.style.background = 'transparent'; }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                <span style={{ fontSize: 12 }}>{typeIcon}</span>
                <span style={{
                  fontSize: 11, fontWeight: 500, color: 'var(--color-text)',
                  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1,
                }}>
                  {displayName}
                </span>
                {isProcessing && (
                  <span className="spinner-sm" style={{ flexShrink: 0 }} />
                )}
              </div>
              <div style={{ display: 'flex', gap: 4, marginTop: 1, fontSize: 10, alignItems: 'center' }}>
                <span style={{ color: statusColor, fontWeight: 600 }}>{s.replace(/_/g, ' ')}</span>
                {info.overall_confidence != null && (
                  <span style={{ color: 'var(--color-text-muted)' }}>{info.overall_confidence}%</span>
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
      if (data.status === 'done' && data.result) {
        setResult(data.result);
        setFields(data.result.fields);
        setSections(data.result.sections || []);
        if (data.result.fields.length > 0) {
          setCurrentPage(data.result.fields[0].page);
        }
      }
    } catch (e: any) {
      console.error('fetchResult failed:', e);
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
      const pdfs = await listPDFs();
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
      await updateRawText(selectedJobId, newRawText);
    } catch (e) {
      console.error('Failed to update raw text:', e);
      alert('Failed to persist text edit. Please retry.');
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

  if (!isJobDone && !result) {
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

  const totalCorrected = fields.filter((f) => f.is_edited === true).length;

  const [showMetrics, setShowMetrics] = useState(false);
  const [metricsData, setMetricsData] = useState<any>(null);
  const [analyticsData, setAnalyticsData] = useState<any>(null);
  const [metricsLoading, setMetricsLoading] = useState(false);
  const [metricsTab, setMetricsTab] = useState<'flat' | 'db'>('db');

  const loadMetrics = useCallback(async () => {
    setMetricsLoading(true);
    await Promise.all([
      fetch('/metrics?top=20').then(r => r.json()).then(setMetricsData).catch(() => setMetricsData(null)),
      fetch('/analytics/frequently-edited?limit=20').then(r => r.json()).then(setAnalyticsData).catch(() => setAnalyticsData(null)),
    ]);
    setMetricsLoading(false);
  }, []);

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
          display: 'flex', alignItems: 'center', gap: 8,
          padding: '4px 16px', background: 'var(--color-bg)',
          borderBottom: '1px solid var(--color-border)',
        }}>
          <span style={{ fontSize: 13, color: 'var(--color-text-secondary)', display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ fontWeight: 600, color: 'var(--color-text)' }}>{filteredFields.length}</span> / <span style={{ color: 'var(--color-text-muted)' }}>{fields.length}</span> fields
            {totalCorrected > 0 && (
              <> · <span style={{ color: 'var(--color-success)', fontWeight: 600 }}>{totalCorrected}</span> corrected</>
            )}
          </span>

          {/* Priority filter */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginLeft: 8 }}>
            <span style={{ fontSize: 12, fontWeight: 500, color: 'var(--color-text-secondary)' }}>Priority:</span>
            <div style={{ display: 'flex', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-md)', overflow: 'hidden', background: 'var(--color-surface)' }}>
              <button
                onClick={() => setPriorityFilter('all')}
                style={{
                  padding: '5px 10px', fontSize: 11, fontWeight: 600, border: 'none',
                  borderRight: '1px solid var(--color-border)', cursor: 'pointer',
                  background: priorityFilter === 'all' ? 'var(--color-border-light)' : 'transparent',
                  color: priorityFilter === 'all' ? 'var(--color-text)' : 'var(--color-text-secondary)',
                  transition: 'all var(--transition-fast)',
                }}
              >
                All
              </button>
              <button
                onClick={() => setPriorityFilter('high')}
                style={{
                  padding: '5px 10px', fontSize: 11, fontWeight: 600, border: 'none',
                  borderRight: '1px solid var(--color-border)', cursor: 'pointer',
                  background: priorityFilter === 'high' ? '#fef2f2' : 'transparent',
                  color: priorityFilter === 'high' ? '#dc2626' : 'var(--color-text-secondary)',
                  transition: 'all var(--transition-fast)',
                }}
                title="Low confidence fields (<70%) or needs clarification"
              >
                🔴 High
              </button>
              <button
                onClick={() => setPriorityFilter('medium')}
                style={{
                  padding: '5px 10px', fontSize: 11, fontWeight: 600, border: 'none',
                  borderRight: '1px solid var(--color-border)', cursor: 'pointer',
                  background: priorityFilter === 'medium' ? '#fffbeb' : 'transparent',
                  color: priorityFilter === 'medium' ? '#d97706' : 'var(--color-text-secondary)',
                  transition: 'all var(--transition-fast)',
                }}
                title="Medium confidence fields (70% - 90%)"
              >
                🟡 Med
              </button>
              <button
                onClick={() => setPriorityFilter('low')}
                style={{
                  padding: '5px 10px', fontSize: 11, fontWeight: 600, border: 'none',
                  cursor: 'pointer',
                  background: priorityFilter === 'low' ? '#f0fdf4' : 'transparent',
                  color: priorityFilter === 'low' ? '#16a34a' : 'var(--color-text-secondary)',
                  transition: 'all var(--transition-fast)',
                }}
                title="High confidence fields (>=90%)"
              >
                🟢 Low
              </button>
            </div>
          </div>

          <div style={{ width: 1, height: 16, background: 'var(--color-border)', margin: '0 4px' }} />

          <button
            onClick={() => setTextView(v => !v)}
            style={{
              padding: '6px 12px', fontSize: 12, fontWeight: 600,
              border: `1px solid ${textView ? 'var(--color-primary)' : 'var(--color-border-hover)'}`,
              borderRadius: 'var(--radius-md)',
              cursor: 'pointer',
              background: textView ? 'var(--color-primary-light)' : 'var(--color-surface)',
              color: textView ? 'var(--color-primary)' : 'var(--color-text-secondary)',
              transition: 'all var(--transition-fast)',
            }}
            title={textView ? 'Switch to side-by-side view' : 'Switch to full text view'}
          >
            {textView ? '🖼️ Side-by-Side' : '📝 Full Text'}
          </button>

          <div style={{ width: 1, height: 16, background: 'var(--color-border)', margin: '0 4px' }} />

          <button
            onClick={() => { loadMetrics(); setShowMetrics(true); }}
            style={{
              padding: '6px 12px', fontSize: 12, fontWeight: 600,
              border: '1px solid var(--color-border-hover)',
              borderRadius: 'var(--radius-md)',
              cursor: 'pointer',
              background: 'var(--color-surface)',
              color: 'var(--color-text-secondary)',
              transition: 'all var(--transition-fast)',
            }}
            title="View frequently corrected fields"
          >
            📊 Metrics
          </button>

          <div style={{ width: 1, height: 16, background: 'var(--color-border)', margin: '0 4px' }} />

          <button
            onClick={async () => {
              try {
                const edited = fields.filter(f => f.is_edited);
                const pdfName = result?.batch ? result?.pdf_names?.[0] : undefined;
                const errors: string[] = [];
                const succeededLabels: string[] = [];
                for (const f of edited) {
                  try {
                    await correctField(selectedJobId, f.label, f.value ?? '', pdfName);
                    succeededLabels.push(f.label);
                  } catch (e: any) {
                    errors.push(`${f.label}: ${e.message || 'Unknown'}`);
                  }
                }
                await saveToDB(selectedJobId, edited.map(f => ({ label: f.label, correct_value: f.value ?? '' })));
                setFields(prev => prev.map(f => {
                  if (!f.is_edited || succeededLabels.includes(f.label)) {
                    return { ...f, original_value: null, is_edited: false, is_verified: true };
                  }
                  return f;
                }));
                if (errors.length === 0) {
                  alert('Saved to database successfully!');
                } else {
                  alert('Saved to database with ' + errors.length + ' field(s) skipped:\n' + errors.join('\n'));
                }
              } catch (e: any) {
                alert('Failed to save to database: ' + (e.message || 'Unknown error'));
              }
            }}
            style={{
              padding: '6px 12px', fontSize: 12, fontWeight: 600,
              border: '1px solid var(--color-border-hover)',
              borderRadius: 'var(--radius-md)',
              cursor: 'pointer',
              background: 'var(--color-surface)',
              color: 'var(--color-text)',
              transition: 'all var(--transition-fast)',
            }}
            title="Save extraction results to database"
          >
            💾 Save to DB
          </button>

          {!textView && (
            <div style={{
              display: 'flex',
              border: '1px solid var(--color-border)',
              borderRadius: 'var(--radius-md)',
              overflow: 'hidden',
              background: 'var(--color-surface)',
            }}>
              <button
                onClick={() => setRightPanelFormat('fields')}
                style={{
                  padding: '5px 12px', fontSize: 12, fontWeight: 600,
                  border: 'none',
                  borderRight: '1px solid var(--color-border)',
                  cursor: 'pointer',
                  background: rightPanelFormat === 'fields' ? 'var(--color-primary-light)' : 'transparent',
                  color: rightPanelFormat === 'fields' ? 'var(--color-primary)' : 'var(--color-text-secondary)',
                  transition: 'all var(--transition-fast)',
                }}
              >
                Fields View
              </button>
              <button
                onClick={() => setRightPanelFormat('txt')}
                style={{
                  padding: '5px 12px', fontSize: 12, fontWeight: 600,
                  border: 'none',
                  cursor: 'pointer',
                  background: rightPanelFormat === 'txt' ? 'var(--color-primary-light)' : 'transparent',
                  color: rightPanelFormat === 'txt' ? 'var(--color-primary)' : 'var(--color-text-secondary)',
                  transition: 'all var(--transition-fast)',
                }}
              >
                📝 Edit Page Text
              </button>
            </div>
          )}
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
              pdfName={result?.batch ? result?.pdf_names?.[0] : null}
            />
          )}
        </div>
      </div>

      {showMetrics && (
        <div style={{
          position: 'fixed', inset: 0, zIndex: 1000,
          background: 'rgba(0,0,0,0.4)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }} onClick={() => setShowMetrics(false)}>
          <div style={{
            background: 'var(--color-surface)', borderRadius: 'var(--radius-lg)',
            padding: 24, maxWidth: 700, width: '90%', maxHeight: '80vh',
            overflow: 'auto', boxShadow: '0 8px 32px rgba(0,0,0,0.2)',
          }} onClick={e => e.stopPropagation()}>
            <div style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              marginBottom: 16,
            }}>
              <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700 }}>
                📊 Field Correction Metrics
              </h2>
              <button onClick={() => setShowMetrics(false)} style={{
                background: 'none', border: 'none', cursor: 'pointer',
                fontSize: 20, color: 'var(--color-text-muted)',
              }}>✕</button>
            </div>

            {metricsLoading && <p style={{ color: 'var(--color-text-secondary)', fontSize: 14 }}>Loading...</p>}

            {!metricsLoading && (
              <>
                <div style={{ display: 'flex', gap: 4, marginBottom: 16 }}>
                  <button
                    onClick={() => setMetricsTab('db')}
                    style={{
                      padding: '6px 14px', fontSize: 12, fontWeight: 600, border: 'none',
                      borderRadius: 'var(--radius-md)', cursor: 'pointer',
                      background: metricsTab === 'db' ? 'var(--color-primary)' : 'var(--color-border-light)',
                      color: metricsTab === 'db' ? '#fff' : 'var(--color-text-secondary)',
                    }}
                  >📀 All Time (DB)</button>
                  <button
                    onClick={() => setMetricsTab('flat')}
                    style={{
                      padding: '6px 14px', fontSize: 12, fontWeight: 600, border: 'none',
                      borderRadius: 'var(--radius-md)', cursor: 'pointer',
                      background: metricsTab === 'flat' ? 'var(--color-primary)' : 'var(--color-border-light)',
                      color: metricsTab === 'flat' ? '#fff' : 'var(--color-text-secondary)',
                    }}
                  >📁 Current Session (File)</button>
                </div>

                {metricsTab === 'db' && !analyticsData && (
                  <p style={{ color: 'var(--color-text-secondary)', fontSize: 14 }}>DB analytics unavailable.</p>
                )}

                {metricsTab === 'db' && analyticsData && analyticsData.total_fields === 0 && (
                  <p style={{ color: 'var(--color-text-secondary)', fontSize: 14 }}>No corrections logged yet.</p>
                )}

                {metricsTab === 'db' && analyticsData && analyticsData.total_fields > 0 && (
                  <>
                    <p style={{ fontSize: 13, color: 'var(--color-text-secondary)', marginBottom: 12 }}>
                      Frequently edited fields in DB: <strong>{analyticsData.total_fields}</strong>
                    </p>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                      <thead>
                        <tr style={{ borderBottom: '2px solid var(--color-border)' }}>
                          <th style={{ textAlign: 'left', padding: '6px 8px', fontWeight: 700 }}>#</th>
                          <th style={{ textAlign: 'left', padding: '6px 8px', fontWeight: 700 }}>Field Label</th>
                          <th style={{ textAlign: 'right', padding: '6px 8px', fontWeight: 700 }}>Edit Count</th>
                          <th style={{ textAlign: 'right', padding: '6px 8px', fontWeight: 700 }}>Last Edited</th>
                        </tr>
                      </thead>
                      <tbody>
                        {analyticsData.frequently_edited.map((item: any, i: number) => (
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
                              {item.last_edited ? new Date(item.last_edited).toLocaleDateString() : '-'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </>
                )}

                {metricsTab === 'flat' && !metricsData && (
                  <p style={{ color: 'var(--color-text-secondary)', fontSize: 14 }}>No file-based metrics.</p>
                )}

                {metricsTab === 'flat' && metricsData && metricsData.total_corrections === 0 && (
                  <p style={{ color: 'var(--color-text-secondary)', fontSize: 14 }}>
                    {metricsData.message || 'No human corrections recorded yet.'}
                  </p>
                )}

                {metricsTab === 'flat' && metricsData && metricsData.total_corrections > 0 && (
                  <>
                    <p style={{ fontSize: 13, color: 'var(--color-text-secondary)', marginBottom: 12 }}>
                      Total corrections across all jobs: <strong>{metricsData.total_corrections}</strong>
                    </p>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                      <thead>
                        <tr style={{ borderBottom: '2px solid var(--color-border)' }}>
                          <th style={{ textAlign: 'left', padding: '6px 8px', fontWeight: 700 }}>#</th>
                          <th style={{ textAlign: 'left', padding: '6px 8px', fontWeight: 700 }}>Field Label</th>
                          <th style={{ textAlign: 'right', padding: '6px 8px', fontWeight: 700 }}>Times Corrected</th>
                          <th style={{ textAlign: 'right', padding: '6px 8px', fontWeight: 700 }}>Stability %</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(Object.entries(metricsData.per_field || {}) as [string, any][]).map(([label, info], i) => (
                          <tr key={label} style={{
                            borderBottom: '1px solid var(--color-border-light)',
                            background: i % 2 === 0 ? 'transparent' : 'var(--color-bg)',
                          }}>
                            <td style={{ padding: '6px 8px', color: 'var(--color-text-muted)' }}>{i + 1}</td>
                            <td style={{ padding: '6px 8px', fontWeight: 500 }}>{label}</td>
                            <td style={{
                              padding: '6px 8px', textAlign: 'right',
                              color: info.total_corrections > 10 ? '#dc2626' : info.total_corrections < 3 ? '#16a34a' : 'var(--color-text)',
                              fontWeight: info.total_corrections > 10 ? 700 : 400,
                            }}>{info.total_corrections}</td>
                            <td style={{
                              padding: '6px 8px', textAlign: 'right',
                              color: info.stability_pct < 50 ? '#dc2626' : info.stability_pct < 80 ? '#d97706' : '#16a34a',
                              fontWeight: 500,
                            }}>{info.stability_pct}%</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>

                    {metricsData.per_page && Object.keys(metricsData.per_page).length > 0 && (
                      <>
                        <h3 style={{ margin: '20px 0 8px', fontSize: 14, fontWeight: 600 }}>
                          Per-Page Breakdown
                        </h3>
                        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                          <thead>
                            <tr style={{ borderBottom: '2px solid var(--color-border)' }}>
                              <th style={{ textAlign: 'left', padding: '6px 8px', fontWeight: 700 }}>Page</th>
                              <th style={{ textAlign: 'right', padding: '6px 8px', fontWeight: 700 }}>Corrections</th>
                              <th style={{ textAlign: 'left', padding: '6px 8px', fontWeight: 700 }}>Fields</th>
                            </tr>
                          </thead>
                          <tbody>
                            {(Object.entries(metricsData.per_page) as [string, any][]).map(([page, info]) => (
                              <tr key={page} style={{
                                borderBottom: '1px solid var(--color-border-light)',
                              }}>
                                <td style={{ padding: '6px 8px', fontWeight: 500 }}>
                                  {page === '0' ? 'Header / Global' : `Section ${page}`}
                                </td>
                                <td style={{ padding: '6px 8px', textAlign: 'right' }}>{info.total_corrections}</td>
                                <td style={{ padding: '6px 8px', color: 'var(--color-text-secondary)', fontSize: 12 }}>
                                  {info.fields?.length || 0} fields
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </>
                    )}
                  </>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
