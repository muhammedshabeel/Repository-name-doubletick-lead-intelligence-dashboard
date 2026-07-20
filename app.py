import io, json, os, re, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

URL = "https://public.doubletick.io/chat-messages"
META_URL = "https://graph.facebook.com"
LOCAL = threading.local()

PRODUCT_VENDOR = {
    "OUD LOVERS":"LPG", "INTENSE SIGNATURE":"LPG", "ARBE PURO COMBO":"LPG",
    "CHERIE BLOSSOM":"LPG", "VELORA POP HEART":"LPG", "VELORA SUGAR BLISS":"LPG",
    "VELORA VIVA CHOCO":"LPG", "ASTORIA":"LPG", "JENAN":"LPG", "NAJAH PISTACHIO":"LPG",
    "LEON":"LPG", "OPUS":"LPG", "ENIGMA":"LPG", "RANIA":"LPG",
    "PREMIUM EDITION":"OUD AL SALAM", "ABSOLUTE MOUNTAIN AVENUE":"OUD AL SALAM",
    "SEVEN DAY":"RT", "OLD MEMORIES":"RT",
    "ARCHER COMBO":"ATYAF", "HECTOR":"ATYAF", "MIRAMAR":"ATYAF", "ASEEL COMBO":"ATYAF",
    "SHADOW FLAME":"ATYAF", "VOLGA COMBO":"ATYAF", "COLLECTION OF MOOD":"ATYAF",
    "DOE COLLECTION":"SCENT PASSION", "ESENCIA FLORAL COLLECTION":"SCENT PASSION",
    "CLIVE COLLECTION":"SCENT PASSION", "AMEERAT AL ARAB":"SCENT PASSION",
}
ALIASES = {
    "ARBE PURO COMBO":["ARBE PURO", "ARBEPURO"],
    "PREMIUM EDITION":["PREMIUM"],
    "ABSOLUTE MOUNTAIN AVENUE":["ABSOLUTE MOUNTAIN", "MOUNTAIN AVENUE"],
    "SEVEN DAY":["SEVEN DAYS", "7 DAYS", "7 DAY"],
    "ARCHER COMBO":["ARCHER"], "ASEEL COMBO":["ASEEL"], "VOLGA COMBO":["VOLGA"],
    "DOE COLLECTION":["DOE"], "ESENCIA FLORAL COLLECTION":["ESENCIA"],
    "CLIVE COLLECTION":["CLIVE"], "AMEERAT AL ARAB":["AMEERAT"],
}
COUNTRY_ALIASES = {
    "UAE":["UAE", "DUBAI", "ABU DHABI", "EMIRATES"],
    "QATAR":["QATAR", "DOHA", "QAR"],
    "KSA":["KSA", "SAUDI", "RIYADH", "JEDDAH", "SAR"],
    "BAHRAIN":["BAHRAIN", "MANAMA", "BHD"],
}

def digits(value):
    value = re.sub(r"\D", "", str(value or ""))
    return value[2:] if value.startswith("00") else value

def norm(value):
    return re.sub(r"[^A-Z0-9]+", " ", str(value or "").upper()).strip()

def session(api_key):
    key = f"session_{hash(api_key)}"
    if not hasattr(LOCAL, key):
        s = requests.Session(); s.headers.update({"Authorization": api_key, "Accept":"application/json"})
        setattr(LOCAL, key, s)
    return getattr(LOCAL, key)

def flatten(value, path=""):
    out=[]
    if isinstance(value,dict):
        for k,v in value.items(): out += flatten(v, f"{path}.{k}" if path else str(k))
    elif isinstance(value,list):
        for i,v in enumerate(value): out += flatten(v, f"{path}[{i}]")
    elif value is not None: out.append((path,str(value)))
    return out

def pick(data, keys):
    wanted={k.lower() for k in keys}
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

def fetch(phone,waba,start,end,api_key):
    last_error=""
    for phone_format in (phone, "+"+phone):
        for attempt in range(4):
            try:
                r=session(api_key).get(URL,params={"wabaNumber":waba,"customerNumber":phone_format,"startDate":start,"endDate":end},timeout=60)
                if r.status_code in (429,500,502,503,504): time.sleep(min(2**(attempt+1),20)); continue
                r.raise_for_status(); messages=extract_messages(r.json() if r.text.strip() else {})
                if messages: return messages,phone_format,""
                break
            except Exception as exc:
                last_error=str(exc)
                if attempt<3: time.sleep(min(2**(attempt+1),20)
                )
    return [],"",last_error

def is_ad(message):
    explicit=pick(message,["isFromAd","fromAd","isAd"]).lower(); raw=json.dumps(message,ensure_ascii=False).lower()
    return explicit in ("true","1","yes") or any(x in raw for x in ("source_id","sourceid","ad_id","adid","ctwa_clid","\"referral\"","source_url","thumbnail_url"))

def incoming(message):
    return pick(message,["messageOriginType","originType","direction","senderType"]).lower() in ("customer","incoming","inbound","user")

def timestamp(message):
    try: return float(pick(message,["messageTime","timestamp","createdAt","sentAt"]) or "inf")
    except ValueError: return float("inf")

def origin_ad(messages):
    ads=[m for m in messages if isinstance(m,dict) and is_ad(m)]; incoming_ads=[m for m in ads if incoming(m)]
    return min(incoming_ads or ads,key=timestamp) if ads else None

def process(phone,wabas,start,end,api_key):
    errors=[]
    for waba in wabas:
        messages,used,error=fetch(phone,waba,start,end,api_key)
        if error: errors.append(f"{waba}: {error}")
        if not messages: continue
        ad=origin_ad(messages)
        if not ad: return {"customer_phone":phone,"waba_number":waba,"phone_format_used":used,"messages_found":len(messages),"ad_id":"","campaign_id":"","adset_id":"","headline":"","source_url":"","ctwa_clid":"","status":"CHAT_FOUND_NO_AD_ID","raw_ad_json":"","error":""}
        ad_id=pick(ad,["source_id","sourceId","ad_id","adId"])
        return {"customer_phone":phone,"waba_number":waba,"phone_format_used":used,"messages_found":len(messages),"ad_id":ad_id,"campaign_id":pick(ad,["campaign_id","campaignId"]),"adset_id":pick(ad,["adset_id","adSetId","adsetId"]),"headline":pick(ad,["headline","title","adHeadline"]),"source_url":pick(ad,["source_url","sourceUrl"]),"ctwa_clid":pick(ad,["ctwa_clid","ctwaClid"]),"status":"AD_ID_FOUND" if ad_id else "AD_MESSAGE_FOUND_ID_MISSING","raw_ad_json":json.dumps(ad,ensure_ascii=False,separators=(",",":")),"error":""}
    return {"customer_phone":phone,"waba_number":"","phone_format_used":"","messages_found":0,"ad_id":"","campaign_id":"","adset_id":"","headline":"","source_url":"","ctwa_clid":"","status":"API_ERROR" if errors else "NO_CHAT_FOUND","raw_ad_json":"","error":" | ".join(errors)}

def meta_ad_details(ad_id,token):
    empty={"meta_ad_name":"","meta_adset_id":"","meta_adset_name":"","meta_campaign_id":"","meta_campaign_name":"","meta_lookup_status":"SKIPPED_NO_META_TOKEN" if not token else "NOT_LOOKED_UP","meta_error":""}
    if not token or not ad_id: return empty
    try:
        r=requests.get(f"{META_URL}/{ad_id}",params={"fields":"id,name,account_id,adset_id,campaign_id","access_token":token},timeout=60); data=r.json() if r.text.strip() else {}
        if not r.ok:
            empty["meta_lookup_status"]="META_AD_LOOKUP_ERROR"; empty["meta_error"]=data.get("error",{}).get("message",r.text[:500]); return empty
        campaign_id=str(data.get("campaign_id","") or ""); adset_id=str(data.get("adset_id","") or "")
        campaign_name=""; adset_name=""; errors=[]
        for obj_id,key,label in ((campaign_id,"campaign_name","Campaign"),(adset_id,"adset_name","Ad set")):
            if obj_id:
                rr=requests.get(f"{META_URL}/{obj_id}",params={"fields":"id,name","access_token":token},timeout=60); payload=rr.json() if rr.text.strip() else {}
                if rr.ok:
                    if key=="campaign_name": campaign_name=payload.get("name","")
                    else: adset_name=payload.get("name","")
                else: errors.append(label+": "+payload.get("error",{}).get("message",rr.text[:300]))
        return {"meta_ad_name":data.get("name",""),"meta_adset_id":adset_id,"meta_adset_name":adset_name,"meta_campaign_id":campaign_id,"meta_campaign_name":campaign_name,"meta_lookup_status":"MATCHED_FROM_META" if campaign_name else "META_IDS_FOUND_NAMES_MISSING","meta_error":" | ".join(errors)}
    except Exception as exc:
        empty["meta_lookup_status"]="META_API_ERROR"; empty["meta_error"]=str(exc); return empty

def read_table(upload):
    name=upload.name.lower()
    if name.endswith((".xlsx",".xls")): return pd.read_excel(upload)
    return pd.read_csv(upload,encoding_errors="ignore")

def detect_column(df, candidates):
    normalized={norm(c):c for c in df.columns}
    for candidate in candidates:
        nc=norm(candidate)
        if nc in normalized: return normalized[nc]
    for c in df.columns:
        nc=norm(c)
        if any(norm(x) in nc for x in candidates): return c
    return None

def infer_product(text):
    t=norm(text)
    for product in sorted(PRODUCT_VENDOR,key=len,reverse=True):
        terms=[product]+ALIASES.get(product,[])
        if any(norm(term) in t for term in terms): return product
    return "UNMATCHED"

def infer_country(text, phone=""):
    t=norm(text)
    for country,terms in COUNTRY_ALIASES.items():
        if any(norm(term) in t for term in terms): return country
    p=digits(phone)
    if p.startswith("971"): return "UAE"
    if p.startswith("974"): return "QATAR"
    if p.startswith("966"): return "KSA"
    if p.startswith("973"): return "BAHRAIN"
    return "UNMATCHED"

def build_excel(df):
    out=io.BytesIO()
    with pd.ExcelWriter(out,engine="openpyxl") as writer:
        df.to_excel(writer,sheet_name="Detailed_Report",index=False)
        df.groupby(["country","vendor"],dropna=False).size().reset_index(name="leads").to_excel(writer,sheet_name="Country_Vendor",index=False)
        df.groupby(["vendor","product"],dropna=False).size().reset_index(name="leads").to_excel(writer,sheet_name="Vendor_Product",index=False)
        df.groupby(["assigned_agent_name","assigned_agent_phone"],dropna=False).size().reset_index(name="assigned_leads").to_excel(writer,sheet_name="Agent_Assignment",index=False)
        df.groupby("status",dropna=False).size().reset_index(name="count").to_excel(writer,sheet_name="API_Status",index=False)
        for ws in writer.sheets.values():
            ws.freeze_panes="A2"; ws.auto_filter.ref=ws.dimensions
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width=min(max(12,max(len(str(c.value or "")) for c in col[:500])+2),55)
    return out.getvalue()

def secret_or_env(name, default=""):
    try:
        return st.secrets[name]
    except Exception:
        return os.getenv(name, default)

st.set_page_config(page_title="DoubleTick Lead Intelligence",page_icon="📊",layout="wide")
st.title("DoubleTick Lead Intelligence")
st.caption("Phone-first agent matching. DoubleTick ad attribution. Country, vendor, product and agent reporting.")

with st.sidebar:
    st.header("API settings")
    api_key=st.text_input("DoubleTick API key",value=secret_or_env("DOUBLETICK_API_KEY"),type="password")
    waba_text=st.text_input("WABA number(s)",value=secret_or_env("DOUBLETICK_WABA_NUMBERS","971521367907"))
    meta_token=st.text_input("Meta access token",value=secret_or_env("META_ACCESS_TOKEN"),type="password")
    start_date=st.date_input("Start date",value=date.today()-timedelta(days=1))
    end_date=st.date_input("End date",value=date.today())
    workers=st.slider("Parallel workers",2,20,8)

c1,c2=st.columns(2)
with c1:
    customer_file=st.file_uploader("1. Upload DoubleTick customer report",type=["xlsx","xls","csv"])
with c2:
    agent_file=st.file_uploader("2. Upload agent phone-name mapping",type=["xlsx","xls","csv"])

st.info("The app ignores the unreliable agent-name field. It reads the assigned agent phone from the customer report, then maps that number to the correct name from the uploaded agent mapping file.")

if st.button("Generate report",type="primary",use_container_width=True):
    if not customer_file or not agent_file: st.error("Upload both files."); st.stop()
    if not api_key: st.error("DoubleTick API key is required."); st.stop()
    if end_date < start_date: st.error("End date cannot be before start date."); st.stop()
    customer_df=read_table(customer_file); agent_df=read_table(agent_file)
    customer_phone_col=detect_column(customer_df,["customer phone","customer number","phone number","mobile","phone"])
    assigned_phone_col=detect_column(customer_df,["assigned user number","assigned agent phone","agent phone","assigned phone","team member phone"])
    agent_phone_col=detect_column(agent_df,["agent phone","phone number","mobile","phone"])
    agent_name_col=detect_column(agent_df,["agent name","name","employee name","user name"])
    missing=[name for name,col in (("customer phone",customer_phone_col),("assigned agent phone",assigned_phone_col),("agent mapping phone",agent_phone_col),("agent mapping name",agent_name_col)) if not col]
    if missing:
        st.error("Could not detect: "+", ".join(missing)+". Rename those columns clearly and retry."); st.write("Customer columns:",list(customer_df.columns)); st.write("Agent columns:",list(agent_df.columns)); st.stop()
    customer_df=customer_df.copy(); customer_df["customer_phone"]=customer_df[customer_phone_col].map(digits); customer_df["assigned_agent_phone"]=customer_df[assigned_phone_col].map(digits)
    customer_df=customer_df[customer_df["customer_phone"].ne("")].drop_duplicates("customer_phone",keep="first")
    agent_map={digits(p):str(n).strip() for p,n in zip(agent_df[agent_phone_col],agent_df[agent_name_col]) if digits(p)}
    customer_df["assigned_agent_name"]=customer_df["assigned_agent_phone"].map(agent_map).fillna("UNMATCHED AGENT")
    phones=customer_df["customer_phone"].tolist(); wabas=[digits(x) for x in waba_text.split(",") if digits(x)]
    api_start=start_date.strftime("%d-%m-%Y"); api_end=(end_date+timedelta(days=1)).strftime("%d-%m-%Y")
    progress=st.progress(0,text="Fetching DoubleTick chats..."); rows=[]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures={pool.submit(process,p,wabas,api_start,api_end,api_key):p for p in phones}
        for i,future in enumerate(as_completed(futures),1):
            rows.append(future.result()); progress.progress(i/len(phones),text=f"Fetched {i:,} of {len(phones):,}")
    result=pd.DataFrame(rows)
    meta_cache={}; ad_ids=list(dict.fromkeys(result.get("ad_id",pd.Series(dtype=str)).fillna("").astype(str).str.strip()))
    ad_ids=[x for x in ad_ids if x]
    if meta_token and ad_ids:
        progress.progress(0,text="Resolving Meta campaign names...")
        with ThreadPoolExecutor(max_workers=min(8,workers)) as pool:
            futures={pool.submit(meta_ad_details,a,meta_token):a for a in ad_ids}
            for i,future in enumerate(as_completed(futures),1):
                meta_cache[futures[future]]=future.result(); progress.progress(i/len(ad_ids),text=f"Resolved {i:,} of {len(ad_ids):,} ads")
    for col in ["meta_ad_name","meta_adset_id","meta_adset_name","meta_campaign_id","meta_campaign_name","meta_lookup_status","meta_error"]:
        result[col]=result["ad_id"].astype(str).map(lambda x:meta_cache.get(x,meta_ad_details("",meta_token)).get(col,""))
    final=customer_df.merge(result,on="customer_phone",how="left")
    source_text=final[["meta_campaign_name","meta_adset_name","meta_ad_name","headline"]].fillna("").agg(" | ".join,axis=1)
    final["product"]=source_text.map(infer_product); final["vendor"]=final["product"].map(PRODUCT_VENDOR).fillna("UNMATCHED")
    final["country"]=[infer_country(text,phone) for text,phone in zip(source_text,final["customer_phone"])]
    final["agent_match_status"]=final["assigned_agent_name"].eq("UNMATCHED AGENT").map({True:"UNMATCHED",False:"MATCHED BY PHONE"})
    st.session_state["report_df"]=final
    progress.empty(); st.success(f"Report generated for {len(final):,} unique customers.")

if "report_df" in st.session_state:
    df=st.session_state["report_df"]
    m1,m2,m3,m4=st.columns(4)
    m1.metric("Total leads",f"{len(df):,}"); m2.metric("Ad IDs found",f"{df['ad_id'].fillna('').astype(str).str.strip().ne('').sum():,}")
    m3.metric("Matched products",f"{df['product'].ne('UNMATCHED').sum():,}"); m4.metric("Matched agents",f"{df['assigned_agent_name'].ne('UNMATCHED AGENT').sum():,}")
    tabs=st.tabs(["Overview","Country & vendor","Products","Agents","Detailed report","Data quality"])
    with tabs[0]:
        st.subheader("Lead distribution")
        a,b=st.columns(2)
        with a: st.bar_chart(df.groupby("country").size().sort_values(ascending=False))
        with b: st.bar_chart(df.groupby("vendor").size().sort_values(ascending=False))
    with tabs[1]: st.dataframe(df.groupby(["country","vendor"]).size().reset_index(name="leads").sort_values("leads",ascending=False),use_container_width=True,hide_index=True)
    with tabs[2]: st.dataframe(df.groupby(["vendor","product"]).size().reset_index(name="leads").sort_values("leads",ascending=False),use_container_width=True,hide_index=True)
    with tabs[3]: st.dataframe(df.groupby(["assigned_agent_name","assigned_agent_phone"]).size().reset_index(name="assigned_leads").sort_values("assigned_leads",ascending=False),use_container_width=True,hide_index=True)
    with tabs[4]: st.dataframe(df,use_container_width=True,hide_index=True,height=620)
    with tabs[5]:
        q1,q2,q3=st.columns(3); q1.metric("Unmatched products",int(df["product"].eq("UNMATCHED").sum())); q2.metric("Unmatched agents",int(df["assigned_agent_name"].eq("UNMATCHED AGENT").sum())); q3.metric("API errors",int(df["status"].eq("API_ERROR").sum()))
        st.dataframe(df[df["product"].eq("UNMATCHED")][["customer_phone","meta_campaign_name","meta_adset_name","meta_ad_name","headline"]],use_container_width=True,hide_index=True)
    excel=build_excel(df)
    st.download_button("Download complete Excel report",excel,"doubletick_lead_intelligence_report.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",type="primary",use_container_width=True)
