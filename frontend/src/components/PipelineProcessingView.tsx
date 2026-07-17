import { useEffect, useRef } from 'react';
import LogViewer from './LogViewer';

interface FieldSummary {
  label: string;
  value: string | null;
  confidence: number;
  page: number;
}

interface Props {
  jobId: string;
  files: Array<{ name: string; jobId?: string }>;
  status: string;
  statusMessage: string;
  progress: number;
  overallProgress: number | null;
  perPdfProgress: Record<string, { progress: number; stage: string; elapsed?: number }>;
  logs: Array<{ t: string; msg: string }>;
  elapsed?: number | null;
  fields?: FieldSummary[];
  onBack: () => void;
  onResumeJob?: (jobId: string) => void;
  onResumeBatch?: () => void;
  onStartOver?: () => void;
  onViewResults?: () => void;
}

const STAGES = [
  { key: 'queued',                 label: 'Uploaded',              icon: '📋' },
  { key: 'preprocessing',          label: 'Preprocessing',         icon: '🖼️' },
  { key: 'primary_extraction',     label: 'Primary Extraction',    icon: '🤖' },
  { key: 'field_mapping',          label: 'Field Mapping',         icon: '🗺️' },
  { key: 'secondary_verification', label: 'Verification',          icon: '✅' },
  { key: 'done',                   label: 'Complete',              icon: '🎉' },
];

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

const STAGE_MAPPING: Record<string, string> = {
  queued: 'queued',
  preprocessing: 'preprocessing',
  primary_extraction: 'primary_extraction',
  extracting: 'primary_extraction',
  field_mapping: 'field_mapping',
  secondary_verification: 'secondary_verification',
  template_fill: 'secondary_verification',
  done: 'done',
};

function confidenceColor(conf: number): string {
  if (conf >= 80) return '#22c55e';
  if (conf >= 50) return '#eab308';
  return '#ef4444';
}

export default function PipelineProcessingView({
  jobId, files, status, statusMessage, progress,
  overallProgress, perPdfProgress, logs, elapsed, fields, onBack,
  onResumeJob, onResumeBatch, onStartOver, onViewResults
}: Props) {
  const stageOrder = STAGES.map(s => s.key);
  const mappedKey = STAGE_MAPPING[status] || 'queued';
  const stageIndex = stageOrder.indexOf(mappedKey);

  return (
    <div style={{
      flex: 1, display: 'flex',
      background: 'var(--color-bg)',
      fontFamily: 'var(--font-sans)', overflow: 'hidden',
    }}>
      {/* ── Left Sidebar: Progress Tracking ── */}
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
            Processing Progress
          </span>
        </div>

        {overallProgress != null && (
          <div style={{ padding: '8px 12px', borderBottom: '1px solid var(--color-border)' }}>
            <div style={{
              display: 'flex', alignItems: 'center', gap: 6,
              fontSize: 11, color: 'var(--color-text-secondary)', marginBottom: 4,
            }}>
              <span style={{ fontWeight: 600 }}>Overall Progress</span>
              <span style={{ fontWeight: 700, color: 'var(--color-primary)' }}>{overallProgress}%</span>
              {elapsed != null && (
                <span style={{ marginLeft: 'auto', fontWeight: 500, color: 'var(--color-text-muted)', fontSize: 10 }}>
                  ⏱️ {elapsed}s
                </span>
              )}
            </div>
            <ProgressBar value={overallProgress} />
          </div>
        )}

        <div style={{ flex: 1, overflow: 'auto', padding: 4 }}>
          {files.length === 0 ? (
            <div style={{ padding: 16, textAlign: 'center', fontSize: 12, color: 'var(--color-text-muted)' }}>
              No files in batch
            </div>
          ) : (
            files.map((p, i) => {
              const pp = perPdfProgress?.[p.name];
              const progressVal = pp?.progress ?? progress;
              const statusVal = pp?.stage || status;
              const statusColor = statusVal === 'done' ? 'var(--color-success)'
                : statusVal === 'error' ? 'var(--color-danger)'
                : 'var(--color-warning)';
              const isError = statusVal === 'error';
              return (
                <div
                  key={p.name || i}
                  style={{
                    padding: '8px 10px', borderRadius: 'var(--radius-md)',
                    borderBottom: '1px solid var(--color-border-light)',
                    background: 'transparent',
                  }}
                >
                  <div style={{ fontSize: 12, fontWeight: 500, color: 'var(--color-text)', display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span>📄</span>
                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }} title={p.name}>
                      {p.name}
                    </span>
                  </div>
                  <div style={{ display: 'flex', gap: 6, marginTop: 2, fontSize: 10, color: 'var(--color-text-muted)', alignItems: 'center' }}>
                    <span style={{ color: statusColor, fontWeight: 600 }}>{statusVal.replace(/_/g, ' ')}</span>
                    {pp?.elapsed != null && (
                      <span style={{ color: 'var(--color-text-muted)', marginLeft: 'auto', fontSize: 9 }}>
                        ⏳ {pp.elapsed}s
                      </span>
                    )}
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 4 }}>
                    <ProgressBar value={progressVal} />
                    <span style={{ fontSize: 10, fontWeight: 600, color: 'var(--color-text-secondary)', minWidth: 28, textAlign: 'right' }}>
                      {progressVal}%
                    </span>
                    {isError && p.jobId && onResumeJob && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          onResumeJob(p.jobId!);
                        }}
                        style={{
                          padding: '2px 8px', fontSize: 10, fontWeight: 600,
                          border: 'none', borderRadius: 4,
                          background: 'var(--color-success)', color: '#fff',
                          cursor: 'pointer', marginLeft: 4,
                        }}
                      >
                        🔄 Resume
                      </button>
                    )}
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>

      {/* ── Main content: Header, Milestones & Pipeline Logs ── */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        <div style={{
          padding: '12px 24px', borderBottom: '1px solid var(--color-border)',
          background: 'rgba(255,255,255,0.85)', backdropFilter: 'blur(12px)',
          display: 'flex', alignItems: 'center', gap: 12,
          position: 'relative',
          zIndex: 5,
        }}>
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
          <div style={{
            width: 32, height: 32, borderRadius: 8,
            background: 'var(--color-primary-gradient)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: '#fff', fontSize: 16, fontWeight: 700,
            boxShadow: 'var(--shadow-primary)',
          }}>O</div>
          <h1 style={{ fontSize: 20, fontWeight: 700, color: 'var(--color-text)', margin: 0, letterSpacing: '-0.02em' }}>
            Pipeline Progress
          </h1>
          {jobId && (
            <span style={{
              fontSize: 11, color: 'var(--color-text-muted)', fontFamily: 'var(--font-mono)',
              marginLeft: 'auto', background: 'var(--color-surface-active)', padding: '2px 8px',
              borderRadius: 'var(--radius-sm)',
            }}>
              {jobId}
            </span>
          )}
        </div>

        <div style={{ flex: 1, overflow: 'auto', padding: 24, display: 'flex', flexDirection: 'column', gap: 20 }}>
          {/* Milestones Flow */}
          <div style={{
            background: 'var(--color-surface)', borderRadius: 'var(--radius-xl)',
            padding: '16px 20px', boxShadow: 'var(--shadow-md)',
            border: '1px solid var(--color-border)',
          }}>
            <h3 style={{ fontSize: 13, color: 'var(--color-text-secondary)', margin: '0 0 12px 0', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Pipeline Milestones
            </h3>
            <div style={{ display: 'flex', gap: 4, marginBottom: 12 }}>
              {STAGES.map((s, i) => {
                const isPast = stageIndex > i;
                const isCurrent = stageIndex === i;
                const isError = status === 'error' && isCurrent;
                return (
                  <div key={s.key} style={{
                    flex: 1, display: 'flex', flexDirection: 'column',
                    alignItems: 'center', gap: 4, position: 'relative',
                  }}>
                    {i > 0 && (
                      <div style={{
                        position: 'absolute', top: 14, left: '-50%',
                        width: '100%', height: 2,
                        background: isPast ? 'var(--color-primary)' : 'var(--color-border)',
                        zIndex: 0,
                      }} />
                    )}
                    <div style={{
                      width: 28, height: 28, borderRadius: 14,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      fontSize: 12, fontWeight: 700, zIndex: 1,
                      background: isError ? 'var(--color-danger-light)' : isPast ? 'var(--color-primary)' : isCurrent ? 'var(--color-primary-light)' : 'var(--color-bg)',
                      border: `2px solid ${
                        isError ? 'var(--color-danger)' : isPast ? 'var(--color-primary)' : isCurrent ? 'var(--color-primary)' : 'var(--color-border)'
                      }`,
                      color: isPast ? '#fff' : isCurrent ? 'var(--color-primary)' : 'var(--color-text-muted)',
                      transition: 'all var(--transition-normal)',
                    }}>
                      {isPast ? '✓' : isError ? '✗' : s.icon}
                    </div>
                    <span style={{
                      fontSize: 10, color: isCurrent ? 'var(--color-primary)' : 'var(--color-text-muted)',
                      fontWeight: isCurrent ? 600 : 400, textAlign: 'center',
                      whiteSpace: 'nowrap',
                    }}>
                      {s.label}
                    </span>
                  </div>
                );
              })}
            </div>
            <div style={{ width: '100%', height: 4, background: 'var(--color-border)', borderRadius: 2, overflow: 'hidden' }}>
              <div style={{
                width: `${progress}%`, height: '100%',
                background: 'linear-gradient(90deg, var(--color-primary), var(--color-primary-border))',
                borderRadius: 2, transition: 'width 0.5s ease',
              }} />
            </div>
          </div>

          {/* Status Message */}
          {statusMessage && (
            <div style={{
              display: 'flex', alignItems: 'center', gap: 8,
              padding: '10px 14px', borderRadius: 'var(--radius-lg)',
              background: status === 'error' ? 'var(--color-danger-light)' : 'var(--color-info-light)',
              border: `1px solid ${status === 'error' ? 'var(--color-danger-border)' : 'var(--color-info-border)'}`,
            }}>
              <span style={{ fontSize: 16 }}>
                {status === 'error' ? '❌' : '⏳'}
              </span>
              <span style={{
                fontSize: 13, fontWeight: 500,
                color: status === 'error' ? 'var(--color-danger)' : 'var(--color-info)',
              }}>
                {statusMessage}
              </span>
            </div>
          )}

          {/* Extracted Fields */}
          {fields && fields.length > 0 && (
            <div style={{
              background: 'var(--color-surface)', borderRadius: 'var(--radius-xl)',
              padding: '14px 18px', boxShadow: 'var(--shadow-md)',
              border: '1px solid var(--color-border)',
            }}>
              <h3 style={{
                fontSize: 13, color: 'var(--color-text-secondary)', margin: '0 0 10px 0',
                fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em',
                display: 'flex', alignItems: 'center', gap: 8,
              }}>
                <span>📋</span>
                <span>Extracted Fields ({fields.length})</span>
                <span style={{
                  fontSize: 10, color: 'var(--color-text-muted)', fontWeight: 400,
                  fontFamily: 'var(--font-mono)', textTransform: 'none',
                }}>
                  live from pipeline
                </span>
              </h3>
              <div style={{ maxHeight: 240, overflow: 'auto' }}>
                <table style={{
                  width: '100%', borderCollapse: 'collapse',
                  fontSize: 12, fontFamily: 'var(--font-mono)',
                }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid var(--color-border)', color: 'var(--color-text-muted)', fontSize: 10 }}>
                      <th style={{ padding: '4px 8px', textAlign: 'left', fontWeight: 500 }}>Page</th>
                      <th style={{ padding: '4px 8px', textAlign: 'left', fontWeight: 500 }}>Label</th>
                      <th style={{ padding: '4px 8px', textAlign: 'left', fontWeight: 500 }}>Value</th>
                      <th style={{ padding: '4px 8px', textAlign: 'right', fontWeight: 500 }}>Conf</th>
                    </tr>
                  </thead>
                  <tbody>
                    {fields.map((f, i) => (
                      <tr key={i} style={{
                        borderBottom: '1px solid var(--color-border-light)',
                        background: i % 2 === 0 ? 'transparent' : 'rgba(0,0,0,0.02)',
                      }}>
                        <td style={{
                          padding: '3px 8px', color: 'var(--color-text-muted)',
                          textAlign: 'center', fontSize: 10,
                        }}>
                          {f.page}
                        </td>
                        <td style={{
                          padding: '3px 8px', color: 'var(--color-text)',
                          maxWidth: 260, overflow: 'hidden', textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                        }} title={f.label}>
                          {f.label}
                        </td>
                        <td style={{
                          padding: '3px 8px', color: 'var(--color-text-secondary)',
                          maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                        }} title={f.value}>
                          {f.value || <span style={{ color: '#94a3b8', fontStyle: 'italic' }}>empty</span>}
                        </td>
                        <td style={{
                          padding: '3px 8px', textAlign: 'right',
                        }}>
                          <span style={{
                            display: 'inline-block', padding: '1px 6px', borderRadius: 4,
                            fontSize: 10, fontWeight: 600,
                            color: confidenceColor(f.confidence) === '#22c55e' ? '#166534'
                              : confidenceColor(f.confidence) === '#eab308' ? '#854d0e'
                              : '#991b1b',
                            background: confidenceColor(f.confidence) === '#22c55e' ? '#dcfce7'
                              : confidenceColor(f.confidence) === '#eab308' ? '#fef9c3'
                              : '#fee2e2',
                          }}>
                            {f.confidence}%
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Terminal logs */}
          <div style={{
            background: 'var(--color-terminal-bg)', borderRadius: 'var(--radius-xl)',
            border: '1px solid var(--color-terminal-header)', overflow: 'hidden',
            boxShadow: '0 4px 16px rgba(0,0,0,0.2)',
            flex: 1, display: 'flex', flexDirection: 'column', minHeight: 250,
          }}>
            <div style={{
              display: 'flex', alignItems: 'center', gap: 8,
              padding: '8px 14px', background: 'var(--color-terminal-header)',
              borderBottom: '1px solid var(--color-terminal-border)',
              flexShrink: 0,
            }}>
              <div style={{ display: 'flex', gap: 5 }}>
                <div style={{ width: 10, height: 10, borderRadius: '50%', background: '#ef4444' }} />
                <div style={{ width: 10, height: 10, borderRadius: '50%', background: '#eab308' }} />
                <div style={{ width: 10, height: 10, borderRadius: '50%', background: '#22c55e' }} />
              </div>
              <span style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--color-text-muted)', marginLeft: 6 }}>
                tesseract_pipeline.log
              </span>
              <span style={{
                marginLeft: 'auto', fontSize: 10, fontFamily: 'var(--font-mono)',
                color: 'var(--color-text-muted)', background: 'rgba(148,163,184,0.15)',
                padding: '1px 8px', borderRadius: 10,
              }}>
                {logs.length} entries
              </span>
            </div>
            <LogViewer logs={logs} autoScroll height="100%" emptyText="Waiting for pipeline logs to stream…" />
          </div>
          {/* Action Buttons */}
          {(status === 'error' || status === 'done' || status === 'incomplete') && (
            <div style={{ display: 'flex', gap: 12, justifyContent: 'center', marginTop: 12 }}>
              {status === 'done' && onViewResults && (
                <button
                  onClick={onViewResults}
                  style={{
                    padding: '10px 24px', fontSize: 14, fontWeight: 600,
                    border: 'none', borderRadius: 'var(--radius-lg)', cursor: 'pointer',
                    background: 'var(--color-success)', color: '#fff',
                    transition: 'all var(--transition-fast)',
                    boxShadow: '0 2px 8px rgba(22,163,74,0.3)',
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.filter = 'brightness(1.05)'; }}
                  onMouseLeave={(e) => { e.currentTarget.style.filter = 'none'; }}
                >
                  🎉 View Results
                </button>
              )}
              {(status === 'error' || status === 'incomplete') && onResumeBatch && jobId && (
                <button
                  onClick={onResumeBatch}
                  style={{
                    padding: '10px 24px', fontSize: 14, fontWeight: 600,
                    border: 'none', borderRadius: 'var(--radius-lg)', cursor: 'pointer',
                    background: 'var(--color-success)', color: '#fff',
                    transition: 'all var(--transition-fast)',
                    boxShadow: '0 2px 8px rgba(22,163,74,0.3)',
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.filter = 'brightness(1.05)'; }}
                  onMouseLeave={(e) => { e.currentTarget.style.filter = 'none'; }}
                >
                  🔄 Resume Batch
                </button>
              )}
              {onStartOver && (
                <button
                  onClick={onStartOver}
                  style={{
                    padding: '10px 24px', fontSize: 14, fontWeight: 600,
                    border: 'none', borderRadius: 'var(--radius-lg)', cursor: 'pointer',
                    background: 'var(--color-primary-gradient)', color: '#fff',
                    boxShadow: 'var(--shadow-primary)',
                    transition: 'all var(--transition-fast)',
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.filter = 'brightness(1.05)'; }}
                  onMouseLeave={(e) => { e.currentTarget.style.filter = 'none'; }}
                >
                  ↩️ Start Over
                </button>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
