import React from 'react';

interface Props {
  children: React.ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export default class ErrorBoundary extends React.Component<Props, State> {
  state: State = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('[ErrorBoundary]', error, info);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{
          padding: 24, fontFamily: 'var(--font-sans)',
          background: 'var(--color-danger-light)', border: '1px solid var(--color-danger-border)',
          borderRadius: 'var(--radius-lg)', margin: 16,
        }}>
          <h2 style={{ color: 'var(--color-danger)', margin: '0 0 8px 0', fontSize: 16 }}>
            Render Error
          </h2>
          <pre style={{
            fontSize: 12, color: 'var(--color-danger-dark)', whiteSpace: 'pre-wrap',
            background: 'var(--color-surface)', padding: 12, borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--color-danger-border)',
          }}>
            {this.state.error?.message}
            {'\n'}
            {this.state.error?.stack}
          </pre>
          <button onClick={() => this.setState({ hasError: false, error: null })}
            style={{
              marginTop: 8, padding: '6px 14px',
              border: 'none', borderRadius: 'var(--radius-md)',
              background: 'var(--color-danger)', color: '#fff', cursor: 'pointer',
              fontWeight: 600,
            }}>
            Retry
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}