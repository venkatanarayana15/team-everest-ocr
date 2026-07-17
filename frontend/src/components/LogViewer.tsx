import { useEffect, useRef } from 'react';

export interface LogLine {
  t: string;
  msg: string;
}

type LogLevel = 'info' | 'warn' | 'error' | 'header' | 'field';

const ANSI_RE = /\x1b\[[0-9;]*[a-zA-Z]/g;

function stripAnsi(s: string): string {
  return s.replace(ANSI_RE, '');
}

function classify(msg: string): LogLevel {
  const m = msg.toLowerCase();
  if (msg.startsWith('📄')) return 'header';
  if (/^\s+[^:]+:\s/.test(msg)) return 'field';
  if (m.includes('error') || m.includes('fail') || m.includes('✗') || m.includes('traceback')) return 'error';
  if (m.includes('warn') || m.includes('⚠')) return 'warn';
  return 'info';
}

const LEVEL_COLOR: Record<LogLevel, string> = {
  info: '#cbd5e1',
  warn: '#fbbf24',
  error: '#f87171',
  header: '#7dd3fc',
  field: '#86efac',
};

const LEVEL_TAG: Record<LogLevel, string> = {
  info: 'INFO',
  warn: 'WARN',
  error: 'ERR ',
  header: 'FILE',
  field: '    ',
};

interface Props {
  logs: LogLine[];
  autoScroll?: boolean;
  height?: number | string;
  emptyText?: string;
}

export default function LogViewer({ logs, autoScroll = false, height = 280, emptyText = 'Waiting for pipeline logs to stream…' }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs, autoScroll]);

  return (
    <div
      ref={scrollRef}
      style={{
        background: 'var(--color-terminal-bg)',
        borderRadius: 'var(--radius-lg)',
        border: '1px solid var(--color-terminal-border)',
        padding: '10px 12px',
        ...(height === '100%'
          ? { flex: 1, minHeight: 0 }
          : { height }),
        overflowY: 'auto',
        fontFamily: 'var(--font-mono)',
        fontSize: 12,
        lineHeight: 1.6,
      }}
    >
      {logs.length === 0 ? (
        <div style={{ color: '#64748b', fontStyle: 'italic' }}>{emptyText}</div>
      ) : (
        logs.map((entry, i) => {
          const clean = stripAnsi(entry.msg);
          const level = classify(clean);
          const isFieldRow = level === 'field' || level === 'header';
          return (
            <div
              key={i}
              style={{
                display: 'flex',
                gap: 8,
                alignItems: 'baseline',
                padding: '1px 6px',
                borderRadius: 3,
                background: level === 'header' ? 'rgba(125,211,252,0.08)' : 'transparent',
                borderLeft: `2px solid ${LEVEL_COLOR[level]}`,
                marginBottom: 1,
              }}
            >
              <span style={{ color: '#64748b', whiteSpace: 'nowrap', userSelect: 'none', flexShrink: 0 }}>
                {entry.t}
              </span>
              {!isFieldRow && (
                <span
                  style={{
                    color: LEVEL_COLOR[level],
                    fontWeight: 700,
                    fontSize: 10,
                    flexShrink: 0,
                    width: 34,
                    textAlign: 'center',
                  }}
                >
                  {LEVEL_TAG[level]}
                </span>
              )}
              <span
                style={{
                  color: LEVEL_COLOR[level],
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                  flex: 1,
                }}
              >
                {clean}
              </span>
            </div>
          );
        })
      )}
    </div>
  );
}
