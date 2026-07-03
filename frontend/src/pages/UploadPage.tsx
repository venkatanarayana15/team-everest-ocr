import { useState, useRef, useEffect, useCallback } from 'react';
import {
  uploadPDFWithDedup, uploadImages, uploadBatch,
  thumbnailUrl, retryJob, listPDFs, getValidation, processFolder,
  subscribeToJob, subscribeToBatch,
} from '../api/client';
import PipelineProcessingView from '../components/PipelineProcessingView';
interface Props {
  onDone: (jobIds: string[]) => void;
  onBack?: () => void;
}

const MAX_POLL_TIME = 600_000;

type UploadMode = 'pdf' | 'images' | 'zip' | 'batch' | 'folder';
type Phase = 'idle' | 'uploading' | 'processing' | 'error' | 'done';

interface StageDef {
  key: string;
  label: string;
  icon: string;
}
const STAGES: StageDef[] = [
  { key: 'queued',                 label: 'Uploaded',              icon: '📋' },
  { key: 'preprocessing',          label: 'Preprocessing',         icon: '🖼️' },
  { key: 'primary_extraction',     label: 'Primary Extraction',    icon: '🤖' },
  { key: 'field_mapping',          label: 'Field Mapping',         icon: '🗺️' },
  { key: 'secondary_verification', label: 'Verification',          icon: '✅' },
  { key: 'done',                   label: 'Complete',              icon: '🎉' },
];

const STATUS_ICON: Record<string, { emoji: string; label: string }> = {
  queued:                 { emoji: '📋', label: 'Queued' },
  preprocessing:          { emoji: '🖼️', label: 'Preprocessing pages' },
  primary_extraction:     { emoji: '🤖', label: 'Running primary AI extraction' },
  field_mapping:          { emoji: '🗺️', label: 'Mapping fields to bounding boxes' },
  secondary_verification: { emoji: '✅', label: 'Running verification' },
  done:                   { emoji: '🎉', label: 'Complete' },
  error:                  { emoji: '❌', label: 'Error' },
  incomplete:             { emoji: '⚠️', label: 'Incomplete' },
};

function ts(): string {
  return new Date().toLocaleTimeString('en-US', { hour12: false });
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

interface PdfEntry {
  id?: number;
  filename: string;
  job_id?: string;
  status?: string;
  uploaded_at?: string;
  file_hash?: string;
  file_size?: number;
  overall_confidence?: number;
  input_type?: string;
}

function ProgressBar({ value, color }: { value: number; color?: string }) {
  const barColor = color || 'var(--color-primary)';
  return (
    <div style={{ flex: 1, height: 4, background: 'var(--color-border)', borderRadius: 2, overflow: 'hidden', minWidth: 40 }}>
      <div style={{
        width: `${Math.min(100, Math.max(0, value))}%`,
        height: '100%',
        background: value >= 100 ? 'var(--color-success)' : barColor,
        borderRadius: 2,
        transition: 'width 0.3s ease',
      }} />
    </div>
  );
}

function PdfSidebar({ pdfs, onSelect, onRefresh, perPdfProgress, overallProgress }: {
  pdfs: PdfEntry[];
  onSelect: (jobId: string) => void;
  onRefresh: () => void;
  perPdfProgress?: Record<string, { progress: number; stage: string }>;
  overallProgress?: number | null;
}) {
  return (
    <div style={{
      width: 260, borderRight: '1px solid var(--color-border)', background: 'var(--color-surface)',
      display: 'flex', flexDirection: 'column', overflow: 'hidden',
      flexShrink: 0,
    }}>
      <div style={{
        padding: '12px 14px', borderBottom: '1px solid var(--color-border)',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-text)' }}>
          Documents
        </span>
        <button onClick={onRefresh} style={{
          border: 'none', background: 'none', cursor: 'pointer',
          fontSize: 16, color: 'var(--color-text-secondary)', padding: 2,
          borderRadius: 'var(--radius-sm)',
          transition: 'color var(--transition-fast)',
        }} title="Refresh">↻</button>
      </div>

      {overallProgress != null && (
        <div style={{ padding: '8px 12px', borderBottom: '1px solid var(--color-border)' }}>
          <div style={{
            display: 'flex', alignItems: 'center', gap: 6,
            fontSize: 11, color: 'var(--color-text-secondary)', marginBottom: 4,
          }}>
            <span style={{ fontWeight: 600 }}>Overall Progress</span>
            <span style={{ fontWeight: 700, color: 'var(--color-primary)' }}>{overallProgress}%</span>
          </div>
          <ProgressBar value={overallProgress} />
        </div>
      )}

      <div style={{ flex: 1, overflow: 'auto', padding: 4 }}>
        {pdfs.length === 0 ? (
          <div style={{ padding: 16, textAlign: 'center', fontSize: 12, color: 'var(--color-text-muted)' }}>
            No documents uploaded yet
          </div>
        ) : (
          pdfs.map((p, i) => {
            const pp = perPdfProgress?.[p.filename || p.job_id || ''];
            const progressVal = pp?.progress ?? 0;
            const statusVal = pp?.stage || p.status || 'queued';
            const statusColor = statusVal === 'done' ? 'var(--color-success)'
              : statusVal === 'error' ? 'var(--color-danger)'
              : 'var(--color-warning)';
            const typeIcon = '📄';
            return (
              <div
                key={p.job_id || p.filename || i}
                style={{
                  padding: '8px 10px', borderRadius: 'var(--radius-md)',
                  borderBottom: '1px solid var(--color-border-light)',
                  background: 'transparent',
                }}
              >
                <div style={{ fontSize: 12, fontWeight: 500, color: 'var(--color-text)', display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span>{typeIcon}</span>
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }} title={p.filename}>
                    {p.filename}
                  </span>
                </div>
                <div style={{ display: 'flex', gap: 6, marginTop: 2, fontSize: 10, color: 'var(--color-text-muted)', alignItems: 'center' }}>
                  <span style={{ color: statusColor, fontWeight: 600 }}>{statusVal.replace(/_/g, ' ')}</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 4 }}>
                  <ProgressBar value={progressVal} />
                  <span style={{ fontSize: 10, fontWeight: 600, color: 'var(--color-text-secondary)', minWidth: 28, textAlign: 'right' }}>
                    {progressVal}%
                  </span>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

export default function UploadPage({ onDone, onBack }: Props) {
  const [mode, setMode] = useState<UploadMode>('batch');
  const [files, setFiles] = useState<File[]>([]);
  const [phase, setPhase] = useState<any>('idle');
  const [statusMsg, setStatusMsg] = useState('');
  const [logs, setLogs] = useState<Array<{ t: string; msg: string }>>([]);
  const [numPages, setNumPages] = useState(0);
  const [jobId, setJobId] = useState<string | null>(null);
  const [currentStatus, setCurrentStatus] = useState('');
  const [progress, setProgress] = useState(0);
  const [pdfs, setPdfs] = useState<PdfEntry[]>([]);
  const [showDedupDialog, setShowDedupDialog] = useState(false);
  const [dedupInfo, setDedupInfo] = useState<any>(null);
  const [uploadQueue, setUploadQueue] = useState<File[]>([]);
  const [isUploadingBatch, setIsUploadingBatch] = useState(false);
  const [batchResults, setBatchResults] = useState<any[]>([]);
  const [showAddOptions, setShowAddOptions] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);
  const sseUnsubRef = useRef<(() => void) | undefined>(undefined);
  const startRef = useRef<number>(0);
  const logEndRef = useRef<HTMLDivElement>(null);
  const fileDropRef = useRef<HTMLDivElement>(null);
  const [perPdfProgress, setPdfProgresses] = useState<Record<string, { progress: number; stage: string; elapsed?: number }>>({});
  const [overallProgress, setOverallProgress] = useState<number | null>(null);
  const [elapsedTime, setElapsedTime] = useState<number | null>(null);
  const [batchJobIds, setBatchJobIds] = useState<string[]>([]);
  const batchJobIdsRef = useRef<string[]>([]);

  useEffect(() => {
    if (phase !== 'processing' && phase !== 'uploading') {
      if (phase === 'idle') setElapsedTime(null);
      return;
    }
    const interval = setInterval(() => {
      if (startRef.current > 0) {
        setElapsedTime(Math.round((Date.now() - startRef.current) / 1000));
      }
    }, 1000);
    return () => clearInterval(interval);
  }, [phase]);
  useEffect(() => {
    batchJobIdsRef.current = batchJobIds;
  }, [batchJobIds]);

  const loadPdfs = useCallback(async () => {
    try {
      const data = await listPDFs();
      setPdfs(Array.isArray(data) ? data : []);
    } catch {}
  }, []);

  useEffect(() => {
    loadPdfs();
  }, [loadPdfs]);

  const stopSSE = useCallback(() => {
    if (sseUnsubRef.current) {
      sseUnsubRef.current();
      sseUnsubRef.current = undefined;
    }
  }, []);

  useEffect(() => {
    return () => stopSSE();
  }, [stopSSE]);

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  const addLog = useCallback((msg: string) => {
    setLogs((prev) => [...prev, { t: ts(), msg }]);
  }, []);

  const syncLogs = useCallback((backendLog: Array<{ t: string; msg: string }>) => {
    if (!backendLog || backendLog.length === 0) return;
    setLogs((prev) => {
      const existing = new Set(prev.map((e) => `${e.t}|${e.msg}`));
      const newEntries = backendLog.filter((e) => !existing.has(`${e.t}|${e.msg}`));
      if (newEntries.length === 0) return prev;
      return [...prev, ...newEntries];
    });
  }, []);

  const handleSSEMessage = useCallback((id: string, data: any) => {
    setCurrentStatus(data.status);
    if (data.message) setStatusMsg(data.message);
    if (data.pages && data.pages > 0) setNumPages(data.pages);
    if (data.log) syncLogs(data.log);

    const stageOrder = STAGES.map((st) => st.key);
    const idx = stageOrder.indexOf(data.status);
    const pct = data.progress?.overall ?? (idx >= 0 ? Math.round((idx / (stageOrder.length - 1)) * 100) : 0);
    setProgress(pct);
    setOverallProgress(pct);
    if (data.progress?.pdfs) {
      setPdfProgresses(data.progress.pdfs);
    }

    if (Date.now() - startRef.current > MAX_POLL_TIME) {
      stopSSE();
      setPhase('error');
      addLog('❌ TIMEOUT: Pipeline took too long.');
      return;
    }

    if (data.status === 'done') {
      setProgress(100);
      setOverallProgress(100);
      addLog('✅ Pipeline complete!');
      stopSSE();
      setTimeout(() => {
        onDone([id]);
        loadPdfs();
      }, 800);
    } else if (data.status === 'error') {
      stopSSE();
      setPhase('error');
      addLog(`❌ ${data.message || 'Unknown error'}`);
    } else if (data.status === 'incomplete') {
      stopSSE();
      setPhase('error');
      addLog(`⚠️ ${data.message || 'Document incomplete'}`);
      addLog(`📋 Check validation report for details.`);
    }
  }, [onDone, stopSSE, addLog, syncLogs, loadPdfs]);

  const startSSE = useCallback((id: string) => {
    stopSSE();
    setLogs([]);
    startRef.current = Date.now();
    sseUnsubRef.current = subscribeToJob(id, (data) => handleSSEMessage(id, data));
  }, [stopSSE, handleSSEMessage]);

  const handleBatchSSEMessage = useCallback((data: any) => {
    if (data._batch_complete) {
      addLog('✅ All batch items processed!');
      setOverallProgress(100);
      setProgress(100);
      setCurrentStatus('done');
      setStatusMsg('Batch extraction complete.');
      stopSSE();
      return;
    }

    const jobName = data.original_name || data.job_id;
    
    setPdfProgresses((prev) => {
      const next = {
        ...prev,
        [jobName]: {
          progress: data.progress?.overall ?? 0,
          stage: data.status,
          elapsed: data.progress?.elapsed,
        }
      };
      
      const values = Object.values(next);
      if (values.length > 0) {
        const sum = values.reduce((acc, curr) => acc + curr.progress, 0);
        setOverallProgress(Math.round(sum / batchJobIdsRef.current.length));
      }
      return next;
    });

    if (data.message) {
      setStatusMsg(`[${jobName}] ${data.message}`);
    }

    if (data.log && Array.isArray(data.log)) {
      setLogs((prev) => {
        const existing = new Set(prev.map((e) => `${e.t}|${e.msg}`));
        const newEntries = data.log
          .map((entry: any) => ({
            t: entry.t,
            msg: `[${jobName}] ${entry.msg}`,
          }))
          .filter((entry: any) => !existing.has(`${entry.t}|${entry.msg}`));
        if (newEntries.length === 0) return prev;
        return [...prev, ...newEntries];
      });
    }

    if (data.status === 'error') {
      addLog(`❌ [${jobName}] failed: ${data.message || 'Unknown error'}`);
    }
  }, [addLog, stopSSE]);

  const startBatchSSE = useCallback((jobIds: string[]) => {
    stopSSE();
    setLogs([]);
    startRef.current = Date.now();
    sseUnsubRef.current = subscribeToBatch(jobIds, handleBatchSSEMessage);
  }, [stopSSE, handleBatchSSEMessage]);

  const handleResumeJob = useCallback(async (jobIdToResume: string) => {
    const jobName = batchResults.find(r => r.job_id === jobIdToResume)?.filename || jobIdToResume;
    addLog(`🔄 Resuming job ${jobName} (${jobIdToResume}) from checkpoint...`);
    
    setPdfProgresses(prev => ({
      ...prev,
      [jobName]: { progress: 0, stage: 'queued' }
    }));
    
    try {
      await retryJob(jobIdToResume);
      addLog(`✅ Resume started for: ${jobName}`);
      
      const jobIds = batchResults.map(r => r.job_id).filter(Boolean) as string[];
      if (jobIds.length > 0) {
        startBatchSSE(jobIds);
      } else {
        startSSE(jobIdToResume);
      }
    } catch (e: any) {
      addLog(`❌ Resume failed for ${jobName}: ${e.message}`);
      setPdfProgresses(prev => ({
        ...prev,
        [jobName]: { progress: 0, stage: 'error' }
      }));
    }
  }, [batchResults, retryJob, addLog, startBatchSSE, startSSE]);

  const handleResumeBatch = useCallback(async () => {
    addLog(`🔄 Resuming failed batch items...`);
    const failedJobs = batchResults.filter(r => {
      const pp = perPdfProgress[r.filename || r.name];
      return pp?.stage === 'error' || r.status === 'error';
    });
    
    if (failedJobs.length === 0) {
      addLog(`ℹ️ No failed jobs to resume.`);
      return;
    }
    
    setPhase('processing');
    setCurrentStatus('preprocessing');
    setStatusMsg(`Resuming ${failedJobs.length} failed items...`);
    
    for (const j of failedJobs) {
      const jobName = j.filename || j.name;
      addLog(`🔄 Resuming ${jobName} (${j.job_id})...`);
      setPdfProgresses(prev => ({
        ...prev,
        [jobName]: { progress: 0, stage: 'queued' }
      }));
      try {
        await retryJob(j.job_id);
      } catch (e: any) {
        addLog(`❌ Failed to start resume for ${jobName}: ${e.message}`);
        setPdfProgresses(prev => ({
          ...prev,
          [jobName]: { progress: 0, stage: 'error' }
        }));
      }
    }
    
    const jobIds = batchResults.map(r => r.job_id).filter(Boolean) as string[];
    startBatchSSE(jobIds);
  }, [batchResults, perPdfProgress, retryJob, addLog, startBatchSSE]);

  const handleStartOver = useCallback(() => {
    setPhase('idle');
    setLogs([]);
    setStatusMsg('');
    setJobId(null);
    setNumPages(0);
    setFiles([]);
    setUploadQueue([]);
    setProgress(0);
    setCurrentStatus('');
    setIsUploadingBatch(false);
    setBatchResults([]);
    setBatchJobIds([]);
    setPdfProgresses({});
    setOverallProgress(null);
  }, []);

  const handleViewResults = useCallback(() => {
    onDone(batchJobIds.length > 0 ? batchJobIds : (jobId ? [jobId] : []));
    loadPdfs();
  }, [onDone, batchJobIds, jobId, loadPdfs]);

  const processQueue = useCallback(async () => {
    if (uploadQueue.length === 0) {
      setIsUploadingBatch(false);
      return;
    }
    setIsUploadingBatch(true);
    const file = uploadQueue[0];
    addLog(`Uploading ${file.name}...`);

    try {
      const resp = await uploadPDFWithDedup(file);
      if (resp.duplicate) {
        setDedupInfo(resp);
        setShowDedupDialog(true);
        setUploadQueue((prev) => prev.slice(1));
        return;
      }
      const id = resp.job_id;
      setJobId(id);
      setPhase('processing');
      addLog(`✅ Uploaded. Job ID: ${id}`);
      addLog('🚀 Starting extraction pipeline...');
      startSSE(id);
      setUploadQueue((prev) => prev.slice(1));
    } catch (e: any) {
      setPhase('error');
      addLog(`❌ Upload failed: ${e.message}`);
      setUploadQueue([]);
      setIsUploadingBatch(false);
    }
  }, [uploadQueue, addLog, startSSE]);

  useEffect(() => {
    if (uploadQueue.length > 0 && !isUploadingBatch && !showDedupDialog) {
      processQueue();
    }
  }, [uploadQueue, isUploadingBatch, showDedupDialog, processQueue]);

  const uploadBatchAll = useCallback(async (allFiles: File[]) => {
    addLog(`Uploading ${allFiles.length} files as batch...`);
    setPhase('uploading');
    try {
      const resp = await uploadBatch(allFiles);
      setBatchResults(resp.results || []);
      addLog(`✅ Batch submitted: ${resp.total} items`);
      const jobIds: string[] = [];
      for (const r of resp.results || []) {
        const icon = r.type === 'pdf' ? '📄' : r.type === 'image_set' ? '🖼️' : '📦';
        addLog(`  ${icon} ${r.filename || r.name} → ${r.job_id}`);
        if (r.job_id) jobIds.push(r.job_id);
      }
      setBatchJobIds(jobIds);
      if (jobIds.length > 0) {
        setPhase('processing');
        startBatchSSE(jobIds);
      }
    } catch (e: any) {
      setPhase('error');
      addLog(`❌ Batch upload failed: ${e.message}`);
    }
  }, [addLog, startBatchSSE]);

  const startUpload = useCallback((fileList: File[]) => {
    const all = Array.from(fileList);
    if (all.length === 0) return;
    setFiles(all);
    setLogs([]);
    setPhase('uploading');
    setBatchResults([]);
    uploadBatchAll(all);
  }, [uploadBatchAll]);

  const uploadImageSet = useCallback(async (imageFiles: File[]) => {
    addLog(`Uploading ${imageFiles.length} images for page classification...`);
    setPhase('uploading');
    try {
      const resp = await uploadImages(imageFiles);
      const id = resp.job_id;
      setJobId(id);
      setPhase('processing');
      addLog(`✅ ${imageFiles.length} images uploaded. Job ID: ${id}`);
      addLog('🔍 Classifying pages by content (ignoring filenames)...');
      startSSE(id);
    } catch (e: any) {
      setPhase('error');
      addLog(`❌ Upload failed: ${e.message}`);
    }
  }, [addLog, startSSE]);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const selected = Array.from(e.dataTransfer.files);
      setFiles(prev => [...prev, ...selected]);
    }
  }, []);

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      const selected = Array.from(e.target.files);
      setFiles(prev => [...prev, ...selected]);
    }
  }, []);

  const handleFolderSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      const selected = Array.from(e.target.files).filter(f => f.name.toLowerCase().endsWith('.pdf'));
      setFiles(prev => [...prev, ...selected]);
    }
  }, []);

  const handleDedupContinue = useCallback(() => {
    const file = uploadQueue[0];
    if (!file) return;
    setShowDedupDialog(false);
    addLog(`⏭️ Skipping duplicate: ${file.name}`);
    setUploadQueue((prev) => prev.slice(1));
  }, [uploadQueue, addLog]);

  const handleDedupView = useCallback(() => {
    setShowDedupDialog(false);
    setUploadQueue([]);
    if (dedupInfo?.existing_job_id) {
      onDone([dedupInfo.existing_job_id]);
    } else if (dedupInfo?.pdf?.id) {
      addLog('ℹ️ Already uploaded. Select from sidebar.');
    }
  }, [dedupInfo, onDone, addLog]);

  const handleSidebarSelect = useCallback((jid: string) => {
    onDone([jid]);
  }, [onDone]);

  const handleModeSwitch = useCallback((newMode: UploadMode) => {
    setMode(newMode);
    setFiles([]);
    setLogs([]);
    setPhase('idle');
    setBatchResults([]);
  }, []);

  const currentStage = currentStatus || (phase === 'uploading' ? 'queued' : '');
  const stageIndex = STAGES.findIndex((s) => s.key === currentStage);
  const showPreview = phase === 'processing' && numPages > 0;
  const isProcessing = phase === 'processing' || phase === 'uploading';

  const getAcceptAttr = () => {
    if (mode === 'pdf') return '.pdf';
    if (mode === 'images') return '.jpg,.jpeg,.png,.tiff,.tif';
    if (mode === 'zip') return '.zip';
    return '.pdf,.jpg,.jpeg,.png,.tiff,.tif,.zip';
  };

  const MODE_LABELS: Record<UploadMode, { icon: string; label: string; desc: string }> = {
    pdf: { icon: '📄', label: 'PDF', desc: 'Single or batch PDF upload' },
    images: { icon: '🖼️', label: 'Images', desc: 'Upload 6 page images (auto-ordered)' },
    zip: { icon: '📦', label: 'ZIP', desc: 'ZIP file with page images' },
    batch: { icon: '📋', label: 'Mixed', desc: 'Mix of PDFs + images + ZIPs' },
    folder: { icon: '📁', label: 'Folder', desc: 'Process entire folder (concurrent batch)' },
  };

  if (phase !== 'idle') {
    const processingFiles = batchResults.length > 0
      ? batchResults.map(r => ({ name: r.filename || r.name, jobId: r.job_id }))
      : files.map(f => ({ name: f.name, jobId: jobId || undefined }));

    return (
      <PipelineProcessingView
        jobId={jobId || (batchJobIds.length > 0 ? `${batchJobIds.length} items` : '')}
        files={processingFiles}
        status={currentStatus}
        statusMessage={statusMsg}
        progress={progress}
        overallProgress={overallProgress}
        perPdfProgress={perPdfProgress}
        logs={logs}
        elapsed={elapsedTime}
        onBack={onBack || (() => {})}
        onResumeJob={handleResumeJob}
        onResumeBatch={handleResumeBatch}
        onStartOver={handleStartOver}
        onViewResults={handleViewResults}
      />
    );
  }

  return (
    <div style={{
      flex: 1, display: 'flex',
      background: 'var(--color-bg)',
      fontFamily: 'var(--font-sans)', overflow: 'hidden',
    }}>
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        <div style={{
          padding: '12px 24px', borderBottom: '1px solid var(--color-border)',
          background: 'rgba(255,255,255,0.85)', backdropFilter: 'blur(12px)',
          display: 'flex', alignItems: 'center', gap: 12,
          position: 'relative',
          zIndex: 5,
        }}>
          {onBack && (
            <button onClick={onBack} style={{
              padding: '6px 14px', fontSize: 12, fontWeight: 600,
              border: 'none', borderRadius: 'var(--radius-md)',
              background: 'var(--color-primary)', color: '#fff',
              cursor: 'pointer', transition: 'all var(--transition-fast)',
              marginRight: 8,
            }}
              onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--color-primary-dark)'; }}
              onMouseLeave={(e) => { e.currentTarget.style.background = 'var(--color-primary)'; }}
            >
              ← Back to Dashboard
            </button>
          )}
          <div style={{
            width: 32, height: 32, borderRadius: 8,
            background: 'var(--color-primary-gradient)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: '#fff', fontSize: 16, fontWeight: 700,
            boxShadow: 'var(--shadow-primary)',
          }}>O</div>
          <h1 style={{ fontSize: 20, fontWeight: 700, color: 'var(--color-text)', margin: 0, letterSpacing: '-0.02em' }}>
            OCR Extraction
          </h1>
          {phase === 'processing' && jobId && (
            <span style={{
              fontSize: 11, color: 'var(--color-text-muted)', fontFamily: 'var(--font-mono)',
              marginLeft: 'auto', background: 'var(--color-surface-active)', padding: '2px 8px',
              borderRadius: 'var(--radius-sm)',
            }}>
              {jobId}
            </span>
          )}
        </div>

        <div style={{ flex: 1, overflow: 'auto', padding: 24 }}>
          <input
            ref={inputRef}
            type="file"
            accept=".pdf,.jpg,.jpeg,.png,.tiff,.tif,.zip"
            multiple
            hidden
            onChange={handleFileSelect}
          />
          <input
            ref={folderInputRef}
            type="file"
            // @ts-ignore
            webkitdirectory=""
            directory=""
            multiple
            hidden
            onChange={handleFolderSelect}
          />

          {phase === 'idle' && files.length === 0 && (
            <div style={{
              display: 'flex', flexDirection: 'column',
              alignItems: 'center', justifyContent: 'center',
              paddingTop: 40, gap: 16,
            }}>
              <div
                ref={fileDropRef}
                onDragOver={(e) => e.preventDefault()}
                onDrop={handleDrop}
                onClick={() => inputRef.current?.click()}
                style={{
                  width: 520, maxWidth: '90vw', height: 220,
                  border: '2px dashed var(--color-text-muted)',
                  borderRadius: 'var(--radius-2xl)',
                  display: 'flex', flexDirection: 'column',
                  alignItems: 'center', justifyContent: 'center',
                  cursor: 'pointer', background: 'var(--color-surface)', gap: 10,
                  transition: 'border-color var(--transition-normal), box-shadow var(--transition-normal), background var(--transition-normal)',
                  boxShadow: 'var(--shadow-sm)',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.borderColor = 'var(--color-primary)';
                  e.currentTarget.style.boxShadow = '0 4px 16px rgba(37,99,235,0.12)';
                  e.currentTarget.style.background = '#fafcff';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = 'var(--color-text-muted)';
                  e.currentTarget.style.boxShadow = 'var(--shadow-sm)';
                  e.currentTarget.style.background = 'var(--color-surface)';
                }}
              >
                <div style={{
                  fontSize: 44, opacity: 0.5, marginBottom: 4,
                  filter: 'grayscale(0.3)',
                }}>
                  📋
                </div>
                <div style={{ fontSize: 15, color: 'var(--color-text-tertiary)', fontWeight: 500, textAlign: 'center', maxWidth: 360 }}>
                  Drop PDFs, images, or ZIP files here or click to browse
                </div>
                <div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
                  Files will be processed together as a concurrent batch
                </div>
              </div>

              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <button onClick={() => inputRef.current?.click()} style={{
                  padding: '8px 18px', fontSize: 13, fontWeight: 600,
                  border: '1px solid var(--color-border-hover)', borderRadius: 'var(--radius-lg)',
                  background: 'var(--color-surface)', cursor: 'pointer',
                  color: 'var(--color-text-tertiary)',
                  transition: 'all var(--transition-fast)',
                }}
                  onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'var(--color-primary)'; e.currentTarget.style.color = 'var(--color-primary)'; }}
                  onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--color-border-hover)'; e.currentTarget.style.color = 'var(--color-text-tertiary)'; }}
                >
                  Select Files
                </button>
                <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>or</span>
                <button onClick={() => folderInputRef.current?.click()} style={{
                  padding: '8px 18px', fontSize: 13, fontWeight: 600,
                  border: '1px solid var(--color-border-hover)', borderRadius: 'var(--radius-lg)',
                  background: 'var(--color-surface)', cursor: 'pointer',
                  color: 'var(--color-text-tertiary)',
                  transition: 'all var(--transition-fast)',
                }}
                  onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'var(--color-primary)'; e.currentTarget.style.color = 'var(--color-primary)'; }}
                  onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--color-border-hover)'; e.currentTarget.style.color = 'var(--color-text-tertiary)'; }}
                >
                  Select Folder
                </button>
              </div>
            </div>
          )}

          {phase === 'idle' && files.length > 0 && (
            <div style={{
              display: 'flex', flexDirection: 'column',
              alignItems: 'center', justifyContent: 'center',
              paddingTop: 40, gap: 20,
            }}>
              <div style={{
                width: 520, maxWidth: '90vw',
                background: 'var(--color-surface)',
                border: '1px solid var(--color-border)',
                borderRadius: 'var(--radius-xl)',
                padding: '20px',
                boxShadow: 'var(--shadow-md)',
                display: 'flex', flexDirection: 'column', gap: 12,
              }}>
                <div style={{ fontSize: 16, fontWeight: 600, color: 'var(--color-text)', borderBottom: '1px solid var(--color-border)', paddingBottom: 8 }}>
                  Selected Files ({files.length})
                </div>
                <div style={{ maxHeight: 200, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {files.map((f, idx) => (
                    <div key={idx} style={{
                      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                      padding: '6px 10px', background: 'var(--color-bg)', borderRadius: 'var(--radius-md)',
                      fontSize: 12, color: 'var(--color-text-secondary)'
                    }}>
                      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1, marginRight: 8 }}>
                        📄 {f.name} ({formatSize(f.size)})
                      </span>
                      <button
                        onClick={() => setFiles(prev => prev.filter((_, i) => i !== idx))}
                        style={{
                          background: 'transparent', border: 'none', cursor: 'pointer',
                          fontSize: 12, color: 'var(--color-text-muted)', display: 'flex', alignItems: 'center'
                        }}
                        onMouseEnter={(e) => e.currentTarget.style.color = 'var(--color-danger)'}
                        onMouseLeave={(e) => e.currentTarget.style.color = 'var(--color-text-muted)'}
                        title="Remove file"
                      >
                        ❌
                      </button>
                    </div>
                  ))}
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 12 }}>
                  <button onClick={() => inputRef.current?.click()} style={{
                    padding: '8px 16px', fontSize: 13, fontWeight: 600,
                    border: '1px solid var(--color-primary)', borderRadius: 'var(--radius-lg)',
                    background: 'transparent', cursor: 'pointer',
                    color: 'var(--color-primary)',
                    transition: 'all var(--transition-fast)',
                  }}
                    onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--color-primary-light)'; }}
                    onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
                  >
                    + Add More
                  </button>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <button onClick={() => { setFiles([]); setUploadQueue([]); }}
                      style={{
                        padding: '8px 16px', fontSize: 13, fontWeight: 500,
                        border: '1px solid var(--color-border-hover)', borderRadius: 'var(--radius-lg)',
                        background: 'var(--color-surface)', cursor: 'pointer',
                        color: 'var(--color-text-tertiary)',
                        transition: 'all var(--transition-fast)',
                      }}
                    >
                      Cancel
                    </button>
                    <button onClick={() => startUpload(files)}
                      disabled={files.length === 0}
                      style={{
                        padding: '8px 18px', fontSize: 13, fontWeight: 600,
                        border: 'none', borderRadius: 'var(--radius-lg)', cursor: 'pointer',
                        background: 'var(--color-primary-gradient)',
                        color: '#fff', boxShadow: 'var(--shadow-primary)',
                        transition: 'all var(--transition-fast)',
                        opacity: files.length === 0 ? 0.6 : 1,
                      }}
                    >
                      Process Batch
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )}


        </div>
      </div>

      {showDedupDialog && dedupInfo && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(15, 23, 42, 0.5)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          zIndex: 1000, animation: 'fadeIn 0.15s ease',
          backdropFilter: 'blur(4px)',
        }}>
          <div style={{
            background: 'var(--color-surface)', borderRadius: 'var(--radius-xl)', padding: 28,
            maxWidth: 440, width: '90vw',
            boxShadow: 'var(--shadow-2xl)',
            animation: 'scaleIn 0.2s ease',
          }}>
            <div style={{
              width: 48, height: 48, borderRadius: 'var(--radius-lg)',
              background: 'var(--color-warning-light)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              margin: '0 auto 12px',
              fontSize: 24,
            }}>📄</div>
            <h3 style={{ fontSize: 17, fontWeight: 600, color: 'var(--color-text)', margin: '0 0 4px 0', textAlign: 'center' }}>
              PDF Already Uploaded
            </h3>
            <p style={{ fontSize: 13, color: 'var(--color-text-secondary)', textAlign: 'center', margin: '0 0 20px 0', lineHeight: 1.5 }}>
              {dedupInfo.message}
            </p>
            <div style={{ display: 'flex', gap: 8, justifyContent: 'center' }}>
              <button onClick={handleDedupView}
                style={{
                  padding: '8px 20px', fontSize: 13, fontWeight: 600,
                  border: 'none', borderRadius: 'var(--radius-md)', cursor: 'pointer',
                  background: 'var(--color-primary-gradient)', color: '#fff',
                  boxShadow: 'var(--shadow-primary)',
                  transition: 'all var(--transition-fast)',
                }}
                onMouseEnter={(e) => { e.currentTarget.style.boxShadow = 'var(--shadow-primary-lg)'; e.currentTarget.style.filter = 'brightness(1.05)'; }}
                onMouseLeave={(e) => { e.currentTarget.style.boxShadow = 'var(--shadow-primary)'; e.currentTarget.style.filter = 'none'; }}>
                View Existing Results
              </button>
              <button onClick={handleDedupContinue}
                style={{
                  padding: '8px 20px', fontSize: 13, fontWeight: 600,
                  border: '1px solid var(--color-border-hover)', borderRadius: 'var(--radius-md)',
                  background: 'var(--color-surface)', cursor: 'pointer',
                  color: 'var(--color-text-tertiary)',
                  transition: 'all var(--transition-fast)',
                }}
                onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'var(--color-text-muted)'; e.currentTarget.style.background = 'var(--color-surface-hover)'; }}
                onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--color-border-hover)'; e.currentTarget.style.background = 'var(--color-surface)'; }}>
                Skip & Continue
              </button>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}
