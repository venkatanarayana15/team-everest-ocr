const API = '';

export function subscribeToJob(jobId: string, onMessage: (data: any) => void): () => void {
  const es = new EventSource(`${API}/stream/${jobId}`);
  es.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      if (data.status === 'heartbeat') return;
      onMessage(data);
      if (data._final) es.close();
    } catch { /* ignore parse errors */ }
  };
  es.onerror = () => {
    // Do NOT close — native EventSource auto-reconnects on error.
    // Closing here would kill the connection until page refresh.
  };
  return () => es.close();
}

export function subscribeToBatch(jobIds: string[], onMessage: (data: any) => void): () => void {
  const ids = jobIds.join(',');
  const es = new EventSource(`${API}/stream-batch?job_ids=${encodeURIComponent(ids)}`);
  es.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      if (data.status === 'heartbeat') return;
      onMessage(data);
      if (data._batch_complete) es.close();
    } catch { /* ignore */ }
  };
  es.onerror = () => {
    // Do NOT close — native EventSource auto-reconnects on error.
  };
  return () => es.close();
}

export interface StatusResponse {
  status: string;
  message?: string;
  log?: Array<{ t: string; msg: string }>;
  pages?: number;
}

export async function uploadPDF(file: File): Promise<{ job_id: string }> {
  const form = new FormData();
  form.append('file', file);
  const res = await fetch(`${API}/upload`, { method: 'POST', body: form });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getStatus(jobId: string): Promise<StatusResponse> {
  const res = await fetch(`${API}/status/${jobId}`);
  if (!res.ok) throw new Error('Failed to get status');
  return res.json();
}

export async function getResult(jobId: string) {
  const res = await fetch(`${API}/result/${jobId}`);
  if (!res.ok) throw new Error('Failed to get result');
  return res.json();
}

export async function listJobs() {
  const res = await fetch(`${API}/jobs`);
  if (!res.ok) throw new Error('Failed to list jobs');
  return res.json();
}

export function pageImageUrl(jobId: string, pageNum: number, pdfName?: string | null): string {
  const query = pdfName ? `?pdf_name=${encodeURIComponent(pdfName)}` : '';
  return `${API}/pages/${jobId}/${pageNum}${query}`;
}

export function thumbnailUrl(jobId: string, pageNum: number, pdfName?: string | null): string {
  const query = pdfName ? `&pdf_name=${encodeURIComponent(pdfName)}` : '';
  return `${API}/pages/${jobId}/${pageNum}?width=200${query}`;
}

export function downloadUrl(jobId: string, format: 'json' | 'md' | 'html' | 'txt'): string {
  return `${API}/download/${jobId}?format=${format}`;
}

export async function retryJob(jobId: string): Promise<{ job_id: string; status: string }> {
  const res = await fetch(`${API}/retry/${jobId}`, { method: 'POST' });
  if (!res.ok) throw new Error('Failed to retry job');
  return res.json();
}

export async function listPDFs(): Promise<any[]> {
  const res = await fetch(`${API}/pdfs`);
  if (!res.ok) throw new Error('Failed to list PDFs');
  return res.json();
}

export async function getTesseractData(jobId: string): Promise<any> {
  const res = await fetch(`${API}/tesseract-data/${jobId}`);
  if (!res.ok) throw new Error('Failed to get tesseract data');
  return res.json();
}

export async function uploadPDFWithDedup(file: File): Promise<any> {
  const form = new FormData();
  form.append('file', file);
  const res = await fetch(`${API}/upload`, { method: 'POST', body: form });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

/* ── New: Multi-input uploads ───────────────────────────────────── */

export async function uploadImages(files: File[]): Promise<any> {
  const form = new FormData();
  for (const f of files) {
    form.append('files', f);
  }
  const res = await fetch(`${API}/upload-images`, { method: 'POST', body: form });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function uploadBatch(files: File[]): Promise<any> {
  const form = new FormData();
  for (const f of files) {
    form.append('files', f);
  }
  const res = await fetch(`${API}/upload-batch`, { method: 'POST', body: form });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getValidation(jobId: string): Promise<any> {
  const res = await fetch(`${API}/validate/${jobId}`);
  if (!res.ok) throw new Error('Failed to get validation');
  return res.json();
}

export async function processFolder(folderPath: string): Promise<any> {
  const res = await fetch(`${API}/process-folder`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ folder_path: folderPath }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function deleteJob(jobId: string): Promise<any> {
  const res = await fetch(`${API}/jobs/${jobId}`, { method: 'DELETE' });
  if (!res.ok) throw new Error('Failed to delete job');
  return res.json();
}

export async function saveToDB(jobId: string): Promise<any> {
  const res = await fetch(`${API}/save-to-db/${jobId}`, { method: 'POST' });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}
