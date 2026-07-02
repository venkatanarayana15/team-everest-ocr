import { useState, useRef, useEffect } from 'react';
import type { Field } from '../types';

interface Props {
  imageUrl: string;
  selectedField: Field | null;
  pageNum: number;
  jobId: string;
}

const LABEL_COLOR = '#3b82f6';
const VALUE_COLOR = '#22c55e';

export default function ImageViewer({ imageUrl, selectedField, pageNum, jobId }: Props) {
  const [imgNatural, setImgNatural] = useState<{ w: number; h: number } | null>(null);
  const [imgDisplay, setImgDisplay] = useState<{ w: number; h: number } | null>(null);
  const [fitMode, setFitMode] = useState(true);
  const [imgError, setImgError] = useState(false);
  const imgRef = useRef<HTMLImageElement>(null);

  useEffect(() => {
    setImgNatural(null);
    setImgDisplay(null);
    setImgError(false);
  }, [imageUrl]);

  const handleLoad = () => {
    if (!imgRef.current) return;
    setImgError(false);
    const w = imgRef.current.naturalWidth;
    const h = imgRef.current.naturalHeight;
    setImgNatural({ w, h });
    setImgDisplay({ w: imgRef.current.clientWidth, h: imgRef.current.clientHeight });
  };

  const handleError = () => {
    setImgError(true);
  };

  const scaleX = imgNatural && imgDisplay ? imgDisplay.w / imgNatural.w : 1;
  const scaleY = imgNatural && imgDisplay ? imgDisplay.h / imgNatural.h : 1;

  const renderBbox = (
    bbox: [number, number, number, number],
    color: string,
  ): React.CSSProperties => ({
    position: 'absolute',
    left: bbox[0] * scaleX,
    top: bbox[1] * scaleY,
    width: (bbox[2] - bbox[0]) * scaleX,
    height: (bbox[3] - bbox[1]) * scaleY,
    border: `2px solid ${color}`,
    background: `${color}22`,
    borderRadius: 2,
    pointerEvents: 'none',
    transition: 'all 0.15s',
  });

  return (
    <div
      style={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        background: 'var(--color-bg)',
        overflow: 'hidden',
        minHeight: 0,
      }}
    >
      <div
        style={{
          padding: '6px 12px',
          background: 'var(--color-surface)',
          borderBottom: '1px solid var(--color-border)',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          fontSize: 13,
        }}
      >
        <span style={{ fontWeight: 600, color: 'var(--color-text)' }}>Page {pageNum}</span>
        <span style={{ color: 'var(--color-text-placeholder)' }}>|</span>
        <button
          onClick={() => setFitMode(!fitMode)}
          style={{
            padding: '2px 8px',
            fontSize: 11,
            fontWeight: 500,
            border: `1px solid ${fitMode ? 'var(--color-primary)' : 'var(--color-border-hover)'}`,
            borderRadius: 'var(--radius-sm)',
            background: fitMode ? 'var(--color-primary-light)' : 'var(--color-surface)',
            color: fitMode ? 'var(--color-primary)' : 'var(--color-text-secondary)',
            cursor: 'pointer',
            transition: 'all var(--transition-fast)',
          }}
        >
          {fitMode ? 'Fit width' : 'Free scroll'}
        </button>
      </div>

      <div
        style={{
          flex: 1,
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: fitMode ? 'center' : 'flex-start',
          overflow: 'auto',
          padding: 8,
          position: 'relative',
          minHeight: 0,
        }}
      >
        {imgError ? (
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            minHeight: 300, color: 'var(--color-text-muted)', fontSize: 14, fontWeight: 500,
          }}>
            <span>Page image not available</span>
          </div>
        ) : (
        <div style={{ position: 'relative', display: 'inline-block' }}>
          <img
            ref={imgRef}
            src={imageUrl}
            onLoad={handleLoad}
            onError={handleError}
            style={{
              maxWidth: fitMode ? '100%' : 'none',
              width: fitMode ? '100%' : 'auto',
              height: 'auto',
              display: 'block',
              boxShadow: 'var(--shadow-sm)',
              borderRadius: 'var(--radius-sm)',
            }}
            alt="Document page"
          />
          {selectedField?.bbox && imgNatural && imgDisplay && (
            <div style={renderBbox(selectedField.bbox, LABEL_COLOR)} />
          )}
          {selectedField?.value_bbox && imgNatural && imgDisplay && (
            <div style={renderBbox(selectedField.value_bbox, VALUE_COLOR)} />
          )}
          </div>
        )}
      </div>
    </div>
  );
}
