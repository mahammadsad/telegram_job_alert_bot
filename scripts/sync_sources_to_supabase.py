#!/usr/bin/env python3
from __future__ import annotations
import re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from config.loader import load_sources  # noqa:E402
from database.supabase_repository import SupabaseRepository  # noqa:E402
def slugify(value:str)->str:return re.sub(r"[^a-z0-9]+","-",value.lower()).strip("-")
def main()->None:
    repo=SupabaseRepository();count=0
    try:
        for source in load_sources():
            parser=str(source.get("parser_type","manual")).lower()
            payload={"name":source["name"],"slug":slugify(source["name"]),"source_type":{"rss":"RSS","html":"HTML","json_api":"JSON_API","sitemap":"SITEMAP"}.get(parser,"MANUAL"),"parser_type":parser,"base_url":source["url"],"feed_url":source["url"] if parser=="rss" else None,"official":bool(source.get("official")),"discovery_only":bool(source.get("discovery_only",True)),"enabled":bool(source.get("enabled",False)),"categories":source.get("categories",[]),"allowed_domains":source.get("allowed_domains",[]),"allowed_document_domains":source.get("allowed_document_domains",[]),"item_selector":source.get("item_selector"),"title_selector":source.get("title_selector"),"link_selector":source.get("link_selector"),"min_interval_minutes":source.get("min_interval_minutes",120),"request_timeout":source.get("request_timeout",20),"max_items":source.get("max_items",20),"terms_reviewed":bool(source.get("terms_reviewed",False)),"notes":source.get("notes") or source.get("parser_note")}
            repo._request("POST","sources",params={"on_conflict":"slug"},body=payload,prefer="resolution=merge-duplicates");count+=1
        print(f"Source registry rows synchronized: {count}")
    finally:repo.close()
if __name__=="__main__":main()
