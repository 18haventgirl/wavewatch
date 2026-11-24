import React, {createContext, useCallback, useContext, useEffect, useRef, useState} from 'react';
import {ChevronLeft, ChevronRight, LoaderCircle} from 'lucide-react';
import type {Column, EventKind} from './api';
import {kindLabel} from './format';
import {columnName, groupName, t} from './i18n';

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'plain' | 'quiet' | 'danger'; icon?: React.ReactNode; busy?: boolean; small?: boolean;
};

export function Button({variant = 'plain', icon, busy, small, children, className = '', disabled, ...rest}: ButtonProps) {
  return <button className={`btn btn-${variant}${small ? ' btn-small' : ''} ${className}`} disabled={disabled || busy} {...rest}>
    {busy ? <LoaderCircle size={small ? 14 : 16} className="spin"/> : icon}{children}
  </button>;
}

export function Segmented<T extends string>({options, value, onChange, label}: {
  options: {value: T; label: string; count?: number}[]; value: T; onChange: (v: T) => void; label: string;
}) {
  return <div className="segmented" role="radiogroup" aria-label={label}>
    {options.map(o => <button key={o.value} role="radio" aria-checked={value === o.value}
      className={value === o.value ? 'on' : ''} onClick={() => onChange(o.value)}>
      {o.label}{o.count !== undefined ? <span className="seg-count">{o.count}</span> : null}
    </button>)}
  </div>;
}

export function Toggle({checked, onChange, label, disabled}: {checked: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean}) {
  return <button type="button" role="switch" aria-checked={checked} aria-label={label} disabled={disabled}
    className={'toggle' + (checked ? ' on' : '')} onClick={() => onChange(!checked)}><span/></button>;
}

export function Field({label, hint, children, wide}: {label: string; hint?: React.ReactNode; children: React.ReactNode; wide?: boolean}) {
  return <label className={'field' + (wide ? ' wide' : '')}>
    <span className="field-label">{label}</span>{children}{hint ? <span className="field-hint">{hint}</span> : null}
  </label>;
}

export function Empty({icon, title, children, action}: {icon?: React.ReactNode; title: string; children?: React.ReactNode; action?: React.ReactNode}) {
  return <div className="empty">{icon ? <div className="empty-icon">{icon}</div> : null}<h3>{title}</h3>
    {children ? <p>{children}</p> : null}{action}</div>;
}

export function Loading({label}: {label?: string}) {
  return <div className="loading"><LoaderCircle size={18} className="spin"/>{label ?? t('正在读取…', 'Loading…')}</div>;
}

export function ErrorNote({message, onRetry}: {message: string; onRetry?: () => void}) {
  return <div className="error-note" role="alert"><span>{message}</span>{onRetry ? <button onClick={onRetry}>{t('重试', 'Retry')}</button> : null}</div>;
}

export function KindBadge({kind}: {kind: EventKind}) {
  return <span className={'kind kind-' + kind}>{kindLabel(kind)}</span>;
}

export function ColumnTag({column}: {column: Column}) {
  return <span className={'col-tag' + (column.role === 'core' ? ' core' : '')} title={groupName(column.group)}>
    {column.role === 'core' ? <i className="seal" aria-hidden="true">政</i> : null}{columnName(column.id, column.name)}
  </span>;
}

export function Pager({page, total, size, onPage}: {page: number; total: number; size: number; onPage: (p: number) => void}) {
  const pages = Math.max(1, Math.ceil(total / size));
  if (total <= size) return <div className="pager"><span>{t(`共 ${total} 条`, `${total} total`)}</span></div>;
  return <div className="pager">
    <span>{t(`共 ${total} 条，第 ${page} / ${pages} 页`, `${total} total, page ${page} of ${pages}`)}</span>
    <div>
      <button className="icon-btn" aria-label={t('上一页', 'Previous page')} disabled={page <= 1} onClick={() => onPage(page - 1)}><ChevronLeft size={17}/></button>
      <button className="icon-btn" aria-label={t('下一页', 'Next page')} disabled={page >= pages} onClick={() => onPage(page + 1)}><ChevronRight size={17}/></button>
    </div>
  </div>;
}

export function Dot({tone}: {tone: 'ok' | 'warn' | 'error' | 'idle' | 'live'}) {
  return <i className={'dot dot-' + tone} aria-hidden="true"/>;
}

// --- toast ---------------------------------------------------------------------------------

type Toast = {id: number; text: string; tone: 'ok' | 'error'};
const ToastContext = createContext<(text: string, tone?: 'ok' | 'error') => void>(() => undefined);

export function ToastProvider({children}: {children: React.ReactNode}) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const counter = useRef(0);
  const show = useCallback((text: string, tone: 'ok' | 'error' = 'ok') => {
    const id = ++counter.current;
    setToasts(t => [...t.slice(-2), {id, text, tone}]);
    window.setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), tone === 'error' ? 7000 : 3500);
  }, []);
  return <ToastContext.Provider value={show}>{children}
    <div className="toasts" role="status" aria-live="polite">
      {toasts.map(t => <div key={t.id} className={'toast toast-' + t.tone}>{t.text}</div>)}
    </div>
  </ToastContext.Provider>;
}

export const useToast = () => useContext(ToastContext);

/** Run an async action with a busy flag and a toast for the outcome. */
export function useAction() {
  const toast = useToast();
  const [busy, setBusy] = useState('');
  const run = useCallback(async (key: string, fn: () => Promise<unknown>, done?: string) => {
    setBusy(key);
    try {
      await fn();
      if (done) toast(done);
      return true;
    } catch (e) {
      toast(e instanceof Error ? e.message : t('操作没有完成', 'The action did not finish'), 'error');
      return false;
    } finally {
      setBusy('');
    }
  }, [toast]);
  return {busy, run};
}

export function useDebounced<T>(value: T, ms = 250): T {
  const [v, setV] = useState(value);
  useEffect(() => { const id = window.setTimeout(() => setV(value), ms); return () => window.clearTimeout(id); }, [value, ms]);
  return v;
}
