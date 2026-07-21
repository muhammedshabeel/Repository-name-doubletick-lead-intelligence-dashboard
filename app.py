import io
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

import pandas as pd
import requests
import streamlit as st
from requests.adapters import HTTPAdapter

DOUBLETICK_URL = "https://public.doubletick.io/chat-messages"
META_URL = "https://graph.facebook.com"
LOCAL = threading.local()
TRANSIENT_CODES = {429, 500, 502, 503, 504}

PRODUCT_VENDOR = {
    "OUD LOVERS": "LPG", "INTENSE SIGNATURE": "LPG", "ARBE PURO COMBO": "LPG",
    "CHERIE BLOSSOM": "LPG", "VELORA POP HEART": "LPG", "VELORA SUGAR BLISS": "LPG",
    "VELORA VIVA CHOCO": "LPG", "ASTORIA": "LPG", "JENAN": "LPG", "NAJAH PISTACHIO": "LPG",
    "LEON": "LPG", "OPUS": "LPG", "ENIGMA": "LPG", "RANIA": "LPG",
    "AL HUDA": "OUD AL SALAM", "PREMIUM EDITION": "OUD AL SALAM", "ABSOLUTE MOUNTAIN AVENUE": "OUD AL SALAM",
    "SEVEN DAY": "RT", "OLD MEMORIES": "RT",
    "ARCHER COMBO": "ATYAF", "HECTOR": "ATYAF", "MIRAMAR": "ATYAF", "ASEEL COMBO": "ATYAF",
    "SHADOW FLAME": "ATYAF", "VOLGA COMBO": "ATYAF", "COLLECTION OF MOOD": "ATYAF",
    "DOE COLLECTION": "SCENT PASSION", "ESENCIA FLORAL COLLECTION": "SCENT PASSION",
    "CLIVE COLLECTION": "SCENT PASSION", "AMEERAT AL ARAB": "SCENT PASSION",
}

ALIASES = {
    "ARBE PURO COMBO": ["ARBE PURO", "ARBEPURO"],
    "AL HUDA": ["ALHUDA", "AL-HUDA", "HUDA"],
    "PREMIUM EDITION": ["PREMIUM"],
    "ABSOLUTE MOUNTAIN AVENUE": ["ABSOLUTE MOUNTAIN", "MOUNTAIN AVENUE"],
    "SEVEN DAY": ["SEVEN DAYS", "7 DAYS", "7 DAY"],
    "ARCHER COMBO": ["ARCHER"], "ASEEL COMBO": ["ASEEL"], "VOLGA COMBO": ["VOLGA"],
    "DOE COLLECTION": ["DOE"], "ESENCIA FLORAL COLLECTION": ["ESENCIA"],
    "CLIVE COLLECTION": ["CLIVE"], "AMEERAT AL ARAB": ["AMEERAT"],
}

COUNTRY_ALIASES = {
    "UAE": ["UAE", "DUBAI", "ABU DHABI", "EMIRATES"],
    "QATAR": ["QATAR", "DOHA", "QAR"],
    "KSA": ["KSA", "SAUDI", "RIYADH", "JEDDAH", "SAR"],
    "BAHRAIN": ["BAHRAIN", "MANAMA", "BHD"],
}

AGENT_PHONE_NAME = {
    "919847941618": "Moinudeen",
    "918590170256": "SHAMNA NAJIYA",
    "917736348315": "NIHAD",
    "919567347417": "JAHID",
    "918156901941": "ADNAN",
    "918606068725": "COMPLAINT",
    "918590227968": "Reshmi Emarath",
    "918089262612": "Ansar Emarath",
    "919995033387": "EMARATH GLOBAL",
    "918606827458": "ANSHAD EMARATH",
    "917306124502": "FATHIMA LIYA",
    "919526016837": "SHIBIL",
    "917907978372": "NAFIH",
    "917510767713": "Hasna",
    "918593978664": "RANJITH",
    "917356565921": "RAHIYAD",
    "916238427287": "SHIHAD",
    "918714661951": "ADWAITHA T M",
    "918891890464": "NEHA P",
}


def digits(value):
    value = re.sub(r"\D", "", str(value or ""))
    return value[2:] if value.startswith("00") else value


def norm(value):
    return re.sub(r"[^A-Z0-9]+", " ", str(value or "").upper()).strip()


def get_session(api_key):
    key = f"dt_{hash(api_key)}"
    if not hasattr(LOCAL, key):
        s = requests.Session()
        adapter = HTTPAdapter(pool_connections=50, pool_maxsize=50, max_retries=0)
        s.mount("https://", adapter)
        s.headers.update({"Authorization": api_key, "Accept": "application/json"})
        setattr(LOCAL, key, s)
    return getattr(LOCAL, key)


def flatten(value, path=""):
    out = []
    if isinstance(value, dict):
        for key, item in value.items():
            out.extend(flatten(item, f"{path}.{key}" if path else str(key)))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            out.extend(flatten(item, f"{path}[{index}]"))
    elif value is not None:
        out.append((path, str(value)))
    return out


def pick(data, keys):
    wanted = {key.lower() for key in keys}
    for path, value in flatten(data):
        parts = [x for x in re.split(r"[.\[\]]", path.lower()) if x]
        if parts and parts[-1] in wanted and value.strip():
            return value.strip()
    return ""


def extract_messages(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("messages", "data", "results", "items"):
            value = data.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, dict):
                for inner in ("messages", "data", "results", "items"):
                    if isinstance(value.get(inner), list):
                        return value[inner]
    return []


def fetch_messages(phone, waba, start, end, api_key):
    last_error = ""
    formats = [phone, f"+{phone}"]
    for phone_format in formats:
        for attempt in range(2):
            try:
                response = get_session(api_key).get(
                    DOUBLETICK_URL,
                    params={
                        "wabaNumber": waba,
                        "customerNumber": phone_format,
                        "startDate": start,
                        "endDate": end,
                    },
                    timeout=(5, 20),
                )
                if response.status_code in TRANSIENT_CODES:
                    last_error = f"HTTP {response.status_code}"
                    if attempt == 0:
                        time.sleep(1.0)
                        continue
                response.raise_for_status()
                messages = extract_messages(response.json() if response.text.strip() else {})
                if messages:
                    return messages, phone_format, ""
                break
            except requests.RequestException as exc:
                last_error = str(exc)
                if attempt == 0:
                    time.sleep(0.75)
    return [], "", last_error


def is_ad_message(message):
    explicit = pick(message, ["isFromAd", "fromAd", "isAd"]).lower()
    raw = json.dumps(message, ensure_ascii=False).lower()
    return explicit in {"true", "1", "yes"} or any(
        key in raw for key in ("source_id", "sourceid", "ad_id", "adid", "ctwa_clid", '"referral"', "source_url")
    )


def is_incoming(message):
    return pick(message, ["messageOriginType", "originType", "direction", "senderType"]).lower() in {
        "customer", "incoming", "inbound", "user"
    }


def message_timestamp(message):
    raw = pick(message, ["messageTime", "timestamp", "createdAt", "sentAt"])
    try:
        return float(raw)
    except (TypeError, ValueError):
        return float("inf")


def origin_ad(messages):
    ads = [item for item in messages if isinstance(item, dict) and is_ad_message(item)]
    incoming = [item for item in ads if is_incoming(item)]
    return min(incoming or ads, key=message_timestamp) if ads else None


def process_unique_phone(phone, wabas, start, end, api_key):
    errors = []
    for waba in wabas:
        messages, used_format, error = fetch_messages(phone, waba, start, end, api_key)
        if error:
            errors.append(f"{waba}: {error}")
        if not messages:
            continue
        ad = origin_ad(messages)
        base = {
            "customer_phone": phone,
            "waba_number": waba,
            "phone_format_used": used_format,
            "messages_found": len(messages),
            "ad_id": "", "campaign_id": "", "adset_id": "", "headline": "",
            "source_url": "", "ctwa_clid": "", "raw_ad_json": "", "error": "",
        }
        if not ad:
            base["status"] = "CHAT_FOUND_NO_AD_ID"
            return base
        base.update({
            "ad_id": pick(ad, ["source_id", "sourceId", "ad_id", "adId"]),
            "campaign_id": pick(ad, ["campaign_id", "campaignId"]),
            "adset_id": pick(ad, ["adset_id", "adSetId", "adsetId"]),
            "headline": pick(ad, ["headline", "title", "adHeadline"]),
            "source_url": pick(ad, ["source_url", "sourceUrl"]),
            "ctwa_clid": pick(ad, ["ctwa_clid", "ctwaClid"]),
            "raw_ad_json": json.dumps(ad, ensure_ascii=False, separators=(",", ":")),
        })
        base["status"] = "AD_ID_FOUND" if base["ad_id"] else "AD_MESSAGE_FOUND_ID_MISSING"
        return base
    return {
        "customer_phone": phone, "waba_number": "", "phone_format_used": "", "messages_found": 0,
        "ad_id": "", "campaign_id": "", "adset_id": "", "headline": "", "source_url": "",
        "ctwa_clid": "", "status": "API_ERROR" if errors else "NO_CHAT_FOUND", "raw_ad_json": "",
        "error": " | ".join(errors),
    }


def meta_ad_details(ad_id, token):
    empty = {
        "meta_ad_name": "", "meta_adset_id": "", "meta_adset_name": "",
        "meta_campaign_id": "", "meta_campaign_name": "",
        "meta_lookup_status": "SKIPPED_NO_META_TOKEN" if not token else "NOT_LOOKED_UP",
        "meta_error": "",
    }
    if not token or not ad_id:
        return empty
    try:
        response = requests.get(
            f"{META_URL}/{ad_id}",
            params={
                "fields": "id,name,adset{id,name},campaign{id,name}",
                "access_token": token,
            },
            timeout=(5, 20),
        )
        payload = response.json() if response.text.strip() else {}
        if not response.ok:
            empty["meta_lookup_status"] = "META_AD_LOOKUP_ERROR"
            empty["meta_error"] = payload.get("error", {}).get("message", response.text[:500])
            return empty
        campaign = payload.get("campaign") or {}
        adset = payload.get("adset") or {}
        return {
            "meta_ad_name": payload.get("name", ""),
            "meta_adset_id": str(adset.get("id", "") or ""),
            "meta_adset_name": adset.get("name", ""),
            "meta_campaign_id": str(campaign.get("id", "") or ""),
            "meta_campaign_name": campaign.get("name", ""),
            "meta_lookup_status": "MATCHED_FROM_META" if campaign.get("name") else "META_NAMES_MISSING",
            "meta_error": "",
        }
    except requests.RequestException as exc:
        empty["meta_lookup_status"] = "META_API_ERROR"
        empty["meta_error"] = str(exc)
        return empty


def read_table(upload):
    if upload.name.lower().endswith((".xlsx", ".xls")):
        return pd.read_excel(upload)
    return pd.read_csv(upload, encoding_errors="ignore")


def detect_column(df, candidates):
    normalized = {norm(column): column for column in df.columns}
    for candidate in candidates:
        if norm(candidate) in normalized:
            return normalized[norm(candidate)]
    for column in df.columns:
        if any(norm(candidate) in norm(column) for candidate in candidates):
            return column
    return None


def infer_product(text):
    cleaned = norm(text)
    for product in sorted(PRODUCT_VENDOR, key=len, reverse=True):
        if any(norm(term) in cleaned for term in [product] + ALIASES.get(product, [])):
            return product
    return "UNMATCHED"


def infer_country(text):
    cleaned = norm(text)
    for country, terms in COUNTRY_ALIASES.items():
        if any(norm(term) in cleaned for term in terms):
            return country
    return "UAE"


def build_excel(df, run_summary):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame(run_summary.items(), columns=["metric", "value"]).to_excel(writer, sheet_name="Run_Summary", index=False)
        df.to_excel(writer, sheet_name="Detailed_Report", index=False)
        df.groupby(["country", "vendor"], dropna=False).size().reset_index(name="lead_rows").to_excel(writer, sheet_name="Country_Vendor", index=False)
        df.groupby(["vendor", "product"], dropna=False).size().reset_index(name="lead_rows").to_excel(writer, sheet_name="Vendor_Product", index=False)
        df.groupby(["assigned_agent_name", "assigned_agent_phone"], dropna=False).size().reset_index(name="assigned_rows").to_excel(writer, sheet_name="Agent_Assignment", index=False)
        df.groupby("status", dropna=False).size().reset_index(name="lead_rows").to_excel(writer, sheet_name="API_Status", index=False)
        for sheet in writer.sheets.values():
            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions
            for column in sheet.columns:
                width = max(len(str(cell.value or "")) for cell in column[:500]) + 2
                sheet.column_dimensions[column[0].column_letter].width = min(max(12, width), 55)
    return output.getvalue()


def secret_or_env(name, default=""):
    try:
        return st.secrets[name]
    except Exception:
        return os.getenv(name, default)


st.set_page_config(page_title="DoubleTick Lead Intelligence", page_icon="📊", layout="wide")
st.title("DoubleTick Lead Intelligence")
st.caption("Every uploaded row is preserved. API calls are made once per unique customer phone.")

with st.sidebar:
    st.header("API settings")
    api_key = st.text_input("DoubleTick API key", value=secret_or_env("DOUBLETICK_API_KEY"), type="password")
    waba_text = st.text_input("WABA number(s)", value=secret_or_env("DOUBLETICK_WABA_NUMBERS", "971521367907"))
    meta_token = st.text_input("Meta access token", value=secret_or_env("META_ACCESS_TOKEN"), type="password")
    start_date = st.date_input("Attribution start date", value=date.today() - timedelta(days=1))
    end_date = st.date_input("Attribution end date (inclusive)", value=date.today())
    workers = st.slider("Parallel workers", 4, 32, 20)

customer_file = st.file_uploader("Upload DoubleTick customer report", type=["xlsx", "xls", "csv"])
st.info(f"Agent names are built into the app and matched by assigned-agent phone. {len(AGENT_PHONE_NAME)} agents are configured.")

if st.button("Generate report", type="primary", use_container_width=True):
    if not customer_file:
        st.error("Upload the DoubleTick customer report.")
        st.stop()
    if not api_key:
        st.error("DoubleTick API key is required.")
        st.stop()
    if end_date < start_date:
        st.error("End date cannot be before start date.")
        st.stop()

    source_df = read_table(customer_file)
    uploaded_rows = len(source_df)
    customer_phone_col = detect_column(source_df, ["customer phone", "customer number", "phone number", "mobile", "phone"])
    assigned_phone_col = detect_column(source_df, ["assigned user number", "assigned agent phone", "agent phone", "assigned phone", "team member phone"])
    missing = [name for name, column in (("customer phone", customer_phone_col), ("assigned agent phone", assigned_phone_col)) if not column]
    if missing:
        st.error("Could not detect: " + ", ".join(missing))
        st.write("Available columns:", list(source_df.columns))
        st.stop()

    working = source_df.copy().reset_index(drop=False).rename(columns={"index": "source_row_index"})
    working["customer_phone"] = working[customer_phone_col].map(digits)
    working["assigned_agent_phone"] = working[assigned_phone_col].map(digits)
    working["assigned_agent_name"] = working["assigned_agent_phone"].map(AGENT_PHONE_NAME).fillna("UNMATCHED AGENT")

    valid_mask = working["customer_phone"].ne("")
    valid_rows = int(valid_mask.sum())
    invalid_rows = uploaded_rows - valid_rows
    unique_phones = working.loc[valid_mask, "customer_phone"].drop_duplicates().tolist()
    duplicate_rows = valid_rows - len(unique_phones)

    wabas = [digits(item) for item in waba_text.split(",") if digits(item)]
    if not wabas:
        st.error("Enter at least one valid WABA number.")
        st.stop()

    api_start = start_date.strftime("%d-%m-%Y")
    api_end = (end_date + timedelta(days=1)).strftime("%d-%m-%Y")
    progress = st.progress(0, text=f"Fetching 0 of {len(unique_phones):,} unique phones...")
    unique_results = []

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(process_unique_phone, phone, wabas, api_start, api_end, api_key): phone for phone in unique_phones}
        for completed, future in enumerate(as_completed(futures), 1):
            unique_results.append(future.result())
            progress.progress(completed / max(len(unique_phones), 1), text=f"Fetched {completed:,} of {len(unique_phones):,} unique phones")

    result = pd.DataFrame(unique_results)
    ad_ids = result.get("ad_id", pd.Series(dtype=str)).fillna("").astype(str).str.strip().drop_duplicates().tolist()
    ad_ids = [ad_id for ad_id in ad_ids if ad_id]
    meta_cache = {}

    if meta_token and ad_ids:
        progress.progress(0, text=f"Resolving 0 of {len(ad_ids):,} unique Meta ads...")
        with ThreadPoolExecutor(max_workers=min(workers, 16)) as pool:
            futures = {pool.submit(meta_ad_details, ad_id, meta_token): ad_id for ad_id in ad_ids}
            for completed, future in enumerate(as_completed(futures), 1):
                meta_cache[futures[future]] = future.result()
                progress.progress(completed / len(ad_ids), text=f"Resolved {completed:,} of {len(ad_ids):,} unique Meta ads")

    empty_meta = meta_ad_details("", meta_token)
    for column in empty_meta:
        result[column] = result["ad_id"].astype(str).map(lambda ad_id, col=column: meta_cache.get(ad_id, empty_meta).get(col, ""))

    final = working.merge(result, on="customer_phone", how="left")
    final.loc[~valid_mask, "status"] = "INVALID_CUSTOMER_PHONE"
    campaign_text = final["meta_campaign_name"].fillna("")
    final["product"] = campaign_text.map(infer_product)
    final["vendor"] = final["product"].map(PRODUCT_VENDOR).fillna("UNMATCHED")
    final["country"] = campaign_text.map(infer_country)
    final["agent_match_status"] = final["assigned_agent_name"].eq("UNMATCHED AGENT").map({True: "UNMATCHED", False: "MATCHED BY PHONE"})

    chats_found_unique = int(result["messages_found"].fillna(0).gt(0).sum())
    ad_found_unique = int(result["ad_id"].fillna("").astype(str).str.strip().ne("").sum())
    chats_found_rows = int(final["messages_found"].fillna(0).gt(0).sum())
    ad_found_rows = int(final["ad_id"].fillna("").astype(str).str.strip().ne("").sum())

    run_summary = {
        "Uploaded rows": uploaded_rows,
        "Rows with valid customer phone": valid_rows,
        "Invalid phone rows": invalid_rows,
        "Unique customer phones fetched": len(unique_phones),
        "Duplicate lead rows preserved": duplicate_rows,
        "Unique phones with chat found": chats_found_unique,
        "Lead rows with chat found": chats_found_rows,
        "Unique phones with ad ID": ad_found_unique,
        "Lead rows with ad ID": ad_found_rows,
    }
    st.session_state["report_df"] = final
    st.session_state["run_summary"] = run_summary
    progress.empty()
    st.success(f"Completed. Preserved all {uploaded_rows:,} uploaded rows and fetched {len(unique_phones):,} unique phones once each.")

if "report_df" in st.session_state:
    df = st.session_state["report_df"]
    summary = st.session_state["run_summary"]

    st.subheader("Run reconciliation")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Uploaded lead rows", f"{summary['Uploaded rows']:,}")
    c2.metric("Unique phones fetched", f"{summary['Unique customer phones fetched']:,}")
    c3.metric("Duplicate rows preserved", f"{summary['Duplicate lead rows preserved']:,}")
    c4.metric("Lead rows with ad ID", f"{summary['Lead rows with ad ID']:,}")
    st.caption("Uploaded lead rows = unique phones fetched + duplicate rows preserved + invalid-phone rows. Unique phone counts must not be compared directly with total lead rows.")

    tabs = st.tabs(["Overview", "Country & vendor", "Products", "Agents", "Detailed report", "Data quality"])
    with tabs[0]:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Rows with chat found", f"{summary['Lead rows with chat found']:,}")
        m2.metric("Unique chats found", f"{summary['Unique phones with chat found']:,}")
        m3.metric("Matched products", f"{df['product'].ne('UNMATCHED').sum():,}")
        m4.metric("Matched agent rows", f"{df['assigned_agent_name'].ne('UNMATCHED AGENT').sum():,}")
        left, right = st.columns(2)
        with left:
            st.bar_chart(df.groupby("country").size().sort_values(ascending=False))
        with right:
            st.bar_chart(df.groupby("vendor").size().sort_values(ascending=False))
    with tabs[1]:
        st.dataframe(df.groupby(["country", "vendor"]).size().reset_index(name="lead_rows").sort_values("lead_rows", ascending=False), use_container_width=True, hide_index=True)
    with tabs[2]:
        st.dataframe(df.groupby(["vendor", "product"]).size().reset_index(name="lead_rows").sort_values("lead_rows", ascending=False), use_container_width=True, hide_index=True)
    with tabs[3]:
        st.dataframe(df.groupby(["assigned_agent_name", "assigned_agent_phone"]).size().reset_index(name="assigned_rows").sort_values("assigned_rows", ascending=False), use_container_width=True, hide_index=True)
    with tabs[4]:
        st.dataframe(df, use_container_width=True, hide_index=True, height=620)
    with tabs[5]:
        q1, q2, q3, q4 = st.columns(4)
        q1.metric("Invalid phone rows", int(df["status"].eq("INVALID_CUSTOMER_PHONE").sum()))
        q2.metric("No-chat rows", int(df["status"].eq("NO_CHAT_FOUND").sum()))
        q3.metric("API-error rows", int(df["status"].eq("API_ERROR").sum()))
        q4.metric("Unmatched product rows", int(df["product"].eq("UNMATCHED").sum()))
        st.dataframe(df[df["product"].eq("UNMATCHED")][["source_row_index", "customer_phone", "status", "meta_campaign_name", "meta_adset_name", "meta_ad_name", "headline"]], use_container_width=True, hide_index=True)

    excel = build_excel(df, summary)
    st.download_button(
        "Download complete Excel report",
        excel,
        "doubletick_lead_intelligence_report.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
        use_container_width=True,
    )
