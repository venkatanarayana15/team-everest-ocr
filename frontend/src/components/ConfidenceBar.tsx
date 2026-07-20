import { confidenceColor3Tier } from '../utils/confidence';

interface Props {
  confidence: number;
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
            background: confidenceColor3Tier(confidence),
            borderRadius: 3,
            transition: 'width 0.4s ease',
            boxShadow: confidence >= 80 ? '0 1px 4px rgba(22,163,74,0.3)' : confidence >= 50 ? '0 1px 4px rgba(217,119,6,0.3)' : '0 1px 4px rgba(220,38,38,0.3)',
          }}
        />
      </div>
      <span style={{ fontSize: 13, fontWeight: 600, color: confidenceColor3Tier(confidence), minWidth: 36, fontVariantNumeric: 'tabular-nums' }}>
        {confidence}%
      </span>
    </div>
  );
}
