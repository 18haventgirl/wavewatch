import {ArrowUpRight} from 'lucide-react';
import {IconBuoy, IconCalm, IconMail, IconRefresh} from '../icons';
import {api, post, type Overview as OverviewData, type Source, type UpdateEvent} from '../api';
import {ago, clock, countdown, duration, interval} from '../format';
import {useData, useNow} from '../hooks';
import {columnName, t, tx} from '../i18n';
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

const nextLabel = (at: number, now: number) => at <= now + 1 ? t('即将检查', 'due now') : t(`下次 ${countdown(at, now)}`, `next ${countdown(at, now)}`);

const HISTORY = 96;   // about 8 hours at the default 5-minute interval

function tickTitle(tk: Source['history'][number]) {
  const what = tk.state === 'ok'
    ? (tk.added ? t(`发现 ${tk.added} 篇新文章`, `${tk.added} new article(s)`) : t('无新内容', 'nothing new'))
    : tk.state === 'error' ? t('失败', 'failed') : tk.state === 'running' ? t('进行中', 'running') : t('中断', 'interrupted');
  return `${clock(tk.started)} ${what}`;
}

function Lane({s, now, onOpen}: {s: Source; now: number; onOpen: () => void}) {
  const ticks = [...Array(Math.max(0, HISTORY - s.history.length)).fill(null), ...s.history.slice(-HISTORY)];
  const tone = sourceTone(s);
  const status = !s.enabled ? t('已暂停', 'Paused') : s.state === 'checking' ? t('正在检查…', 'Checking…')
    : s.state === 'error' ? t(`检查失败 ${s.fail_count} 次`, `Failed ${s.fail_count}×`)
    : s.last_success ? t(`${ago(s.last_success, now)}检查正常`, `OK, checked ${ago(s.last_success, now)}`) : t('等待首次检查', 'Waiting for first check');
  const counts = t(`${s.articles} 篇`, `${s.articles} articles`) + (s.unread ? t(`，${s.unread} 篇未读`, `, ${s.unread} unread`) : '');
  return <button className={'lane' + (s.enabled ? '' : ' lane-off')} onClick={onOpen}>
    <span className="lane-name">
      <ColumnTag column={{id: s.id, name: s.name, role: s.role, group: s.grp}}/>
      <small>{counts}</small>
    </span>
    <span className="lane-pulse" aria-label={t('最近的检查记录', 'Recent checks')}>
      {ticks.map((tk, i) => <i key={i} className={!tk ? 'tick tick-empty' : `tick tick-${tk.state}${tk.added ? ' tick-new' : ''}${tk.mode === 'full' ? ' tick-full' : ''}`}
        title={tk ? tickTitle(tk) : undefined}/>)}
    </span>
    <span className="lane-next">
      <span className="lane-text"><b className={'tone-' + tone}><Dot tone={tone}/>{status}</b>
        <small>{s.enabled ? (s.state === 'checking' ? t('检查中', 'checking') : nextLabel(s.next_check, now)) + t('，', ', ') + interval(s.list_minutes) : t('不检查', 'not checked')}</small></span>
      <Ring s={s} now={now}/>
    </span>
  </button>;
}

export function EventLine({e, onOpen}: {e: UpdateEvent; onOpen: (id: string) => void}) {
  return <button className={'event-line' + (e.read_at ? '' : ' unread')} onClick={() => onOpen(e.article_id)}>
    <KindBadge kind={e.kind}/>
    <span className="event-title">{e.title}
      {e.attachment_title ? <small>{t('附件：', 'File: ')}{e.attachment_title}</small> : e.kind === 'changed' && e.summary ? <small>{tx(e.summary)}</small> : null}
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
  const headline = !data.healthy ? t('后台任务没有响应', 'Background tasks not responding')
    : failing.length ? t(`${failing.length} 个栏目检查失败`, `${failing.length} column(s) failing`)
    : active.length ? t('实时监测中', 'Monitoring live') : t('全部栏目已暂停', 'All columns paused');
  const attention: {key: string; text: string; action?: () => void; label?: string}[] = [];
  const seeLog = t('查看记录', 'Open log');
  failing.forEach(s => attention.push({key: s.id, text: `${columnName(s.id, s.name)}${t('：', ': ')}${tx(s.error)}`, action: () => go('sources'), label: t('查看栏目', 'Open column')}));
  if (!data.email.ready) attention.push({key: 'mail', text: t('邮件通知还没有开启，发现更新时只会显示在这里。', 'E-mail is off; changes only show up here.'), action: () => go('notify'), label: t('设置邮件', 'Set up e-mail')});
  if (data.email.failed) attention.push({key: 'mailfail', text: t(`最近 24 小时有 ${data.email.failed} 封邮件发送失败：`, `${data.email.failed} e-mail(s) failed in the last 24 h: `) + tx(data.email.last_error), action: () => go('notify'), label: t('查看邮件', 'Open e-mail')});
  if (data.stats.check_errors) attention.push({key: 'art', text: t(`${data.stats.check_errors} 篇文章最近一次复查失败，会自动重试。`, `${data.stats.check_errors} article(s) failed their last re-check; will retry.`), action: () => go('runs'), label: seeLog});
  if (data.import?.error) attention.push({key: 'imp', text: t(`旧版数据导入失败：${data.import.error}。已从官网重新建立数据。`, `Import from the previous version failed: ${data.import.error}. Data was rebuilt from the site.`)});
  Object.entries(data.workers).forEach(([name, w]) => { if (w.error) attention.push({key: 'w' + name, text: t('后台任务出错：', 'Background task error: ') + w.error, action: () => go('runs'), label: seeLog}); });

  const soonest = active.filter(s => s.state !== 'checking').map(s => s.next_check).sort((a, b) => a - b)[0];
  const tone = !data.healthy || failing.length ? 'warn' : active.length ? 'live' : 'idle';
  const next = checking ? t('正在检查官网…', 'Checking the site…')
    : soonest ? (soonest <= now + 1 ? t('马上开始下一次检查', 'Next check starting') : t(`下一次检查 ${countdown(soonest, now)}`, `Next check ${countdown(soonest, now)}`))
    : t('没有正在监测的栏目', 'No column is being monitored');
  const pending = data.stats.never_checked ? t(`，${data.stats.never_checked} 篇正文待首次保存`, `; ${data.stats.never_checked} bodies waiting to be saved`) : '';
  const mailLine = data.email.ready ? t(`邮件已开启，发给 ${data.email.recipients} 人`, `E-mail on, to ${data.email.recipients}`) : t('邮件未开启', 'E-mail off');
  const mailSub = data.email.ready
    ? (data.email.last_sent ? t(`上次发送 ${clock(data.email.last_sent)}`, `Last sent ${clock(data.email.last_sent)}`) : t(`每日 ${data.email.digest_time} 汇总`, `Daily digest at ${data.email.digest_time}`))
    : t('点此设置', 'Set up');

  return <div className="page overview">
    <header className={'glass hero hero-' + tone}>
      <div className="hero-main">
        <span className="hero-kicker"><Dot tone={tone === 'warn' ? 'warn' : tone === 'live' ? 'live' : 'idle'}/>
          {t(`中国出口管制信息网，${active.length} 个栏目`, `China Export Control Information Network, ${active.length} columns`)}</span>
        <h1>{headline}</h1>
        <p>{next}{pending}</p>
        <div className="hero-actions">
          <Button variant="primary" icon={<IconRefresh size={18} className={checking ? 'spin' : ''}/>} busy={busy === 'all'}
            onClick={() => run('all', async () => { await post('/check'); window.setTimeout(reload, 800); }, t('已开始检查全部栏目', 'Checking all columns'))}>{t('立即检查', 'Check now')}</Button>
          <button className="hero-mail" onClick={() => go('notify')}>
            <IconMail size={20}/><span>{mailLine}<small>{mailSub}</small></span>
          </button>
        </div>
      </div>
      <div className="hero-figures">
        <button onClick={() => go('updates')}><span className="fig-label">{t('今日新发布', 'New today')}</span><span className="fig-value">{data.stats.today_new}</span></button>
        <button onClick={() => go('updates')}><span className="fig-label">{t('今日修订与附件', 'Revised today')}</span><span className="fig-value">{data.stats.today_changed}</span></button>
        <button onClick={() => go('updates')}><span className="fig-label">{t('未读', 'Unread')}</span><span className={'fig-value' + (data.stats.unread ? ' accent' : '')}>{data.stats.unread}</span></button>
        <button onClick={() => go('library')}><span className="fig-label">{t('已收录文章', 'Articles')}</span><span className="fig-value">{data.stats.articles}</span></button>
      </div>
      <svg className="hero-wave" viewBox="0 0 1200 80" preserveAspectRatio="none" aria-hidden="true">
        <path className="w1" d="M0 46 C 150 26 300 66 450 46 S 750 26 900 46 S 1200 66 1350 46 V80 H0Z"/>
        <path className="w2" d="M0 56 C 160 40 320 72 480 56 S 800 40 960 56 S 1280 72 1440 56 V80 H0Z"/>
      </svg>
    </header>

    <section className="glass lanes" aria-label={t('栏目实时状态', 'Live column status')}>
      <div className="lanes-head"><h2>{t('栏目实时状态', 'Live column status')}</h2>
        <div className="lanes-legend"><span><i className="tick tick-ok"/>{t('正常', 'OK')}</span><span><i className="tick tick-ok tick-new"/>{t('发现新文章', 'New articles')}</span>
          <span><i className="tick tick-error"/>{t('失败', 'Failed')}</span><span><i className="tick tick-ok tick-full"/>{t('完整核对', 'Full sweep')}</span>
          <span className="muted">{t('最近约 8 小时 → 现在', 'Last ~8 hours → now')}</span></div></div>
      {data.sources.map(s => <Lane key={s.id} s={s} now={now} onOpen={() => go('sources')}/>)}
    </section>

    <div className="overview-grid">
      <section className="glass panel">
        <div className="panel-head"><h2>{t('最新动态', 'Latest changes')}</h2><button className="link" onClick={() => go('updates')}>{t('全部动态', 'All updates')}<ArrowUpRight size={14}/></button></div>
        {data.recent.length ? <div className="event-list">{data.recent.map(e => <EventLine key={e.id} e={e} onOpen={onOpen}/>)}</div>
          : <Empty icon={<IconCalm size={26}/>} title={t('还没有新动态', 'No changes yet')}>
            {t('首次检查只建立基线，之后官网的新发布和修订会出现在这里。', 'The first check only records a baseline. New publications and revisions will appear here.')}</Empty>}
      </section>
      <section className={'glass panel attention' + (attention.length ? '' : ' calm')}>
        <div className="panel-head"><h2>{t('需要注意', 'Needs attention')}</h2></div>
        {attention.length ? <ul>{attention.map(a => <li key={a.key}><IconBuoy size={20}/><span>{a.text}</span>
          {a.action ? <button className="link" onClick={a.action}>{a.label}</button> : null}</li>)}</ul>
          : <p className="calm-note">{data.email.ready ? t('一切正常。官网有变化时会发邮件并显示在左侧。', 'All good. Changes on the site will be e-mailed and shown on the left.')
            : t('一切正常。官网有变化时会显示在左侧。', 'All good. Changes on the site will show on the left.')}</p>}
        <dl className="mini-stats">
          <div><dt>{t('待复查正文', 'Due for re-check')}</dt><dd>{data.stats.due}</dd></div>
          <div><dt>{t('附件文件', 'Attachments')}</dt><dd>{data.stats.attachments}</dd></div>
          <div><dt>{t('近 7 天变化', 'Changes, last 7 days')}</dt><dd>{data.stats.week_events}</dd></div>
          <div><dt>{t('服务已运行', 'Running for')}</dt><dd>{duration(now - data.started)}</dd></div>
        </dl>
      </section>
    </div>
  </div>;
}
