import React, {useRef, useState} from 'react'
import Taro, {useDidShow} from '@tarojs/taro'
import {View, Text, Button, Input} from '@tarojs/components'
import {api, Article, clearToken, loginPage, Preferences, token} from '../api'

type Kind='feed'|'digests'|'messages'|'profile'
const titles={feed:'动态',digests:'每日日报',messages:'消息',profile:'我的'}
const categories=[['','全部'],['cn-domestic-rules','规章及规范性文件'],['cn-domestic-laws','法律'],['cn-domestic-regulations','法规'],['cn-domestic-news','国内动态'],['cn-international-news','国际动态']]
export default function Workspace({kind}:{kind:Kind}) {
  const [items,setItems]=useState<Article[]>([])
  const [total,setTotal]=useState(0)
  const [category,setCategory]=useState('')
  const [query,setQuery]=useState('')
  const [page,setPage]=useState(1)
  const [error,setError]=useState('')
  const [busy,setBusy]=useState(false)
  const [user,setUser]=useState<{name:string;role:string}|null>(null)
  const [prefs,setPrefs]=useState<Preferences|null>(null)
  const sequence=useRef(0)
  async function load(cat=category,search=query,next=1) {
    const request=++sequence.current
    if(!token()) {setItems([]);setUser(null);setPrefs(null);setTotal(0);setBusy(false);setError('登录后查看你的监测信息');return}
    setBusy(true);setError('')
    try {
      if(kind==='feed') {
        const r=await api<{items:Article[];total:number}>('/articles?category='+encodeURIComponent(cat)+'&q='+encodeURIComponent(search)+'&page='+next+'&sort='+(cat?'official':'latest'))
        if(request!==sequence.current)return
        setItems(previous=>next===1?r.items:[...previous,...r.items]);setTotal(r.total);setPage(next)
      } else if(kind==='messages') {
        const r=await api<{items:{article_id:string;title:string;created:number}[];total:number}>('/me/events?page='+next)
        if(request!==sequence.current)return
        const rows=r.items.map(e=>({id:e.article_id,title:e.title,url:'',subtitle:'',published:new Date(e.created*1000).toLocaleString()}))
        setItems(previous=>next===1?rows:[...previous,...rows]);setTotal(r.total);setPage(next)
      } else if(kind==='profile') {
        const [me,preferences]=await Promise.all([api<{name:string;role:string}>('/me'),api<Preferences>('/me/preferences')])
        if(request!==sequence.current)return
        setUser(me);setPrefs(preferences)
      }
    } catch(e) {if(request===sequence.current)setError(e instanceof Error?e.message:'加载失败')}
    finally {if(request===sequence.current)setBusy(false)}
  }
  useDidShow(()=>{void load()})
  async function save() {
    if(!prefs)return
    setBusy(true)
    try {await api('/me/preferences','PUT',prefs);await Taro.showToast({title:'偏好已保存',icon:'success'})}
    catch(e){setError(e instanceof Error?e.message:'保存失败')}
    finally{setBusy(false)}
  }
  async function logout() {
    try {await api('/auth/logout','POST')} catch { /* Local logout also works offline. */ }
    finally {clearToken();setUser(null);setItems([]);void loginPage()}
  }
  return <View className='page'>
    <View className='eyebrow'>GUANLAN · 中国政策观察</View><View className='title'>{titles[kind]}</View>
    {error?<View className='card notice'><Text>{error}</Text><Button className='quiet' onClick={()=>void loginPage()}>微信登录</Button><Button className='quiet' onClick={()=>void load()}>重试</Button></View>:null}
    {kind==='feed'?<>
      <View className='search card'><Input placeholder='搜索标题与官网说明' value={query} onInput={e=>setQuery(e.detail.value)} onConfirm={()=>void load(category,query)} confirmType='search'/><Button className='quiet' onClick={()=>void load(category,query)}>搜索</Button></View>
      <View className='chips'>{categories.map(([id,name])=><Button key={id||'all'} className={'chip '+(category===id?'selected':'')} onClick={()=>{setCategory(id);void load(id,query)}}>{name}</Button>)}</View>
    </>:null}
    {kind==='feed'||kind==='messages'?<>
      <View className='meta'>{busy?'正在读取…':`${total} 条${kind==='messages'?'未读更新':'信息'}`}</View>
      {items.map((item,i)=><View key={item.id+':'+i} className='card article' onClick={()=>void Taro.navigateTo({url:'/pages/article/index?id='+encodeURIComponent(item.id)})}><Text className='flag'>🇨🇳</Text><View className='article-text'><View className='article-title'>{item.title}</View>{item.subtitle?<View className='subtitle'>{item.subtitle}</View>:null}<View className='meta'>{item.published||'原站未提供日期'}</View></View></View>)}
      {!busy&&!error&&!items.length?<View className='card empty'>{kind==='messages'?'暂无未读更新':'暂无符合条件的信息'}</View>:null}
      {items.length<total?<Button className='quiet' disabled={busy} onClick={()=>void load(category,query,page+1)}>加载更多</Button>:null}
    </>:null}
    {kind==='digests'?<View className='card empty'><View className='article-title'>每日汇总，集中查看</View><View className='subtitle'>日报与微信通知模块正在接入。完成后在这里查看真实汇总记录。</View></View>:null}
    {kind==='profile'&&user?<View className='card settings'><View className='article-title'>{user.name}</View><View className='meta'>{user.role==='admin'?'管理员':'指定成员'}</View>{prefs?<><View className='setting-row'><Text>日报时间（北京时间）</Text><Input value={prefs.daily_time} onInput={e=>setPrefs({...prefs,daily_time:e.detail.value})}/></View><View className='subtitle'>当前保存阅读与提醒偏好；微信通知尚未接通。</View><Button className='primary' disabled={busy} onClick={()=>void save()}>保存偏好</Button></>:null}<Button className='quiet' onClick={()=>void logout()}>退出登录</Button></View>:null}
  </View>
}
