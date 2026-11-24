import {useState} from 'react';
import {AlertCircle} from 'lucide-react';
import {IconRuns} from '../icons';
import {api, type Run, type Source} from '../api';
import {ago, clock, fullTime} from '../format';
import {useData} from '../hooks';
import {columnName, t, tx} from '../i18n';
import {Dot, Empty, ErrorNote, Loading, Pager, Segmented, Toggle} from '../ui';

type RunsPage = {items: (Run & {name: string})[]; total: number; page: number; size: number;
  article_errors: {id: string; title: string; url: string; check_error: string; fail_count: number; last_check: number | null; next_check: number}[]};

const tone = (s: Run['state']) => s === 'ok' ? 'ok' : s === 'running' ? 'live' : s === 'error' ? 'error' : 'warn';
const stateText = (s: Run['state']) => ({ok: t('成功', 'OK'), running: t('进行中', 'Running'), error: t('失败', 'Failed'), interrupted: t('中断', 'Interrupted')})[s];

export default function Runs({sources, onOpen, refreshKey}: {sources: Source[]; onOpen: (id: string) => void; refreshKey: number}) {
  const [source, setSource] = useState('');
  const [state, setState] = useState<'' | 'error'>('');
  const [important, setImportant] = useState(true);
  const [page, setPage] = useState(1);
  const {data, error, reload} = useData(s => api<RunsPage>(
    `/runs?source=${source}&state=${state}&changes_only=${important}&page=${page}`, {signal: s}), [source, state, important, page, refreshKey], 10000);

  return <div className="page">
    <header className="page-head"><div><h1>{t('运行记录', 'Activity log')}</h1>
      <p>{t('每次栏目检查的结果。没有新内容的快速检查保留 7 天。', 'The result of every column check. Quick checks with nothing new are kept for 7 days.')}</p></div></header>
    <div className="toolbar glass">
      <select value={source} onChange={e => { setSource(e.target.value); setPage(1); }} aria-label={t('栏目', 'Column')}>
        <option value="">{t('全部栏目', 'All columns')}</option>{sources.map(s => <option key={s.id} value={s.id}>{columnName(s.id, s.name)}</option>)}</select>
      <Segmented label={t('结果', 'Result')} value={state} onChange={v => { setState(v); setPage(1); }}
        options={[{value: '', label: t('全部结果', 'All results')}, {value: 'error', label: t('只看失败', 'Failures only')}]}/>
      <label className="inline-toggle"><Toggle checked={important} onChange={v => { setImportant(v); setPage(1); }} label={t('隐藏无变化的检查', 'Hide quiet checks')}/>
        {t('隐藏无变化的快速检查', 'Hide quick checks with nothing new')}</label>
    </div>
    {error ? <ErrorNote message={error} onRetry={reload}/> : null}

    {data?.article_errors.length ? <section className="glass panel">
      <div className="panel-head"><h2><AlertCircle size={18}/>{t('正文复查失败', 'Re-checks that failed')}</h2>
        <span className="muted">{t('会自动重试，失败越多间隔越长', 'Retried automatically, waiting longer after each failure')}</span></div>
      <div className="run-list">{data.article_errors.map(a => <button key={a.id} className="run-row" onClick={() => onOpen(a.id)}>
        <Dot tone="warn"/><span className="run-main"><b>{a.title}</b><small>{tx(a.check_error)}</small></span>
        <span className="run-side">{t(`失败 ${a.fail_count} 次`, `Failed ${a.fail_count}×`)}<small>{t('下次 ', 'Next ')}{clock(a.next_check)}</small></span></button>)}</div>
    </section> : null}

    <section className="glass panel">
      {!data ? <Loading/> : !data.items.length ? <Empty icon={<IconRuns size={26}/>} title={t('没有符合条件的记录', 'No matching entries')}>
        {important ? t('关闭“隐藏无变化的快速检查”可以看到每一次检查。', 'Turn off "Hide quick checks with nothing new" to see every check.')
          : t('服务启动后，检查记录会出现在这里。', 'Checks will appear here once the service runs.')}</Empty> :
        <div className="run-list">{data.items.map(r => <div key={r.id} className="run-row">
          <Dot tone={tone(r.state)}/>
          <span className="run-main"><b>{columnName(r.source_id, r.name)}<span className="pill">{r.mode === 'full' ? t('完整核对', 'Full sweep') : t('快速检查', 'Quick check')}</span>
            {r.added ? <span className="pill blue">{t(`新增 ${r.added}`, `${r.added} new`)}</span> : null}</b><small>{tx(r.message) || stateText(r.state)}</small></span>
          <span className="run-side" title={fullTime(r.started)}>{clock(r.started)}
            <small>{r.finished ? t(`用时 ${Math.max(0.1, r.finished - r.started).toFixed(1)} 秒`, `took ${Math.max(0.1, r.finished - r.started).toFixed(1)} s`) : ago(r.started)}</small></span>
        </div>)}</div>}
      {data ? <Pager page={page} total={data.total} size={data.size} onPage={setPage}/> : null}
    </section>
  </div>;
}
