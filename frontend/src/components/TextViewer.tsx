import type { Field, Section } from '../types';
import TranscriptionPane from './TranscriptionPane';
import ExtractedDataPanel from './ExtractedDataPanel';

interface Props {
  rawText: string;
  fields: Field[];
  sections: Section[];
  selectedField: Field | null;
  currentPage: number;
  jobId: string;
  onFieldClick: (field: Field) => void;
  onFieldsUpdated: (fields: Field[]) => void;
  onPageChange: (page: number) => void;
  numPages: number;
}

export default function TextViewer({
  rawText, fields, sections, selectedField,
  currentPage, jobId, onFieldClick, onFieldsUpdated,
  onPageChange, numPages,
}: Props) {
  return (
    <div style={{
      flex: 1, display: 'flex', overflow: 'hidden',
      fontFamily: 'var(--font-sans)',
    }}>
      <div style={{
        width: '55%', display: 'flex', flexDirection: 'column',
        minHeight: 0, borderRight: '1px solid var(--color-border)',
      }}>
        <div style={{
          padding: '8px 14px', background: 'var(--color-surface)',
          borderBottom: '1px solid var(--color-border)',
          display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0,
        }}>
          <span style={{ fontWeight: 600, fontSize: 13, color: 'var(--color-text)' }}>
            OCR Transcription
          </span>
          <span style={{ color: 'var(--color-text-placeholder)' }}>·</span>
          <span style={{ fontWeight: 400, color: 'var(--color-text-secondary)', fontSize: 12 }}>
            Page {currentPage} / {numPages}
          </span>
        </div>
        <TranscriptionPane
          rawText={rawText}
          fields={fields}
          currentPage={currentPage}
          onFieldClick={onFieldClick}
          jobId={jobId}
          onFieldsUpdated={onFieldsUpdated}
        />
      </div>
      <div style={{
        width: '45%', display: 'flex', flexDirection: 'column',
        minHeight: 0, overflow: 'hidden',
      }}>
        <ExtractedDataPanel
          fields={fields}
          sections={sections}
          selectedField={selectedField}
          onFieldClick={onFieldClick}
          onPageClick={onPageChange}
          currentPage={currentPage}
          numPages={numPages}
          jobId={jobId}
          onFieldsUpdated={onFieldsUpdated}
        />
      </div>
    </div>
  );
}
