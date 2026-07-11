#!/usr/bin/env python3
from __future__ import annotations
import os,sys
from datetime import datetime,timezone
from pathlib import Path
import requests
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from database.supabase_repository import SupabaseRepository  # noqa:E402


def main()->None:
    if os.getenv("DAILY_DIGEST_ENABLED","false").lower() not in {"1","true","yes","on"}:
        print("Daily digest disabled.");return
    repo=SupabaseRepository();today=datetime.now(timezone.utc).date().isoformat()
    try:
        if repo._one("publication_digests",{"digest_date":f"eq.{today}"}):
            print("Today's digest was already sent.");return
        rows=repo._request("GET","notices",params={"publication_status":"eq.PUBLISHED","verification_status":"eq.VERIFIED_OFFICIAL","publication_priority":"eq.DIGEST_ONLY","updated_at":f"gte.{today}T00:00:00Z","select":"id,title_bn,original_title,category,deadline","order":"updated_at.asc","limit":"15"}) or []
        if not rows:print("No digest-only notices today.");return
        lines=["📚 সরকারি তথ্যকেন্দ্র — আজকের তথ্যসংক্ষেপ",""]
        for index,row in enumerate(rows,1):
            title=row.get("title_bn") or row["original_title"];deadline=f" — শেষ তারিখ {row['deadline']}" if row.get("deadline") else ""
            lines.append(f"{index}. {title}{deadline}")
        website=os.getenv("PUBLIC_WEBSITE_URL","").rstrip("/")
        if website:lines.extend(["",f"সম্পূর্ণ তথ্য: {website}/notices"])
        token=os.getenv("TELEGRAM_BOT_TOKEN","");channel=os.getenv("TELEGRAM_CHANNEL_ID","")
        if not token or not channel:raise RuntimeError("Telegram digest credentials are missing")
        response=requests.post(f"https://api.telegram.org/bot{token}/sendMessage",json={"chat_id":channel,"text":"\n".join(lines),"disable_web_page_preview":True},timeout=30);response.raise_for_status()
        message_id=str(response.json()["result"]["message_id"])
        repo._request("POST","publication_digests",body={"digest_date":today,"notice_ids":[row["id"] for row in rows],"telegram_message_id":message_id,"delivery_state":"FULLY_SENT"})
        print(f"Digest sent with {len(rows)} notices.")
    finally:repo.close()
if __name__=="__main__":main()
