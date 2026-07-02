interface Props {
  confidence: number;
}

function confidenceColor(conf: number): string {
  if (conf >= 80) return '#22c55e';
  if (conf >= 60) return '#eab308';
  return '#ef4444';
}

export default function ConfidenceBar({ confidence }: Props) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div
        style={{
          flex: 1,
          height: 6,
          background: 'var(--color-border)',
          borderRadius: 3,
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            width: `${confidence}%`,
            height: '100%',
            background: confidenceColor(confidence),
            borderRadius: 3,
            transition: 'width 0.4s ease',
            boxShadow: confidence >= 80 ? '0 1px 4px rgba(22,163,74,0.3)' : confidence >= 60 ? '0 1px 4px rgba(234,179,8,0.3)' : '0 1px 4px rgba(239,68,68,0.3)',
          }}
        />
      </div>
      <span style={{ fontSize: 13, fontWeight: 600, color: confidenceColor(confidence), minWidth: 36, fontVariantNumeric: 'tabular-nums' }}>
        {confidence}%
      </span>
    </div>
  );
}
