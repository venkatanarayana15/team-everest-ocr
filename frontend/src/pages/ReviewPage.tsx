import { useState, useEffect, useCallback, useRef } from 'react';
import { getResult, saveToDB, getStatus } from '../api/client';
import type { Field, JobResult, StatusResponse } from '../types';
import DocumentReview from '../components/DocumentReview';
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
  const [savingToDb, setSavingToDb] = useState(false);
  const [dbSaved, setDbSaved] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [jobStatuses, setJobStatuses] = useState<Record<string, BatchStatus>>({});
  const pollRef = useRef<ReturnType<typeof setInterval> | undefined>(undefined);

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

    pollRef.current = setInterval(() => {
      fetchStatuses();
      enrichFromResult();
    }, 3000);

    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [jobIds, fetchStatuses, enrichFromResult, enrichFilenames]);

  const handleFieldClick = useCallback((field: Field) => {
    setSelectedField(field);
    setCurrentPage(field.page);
  }, []);

  const handleFieldsUpdated = useCallback((updated: Field[]) => {
    setFields(updated);
  }, []);

  const handleSaveToDb = useCallback(async () => {
    if (savingToDb || dbSaved) return;
    setSavingToDb(true);
    try {
      const result = await saveToDB(selectedJobId);
      if (result.status === 'saved') {
        setDbSaved(true);
      }
    } catch (e: any) {
      console.error('Save to DB failed:', e);
    }
    setSavingToDb(false);
  }, [selectedJobId, savingToDb, dbSaved]);

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
        />

        <div style={{
          display: 'flex', alignItems: 'center', gap: 8,
          padding: '4px 16px', background: 'var(--color-bg)',
          borderBottom: '1px solid var(--color-border)',
        }}>
          <span style={{ fontSize: 13, color: 'var(--color-text-secondary)', display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ fontWeight: 600, color: 'var(--color-text)' }}>{fields.length}</span> fields
            {totalCorrected > 0 && (
              <> · <span style={{ color: 'var(--color-success)', fontWeight: 600 }}>{totalCorrected}</span> corrected</>
            )}
          </span>
          <div style={{ flex: 1 }} />
          {selectedJobId && (
            <button
              onClick={handleSaveToDb}
              disabled={savingToDb || dbSaved}
              style={{
                padding: '6px 16px', fontSize: 13, fontWeight: 600,
                border: 'none', borderRadius: 'var(--radius-md)',
                cursor: savingToDb || dbSaved ? 'default' : 'pointer',
                background: dbSaved ? 'var(--color-success-light)' : savingToDb ? 'var(--color-bg)' : 'var(--color-primary)',
                color: dbSaved ? 'var(--color-success-dark)' : savingToDb ? 'var(--color-text-muted)' : '#fff',
                transition: 'all var(--transition-fast)',
              }}>
              {dbSaved ? '✓ Saved to Database' : savingToDb ? 'Saving...' : 'Save to Database'}
            </button>
          )}
        </div>

        <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
          <DocumentReview
            jobId={selectedJobId}
            numPages={result?.num_pages ?? 0}
            fields={fields}
            sections={sections}
            selectedField={selectedField}
            currentPage={currentPage}
            onFieldClick={handleFieldClick}
            onFieldsUpdated={handleFieldsUpdated}
          />
        </div>
      </div>
    </div>
  );
}
