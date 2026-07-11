export type Notice = {
  id:number; category:string; subtype:string; original_title:string; title_bn:string|null; title_en:string|null;
  issuing_authority:string|null; official_page_url:string|null; official_document_url:string|null;
  final_resolved_url:string|null; deadline:string|null; original_deadline_text:string|null;
  deadline_state:'OPEN'|'CLOSING_SOON'|'EXPIRED'|'CANCELLED'|'UNKNOWN';
  eligibility_status:string|null; west_bengal_relevance:'HIGH'|'MEDIUM'|'LOW'|'REJECT';
  relevance_reason:string|null; publication_status:string; verification_status:string;
  publication_priority:string; structured_data:Record<string,unknown>|null; verified_at:string|null; posted_at:string|null;
}
export type Filters={query:string;category:string;relevance:string;deadlineState:string;domicile:string;sort:'latest'|'deadline'}
export type Profile={id:string;email:string|null;role:'viewer'|'reviewer'|'admin'}
