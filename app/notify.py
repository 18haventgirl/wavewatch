"""E-mail notifications.

* instant: changes in columns set to 「即时」 are collected for a short merge window
  and sent as one message;
* digest:  a daily summary at a fixed Beijing time for columns set to 「每日汇总」
  (optionally recapping instant items too);
* alert:   a column failing repeatedly, and its recovery.

Messages are first written to the ``emails`` outbox inside the same transaction
that marks the events as handled, then delivered with retries.  Nothing is sent
for events that happened before e-mail was switched on.
"""
from __future__ import annotations

import html
import json
import logging
import smtplib
import ssl
import time
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

import truststore

from . import config, db, diffing, secret

log = logging.getLogger('guanlan.notify')

DEFAULTS = {
    'enabled': False,
    'host': '',
    'port': 465,
    'security': 'ssl',          # ssl | starttls | none
    'username': '',
    'password': '',             # sealed with app.secret
    'sender': '',
    'sender_name': '观澜监测',
    'recipients': [],
    'merge_minutes': 2,
    'digest_time': '18:00',
    'digest_include_instant': True,
    'digest_send_empty': False,
    'alert_failures': 3,
    'enabled_since': None,
}
RETRY_MINUTES = [1, 5, 15, 30, 60, 120, 240]
KIND_LABEL = {'new': '新发布', 'changed': '正文修订', 'attachment_new': '新增附件', 'attachment_changed': '附件更新'}
KIND_COLOR = {'new': '#0a84ff', 'changed': '#ff9f0a', 'attachment_new': '#30b0c7', 'attachment_changed': '#bf5af2'}


# --- settings -----------------------------------------------------------------------------------

def load(conn) -> dict:
    return {**DEFAULTS, **db.get_setting(conn, 'email', {})}


def public(settings: dict) -> dict:
    """Settings as shown in the UI: never includes the password itself."""
    data = {k: v for k, v in settings.items() if k != 'password'}
    data['password_set'] = bool(settings.get('password'))
    data['password_protected'] = secret.PROTECTED
    return data


def save(conn, changes: dict) -> dict:
    current = load(conn)
    updated = {**current, **{k: v for k, v in changes.items() if k in DEFAULTS and k not in ('password', 'enabled_since')}}
    if changes.get('password'):
        updated['password'] = secret.seal(changes['password'])
    if changes.get('clear_password'):
        updated['password'] = ''
    if updated['enabled'] and not current['enabled']:
        updated['enabled_since'] = time.time()
        db.set_setting(conn, 'digest_last', time.time())
    db.set_setting(conn, 'email', updated)
    return updated


def ready(settings: dict) -> bool:
    return bool(settings['enabled'] and settings['host'] and settings['recipients'])


# --- composing -----------------------------------------------------------------------------------

def _bj(ts: float | None, fmt: str = '%m-%d %H:%M') -> str:
    return datetime.fromtimestamp(ts, config.BEIJING).strftime(fmt) if ts else '—'


def _event_rows(conn, event_ids: list[int]) -> list[dict]:
    if not event_ids:
        return []
    marks = ','.join('?' * len(event_ids))
    items = db.rows(conn, f'''
        SELECT e.*, a.title, a.url, a.published, a.subtitle, s_names.names AS columns,
               c.title AS attachment_title, c.url AS attachment_url
        FROM events e JOIN articles a ON a.id=e.article_id
        LEFT JOIN articles c ON c.id=e.attachment_id
        LEFT JOIN (SELECT en.article_id, GROUP_CONCAT(DISTINCT s.name) AS names
                   FROM entries en JOIN sources s ON s.id=en.source_id GROUP BY en.article_id) s_names
               ON s_names.article_id=e.article_id
        WHERE e.id IN ({marks}) ORDER BY e.created''', event_ids)
    for item in items:
        item['excerpt'] = []
        if item['kind'] == 'changed' and item['version_id']:
            current = db.row(conn, 'SELECT article_id, content FROM versions WHERE id=?', (item['version_id'],))
            previous = db.row(conn, 'SELECT content FROM versions WHERE article_id=? AND id<? ORDER BY id DESC LIMIT 1',
                              (current['article_id'], item['version_id'])) if current else None
            if current and previous:
                item['excerpt'] = diffing.excerpt(previous['content'], current['content'])
    return items


def _render_items(items: list[dict]) -> tuple[str, str]:
    text_parts, html_parts = [], []
    for it in items:
        label = KIND_LABEL[it['kind']]
        local = f"{config.LOCAL_URL}/#/article/{it['article_id']}"
        extra = ''
        if it['kind'].startswith('attachment') and it['attachment_title']:
            extra = f"附件：{it['attachment_title']}"
        elif it['summary']:
            extra = it['summary']
        text_parts.append('\n'.join(filter(None, [
            f"[{label}] {it['title']}",
            f"栏目：{it['columns'] or '—'}　原站发布：{it['published'] or '—'}　发现：{_bj(it['created'])}",
            extra,
            *[f"  {sign} {line}" for sign, line in it['excerpt']],
            f"原文：{it['url']}",
            f"本机查看：{local}",
        ])))
        excerpt = ''.join(
            f'<div style="font-family:Menlo,Consolas,monospace;font-size:12px;padding:2px 8px;border-radius:4px;'
            f'background:{"#e8f7ec" if sign == "+" else "#fdecec"};color:{"#1d6b35" if sign == "+" else "#a1251b"};'
            f'margin:2px 0">{sign} {html.escape(line)}</div>' for sign, line in it['excerpt'])
        html_parts.append(f'''
<tr><td style="padding:16px 20px;border-bottom:1px solid #eef0f4">
  <span style="display:inline-block;font-size:12px;font-weight:600;color:#fff;background:{KIND_COLOR[it['kind']]};
        border-radius:10px;padding:2px 9px">{label}</span>
  <span style="font-size:12px;color:#6e7685;margin-left:6px">{html.escape(it['columns'] or '')}</span>
  <div style="font-size:16px;font-weight:600;margin:8px 0 4px;color:#1d1d1f;line-height:1.45">
    <a href="{html.escape(it['url'])}" style="color:#1d1d1f;text-decoration:none">{html.escape(it['title'])}</a></div>
  <div style="font-size:12px;color:#6e7685">原站发布 {html.escape(it['published'] or '—')} · 发现于 {_bj(it['created'])}</div>
  {f'<div style="font-size:13px;color:#3a3f4a;margin-top:6px">{html.escape(extra)}</div>' if extra else ''}
  {f'<div style="margin-top:8px">{excerpt}</div>' if excerpt else ''}
  <div style="margin-top:10px;font-size:13px">
    <a href="{html.escape(it['url'])}" style="color:#0a66d6;text-decoration:none">查看官网原文 →</a>
    <a href="{local}" style="color:#6e7685;text-decoration:none;margin-left:14px">在观澜中查看</a></div>
</td></tr>''')
    return '\n\n'.join(text_parts), ''.join(html_parts)


def _wrap(title: str, intro: str, rows_html: str, footer: str = '') -> str:
    return f'''<!doctype html><html><body style="margin:0;background:#f2f4f8;padding:24px 12px;
font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif">
<table role="presentation" width="100%" style="max-width:640px;margin:0 auto;background:#ffffff;border-radius:16px;
  border-collapse:separate;overflow:hidden;box-shadow:0 2px 10px rgba(15,30,60,.06)">
<tr><td style="padding:22px 20px 14px;background:linear-gradient(135deg,#eaf3ff,#f6f0ff)">
  <div style="font-size:12px;letter-spacing:.08em;color:#6e7685">观澜 · 中国出口管制信息网监测</div>
  <div style="font-size:20px;font-weight:700;color:#1d1d1f;margin-top:4px">{html.escape(title)}</div>
  <div style="font-size:13px;color:#3a3f4a;margin-top:6px">{html.escape(intro)}</div></td></tr>
{rows_html}
<tr><td style="padding:14px 20px;font-size:12px;color:#8a919e">{footer or '此邮件由本机观澜监测服务自动发送。'}
  <a href="{config.LOCAL_URL}" style="color:#8a919e">打开观澜</a></td></tr>
</table></body></html>'''


def _queue(conn, kind: str, subject: str, text_body: str, html_body: str, recipients: list[str]) -> int:
    return int(conn.execute(
        "INSERT INTO emails(kind,subject,text_body,html_body,recipients,created,state) VALUES(?,?,?,?,?,?,'pending')",
        (kind, subject, text_body, html_body, json.dumps(recipients), time.time())).lastrowid)


# --- routing --------------------------------------------------------------------------------------

def queue_instant(now: float | None = None) -> int | None:
    now = now or time.time()
    with db.tx() as conn:
        settings = load(conn)
        if not ready(settings):
            return None
        # Wait for the merge window, and give a brand-new article up to 10 minutes to have its
        # body fetched so the message can include it.
        pending = db.rows(conn, '''
            SELECT e.id, e.created FROM events e JOIN articles a ON a.id=e.article_id
            WHERE e.route='instant' AND e.email_id IS NULL AND e.created>=?
            ORDER BY e.created''', (settings['enabled_since'] or now,))
        if not pending or pending[0]['created'] > now - settings['merge_minutes'] * 60:
            return None
        items = _event_rows(conn, [p['id'] for p in pending])
        waiting = [i for i in items if i['kind'] == 'new' and now - i['created'] < 600 and not _checked(conn, i['article_id'])]
        if waiting and len(waiting) == len(items):
            return None
        items = [i for i in items if i not in waiting]
        text_body, rows_html = _render_items(items)
        first = items[0]
        if len(items) == 1:
            subject = f"【观澜】{KIND_LABEL[first['kind']]}：{first['title']}"
        else:
            subject = f"【观澜】{len(items)} 条核心更新：{first['title']} 等"
        intro = f"{_bj(now, '%Y-%m-%d %H:%M')} 检测到 {len(items)} 条需要立即关注的更新。"
        email_id = _queue(conn, 'instant', subject[:200], intro + '\n\n' + text_body,
                          _wrap('核心栏目更新', intro, rows_html), settings['recipients'])
        conn.executemany('UPDATE events SET email_id=? WHERE id=?', [(email_id, i['id']) for i in items])
        return email_id


def _checked(conn, article_id: str) -> bool:
    return conn.execute('SELECT last_check IS NOT NULL FROM articles WHERE id=?', (article_id,)).fetchone()[0] == 1


def digest_due_at(settings: dict, now: float) -> float:
    """Epoch time of the most recent scheduled digest at or before ``now``."""
    hour, minute = (int(x) for x in settings['digest_time'].split(':'))
    local = datetime.fromtimestamp(now, config.BEIJING)
    slot = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if slot > local:
        slot -= timedelta(days=1)
    return slot.timestamp()


def queue_digest(now: float | None = None, *, force: bool = False) -> int | None:
    now = now or time.time()
    with db.tx() as conn:
        settings = load(conn)
        if not ready(settings):
            return None
        slot = now if force else digest_due_at(settings, now)
        last = db.get_setting(conn, 'digest_last', settings['enabled_since'] or now)
        if not force and last >= slot:
            return None
        ids = [r[0] for r in conn.execute(
            "SELECT id FROM events WHERE created>? AND created<=? AND route IN (?, ?) ORDER BY created",
            (last, slot, 'digest', 'instant' if settings['digest_include_instant'] else 'digest'))]
        items = _event_rows(conn, ids)
        db.set_setting(conn, 'digest_last', slot)
        if not items and not settings['digest_send_empty'] and not force:
            return None
        health = db.rows(conn, 'SELECT name, state, error, last_success FROM sources WHERE configured=1 ORDER BY position')
        counts = {k: sum(1 for i in items if i['kind'] == k) for k in KIND_LABEL}
        day = datetime.fromtimestamp(slot, config.BEIJING)
        head = '、'.join(f'{KIND_LABEL[k]} {v}' for k, v in counts.items() if v) or '没有新的发布或修订'
        intro = f"{_bj(last, '%m-%d %H:%M')} 至 {_bj(slot, '%m-%d %H:%M')}：{head}。"
        problems = [h for h in health if h['state'] == 'error']
        health_text = '栏目状态：' + ('全部正常' if not problems else '；'.join(f"{h['name']} 检查失败（{h['error']}）" for h in problems))
        text_body, rows_html = _render_items(items)
        health_html = (f'<tr><td style="padding:12px 20px;font-size:13px;color:{"#a1251b" if problems else "#1d6b35"}">'
                       f'{html.escape(health_text)}</td></tr>')
        subject = f"【观澜日报】{day.month}月{day.day}日 · {head}"
        email_id = _queue(conn, 'digest', subject[:200], intro + '\n' + health_text + '\n\n' + text_body,
                          _wrap('每日汇总', intro, health_html + rows_html), settings['recipients'])
        return email_id


def queue_alerts(now: float | None = None) -> list[int]:
    now = now or time.time()
    queued = []
    with db.tx() as conn:
        settings = load(conn)
        if not ready(settings):
            return queued
        for src in db.rows(conn, 'SELECT * FROM sources WHERE configured=1 AND enabled=1'):
            if src['fail_count'] >= settings['alert_failures'] and not src['alerted_at']:
                subject = f"【观澜提醒】{src['name']} 连续 {src['fail_count']} 次检查失败"
                body = (f"栏目「{src['name']}」最近 {src['fail_count']} 次检查都没有成功。\n原因：{src['error']}\n"
                        f"最后一次成功：{_bj(src['last_success'], '%Y-%m-%d %H:%M')}\n恢复正常后会再发一封邮件。")
                queued.append(_queue(conn, 'alert', subject, body, _wrap(subject, body, ''), settings['recipients']))
                conn.execute('UPDATE sources SET alerted_at=? WHERE id=?', (now, src['id']))
            elif src['alerted_at'] and src['fail_count'] == 0:
                subject = f"【观澜提醒】{src['name']} 已恢复正常"
                body = f"栏目「{src['name']}」已于 {_bj(src['last_success'], '%m-%d %H:%M')} 恢复检查。"
                queued.append(_queue(conn, 'alert', subject, body, _wrap(subject, body, ''), settings['recipients']))
                conn.execute('UPDATE sources SET alerted_at=NULL WHERE id=?', (src['id'],))
    return queued


# --- delivery -----------------------------------------------------------------------------------------

PERMANENT = (smtplib.SMTPAuthenticationError, smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused)


def send(settings: dict, subject: str, text_body: str, html_body: str, recipients: list[str]) -> None:
    msg = EmailMessage()
    sender = settings['sender'] or settings['username']
    msg['Subject'] = subject
    msg['From'] = formataddr((settings['sender_name'] or '观澜监测', sender))
    msg['To'] = ', '.join(recipients)
    msg['Message-ID'] = make_msgid(domain=sender.split('@')[-1] if '@' in sender else 'guanlan.local')
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype='html')
    context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    port = int(settings['port'])
    if settings['security'] == 'ssl':
        server: smtplib.SMTP = smtplib.SMTP_SSL(settings['host'], port, timeout=30, context=context)
    else:
        server = smtplib.SMTP(settings['host'], port, timeout=30)
    with server:
        if settings['security'] == 'starttls':
            server.starttls(context=context)
        if settings['username']:
            server.login(settings['username'], secret.unseal(settings['password']))
        server.send_message(msg)


def explain(exc: BaseException) -> str:
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return '邮箱登录被拒绝：请检查账号和授权码（QQ/163 邮箱需使用“授权码”，不是登录密码）'
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return '收件地址被邮件服务器拒绝，请检查收件人'
    if isinstance(exc, smtplib.SMTPSenderRefused):
        return '发件地址被拒绝，发件人通常需要与登录账号一致'
    if isinstance(exc, (TimeoutError, OSError)) and 'timed out' in str(exc).lower():
        return '连接邮件服务器超时，请检查服务器地址、端口和网络'
    if isinstance(exc, ssl.SSLError):
        return f'加密连接失败：端口与加密方式可能不匹配（465 用 SSL，587 用 STARTTLS）。{exc}'[:300]
    if isinstance(exc, ConnectionRefusedError):
        return '邮件服务器拒绝连接，请检查服务器地址和端口'
    return (str(exc) or exc.__class__.__name__)[:300]


def deliver(now: float | None = None, limit: int = 5) -> int:
    now = now or time.time()
    with db.tx() as conn:
        settings = load(conn)
        due = db.rows(conn, "SELECT * FROM emails WHERE state='pending' AND next_attempt<=? ORDER BY id LIMIT ?", (now, limit))
    sent = 0
    for mail in due:
        try:
            if not settings['host']:
                raise RuntimeError('尚未设置邮件服务器')
            send(settings, mail['subject'], mail['text_body'], mail['html_body'], json.loads(mail['recipients']))
        except Exception as exc:  # noqa: BLE001
            attempts = mail['attempts'] + 1
            permanent = isinstance(exc, PERMANENT) or attempts > len(RETRY_MINUTES)
            log.warning('email %s failed (attempt %d): %s', mail['id'], attempts, exc)
            with db.tx() as conn:
                conn.execute('UPDATE emails SET attempts=?, last_error=?, state=?, next_attempt=? WHERE id=?',
                             (attempts, explain(exc), 'failed' if permanent else 'pending',
                              time.time() + RETRY_MINUTES[min(attempts, len(RETRY_MINUTES)) - 1] * 60, mail['id']))
            if permanent and isinstance(exc, smtplib.SMTPAuthenticationError):
                break
            continue
        with db.tx() as conn:
            conn.execute("UPDATE emails SET state='sent', attempts=attempts+1, sent_at=?, last_error='' WHERE id=?",
                         (time.time(), mail['id']))
        sent += 1
    return sent


def send_test(settings_override: dict | None = None) -> dict:
    """Send a test message right away and report the result to the UI."""
    with db.tx() as conn:
        settings = {**load(conn), **(settings_override or {})}
    if not settings['host'] or not settings['recipients']:
        return {'ok': False, 'error': '请先填写邮件服务器和收件人'}
    subject = '【观澜】测试邮件'
    body = f"这是一封测试邮件，发送于 {_bj(time.time(), '%Y-%m-%d %H:%M:%S')}（北京时间）。收到即表示邮件通知配置正确。"
    try:
        send(settings, subject, body, _wrap('测试邮件', body, ''), settings['recipients'])
    except Exception as exc:  # noqa: BLE001
        return {'ok': False, 'error': explain(exc)}
    with db.tx() as conn:
        conn.execute("INSERT INTO emails(kind,subject,text_body,html_body,recipients,created,state,attempts,sent_at) "
                     "VALUES('test',?,?,?,?,?,'sent',1,?)",
                     (subject, body, '', json.dumps(settings['recipients']), time.time(), time.time()))
    return {'ok': True}
