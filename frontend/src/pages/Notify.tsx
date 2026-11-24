import {useEffect, useMemo, useState} from 'react';
import {Eye, MonitorCog, RotateCcw, Send, X} from 'lucide-react';
import {IconMail} from '../icons';
import {api, post, put, type Email, type EmailSettings, type Page, type Source, type SystemState} from '../api';
import {clock, list} from '../format';
import {useData} from '../hooks';
import {columnName, t, tx} from '../i18n';
import {Button, Empty, ErrorNote, Field, Loading, Pager, Segmented, Toggle, useAction} from '../ui';

const presets = () => [
  {id: 'qq', label: t('QQ 邮箱', 'QQ Mail'), host: 'smtp.qq.com', port: 465, security: 'ssl',
    hint: t('QQ 邮箱网页版：设置 › 账号与安全 › 安全设置，开启 SMTP 服务后生成“授权码”。', 'QQ Mail on the web: Settings › Account & security › Security, turn on SMTP, then generate an authorization code.')},
  {id: '163', label: t('网易 163', 'NetEase 163'), host: 'smtp.163.com', port: 465, security: 'ssl',
    hint: t('163 邮箱网页版：设置 › POP3/SMTP/IMAP，开启 SMTP 服务后生成“授权码”。', '163 Mail on the web: Settings › POP3/SMTP/IMAP, turn on SMTP, then generate an authorization code.')},
  {id: '126', label: t('网易 126', 'NetEase 126'), host: 'smtp.126.com', port: 465, security: 'ssl',
    hint: t('126 邮箱网页版：设置 › POP3/SMTP/IMAP，开启后生成“授权码”。', '126 Mail on the web: Settings › POP3/SMTP/IMAP, turn it on, then generate an authorization code.')},
  {id: 'exmail', label: t('腾讯企业邮', 'Tencent Exmail'), host: 'smtp.exmail.qq.com', port: 465, security: 'ssl',
    hint: t('使用企业邮箱密码；如开启了安全登录，需要生成“客户端专用密码”。', 'Use the mailbox password; with secure login on, generate a client-specific password.')},
  {id: 'aliyun', label: t('阿里企业邮', 'Alibaba Mail'), host: 'smtp.qiye.aliyun.com', port: 465, security: 'ssl',
    hint: t('使用企业邮箱密码或管理员开启的三方客户端密码。', 'Use the mailbox password, or a third-party client password enabled by your admin.')},
  {id: 'outlook', label: 'Outlook', host: 'smtp.office365.com', port: 587, security: 'starttls',
    hint: t('部分组织关闭了 SMTP 账号密码登录，测试失败时请联系邮箱管理员。', 'Some organisations disable SMTP password login; if the test fails, ask your mail admin.')},
  {id: 'custom', label: t('其他', 'Other'), host: '', port: 465, security: 'ssl',
    hint: t('向邮箱服务商查询 SMTP 服务器地址、端口和加密方式。', 'Ask your mail provider for the SMTP host, port and encryption.')},
] as const;

const kindName = (k: Email['kind']) => ({instant: t('即时', 'Instant'), digest: t('汇总', 'Digest'), alert: t('提醒', 'Alert'), test: t('测试', 'Test')})[k];
const stateName = (s: Email['state']) => ({pending: t('等待发送', 'Waiting'), sent: t('已发送', 'Sent'), failed: t('发送失败', 'Failed')})[s];

function Recipients({value, onChange}: {value: string[]; onChange: (v: string[]) => void}) {
  const [draft, setDraft] = useState('');
  const add = () => {
    const parts = draft.split(/[\s,;，；]+/).map(x => x.trim()).filter(Boolean);
    if (parts.length) onChange([...new Set([...value, ...parts])]);
    setDraft('');
  };
  return <div className="chips" onClick={e => (e.currentTarget.querySelector('input') as HTMLInputElement)?.focus()}>
    {value.map(v => <span key={v} className="chip">{v}<button type="button" aria-label={t('移除 ', 'Remove ') + v} onClick={() => onChange(value.filter(x => x !== v))}><X size={12}/></button></span>)}
    <input value={draft} onChange={e => setDraft(e.target.value)} onBlur={add} placeholder={value.length ? '' : t('输入邮箱地址后按回车', 'Type an address and press Enter')}
      onKeyDown={e => { if (e.key === 'Enter' || e.key === ',' || e.key === '，') { e.preventDefault(); add(); }
        if (e.key === 'Backspace' && !draft && value.length) onChange(value.slice(0, -1)); }} aria-label={t('添加收件人', 'Add recipient')}/>
  </div>;
}

function Preview({id, onClose}: {id: number; onClose: () => void}) {
  return <div className="sheet-backdrop" onClick={onClose}>
    <div className="glass preview" onClick={e => e.stopPropagation()} role="dialog" aria-label={t('邮件预览', 'E-mail preview')}>
      <div className="panel-head"><h2>{t('邮件预览', 'E-mail preview')}</h2><button className="icon-btn" onClick={onClose} aria-label={t('关闭', 'Close')}><X size={18}/></button></div>
      <iframe title={t('邮件内容', 'E-mail content')} sandbox="" src={`/api/emails/${id}/preview`}/>
    </div>
  </div>;
}

export default function NotifyPage({sources, go}: {sources: Source[]; go: (p: string) => void}) {
  const settings = useData(s => api<EmailSettings>('/email', {signal: s}), []);
  const system = useData(s => api<SystemState>('/system', {signal: s}), []);
  const [form, setForm] = useState<EmailSettings | null>(null);
  const [password, setPassword] = useState('');
  const [page, setPage] = useState(1);
  const [state, setState] = useState<'' | 'pending' | 'sent' | 'failed'>('');
  const [preview, setPreview] = useState<number | null>(null);
  const outbox = useData(s => api<Page<Email>>(`/emails?page=${page}&state=${state}`, {signal: s}), [page, state], 10000);
  const {busy, run} = useAction();
  const PRESETS = presets();

  useEffect(() => { if (settings.data && !form) setForm(settings.data); }, [settings.data, form]);
  const preset = useMemo(() => PRESETS.find(p => form && p.host === form.host) || PRESETS[PRESETS.length - 1], [form]);
  const dirty = !!form && !!settings.data && (JSON.stringify(form) !== JSON.stringify(settings.data) || !!password);

  if (!form) return settings.error ? <ErrorNote message={settings.error} onRetry={settings.reload}/> : <Loading/>;
  const set = <K extends keyof EmailSettings>(k: K, v: EmailSettings[K]) => setForm({...form, [k]: v});

  const body = () => ({enabled: form.enabled, host: form.host.trim(), port: form.port, security: form.security,
    username: form.username.trim(), sender: form.sender.trim(), sender_name: form.sender_name, recipients: form.recipients,
    merge_minutes: form.merge_minutes, digest_time: form.digest_time, digest_include_instant: form.digest_include_instant,
    digest_send_empty: form.digest_send_empty, alert_failures: form.alert_failures, ...(password ? {password} : {})});

  async function save(extra: Partial<EmailSettings> = {}) {
    const saved = await put<EmailSettings>('/email', {...body(), ...extra});
    setForm(saved); settings.setData(saved); setPassword('');
    return saved;
  }

  async function testMail() {
    await save();
    const result = await post<{ok: boolean; error?: string}>('/email/test');
    if (!result.ok) throw new Error(t('测试邮件没有发出：', 'The test e-mail was not sent: ') + tx(result.error));
    outbox.reload();
  }

  const instantCols = sources.filter(s => s.notify === 'instant').map(s => columnName(s.id, s.name));
  const digestCols = sources.filter(s => s.notify === 'digest').map(s => columnName(s.id, s.name));
  const none = t('没有栏目', 'No columns');
  const saved = t('设置已保存', 'Settings saved');

  return <div className="page notify-page">
    <header className="page-head">
      <div><h1>{t('邮件通知', 'E-mail')}</h1><p>{t('即时邮件和每日汇总都从这台电脑发出，需要一个可以用 SMTP 发信的邮箱。', 'Instant e-mails and the daily digest are sent from this computer through a mailbox that allows SMTP.')}</p></div>
      <label className="inline-toggle big"><Toggle checked={form.enabled} label={t('开启邮件通知', 'Turn on e-mail')} disabled={busy === 'enable'}
        onChange={v => run('enable', async () => { await save({enabled: v}); }, v ? t('邮件通知已开启，从现在起的变化会发邮件', 'E-mail is on; changes from now on will be e-mailed') : t('邮件通知已关闭', 'E-mail is off'))}/>
        {form.enabled ? t('已开启', 'On') : t('未开启', 'Off')}</label>
    </header>

    <section className="glass panel form-panel">
      <div className="panel-head"><h2>{t('发件邮箱', 'Sending mailbox')}</h2></div>
      <div className="presets">
        <Segmented label={t('邮箱服务商', 'Mail provider')} value={preset.id} onChange={id => {
          const p = PRESETS.find(x => x.id === id)!;
          setForm({...form, host: p.host, port: p.port, security: p.security});
        }} options={PRESETS.map(p => ({value: p.id, label: p.label}))}/>
        <p className="field-hint">{preset.hint}</p>
      </div>
      <div className="form-grid">
        <Field label={t('SMTP 服务器', 'SMTP host')}><input value={form.host} onChange={e => set('host', e.target.value)} placeholder="smtp.example.com"/></Field>
        <Field label={t('端口', 'Port')}><input type="number" value={form.port} onChange={e => set('port', Number(e.target.value))}/></Field>
        <Field label={t('加密方式', 'Encryption')}><select value={form.security} onChange={e => set('security', e.target.value as EmailSettings['security'])}>
          <option value="ssl">{t('SSL（常用 465）', 'SSL (usually 465)')}</option><option value="starttls">{t('STARTTLS（常用 587）', 'STARTTLS (usually 587)')}</option>
          <option value="none">{t('不加密', 'None')}</option></select></Field>
        <Field label={t('邮箱账号', 'Account')}><input value={form.username} onChange={e => set('username', e.target.value)} placeholder="name@qq.com" autoComplete="username"/></Field>
        <Field label={t('授权码', 'App password')} hint={form.password_set
          ? (form.password_protected ? t('已保存，并用 Windows 账户加密。留空表示不修改。', 'Saved and encrypted with your Windows account. Leave blank to keep it.') : t('已保存。留空表示不修改。', 'Saved. Leave blank to keep it.'))
          : t('不是邮箱登录密码，而是邮箱设置里生成的授权码。', 'Not your login password: the authorization code generated in your mailbox settings.')}>
          <input type="password" value={password} onChange={e => setPassword(e.target.value)} autoComplete="new-password"
            placeholder={form.password_set ? t('••••••••（已保存）', '•••••••• (saved)') : t('粘贴授权码', 'Paste the code')}/></Field>
        <Field label={t('发件人名称', 'Sender name')}><input value={form.sender_name} onChange={e => set('sender_name', e.target.value)}/></Field>
        <Field label={t('收件人', 'Recipients')} wide hint={t('可以填多个，例如自己和同事。', 'Add as many as you like, for example yourself and colleagues.')}>
          <Recipients value={form.recipients} onChange={v => set('recipients', v)}/></Field>
      </div>
      <div className="form-actions">
        <Button variant="primary" busy={busy === 'save'} disabled={!dirty} onClick={() => run('save', save, saved)}>{t('保存', 'Save')}</Button>
        <Button icon={<Send size={15}/>} busy={busy === 'test'} disabled={!form.host || !form.recipients.length}
          onClick={() => run('test', testMail, t('测试邮件已发出，请查看收件箱', 'Test e-mail sent; check the inbox'))}>{t('保存并发送测试邮件', 'Save and send a test')}</Button>
      </div>
    </section>

    <section className="glass panel form-panel">
      <div className="panel-head"><h2>{t('什么时候发', 'When to send')}</h2></div>
      <div className="rule-summary">
        <p><b>{t('即时邮件：', 'Instant: ')}</b>{t(`${instantCols.length ? list(instantCols) : none}出现新发布、正文修订或附件变化时发送。`,
          `sent when ${instantCols.length ? list(instantCols) : 'no column'} has a new article, a revision or a file change.`)}</p>
        <p><b>{t('每日汇总：', 'Daily digest: ')}</b>{t(`${digestCols.length ? list(digestCols) : none}的变化${form.digest_include_instant ? '，并回顾当天已即时通知的内容' : ''}。`,
          `changes in ${digestCols.length ? list(digestCols) : 'no column'}${form.digest_include_instant ? ', plus a recap of the day\'s instant e-mails' : ''}.`)}</p>
        <button className="link" onClick={() => go('sources')}>{t('在「栏目」里调整每个栏目的方式', 'Change this per column under Columns')}</button>
      </div>
      <div className="form-grid">
        <Field label={t('即时邮件合并等待', 'Wait before sending')} hint={t('等待这段时间，把同一批变化合成一封邮件。', 'Changes found within this time go into one e-mail.')}>
          <select value={form.merge_minutes} onChange={e => set('merge_minutes', Number(e.target.value))}>
            {[0, 1, 2, 5, 10, 30].map(m => <option key={m} value={m}>{m ? t(`${m} 分钟`, `${m} min`) : t('不等待', 'No wait')}</option>)}</select></Field>
        <Field label={t('每日汇总时间（北京时间）', 'Digest time (Beijing)')}><input type="time" value={form.digest_time} onChange={e => set('digest_time', e.target.value)}/></Field>
        <Field label={t('连续失败几次后提醒', 'Alert after failures')} hint={t('栏目检查连续失败时发提醒，恢复后再发一封。', 'E-mail when a column keeps failing, and again when it recovers.')}>
          <select value={form.alert_failures} onChange={e => set('alert_failures', Number(e.target.value))}>
            {[2, 3, 5, 10].map(n => <option key={n} value={n}>{t(`${n} 次`, `${n} in a row`)}</option>)}</select></Field>
        <label className="check-row"><Toggle checked={form.digest_include_instant} onChange={v => set('digest_include_instant', v)} label={t('汇总包含即时内容', 'Recap instant items')}/>
          {t('汇总里回顾已即时发送的内容', 'Recap instant e-mails in the digest')}</label>
        <label className="check-row"><Toggle checked={form.digest_send_empty} onChange={v => set('digest_send_empty', v)} label={t('没有变化也发送汇总', 'Send empty digests')}/>
          {t('当天没有变化也发送汇总', 'Send the digest even when nothing changed')}</label>
      </div>
      <div className="form-actions">
        <Button variant="primary" busy={busy === 'save2'} disabled={!dirty} onClick={() => run('save2', save, saved)}>{t('保存', 'Save')}</Button>
        <Button variant="quiet" busy={busy === 'digest'} disabled={!settings.data?.enabled}
          onClick={() => run('digest', async () => { await post('/email/digest'); window.setTimeout(outbox.reload, 1500); }, t('已生成汇总邮件，正在发送', 'Digest created; sending'))}>
          {t('立即发送一次汇总', 'Send a digest now')}</Button>
      </div>
    </section>

    <section className="glass panel outbox">
      <div className="panel-head"><h2>{t('发送记录', 'Sent e-mails')}</h2>
        <Segmented label={t('发送状态', 'Status')} value={state} onChange={v => { setState(v); setPage(1); }}
          options={[{value: '', label: t('全部', 'All')}, {value: 'pending', label: t('等待', 'Waiting')}, {value: 'sent', label: t('已发送', 'Sent')}, {value: 'failed', label: t('失败', 'Failed')}]}/></div>
      {outbox.error ? <ErrorNote message={outbox.error} onRetry={outbox.reload}/> : null}
      {!outbox.data ? <Loading/> : !outbox.data.items.length ? <Empty icon={<IconMail size={26}/>} title={t('还没有发送记录', 'Nothing sent yet')}>
        {t('开启邮件通知并发送测试邮件后，记录会出现在这里。', 'Turn on e-mail and send a test; it will appear here.')}</Empty> :
        <div className="mail-list">{outbox.data.items.map(m => <div key={m.id} className={'mail-row state-' + m.state}>
          <span className={'mail-kind kind-' + m.kind}>{kindName(m.kind)}</span>
          <span className="mail-main"><b>{m.subject}</b>
            <small>{list(m.recipients)}{m.events ? t(`，包含 ${m.events} 条变化`, `, ${m.events} change(s)`) : ''}</small>
            {m.last_error ? <small className="err">{tx(m.last_error)}{m.state === 'pending' ? t(`，将于 ${clock(m.next_attempt)} 重试`, `; retrying ${clock(m.next_attempt)}`) : ''}</small> : null}</span>
          <span className="mail-state">{stateName(m.state)}<small>{clock(m.sent_at || m.created)}</small></span>
          <span className="mail-actions">
            {m.kind !== 'test' ? <button className="icon-btn" onClick={() => setPreview(m.id)} aria-label={t('预览', 'Preview')}><Eye size={16}/></button> : null}
            {m.state !== 'sent' ? <button className="icon-btn" aria-label={t('重新发送', 'Send again')}
              onClick={() => run('retry', async () => { await post(`/emails/${m.id}/retry`); outbox.reload(); }, t('已重新加入发送队列', 'Queued again'))}><RotateCcw size={16}/></button> : null}
          </span>
        </div>)}</div>}
      {outbox.data ? <Pager page={page} total={outbox.data.total} size={outbox.data.size} onPage={setPage}/> : null}
    </section>

    <section className="glass panel form-panel">
      <div className="panel-head"><h2><MonitorCog size={18}/>{t('这台电脑', 'This computer')}</h2></div>
      {!system.data ? <Loading/> : <div className="system-rows">
        <label className="check-row"><Toggle checked={system.data.keep_awake} disabled={!system.data.keep_awake_supported}
          label={t('运行时阻止电脑自动睡眠', 'Keep the computer awake')} onChange={v => run('awake', async () => system.setData(await put<SystemState>('/system', {keep_awake: v})),
            v ? t('程序运行时电脑不会自动睡眠', 'The computer will not sleep on its own while this runs') : t('已恢复系统默认睡眠设置', 'System sleep settings restored'))}/>
          <span>{t('运行时阻止电脑自动睡眠', 'Keep the computer awake while running')}
            <small>{t('睡眠期间无法检查。显示器仍会按设置关闭，手动睡眠和关机不受影响。', 'No checks can run during sleep. The display still turns off, and manual sleep and shutdown still work.')}</small></span></label>
        <label className="check-row"><Toggle checked={system.data.autostart} disabled={!system.data.autostart_supported}
          label={t('登录 Windows 后自动在后台启动', 'Start in the background at Windows sign-in')} onChange={v => run('auto', async () => system.setData(await put<SystemState>('/system', {autostart: v})),
            v ? t('已设置开机自启', 'Will start at sign-in') : t('已取消开机自启', 'Will no longer start at sign-in'))}/>
          <span>{t('登录 Windows 后自动在后台启动', 'Start in the background at Windows sign-in')}
            <small>{t('后台运行时如果意外退出，会自动重新启动。', 'If it stops unexpectedly in the background, it restarts automatically.')}</small></span></label>
        <p className="muted small">{t(`数据保存在 ${system.data.data_dir}，本机访问地址 ${system.data.url}`, `Data is stored in ${system.data.data_dir}; local address ${system.data.url}`)}</p>
      </div>}
    </section>
    {preview ? <Preview id={preview} onClose={() => setPreview(null)}/> : null}
  </div>;
}
