import {useCallback, useEffect, useState} from 'react';
import {Activity, BellRing, Columns3, LayoutDashboard, Library as LibraryIcon, Mail, Moon, Sun, SunMoon} from 'lucide-react';
import {api, type Overview as OverviewData, type Source} from './api';
import Article from './Article';
import {useData, useHotkeys, useNow, useRoute, useStored} from './hooks';
import Library from './pages/Library';
import Notify from './pages/Notify';
import Overview from './pages/Overview';
import Runs from './pages/Runs';
import Sources from './pages/Sources';
import Updates from './pages/Updates';
import {Dot, ToastProvider} from './ui';

const NAV = [
  {id: 'overview', label: '总览', icon: LayoutDashboard},
  {id: 'updates', label: '动态', icon: BellRing},
  {id: 'library', label: '文库', icon: LibraryIcon},
  {id: 'sources', label: '栏目', icon: Columns3},
  {id: 'notify', label: '邮件通知', icon: Mail},
  {id: 'runs', label: '运行记录', icon: Activity},
];

type Theme = 'auto' | 'light' | 'dark';

function Shell() {
  const {route, go, open, close} = useRoute();
  const [theme, setTheme] = useStored<Theme>('guanlan.theme', 'auto');
  const [refreshKey, setRefreshKey] = useState(0);
  const status = useData(s => api<OverviewData>('/overview', {signal: s}), [refreshKey], 8000);
  const [sources, setSources] = useState<Source[]>([]);
  const now = useNow();
  useEffect(() => { if (status.data) setSources(status.data.sources); }, [status.data]);
  useEffect(() => { document.documentElement.dataset.theme = theme; }, [theme]);
  useEffect(() => {
    const label = NAV.find(n => n.id === route.page)?.label || '总览';
    const unread = status.data?.stats.unread;
    document.title = `${unread ? `(${unread}) ` : ''}${label} · 观澜`;
  }, [route.page, status.data?.stats.unread]);

  const refresh = useCallback(() => { setRefreshKey(k => k + 1); }, []);
  const page = NAV.some(n => n.id === route.page) ? route.page : 'overview';

  useHotkeys({
    '/': () => (document.querySelector('.search input') as HTMLInputElement | null)?.focus(),
    ...Object.fromEntries(NAV.map((n, i) => [String(i + 1), () => go(n.id)])),
  }, !route.article);

  const data = status.data;
  const failing = sources.filter(s => s.enabled && s.state === 'error').length;
  const live = data?.healthy && !failing && sources.some(s => s.enabled);
  const beijing = new Date(now * 1000).toLocaleTimeString('zh-CN', {timeZone: 'Asia/Shanghai', hour12: false});

  return <div className="shell">
    <div className="backdrop" aria-hidden="true"><i/><i/><i/></div>
    <aside className="sidebar glass">
      <a className="brand" href="#/overview">
        <span className="brand-mark" aria-hidden="true"><svg viewBox="0 0 32 32"><path d="M3 19c3.5 0 3.5-3 7-3s3.5 3 7 3 3.5-3 7-3 3.5 3 5 3"/><path d="M3 25c3.5 0 3.5-3 7-3s3.5 3 7 3 3.5-3 7-3 3.5 3 5 3"/><circle cx="16" cy="9" r="3.2"/></svg></span>
        <span>观澜<small>出口管制信息监测</small></span>
      </a>
      <nav aria-label="主导航">
        {NAV.map((n, i) => <a key={n.id} href={'#/' + n.id} className={'nav' + (page === n.id ? ' on' : '')} aria-current={page === n.id ? 'page' : undefined}
          title={`${n.label}（快捷键 ${i + 1}）`}>
          <n.icon size={18}/><span>{n.label}</span>
          {n.id === 'updates' && data?.stats.unread ? <b className="badge">{data.stats.unread > 99 ? '99+' : data.stats.unread}</b> : null}
          {n.id === 'sources' && failing ? <b className="badge warn">{failing}</b> : null}
          {n.id === 'notify' && data && !data.email.ready ? <b className="badge muted">未开启</b> : null}
        </a>)}
      </nav>
      <div className="side-foot">
        <div className={'service' + (live ? ' live' : '')}>
          <Dot tone={!data ? 'idle' : live ? 'live' : data.healthy ? 'warn' : 'error'}/>
          <span>{!data ? (status.error ? '无法连接服务' : '正在连接…') : live ? '实时监测中' : failing ? `${failing} 个栏目异常` : data.healthy ? '监测已暂停' : '后台任务无响应'}
            <small>北京时间 {beijing}</small></span>
        </div>
        <div className="theme-switch" role="radiogroup" aria-label="外观">
          {([['auto', SunMoon, '跟随系统'], ['light', Sun, '浅色'], ['dark', Moon, '深色']] as const).map(([value, Icon, label]) =>
            <button key={value} role="radio" aria-checked={theme === value} aria-label={label} title={label}
              className={theme === value ? 'on' : ''} onClick={() => setTheme(value)}><Icon size={15}/></button>)}
        </div>
      </div>
    </aside>

    <main className="main">
      {status.error && !data ? <div className="offline glass"><b>连接不到观澜服务</b><span>请确认后台程序正在运行（运行 start.ps1），页面会自动重连。</span></div> : null}
      {page === 'overview' ? <Overview onOpen={open} go={go}/> : null}
      {page === 'updates' ? <Updates onOpen={open} sources={sources} refreshKey={refreshKey}/> : null}
      {page === 'library' ? <Library onOpen={open} sources={sources} refreshKey={refreshKey}/> : null}
      {page === 'sources' ? <Sources sources={sources} onChange={s => setSources(list => list.map(x => x.id === s.id ? {...x, ...s} : x))}/> : null}
      {page === 'notify' ? <Notify sources={sources} go={go}/> : null}
      {page === 'runs' ? <Runs sources={sources} onOpen={open} refreshKey={refreshKey}/> : null}
    </main>
    {route.article ? <Article id={route.article} onClose={close} onOpen={open} onChanged={refresh}/> : null}
  </div>;
}

export default function App() {
  return <ToastProvider><Shell/></ToastProvider>;
}
