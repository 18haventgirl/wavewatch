import {useEffect, useState} from 'react';
import {AlertCircle, FileText, Layers, Paperclip, Search, X} from 'lucide-react';
import {api, type ArticleRow, type Page, type Source} from '../api';
import {ago, publishedDate} from '../format';
import {useData, useHotkeys} from '../hooks';
import {ColumnTag, Empty, ErrorNote, Loading, Pager, Segmented, useDebounced} from '../ui';

type Status = '' | 'unread' | 'changed' | 'attachments' | 'error';

export default function Library({onOpen, sources, refreshKey}: {onOpen: (id: string) => void; sources: Source[]; refreshKey: number}) {
  const [query, setQuery] = useState('');
  const [scope, setScope] = useState('');          // '', 'core', 'news' or a source id
  const [status, setStatus] = useState<Status>('');
  const [sort, setSort] = useState('published');
  const [page, setPage] = useState(1);
  const [cursor, setCursor] = useState(0);
  const q = useDebounced(query);
  const isSource = scope !== '' && scope !== 'core' && scope !== 'news';
  useEffect(() => { setPage(1); setCursor(0); }, [q, scope, status, sort]);
  useEffect(() => { if (!isSource && sort === 'official') setSort('published'); }, [isSource, sort]);

  const {data, error, loading, reload} = useData(signal => {
    const params = new URLSearchParams({q, status, sort, page: String(page), size: '30',
      ...(isSource ? {source: scope} : {group: scope})});
    return api<Page<ArticleRow>>('/articles?' + params, {signal});
  }, [q, scope, status, sort, page, refreshKey], 30000);
  const items = data?.items || [];

  useHotkeys({
    j: () => setCursor(c => Math.min(items.length - 1, c + 1)),
    k: () => setCursor(c => Math.max(0, c - 1)),
    Enter: () => { if (items[cursor]) onOpen(items[cursor].id); },
  });
  useEffect(() => { document.querySelector('.doc-row.cursor')?.scrollIntoView({block: 'nearest'}); }, [cursor]);

  return <div className="page">
    <header className="page-head"><div><h1>文库</h1><p>已收录的全部文章，可按栏目、状态和时间查找。</p></div></header>

    <div className="toolbar glass">
      <label className="search grow"><Search size={16}/><input value={query} onChange={e => setQuery(e.target.value)}
        placeholder="搜索标题、副标题或来源，多个词用空格分隔" aria-label="搜索文章"/>
        {query ? <button onClick={() => setQuery('')} aria-label="清除"><X size={14}/></button> : null}</label>
      <select value={scope} onChange={e => setScope(e.target.value)} aria-label="栏目">
        <option value="">全部栏目</option>
        <option value="core">政策法规（核心）</option>
        <option value="news">资讯动态</option>
        <optgroup label="单个栏目">{sources.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</optgroup>
      </select>
      <select value={sort} onChange={e => setSort(e.target.value)} aria-label="排序">
        <option value="published">按原站发布时间</option>
        <option value="discovered">按收录时间</option>
        <option value="updated">按最近变化</option>
        {isSource ? <option value="official">按官网列表顺序</option> : null}
      </select>
    </div>
    <div className="subbar">
      <Segmented label="状态" value={status} onChange={setStatus} options={[
        {value: '', label: '全部'}, {value: 'unread', label: '未读'}, {value: 'changed', label: '有修订'},
        {value: 'attachments', label: '含附件'}, {value: 'error', label: '复查失败'}]}/>
    </div>

    {error ? <ErrorNote message={error} onRetry={reload}/> : null}
    <section className="glass panel" aria-busy={loading}>
      {!data ? <Loading/> : !items.length ? <Empty icon={<FileText/>} title="没有找到文章">试试更短的关键词，或切换栏目和状态。</Empty> :
        <div className="doc-list">{items.map((a, i) => <button key={a.id} className={'doc-row' + (i === cursor ? ' cursor' : '') + (a.unread ? ' unread' : '')}
          onClick={() => { setCursor(i); onOpen(a.id); }}>
          <span className="doc-date">{publishedDate(a.published) || '日期未知'}</span>
          <span className="doc-main">
            <span className="doc-title">{a.unread ? <i className="unread-dot" aria-label="未读"/> : null}{a.title}</span>
            {a.subtitle && a.subtitle !== a.title ? <span className="doc-sub">{a.subtitle}</span> : null}
            <span className="doc-meta">
              {a.columns.map(c => <ColumnTag key={c.id} column={c}/>)}
              {a.origin ? <span className="muted">来源：{a.origin}</span> : null}
              {a.changes ? <span className="pill amber"><Layers size={12}/>{a.changes} 次变化</span> : null}
              {a.attachments ? <span className="pill teal"><Paperclip size={12}/>{a.attachments} 个附件</span> : null}
              {a.check_error ? <span className="pill red" title={a.check_error}><AlertCircle size={12}/>复查失败</span> : null}
            </span>
          </span>
          <span className="doc-check muted">{a.last_check ? `复查于 ${ago(a.last_check)}` : '待首次保存'}</span>
        </button>)}</div>}
      {data ? <Pager page={page} total={data.total} size={data.size} onPage={setPage}/> : null}
    </section>
  </div>;
}
