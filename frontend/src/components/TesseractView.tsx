import { useState, useEffect, useRef } from 'react';
import { getTesseractData, pageImageUrl } from '../api/client';
import type { TesseractWord, Field, TesseractData } from '../types';

interface Props {
  jobId: string;
  currentPage: number;
  fields: Field[];
  selectedField: Field | null;
  onFieldClick: (field: Field) => void;
}

const TESS_COLOR = '#94a3b8';
const TESS_HIGH_CONF = '#16a34a';
const LABEL_COLOR = '#3b82f6';
const VALUE_COLOR = '#22c55e';
const SV_WIDTH = 800;
const SV_HEIGHT = 1100;

export default function TesseractView({ jobId, currentPage, fields, selectedField, onFieldClick }: Props) {
  const [tesseractData, setTesseractData] = useState<TesseractData | null>(null);
  const [loading, setLoading] = useState(true);
  const [imgSize, setImgSize] = useState<{ w: number; h: number } | null>(null);
  const [showAllPages, setShowAllPages] = useState(false);
  const imgRef = useRef<HTMLImageElement>(null);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const data = await getTesseractData(jobId);
        setTesseractData(data);
      } catch (e) {
        console.error('Failed to load tesseract data:', e);
      }
      setLoading(false);
    })();
  }, [jobId]);

  const words = tesseractData?.pages?.[String(currentPage)] || [];
  const pageFields = fields.filter(f => f.page === currentPage);

  const handleImgLoad = () => {
    if (imgRef.current) {
      setImgSize({
        w: imgRef.current.clientWidth,
        h: imgRef.current.clientHeight,
      });
    }
  };

  // Group words by approximate Y-line for table view
  const lines = groupWordsByLine(words);

  if (loading) {
    return (
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--color-text-muted)', fontSize: 16 }}>
        <div style={{ textAlign: 'center' }}>
          <div className="spinner" style={{ margin: '0 auto 12px' }} />
          Loading tesseract data...
        </div>
      </div>
    );
  }

  if (!tesseractData) {
    return (
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--color-text-muted)', fontSize: 16 }}>
        Tesseract data not available yet.
      </div>
    );
  }

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', background: 'var(--color-bg)' }}>
      {/* Header */}
      <div style={{
        padding: '8px 16px', background: 'var(--color-surface)', borderBottom: '1px solid var(--color-border)',
        display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap', fontSize: 14,
      }}>
        <span style={{ fontWeight: 700, color: 'var(--color-text)' }}>
          Tesseract OCR Mapping — Page {currentPage}
        </span>
        <span style={{ color: 'var(--color-text-secondary)' }}>{words.length} words detected</span>
        <span style={{ color: 'var(--color-text-muted)' }}>·</span>
        <span style={{ color: 'var(--color-label)' }}>■ Label bbox</span>
        <span style={{ color: 'var(--color-value)' }}>■ Value bbox</span>
        <span style={{ color: TESS_COLOR }}>■ Tesseract word</span>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
          <button
            onClick={() => setShowAllPages(!showAllPages)}
            style={{
              padding: '4px 12px', fontSize: 13, fontWeight: 500,
              border: `1px solid ${showAllPages ? 'var(--color-primary)' : 'var(--color-border-hover)'}`,
              borderRadius: 'var(--radius-sm)',
              background: showAllPages ? 'var(--color-primary-light)' : 'var(--color-surface)',
              color: showAllPages ? 'var(--color-primary)' : 'var(--color-text-secondary)',
              cursor: 'pointer',
              transition: 'all var(--transition-fast)',
            }}
          >
            {showAllPages ? 'Current page only' : 'All pages'}
          </button>
        </div>
      </div>

      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        {/* Left: Image with bbox overlays */}
        <div style={{ flex: 1, overflow: 'auto', display: 'flex', justifyContent: 'center', padding: 8, position: 'relative' }}>
          <div style={{ position: 'relative', display: 'inline-block' }}>
            <img
              ref={imgRef}
              src={pageImageUrl(jobId, currentPage)}
              onLoad={handleImgLoad}
              style={{ display: 'block', maxWidth: '100%', boxShadow: 'var(--shadow-sm)' }}
              alt={`Page ${currentPage}`}
            />
            {imgSize && (
              <svg
                width={imgSize.w}
                height={imgSize.h}
                style={{ position: 'absolute', top: 0, left: 0, pointerEvents: 'none' }}
              >
                {/* Tesseract word boxes */}
                {words.map((w, i) => (
                  <rect
                    key={`tess-${i}`}
                    x={(w.bbox[0] / SV_WIDTH) * imgSize.w}
                    y={(w.bbox[1] / SV_HEIGHT) * imgSize.h}
                    width={((w.bbox[2] - w.bbox[0]) / SV_WIDTH) * imgSize.w}
                    height={((w.bbox[3] - w.bbox[1]) / SV_HEIGHT) * imgSize.h}
                    fill="none"
                    stroke={w.confidence >= 80 ? TESS_HIGH_CONF : TESS_COLOR}
                    strokeWidth={1}
                    strokeDasharray={w.confidence < 80 ? '3,3' : 'none'}
                    opacity={0.7}
                  />
                ))}
                {/* Field label bboxes */}
                {pageFields.filter(f => f.bbox).map((f, i) => (
                  <rect
                    key={`label-${i}`}
                    x={(f.bbox![0] / SV_WIDTH) * imgSize.w}
                    y={(f.bbox![1] / SV_HEIGHT) * imgSize.h}
                    width={((f.bbox![2] - f.bbox![0]) / SV_WIDTH) * imgSize.w}
                    height={((f.bbox![3] - f.bbox![1]) / SV_HEIGHT) * imgSize.h}
                    fill={f === selectedField ? `${LABEL_COLOR}44` : 'none'}
                    stroke={f === selectedField ? '#dc2626' : LABEL_COLOR}
                    strokeWidth={f === selectedField ? 3 : 2}
                    style={{ pointerEvents: 'auto', cursor: 'pointer' }}
                    onClick={() => onFieldClick(f)}
                  >
                    <title>{f.label}: {f.value}</title>
                  </rect>
                ))}
                {/* Field value bboxes */}
                {pageFields.filter(f => f.value_bbox).map((f, i) => (
                  <rect
                    key={`val-${i}`}
                    x={(f.value_bbox![0] / SV_WIDTH) * imgSize.w}
                    y={(f.value_bbox![1] / SV_HEIGHT) * imgSize.h}
                    width={((f.value_bbox![2] - f.value_bbox![0]) / SV_WIDTH) * imgSize.w}
                    height={((f.value_bbox![3] - f.value_bbox![1]) / SV_HEIGHT) * imgSize.h}
                    fill={f === selectedField ? `${VALUE_COLOR}44` : 'none'}
                    stroke={f === selectedField ? '#dc2626' : VALUE_COLOR}
                    strokeWidth={f === selectedField ? 3 : 2}
                    style={{ pointerEvents: 'auto', cursor: 'pointer' }}
                    onClick={() => onFieldClick(f)}
                  >
                    <title>{f.label}: {f.value}</title>
                  </rect>
                ))}
              </svg>
            )}
          </div>
        </div>

        {/* Right: Word list table */}
        <div style={{
          width: 340, borderLeft: '1px solid var(--color-border)', background: 'var(--color-surface)',
          display: 'flex', flexDirection: 'column', overflow: 'hidden',
        }}>
          <div style={{
            padding: '8px 12px', borderBottom: '1px solid var(--color-border)',
            fontSize: 13, fontWeight: 600, color: 'var(--color-text-tertiary)',
          }}>
            Tesseract Words · {words.length} total
          </div>
          <div style={{ flex: 1, overflow: 'auto', padding: 4 }}>
            {lines.length === 0 && (
              <p style={{ padding: 16, color: 'var(--color-text-muted)', fontSize: 13 }}>No words detected.</p>
            )}
            {lines.map((line, i) => (
              <div key={i} style={{ marginBottom: 4, fontSize: 13 }}>
                <div style={{
                  padding: '3px 8px', background: 'var(--color-surface-active)', borderRadius: 3,
                  fontSize: 11, color: 'var(--color-text-secondary)', fontFamily: 'var(--font-mono)', marginBottom: 2,
                }}>
                  Line {i + 1} · y≈{Math.round(line.words[0]?.bbox[1] || 0)}
                </div>
                {line.words.map((w, j) => (
                  <div
                    key={j}
                    style={{
                      display: 'inline-block',
                      padding: '2px 6px', margin: '1px 2px',
                      borderRadius: 3,
                      background: w.confidence >= 80 ? 'var(--color-success-light)' : 'var(--color-warning-light)',
                      border: `1px solid ${w.confidence >= 80 ? 'var(--color-success-border)' : 'var(--color-warning-border)'}`,
                      fontSize: 12, fontFamily: 'var(--font-mono)',
                    }}
                    title={`conf: ${w.confidence}%`}
                  >
                    {w.text}
                    <span style={{ fontSize: 10, color: 'var(--color-text-muted)', marginLeft: 3 }}>
                      {w.confidence}%
                    </span>
                  </div>
                ))}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function groupWordsByLine(words: TesseractWord[], yTolerance = 15): Array<{ words: TesseractWord[] }> {
  if (words.length === 0) return [];
  const sorted = [...words].sort((a, b) => a.bbox[1] - b.bbox[1] || a.bbox[0] - b.bbox[0]);
  const lines: Array<{ words: TesseractWord[] }> = [{ words: [sorted[0]] }];
  for (let i = 1; i < sorted.length; i++) {
    const prev = lines[lines.length - 1].words[lines[lines.length - 1].words.length - 1];
    if (Math.abs(sorted[i].bbox[1] - prev.bbox[1]) < yTolerance) {
      lines[lines.length - 1].words.push(sorted[i]);
    } else {
      lines.push({ words: [sorted[i]] });
    }
  }
  return lines;
}
