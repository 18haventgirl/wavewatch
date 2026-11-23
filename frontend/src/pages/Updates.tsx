import {useEffect, useMemo, useState} from 'react';
import {CheckCheck, Circle, Inbox, Search, X} from 'lucide-react';
import {api, post, type Page, type Source, type UpdateEvent} from '../api';
import {clock, dayLabel, publishedDate} from '../format';
import {useData, useHotkeys} from '../hooks';
import {Button, ColumnTag, Empty, ErrorNote, KindBadge, Loading, Pager, Segmented, Toggle, useAction, useDebounced} from '../ui';

type Kind = '' | 'new' | 'changes';

export default function Updates({onOpen, sources, refreshKey}: {onOpen: (id: string) => void; sources: Source[]; refreshKey: number}) {
  const [kind, setKind] = useState<Kind>('');
  const [source, setSource] = useState('');
  const [unread, setUnread] = useState(false);
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(1);
  const [cursor, setCursor] = useState(0);
  const q = useDebounced(query);
  const {busy, run} = useAction();
  useEffect(() => { setPage(1); setCursor(0); }, [kind, source, unread, q]);

  const {data, error, loading, reload, setData} = useData(signal => {
    const params = new URLSearchParams({kind, source, unread: String(unread), q, page: String(page), size: '40'});
    return api<Page<UpdateEvent> & {unread: number}>('/events?' + params, {signal});
  }, [kind, source, unread, q, page, refreshKey], 15000);

  const items = data?.items || [];
  const groups = useMemo(() => {
    const out: {day: string; items: {e: UpdateEvent; index: number}[]}[] = [];
    items.forEach((e, index) => {
      const day = dayLabel(e.created);
      if (!out.length || out[out.length - 1].day !== day) out.push({day, items: []});
      out[out.length - 1].items.push({e, index});
    });
    return out;
  }, [items]);

  async function markRead(e: UpdateEvent, read = true) {
    await post('/events/read', {ids: [e.id], read});
    setData(d => d ? {...d, unread: d.unread + (read ? -1 : 1), items: d.items.map(x => x.id === e.id ? {...x, read_at: read ? Date.now() / 1000 : null} : x)} : d);
  }

  useHotkeys({
    j: () => setCursor(c => Math.min(items.length - 1, c + 1)),
    k: () => setCursor(c => Math.max(0, c - 1)),
    Enter: () => { const e = items[cursor]; if (e) { markRead(e); onOpen(e.article_id); } },
    e: () => { const e = items[cursor]; if (e) markRead(e, !!e.read_at); },
  });
  useEffect(() => { document.querySelector('.update-row.cursor')?.scrollIntoView({block: 'nearest'}); }, [cursor]);

  return <div className="page">
    <header className="page-head">
      <div><h1>动态</h1><p>官网的新发布、正文修订和附件变化，按发现时间排列。</p></div>
      <Button icon={<CheckCheck size={16}/>} disabled={!data?.unread} busy={busy === 'all'}
        onClick={() => run('all', async () => { await post('/events/read', {all: true, source}); reload(); }, '已全部标为已读')}>
        {source ? '本栏目全部已读' : '全部标为已读'}</Button>
    </header>

    <div className="toolbar glass">
      <Segmented label="变化类型" value={kind} onChange={setKind}
        options={[{value: '', label: '全部'}, {value: 'new', label: '新发布'}, {value: 'changes', label: '修订与附件'}]}/>
      <select value={source} onChange={e => setSource(e.target.value)} aria-label="栏目">
        <option value="">全部栏目</option>
        {sources.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
      </select>
      <label className="inline-toggle"><Toggle checked={unread} onChange={setUnread} label="只看未读"/>只看未读{data ? <b>{data.unread}</b> : null}</label>
      <label className="search"><Search size={16}/><input value={query} onChange={e => setQuery(e.target.value)} placeholder="搜索标题" aria-label="搜索标题"/>
        {query ? <button onClick={() => setQuery('')} aria-label="清除"><X size={14}/></button> : null}</label>
    </div>

    {error ? <ErrorNote message={error} onRetry={reload}/> : null}
    <section className="glass panel timeline" aria-busy={loading}>
      {!data ? <Loading/> : !items.length ? <Empty icon={<Inbox/>} title={unread ? '没有未读动态' : '没有符合条件的动态'}>
        {unread ? '全部看完了。' : '换个筛选条件，或等待下次检查发现变化。'}</Empty> :
        groups.map(g => <div key={g.day} className="day-group">
          <h3 className="day">{g.day}</h3>
          {g.items.map(({e, index}) => <div key={e.id} className={'update-row' + (e.read_at ? '' : ' unread') + (index === cursor ? ' cursor' : '')}>
            <button className="read-dot" title={e.read_at ? '标为未读' : '标为已读'} aria-label={e.read_at ? '标为未读' : '标为已读'}
              onClick={() => markRead(e, !!e.read_at)}><Circle size={10}/></button>
            <button className="update-main" onClick={() => { setCursor(index); markRead(e); onOpen(e.article_id); }}>
              <span className="update-meta"><KindBadge kind={e.kind}/>{e.columns.map(c => <ColumnTag key={c.id} column={c}/>)}
                {e.published ? <span className="muted">原站发布 {publishedDate(e.published)}</span> : null}</span>
              <span className="update-title">{e.title}</span>
              {e.attachment_title ? <span className="update-note">附件：{e.attachment_title}{e.summary && e.kind === 'attachment_changed' ? `（${e.summary}）` : ''}</span>
                : e.summary ? <span className="update-note">{e.summary}</span> : null}
            </button>
            <time>{clock(e.created, false)}</time>
          </div>)}
        </div>)}
      {data ? <Pager page={page} total={data.total} size={data.size} onPage={setPage}/> : null}
    </section>
    <p className="hint">快捷键：J / K 上下移动，Enter 打开，E 切换已读，/ 搜索</p>
  </div>;
}
