import { useRef, useCallback, useState, useEffect, useMemo } from 'react';
import { pageImageUrl } from '../api/client';
import type { Field, Section } from '../types';
import ExtractedDataPanel from './ExtractedDataPanel';

interface Props {
  jobId: string;
  numPages: number;
  pageOffset?: number;
  fields: Field[];
  sections: Section[];
  selectedField: Field | null;
  currentPage: number;
  onFieldClick: (field: Field) => void;
  onFieldsUpdated: (fields: Field[]) => void;
  rawText?: string;
  rightPanelFormat?: 'fields' | 'txt';
  onRawTextUpdated?: (newRawText: string) => void;
  pdfName?: string | null;
}

function getPageText(rawText: string, pageNum: number): string {
  const parts = rawText.split(/--- Page \d+ ---/);
  if (parts.length === 1) return rawText;
  if (pageNum < parts.length) return parts[pageNum]?.trim() || '';
  return parts[parts.length - 1]?.trim() || '';
}

function BboxOverlay({
  bbox, color, natW, natH, elW, elH,
}: {
  bbox: [number, number, number, number];
  color: string;
  natW: number;
  natH: number;
  elW: number;
  elH: number;
}) {
  const scale = Math.min(elW / natW, elH / natH);
  const renderedW = natW * scale;
  const renderedH = natH * scale;
  const offsetX = (elW - renderedW) / 2;
  const offsetY = (elH - renderedH) / 2;

  return (
    <div style={{
      position: 'absolute',
      left: bbox[0] * scale + offsetX,
      top: bbox[1] * scale + offsetY,
      width: (bbox[2] - bbox[0]) * scale,
      height: (bbox[3] - bbox[1]) * scale,
      border: `2px solid ${color}`,
      background: `${color}22`,
      borderRadius: 2,
      pointerEvents: 'none',
    }} />
  );
}

function EditableTextViewer({
  pageNum,
  rawText,
  onSave,
}: {
  pageNum: number;
  rawText: string;
  onSave: (pageNum: number, text: string) => void;
}) {
  const initialText = useMemo(() => getPageText(rawText, pageNum), [rawText, pageNum]);
  const [text, setText] = useState(initialText);

  useEffect(() => {
    setText(initialText);
  }, [initialText]);

  return (
    <div style={{
      flex: 1,
      display: 'flex',
      flexDirection: 'column',
      background: 'var(--color-surface)',
      padding: '12px 16px',
      minHeight: 0,
    }}>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        style={{
          flex: 1,
          fontFamily: 'var(--font-mono)',
          fontSize: 13,
          lineHeight: 1.6,
          padding: 12,
          border: '1px solid var(--color-border)',
          borderRadius: 'var(--radius-md)',
          resize: 'none',
          outline: 'none',
          background: 'var(--color-bg)',
          color: 'var(--color-text)',
          boxShadow: 'inset 0 1px 2px rgba(0,0,0,0.05)',
        }}
        placeholder="Raw OCR transcription text..."
      />
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 8 }}>
        <button
          onClick={() => onSave(pageNum, text)}
          style={{
            padding: '6px 14px',
            fontSize: 12,
            fontWeight: 600,
            border: 'none',
            borderRadius: 'var(--radius-sm)',
            background: 'var(--color-primary)',
            color: '#fff',
            cursor: 'pointer',
            transition: 'all var(--transition-fast)',
          }}
        >
          Save Text
        </button>
      </div>
    </div>
  );
}

export default function DocumentReview({
  jobId, numPages, pageOffset = 0, fields, sections,
  selectedField, currentPage, onFieldClick, onFieldsUpdated,
  rawText = '',
  rightPanelFormat = 'fields',
  onRawTextUpdated,
  pdfName = null,
}: Props) {
  const [fitModes, setFitModes] = useState<Record<number, boolean>>({});
  const [imgDims, setImgDims] = useState<Record<number, { natW: number; natH: number; elW: number; elH: number }>>({});
  const blockRefs = useRef<Map<number, HTMLDivElement>>(new Map());

  const handlePageTextChange = useCallback((pageNum: number, newPageText: string) => {
    const parts = rawText.split(/(--- Page \d+ ---)/);
    const targetSeparator = `--- Page ${pageNum} ---`;
    const idx = parts.indexOf(targetSeparator);
    if (idx !== -1 && idx + 1 < parts.length) {
      parts[idx + 1] = `\n${newPageText.trim()}\n\n`;
      const fullText = parts.join('');
      if (onRawTextUpdated) onRawTextUpdated(fullText);
    } else {
      if (onRawTextUpdated) onRawTextUpdated(newPageText);
    }
  }, [rawText, onRawTextUpdated]);

  useEffect(() => {
    const block = blockRefs.current.get(currentPage);
    if (block) block.scrollIntoView({ behavior: 'auto', block: 'start' });
  }, [currentPage]);

  useEffect(() => {
    // Immediate check for already loaded (cached) images
    const timer = setInterval(() => {
      let updated = false;
      const nextDims = { ...imgDims };
      for (let pageNum = 1; pageNum <= numPages; pageNum++) {
        if (nextDims[pageNum]) continue;
        const el = document.getElementById(`doc-review-img-${pageNum}`) as HTMLImageElement | null;
        if (el && el.complete && el.naturalWidth > 0 && el.clientWidth > 0) {
          nextDims[pageNum] = {
            natW: el.naturalWidth,
            natH: el.naturalHeight,
            elW: el.clientWidth,
            elH: el.clientHeight,
          };
          updated = true;
        }
      }
      if (updated) {
        setImgDims(nextDims);
      }
    }, 300);

    return () => clearInterval(timer);
  }, [numPages, jobId, imgDims]);

  const handleFieldClick = useCallback((field: Field) => {
    onFieldClick(field);
  }, [onFieldClick]);

  const handleImgLoad = useCallback((pageNum: number) => {
    const el = document.getElementById(`doc-review-img-${pageNum}`) as HTMLImageElement | null;
    if (!el || el.naturalWidth === 0 || el.clientWidth === 0) return;
    setImgDims(prev => ({
      ...prev,
      [pageNum]: {
        natW: el.naturalWidth,
        natH: el.naturalHeight,
        elW: el.clientWidth,
        elH: el.clientHeight,
      },
    }));
  }, []);

  const setBlockRef = useCallback((pageNum: number, el: HTMLDivElement | null) => {
    if (el) blockRefs.current.set(pageNum, el);
    else blockRefs.current.delete(pageNum);
  }, []);

  const toggleFit = useCallback((pageNum: number) => {
    setFitModes(prev => ({ ...prev, [pageNum]: !prev[pageNum] }));
    setImgDims(prev => {
      const d = { ...prev };
      delete d[pageNum];
      return d;
    });
  }, []);

  const selectedOnPage = selectedField?.page;

  if (!numPages || numPages === 0) {
    return (
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--color-text-muted)', fontSize: 14 }}>
        No pages to display.
      </div>
    );
  }

  return (
    <div style={{
      flex: 1, display: 'flex', fontFamily: 'var(--font-sans)',
      background: 'var(--color-bg)', overflow: 'hidden',
    }}>
      {/* ── Left pane: PDF pages (independent scroll) ── */}
      <div style={{
        width: '55%',
        overflowY: 'auto',
        overflowX: 'hidden',
        borderRight: '1px solid var(--color-border)',
        background: '#fafafa',
        display: 'block',
      }}>
        {Array.from({ length: numPages }, (_, i) => {
          const pageNum = i + 1;
          const fitMode = fitModes[pageNum] ?? true;
          const dims = imgDims[pageNum];
          const isSelectedPage = selectedOnPage === pageNum;
          const pageFields = fields.filter(f => f.page === pageNum);

          return (
            <div
              key={pageNum}
              ref={el => setBlockRef(pageNum, el)}
              style={{
                display: 'flex',
                flexDirection: 'column',
                margin: 12,
                minHeight: 'calc(100vh - 180px)',
                height: 'auto',
                borderRadius: 'var(--radius-xl)',
                border: `1px solid ${isSelectedPage ? 'var(--color-primary)' : 'var(--color-border)'}`,
                boxShadow: isSelectedPage
                  ? '0 0 0 2px rgba(37,99,235,0.15), var(--shadow-md)'
                  : 'var(--shadow-sm)',
                background: 'var(--color-surface)',
                transition: 'border-color var(--transition-normal), box-shadow var(--transition-normal)',
                overflow: 'hidden',
              }}
            >
              {/* Page header */}
              <div style={{
                padding: '8px 14px',
                background: 'var(--color-surface)',
                borderBottom: '1px solid var(--color-border)',
                display: 'flex',
                alignItems: 'center',
                gap: 8,
              }}>
                <span style={{ fontWeight: 600, fontSize: 13, color: 'var(--color-text)' }}>Page {pageNum}</span>
                <span style={{ color: 'var(--color-text-placeholder)' }}>·</span>
                <span style={{ fontWeight: 400, color: 'var(--color-text-secondary)', fontSize: 12 }}>
                  {pageFields.length} field{pageFields.length !== 1 ? 's' : ''}
                </span>
                <div style={{ flex: 1 }} />
                <button
                  onClick={() => toggleFit(pageNum)}
                  style={{
                    padding: '2px 8px', fontSize: 11, fontWeight: 500,
                    border: `1px solid ${fitMode ? 'var(--color-primary)' : 'var(--color-border-hover)'}`,
                    borderRadius: 'var(--radius-sm)',
                    background: fitMode ? 'var(--color-primary-light)' : 'var(--color-surface)',
                    color: fitMode ? 'var(--color-primary)' : 'var(--color-text-secondary)',
                    cursor: 'pointer',
                    transition: 'all var(--transition-fast)',
                  }}
                >
                  {fitMode ? 'Fit' : 'Free'}
                </button>
              </div>

              {/* Page image */}
              <div style={{
                flex: 1,
                minHeight: 'auto',
                overflow: fitMode ? 'visible' : 'auto',
                display: 'flex',
                justifyContent: fitMode ? 'center' : 'flex-start',
                alignItems: 'flex-start',
                position: 'relative',
              }}>
                {fitMode ? (
                  <div style={{ position: 'relative', width: '100%' }}>
                    <img
                      id={`doc-review-img-${pageNum}`}
                      src={pageImageUrl(jobId, pdfName ? pageNum : pageOffset + pageNum, pdfName)}
                      onLoad={() => handleImgLoad(pageNum)}
                      style={{ width: '100%', maxWidth: '100%', height: 'auto', display: 'block' }}
                      alt={`Page ${pageNum}`}
                    />
                    {dims && (
                      <>
                        {selectedField?.bbox && isSelectedPage && (
                          <BboxOverlay bbox={selectedField.bbox} color="#3b82f6" natW={dims.natW} natH={dims.natH} elW={dims.elW} elH={dims.elH} />
                        )}
                        {selectedField?.value_bbox && isSelectedPage && (
                          <BboxOverlay bbox={selectedField.value_bbox} color="#22c55e" natW={dims.natW} natH={dims.natH} elW={dims.elW} elH={dims.elH} />
                        )}
                      </>
                    )}
                  </div>
                ) : (
                  <div style={{ position: 'relative', display: 'inline-block', padding: 8 }}>
                    <img
                      id={`doc-review-img-${pageNum}`}
                      src={pageImageUrl(jobId, pdfName ? pageNum : pageOffset + pageNum, pdfName)}
                      onLoad={() => handleImgLoad(pageNum)}
                      style={{ display: 'block', boxShadow: '0 1px 4px rgba(0,0,0,0.1)' }}
                      alt={`Page ${pageNum}`}
                    />
                    {dims && (
                      <>
                        {selectedField?.bbox && isSelectedPage && (
                          <BboxOverlay bbox={selectedField.bbox} color="#3b82f6" natW={dims.natW} natH={dims.natH} elW={dims.elW} elH={dims.elH} />
                        )}
                        {selectedField?.value_bbox && isSelectedPage && (
                          <BboxOverlay bbox={selectedField.value_bbox} color="#22c55e" natW={dims.natW} natH={dims.natH} elW={dims.elW} elH={dims.elH} />
                        )}
                      </>
                    )}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* ── Right pane: Extracted data / Raw text (independent scroll) ── */}
      <div style={{
        width: '45%',
        overflowY: 'auto',
        overflowX: 'hidden',
        background: 'var(--color-bg)',
        display: 'block',
      }}>
        {Array.from({ length: numPages }, (_, i) => {
          const pageNum = i + 1;
          return (
            <div key={pageNum} style={{
              margin: '12px 12px 0 12px',
              borderRadius: 'var(--radius-xl)',
              background: 'var(--color-surface)',
              border: '1px solid var(--color-border)',
              display: 'flex',
              flexDirection: 'column',
              boxShadow: 'var(--shadow-sm)',
              overflow: 'hidden',
            }}>
              <div style={{
                padding: '12px 16px',
                background: '#fafafa',
                borderBottom: '1px solid var(--color-border)',
                fontWeight: 600,
                fontSize: 14,
                color: 'var(--color-text)',
                display: 'flex',
                alignItems: 'center',
                gap: 8,
              }}>
                <span style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  width: 24, height: 24, borderRadius: '50%', background: 'var(--color-primary-light)',
                  color: 'var(--color-primary)', fontSize: 12, fontWeight: 700,
                }}>
                  {pageNum}
                </span>
                Page {pageNum} Data
              </div>
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
                {rightPanelFormat === 'fields' ? (
                  <ExtractedDataPanel
                    fields={fields}
                    sections={sections}
                    selectedField={selectedField}
                    onFieldClick={handleFieldClick}
                    onPageClick={() => {}}
                    currentPage={pageNum}
                    numPages={numPages}
                    jobId={jobId}
                    onFieldsUpdated={onFieldsUpdated}
                    hideToolbar
                  />
                ) : (
                  <EditableTextViewer
                    pageNum={pageNum}
                    rawText={rawText}
                    onSave={handlePageTextChange}
                  />
                )}
              </div>
            </div>
          );
        })}
        {/* Spacer at the bottom so the last item isn't flush against the window edge */}
        <div style={{ height: 12, flexShrink: 0 }} />
      </div>
    </div>
  );
}
