import { useState, useRef, useCallback } from 'react';

interface Props {
  left: React.ReactNode;
  right: React.ReactNode;
}

export default function SplitPane({ left, right }: Props) {
  const [split, setSplit] = useState(55);
  const dragging = useRef(false);

  const handleMouseDown = useCallback(() => {
    dragging.current = true;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  }, []);

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (!dragging.current) return;
    const pct = (e.clientX / window.innerWidth) * 100;
    setSplit(Math.max(25, Math.min(75, pct)));
  }, []);

  const handleMouseUp = useCallback(() => {
    dragging.current = false;
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
  }, []);

  return (
    <div
      style={{ display: 'flex', flex: 1, overflow: 'hidden' }}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
    >
      <div style={{ width: `${split}%`, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>{left}</div>
      <div
        onMouseDown={handleMouseDown}
        style={{
          width: 4,
          cursor: 'col-resize',
          background: 'var(--color-border)',
          flexShrink: 0,
          transition: 'background var(--transition-fast)',
        }}
        onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--color-primary)'; }}
        onMouseLeave={(e) => { e.currentTarget.style.background = 'var(--color-border)'; }}
      />
      <div style={{ flex: 1, overflow: 'hidden', display: 'flex' }}>{right}</div>
    </div>
  );
}
