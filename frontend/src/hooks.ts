import {useCallback, useEffect, useRef, useState} from 'react';

/** Load data, optionally refresh on an interval (paused while the tab is hidden). */
export function useData<T>(load: (signal: AbortSignal) => Promise<T>, deps: unknown[], every = 0) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const loadRef = useRef(load);
  loadRef.current = load;

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    loadRef.current(controller.signal)
      .then(value => { setData(value); setError(''); })
      .catch(e => { if (e.name !== 'AbortError') setError(e.message || '加载失败'); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  useEffect(() => {
    if (!every) return;
    const id = window.setInterval(() => { if (!document.hidden) setTick(t => t + 1); }, every);
    const onVisible = () => { if (!document.hidden) setTick(t => t + 1); };
    document.addEventListener('visibilitychange', onVisible);
    return () => { window.clearInterval(id); document.removeEventListener('visibilitychange', onVisible); };
  }, [every]);

  const reload = useCallback(() => setTick(t => t + 1), []);
  return {data, error, loading, reload, setData};
}

/** Seconds since epoch, updated every second (for countdowns). */
export function useNow(): number {
  const [now, setNow] = useState(Date.now() / 1000);
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => window.clearInterval(id);
  }, []);
  return now;
}

export type Route = {page: string; article: string | null};

function parse(hash: string): Route {
  const parts = hash.replace(/^#\/?/, '').split('/').filter(Boolean);
  if (parts[0] === 'article' && parts[1]) return {page: sessionStorage.getItem('wavewatch.page') || 'overview', article: parts[1]};
  return {page: parts[0] || 'overview', article: null};
}

export function useRoute() {
  const [route, setRoute] = useState<Route>(() => parse(location.hash));
  useEffect(() => {
    const onHash = () => setRoute(parse(location.hash));
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);
  const go = useCallback((page: string) => {
    try { sessionStorage.setItem('wavewatch.page', page); } catch { /* private mode */ }
    location.hash = '#/' + page;
  }, []);
  const open = useCallback((id: string) => {
    try { sessionStorage.setItem('wavewatch.page', parse(location.hash).page); } catch { /* ignore */ }
    location.hash = '#/article/' + id;
  }, []);
  const close = useCallback(() => {
    location.hash = '#/' + (sessionStorage.getItem('wavewatch.page') || 'overview');
  }, []);
  return {route, go, open, close};
}

/** Single-key shortcuts, ignored while typing in a field. */
export function useHotkeys(map: Record<string, (e: KeyboardEvent) => void>, enabled = true) {
  const ref = useRef(map);
  ref.current = map;
  useEffect(() => {
    if (!enabled) return;
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      const typing = ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName) || target.isContentEditable;
      if (e.key === 'Escape' && ref.current.Escape) { ref.current.Escape(e); return; }
      if (typing || e.metaKey || e.ctrlKey || e.altKey) return;
      const handler = ref.current[e.key];
      if (handler) { e.preventDefault(); handler(e); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [enabled]);
}

export function useStored<T>(key: string, initial: T): [T, (v: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try { const raw = localStorage.getItem(key); return raw ? JSON.parse(raw) : initial; } catch { return initial; }
  });
  const update = useCallback((v: T) => {
    setValue(v);
    try { localStorage.setItem(key, JSON.stringify(v)); } catch { /* storage unavailable */ }
  }, [key]);
  return [value, update];
}
