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
      if (r.processing_time) {
        setElapsed(r.processing_time);
      }

      const rawResult = data.result as any;
      const pdfsArr: any[] = rawResult.pdfs;
      const names: string[] = rawResult.pdf_names || [];

      if (pdfsArr && pdfsArr.length > 0) {
        const map: Record<string, any> = {};
        for (const pr of pdfsArr) {
          const name = pr.pdf_name || pr.name || '';
          if (name) map[name] = pr;
        }
        setPdfResultsMap(map);

        const first = names[0] || Object.keys(map)[0] || null;
        setSelectedPdf(first);

        const firstSections = pdfsArr[0]?.sections;
        if (firstSections) setSections(firstSections);
      } else {
        // Single-document fallback
        const singleName = names[0] || originalName || jobId;
        const wrapped: Record<string, any> = {};
        wrapped[singleName] = {
          fields: r.fields || [],
          sections: r.sections || [],
          num_pages: r.num_pages || 1,
          overall_confidence: r.overall_confidence || 0,
          pdf_name: singleName,
        };
        setPdfResultsMap(wrapped);
        setSelectedPdf(singleName);
        setSections(r.sections || []);
      }
    } catch { /* ignore */ }
    setLoading(false);
  }, [jobId, originalName]);

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
  }, []);

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
  }, [selectedPdf]);

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
    </div>
  );
}
