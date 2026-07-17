import { useState, useEffect, useCallback, useMemo } from 'react';
import { getResult, getStatus, subscribeToJob, correctField, saveToDB } from '../api/client';
import type { Field, JobResult, StatusResponse } from '../types';
import DocumentReview from '../components/DocumentReview';
import PipelineProcessingView from '../components/PipelineProcessingView';
import LogViewer from '../components/LogViewer';

interface Props {
  jobId: string;
  onBack: () => void;
}

export default function FolderReviewPage({ jobId, onBack }: Props) {
  const [result, setResult] = useState<JobResult | null>(null);
  const [sections, setSections] = useState<import('../types').Section[]>([]);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState<string>('queued');
  const [statusMessage, setStatusMessage] = useState<string>('');
  const [selectedField, setSelectedField] = useState<Field | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [selectedPdf, setSelectedPdf] = useState<string | null>(null);
  const [pdfResultsMap, setPdfResultsMap] = useState<Record<string, any>>({});
  const [progress, setProgress] = useState(0);
  const [overallProgress, setOverallProgress] = useState<number | null>(null);
  const [perPdfProgress, setPdfProgresses] = useState<Record<string, { progress: number; stage: string }>>({});
  const [logs, setLogs] = useState<Array<{ t: string; msg: string }>>([]);
  const [originalName, setOriginalName] = useState<string>('');
  const [elapsed, setElapsed] = useState<number | null>(null);
  const [showUpdateModal, setShowUpdateModal] = useState(false);
  const [showLogsModal, setShowLogsModal] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadDone, setUploadDone] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [confirmStep, setConfirmStep] = useState(false);

  const fetchFullLogs = useCallback(async () => {
    try {
      const res = await fetch(`/logs/${jobId}?lines=9999`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (data.log) setLogs(data.log);
    } catch (e) {
      console.error('fetchFullLogs failed:', e);
    }
  }, [jobId]);

  const fetchResult = useCallback(async () => {
    try {
      try {
        const st = await getStatus(jobId);
        setStatus(st.status);
        setStatusMessage(st.message || '');
        if ((st as any).original_name) setOriginalName((st as any).original_name);
      } catch { /* status fetch failed, proceed to result */ }

      const data = await getResult(jobId);
      setStatus(data.status);
      setStatusMessage(data.message || '');
      if (data.status !== 'done') {
        setLoading(false);
        return;
      }
      const r: JobResult = data.result;
      setResult(r);
      if (r.processing_time) {
        setElapsed(r.processing_time);
      }

      const rawResult = data.result as any;
      const pdfsArr: any[] = rawResult.pdfs;
      const names: string[] = rawResult.pdf_names || [];

      setPdfResultsMap(_buildPdfMap(pdfsArr, names, r, originalName, jobId));
      if (pdfsArr && pdfsArr.length > 0) {
        setSelectedPdf(prev => prev ?? (names[0] || Object.keys(pdfsArr[0] || {})[0] || null));
        const firstSections = pdfsArr[0]?.sections;
        if (firstSections) setSections(firstSections);
      } else {
          setSelectedPdf(prev => prev ?? (names[0] || originalName || jobId));
        setSections(r.sections || []);
      }
    } catch (e) {
      console.error('fetchResult failed:', e);
      setStatus('error');
      setStatusMessage('Failed to load pipeline results');
    }
    setLoading(false);
  }, [jobId]);

  const _buildPdfMap = useCallback((
    pdfsArr: any[],
    names: string[],
    r: JobResult,
    origName: string,
    jid: string,
  ): Record<string, any> => {
    if (pdfsArr && pdfsArr.length > 0) {
      const map: Record<string, any> = {};
      for (const pr of pdfsArr) {
        const name = pr.pdf_name || pr.name || '';
        if (name) map[name] = pr;
      }
      return map;
    }
    const singleName = names[0] || origName || jid;
    return {
      [singleName]: {
        fields: r.fields || [],
        sections: r.sections || [],
        num_pages: r.num_pages || 1,
        overall_confidence: r.overall_confidence || 0,
        pdf_name: singleName,
      },
    };
  }, []);

  useEffect(() => {
    fetchResult();
  }, [fetchResult]);

  useEffect(() => {
    if (status === 'done' || status === 'error' || status === 'incomplete') {
      return;
    }
    const unsub = subscribeToJob(jobId, (data) => {
      setStatus(data.status);
      setStatusMessage(data.message || '');
      if (data.log) {
        setLogs(data.log);
      }
      if (data.original_name) {
        setOriginalName(data.original_name);
      }
      const STAGES_KEYS = ['queued', 'preprocessing', 'primary_extraction', 'field_mapping', 'secondary_verification', 'done'];
      const idx = STAGES_KEYS.indexOf(data.status);
      const pct = data.progress?.overall ?? (idx >= 0 ? Math.round((idx / (STAGES_KEYS.length - 1)) * 100) : 0);
      setProgress(pct);
      setOverallProgress(pct);
      if (data.progress?.elapsed != null) {
        setElapsed(data.progress.elapsed);
      }
      if (data.progress?.pdfs) {
        setPdfProgresses(data.progress.pdfs);
      }
      if (data.status === 'done') {
        fetchResult();
        unsub();
      } else if (data.status === 'error' || data.status === 'incomplete') {
        unsub();
      }
    });
    return () => unsub();
  }, [jobId]);

  useEffect(() => {
    if (status === 'done') fetchFullLogs();
  }, [status, fetchFullLogs]);

  const currentPdfResult = selectedPdf ? pdfResultsMap[selectedPdf] : null;
  const displayFields: Field[] = currentPdfResult?.fields || [];
  const displayNumPages: number = currentPdfResult?.num_pages || 1;
  const displayConfidence: number | null = currentPdfResult?.overall_confidence ?? null;

  const pdfNames: string[] = useMemo(() => {
    const fromMap = Object.keys(pdfResultsMap);
    if (fromMap.length > 0) return fromMap;
    return (result as any)?.pdf_names || [];
  }, [pdfResultsMap, result]);

  const handleSelectPdf = useCallback((name: string) => {
    setSelectedPdf(name);
    setSelectedField(null);
    setCurrentPage(1);
    const pdf = pdfResultsMap[name];
    if (pdf?.sections) setSections(pdf.sections);
  }, [pdfResultsMap]);

  const handleFieldClick = useCallback((field: Field) => {
    setSelectedField(field);
    setCurrentPage(field.page);
  }, []);

  const handleFieldsUpdated = useCallback((updated: Field[]) => {
    setPdfResultsMap((prev) => {
      if (!selectedPdf) return prev;
      const entry = prev[selectedPdf];
      if (!entry) return prev;
      return { ...prev, [selectedPdf]: { ...entry, fields: updated } };
    });
    setConfirmStep(true);
  }, [selectedPdf]);

  const changedFields = useMemo(() =>
    displayFields.filter(f => f.is_edited === true),
    [displayFields]
  );

  const groupedChanges = useMemo(() => {
    const groups = new Map<string, { label: string; fields: Field[] }>();

    for (const f of changedFields) {
      const parts = f.label.split(/ — | – | - /);
      if (parts.length >= 2) {
        const prefix = parts[0];
        if (!groups.has(prefix)) {
          const grpFields = displayFields.filter(df =>
            df.label.startsWith(prefix + ' — ') ||
            df.label.startsWith(prefix + ' – ') ||
            df.label.startsWith(prefix + ' - ')
          );
          groups.set(prefix, { label: prefix, fields: grpFields.length > 0 ? grpFields : [f] });
        }
      } else {
        groups.set('__' + f.label, { label: f.label, fields: [f] });
      }
    }

    return Array.from(groups.values()).map(grp => {
      const isCheckboxGroup = grp.fields.length > 1 &&
        grp.fields.some(f => ['yes', 'no'].includes((f.value ?? '').trim().toLowerCase()));

      if (isCheckboxGroup) {
        const oldSel: string[] = [];
        const newSel: string[] = [];
        for (const f of grp.fields) {
          const optName = f.label.split(/ — | – | - /).slice(1).join(' — ');
          const oldVal = f.original_value != null ? f.original_value : f.value;
          if ((oldVal ?? '').trim().toLowerCase() === 'yes') oldSel.push(optName);
          if ((f.value ?? '').trim().toLowerCase() === 'yes') newSel.push(optName);
        }
        const oldStr = oldSel.join(', ') || '(none)';
        const newStr = newSel.join(', ') || '(none)';
        if (oldStr === newStr) return null;
        return { label: grp.label, oldDisplay: oldStr, newDisplay: newStr };
      }

      const f = grp.fields[0];
      return { label: f.label, oldDisplay: f.original_value || '(empty)', newDisplay: f.value || '(empty)' };
    }).filter(Boolean) as { label: string; oldDisplay: string; newDisplay: string }[];
  }, [changedFields, displayFields]);

  const handleConfirmUpload = useCallback(async () => {
    setUploading(true);
    setUploadError(null);
    try {
      const errors: string[] = [];
      const succeededLabels: string[] = [];
      for (const f of changedFields) {
        try {
          await correctField(jobId, f.label, f.value ?? '', selectedPdf ?? undefined);
          succeededLabels.push(f.label);
        } catch (e: any) {
          errors.push(`${f.label}: ${e.message || 'Unknown'}`);
        }
      }
      await saveToDB(jobId, changedFields.map(f => ({ label: f.label, correct_value: f.value ?? '', pdf_name: selectedPdf })));
      setPdfResultsMap((prev) => {
        const next = { ...prev };
        for (const [pdfName, entry] of Object.entries(next)) {
          if (!entry?.fields) continue;
          next[pdfName] = {
            ...entry,
            fields: entry.fields.map((f: Field) => {
              if (!f.is_edited || succeededLabels.includes(f.label)) {
                return { ...f, original_value: null, is_verified: true, is_edited: false };
              }
              return f;
            }),
          };
        }
        return next;
      });
      setConfirmStep(false);
      setUploadDone(true);
      if (errors.length > 0) {
        setUploadError(errors.length + ' field(s) skipped:\n' + errors.join('\n'));
      }
    } catch (e: any) {
      setUploadError(e?.message || 'Upload failed');
    }
    setUploading(false);
  }, [jobId, changedFields, selectedPdf]);

  const handleCloseUpdate = useCallback(() => {
    setShowUpdateModal(false);
    setUploadDone(false);
    setUploadError(null);
    setUploading(false);
  }, []);

  if (loading && !result) {
    return (
      <div style={{
        flex: 1, display: 'flex', fontFamily: 'var(--font-sans)',
        alignItems: 'center', justifyContent: 'center',
        background: 'var(--color-bg)',
      }}>
        <div className="spinner" />
      </div>
    );
  }

  if (status !== 'done' || !result) {
    const progressKeys = Object.keys(perPdfProgress);
    const filteredKeys = progressKeys.filter(k => k !== originalName);
    const fileKeys = filteredKeys.length > 0 ? filteredKeys : progressKeys;
    const filesList = fileKeys.length > 0
      ? fileKeys.map((name) => ({ name }))
      : (result as any)?.pdf_names?.map((name: string) => ({ name })) || [];

    return (
      <PipelineProcessingView
        jobId={jobId}
        files={filesList}
        status={status}
        statusMessage={statusMessage}
        progress={progress}
        overallProgress={overallProgress}
        perPdfProgress={perPdfProgress}
        logs={logs}
        elapsed={elapsed}
        onBack={onBack}
      />
    );
  }

  return (
    <div style={{ flex: 1, display: 'flex', fontFamily: 'var(--font-sans)', overflow: 'hidden', background: 'var(--color-bg)' }}>
      {/* Left sidebar: PDF list */}
      <div style={{
        width: 220, borderRight: '1px solid var(--color-border)',
        background: 'var(--color-surface)', flexShrink: 0,
        display: 'flex', flexDirection: 'column', overflow: 'hidden',
      }}>
        <div style={{ padding: '10px 12px', borderBottom: '1px solid var(--color-border)' }}>
          <button
            onClick={onBack}
            style={{
              width: '100%', padding: '6px 0', fontSize: 12, fontWeight: 600,
              border: 'none', borderRadius: 'var(--radius-md)',
              background: 'var(--color-primary)', color: '#fff',
              cursor: 'pointer', transition: 'all var(--transition-fast)',
            }}
            onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--color-primary-dark)'; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = 'var(--color-primary)'; }}
          >
            ← Dashboard
          </button>
        </div>
        <div style={{
          padding: '10px 12px', borderBottom: '1px solid var(--color-border)',
          display: 'flex', alignItems: 'center', gap: 6,
        }}>
          <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-text)' }}>
            PDFs in batch {result?.processing_time != null ? `(⏱️ ${result.processing_time}s)` : ''}
          </span>
          <span style={{
            fontSize: 10, color: 'var(--color-text-muted)',
            background: 'var(--color-bg)', padding: '1px 6px', borderRadius: 8,
          }}>
            {pdfNames.length}
          </span>
        </div>
        <div style={{ flex: 1, overflow: 'auto', padding: 4 }}>
          {pdfNames.length === 0 ? (
            <div style={{ padding: 12, fontSize: 11, color: 'var(--color-text-muted)', textAlign: 'center' }}>
              {result ? 'No PDF names available' : 'Loading...'}
            </div>
          ) : pdfNames.map((name) => {
            const isActive = name === selectedPdf;
            const pdfConfidence = pdfResultsMap[name]?.overall_confidence;
            return (
              <div
                key={name}
                onClick={() => handleSelectPdf(name)}
                style={{
                  padding: '7px 8px', borderRadius: 'var(--radius-md)', cursor: 'pointer',
                  borderBottom: '1px solid var(--color-border-light)',
                  background: isActive ? 'var(--color-primary-light)' : 'transparent',
                  borderLeft: isActive ? '3px solid var(--color-primary)' : '3px solid transparent',
                  transition: 'background var(--transition-fast)', fontSize: 12,
                  color: 'var(--color-text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                }}
                onMouseEnter={(e) => { if (!isActive) e.currentTarget.style.background = 'var(--color-bg)'; }}
                onMouseLeave={(e) => { if (!isActive) e.currentTarget.style.background = 'transparent'; }}
              >
                <span>📄 {name}</span>
                {pdfConfidence != null && (
                  <span style={{
                    marginLeft: 6, fontSize: 10, fontWeight: 600,
                    color: pdfConfidence >= 70 ? 'var(--color-success, #16a34a)' : pdfConfidence >= 40 ? 'var(--color-warning, #d97706)' : 'var(--color-error, #dc2626)',
                  }}>
                    {pdfConfidence}%
                  </span>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Main area: DocumentReview */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {/* Navbar */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '8px 16px', borderBottom: '1px solid var(--color-border)',
          background: 'var(--color-surface)', flexShrink: 0,
        }}>
          <span style={{ fontWeight: 600, fontSize: 15, color: 'var(--color-text)' }}>
            📄 Review Fields
            {confirmStep && groupedChanges.length > 0 && (
              <span style={{ marginLeft: 8, fontSize: 12, color: 'var(--color-warning, #d97706)', fontWeight: 500 }}>
                ({groupedChanges.length} unsaved change{groupedChanges.length > 1 ? 's' : ''})
              </span>
            )}
          </span>
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              onClick={() => setShowLogsModal(true)}
              style={{
                padding: '6px 14px', fontSize: 12, fontWeight: 600,
                border: '1px solid var(--color-border)', borderRadius: 'var(--radius-md)',
                background: 'var(--color-bg)', color: 'var(--color-text)',
                cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4,
              }}
            >
              📋 Logs
            </button>
            <button
              onClick={() => setShowUpdateModal(true)}
              disabled={groupedChanges.length === 0}
              style={{
                padding: '6px 14px', fontSize: 12, fontWeight: 600,
                border: 'none', borderRadius: 'var(--radius-md)',
                background: groupedChanges.length === 0 ? 'var(--color-border)' : 'var(--color-primary)',
                color: groupedChanges.length === 0 ? 'var(--color-text-muted)' : '#fff',
                cursor: groupedChanges.length === 0 ? 'not-allowed' : 'pointer',
                display: 'flex', alignItems: 'center', gap: 4,
              }}
            >
              ⚡ Update {groupedChanges.length > 0 ? `(${groupedChanges.length})` : ''}
            </button>
          </div>
        </div>

        {result && selectedPdf ? (
          <DocumentReview
            jobId={jobId}
            numPages={displayNumPages}
            fields={displayFields}
            sections={sections}
            selectedField={selectedField}
            currentPage={currentPage}
            onFieldClick={handleFieldClick}
            onFieldsUpdated={handleFieldsUpdated}
            pdfName={selectedPdf}
          />
        ) : (
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--color-text-muted)' }}>
            {loading ? 'Loading...' : selectedPdf ? 'No results available' : 'Select a PDF from the sidebar'}
          </div>
        )}
      </div>

      {/* ── Update Modal ── */}
      {showUpdateModal && (
        <div
          onClick={handleCloseUpdate}
          style={{
            position: 'fixed', inset: 0, zIndex: 1000,
            background: 'rgba(0,0,0,0.4)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              background: 'var(--color-surface)', borderRadius: 12,
              width: 560, maxHeight: '80vh', display: 'flex', flexDirection: 'column',
              boxShadow: '0 8px 32px rgba(0,0,0,0.2)',
            }}
          >
            {uploadDone ? (
              /* ── Success state: centered message + Done button ── */
              <div style={{
                display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
                padding: '80px 20px', gap: 24,
              }}>
                <div style={{
                  width: 72, height: 72, borderRadius: '50%',
                  background: '#dcfce7', display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 36, color: '#16a34a', fontWeight: 700,
                }}>
                  ✓
                </div>
                <div style={{ fontSize: 20, fontWeight: 700, color: '#166534' }}>
                  Saved Successfully
                </div>
                <button
                  onClick={handleCloseUpdate}
                  style={{
                    marginTop: 12, padding: '10px 48px', fontSize: 15, fontWeight: 600,
                    border: 'none', borderRadius: 'var(--radius-md)',
                    background: 'var(--color-primary)', color: '#fff',
                    cursor: 'pointer',
                  }}
                >
                  Done
                </button>
              </div>
            ) : (
              <>
                {/* Header */}
                <div style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  padding: '16px 20px', borderBottom: '1px solid var(--color-border)',
                }}>
                  <span style={{ fontSize: 16, fontWeight: 700, color: 'var(--color-text)' }}>
                    ⚡ Update Changes
                    {groupedChanges.length > 0 && (
                      <span style={{ marginLeft: 8, fontSize: 13, fontWeight: 500, color: 'var(--color-text-muted)' }}>
                        ({groupedChanges.length} field{groupedChanges.length > 1 ? 's' : ''})
                      </span>
                    )}
                  </span>
                  <button
                    onClick={handleCloseUpdate}
                    style={{ border: 'none', background: 'none', cursor: 'pointer', fontSize: 18, color: 'var(--color-text-muted)', padding: 4 }}
                  >
                    ✕
                  </button>
                </div>

                {/* Body */}
                <div style={{ flex: 1, overflow: 'auto', padding: '12px 20px' }}>
                  {groupedChanges.length === 0 ? (
                    <div style={{ padding: '20px 0', textAlign: 'center', color: 'var(--color-text-muted)', fontSize: 13 }}>
                      No changes detected. Edit field values to see them here.
                    </div>
                  ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                      {groupedChanges.map(g => (
                        <div key={g.label} style={{
                          padding: '10px 12px', borderRadius: 8,
                          border: '1px solid var(--color-border)',
                          background: 'var(--color-bg)',
                        }}>
                          <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--color-text)', marginBottom: 4 }}>
                            {g.label}
                          </div>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
                            <span style={{
                              background: '#fee2e2', color: '#991b1b', padding: '2px 8px',
                              borderRadius: 4, fontFamily: 'var(--font-mono)', fontSize: 12,
                              textDecoration: 'line-through', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis',
                            }}>
                              {g.oldDisplay}
                            </span>
                            <span style={{ color: 'var(--color-text-muted)' }}>→</span>
                            <span style={{
                              background: '#dcfce7', color: '#166534', padding: '2px 8px',
                              borderRadius: 4, fontFamily: 'var(--font-mono)', fontSize: 12,
                              fontWeight: 600, maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis',
                            }}>
                              {g.newDisplay}
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* Footer */}
                <div style={{
                  display: 'flex', justifyContent: 'flex-end', gap: 8,
                  padding: '12px 20px', borderTop: '1px solid var(--color-border)',
                }}>
                  <button
                    onClick={handleCloseUpdate}
                    disabled={uploading}
                    style={{
                      padding: '8px 20px', fontSize: 13, fontWeight: 600,
                      border: '1px solid var(--color-border)', borderRadius: 'var(--radius-md)',
                      background: 'var(--color-bg)', color: 'var(--color-text)',
                      cursor: 'pointer',
                    }}
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleConfirmUpload}
                    disabled={uploading || groupedChanges.length === 0}
                    style={{
                      padding: '8px 20px', fontSize: 13, fontWeight: 600,
                      border: 'none', borderRadius: 'var(--radius-md)',
                      background: groupedChanges.length === 0 ? 'var(--color-border)' : '#16a34a',
                      color: groupedChanges.length === 0 ? 'var(--color-text-muted)' : '#fff',
                      cursor: groupedChanges.length === 0 || uploading ? 'not-allowed' : 'pointer',
                      display: 'flex', alignItems: 'center', gap: 6,
                    }}
                  >
                    {uploading ? '⏳ Uploading...' : '✓ Confirm Upload'}
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {/* ── Logs Modal ── */}
      {showLogsModal && (
        <div
          onClick={() => setShowLogsModal(false)}
          style={{
            position: 'fixed', inset: 0, zIndex: 1000,
            background: 'rgba(0,0,0,0.4)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              background: 'var(--color-surface)', borderRadius: 12,
              width: 760, maxWidth: '92vw', maxHeight: '85vh', display: 'flex', flexDirection: 'column',
              boxShadow: '0 8px 32px rgba(0,0,0,0.2)',
            }}
          >
            <div style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '16px 20px', borderBottom: '1px solid var(--color-border)',
            }}>
              <span style={{ fontSize: 16, fontWeight: 700, color: 'var(--color-text)' }}>
                📋 Processing Logs
              </span>
              <button
                onClick={() => setShowLogsModal(false)}
                style={{ border: 'none', background: 'none', cursor: 'pointer', fontSize: 18, color: 'var(--color-text-muted)', padding: 4 }}
              >
                ✕
              </button>
            </div>
            <div style={{ flex: 1, overflow: 'hidden', padding: '16px 20px', display: 'flex', flexDirection: 'column' }}>
              {logs.length === 0 ? (
                <div style={{ padding: '20px 0', textAlign: 'center', color: 'var(--color-text-muted)', fontSize: 13 }}>
                  No logs available.
                </div>
              ) : (
                <LogViewer logs={logs} height="100%" emptyText="No logs available." />
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
