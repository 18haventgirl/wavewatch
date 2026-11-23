import {useEffect, useMemo, useRef, useState, type ReactNode} from 'react';
import {Download, ExternalLink, FileText, Layers, Paperclip, RefreshCw, X} from 'lucide-react';
import {api, post, type ArticleDetail, type Compare, type DiffRow, type Version} from './api';
import {ago, bytes, clock, fullTime, kindLabel} from './format';
import {useData, useHotkeys} from './hooks';
import {Button, ColumnTag, Empty, ErrorNote, KindBadge, Loading, Segmented, useAction} from './ui';

type Tab = 'content' | 'diff' | 'files' | 'log';

function Highlighted({text, spans}: {text: string; spans?: number[][]}) {
  if (!spans?.length) return <>{text}</>;
  const parts: ReactNode[] = [];
  let at = 0;
  spans.forEach(([a, b], i) => {
    if (a > at) parts.push(text.slice(at, a));
    parts.push(<mark key={i}>{text.slice(a, b)}</mark>);
    at = b;
  });
  parts.push(text.slice(at));
  return <>{parts}</>;
}

function DiffView({rows}: {rows: DiffRow[]}) {
  return <div className="diff" role="table" aria-label="版本对比">
    {rows.map((r, i) => r.type === 'fold'
      ? <div key={i} className="diff-fold">… {r.count} 行未变化 …</div>
      : <div key={i} className={'diff-row diff-' + r.type} role="row">
        <span className="ln">{r.old_no ?? ''}</span>
        <span className="cell old">{r.old != null ? <Highlighted text={r.old} spans={r.spans?.old}/> : null}</span>
        <span className="ln">{r.new_no ?? ''}</span>
        <span className="cell new">{r.new != null ? <Highlighted text={r.new} spans={r.spans?.new}/> : null}</span>
      </div>)}
  </div>;
}

function versionLabel(v: Version, index: number) {
  return `${clock(v.created)}${index === 0 ? '（最新）' : ''}${v.baseline ? ' 基线' : ' 修订'}`;
}

export default function Article({id, onClose, onOpen, onChanged}: {id: string; onClose: () => void; onOpen: (id: string) => void; onChanged: () => void}) {
  const {data, error, reload, setData} = useData(s => api<ArticleDetail>('/articles/' + id, {signal: s}), [id], 15000);
  const [tab, setTab] = useState<Tab>('content');
  const [versionId, setVersionId] = useState<number | null>(null);
  const [versionText, setVersionText] = useState('');
  const [base, setBase] = useState<number | null>(null);
  const [target, setTarget] = useState<number | null>(null);
  const [diff, setDiff] = useState<Compare | null>(null);
  const {busy, run} = useAction();
  const sheet = useRef<HTMLElement>(null);
  useHotkeys({Escape: onClose});

  useEffect(() => { setTab('content'); setVersionId(null); setBase(null); setTarget(null); sheet.current?.focus(); }, [id]);

  // Opening an item marks its unread changes as read.
  const markedFor = useRef('');
  useEffect(() => {
    if (!data || data.id !== id || markedFor.current === id) return;
    markedFor.current = id;
    if (data.events.some(e => !e.read_at)) post('/events/read', {articles: [id]}).then(onChanged).catch(() => undefined);
  }, [data, id, onChanged]);

  useEffect(() => {
    if (!versionId || !data || versionId === data.versions[0]?.id) { setVersionText(''); return; }
    api<{content: string}>(`/articles/${id}/versions/${versionId}`).then(v => setVersionText(v.content)).catch(() => setVersionText(''));
  }, [versionId, id, data]);

  useEffect(() => {
    if (tab !== 'diff' || !data || data.versions.length < 2) return;
    const params = new URLSearchParams();
    if (base) params.set('base', String(base));
    if (target) params.set('target', String(target));
    api<Compare>(`/articles/${id}/compare?${params}`).then(setDiff).catch(() => setDiff(null));
  }, [tab, base, target, id, data?.versions.length]);

  const unread = useMemo(() => data?.events.some(e => !e.read_at), [data]);
  const content = versionText || data?.content || '';
  const body = content.split('\n\n').slice(1).join('\n\n') || content;

  return <div className="sheet-backdrop" onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}>
    <aside className="sheet glass" ref={sheet} tabIndex={-1} role="dialog" aria-modal="true" aria-label="文章详情">
      <div className="sheet-top">
        <div className="sheet-tags">{data?.columns.map(c => <ColumnTag key={c.id} column={c}/>)}
          {data?.kind === 'attachment' ? <span className="pill teal">附件文件</span> : null}</div>
        <button className="icon-btn" onClick={onClose} aria-label="关闭（Esc）"><X size={19}/></button>
      </div>
      {error ? <ErrorNote message={error} onRetry={reload}/> : !data ? <Loading/> : <>
        <h1 className="sheet-title">{data.title}</h1>
        {data.subtitle && data.subtitle !== data.title ? <p className="sheet-sub">{data.subtitle}</p> : null}
        <dl className="sheet-meta">
          <div><dt>原站发布</dt><dd>{data.published || '—'}</dd></div>
          <div><dt>收录于</dt><dd>{fullTime(data.discovered)}</dd></div>
          {data.origin ? <div><dt>文章来源</dt><dd>{data.origin}</dd></div> : null}
          <div><dt>最近复查</dt><dd>{data.last_check ? ago(data.last_check) : '尚未保存正文'}{data.check_error ? <em className="err">（{data.check_error}）</em> : null}</dd></div>
        </dl>
        {data.parents.length ? <p className="muted small">所属文章：{data.parents.map(p => <button key={p.id} className="link" onClick={() => onOpen(p.id)}>{p.title}</button>)}</p> : null}
        <div className="sheet-actions">
          <a className="btn btn-primary" href={data.url} target="_blank" rel="noreferrer"><ExternalLink size={16}/>打开官网原文</a>
          <Button icon={<RefreshCw size={15}/>} busy={busy === 'check'} onClick={() => run('check', async () => {
            await post(`/articles/${id}/check`); window.setTimeout(reload, 4000);
          }, '已加入复查，几秒后刷新')}>立即复查</Button>
          {data.events.length ? <Button variant="quiet" onClick={() => run('read', async () => {
            await post('/events/read', {articles: [id], read: !!unread});
            setData({...data, events: data.events.map(e => ({...e, read_at: unread ? Date.now() / 1000 : null}))}); onChanged();
          })}>{unread ? '标为已读' : '标为未读'}</Button> : null}
        </div>

        <Segmented<Tab> label="详情内容" value={tab} onChange={setTab} options={[
          {value: 'content', label: data.kind === 'attachment' ? '文件内容' : '正文'},
          {value: 'diff', label: '修订对比', count: Math.max(0, data.versions.length - 1)},
          ...(data.kind === 'article' ? [{value: 'files' as Tab, label: '附件', count: data.attachments.length}] : []),
          {value: 'log', label: '记录', count: data.events.length}]}/>

        {tab === 'content' ? <div className="tab-body">
          {data.versions.length ? <>
            <div className="version-bar">
              <select value={versionId ?? data.versions[0].id} onChange={e => setVersionId(Number(e.target.value))} aria-label="选择版本">
                {data.versions.map((v, i) => <option key={v.id} value={v.id}>{versionLabel(v, i)}</option>)}</select>
              {(() => { const v = data.versions.find(x => x.id === (versionId ?? data.versions[0].id)); return v?.note ? <span className="muted small">{v.note}</span> : null; })()}
              {(() => { const v = data.versions.find(x => x.id === (versionId ?? data.versions[0].id)); return v?.file_digest
                ? <a className="btn btn-plain btn-small" href={`/api/files/${v.file_digest}`}><Download size={14}/>下载此版本文件{v.file_bytes ? `（${bytes(v.file_bytes)}）` : ''}</a> : null; })()}
            </div>
            <article className="reading">{body.split('\n').map((line, i) => line.startsWith('[图片]')
              ? <p key={i} className="figure-note">{line}</p> : <p key={i}>{line}</p>)}</article>
          </> : <Empty icon={<FileText/>} title="正文还没有保存">发现后会尽快读取正文；可以点“立即复查”。</Empty>}
        </div> : null}

        {tab === 'diff' ? <div className="tab-body">
          {data.versions.length < 2 ? <Empty icon={<Layers/>} title="还没有修订">目前只有基线版本。官网修改正文、标题或附件后，这里会并排显示前后差异。</Empty> : <>
            <div className="version-bar">
              <label>旧版本 <select value={base ?? diff?.base ?? ''} onChange={e => setBase(Number(e.target.value))}>
                {data.versions.slice(1).map((v, i) => <option key={v.id} value={v.id}>{versionLabel(v, i + 1)}</option>)}</select></label>
              <label>新版本 <select value={target ?? diff?.target ?? ''} onChange={e => setTarget(Number(e.target.value))}>
                {data.versions.map((v, i) => <option key={v.id} value={v.id}>{versionLabel(v, i)}</option>)}</select></label>
              {diff ? <span className="diff-stats"><b className="plus">+{diff.stats.added}</b><b className="minus">−{diff.stats.removed}</b></span> : null}
            </div>
            {diff ? <DiffView rows={diff.rows}/> : <Loading/>}
          </>}
        </div> : null}

        {tab === 'files' ? <div className="tab-body">
          {data.attachments.length ? <div className="file-list">{data.attachments.map(a => <div key={a.id} className="file-row">
            <Paperclip size={18}/>
            <button className="file-main" onClick={() => onOpen(a.id)}><b>{a.title}</b>
              <small>{a.versions} 个版本{a.bytes ? `，${bytes(a.bytes)}` : ''}{a.last_check ? `，复查于 ${ago(a.last_check)}` : '，待下载'}{a.check_error ? `，${a.check_error}` : ''}</small></button>
            {a.file_digest ? <a className="icon-btn" href={`/api/files/${a.file_digest}`} aria-label="下载"><Download size={17}/></a> : null}
            <a className="icon-btn" href={a.url} target="_blank" rel="noreferrer" aria-label="打开官网文件"><ExternalLink size={16}/></a>
          </div>)}</div> : <Empty icon={<Paperclip/>} title="没有附件">正文中出现附件链接时会自动下载并跟踪变化。</Empty>}
        </div> : null}

        {tab === 'log' ? <div className="tab-body">
          <h3 className="mini-title">变化记录</h3>
          {data.events.length ? <ul className="log-list">{data.events.map(e => <li key={e.id}><KindBadge kind={e.kind}/>
            <span>{e.attachment_title ? `${kindLabel[e.kind]}：${e.attachment_title}` : e.summary || kindLabel[e.kind]}</span>
            <time>{fullTime(e.created)}</time></li>)}</ul> : <p className="muted small">收录以来没有变化。首次收录只建立基线，不算作变化。</p>}
          <h3 className="mini-title">出现在官网栏目</h3>
          <ul className="log-list">{data.entries.map(e => <li key={e.source_id + e.position}><span className="pill">{e.name}</span>
            <span>{e.page ? `第 ${e.page} 页` : ''}{e.raw_title && e.raw_title !== data.title ? `，列表标题：${e.raw_title}` : ''}</span>
            <time>首次 {clock(e.first_seen)}，最近 {clock(e.last_seen)}</time></li>)}</ul>
        </div> : null}
      </>}
    </aside>
  </div>;
}
