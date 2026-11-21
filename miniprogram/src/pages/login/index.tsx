import React,{useState} from 'react'
import Taro from '@tarojs/taro'
import {View,Input,Button,Text} from '@tarojs/components'
import {api,setToken} from '../../api'
export default function Login(){
  const [invite,setInvite]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('')
  async function signIn(){
    setBusy(true);setError('')
    try{
      const config=await api<{login_configured:boolean}>('/client-config')
      if(!config.login_configured)throw new Error('服务端尚未配置微信登录，请按联调说明启动服务')
      const {code}=await Taro.login()
      if(!code)throw new Error('未取得微信登录凭证，请重试')
      const session=await api<{token:string}>('/auth/wechat','POST',{code,invitation:invite.trim()})
      setToken(session.token);await Taro.switchTab({url:'/pages/feed/index'})
    }catch(e){setError(e instanceof Error?e.message:'登录未完成')}
    finally{setBusy(false)}
  }
  return <View className='page login'><View className='mark'>观</View><View className='title'>观澜</View><View className='subtitle'>官方政策信息，随时掌握</View><View className='card settings'><Text className='article-title'>微信登录</Text><Input className='invite' placeholder='首次使用填写一次性邀请码' value={invite} onInput={e=>setInvite(e.detail.value)}/>{error?<View className='error'>{error}</View>:null}<Button className='primary' loading={busy} disabled={busy} onClick={()=>void signIn()}>登录并进入</Button><View className='meta'>仅限受邀成员使用</View></View></View>
}
