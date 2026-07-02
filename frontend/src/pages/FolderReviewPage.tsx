import { useState, useEffect, useCallback, useMemo } from 'react';
import { getResult, getStatus, subscribeToJob } from '../api/client';
import type { Field, JobResult, StatusResponse } from '../types';
import DocumentReview from '../components/DocumentReview';
import PipelineProcessingView from '../components/PipelineProcessingView';

interface Props {
  jobId: string;
  onBack: () => void;
}

export default function FolderReviewPage({ jobId, onBack }: Props) {
  const [result, setResult] = useState<JobResult | null>(null);
  const [fields, setFields] = useState<Field[]>([]);
  const [sections, setSections] = useState<import('../types').Section[]>([]);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState<string>('queued');
  const [statusMessage, setStatusMessage] = useState<string>('');
  const [selectedField, setSelectedField] = useState<Field | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [selectedPdf, setSelectedPdf] = useState<string | null>(null);
  const [filteredFields, setFilteredFields] = useState<Field[]>([]);
  const [progress, setProgress] = useState(0);
  const [overallProgress, setOverallProgress] = useState<number | null>(null);
  const [perPdfProgress, setPdfProgresses] = useState<Record<string, { progress: number; stage: string }>>({});
  const [logs, setLogs] = useState<Array<{ t: string; msg: string }>>([]);
  const [originalName, setOriginalName] = useState<string>('');
  const [elapsed, setElapsed] = useState<number | null>(null);

  const fetchResult = useCallback(async () => {
    try {
      try {
        const st = await getStatus(jobId);
        setStatus(st.status);
        setStatusMessage(st.message || '');
        if (st.log) setLogs(st.log);
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
      setFields(r.fields || []);
      setSections(r.sections || []);
      if (r.processing_time) {
        setElapsed(r.processing_time);
      }

      const pdfs: string[] = r.fields && r.fields.length > 0
        ? [...new Set(r.fields.map((f: any) => f.file).filter(Boolean))] as string[]
        : [];
      const firstPdf = pdfs[0] || null;
      setSelectedPdf(firstPdf);
      if (r.fields && r.fields.length > 0) {
        setCurrentPage(r.fields[0].page);
      }
    } catch { /* ignore */ }
    setLoading(false);
  }, [jobId]);

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
      }
    });
    return () => unsub();
  }, [jobId]);

  useEffect(() => {
    if (!selectedPdf) {
      setFilteredFields(fields);
      return;
    }
    setFilteredFields(fields.filter((f) => (f as any).file === selectedPdf));
  }, [fields, selectedPdf]);

  const handleFieldClick = useCallback((field: Field) => {
    setSelectedField(field);
    setCurrentPage(field.page);
  }, []);

  const handleFieldsUpdated = useCallback((updated: Field[]) => {
    setFields((prev) => {
      if (!selectedPdf) return updated;
      const other = prev.filter((f) => (f as any).file !== selectedPdf);
      return [...other, ...updated];
    });
  }, [selectedPdf]);

  const pdfNames: string[] = result
    ? (result as any).pdf_names || [...new Set(fields.map((f) => (f as any).file).filter(Boolean))] as string[]
    : [];

  const handleSelectPdf = useCallback((name: string) => {
    setSelectedPdf(name);
    setSelectedField(null);
    setCurrentPage(1);
  }, []);

  const getPdfPageCount = useCallback((name: string) => {
    const pdfFields = fields.filter((f) => (f as any).file === name);
    return pdfFields.reduce((max, f) => Math.max(max, f.page), 0) || 1;
  }, [fields]);

  const selectedPdfPageCount = result ? result.num_pages : (selectedPdf ? getPdfPageCount(selectedPdf) : 1);

  const pageOffset = useMemo(() => {
    if (!selectedPdf) return 0;
    let offset = 0;
    for (const name of pdfNames) {
      if (name === selectedPdf) break;
      offset += getPdfPageCount(name);
    }
    return offset;
  }, [pdfNames, selectedPdf, getPdfPageCount]);

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

  if (status !== 'done') {
    const filesList = Object.keys(perPdfProgress).length > 0
      ? Object.keys(perPdfProgress).map((name) => ({ name }))
      : (result as any)?.pdf_names?.map((name: string) => ({ name })) || (pdfNames.length > 0 ? pdfNames.map((name) => ({ name })) : null) || (originalName ? [{ name: originalName }] : []);

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
          <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-text)' }}>PDFs in batch</span>
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
              </div>
            );
          })}
        </div>
      </div>

      {/* Main area: DocumentReview */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {result ? (
          <DocumentReview
            jobId={jobId}
            numPages={selectedPdfPageCount}
            pageOffset={pageOffset}
            fields={filteredFields}
            sections={sections}
            selectedField={selectedField}
            currentPage={currentPage}
            onFieldClick={handleFieldClick}
            onFieldsUpdated={handleFieldsUpdated}
          />
        ) : (
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--color-text-muted)' }}>
            {loading ? 'Loading...' : 'No results available'}
          </div>
        )}
      </div>
    </div>
  );
}
