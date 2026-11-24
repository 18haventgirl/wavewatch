import {useEffect, useState} from 'react';
import {AlertCircle, Layers, Paperclip, Search, X} from 'lucide-react';
import {IconLibrary} from '../icons';
import {api, type ArticleRow, type Page, type Source} from '../api';
import {ago, publishedDate} from '../format';
import {useData, useHotkeys} from '../hooks';
import {columnName, t, tx} from '../i18n';
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
    <header className="page-head"><div><h1>{t('文库', 'Library')}</h1><p>{t('已收录的全部文章，可按栏目、状态和时间查找。', 'Every collected article; filter by column, status and date.')}</p></div></header>

    <div className="toolbar glass">
      <label className="search grow"><Search size={16}/><input value={query} onChange={e => setQuery(e.target.value)}
        placeholder={t('搜索标题、副标题或来源，多个词用空格分隔', 'Search title, subtitle or source; separate words with spaces')} aria-label={t('搜索文章', 'Search articles')}/>
        {query ? <button onClick={() => setQuery('')} aria-label={t('清除', 'Clear')}><X size={14}/></button> : null}</label>
      <select value={scope} onChange={e => setScope(e.target.value)} aria-label={t('栏目', 'Column')}>
        <option value="">{t('全部栏目', 'All columns')}</option>
        <option value="core">{t('政策法规（核心）', 'Policies & regulations (core)')}</option>
        <option value="news">{t('资讯动态', 'News')}</option>
        <optgroup label={t('单个栏目', 'Single column')}>{sources.map(s => <option key={s.id} value={s.id}>{columnName(s.id, s.name)}</option>)}</optgroup>
      </select>
      <select value={sort} onChange={e => setSort(e.target.value)} aria-label={t('排序', 'Sort')}>
        <option value="published">{t('按原站发布时间', 'By publication date')}</option>
        <option value="discovered">{t('按收录时间', 'By date collected')}</option>
        <option value="updated">{t('按最近变化', 'By latest change')}</option>
        {isSource ? <option value="official">{t('按官网列表顺序', 'In site order')}</option> : null}
      </select>
    </div>
    <div className="subbar">
      <Segmented label={t('状态', 'Status')} value={status} onChange={setStatus} options={[
        {value: '', label: t('全部', 'All')}, {value: 'unread', label: t('未读', 'Unread')}, {value: 'changed', label: t('有修订', 'Revised')},
        {value: 'attachments', label: t('含附件', 'With files')}, {value: 'error', label: t('复查失败', 'Check failed')}]}/>
    </div>

    {error ? <ErrorNote message={error} onRetry={reload}/> : null}
    <section className="glass panel" aria-busy={loading}>
      {!data ? <Loading/> : !items.length ? <Empty icon={<IconLibrary size={26}/>} title={t('没有找到文章', 'No articles found')}>
        {t('试试更短的关键词，或切换栏目和状态。', 'Try a shorter keyword, or another column or status.')}</Empty> :
        <div className="doc-list">{items.map((a, i) => <button key={a.id} className={'doc-row' + (i === cursor ? ' cursor' : '') + (a.unread ? ' unread' : '')}
          onClick={() => { setCursor(i); onOpen(a.id); }}>
          <span className="doc-date">{publishedDate(a.published) || t('日期未知', 'No date')}</span>
          <span className="doc-main">
            <span className="doc-title">{a.unread ? <i className="unread-dot" aria-label={t('未读', 'Unread')}/> : null}{a.title}</span>
            {a.subtitle && a.subtitle !== a.title ? <span className="doc-sub">{a.subtitle}</span> : null}
            <span className="doc-meta">
              {a.columns.map(c => <ColumnTag key={c.id} column={c}/>)}
              {a.origin ? <span className="muted">{t('来源：', 'Source: ')}{a.origin}</span> : null}
              {a.changes ? <span className="pill amber"><Layers size={12}/>{t(`${a.changes} 次变化`, `${a.changes} change(s)`)}</span> : null}
              {a.attachments ? <span className="pill teal"><Paperclip size={12}/>{t(`${a.attachments} 个附件`, `${a.attachments} file(s)`)}</span> : null}
              {a.check_error ? <span className="pill red" title={tx(a.check_error)}><AlertCircle size={12}/>{t('复查失败', 'Check failed')}</span> : null}
            </span>
          </span>
          <span className="doc-check muted">{a.last_check ? t(`复查于 ${ago(a.last_check)}`, `Checked ${ago(a.last_check)}`) : t('待首次保存', 'Not saved yet')}</span>
        </button>)}</div>}
      {data ? <Pager page={page} total={data.total} size={data.size} onPage={setPage}/> : null}
    </section>
  </div>;
}
