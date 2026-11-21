import React,{useState} from 'react'
import Taro,{useLoad} from '@tarojs/taro'
import {View,Button,Text} from '@tarojs/components'
import {api,Detail} from '../../api'
export default function ArticlePage(){
  const [detail,setDetail]=useState<Detail|null>(null),[error,setError]=useState(''),[diff,setDiff]=useState(false)
  useLoad(params=>{if(!params.id)return;const id=encodeURIComponent(params.id);void api<Detail>('/articles/'+id).then(d=>{setDetail(d);return api('/articles/'+id+'/read','POST')}).catch(e=>setError(e instanceof Error?e.message:'读取失败'))})
  return <View className='page'>{error?<View className='error'>{error}</View>:null}{detail?<><View className='eyebrow'>🇨🇳 官方发布</View><View className='title article-heading'>{detail.title}</View>{detail.subtitle?<View className='subtitle'>{detail.subtitle}</View>:null}<View className='meta'>{detail.published}</View><View className='actions'><Button className='quiet' onClick={()=>void Taro.setClipboardData({data:detail.url})}>复制原文链接</Button><Button className='quiet' onClick={()=>setDiff(!diff)}>{diff?'查看正文':'查看修订差异'}</Button></View><View className='card document'><Text selectable>{diff?(detail.diff.join('\n')||'暂无可比较的修订版本'):(detail.versions[0]?.content||'正文正在采集中')}</Text></View>{detail.attachments.map(a=><View key={a.id} className='card article' onClick={()=>void Taro.navigateTo({url:'/pages/article/index?id='+encodeURIComponent(a.id)})}>{a.title}</View>)}</>:!error?<View className='meta'>正在读取…</View>:null}</View>
}
