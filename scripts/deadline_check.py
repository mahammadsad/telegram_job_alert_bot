#!/usr/bin/env python3
from __future__ import annotations
import sys
from datetime import date
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from database.supabase_repository import SupabaseRepository  # noqa:E402
from processing.deadlines import deadline_state  # noqa:E402
def main()->None:
    repo=SupabaseRepository();updated=0
    try:
        rows=repo._request('GET','notices',params={'publication_status':'eq.PUBLISHED','deadline':'not.is.null','select':'id,deadline,deadline_state,subtype'}) or []
        for row in rows:
            state=deadline_state(row['deadline'],today=date.today(),cancelled=row['subtype']=='CANCELLED').value
            if state!=row['deadline_state']:
                priority={'CLOSING_SOON':'HIGH','CANCELLED':'URGENT','EXPIRED':'REJECT'}.get(state,'NORMAL')
                repo._request('PATCH','notices',params={'id':f"eq.{row['id']}"},body={'deadline_state':state,'publication_priority':priority});updated+=1
                if state=='CLOSING_SOON' and not repo._one('review_queue',{'notice_id':f"eq.{row['id']}",'status':'in.(PENDING,APPROVED,RETRY,PROCESSING)'}):
                    repo._request('POST','review_queue',body={'notice_id':row['id'],'review_reason':'DEADLINE_REMINDER_CANDIDATE: deadline is within three days','priority':'HIGH'})
        print(f'Deadline states updated: {updated}')
    finally: repo.close()
if __name__=='__main__':main()
