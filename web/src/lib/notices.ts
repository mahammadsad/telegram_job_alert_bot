import type {Filters,Notice} from '../types'
export const isPublicNotice=(notice:Notice)=>notice.publication_status==='PUBLISHED'&&['VERIFIED_OFFICIAL','POSTED'].includes(notice.verification_status)
export const relevanceLabel=(value:string)=>({HIGH:'পশ্চিমবঙ্গের জন্য গুরুত্বপূর্ণ',MEDIUM:'আবেদনযোগ্য',LOW:'সীমিত প্রাসঙ্গিকতা',REJECT:'প্রযোজ্য নয়'}[value]||value)
export const deadlineLabel=(value:string)=>({OPEN:'আবেদন চলছে',CLOSING_SOON:'শীঘ্রই শেষ',EXPIRED:'মেয়াদ শেষ',CANCELLED:'বাতিল',UNKNOWN:'তারিখ দেখুন'}[value]||value)
export function filterNotices(input:Notice[],filters:Filters){
  const q=filters.query.trim().toLocaleLowerCase('bn')
  return input.filter(isPublicNotice).filter(n=>!q||[n.title_bn,n.original_title,n.issuing_authority,JSON.stringify(n.structured_data)].some(v=>String(v||'').toLocaleLowerCase('bn').includes(q)))
    .filter(n=>!filters.category||n.category===filters.category)
    .filter(n=>!filters.relevance||n.west_bengal_relevance===filters.relevance)
    .filter(n=>!filters.deadlineState||n.deadline_state===filters.deadlineState)
    .filter(n=>!filters.domicile||JSON.stringify(n.structured_data||{}).includes(filters.domicile))
    .sort((a,b)=>filters.sort==='deadline'?String(a.deadline||'9999').localeCompare(String(b.deadline||'9999')):String(b.posted_at||b.verified_at).localeCompare(String(a.posted_at||a.verified_at)))
}
