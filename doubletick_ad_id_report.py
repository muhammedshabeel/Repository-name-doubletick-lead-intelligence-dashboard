#!/usr/bin/env python3
import argparse, json, os, re, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
import requests

URL = "https://public.doubletick.io/chat-messages"
META_URL = "https://graph.facebook.com"
LOCAL = threading.local()

def digits(value):
    value = re.sub(r"\D", "", str(value or ""))
    return value[2:] if value.startswith("00") else value

def session():
    if not hasattr(LOCAL, "value"):
        LOCAL.value = requests.Session()
        LOCAL.value.headers.update({"Authorization": os.environ["DOUBLETICK_API_KEY"], "Accept":"application/json"})
    return LOCAL.value

def flatten(value, path=""):
    result=[]
    if isinstance(value,dict):
        for key,child in value.items(): result += flatten(child, f"{path}.{key}" if path else str(key))
    elif isinstance(value,list):
        for index,child in enumerate(value): result += flatten(child, f"{path}[{index}]")
    elif value is not None: result.append((path,str(value)))
    return result

def pick(data, keys):
    wanted={key.lower() for key in keys}
    for path,value in flatten(data):
        parts=[x for x in re.split(r"[.\[\]]",path.lower()) if x]
        if parts and parts[-1] in wanted and value.strip(): return value.strip()
    return ""

def extract_messages(data):
    if isinstance(data,list): return data
    if isinstance(data,dict):
        for key in ("messages","data","results","items"):
            value=data.get(key)
            if isinstance(value,list): return value
            if isinstance(value,dict):
                for inner in ("messages","data","results","items"):
                    if isinstance(value.get(inner),list): return value[inner]
    return []

def fetch(phone,waba,start,end):
    last_error=""
    for phone_format in (phone, "+"+phone):
        for attempt in range(4):
            try:
                response=session().get(URL,params={"wabaNumber":waba,"customerNumber":phone_format,"startDate":start,"endDate":end},timeout=60)
                if response.status_code in (429,500,502,503,504): time.sleep(min(2**(attempt+1),20)); continue
                response.raise_for_status()
                messages=extract_messages(response.json() if response.text.strip() else {})
                if messages: return messages, phone_format, ""
                break
            except Exception as exc:
                last_error=str(exc)
                if attempt<3: time.sleep(min(2**(attempt+1),20))
    return [], "", last_error

def is_ad(message):
    explicit=pick(message,["isFromAd","fromAd","isAd"]).lower()
    raw=json.dumps(message,ensure_ascii=False).lower()
    return explicit in ("true","1","yes") or any(x in raw for x in ("source_id","sourceid","ad_id","adid","ctwa_clid","\"referral\"","source_url","thumbnail_url"))

def incoming(message):
    return pick(message,["messageOriginType","originType","direction","senderType"]).lower() in ("customer","incoming","inbound","user")

def timestamp(message):
    try: return float(pick(message,["messageTime","timestamp","createdAt","sentAt"]) or "inf")
    except ValueError: return float("inf")

def origin_ad(messages):
    ads=[m for m in messages if isinstance(m,dict) and is_ad(m)]
    customer_ads=[m for m in ads if incoming(m)]
    candidates=customer_ads or ads
    return min(candidates,key=timestamp) if candidates else None

def process(phone,wabas,start,end):
    errors=[]
    for waba in wabas:
        messages,used_format,error=fetch(phone,waba,start,end)
        if error: errors.append(f"{waba}: {error}")
        if not messages: continue
        ad=origin_ad(messages)
        if not ad:
            return {"phone":phone,"waba_number":waba,"phone_format_used":used_format,"messages_found":len(messages),"ad_id":"","campaign_id":"","adset_id":"","headline":"","source_url":"","ctwa_clid":"","status":"CHAT_FOUND_NO_AD_ID","raw_ad_json":"","error":""}
        ad_id=pick(ad,["source_id","sourceId","ad_id","adId"])
        return {"phone":phone,"waba_number":waba,"phone_format_used":used_format,"messages_found":len(messages),"ad_id":ad_id,"campaign_id":pick(ad,["campaign_id","campaignId"]),"adset_id":pick(ad,["adset_id","adSetId","adsetId"]),"headline":pick(ad,["headline","title","adHeadline"]),"source_url":pick(ad,["source_url","sourceUrl"]),"ctwa_clid":pick(ad,["ctwa_clid","ctwaClid"]),"status":"AD_ID_FOUND" if ad_id else "AD_MESSAGE_FOUND_ID_MISSING","raw_ad_json":json.dumps(ad,ensure_ascii=False,separators=(",",":")),"error":""}
    return {"phone":phone,"waba_number":"","phone_format_used":"","messages_found":0,"ad_id":"","campaign_id":"","adset_id":"","headline":"","source_url":"","ctwa_clid":"","status":"API_ERROR" if errors else "NO_CHAT_FOUND","raw_ad_json":"","error":" | ".join(errors)}

def meta_ad_details(ad_id):
    token=os.getenv("META_ACCESS_TOKEN","").strip()
    empty={"meta_ad_name":"","meta_adset_id":"","meta_adset_name":"","meta_campaign_id":"","meta_campaign_name":"","meta_lookup_status":"SKIPPED_NO_META_TOKEN" if not token else "NOT_LOOKED_UP","meta_error":""}
    if not token or not ad_id: return empty
    try:
        # First get plain scalar IDs from the Ad object. This is more reliable
        # than requesting nested campaign/ad-set objects in one Graph call.
        response=requests.get(f"{META_URL}/{ad_id}",params={"fields":"id,name,account_id,adset_id,campaign_id","access_token":token},timeout=60)
        data=response.json() if response.text.strip() else {}
        if not response.ok:
            empty["meta_lookup_status"]="META_AD_LOOKUP_ERROR"
            empty["meta_error"]=data.get("error",{}).get("message",response.text[:500])
            return empty
        campaign_id=str(data.get("campaign_id","") or "")
        adset_id=str(data.get("adset_id","") or "")
        campaign_name=""; adset_name=""; errors=[]
        if campaign_id:
            r=requests.get(f"{META_URL}/{campaign_id}",params={"fields":"id,name","access_token":token},timeout=60)
            payload=r.json() if r.text.strip() else {}
            if r.ok: campaign_name=payload.get("name","")
            else: errors.append("Campaign: "+payload.get("error",{}).get("message",r.text[:300]))
        if adset_id:
            r=requests.get(f"{META_URL}/{adset_id}",params={"fields":"id,name","access_token":token},timeout=60)
            payload=r.json() if r.text.strip() else {}
            if r.ok: adset_name=payload.get("name","")
            else: errors.append("Ad set: "+payload.get("error",{}).get("message",r.text[:300]))
        status="MATCHED_FROM_META" if campaign_name else ("META_IDS_FOUND_NAMES_MISSING" if campaign_id or adset_id else "META_AD_FOUND_IDS_MISSING")
        return {"meta_ad_name":data.get("name",""),"meta_adset_id":adset_id,"meta_adset_name":adset_name,"meta_campaign_id":campaign_id,"meta_campaign_name":campaign_name,"meta_lookup_status":status,"meta_error":" | ".join(errors)}
    except Exception as exc:
        empty["meta_lookup_status"]="META_API_ERROR"; empty["meta_error"]=str(exc); return empty

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--input",default="phone_numbers.txt")
    parser.add_argument("--start-date",required=True)
    parser.add_argument("--end-date",required=True,help="Inclusive end date in DD-MM-YYYY")
    parser.add_argument("--workers",type=int,default=8)
    parser.add_argument("--output",default="doubletick_ad_id_report.xlsx")
    args=parser.parse_args()
    if not os.getenv("DOUBLETICK_API_KEY"): raise SystemExit("DOUBLETICK_API_KEY is missing.")
    wabas=[digits(x) for x in os.getenv("DOUBLETICK_WABA_NUMBERS","").split(",") if digits(x)]
    if not wabas: raise SystemExit("DOUBLETICK_WABA_NUMBERS is missing.")
    source=Path(args.input)
    if not source.exists(): raise SystemExit(f"Missing file: {args.input}")
    phones=list(dict.fromkeys(digits(x) for x in source.read_text(encoding="utf-8-sig").splitlines() if digits(x)))
    try:
        datetime.strptime(args.start_date,"%d-%m-%Y")
        api_end=(datetime.strptime(args.end_date,"%d-%m-%Y")+timedelta(days=1)).strftime("%d-%m-%Y")
    except ValueError: raise SystemExit("Dates must use DD-MM-YYYY, for example 18-07-2026.")
    print(f"Customers: {len(phones)} | API window: {args.start_date} to {api_end} (your end date is inclusive)")
    rows=[]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures={pool.submit(process,p,wabas,args.start_date,api_end):p for p in phones}
        for count,future in enumerate(as_completed(futures),1):
            row=future.result(); rows.append(row); print(f"[{count}/{len(phones)}] {row['phone']} | {row['status']} | Ad ID: {row['ad_id']}")
    meta_cache={}
    if os.getenv("META_ACCESS_TOKEN","").strip():
        ad_ids=list(dict.fromkeys(str(r.get("ad_id","")).strip() for r in rows if str(r.get("ad_id","")).strip()))
        print(f"Resolving {len(ad_ids)} unique Ad IDs through Meta...")
        with ThreadPoolExecutor(max_workers=8) as pool:
            lookups={pool.submit(meta_ad_details,ad_id):ad_id for ad_id in ad_ids}
            for future in as_completed(lookups): meta_cache[lookups[future]]=future.result()
    for row in rows: row.update(meta_cache.get(str(row.get("ad_id","")).strip(),meta_ad_details("")))
    order={p:i for i,p in enumerate(phones)}; df=pd.DataFrame(rows); df["_order"]=df.phone.map(order); df=df.sort_values("_order").drop(columns="_order")
    with pd.ExcelWriter(args.output,engine="openpyxl") as writer:
        df.to_excel(writer,sheet_name="All_Chats",index=False)
        df[df.ad_id.fillna("").astype(str).str.strip().ne("")].to_excel(writer,sheet_name="Ad_ID_Found",index=False)
        df[df.ad_id.fillna("").astype(str).str.strip().eq("")].to_excel(writer,sheet_name="Ad_ID_Missing",index=False)
        df.groupby("status").phone.nunique().reset_index(name="count").to_excel(writer,sheet_name="Summary",index=False)
        for sheet in writer.sheets.values():
            sheet.freeze_panes="A2"; sheet.auto_filter.ref=sheet.dimensions
            for col in sheet.columns: sheet.column_dimensions[col[0].column_letter].width=min(max(12,max(len(str(c.value or "")) for c in col[:500])+2),55)
    print(f"\nDone: {args.output}")

if __name__ == "__main__": main()
