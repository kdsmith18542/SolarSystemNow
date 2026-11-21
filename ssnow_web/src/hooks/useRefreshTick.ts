import { useEffect, useState } from 'react';

/**
 * Shared refresh signal: SSE ingest events and the manual Refresh button bump
 * a tick instead of remounting the active view (which would reset filters,
 * map camera and unsaved form state).
 */
export function useRefreshTick(): number {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const handler = () => setTick((value) => value + 1);
    window.addEventListener('ssnow:refresh', handler);
    return () => window.removeEventListener('ssnow:refresh', handler);
  }, []);
  return tick;
}
