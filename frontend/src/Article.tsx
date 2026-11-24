import {useEffect, useMemo, useRef, useState, type ReactNode} from 'react';
import {Check, Download, ExternalLink, X} from 'lucide-react';
import {IconFile, IconRefresh, IconVersions} from './icons';
import {api, post, type ArticleDetail, type Compare, type DiffRow, type Version} from './api';
import {ago, bytes, clock, fullTime, kindLabel} from './format';
import {useData, useHotkeys} from './hooks';
import {columnName, t, tx} from './i18n';
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
  return <div className="diff" role="table" aria-label={t('版本对比', 'Version comparison')}>
    {rows.map((r, i) => r.type === 'fold'
      ? <div key={i} className="diff-fold">… {t(`${r.count} 行未变化`, `${r.count} unchanged lines`)} …</div>
      : <div key={i} className={'diff-row diff-' + r.type} role="row">
        <span className="ln">{r.old_no ?? ''}</span>
        <span className="cell old">{r.old != null ? <Highlighted text={r.old} spans={r.spans?.old}/> : null}</span>
        <span className="ln">{r.new_no ?? ''}</span>
        <span className="cell new">{r.new != null ? <Highlighted text={r.new} spans={r.spans?.new}/> : null}</span>
      </div>)}
  </div>;
}

/** Whether the shown version is still what the official page says, in plain words. */
function VersionStatus({detail, version}: {detail: ArticleDetail; version?: Version}) {
  if (!version) return null;
  const latest = detail.versions[0]?.id === version.id;
  if (!latest) {
    const note = version.note ? t(`（${version.note}）`, ` (${tx(version.note)})`) : '';
    return <span className="version-state muted">{t(`这是 ${fullTime(version.created)} 保存的旧版本`, `Older version saved ${fullTime(version.created)}`)}{note}</span>;
  }
  const imported = version.note.includes('导入');
  const recheckedSince = detail.last_check != null && detail.last_check > version.created + 1;
  if (detail.check_error) {
    return <span className="version-state warn" title={tx(detail.check_error)}>{t(`最近一次复查失败：${detail.check_error}，将自动重试`, `Last re-check failed: ${tx(detail.check_error)}; will retry`)}</span>;
  }
  if (recheckedSince) {
    const title = t(`此版本保存于 ${fullTime(version.created)}${version.note ? `，${version.note}` : ''}`,
      `Saved ${fullTime(version.created)}${version.note ? `; ${tx(version.note)}` : ''}`);
    return <span className="version-state ok" title={title}>
      <Check size={14}/>{t(`已于 ${ago(detail.last_check)}复查，与官网一致`, `Checked ${ago(detail.last_check)}: matches the site`)}</span>;
  }
  if (imported) return <span className="version-state muted">{t('从旧版快照导入，等待首次复查', 'Imported from the previous version; waiting for its first check')}</span>;
  return <span className="version-state muted">{t(`保存于 ${ago(version.created)}`, `Saved ${ago(version.created)}`)}</span>;
}

function versionLabel(v: Version, index: number) {
  return `${clock(v.created)}${index === 0 ? t('（最新）', ' (latest)') : ''}${v.baseline ? t(' 基线', ' · baseline') : t(' 修订', ' · revision')}`;
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
    <aside className="sheet glass" ref={sheet} tabIndex={-1} role="dialog" aria-modal="true" aria-label={t('文章详情', 'Article')}>
      <div className="sheet-top">
        <div className="sheet-tags">{data?.columns.map(c => <ColumnTag key={c.id} column={c}/>)}
          {data?.kind === 'attachment' ? <span className="pill teal">{t('附件文件', 'Attachment')}</span> : null}</div>
        <button className="icon-btn" onClick={onClose} aria-label={t('关闭（Esc）', 'Close (Esc)')}><X size={19}/></button>
      </div>
      {error ? <ErrorNote message={error} onRetry={reload}/> : !data ? <Loading/> : <>
        <h1 className="sheet-title">{data.title}</h1>
        {data.subtitle && data.subtitle !== data.title ? <p className="sheet-sub">{data.subtitle}</p> : null}
        <dl className="sheet-meta">
          <div><dt>{t('原站发布', 'Published')}</dt><dd>{data.published || '—'}</dd></div>
          <div><dt>{t('收录于', 'Collected')}</dt><dd>{fullTime(data.discovered)}</dd></div>
          {data.origin ? <div><dt>{t('文章来源', 'Source')}</dt><dd>{data.origin}</dd></div> : null}
          <div><dt>{t('最近复查', 'Last check')}</dt><dd>{data.last_check ? ago(data.last_check) : t('尚未保存正文', 'Body not saved yet')}{data.check_error ? <em className="err">{t(`（${data.check_error}）`, ` (${tx(data.check_error)})`)}</em> : null}</dd></div>
        </dl>
        {data.parents.length ? <p className="muted small">{t('所属文章：', 'Linked from: ')}{data.parents.map(p => <button key={p.id} className="link" onClick={() => onOpen(p.id)}>{p.title}</button>)}</p> : null}
        <div className="sheet-actions">
          <a className="btn btn-primary" href={data.url} target="_blank" rel="noreferrer"><ExternalLink size={16}/>{t('打开官网原文', 'Open on the site')}</a>
          <Button icon={<IconRefresh size={17}/>} busy={busy === 'check'} onClick={() => run('check', async () => {
            await post(`/articles/${id}/check`); window.setTimeout(reload, 4000);
          }, t('已加入复查，几秒后刷新', 'Queued for re-check; refreshing shortly'))}>{t('立即复查', 'Re-check now')}</Button>
          {data.events.length ? <Button variant="quiet" onClick={() => run('read', async () => {
            await post('/events/read', {articles: [id], read: !!unread});
            setData({...data, events: data.events.map(e => ({...e, read_at: unread ? Date.now() / 1000 : null}))}); onChanged();
          })}>{unread ? t('标为已读', 'Mark as read') : t('标为未读', 'Mark as unread')}</Button> : null}
        </div>

        <Segmented<Tab> label={t('详情内容', 'Details')} value={tab} onChange={setTab} options={[
          {value: 'content', label: data.kind === 'attachment' ? t('文件内容', 'File text') : t('正文', 'Text')},
          {value: 'diff', label: t('修订对比', 'Compare'), count: Math.max(0, data.versions.length - 1)},
          ...(data.kind === 'article' ? [{value: 'files' as Tab, label: t('附件', 'Files'), count: data.attachments.length}] : []),
          {value: 'log', label: t('记录', 'History'), count: data.events.length}]}/>

        {tab === 'content' ? <div className="tab-body">
          {data.versions.length ? <>
            <div className="version-bar">
              <select value={versionId ?? data.versions[0].id} onChange={e => setVersionId(Number(e.target.value))} aria-label={t('选择版本', 'Version')}>
                {data.versions.map((v, i) => <option key={v.id} value={v.id}>{versionLabel(v, i)}</option>)}</select>
              <VersionStatus detail={data} version={data.versions.find(x => x.id === (versionId ?? data.versions[0].id))}/>
              {(() => { const v = data.versions.find(x => x.id === (versionId ?? data.versions[0].id)); return v?.file_digest
                ? <a className="btn btn-plain btn-small" href={`/api/files/${v.file_digest}`}><Download size={14}/>{t('下载此版本文件', 'Download this version')}{v.file_bytes ? t(`（${bytes(v.file_bytes)}）`, ` (${bytes(v.file_bytes)})`) : ''}</a> : null; })()}
            </div>
            <article className="reading">{body.split('\n').map((line, i) => line.startsWith('[图片]')
              ? <p key={i} className="figure-note">{line}</p> : <p key={i}>{line}</p>)}</article>
          </> : <Empty icon={<IconFile size={26}/>} title={t('正文还没有保存', 'Body not saved yet')}>
            {t('发现后会尽快读取正文；可以点“立即复查”。', 'It will be read shortly; you can also click "Re-check now".')}</Empty>}
        </div> : null}

        {tab === 'diff' ? <div className="tab-body">
          {data.versions.length < 2 ? <Empty icon={<IconVersions size={26}/>} title={t('还没有修订', 'No revisions yet')}>
            {t('目前只有基线版本。官网修改正文、标题或附件后，这里会并排显示前后差异。', 'Only the baseline so far. When the site changes the text, title or files, the differences appear here side by side.')}</Empty> : <>
            <div className="version-bar">
              <label>{t('旧版本', 'From')} <select value={base ?? diff?.base ?? ''} onChange={e => setBase(Number(e.target.value))}>
                {data.versions.slice(1).map((v, i) => <option key={v.id} value={v.id}>{versionLabel(v, i + 1)}</option>)}</select></label>
              <label>{t('新版本', 'To')} <select value={target ?? diff?.target ?? ''} onChange={e => setTarget(Number(e.target.value))}>
                {data.versions.map((v, i) => <option key={v.id} value={v.id}>{versionLabel(v, i)}</option>)}</select></label>
              {diff ? <span className="diff-stats"><b className="plus">+{diff.stats.added}</b><b className="minus">−{diff.stats.removed}</b></span> : null}
            </div>
            {diff ? <DiffView rows={diff.rows}/> : <Loading/>}
          </>}
        </div> : null}

        {tab === 'files' ? <div className="tab-body">
          {data.attachments.length ? <div className="file-list">{data.attachments.map(a => <div key={a.id} className="file-row">
            <IconFile size={20}/>
            <button className="file-main" onClick={() => onOpen(a.id)}><b>{a.title}</b>
              <small>{t(`${a.versions} 个版本`, `${a.versions} version(s)`)}{a.bytes ? t(`，${bytes(a.bytes)}`, `, ${bytes(a.bytes)}`) : ''}
                {a.last_check ? t(`，复查于 ${ago(a.last_check)}`, `, checked ${ago(a.last_check)}`) : t('，待下载', ', not downloaded yet')}{a.check_error ? t('，', ', ') + tx(a.check_error) : ''}</small></button>
            {a.file_digest ? <a className="icon-btn" href={`/api/files/${a.file_digest}`} aria-label={t('下载', 'Download')}><Download size={17}/></a> : null}
            <a className="icon-btn" href={a.url} target="_blank" rel="noreferrer" aria-label={t('打开官网文件', 'Open on the site')}><ExternalLink size={16}/></a>
          </div>)}</div> : <Empty icon={<IconFile size={26}/>} title={t('没有附件', 'No files')}>{t('正文中出现附件链接时会自动下载并跟踪变化。', 'Files linked from the article are downloaded and tracked automatically.')}</Empty>}
        </div> : null}

        {tab === 'log' ? <div className="tab-body">
          <h3 className="mini-title">{t('变化记录', 'Changes')}</h3>
          {data.events.length ? <ul className="log-list">{data.events.map(e => <li key={e.id}><KindBadge kind={e.kind}/>
            <span>{e.attachment_title ? `${kindLabel(e.kind)}${t('：', ': ')}${e.attachment_title}` : tx(e.summary) || kindLabel(e.kind)}</span>
            <time>{fullTime(e.created)}</time></li>)}</ul> : <p className="muted small">{t('收录以来没有变化。首次收录只建立基线，不算作变化。', 'No changes since it was collected. The first copy is a baseline, not a change.')}</p>}
          <h3 className="mini-title">{t('出现在官网栏目', 'Listed in site columns')}</h3>
          <ul className="log-list">{data.entries.map(e => <li key={e.source_id + e.position}><span className="pill">{columnName(e.source_id, e.name)}</span>
            <span>{e.page ? t(`第 ${e.page} 页`, `page ${e.page}`) : ''}{e.raw_title && e.raw_title !== data.title ? t(`，列表标题：${e.raw_title}`, `, list title: ${e.raw_title}`) : ''}</span>
            <time>{t(`首次 ${clock(e.first_seen)}，最近 ${clock(e.last_seen)}`, `first ${clock(e.first_seen)}, last ${clock(e.last_seen)}`)}</time></li>)}</ul>
        </div> : null}
      </>}
    </aside>
  </div>;
}
