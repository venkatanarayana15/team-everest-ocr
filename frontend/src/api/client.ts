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
  let url = `${API}/pages/${jobId}/${pageNum}`;
  const params: string[] = [];
  if (pdfName) {
    params.push(`pdf_name=${encodeURIComponent(pdfName)}`);
  }
  if (params.length > 0) {
    url += '?' + params.join('&');
  }
  return url;
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

export async function getValidation(jobId: string): Promise<any> {
  const res = await fetch(`${API}/validate/${jobId}`);
  if (!res.ok) throw new Error('Failed to get validation');
  return res.json();
}

export function subscribeNewJobs(
  onSnapshot: (jobs: any[]) => void,
  onNewJob: (jobId: string) => void,
): () => void {
  const es = new EventSource(`${API}/stream-new-jobs`);
  es.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      if (data.heartbeat) return;
      if (data.snapshot) { onSnapshot(data.snapshot); return; }
      if (data.job_id) onNewJob(data.job_id);
    } catch { /* ignore */ }
  };
  es.onerror = () => {
    // EventSource auto-reconnects
  };
  return () => es.close();
}

export async function deleteJob(jobId: string): Promise<any> {
  const res = await fetch(`${API}/jobs/${jobId}`, { method: 'DELETE' });
  if (!res.ok) throw new Error('Failed to delete job');
  return res.json();
}

export async function saveToDB(jobId: string, corrections?: {label: string; correct_value: string}[]): Promise<any> {
  const options: RequestInit = { method: 'POST' };
  if (corrections && corrections.length > 0) {
    options.headers = { 'Content-Type': 'application/json' };
    options.body = JSON.stringify({ corrections });
  }
  const res = await fetch(`${API}/save-to-db/${jobId}`, options);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function correctField(jobId: string, label: string, correctValue: string, pdfName?: string): Promise<any> {
  const body: Record<string, string> = { label, correct_value: correctValue };
  if (pdfName) body.pdf_name = pdfName;
  const res = await fetch(`${API}/correct/${jobId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error('Failed to correct field');
  return res.json();
}

export async function updateRawText(jobId: string, rawText: string): Promise<any> {
  const res = await fetch(`${API}/update-raw-text/${jobId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ raw_text: rawText }),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}
