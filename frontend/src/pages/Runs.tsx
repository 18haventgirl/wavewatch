import {useState} from 'react';
import {AlertCircle} from 'lucide-react';
import {IconRuns} from '../icons';
import {api, type Run, type Source} from '../api';
import {ago, clock, fullTime} from '../format';
import {useData} from '../hooks';
import {Dot, Empty, ErrorNote, Loading, Pager, Segmented, Toggle} from '../ui';

type RunsPage = {items: (Run & {name: string})[]; total: number; page: number; size: number;
  article_errors: {id: string; title: string; url: string; check_error: string; fail_count: number; last_check: number | null; next_check: number}[]};

const tone = (s: Run['state']) => s === 'ok' ? 'ok' : s === 'running' ? 'live' : s === 'error' ? 'error' : 'warn';
const stateText = {ok: '成功', running: '进行中', error: '失败', interrupted: '中断'} as const;

export default function Runs({sources, onOpen, refreshKey}: {sources: Source[]; onOpen: (id: string) => void; refreshKey: number}) {
  const [source, setSource] = useState('');
  const [state, setState] = useState<'' | 'error'>('');
  const [important, setImportant] = useState(true);
  const [page, setPage] = useState(1);
  const {data, error, reload} = useData(s => api<RunsPage>(
    `/runs?source=${source}&state=${state}&changes_only=${important}&page=${page}`, {signal: s}), [source, state, important, page, refreshKey], 10000);

  return <div className="page">
    <header className="page-head"><div><h1>运行记录</h1><p>每次栏目检查的结果。没有新内容的快速检查保留 7 天。</p></div></header>
    <div className="toolbar glass">
      <select value={source} onChange={e => { setSource(e.target.value); setPage(1); }} aria-label="栏目">
        <option value="">全部栏目</option>{sources.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select>
      <Segmented label="结果" value={state} onChange={v => { setState(v); setPage(1); }} options={[{value: '', label: '全部结果'}, {value: 'error', label: '只看失败'}]}/>
      <label className="inline-toggle"><Toggle checked={important} onChange={v => { setImportant(v); setPage(1); }} label="隐藏无变化的检查"/>隐藏无变化的快速检查</label>
    </div>
    {error ? <ErrorNote message={error} onRetry={reload}/> : null}

    {data?.article_errors.length ? <section className="glass panel">
      <div className="panel-head"><h2><AlertCircle size={18}/>正文复查失败</h2><span className="muted">会自动重试，失败越多间隔越长</span></div>
      <div className="run-list">{data.article_errors.map(a => <button key={a.id} className="run-row" onClick={() => onOpen(a.id)}>
        <Dot tone="warn"/><span className="run-main"><b>{a.title}</b><small>{a.check_error}</small></span>
        <span className="run-side">失败 {a.fail_count} 次<small>下次 {clock(a.next_check)}</small></span></button>)}</div>
    </section> : null}

    <section className="glass panel">
      {!data ? <Loading/> : !data.items.length ? <Empty icon={<IconRuns size={26}/>} title="没有符合条件的记录">
        {important ? '关闭“隐藏无变化的快速检查”可以看到每一次检查。' : '服务启动后，检查记录会出现在这里。'}</Empty> :
        <div className="run-list">{data.items.map(r => <div key={r.id} className="run-row">
          <Dot tone={tone(r.state)}/>
          <span className="run-main"><b>{r.name}<span className="pill">{r.mode === 'full' ? '完整核对' : '快速检查'}</span>
            {r.added ? <span className="pill blue">新增 {r.added}</span> : null}</b><small>{r.message || stateText[r.state]}</small></span>
          <span className="run-side" title={fullTime(r.started)}>{clock(r.started)}<small>{r.finished ? `用时 ${Math.max(0.1, r.finished - r.started).toFixed(1)} 秒` : ago(r.started)}</small></span>
        </div>)}</div>}
      {data ? <Pager page={page} total={data.total} size={data.size} onPage={setPage}/> : null}
    </section>
  </div>;
}
