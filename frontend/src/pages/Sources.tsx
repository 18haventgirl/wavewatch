import {ExternalLink, ScanSearch} from 'lucide-react';
import {IconRefresh} from '../icons';
import {patch, post, type Notify, type Source} from '../api';
import {ago, clock, countdown, everyHours, interval, notifyLabel} from '../format';
import {useNow} from '../hooks';
import {columnName, groupName, t, tx} from '../i18n';
import {Button, ColumnTag, Dot, Segmented, Toggle, useAction} from '../ui';
import {sourceTone} from './Overview';

const LIST_MINUTES = [1, 2, 3, 5, 10, 15, 30, 60, 120, 360];
const ARTICLE_HOURS = [1, 2, 3, 6, 12, 24, 48, 72, 168];

function withCurrent(options: number[], value: number) {
  return options.includes(value) ? options : [...options, value].sort((a, b) => a - b);
}

function SourceRow({s, onChange, now}: {s: Source; onChange: (s: Source) => void; now: number}) {
  const {busy, run} = useAction();
  const name = columnName(s.id, s.name);
  const save = (body: Partial<Pick<Source, 'list_minutes' | 'article_hours' | 'notify'>> & {enabled?: boolean}, done: string) =>
    run('save', async () => onChange(await patch<Source>('/sources/' + s.id, body)), done);
  const check = (full: boolean) => run(full ? 'full' : 'quick', async () => {
    await post('/sources/' + s.id + '/check', {full});
    onChange({...s, next_check: 0, state: 'checking'});
  }, full ? t('已开始完整核对，所有分页都会重新读取', 'Full sweep started; every page will be read again') : t('已开始检查', 'Check started'));
  const tone = sourceTone(s);
  const last = s.last_run;
  const state = !s.enabled ? t('已暂停', 'Paused') : s.state === 'checking' ? t('正在检查', 'Checking')
    : s.state === 'error' ? t(`连续失败 ${s.fail_count} 次`, `Failed ${s.fail_count}× in a row`)
    : s.last_success ? t('运行正常', 'Working') : t('等待首次检查', 'Waiting for first check');

  return <article className={'glass source-row' + (s.enabled ? '' : ' off')}>
    <header>
      <ColumnTag column={{id: s.id, name: s.name, role: s.role, group: s.grp}}/>
      <span className="muted">{t(`官网栏目 ${s.column_id}`, `Site column ${s.column_id}`)}</span>
      <a className="link" href={s.page_url} target="_blank" rel="noreferrer">{t('打开官网栏目', 'Open on the site')}<ExternalLink size={13}/></a>
      <span className={'source-state tone-' + tone}><Dot tone={tone}/>{state}</span>
      <label className="inline-toggle end"><Toggle checked={!!s.enabled} label={t('启用监测', 'Monitor this column')} disabled={busy === 'save'}
        onChange={v => save({enabled: v}, v ? t(`已恢复监测「${name}」`, `Monitoring "${name}" again`) : t(`已暂停「${name}」，不再检查也不发邮件`, `Paused "${name}": no checks and no e-mail`))}/>
        {s.enabled ? t('监测中', 'On') : t('已暂停', 'Paused')}</label>
    </header>

    {s.error ? <div className="error-note">{tx(s.error)}</div> : null}

    <div className="source-settings">
      <label className="setting"><span>{t('检查新发布', 'Check for new articles')}</span>
        <select value={s.list_minutes} disabled={!s.enabled} onChange={e => save({list_minutes: Number(e.target.value)}, t('检查频率已更新', 'Check interval updated'))}>
          {withCurrent(LIST_MINUTES, s.list_minutes).map(m => <option key={m} value={m}>{interval(m)}</option>)}
        </select></label>
      <label className="setting"><span>{t('复查正文和附件', 'Re-check bodies and files')}</span>
        <select value={s.article_hours} disabled={!s.enabled} onChange={e => save({article_hours: Number(e.target.value)}, t('复查频率已更新', 'Re-check interval updated'))}>
          {withCurrent(ARTICLE_HOURS, s.article_hours).map(h => <option key={h} value={h}>{everyHours(h)}</option>)}
        </select></label>
      <div className="setting"><span>{t('邮件通知', 'E-mail')}</span>
        <Segmented<Notify> label={t('邮件通知方式', 'E-mail mode')} value={s.notify}
          onChange={v => save({notify: v}, t(`「${name}」改为${notifyLabel(v)}`, `"${name}" now uses ${notifyLabel(v)}`))}
          options={[{value: 'instant', label: t('即时', 'Instant')}, {value: 'digest', label: t('每日汇总', 'Daily digest')}, {value: 'off', label: t('不发', 'None')}]}/></div>
    </div>

    <dl className="source-facts">
      <div><dt>{t('上次检查', 'Last check')}</dt><dd>{ago(s.last_check, now)}{last ? <small>{tx(last.message)}</small> : null}</dd></div>
      <div><dt>{t('下次检查', 'Next check')}</dt><dd>{s.enabled ? (s.state === 'checking' ? t('进行中', 'Running') : countdown(s.next_check, now)) : '—'}</dd></div>
      <div><dt>{t('官网条数 / 已收录', 'On site / collected')}</dt><dd>{s.reported_total ?? '—'} / {s.articles}</dd></div>
      <div><dt>{t('上次完整核对', 'Last full sweep')}</dt><dd>{clock(s.last_full)}</dd></div>
      <div><dt>{t('最近一次新发布', 'Latest new article')}</dt><dd>{s.last_added?.at ? clock(s.last_added.at) : t('尚未发现', 'None yet')}</dd></div>
    </dl>

    <footer>
      <Button small icon={<IconRefresh size={16}/>} busy={busy === 'quick'} disabled={!s.enabled} onClick={() => check(false)}>{t('立即检查', 'Check now')}</Button>
      <Button small variant="quiet" icon={<ScanSearch size={14}/>} busy={busy === 'full'} disabled={!s.enabled} onClick={() => check(true)}
        title={t('重新读取全部分页，核对是否有遗漏', 'Read every page again to catch anything missed')}>{t('完整核对', 'Full sweep')}</Button>
    </footer>
  </article>;
}

export default function Sources({sources, onChange}: {sources: Source[]; onChange: (s: Source) => void}) {
  const now = useNow();
  const groups = [...new Set(sources.map(s => s.grp))];
  return <div className="page">
    <header className="page-head"><div><h1>{t('栏目', 'Columns')}</h1>
      <p>{t('每个栏目单独设置检查频率和邮件方式。检查新发布只读第一页，请求很少；每天还会自动做一次完整核对。',
        'Set the check interval and e-mail mode for each column. Checking for new articles reads only the first page, so it is light on the site; a full sweep also runs once a day.')}</p></div></header>
    {groups.map(g => <section key={g} className="source-group">
      <h2 className="group-title">{groupName(g)}</h2>
      {sources.filter(s => s.grp === g).map(s => <SourceRow key={s.id} s={s} onChange={onChange} now={now}/>)}
    </section>)}
  </div>;
}
