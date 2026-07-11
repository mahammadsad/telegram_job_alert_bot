import {Link} from 'react-router-dom'
import {deadlineLabel,relevanceLabel} from '../lib/notices'
import type {Notice} from '../types'
export function NoticeCard({notice}: {notice:Notice}){return <article className="notice-card">
  <div className="badges"><span>{notice.category.replaceAll('_',' ')}</span><span className={`state ${notice.deadline_state.toLowerCase()}`}>{deadlineLabel(notice.deadline_state)}</span></div>
  <h2><Link to={`/notice/${notice.id}`}>{notice.title_bn||notice.original_title}</Link></h2>
  <p>{notice.issuing_authority||'অফিসিয়াল সরকারি সংস্থা'}</p>
  <dl><div><dt>🌍 প্রাসঙ্গিকতা</dt><dd>{relevanceLabel(notice.west_bengal_relevance)}</dd></div><div><dt>📅 শেষ তারিখ</dt><dd>{notice.original_deadline_text||notice.deadline||'অফিসিয়াল নোটিশ দেখুন'}</dd></div></dl>
  <small>🛡️ অফিসিয়াল উৎস যাচাই: {notice.verified_at?new Date(notice.verified_at).toLocaleString('bn-IN'):'—'}</small>
</article>}
