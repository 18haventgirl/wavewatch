import {useCallback, useEffect, useState} from 'react';
import {Moon, Sun, SunMoon} from 'lucide-react';
import {api, type Overview as OverviewData, type Source} from './api';
import Article from './Article';
import {APP_NAME, beijingClock} from './format';
import {LangProvider, t, useLang, type Lang} from './i18n';
import {IconColumns, IconLibrary, IconMail, IconOverview, IconRuns, IconUpdates} from './icons';
import {useData, useHotkeys, useNow, useRoute, useStored} from './hooks';
import Library from './pages/Library';
import Notify from './pages/Notify';
import Overview from './pages/Overview';
import Runs from './pages/Runs';
import Sources from './pages/Sources';
import Updates from './pages/Updates';
import {Dot, ToastProvider} from './ui';

const nav = () => [
  {id: 'overview', label: t('总览', 'Overview'), icon: IconOverview},
  {id: 'updates', label: t('动态', 'Updates'), icon: IconUpdates},
  {id: 'library', label: t('文库', 'Library'), icon: IconLibrary},
  {id: 'sources', label: t('栏目', 'Columns'), icon: IconColumns},
  {id: 'notify', label: t('邮件通知', 'E-mail'), icon: IconMail},
  {id: 'runs', label: t('运行记录', 'Activity log'), icon: IconRuns},
];

type Theme = 'auto' | 'light' | 'dark';

function Shell() {
  const {route, go, open, close} = useRoute();
  const {lang, setLang} = useLang();
  const [theme, setTheme] = useStored<Theme>('wavewatch.theme', 'auto');
  const [refreshKey, setRefreshKey] = useState(0);
  const status = useData(s => api<OverviewData>('/overview', {signal: s}), [refreshKey], 8000);
  const [sources, setSources] = useState<Source[]>([]);
  const now = useNow();
  const NAV = nav();
  useEffect(() => { if (status.data) setSources(status.data.sources); }, [status.data]);
  useEffect(() => { document.documentElement.dataset.theme = theme; }, [theme]);
  useEffect(() => {
    const label = NAV.find(n => n.id === route.page)?.label || NAV[0].label;
    const unread = status.data?.stats.unread;
    document.title = `${unread ? `(${unread}) ` : ''}${label} · ${APP_NAME}`;
  }, [route.page, status.data?.stats.unread, lang]);

  const refresh = useCallback(() => { setRefreshKey(k => k + 1); }, []);
  const page = NAV.some(n => n.id === route.page) ? route.page : 'overview';

  useHotkeys({
    '/': () => (document.querySelector('.search input') as HTMLInputElement | null)?.focus(),
    ...Object.fromEntries(NAV.map((n, i) => [String(i + 1), () => go(n.id)])),
  }, !route.article);

  const data = status.data;
  const failing = sources.filter(s => s.enabled && s.state === 'error').length;
  const live = data?.healthy && !failing && sources.some(s => s.enabled);
  const tone = !data ? (status.error ? 'error' : 'idle') : live ? 'live' : data.healthy ? 'warn' : 'error';
  const serviceText = !data ? (status.error ? t('无法连接服务', 'Cannot reach the service') : t('正在连接…', 'Connecting…'))
    : live ? t('实时监测中', 'Monitoring live') : failing ? t(`${failing} 个栏目异常`, `${failing} column(s) failing`)
    : data.healthy ? t('监测已暂停', 'Monitoring paused') : t('后台任务无响应', 'Background tasks not responding');

  return <div className="shell">
    <div className="backdrop" aria-hidden="true"><i/><i/><i/>
      <svg className="horizon" viewBox="0 0 1440 220" preserveAspectRatio="none">
        <path d="M0 120 C 240 80 480 160 720 120 S 1200 80 1440 120 V220 H0Z"/>
        <path d="M0 150 C 260 118 520 182 780 150 S 1260 118 1440 150 V220 H0Z"/>
      </svg></div>
    <aside className="sidebar glass">
      <a className="brand" href="#/overview" aria-label={`${APP_NAME} ${t('总览', 'Overview')}`}>
        <img className="brand-logo" src="/assets/trench-logo.png" alt="Trench Group" width={153} height={21}/>
        <span className="brand-product"><b lang="en">Wavewatch</b>{t('出口管制信息监测', 'Export Controls')}</span>
      </a>
      <nav aria-label={t('主导航', 'Main navigation')}>
        {NAV.map((n, i) => <a key={n.id} href={'#/' + n.id} className={'nav' + (page === n.id ? ' on' : '')} aria-current={page === n.id ? 'page' : undefined}
          title={t(`${n.label}（快捷键 ${i + 1}）`, `${n.label} (shortcut ${i + 1})`)}>
          <n.icon size={20}/><span>{n.label}</span>
          {n.id === 'updates' && data?.stats.unread ? <b className="badge">{data.stats.unread > 99 ? '99+' : data.stats.unread}</b> : null}
          {n.id === 'sources' && failing ? <b className="badge warn">{failing}</b> : null}
          {n.id === 'notify' && data && !data.email.ready ? <b className="badge muted">{t('未开启', 'Off')}</b> : null}
        </a>)}
      </nav>
      <div className="side-foot">
        <div className="service" role="status" title={serviceText} aria-label={serviceText}>
          <Dot tone={tone}/>
          <span className="service-clock">{t('北京时间', 'Beijing')} <b>{beijingClock(now)}</b></span>
        </div>
        <div className="switches">
          <div className="seg-mini" role="radiogroup" aria-label={t('外观', 'Appearance')}>
            {([['auto', SunMoon, t('跟随系统', 'Match system')], ['light', Sun, t('浅色', 'Light')], ['dark', Moon, t('深色', 'Dark')]] as const).map(([value, Icon, label]) =>
              <button key={value} role="radio" aria-checked={theme === value} aria-label={label} title={label}
                className={theme === value ? 'on' : ''} onClick={() => setTheme(value)}><Icon size={15}/></button>)}
          </div>
          <div className="seg-mini lang" role="radiogroup" aria-label={t('界面语言', 'Language')}>
            {([['zh', '中', '中文'], ['en', 'EN', 'English']] as [Lang, string, string][]).map(([value, short, label]) =>
              <button key={value} role="radio" aria-checked={lang === value} aria-label={label} title={label}
                lang={value === 'zh' ? 'zh-CN' : 'en'} className={lang === value ? 'on' : ''} onClick={() => setLang(value)}>{short}</button>)}
          </div>
        </div>
      </div>
    </aside>

    <main className="main">
      {status.error && !data ? <div className="offline glass"><b>{t(`连接不到 ${APP_NAME} 服务`, `Cannot reach ${APP_NAME}`)}</b>
        <span>{t('请确认后台程序正在运行（运行 start.ps1），页面会自动重连。', 'Make sure the service is running (start.ps1); this page reconnects automatically.')}</span></div> : null}
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
  return <LangProvider><ToastProvider><Shell/></ToastProvider></LangProvider>;
}
