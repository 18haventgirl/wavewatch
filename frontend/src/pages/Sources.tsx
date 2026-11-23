import {ExternalLink, ScanSearch} from 'lucide-react';
import {IconRefresh} from '../icons';
import {patch, post, type Notify, type Source} from '../api';
import {ago, clock, countdown, notifyLabel} from '../format';
import {useNow} from '../hooks';
import {Button, ColumnTag, Dot, Segmented, Toggle, useAction} from '../ui';
import {sourceTone} from './Overview';

const LIST_MINUTES = [1, 2, 3, 5, 10, 15, 30, 60, 120, 360];
const ARTICLE_HOURS = [1, 2, 3, 6, 12, 24, 48, 72, 168];

function withCurrent(options: number[], value: number) {
  return options.includes(value) ? options : [...options, value].sort((a, b) => a - b);
}

function SourceRow({s, onChange, now}: {s: Source; onChange: (s: Source) => void; now: number}) {
  const {busy, run} = useAction();
  const save = (body: Partial<Pick<Source, 'list_minutes' | 'article_hours' | 'notify'>> & {enabled?: boolean}, done: string) =>
    run('save', async () => onChange(await patch<Source>('/sources/' + s.id, body)), done);
  const check = (full: boolean) => run(full ? 'full' : 'quick', async () => {
    await post('/sources/' + s.id + '/check', {full});
    onChange({...s, next_check: 0, state: 'checking'});
  }, full ? '已开始完整核对，所有分页都会重新读取' : '已开始检查');
  const tone = sourceTone(s);
  const run_ = s.last_run;

  return <article className={'glass source-row' + (s.enabled ? '' : ' off')}>
    <header>
      <ColumnTag column={{id: s.id, name: s.name, role: s.role, group: s.grp}}/>
      <span className="muted">官网栏目 {s.column_id}</span>
      <a className="link" href={s.page_url} target="_blank" rel="noreferrer">打开官网栏目<ExternalLink size={13}/></a>
      <span className={'source-state tone-' + tone}><Dot tone={tone}/>
        {!s.enabled ? '已暂停' : s.state === 'checking' ? '正在检查' : s.state === 'error' ? `连续失败 ${s.fail_count} 次` : s.last_success ? '运行正常' : '等待首次检查'}</span>
      <label className="inline-toggle end"><Toggle checked={!!s.enabled} label="启用监测" disabled={busy === 'save'}
        onChange={v => save({enabled: v}, v ? `已恢复监测「${s.name}」` : `已暂停「${s.name}」，不再检查也不发邮件`)}/>{s.enabled ? '监测中' : '已暂停'}</label>
    </header>

    {s.error ? <div className="error-note">{s.error}</div> : null}

    <div className="source-settings">
      <label className="setting"><span>检查新发布</span>
        <select value={s.list_minutes} disabled={!s.enabled} onChange={e => save({list_minutes: Number(e.target.value)}, '检查频率已更新')}>
          {withCurrent(LIST_MINUTES, s.list_minutes).map(m => <option key={m} value={m}>{m < 60 ? `每 ${m} 分钟` : `每 ${m / 60} 小时`}</option>)}
        </select></label>
      <label className="setting"><span>复查正文和附件</span>
        <select value={s.article_hours} disabled={!s.enabled} onChange={e => save({article_hours: Number(e.target.value)}, '复查频率已更新')}>
          {withCurrent(ARTICLE_HOURS, s.article_hours).map(h => <option key={h} value={h}>{h < 24 ? `每 ${h} 小时` : `每 ${h / 24} 天`}</option>)}
        </select></label>
      <div className="setting"><span>邮件通知</span>
        <Segmented<Notify> label="邮件通知方式" value={s.notify} onChange={v => save({notify: v}, `「${s.name}」改为${notifyLabel[v]}`)}
          options={[{value: 'instant', label: '即时'}, {value: 'digest', label: '每日汇总'}, {value: 'off', label: '不发'}]}/></div>
    </div>

    <dl className="source-facts">
      <div><dt>上次检查</dt><dd>{ago(s.last_check, now)}{run_ ? <small>{run_.message}</small> : null}</dd></div>
      <div><dt>下次检查</dt><dd>{s.enabled ? (s.state === 'checking' ? '进行中' : countdown(s.next_check, now)) : '—'}</dd></div>
      <div><dt>官网条数 / 已收录</dt><dd>{s.reported_total ?? '—'} / {s.articles}</dd></div>
      <div><dt>上次完整核对</dt><dd>{clock(s.last_full)}</dd></div>
      <div><dt>最近一次新发布</dt><dd>{s.last_added?.at ? clock(s.last_added.at) : '尚未发现'}</dd></div>
    </dl>

    <footer>
      <Button small icon={<IconRefresh size={16}/>} busy={busy === 'quick'} disabled={!s.enabled} onClick={() => check(false)}>立即检查</Button>
      <Button small variant="quiet" icon={<ScanSearch size={14}/>} busy={busy === 'full'} disabled={!s.enabled} onClick={() => check(true)}
        title="重新读取全部分页，核对是否有遗漏">完整核对</Button>
    </footer>
  </article>;
}

export default function Sources({sources, onChange}: {sources: Source[]; onChange: (s: Source) => void}) {
  const now = useNow();
  const groups = [...new Set(sources.map(s => s.grp))];
  return <div className="page">
    <header className="page-head"><div><h1>栏目</h1>
      <p>每个栏目单独设置检查频率和邮件方式。检查新发布只读第一页，请求很少；每天还会自动做一次完整核对。</p></div></header>
    {groups.map(g => <section key={g} className="source-group">
      <h2 className="group-title">{g}</h2>
      {sources.filter(s => s.grp === g).map(s => <SourceRow key={s.id} s={s} onChange={onChange} now={now}/>)}
    </section>)}
  </div>;
}
