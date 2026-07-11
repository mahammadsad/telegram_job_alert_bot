import {useEffect,useState} from 'react'
import {Navigate} from 'react-router-dom'
import {supabase} from '../lib/supabase'
import type {Profile} from '../types'
export function AdminGuard({children}:{children:React.ReactNode}){
 const [state,setState]=useState<'loading'|'denied'|'allowed'>('loading')
 useEffect(()=>{void(async()=>{const {data:{user}}=await supabase.auth.getUser();if(!user){setState('denied');return}
 const {data}=await supabase.from('profiles').select('id,email,role').eq('id',user.id).maybeSingle<Profile>();setState(data&&['admin','reviewer'].includes(data.role)?'allowed':'denied')})()},[])
 if(state==='loading')return <p role="status">অ্যাকাউন্ট যাচাই হচ্ছে…</p>
 return state==='allowed'?<>{children}</>:<Navigate to="/admin/login" replace/>
}
