import { useEffect, useRef, useState } from 'react';
import type { RunEvent } from './client';

/** Live log events of a run (Server-Sent Events); replays what happened before connecting. */
export function useRunEvents(runId: string | undefined, onEvent?: (e: RunEvent) => void) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [state, setState] = useState<'connecting' | 'live' | 'ended' | 'error'>('connecting');
  const handler = useRef(onEvent);
  handler.current = onEvent;

  useEffect(() => {
    if (!runId) return;
    setEvents([]);
    setState('connecting');
    let lastSeq = 0;
    let buffer: RunEvent[] = [];
    let timer: ReturnType<typeof setTimeout> | null = null;
    const flush = () => {
      timer = null;
      if (!buffer.length) return;
      const batch = buffer;
      buffer = [];
      setEvents((prev) => [...prev, ...batch].slice(-5000));
    };
    const source = new EventSource(`/api/runs/${runId}/events`);
    source.onopen = () => setState('live');
    source.onmessage = (msg) => {
      const event = JSON.parse(msg.data) as RunEvent;
      if (event.seq <= lastSeq) return;
      lastSeq = event.seq;
      buffer.push(event);
      handler.current?.(event);
      if (!timer) timer = setTimeout(flush, 120);
    };
    source.addEventListener('end', () => {
      flush();
      setState('ended');
      source.close();
    });
    source.onerror = () => {
      if (source.readyState === EventSource.CLOSED) setState((s) => (s === 'ended' ? s : 'error'));
    };
    return () => {
      if (timer) clearTimeout(timer);
      source.close();
    };
  }, [runId]);

  return { events, state };
}
