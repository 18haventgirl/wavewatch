import type {EventKind} from './api';

const tz = 'Asia/Shanghai';

export function clock(ts: number | null | undefined, withDate = true): string {
  if (!ts) return '—';
  const d = new Date(ts * 1000);
  const time = d.toLocaleTimeString('zh-CN', {timeZone: tz, hour: '2-digit', minute: '2-digit', hour12: false});
  if (!withDate) return time;
  const now = new Date();
  const day = (x: Date) => x.toLocaleDateString('zh-CN', {timeZone: tz});
  if (day(d) === day(now)) return '今天 ' + time;
  const yesterday = new Date(now.getTime() - 86400000);
  if (day(d) === day(yesterday)) return '昨天 ' + time;
  const sameYear = d.toLocaleDateString('zh-CN', {timeZone: tz, year: 'numeric'}) === now.toLocaleDateString('zh-CN', {timeZone: tz, year: 'numeric'});
  return d.toLocaleDateString('zh-CN', {timeZone: tz, ...(sameYear ? {} : {year: 'numeric'}), month: 'numeric', day: 'numeric'}) + ' ' + time;
}

export function fullTime(ts: number | null | undefined): string {
  if (!ts) return '—';
  return new Date(ts * 1000).toLocaleString('zh-CN', {timeZone: tz, hour12: false});
}

export function ago(ts: number | null | undefined, now = Date.now() / 1000): string {
  if (!ts) return '从未';
  const s = Math.round(now - ts);
  if (s < 10) return '刚刚';
  if (s < 60) return `${s} 秒前`;
  if (s < 3600) return `${Math.floor(s / 60)} 分钟前`;
  if (s < 86400) return `${Math.floor(s / 3600)} 小时前`;
  return `${Math.floor(s / 86400)} 天前`;
}

export function countdown(ts: number, now = Date.now() / 1000): string {
  const s = Math.max(0, Math.round(ts - now));
  if (s === 0) return '即将检查';
  if (s < 60) return `${s} 秒后`;
  if (s < 3600) return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')} 后`;
  return `${Math.floor(s / 3600)} 小时 ${Math.floor((s % 3600) / 60)} 分后`;
}

export function dayLabel(ts: number): string {
  const now = Date.now() / 1000;
  const key = (t: number) => new Date(t * 1000).toLocaleDateString('zh-CN', {timeZone: tz});
  if (key(ts) === key(now)) return '今天';
  if (key(ts) === key(now - 86400)) return '昨天';
  return new Date(ts * 1000).toLocaleDateString('zh-CN', {timeZone: tz, month: 'long', day: 'numeric', weekday: 'short'});
}

export function bytes(n: number | null | undefined): string {
  if (!n) return '';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function interval(minutes: number): string {
  if (minutes < 60) return `每 ${minutes} 分钟`;
  if (minutes % 60 === 0) return `每 ${minutes / 60} 小时`;
  return `每 ${minutes} 分钟`;
}

export const kindLabel: Record<EventKind, string> = {
  new: '新发布', changed: '正文修订', attachment_new: '新增附件', attachment_changed: '附件更新',
};

export const notifyLabel = {instant: '即时邮件', digest: '每日汇总', off: '不发邮件'} as const;

export function publishedDate(value: string | null): string {
  if (!value) return '';
  return value.slice(0, 10);
}
