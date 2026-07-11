#!/usr/bin/env python3
from __future__ import annotations
import os,sys
from datetime import datetime,timezone
from pathlib import Path
import requests
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from database.supabase_repository import SupabaseRepository  # noqa:E402
def count(repo:SupabaseRepository,table:str,params:dict[str,str])->int:
    response=repo.session.get(f'{repo.url}/rest/v1/{table}',headers={**repo.headers,'Prefer':'count=exact'},params={**params,'select':'id','limit':'1'},timeout=20);response.raise_for_status();return int(response.headers.get('content-range','0/0').split('/')[-1].replace('*','0'))
def main()->None:
    repo=SupabaseRepository();today=datetime.now(timezone.utc).date().isoformat()
    try:
        runs=repo._request('GET','pipeline_runs',params={'started_at':f'gte.{today}T00:00:00Z','select':'sources_checked,items_discovered,items_verified,items_posted,items_rejected,items_queued,duplicates'}) or []
        total=lambda field:sum(int(row.get(field) or 0) for row in runs)
        usage=repo._request('GET','provider_usage',params={'usage_date':f'eq.{today}','select':'calls'}) or []
        successful=count(repo,'source_checks',{'status':'eq.SUCCESS','checked_at':f'gte.{today}'})
        failed=count(repo,'source_checks',{'status':'eq.FAILED','checked_at':f'gte.{today}'})
        lines=['সরকারি তথ্যকেন্দ্র — দৈনিক স্বাস্থ্য রিপোর্ট',f'তারিখ: {today}',
          f"Source checked: {successful+failed}",f"সফল source check: {successful}",f"ব্যর্থ source check: {failed}",
          f"Notices discovered: {total('items_discovered')}",f"Verified: {total('items_verified')}",
          f"Posted: {total('items_posted')}",f"Duplicates skipped: {total('duplicates')}",
          f"Rejected: {total('items_rejected')}",f"Queued this day: {total('items_queued')}",
          f"Review-তে অপেক্ষমাণ: {count(repo,'review_queue',{'status':'eq.PENDING'})}",
          f"AI calls today: {sum(int(row.get('calls') or 0) for row in usage)}",
          f"Telegram ব্যর্থতা: {count(repo,'telegram_posts',{'delivery_state':'in.(FAILED,PARTIAL_FAILURE)'})}"]
        message='\n'.join(lines);print(message)
        token=os.getenv('TELEGRAM_BOT_TOKEN','');chat=os.getenv('TELEGRAM_REVIEW_CHAT_ID','')
        if token and chat: requests.post(f'https://api.telegram.org/bot{token}/sendMessage',json={'chat_id':chat,'text':message},timeout=20).raise_for_status()
    finally: repo.close()
if __name__=='__main__':main()
