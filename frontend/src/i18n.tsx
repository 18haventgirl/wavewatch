/* Interface language (中文 / English).
 *
 * Text is written in place as pairs: t('总览', 'Overview').  The chosen language is
 * remembered in this browser; switching re-renders the whole interface.
 * Official article titles and bodies are never translated.
 */
import {createContext, useCallback, useContext, useState, type ReactNode} from 'react';

export type Lang = 'zh' | 'en';
const KEY = 'wavewatch.lang';

function initial(): Lang {
  try {
    const saved = localStorage.getItem(KEY);
    if (saved === 'zh' || saved === 'en') return saved;
  } catch { /* storage unavailable */ }
  return 'zh';
}

let current: Lang = initial();
document.documentElement.lang = current === 'zh' ? 'zh-CN' : 'en';

export const lang = () => current;
export const isEn = () => current === 'en';

/** Pick the text for the current language. */
export function t(zh: string, en: string): string {
  return current === 'en' ? en : zh;
}

/** Locale for dates and numbers. */
export const locale = () => current === 'en' ? 'en-US' : 'zh-CN';

const LangContext = createContext<{lang: Lang; setLang: (l: Lang) => void}>({lang: current, setLang: () => undefined});

export function LangProvider({children}: {children: ReactNode}) {
  const [value, setValue] = useState<Lang>(current);
  const setLang = useCallback((next: Lang) => {
    current = next;
    document.documentElement.lang = next === 'zh' ? 'zh-CN' : 'en';
    try { localStorage.setItem(KEY, next); } catch { /* storage unavailable */ }
    setValue(next);
  }, []);
  // Keyed by language so every component re-renders with the new text.
  return <LangContext.Provider value={{lang: value, setLang}}><div key={value} className="lang-root">{children}</div></LangContext.Provider>;
}

export const useLang = () => useContext(LangContext);

// --- names from the official site ------------------------------------------------------------

const COLUMNS: Record<string, string> = {
  'cn-policy-laws': 'Laws',
  'cn-policy-regulations': 'Administrative Regulations',
  'cn-policy-rules': 'Rules & Normative Documents',
  'cn-news-domestic': 'Domestic News',
  'cn-news-international': 'International News',
};
const GROUPS: Record<string, string> = {'政策法规': 'Policies & Regulations', '资讯动态': 'News'};

export const columnName = (id: string, name: string) => current === 'en' ? COLUMNS[id] || name : name;
export const groupName = (name: string) => current === 'en' ? GROUPS[name] || name : name;

// --- messages produced by the background service ----------------------------------------------

const PHRASES: Record<string, string> = {
  // network and site
  '原站重定向到未核实的地址，已停止': 'The site redirected to an unverified address; stopped',
  '文件超过 25 MB，未下载': 'File larger than 25 MB; not downloaded',
  '重定向次数过多': 'Too many redirects',
  '地址不在已核实的官方站点范围内': 'Address is outside the verified official site',
  '请求失败': 'Request failed',
  '证书校验失败（未关闭安全校验），请检查本机网络或代理': 'Certificate check failed (verification stays on); check this computer\'s network or proxy',
  '连接原站超时，稍后自动重试': 'Connection to the site timed out; will retry automatically',
  '无法连接原站，请检查网络': 'Cannot reach the site; check the network',
  '与原站的连接中断，稍后自动重试': 'Connection to the site was interrupted; will retry automatically',
  '原站返回访问验证页面，未取得列表': 'The site returned a verification page; no list received',
  '栏目接口没有返回有效 JSON': 'The column API did not return valid JSON',
  '栏目接口格式与预期不符，可能已改版': 'The column API format has changed; the site may have been redesigned',
  '原站返回的页码与请求不一致': 'The site returned a different page number than requested',
  '原站返回访问验证页面': 'The site returned a verification page',
  '页面中没有找到文章正文区域，可能已改版或文章已撤下': 'No article body found; the page may have changed or been removed',
  '正文区域为空，暂不作为有效版本保存': 'The article body is empty; not saved as a version',
  '原站列表返回为空，已保留全部历史数据，等待下次复核': 'The site returned an empty list; all history kept, will re-check',
  '附件地址返回的是网页，没有取得文件': 'The attachment link returned a web page instead of a file',
  '程序在检查过程中退出': 'The program stopped during this check',
  // version notes
  '首次保存': 'First saved copy',
  '补存文件，作为新基线': 'File saved as a new baseline',
  '提取规则更新后重建基线，不计为修订': 'Baseline rebuilt after an extraction update; not a revision',
  '文件字节变化；不一定代表政策内容变化': 'File bytes changed; not necessarily a policy change',
  '由旧版本导入': 'Imported from the previous version',
  '由旧监测引擎快照导入': 'Imported from the previous engine\'s snapshot',
  '旧版正文；下次检查按新规则重建基线': 'Previous-version text; rebuilt on the next check',
  // diff summary
  '仅格式变化': 'Formatting only',
  // e-mail
  '邮箱登录被拒绝：请检查账号和授权码（QQ/163 邮箱需使用“授权码”，不是登录密码）': 'Mail login refused: check the account and app password (QQ/163 need the authorization code, not the login password)',
  '收件地址被邮件服务器拒绝，请检查收件人': 'The mail server refused a recipient; check the addresses',
  '发件地址被拒绝，发件人通常需要与登录账号一致': 'Sender refused; it usually has to match the login account',
  '连接邮件服务器超时，请检查服务器地址、端口和网络': 'Mail server timed out; check host, port and network',
  '邮件服务器拒绝连接，请检查服务器地址和端口': 'The mail server refused the connection; check host and port',
  '尚未设置邮件服务器': 'No mail server set',
  '请先填写邮件服务器和收件人': 'Fill in the mail server and recipients first',
  // API
  '栏目不存在': 'Column not found',
  '没有找到这条信息': 'Item not found',
  '没有找到该版本': 'Version not found',
  '没有可比较的更早版本': 'No earlier version to compare',
  '文件不存在': 'File not found',
  '文件尚未保存到本机': 'File not saved on this computer yet',
  '收件人最多 20 个': 'At most 20 recipients',
  '汇总时间格式应为 HH:MM': 'Digest time must be HH:MM',
  '发件地址格式不正确': 'Invalid sender address',
  '开启邮件通知前，请填写邮件服务器和至少一个收件人': 'Fill in the mail server and at least one recipient before turning e-mail on',
  '邮件通知尚未开启或配置不完整': 'E-mail is off or not fully set up',
  '邮件不存在': 'E-mail not found',
  '这封邮件已发送或不存在': 'This e-mail was already sent or does not exist',
  '开机自启只在 Windows 上可用': 'Start at login is only available on Windows',
  '仅允许本机访问': 'Only this computer may connect',
  '请求来源不符': 'Request origin not allowed',
};

const RULES: [RegExp, (...m: string[]) => string][] = [
  [/^原站返回 HTTP (\d+)$/, code => `The site returned HTTP ${code}`],
  [/^(完整核对|快速检查)：读取 (\d+) 页 (\d+) 条，新增 (\d+) 篇$/,
    (mode, p, r, a) => `${mode === '完整核对' ? 'Full sweep' : 'Quick check'}: ${p} page(s), ${r} rows, ${a} new`],
  [/^达到 (\d+) 页上限，更早的条目未读取$/, n => `Reached the ${n}-page limit; older entries not read`],
  [/^原站报告 (\d+) 条，读取到 (\d+) 条$/, (a, b) => `Site reports ${a}, read ${b}`],
  [/^(\d+) 条记录地址异常，已跳过$/, n => `${n} rows had invalid links and were skipped`],
  [/^新增 (\d+) 行，删除 (\d+) 行$/, (a, d) => `${a} line(s) added, ${d} removed`],
  [/^新增 (\d+) 行$/, a => `${a} line(s) added`],
  [/^删除 (\d+) 行$/, d => `${d} line(s) removed`],
  [/^收件地址格式不正确：(.*)$/, list => `Invalid recipient address: ${list}`],
  [/^设置开机自启失败：(.*)$/, why => `Could not set start at login: ${why}`],
  [/^加密连接失败：端口与加密方式可能不匹配（465 用 SSL，587 用 STARTTLS）。(.*)$/,
    why => `Secure connection failed: port and encryption may not match (465 = SSL, 587 = STARTTLS). ${why}`],
];

function one(part: string): string {
  const trimmed = part.trim();
  if (PHRASES[trimmed]) return PHRASES[trimmed];
  for (const [re, fn] of RULES) {
    const m = trimmed.match(re);
    if (m) return fn(...m.slice(1));
  }
  return trimmed;
}

/** Translate a message that came from the service, when English is selected. */
export function tx(message: string | null | undefined): string {
  if (!message) return '';
  if (current !== 'en') return message;
  return message.split('；').map(one).join('; ');
}
