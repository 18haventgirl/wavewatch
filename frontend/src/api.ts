export type Role = 'core' | 'news';
export type Notify = 'instant' | 'digest' | 'off';
export type EventKind = 'new' | 'changed' | 'attachment_new' | 'attachment_changed';

export type Column = {id: string; name: string; role: Role; group: string};

export type Run = {
  id: number; source_id: string; name?: string; mode: 'quick' | 'full'; started: number; finished: number | null;
  state: 'running' | 'ok' | 'error' | 'interrupted'; pages: number; rows: number; added: number; message: string;
};

export type Source = {
  id: string; name: string; grp: string; role: Role; column_id: number; page_url: string;
  enabled: number; list_minutes: number; article_hours: number; notify: Notify;
  state: 'idle' | 'checking' | 'ok' | 'error'; error: string; fail_count: number; initialized: number;
  reported_total: number | null; last_check: number | null; last_success: number | null; last_full: number | null;
  next_check: number; full_requested: number; articles: number; unread: number;
  last_run: Run | null; last_added: {at: number | null; total: number | null} | null;
  history: {started: number; state: Run['state']; added: number; mode: Run['mode']}[];
};

export type UpdateEvent = {
  id: number; kind: EventKind; created: number; summary: string; read_at: number | null; route: string;
  email_id: number | null; version_id: number | null; article_id: string; title: string; url: string;
  published: string | null; article_kind: string; attachment_id: string | null; attachment_title: string | null;
  columns: Column[];
};

export type WorkerStatus = {task: string; beat: number | null; error: string};

export type Overview = {
  now: number; started: number; healthy: boolean;
  stats: {articles: number; attachments: number; unread: number; today_new: number; today_changed: number;
    week_events: number; check_errors: number; due: number; never_checked: number};
  email: {enabled: boolean; ready: boolean; recipients: number; digest_time: string; pending: number; failed: number;
    last_sent: number | null; last_error: string};
  sources: Source[]; recent: UpdateEvent[]; workers: Record<string, WorkerStatus>;
  import: {articles?: number; from_snapshot?: number; error?: string; at?: number} | null;
};

export type ArticleRow = {
  id: string; url: string; kind: 'article' | 'attachment'; title: string; subtitle: string; origin: string;
  published: string | null; discovered: number; last_check: number | null; next_check: number; check_error: string;
  title_ok: number; versions: number; attachments: number; unread: number; changes: number; last_event: number | null;
  columns: Column[];
};

export type Version = {id: number; created: number; digest: string; baseline: number; note: string;
  file_digest: string | null; length: number; file_bytes: number | null};

export type Attachment = {id: string; url: string; title: string; last_check: number | null; check_error: string;
  file_digest: string | null; versions: number; bytes: number | null};

export type ArticleDetail = ArticleRow & {
  content: string; versions: Version[]; attachments: Attachment[]; parents: {id: string; title: string}[];
  events: UpdateEvent[]; fail_count: number;
  entries: {source_id: string; name: string; page: number | null; position: number | null; first_seen: number;
    last_seen: number; raw_title: string}[];
};

export type DiffRow = {type: 'same' | 'changed' | 'added' | 'removed' | 'fold'; old?: string | null; new?: string | null;
  old_no?: number | null; new_no?: number | null; count?: number; spans?: {old: number[][]; new: number[][]} | null};

export type Compare = {base: number | null; target: number | null; rows: DiffRow[]; stats: {added: number; removed: number}};

export type EmailSettings = {
  enabled: boolean; host: string; port: number; security: 'ssl' | 'starttls' | 'none'; username: string;
  sender: string; sender_name: string; recipients: string[]; merge_minutes: number; digest_time: string;
  digest_include_instant: boolean; digest_send_empty: boolean; alert_failures: number; enabled_since: number | null;
  password_set: boolean; password_protected: boolean;
};

export type Email = {id: number; kind: 'instant' | 'digest' | 'alert' | 'test'; subject: string; recipients: string[];
  created: number; state: 'pending' | 'sent' | 'failed'; attempts: number; next_attempt: number; last_error: string;
  sent_at: number | null; events: number};

export type SystemState = {keep_awake: boolean; keep_awake_supported: boolean; autostart: boolean;
  autostart_supported: boolean; data_dir: string; url: string};

export type Page<T> = {items: T[]; total: number; page: number; size: number};

export class ApiError extends Error {}

export async function api<T>(path: string, init?: RequestInit & {json?: unknown}): Promise<T> {
  const {json, ...rest} = init || {};
  const response = await fetch('/api' + path, {
    ...rest,
    headers: json !== undefined ? {'Content-Type': 'application/json', ...(rest.headers || {})} : rest.headers,
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  });
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    let message = '服务没有响应，请确认 Wavewatch THVS 正在运行';
    if (data && typeof data.detail === 'string') message = data.detail;
    else if (data && Array.isArray(data.detail)) message = data.detail.map((d: {msg: string}) => d.msg.replace(/^Value error, /, '')).join('；');
    throw new ApiError(message);
  }
  return response.json();
}

export const post = <T,>(path: string, json?: unknown) => api<T>(path, {method: 'POST', json: json ?? {}});
export const patch = <T,>(path: string, json: unknown) => api<T>(path, {method: 'PATCH', json});
export const put = <T,>(path: string, json: unknown) => api<T>(path, {method: 'PUT', json});
