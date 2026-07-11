import type {Filters as FilterType} from '../types'
export const EMPTY_FILTERS:FilterType={query:'',category:'',relevance:'',deadlineState:'',domicile:'',sort:'latest'}
export function Filters({value,onChange}:{value:FilterType;onChange:(value:FilterType)=>void}){
  const set=(key:keyof FilterType)=>(event:React.ChangeEvent<HTMLInputElement|HTMLSelectElement>)=>onChange({...value,[key]:event.target.value})
  return <section className="filters" aria-label="তথ্য ফিল্টার"><input aria-label="খুঁজুন" value={value.query} onChange={set('query')} placeholder="শিরোনাম, বিভাগ বা যোগ্যতা"/>
    <select aria-label="বিভাগ" value={value.category} onChange={set('category')}><option value="">সব বিভাগ</option>{['JOB','SCHOLARSHIP','ADMISSION','EXAMINATION','RESULT','WELFARE_SCHEME','EDUCATION_NOTICE','UNIVERSITY_NOTICE','GOVERNMENT_SERVICE','DOCUMENT_UPDATE','GOVERNMENT_ANNOUNCEMENT'].map(x=><option key={x}>{x}</option>)}</select>
    <select aria-label="প্রাসঙ্গিকতা" value={value.relevance} onChange={set('relevance')}><option value="">পশ্চিমবঙ্গ ও সর্বভারতীয়</option><option value="HIGH">পশ্চিমবঙ্গ/উচ্চ</option><option value="MEDIUM">সর্বভারতীয়/উন্মুক্ত</option></select>
    <select aria-label="ডোমিসাইল" value={value.domicile} onChange={set('domicile')}><option value="">সব domicile শর্ত</option><option value="WEST_BENGAL">পশ্চিমবঙ্গ</option><option value="false">domicile প্রয়োজন নেই</option><option value="true">domicile প্রয়োজন</option></select>
    <select aria-label="সময়সীমা" value={value.deadlineState} onChange={set('deadlineState')}><option value="">সব সময়সীমা</option><option value="OPEN">আবেদন চলছে</option><option value="CLOSING_SOON">শীঘ্রই শেষ</option><option value="EXPIRED">মেয়াদ শেষ</option><option value="CANCELLED">বাতিল</option></select>
    <select aria-label="সাজান" value={value.sort} onChange={set('sort')}><option value="latest">সর্বশেষ</option><option value="deadline">শেষ তারিখ</option></select></section>}
