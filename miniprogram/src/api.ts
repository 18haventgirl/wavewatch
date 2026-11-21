import Taro from '@tarojs/taro'
export type Article = {id:string; title:string; subtitle:string; published:string|null; url:string}
export type Detail = Article & {versions:{id:number;content:string;created:number}[];attachments:Article[];diff:string[]}
export type Preferences = {source_ids:string[];keywords:string[];daily_time:string;quiet_start:string;quiet_end:string;priority_alerts:boolean}
const key = 'guanlan-session-v1'
export function token():string { return Taro.getStorageSync(key) || '' }
export function setToken(value:string) { Taro.setStorageSync(key,value) }
export function clearToken() { Taro.removeStorageSync(key) }
export function loginPage() { return Taro.navigateTo({url:'/pages/login/index'}) }
export async function api<T>(path:string, method:'GET'|'POST'|'PUT'='GET', data?:unknown):Promise<T> {
  let response:Taro.request.SuccessCallbackResult<{detail?:unknown}>
  try {
    response = await Taro.request({url:API_BASE_URL+'/api/v1'+path,method,data,
      timeout:20000,header:{'Content-Type':'application/json',...(token()?{Authorization:'Bearer '+token()}:{})}})
  } catch { throw new Error('暂时无法连接服务，请检查联调地址和网络') }
  if(response.statusCode===401) clearToken()
  if(response.statusCode>=400) throw new Error(typeof response.data?.detail==='string'?response.data.detail:'请求未完成，请稍后重试')
  return response.data as T
}
