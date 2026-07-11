#!/usr/bin/env python3
from __future__ import annotations
import argparse, os, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
def main()->None:
    parser=argparse.ArgumentParser();parser.add_argument('--production',action='store_true');args=parser.parse_args()
    required=['SUPABASE_URL','SUPABASE_SERVICE_ROLE_KEY'] if args.production else []
    missing=[name for name in required if not os.getenv(name,'').strip()]
    if missing: raise SystemExit('Missing required environment variables: '+', '.join(missing))
    if os.getenv('SUPABASE_SERVICE_ROLE_KEY') and os.getenv('VITE_SUPABASE_ANON_KEY')==os.getenv('SUPABASE_SERVICE_ROLE_KEY'):
        raise SystemExit('The Supabase service-role key must never be used as VITE_SUPABASE_ANON_KEY')
    if args.production:
        from database.supabase_repository import SupabaseRepository
        repository=SupabaseRepository()
        try:
            for table in ('sources','notices','pipeline_runs','review_queue','telegram_posts'):
                repository._request('GET',table,params={'select':'id','limit':'1'})
        finally:repository.close()
    print('Environment configuration is valid (secret values not displayed).')
if __name__=='__main__': main()
