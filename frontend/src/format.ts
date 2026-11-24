import type {EventKind, Notify} from './api';
import {isEn, locale, t} from './i18n';

export const APP_NAME = 'Wavewatch THVS';

const tz = 'Asia/Shanghai';
const dayKey = (d: Date) => d.toLocaleDateString('en-CA', {timeZone: tz});

export function clock(ts: number | null | undefined, withDate = true): string {
  if (!ts) return '—';
  const d = new Date(ts * 1000);
  const time = d.toLocaleTimeString('zh-CN', {timeZone: tz, hour: '2-digit', minute: '2-digit', hour12: false});
  if (!withDate) return time;
  const now = new Date();
  if (dayKey(d) === dayKey(now)) return t('今天 ', 'Today ') + time;
  if (dayKey(d) === dayKey(new Date(now.getTime() - 86400000))) return t('昨天 ', 'Yesterday ') + time;
  const sameYear = dayKey(d).slice(0, 4) === dayKey(now).slice(0, 4);
  const date = d.toLocaleDateString(locale(), {timeZone: tz, ...(sameYear ? {} : {year: 'numeric'}),
    month: isEn() ? 'short' : 'numeric', day: 'numeric'});
  return date + ' ' + time;
}

/** Full date and time; numeric, so it reads the same in both languages. */
export function fullTime(ts: number | null | undefined): string {
  if (!ts) return '—';
  return new Date(ts * 1000).toLocaleString('zh-CN', {timeZone: tz, hour12: false});
}

/** Time of day in Beijing, HH:MM:SS. */
export function beijingClock(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString('zh-CN', {timeZone: tz, hour12: false});
}

/** A length of time, e.g. "5 分钟" / "5 min". */
export function duration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return t(`${s} 秒`, `${s} s`);
  if (s < 3600) return t(`${Math.floor(s / 60)} 分钟`, `${Math.floor(s / 60)} min`);
  if (s < 86400) return t(`${Math.floor(s / 3600)} 小时`, `${Math.floor(s / 3600)} h`);
  return t(`${Math.floor(s / 86400)} 天`, `${Math.floor(s / 86400)} d`);
}

export function ago(ts: number | null | undefined, now = Date.now() / 1000): string {
  if (!ts) return t('从未', 'never');
  const s = Math.round(now - ts);
  if (s < 10) return t('刚刚', 'just now');
  return t(`${duration(s)}前`, `${duration(s)} ago`);
}

export function countdown(ts: number, now = Date.now() / 1000): string {
  const s = Math.max(0, Math.round(ts - now));
  if (s === 0) return t('即将检查', 'due now');
  if (s < 60) return t(`${s} 秒后`, `in ${s} s`);
  if (s < 3600) {
    const mmss = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
    return t(`${mmss} 后`, `in ${mmss}`);
  }
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return t(`${h} 小时 ${m} 分后`, `in ${h} h ${m} min`);
}

export function dayLabel(ts: number): string {
  const now = Date.now() / 1000;
  const d = new Date(ts * 1000);
  if (dayKey(d) === dayKey(new Date(now * 1000))) return t('今天', 'Today');
  if (dayKey(d) === dayKey(new Date((now - 86400) * 1000))) return t('昨天', 'Yesterday');
  return d.toLocaleDateString(locale(), {timeZone: tz, month: 'long', day: 'numeric', weekday: isEn() ? 'long' : 'short'});
}

export function bytes(n: number | null | undefined): string {
  if (!n) return '';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function interval(minutes: number): string {
  if (minutes >= 60 && minutes % 60 === 0) return t(`每 ${minutes / 60} 小时`, `every ${minutes / 60} h`);
  return t(`每 ${minutes} 分钟`, `every ${minutes} min`);
}

export function everyHours(hours: number): string {
  if (hours >= 24 && hours % 24 === 0) return t(`每 ${hours / 24} 天`, `every ${hours / 24} d`);
  return t(`每 ${hours} 小时`, `every ${hours} h`);
}

export function kindLabel(kind: EventKind): string {
  return {
    new: t('新发布', 'New'), changed: t('正文修订', 'Revised'),
    attachment_new: t('新增附件', 'New file'), attachment_changed: t('附件更新', 'File changed'),
  }[kind];
}

export function notifyLabel(mode: Notify): string {
  return {instant: t('即时邮件', 'instant e-mail'), digest: t('每日汇总', 'daily digest'), off: t('不发邮件', 'no e-mail')}[mode];
}

export function publishedDate(value: string | null): string {
  if (!value) return '';
  return value.slice(0, 10);
}

/** "A、B、C" / "A, B, C" */
export const list = (items: string[]) => items.join(t('、', ', '));
