import {FormEvent,useEffect,useState} from 'react'
import {supabase} from '../lib/supabase'

export function AdminLogin(){
  const [email,setEmail]=useState('');const [message,setMessage]=useState('')
  async function submit(e:FormEvent){e.preventDefault();const {error}=await supabase.auth.signInWithOtp({email,options:{emailRedirectTo:`${location.origin}/admin`}});setMessage(error?.message||'ইমেলে নিরাপদ লগইন লিঙ্ক পাঠানো হয়েছে।')}
  return <form className="login" onSubmit={submit}><h1>প্রশাসনিক লগইন</h1><label>ইমেল<input type="email" required value={email} onChange={e=>setEmail(e.target.value)}/></label><button>Magic link পাঠান</button><p role="status">{message}</p></form>
}

type Row=Record<string,unknown>

function ReviewPreview({row}:{row:Row}){
  const notice=(row.notices||{}) as Row
  const structured=(row.corrected_structured_data||notice.structured_data||{}) as Row
  const fields=(structured.fields||{}) as Record<string,{value?:unknown}>
  const title=String(structured.title_bn||notice.title_bn||notice.original_title||'শিরোনাম পাওয়া যায়নি')
  const facts=Object.entries(fields).filter(([,value])=>value?.value!=null).slice(0,5)
  return <div className="admin-preview"><p><b>Telegram/Poster preview</b></p><h3>{title}</h3>{facts.map(([name,value])=><p key={name}><b>{name.replaceAll('_',' ')}:</b> {String(value.value)}</p>)}<p>🌍 {String(structured.eligibility_scope||'যোগ্যতা পুনরায় যাচাই প্রয়োজন')}</p><p>🛡️ এটি preview; pipeline যাচাই না করা পর্যন্ত প্রকাশযোগ্য নয়।</p><p>{Boolean(notice.discovery_url)&&<a href={String(notice.discovery_url)} target="_blank" rel="noreferrer">Discovery source</a>} {Boolean(row.corrected_official_url)&&<a href={String(row.corrected_official_url)} target="_blank" rel="noreferrer">Corrected official URL</a>}</p></div>
}

export function AdminDashboard(){
  const [tab,setTab]=useState('review_queue');const [rows,setRows]=useState<Row[]>([])
  async function load(table=tab){const order=table==='sources'?'name':'created_at';const selection=table==='review_queue'?'*,notices(*)':'*';const {data}=await supabase.from(table).select(selection).order(order,{ascending:false}).limit(100);setRows((data||[]) as unknown as Row[])}
  useEffect(()=>{void load()},[tab])
  async function audit(action:string,entityType:string,entityId:unknown,reason:string,changes:unknown={}){
    const {data:{user}}=await supabase.auth.getUser()
    await supabase.from('audit_logs').insert({actor_id:user?.id||null,action,entity_type:entityType,entity_id:String(entityId),reason,changes})
  }

  async function correctAndRetry(row:Row){
    if(!row.notice_id)return
    const official=window.prompt('সঠিক অফিসিয়াল HTTPS URL লিখুন',String(row.corrected_official_url||''));if(!official)return
    const corrected=window.prompt('সংশোধিত structured JSON (ঐচ্ছিক)',row.corrected_structured_data?JSON.stringify(row.corrected_structured_data):'')
    let structured:unknown=null;try{structured=corrected?JSON.parse(corrected):null}catch{alert('JSON সঠিক নয়');return}
    await supabase.from('review_queue').update({corrected_official_url:official,corrected_structured_data:structured,status:'RETRY',updated_at:new Date().toISOString()}).eq('id',row.id)
    await audit('REVIEW_CORRECT_AND_RETRY','review_queue',row.id,'Administrator corrected official URL/data and requested full re-verification',{official})
    await load()
  }
  async function reject(row:Row){const reason=window.prompt('প্রত্যাখ্যানের কারণ লিখুন');if(!reason)return;await supabase.from('review_queue').update({status:'REJECTED',admin_note:reason,resolved_at:new Date().toISOString()}).eq('id',row.id);await audit('REVIEW_REJECT','review_queue',row.id,reason);await load()}
  async function addSource(){
    const name=window.prompt('Source name');const base=window.prompt('Official/base HTTPS URL');if(!name||!base)return
    const parser=(window.prompt('Parser: rss, html, json_api, sitemap','rss')||'rss').toLowerCase()
    let parsed:URL;try{parsed=new URL(base)}catch{alert('সঠিক HTTPS URL দিন');return}
    if(parsed.protocol!=='https:'||parsed.username||parsed.password||parsed.port){alert('শুধু credential/port ছাড়া HTTPS URL গ্রহণযোগ্য');return}
    const domain=parsed.hostname;const slug=name.toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/(^-|-$)/g,'')||`source-${Date.now()}`
    const {data}=await supabase.from('sources').insert({name,slug,source_type:parser==='json_api'?'JSON_API':parser.toUpperCase(),parser_type:parser,base_url:base,feed_url:parser==='rss'?base:null,allowed_domains:[domain],enabled:false,terms_reviewed:false,notes:'Added in admin; review terms, robots and selectors before enabling.'}).select('id').single();await audit('SOURCE_CREATE','source',data?.id||slug,'Created disabled source pending policy review',{name,base,parser});await load()
  }
  async function editSource(row:Row){
    const interval=Number(window.prompt('Minimum interval (minutes)',String(row.min_interval_minutes||120)));if(!Number.isFinite(interval)||interval<0)return
    const item=window.prompt('Verified item selector (blank for RSS/API)',String(row.item_selector||''));const title=window.prompt('Verified title selector/key',String(row.title_selector||''));const link=window.prompt('Verified link selector/key',String(row.link_selector||''))
    const reviewed=window.confirm('robots.txt, terms এবং selectors নিজে যাচাই করেছেন?')
    const changes={min_interval_minutes:interval,item_selector:item||null,title_selector:title||null,link_selector:link||null,terms_reviewed:reviewed,selector_verified_at:reviewed?new Date().toISOString():null,updated_at:new Date().toISOString()}
    await supabase.from('sources').update(changes).eq('id',row.id);await audit('SOURCE_EDIT','source',row.id,'Updated interval/selectors and review state',changes);await load()
  }
  async function toggleSource(row:Row){if(!row.enabled&&!row.terms_reviewed){alert('Enable করার আগে terms/robots review সম্পূর্ণ করুন');return}const enabled=!row.enabled;await supabase.from('sources').update({enabled,updated_at:new Date().toISOString()}).eq('id',row.id);await audit(enabled?'SOURCE_ENABLE':'SOURCE_DISABLE','source',row.id,enabled?'Policy review completed':'Administrator disabled source',{enabled});await load()}
  async function requestCancellationCheck(row:Row){const reason=window.prompt('Official cancellation reason');const official=window.prompt('Official cancellation/corrigendum HTTPS URL');if(!reason||!official)return;const {data:active}=await supabase.from('review_queue').select('id').eq('notice_id',row.id).in('status',['PENDING','APPROVED','RETRY','PROCESSING']).maybeSingle();if(active)await supabase.from('review_queue').update({status:'RETRY',priority:'URGENT',review_reason:`CANCELLATION_RECHECK: ${reason}`,corrected_official_url:official,updated_at:new Date().toISOString()}).eq('id',active.id);else await supabase.from('review_queue').insert({notice_id:row.id,status:'RETRY',priority:'URGENT',review_reason:`CANCELLATION_RECHECK: ${reason}`,corrected_official_url:official});await audit('CANCELLATION_RECHECK','notice',row.id,reason,{official});await load()}
  async function retryDelivery(row:Row){await supabase.from('telegram_posts').update({delivery_state:'PARTIAL_FAILURE',error:'Admin requested safe missing-part retry',updated_at:new Date().toISOString()}).eq('id',row.id);await audit('TELEGRAM_REPAIR_REQUEST','telegram_post',row.id,'Retry only the missing delivery part');await load()}

  return <section><h1>প্রশাসনিক ড্যাশবোর্ড</h1><nav className="tabs">{['review_queue','sources','pipeline_runs','notices','telegram_posts'].map(x=><button className={tab===x?'active':''} key={x} onClick={()=>setTab(x)}>{x.replaceAll('_',' ')}</button>)}</nav><p>অনুমোদন কোনো যাচাই ধাপ এড়িয়ে যায় না; Retry দিলে official source দিয়ে pipeline আবার যাচাই করে।</p>{tab==='sources'&&<button onClick={()=>void addSource()}>নতুন disabled source যোগ করুন</button>}<div className="admin-list">{rows.map(row=><article key={String(row.id)}>{tab==='review_queue'&&<ReviewPreview row={row}/>}<details><summary>Raw record</summary><pre>{JSON.stringify(row,null,2)}</pre></details>{tab==='review_queue'&&<p><button onClick={()=>void correctAndRetry(row)}>URL/data ঠিক করে পুনরায় যাচাই</button> <button onClick={()=>void reject(row)}>কারণসহ প্রত্যাখ্যান</button></p>}{tab==='sources'&&<p><button onClick={()=>void editSource(row)}>interval/selectors edit</button> <button onClick={()=>void toggleSource(row)}>{row.enabled?'Disable':'Enable after review'}</button></p>}{tab==='notices'&&<p><button onClick={()=>void requestCancellationCheck(row)}>official cancellation পুনরায় যাচাই করুন</button></p>}{tab==='telegram_posts'&&row.delivery_state==='PARTIAL_FAILURE'&&<button onClick={()=>void retryDelivery(row)}>missing অংশ retry করুন</button>}</article>)}</div></section>
}
