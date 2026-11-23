import {ArrowUpRight} from 'lucide-react';
import {IconBuoy, IconCalm, IconMail, IconRefresh} from '../icons';
import {api, post, type Overview as OverviewData, type Source, type UpdateEvent} from '../api';
import {ago, clock, countdown, interval} from '../format';
import {useData, useNow} from '../hooks';
import {Button, ColumnTag, Dot, Empty, ErrorNote, KindBadge, Loading, useAction} from '../ui';

export function sourceTone(s: Source): 'ok' | 'warn' | 'error' | 'idle' | 'live' {
  if (!s.enabled) return 'idle';
  if (s.state === 'checking') return 'live';
  if (s.state === 'error') return s.fail_count >= 3 ? 'error' : 'warn';
  return s.last_success ? 'ok' : 'idle';
}

function Ring({s, now}: {s: Source; now: number}) {
  const span = s.list_minutes * 60;
  const left = Math.max(0, s.next_check - now);
  const fraction = s.enabled ? Math.min(1, Math.max(0, 1 - left / span)) : 0;
  const r = 15, c = 2 * Math.PI * r;
  return <svg className={'ring' + (s.state === 'checking' ? ' ring-live' : '')} viewBox="0 0 36 36" aria-hidden="true">
    <circle cx="18" cy="18" r={r} className="ring-track"/>
    <circle cx="18" cy="18" r={r} className="ring-fill" strokeDasharray={c} strokeDashoffset={c * (1 - fraction)}/>
  </svg>;
}

const nextLabel = (at: number, now: number) => at <= now + 1 ? '即将检查' : `下次 ${countdown(at, now)}`;

const HISTORY = 96;   // about 8 hours at the default 5-minute interval

function Lane({s, now, onOpen}: {s: Source; now: number; onOpen: () => void}) {
  const ticks = [...Array(Math.max(0, HISTORY - s.history.length)).fill(null), ...s.history.slice(-HISTORY)];
  const tone = sourceTone(s);
  const status = !s.enabled ? '已暂停' : s.state === 'checking' ? '正在检查…'
    : s.state === 'error' ? `检查失败 ${s.fail_count} 次` : s.last_success ? `${ago(s.last_success, now)}检查正常` : '等待首次检查';
  return <button className={'lane' + (s.enabled ? '' : ' lane-off')} onClick={onOpen}>
    <span className="lane-name">
      <ColumnTag column={{id: s.id, name: s.name, role: s.role, group: s.grp}}/>
      <small>{s.articles} 篇{s.unread ? `，${s.unread} 篇未读` : ''}</small>
    </span>
    <span className="lane-pulse" aria-label="最近的检查记录">
      {ticks.map((t, i) => <i key={i} className={!t ? 'tick tick-empty' : `tick tick-${t.state}${t.added ? ' tick-new' : ''}${t.mode === 'full' ? ' tick-full' : ''}`}
        title={t ? `${clock(t.started)} ${t.state === 'ok' ? (t.added ? `发现 ${t.added} 篇新文章` : '无新内容') : t.state === 'error' ? '失败' : t.state}` : undefined}/>)}
    </span>
    <span className="lane-next">
      <span className="lane-text"><b className={'tone-' + tone}><Dot tone={tone}/>{status}</b>
        <small>{s.enabled ? (s.state === 'checking' ? '检查中' : nextLabel(s.next_check, now)) + `，${interval(s.list_minutes)}` : '不检查'}</small></span>
      <Ring s={s} now={now}/>
    </span>
  </button>;
}

export function EventLine({e, onOpen}: {e: UpdateEvent; onOpen: (id: string) => void}) {
  return <button className={'event-line' + (e.read_at ? '' : ' unread')} onClick={() => onOpen(e.article_id)}>
    <KindBadge kind={e.kind}/>
    <span className="event-title">{e.title}
      {e.attachment_title ? <small>附件：{e.attachment_title}</small> : e.kind === 'changed' && e.summary ? <small>{e.summary}</small> : null}
    </span>
    <span className="event-cols">{e.columns.slice(0, 1).map(c => <ColumnTag key={c.id} column={c}/>)}</span>
    <time>{clock(e.created)}</time>
  </button>;
}

export default function Overview({onOpen, go}: {onOpen: (id: string) => void; go: (page: string) => void}) {
  const {data, error, reload} = useData(s => api<OverviewData>('/overview', {signal: s}), [], 5000);
  const now = useNow();
  const {busy, run} = useAction();

  if (!data) return error ? <ErrorNote message={error} onRetry={reload}/> : <Loading/>;
  const active = data.sources.filter(s => s.enabled);
  const failing = active.filter(s => s.state === 'error');
  const checking = active.some(s => s.state === 'checking');
  const headline = !data.healthy ? '后台任务没有响应' : failing.length ? `${failing.length} 个栏目检查失败` : active.length ? '实时监测中' : '全部栏目已暂停';
  const attention: {key: string; text: string; action?: () => void; label?: string}[] = [];
  failing.forEach(s => attention.push({key: s.id, text: `${s.name}：${s.error}`, action: () => go('sources'), label: '查看栏目'}));
  if (!data.email.ready) attention.push({key: 'mail', text: '邮件通知还没有开启，发现更新时只会显示在这里。', action: () => go('notify'), label: '设置邮件'});
  if (data.email.failed) attention.push({key: 'mailfail', text: `最近 24 小时有 ${data.email.failed} 封邮件发送失败：${data.email.last_error}`, action: () => go('notify'), label: '查看邮件'});
  if (data.stats.check_errors) attention.push({key: 'art', text: `${data.stats.check_errors} 篇文章最近一次复查失败，会自动重试。`, action: () => go('runs'), label: '查看记录'});
  if (data.import?.error) attention.push({key: 'imp', text: `旧版数据导入失败：${data.import.error}。已从官网重新建立数据。`});
  Object.entries(data.workers).forEach(([name, w]) => { if (w.error) attention.push({key: 'w' + name, text: `后台任务出错：${w.error}`, action: () => go('runs'), label: '查看记录'}); });

  const soonest = active.filter(s => s.state !== 'checking').map(s => s.next_check).sort((a, b) => a - b)[0];
  const tone = !data.healthy || failing.length ? 'warn' : active.length ? 'live' : 'idle';
  return <div className="page overview">
    <header className={'glass hero hero-' + tone}>
      <div className="hero-main">
        <span className="hero-kicker"><Dot tone={tone === 'warn' ? 'warn' : tone === 'live' ? 'live' : 'idle'}/>中国出口管制信息网，{active.length} 个栏目</span>
        <h1>{headline}</h1>
        <p>{checking ? '正在检查官网…' : soonest ? (soonest <= now + 1 ? '马上开始下一次检查' : `下一次检查 ${countdown(soonest, now)}`) : '没有正在监测的栏目'}
          {data.stats.never_checked ? `，${data.stats.never_checked} 篇正文待首次保存` : ''}</p>
        <div className="hero-actions">
          <Button variant="primary" icon={<IconRefresh size={18} className={checking ? 'spin' : ''}/>} busy={busy === 'all'}
            onClick={() => run('all', async () => { await post('/check'); window.setTimeout(reload, 800); }, '已开始检查全部栏目')}>立即检查</Button>
          <button className="hero-mail" onClick={() => go('notify')}>
            <IconMail size={20}/><span>{data.email.ready ? `邮件已开启，发给 ${data.email.recipients} 人` : '邮件未开启'}
              <small>{data.email.ready ? (data.email.last_sent ? `上次发送 ${clock(data.email.last_sent)}` : `每日 ${data.email.digest_time} 汇总`) : '点此设置'}</small></span>
          </button>
        </div>
      </div>
      <div className="hero-figures">
        <button onClick={() => go('updates')}><span className="fig-label">今日新发布</span><span className="fig-value">{data.stats.today_new}</span></button>
        <button onClick={() => go('updates')}><span className="fig-label">今日修订与附件</span><span className="fig-value">{data.stats.today_changed}</span></button>
        <button onClick={() => go('updates')}><span className="fig-label">未读</span><span className={'fig-value' + (data.stats.unread ? ' accent' : '')}>{data.stats.unread}</span></button>
        <button onClick={() => go('library')}><span className="fig-label">已收录文章</span><span className="fig-value">{data.stats.articles}</span></button>
      </div>
      <svg className="hero-wave" viewBox="0 0 1200 80" preserveAspectRatio="none" aria-hidden="true">
        <path className="w1" d="M0 46 C 150 26 300 66 450 46 S 750 26 900 46 S 1200 66 1350 46 V80 H0Z"/>
        <path className="w2" d="M0 56 C 160 40 320 72 480 56 S 800 40 960 56 S 1280 72 1440 56 V80 H0Z"/>
      </svg>
    </header>

    <section className="glass lanes" aria-label="栏目实时状态">
      <div className="lanes-head"><h2>栏目实时状态</h2>
        <div className="lanes-legend"><span><i className="tick tick-ok"/>正常</span><span><i className="tick tick-ok tick-new"/>发现新文章</span>
          <span><i className="tick tick-error"/>失败</span><span><i className="tick tick-ok tick-full"/>完整核对</span><span className="muted">最近约 8 小时 → 现在</span></div></div>
      {data.sources.map(s => <Lane key={s.id} s={s} now={now} onOpen={() => go('sources')}/>)}
    </section>

    <div className="overview-grid">
      <section className="glass panel">
        <div className="panel-head"><h2>最新动态</h2><button className="link" onClick={() => go('updates')}>全部动态<ArrowUpRight size={14}/></button></div>
        {data.recent.length ? <div className="event-list">{data.recent.map(e => <EventLine key={e.id} e={e} onOpen={onOpen}/>)}</div>
          : <Empty icon={<IconCalm size={26}/>} title="还没有新动态">首次检查只建立基线，之后官网的新发布和修订会出现在这里。</Empty>}
      </section>
      <section className={'glass panel attention' + (attention.length ? '' : ' calm')}>
        <div className="panel-head"><h2>需要注意</h2></div>
        {attention.length ? <ul>{attention.map(a => <li key={a.key}><IconBuoy size={20}/><span>{a.text}</span>
          {a.action ? <button className="link" onClick={a.action}>{a.label}</button> : null}</li>)}</ul>
          : <p className="calm-note">一切正常。官网有变化时会{data.email.ready ? '发邮件并' : ''}显示在左侧。</p>}
        <dl className="mini-stats">
          <div><dt>待复查正文</dt><dd>{data.stats.due}</dd></div>
          <div><dt>附件文件</dt><dd>{data.stats.attachments}</dd></div>
          <div><dt>近 7 天变化</dt><dd>{data.stats.week_events}</dd></div>
          <div><dt>服务已运行</dt><dd>{ago(data.started, now).replace('前', '')}</dd></div>
        </dl>
      </section>
    </div>
  </div>;
}
