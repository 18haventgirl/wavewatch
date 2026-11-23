import {useEffect, useMemo, useState} from 'react';
import {Eye, MonitorCog, RotateCcw, Send, X} from 'lucide-react';
import {IconMail} from '../icons';
import {api, post, put, type Email, type EmailSettings, type Page, type Source, type SystemState} from '../api';
import {clock} from '../format';
import {useData} from '../hooks';
import {Button, Empty, ErrorNote, Field, Loading, Pager, Segmented, Toggle, useAction} from '../ui';

const PRESETS = [
  {id: 'qq', label: 'QQ 邮箱', host: 'smtp.qq.com', port: 465, security: 'ssl', hint: 'QQ 邮箱网页版：设置 › 账号与安全 › 安全设置，开启 SMTP 服务后生成“授权码”。'},
  {id: '163', label: '网易 163', host: 'smtp.163.com', port: 465, security: 'ssl', hint: '163 邮箱网页版：设置 › POP3/SMTP/IMAP，开启 SMTP 服务后生成“授权码”。'},
  {id: '126', label: '网易 126', host: 'smtp.126.com', port: 465, security: 'ssl', hint: '126 邮箱网页版：设置 › POP3/SMTP/IMAP，开启后生成“授权码”。'},
  {id: 'exmail', label: '腾讯企业邮', host: 'smtp.exmail.qq.com', port: 465, security: 'ssl', hint: '使用企业邮箱密码；如开启了安全登录，需要生成“客户端专用密码”。'},
  {id: 'aliyun', label: '阿里企业邮', host: 'smtp.qiye.aliyun.com', port: 465, security: 'ssl', hint: '使用企业邮箱密码或管理员开启的三方客户端密码。'},
  {id: 'outlook', label: 'Outlook', host: 'smtp.office365.com', port: 587, security: 'starttls', hint: '部分组织关闭了 SMTP 账号密码登录，测试失败时请联系邮箱管理员。'},
  {id: 'custom', label: '其他', host: '', port: 465, security: 'ssl', hint: '向邮箱服务商查询 SMTP 服务器地址、端口和加密方式。'},
] as const;

const kindName = {instant: '即时', digest: '汇总', alert: '提醒', test: '测试'} as const;
const stateName = {pending: '等待发送', sent: '已发送', failed: '发送失败'} as const;

function Recipients({value, onChange}: {value: string[]; onChange: (v: string[]) => void}) {
  const [draft, setDraft] = useState('');
  const add = () => {
    const parts = draft.split(/[\s,;，；]+/).map(x => x.trim()).filter(Boolean);
    if (parts.length) onChange([...new Set([...value, ...parts])]);
    setDraft('');
  };
  return <div className="chips" onClick={e => (e.currentTarget.querySelector('input') as HTMLInputElement)?.focus()}>
    {value.map(v => <span key={v} className="chip">{v}<button type="button" aria-label={'移除 ' + v} onClick={() => onChange(value.filter(x => x !== v))}><X size={12}/></button></span>)}
    <input value={draft} onChange={e => setDraft(e.target.value)} onBlur={add} placeholder={value.length ? '' : '输入邮箱地址后按回车'}
      onKeyDown={e => { if (e.key === 'Enter' || e.key === ',' || e.key === '，') { e.preventDefault(); add(); }
        if (e.key === 'Backspace' && !draft && value.length) onChange(value.slice(0, -1)); }} aria-label="添加收件人"/>
  </div>;
}

function Preview({id, onClose}: {id: number; onClose: () => void}) {
  return <div className="sheet-backdrop" onClick={onClose}>
    <div className="glass preview" onClick={e => e.stopPropagation()} role="dialog" aria-label="邮件预览">
      <div className="panel-head"><h2>邮件预览</h2><button className="icon-btn" onClick={onClose} aria-label="关闭"><X size={18}/></button></div>
      <iframe title="邮件内容" sandbox="" src={`/api/emails/${id}/preview`}/>
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
    if (!result.ok) throw new Error('测试邮件没有发出：' + result.error);
    outbox.reload();
  }

  const instantCols = sources.filter(s => s.notify === 'instant').map(s => s.name);
  const digestCols = sources.filter(s => s.notify === 'digest').map(s => s.name);

  return <div className="page notify-page">
    <header className="page-head">
      <div><h1>邮件通知</h1><p>即时邮件和每日汇总都从这台电脑发出，需要一个可以用 SMTP 发信的邮箱。</p></div>
      <label className="inline-toggle big"><Toggle checked={form.enabled} label="开启邮件通知" disabled={busy === 'enable'}
        onChange={v => run('enable', async () => { await save({enabled: v}); }, v ? '邮件通知已开启，从现在起的变化会发邮件' : '邮件通知已关闭')}/>
        {form.enabled ? '已开启' : '未开启'}</label>
    </header>

    <section className="glass panel form-panel">
      <div className="panel-head"><h2>发件邮箱</h2></div>
      <div className="presets">
        <Segmented label="邮箱服务商" value={preset.id} onChange={id => {
          const p = PRESETS.find(x => x.id === id)!;
          setForm({...form, host: p.host, port: p.port, security: p.security});
        }} options={PRESETS.map(p => ({value: p.id, label: p.label}))}/>
        <p className="field-hint">{preset.hint}</p>
      </div>
      <div className="form-grid">
        <Field label="SMTP 服务器"><input value={form.host} onChange={e => set('host', e.target.value)} placeholder="smtp.example.com"/></Field>
        <Field label="端口"><input type="number" value={form.port} onChange={e => set('port', Number(e.target.value))}/></Field>
        <Field label="加密方式"><select value={form.security} onChange={e => set('security', e.target.value as EmailSettings['security'])}>
          <option value="ssl">SSL（常用 465）</option><option value="starttls">STARTTLS（常用 587）</option><option value="none">不加密</option></select></Field>
        <Field label="邮箱账号"><input value={form.username} onChange={e => set('username', e.target.value)} placeholder="name@qq.com" autoComplete="username"/></Field>
        <Field label="授权码" hint={form.password_set ? (form.password_protected ? '已保存，并用 Windows 账户加密。留空表示不修改。' : '已保存。留空表示不修改。') : '不是邮箱登录密码，而是邮箱设置里生成的授权码。'}>
          <input type="password" value={password} onChange={e => setPassword(e.target.value)} autoComplete="new-password"
            placeholder={form.password_set ? '••••••••（已保存）' : '粘贴授权码'}/></Field>
        <Field label="发件人名称"><input value={form.sender_name} onChange={e => set('sender_name', e.target.value)}/></Field>
        <Field label="收件人" wide hint="可以填多个，例如自己和同事。"><Recipients value={form.recipients} onChange={v => set('recipients', v)}/></Field>
      </div>
      <div className="form-actions">
        <Button variant="primary" busy={busy === 'save'} disabled={!dirty} onClick={() => run('save', save, '设置已保存')}>保存</Button>
        <Button icon={<Send size={15}/>} busy={busy === 'test'} disabled={!form.host || !form.recipients.length}
          onClick={() => run('test', testMail, '测试邮件已发出，请查看收件箱')}>保存并发送测试邮件</Button>
      </div>
    </section>

    <section className="glass panel form-panel">
      <div className="panel-head"><h2>什么时候发</h2></div>
      <div className="rule-summary">
        <p><b>即时邮件：</b>{instantCols.length ? instantCols.join('、') : '没有栏目'}出现新发布、正文修订或附件变化时发送。</p>
        <p><b>每日汇总：</b>{digestCols.length ? digestCols.join('、') : '没有栏目'}的变化{form.digest_include_instant ? '，并回顾当天已即时通知的内容' : ''}。</p>
        <button className="link" onClick={() => go('sources')}>在「栏目」里调整每个栏目的方式</button>
      </div>
      <div className="form-grid">
        <Field label="即时邮件合并等待" hint="等待这段时间，把同一批变化合成一封邮件。">
          <select value={form.merge_minutes} onChange={e => set('merge_minutes', Number(e.target.value))}>
            {[0, 1, 2, 5, 10, 30].map(m => <option key={m} value={m}>{m ? `${m} 分钟` : '不等待'}</option>)}</select></Field>
        <Field label="每日汇总时间（北京时间）"><input type="time" value={form.digest_time} onChange={e => set('digest_time', e.target.value)}/></Field>
        <Field label="连续失败几次后提醒" hint="栏目检查连续失败时发提醒，恢复后再发一封。">
          <select value={form.alert_failures} onChange={e => set('alert_failures', Number(e.target.value))}>
            {[2, 3, 5, 10].map(n => <option key={n} value={n}>{n} 次</option>)}</select></Field>
        <label className="check-row"><Toggle checked={form.digest_include_instant} onChange={v => set('digest_include_instant', v)} label="汇总包含即时内容"/>汇总里回顾已即时发送的内容</label>
        <label className="check-row"><Toggle checked={form.digest_send_empty} onChange={v => set('digest_send_empty', v)} label="没有变化也发送汇总"/>当天没有变化也发送汇总</label>
      </div>
      <div className="form-actions">
        <Button variant="primary" busy={busy === 'save2'} disabled={!dirty} onClick={() => run('save2', save, '设置已保存')}>保存</Button>
        <Button variant="quiet" busy={busy === 'digest'} disabled={!settings.data?.enabled}
          onClick={() => run('digest', async () => { await post('/email/digest'); window.setTimeout(outbox.reload, 1500); }, '已生成汇总邮件，正在发送')}>立即发送一次汇总</Button>
      </div>
    </section>

    <section className="glass panel outbox">
      <div className="panel-head"><h2>发送记录</h2>
        <Segmented label="发送状态" value={state} onChange={v => { setState(v); setPage(1); }}
          options={[{value: '', label: '全部'}, {value: 'pending', label: '等待'}, {value: 'sent', label: '已发送'}, {value: 'failed', label: '失败'}]}/></div>
      {outbox.error ? <ErrorNote message={outbox.error} onRetry={outbox.reload}/> : null}
      {!outbox.data ? <Loading/> : !outbox.data.items.length ? <Empty icon={<IconMail size={26}/>} title="还没有发送记录">开启邮件通知并发送测试邮件后，记录会出现在这里。</Empty> :
        <div className="mail-list">{outbox.data.items.map(m => <div key={m.id} className={'mail-row state-' + m.state}>
          <span className={'mail-kind kind-' + m.kind}>{kindName[m.kind]}</span>
          <span className="mail-main"><b>{m.subject}</b>
            <small>{m.recipients.join('、')}{m.events ? `，包含 ${m.events} 条变化` : ''}</small>
            {m.last_error ? <small className="err">{m.last_error}{m.state === 'pending' ? `，将于 ${clock(m.next_attempt)} 重试` : ''}</small> : null}</span>
          <span className="mail-state">{stateName[m.state]}<small>{clock(m.sent_at || m.created)}</small></span>
          <span className="mail-actions">
            {m.kind !== 'test' ? <button className="icon-btn" onClick={() => setPreview(m.id)} aria-label="预览"><Eye size={16}/></button> : null}
            {m.state !== 'sent' ? <button className="icon-btn" aria-label="重新发送"
              onClick={() => run('retry', async () => { await post(`/emails/${m.id}/retry`); outbox.reload(); }, '已重新加入发送队列')}><RotateCcw size={16}/></button> : null}
          </span>
        </div>)}</div>}
      {outbox.data ? <Pager page={page} total={outbox.data.total} size={outbox.data.size} onPage={setPage}/> : null}
    </section>

    <section className="glass panel form-panel">
      <div className="panel-head"><h2><MonitorCog size={18}/>这台电脑</h2></div>
      {!system.data ? <Loading/> : <div className="system-rows">
        <label className="check-row"><Toggle checked={system.data.keep_awake} disabled={!system.data.keep_awake_supported}
          label="运行时阻止电脑自动睡眠" onChange={v => run('awake', async () => system.setData(await put<SystemState>('/system', {keep_awake: v})),
            v ? '程序运行时电脑不会自动睡眠' : '已恢复系统默认睡眠设置')}/>
          <span>运行时阻止电脑自动睡眠<small>睡眠期间无法检查。显示器仍会按设置关闭，手动睡眠和关机不受影响。</small></span></label>
        <label className="check-row"><Toggle checked={system.data.autostart} disabled={!system.data.autostart_supported}
          label="登录 Windows 后自动在后台启动" onChange={v => run('auto', async () => system.setData(await put<SystemState>('/system', {autostart: v})),
            v ? '已设置开机自启' : '已取消开机自启')}/>
          <span>登录 Windows 后自动在后台启动<small>后台运行时如果意外退出，会自动重新启动。</small></span></label>
        <p className="muted small">数据保存在 {system.data.data_dir}，本机访问地址 {system.data.url}</p>
      </div>}
    </section>
    {preview ? <Preview id={preview} onClose={() => setPreview(null)}/> : null}
  </div>;
}
