import { useEffect, useRef, useCallback } from 'react';

/**
 * Custom polling hook with AbortController and visibility-aware pausing.
 *
 * - Pauses polling when the tab is hidden (saves network + CPU)
 * - Cancels in-flight requests on unmount or pause
 * - Resumes immediately when the tab becomes visible again
 *
 * Usage:
 *   usePolling(async (signal) => {
 *     const res = await fetch('/api/status', { signal });
 *     setData(await res.json());
 *   }, 5000, enabled);
 */
export function usePolling(
  callback: (signal: AbortSignal) => Promise<void>,
  intervalMs: number,
  enabled: boolean = true,
) {
  const callbackRef = useRef(callback);
  callbackRef.current = callback;

  const abortRef = useRef<AbortController | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const cancel = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const tick = useCallback(async () => {
    if (document.visibilityState === 'hidden') return;
    const ac = new AbortController();
    abortRef.current = ac;
    try {
      await callbackRef.current(ac.signal);
    } catch (e: unknown) {
      if (e instanceof DOMException && e.name === 'AbortError') return;
      // Don't crash the loop on transient errors
      console.warn('[usePolling] callback error:', e);
    }
  }, []);

  useEffect(() => {
    if (!enabled) {
      cancel();
      return;
    }

    // Initial tick
    tick();

    // Schedule recurring ticks
    const schedule = () => {
      timerRef.current = setTimeout(async () => {
        await tick();
        schedule();
      }, intervalMs);
    };
    schedule();

    // Pause on visibility change
    const onVisibility = () => {
      if (document.visibilityState === 'hidden') {
        cancel();
      } else {
        tick();
        schedule();
      }
    };
    document.addEventListener('visibilitychange', onVisibility);

    return () => {
      cancel();
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [enabled, intervalMs, tick, cancel]);
}
