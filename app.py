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

AGENT_PHONE_NAME = {
    "919847941618": "Moinudeen",
    "918590170256": "SHAMNA NAJIYA",
    "917736348315": "NIHAD",
    "919567347417": "JAHID",
    "918156901941": "ADNAN",
    "918606068725": "COMPLAINT",
    "918590227968": "RESHMI",
    "918089262612": "ANSAR",
    "919995033387": "EMARATH GLOBAL",
    "918606827458": "ANSHAD",
    "917306124502": "FATHIMA LIYA",
    "919526016837": "SHIBIL",
    "917907978372": "NAFIH",
    "917510767713": "HASNA",
    "918593978664": "RANJITH",
    "917356565921": "RAHIYAD",
    "916238427287": "SHIHAD",
    "918714661951": "ADWAITHA T M",
    "918891890464": "NEHA P",
}

PRODUCT_VENDOR = {
    "OUD LOVERS": "LPG",
    "INTENSE SIGNATURE": "LPG",
    "ARBE PURO COMBO": "LPG",
    "CHERIE BLOSSOM": "LPG",
    "VELORA POP HEART": "LPG",
    "VELORA SUGAR BLISS": "LPG",
    "VELORA VIVA CHOCO": "LPG",
    "ASTORIA": "LPG",
    "JENAN": "LPG",
    "NAJAH PISTACHIO": "LPG",
    "LEON": "LPG",
    "OPUS": "LPG",
    "ENIGMA": "LPG",
    "RANIA": "LPG",
    "PREMIUM EDITION": "OUD AL SALAM",
    "ABSOLUTE MOUNTAIN AVENUE": "OUD AL SALAM",
    "AL HUDA": "OUD AL SALAM",
    "LUMINUX": "OUD AL SALAM",
    "SEVEN DAY": "RT",
    "OLD MEMORIES": "RT",
    "ARCHER COMBO": "ATYAF",
    "HECTOR": "ATYAF",
    "MIRAMAR": "ATYAF",
    "ASEEL COMBO": "ATYAF",
    "SHADOW FLAME": "ATYAF",
    "VOLGA COMBO": "ATYAF",
    "COLLECTION OF MOOD": "ATYAF",
    "DOE COLLECTION": "SCENT PASSION",
    "ESENCIA FLORAL COLLECTION": "SCENT PASSION",
    "CLIVE COLLECTION": "SCENT PASSION",
    "AMEERAT AL ARAB": "SCENT PASSION",
}

PRODUCT_ALIASES = {
    "OUD LOVERS": ["OUDLOVERS", "OUD LOVER", "OUD LOVERS"],
    "INTENSE SIGNATURE": ["INTENSE SIGNATURE"],
    "ARBE PURO COMBO": ["ARBE PURO", "ARBEPURO"],
    "PREMIUM EDITION": ["PREMIUM EDITION", "PREMIUM"],
    "ABSOLUTE MOUNTAIN AVENUE": ["ABSOLUTE MOUNTAIN AVENUE", "ABSOLUTE MOUNTAIN", "MOUNTAIN AVENUE"],
    "AL HUDA": ["AL HUDA", "ALHUDA", "AL-HUDA"],
    "LUMINUX": ["LUMINUX"],
    "SEVEN DAY": ["SEVEN DAY", "SEVEN DAYS", "7 DAY", "7 DAYS"],
    "OLD MEMORIES": ["OLD MEMORIES"],
    "ARCHER COMBO": ["ARCHER COMBO", "ARCHER"],
    "HECTOR": ["HECTOR"],
    "MIRAMAR": ["MIRAMAR"],
    "ASEEL COMBO": ["ASEEL COMBO", "ASEEL"],
    "SHADOW FLAME": ["SHADOW FLAME"],
    "VOLGA COMBO": ["VOLGA COMBO", "VOLGA"],
    "COLLECTION OF MOOD": ["COLLECTION OF MOOD"],
    "DOE COLLECTION": ["DOE COLLECTION", "DOE"],
    "ESENCIA FLORAL COLLECTION": ["ESENCIA FLORAL COLLECTION", "ESENCIA"],
    "CLIVE COLLECTION": ["CLIVE COLLECTION", "CLIVE"],
    "AMEERAT AL ARAB": ["AMEERAT AL ARAB", "AMEERAT", "AMEERATH"],
}
for product in PRODUCT_VENDOR:
    PRODUCT_ALIASES.setdefault(product, [product])

COUNTRY_ALIASES = {
    "UAE": ["UAE", "DUBAI", "ABU DHABI", "EMIRATES", "UAETEAM"],
    "QATAR": ["QATAR", "DOHA", "QAR"],
    "KSA": ["KSA", "SAUDI", "RIYADH", "JEDDAH", "SAR"],
    "BAHRAIN": ["BAHRAIN", "MANAMA", "BHD"],
}


def digits(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].replace(".", "", 1).isdigit():
        text = text[:-2]
    value = re.sub(r"\D", "", text)
    return value[2:] if value.startswith("00") else value


def norm(value):
    return re.sub(r"[^A-Z0-9]+", " ", str(value or "").upper()).strip()


def http_session(api_key=""):
    key = f"session_{hash(api_key)}"
    if not hasattr(LOCAL, key):
        s = requests.Session()
        adapter = HTTPAdapter(pool_connections=50, pool_maxsize=50, max_retries=0)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        headers = {"Accept": "application/json", "User-Agent": "DoubleTickLeadDashboard/2.0"}
        if api_key:
            headers["Authorization"] = api_key
        s.headers.update(headers)
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
        parts = [part for part in re.split(r"[.\[\]]", path.lower()) if part]
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
                    nested = value.get(inner)
                    if isinstance(nested, list):
                        return nested
    return []


def is_ad(message):
    explicit = pick(message, ["isFromAd", "fromAd", "isAd"]).lower()
    raw = json.dumps(message, ensure_ascii=False).lower()
    return explicit in ("true", "1", "yes") or any(
        token in raw for token in ("source_id", "sourceid", "ad_id", "adid", "ctwa_clid", '"referral"', "source_url")
    )


def incoming(message):
    return pick(message, ["messageOriginType", "originType", "direction", "senderType"]).lower() in (
        "customer", "incoming", "inbound", "user"
    )


def message_time(message):
    raw = pick(message, ["messageTime", "timestamp", "createdAt", "sentAt"])
    try:
        return float(raw)
    except (TypeError, ValueError):
        return float("inf")


def origin_ad(messages):
    ads = [m for m in messages if isinstance(m, dict) and is_ad(m)]
    incoming_ads = [m for m in ads if incoming(m)]
    return min(incoming_ads or ads, key=message_time) if ads else None


def fetch_chat(phone, waba, start, end, api_key):
    last_error = ""
    formats = [phone]
    if not phone.startswith("+"):
        formats.append("+" + phone)
    for phone_format in formats:
        for attempt in range(2):
            try:
                response = http_session(api_key).get(
                    DOUBLETICK_URL,
                    params={
                        "wabaNumber": waba,
                        "customerNumber": phone_format,
                        "startDate": start,
                        "endDate": end,
                    },
                    timeout=(5, 20),
                )
                if response.status_code in (429, 500, 502, 503, 504):
                    last_error = f"HTTP {response.status_code}"
                    if attempt == 0:
                        time.sleep(1.5)
                        continue
                response.raise_for_status()
                messages = extract_messages(response.json() if response.text.strip() else {})
                if messages:
                    return messages, phone_format, ""
                break
            except requests.RequestException as exc:
                last_error = str(exc)
                if attempt == 0:
                    time.sleep(1)
    return [], "", last_error


def process_phone(phone, wabas, start, end, api_key):
    errors = []
    for waba in wabas:
        messages, used, error = fetch_chat(phone, waba, start, end, api_key)
        if error:
            errors.append(f"{waba}: {error}")
        if not messages:
            continue
        ad = origin_ad(messages)
        if not ad:
            return {
                "customer_phone": phone, "waba_number": waba, "phone_format_used": used,
                "messages_found": len(messages), "ad_id": "", "campaign_id": "", "adset_id": "",
                "headline": "", "source_url": "", "ctwa_clid": "", "status": "CHAT_FOUND_NO_AD_ID",
                "error": "",
            }
        ad_id = pick(ad, ["source_id", "sourceId", "ad_id", "adId"])
        return {
            "customer_phone": phone,
            "waba_number": waba,
            "phone_format_used": used,
            "messages_found": len(messages),
            "ad_id": ad_id,
            "campaign_id": pick(ad, ["campaign_id", "campaignId"]),
            "adset_id": pick(ad, ["adset_id", "adSetId", "adsetId"]),
            "headline": pick(ad, ["headline", "title", "adHeadline"]),
            "source_url": pick(ad, ["source_url", "sourceUrl"]),
            "ctwa_clid": pick(ad, ["ctwa_clid", "ctwaClid"]),
            "status": "AD_ID_FOUND" if ad_id else "AD_MESSAGE_FOUND_ID_MISSING",
            "error": "",
        }
    return {
        "customer_phone": phone, "waba_number": "", "phone_format_used": "", "messages_found": 0,
        "ad_id": "", "campaign_id": "", "adset_id": "", "headline": "", "source_url": "",
        "ctwa_clid": "", "status": "API_ERROR" if errors else "NO_CHAT_FOUND",
        "error": " | ".join(errors),
    }


def meta_ad_details(ad_id, token):
    empty = {
        "meta_ad_name": "", "meta_adset_id": "", "meta_adset_name": "",
        "meta_campaign_id": "", "meta_campaign_name": "",
        "meta_lookup_status": "SKIPPED_NO_META_TOKEN" if not token else "NOT_LOOKED_UP", "meta_error": "",
    }
    if not token or not ad_id:
        return empty
    try:
        response = http_session().get(
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
        adset = payload.get("adset") or {}
        campaign = payload.get("campaign") or {}
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
    name = upload.name.lower()
    if name.endswith((".xlsx", ".xls")):
        return pd.read_excel(upload, dtype=str)
    return pd.read_csv(upload, dtype=str, encoding_errors="ignore")


def detect_column(df, candidates):
    normalized = {norm(column): column for column in df.columns}
    for candidate in candidates:
        if norm(candidate) in normalized:
            return normalized[norm(candidate)]
    for column in df.columns:
        ncol = norm(column)
        if any(norm(candidate) in ncol for candidate in candidates):
            return column
    return None


def infer_product(campaign_name):
    text = norm(campaign_name)
    for product in sorted(PRODUCT_ALIASES, key=len, reverse=True):
        if any(norm(alias) in text for alias in PRODUCT_ALIASES[product]):
            return product
    return "UNMATCHED"


def infer_country(campaign_name):
    text = norm(campaign_name)
    for country, aliases in COUNTRY_ALIASES.items():
        if any(norm(alias) in text for alias in aliases):
            return country
    return "UNMATCHED"


def build_excel(df, summary):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame(list(summary.items()), columns=["Metric", "Value"]).to_excel(writer, sheet_name="Run_Summary", index=False)
        df.to_excel(writer, sheet_name="Detailed_Report", index=False)
        df.groupby(["country", "vendor"], dropna=False).size().reset_index(name="leads").to_excel(writer, sheet_name="Country_Vendor", index=False)
        df.groupby(["country", "vendor", "product"], dropna=False).size().reset_index(name="leads").to_excel(writer, sheet_name="Country_Vendor_Product", index=False)
        df.groupby(["vendor", "product"], dropna=False).size().reset_index(name="leads").to_excel(writer, sheet_name="Vendor_Product", index=False)
        df.groupby(["assigned_agent_name", "assigned_agent_phone"], dropna=False).size().reset_index(name="assigned_leads").to_excel(writer, sheet_name="Agent_Assignment", index=False)
        df.groupby("status", dropna=False).size().reset_index(name="count").to_excel(writer, sheet_name="API_Status", index=False)
        for sheet in writer.sheets.values():
            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions
            for column in sheet.columns:
                width = max(len(str(cell.value or "")) for cell in column[:500]) + 2
                sheet.column_dimensions[column[0].column_letter].width = min(max(width, 12), 45)
    return output.getvalue()


def secret_or_env(name, default=""):
    try:
        return st.secrets[name]
    except Exception:
        return os.getenv(name, default)


st.set_page_config(page_title="DoubleTick Lead Intelligence", page_icon="📊", layout="wide")
st.title("DoubleTick Lead Intelligence")
st.caption("Exact uploaded lead count, campaign-based country/vendor/product attribution, and assigned-agent phone/name reporting.")

with st.sidebar:
    st.header("API settings")
    api_key = st.text_input("DoubleTick API key", value=secret_or_env("DOUBLETICK_API_KEY"), type="password")
    waba_text = st.text_input("WABA number(s)", value=secret_or_env("DOUBLETICK_WABA_NUMBERS", "971521367907"))
    meta_token = st.text_input("Meta access token", value=secret_or_env("META_ACCESS_TOKEN"), type="password")
    start_date = st.date_input("Start date", value=date.today() - timedelta(days=1))
    end_date = st.date_input("End date", value=date.today())
    workers = st.slider("Parallel workers", 5, 40, 25)

customer_file = st.file_uploader("Upload DoubleTick customer report", type=["xlsx", "xls", "csv"])
st.info(
    "Every uploaded row remains a lead in the final report. The app fetches each phone once, then merges the result back to every uploaded row. "
    "Agent names are matched from the assigned-agent phone number using the built-in mapping."
)

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
    assigned_phone_col = detect_column(source_df, [
        "assigned user number", "assigned agent phone", "agent phone", "assigned phone",
        "team member phone", "assigned user phone", "assignee phone",
    ])
    missing = [name for name, column in (("customer phone", customer_phone_col), ("assigned agent phone", assigned_phone_col)) if not column]
    if missing:
        st.error("Could not detect: " + ", ".join(missing))
        st.write("Available columns:", list(source_df.columns))
        st.stop()

    lead_df = source_df.copy().reset_index(drop=True)
    lead_df.insert(0, "lead_row_number", range(1, len(lead_df) + 1))
    lead_df["customer_phone"] = lead_df[customer_phone_col].map(digits)
    lead_df["assigned_agent_phone"] = lead_df[assigned_phone_col].map(digits)
    lead_df["assigned_agent_name"] = lead_df["assigned_agent_phone"].map(AGENT_PHONE_NAME).fillna("UNMATCHED AGENT")

    valid_phones = list(dict.fromkeys(phone for phone in lead_df["customer_phone"] if phone))
    invalid_rows = int(lead_df["customer_phone"].eq("").sum())
    duplicate_rows = int(lead_df["customer_phone"].ne("").sum() - len(valid_phones))
    wabas = [digits(value) for value in waba_text.split(",") if digits(value)]
    if not wabas:
        st.error("Enter at least one valid WABA number.")
        st.stop()

    api_start = start_date.strftime("%d-%m-%Y")
    api_end = (end_date + timedelta(days=1)).strftime("%d-%m-%Y")
    progress = st.progress(0, text="Fetching DoubleTick chats...")
    rows = []
    if valid_phones:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(process_phone, phone, wabas, api_start, api_end, api_key): phone for phone in valid_phones}
            for index, future in enumerate(as_completed(futures), 1):
                try:
                    rows.append(future.result())
                except Exception as exc:
                    phone = futures[future]
                    rows.append({
                        "customer_phone": phone, "waba_number": "", "phone_format_used": "", "messages_found": 0,
                        "ad_id": "", "campaign_id": "", "adset_id": "", "headline": "", "source_url": "",
                        "ctwa_clid": "", "status": "API_ERROR", "error": str(exc),
                    })
                progress.progress(index / len(valid_phones), text=f"Fetched {index:,} of {len(valid_phones):,} phones")

    result = pd.DataFrame(rows)
    if result.empty:
        result = pd.DataFrame(columns=[
            "customer_phone", "waba_number", "phone_format_used", "messages_found", "ad_id", "campaign_id",
            "adset_id", "headline", "source_url", "ctwa_clid", "status", "error",
        ])

    ad_ids = list(dict.fromkeys(result["ad_id"].fillna("").astype(str).str.strip()))
    ad_ids = [ad_id for ad_id in ad_ids if ad_id]
    meta_cache = {}
    if meta_token and ad_ids:
        progress.progress(0, text="Resolving Meta campaign names...")
        with ThreadPoolExecutor(max_workers=min(20, workers)) as pool:
            futures = {pool.submit(meta_ad_details, ad_id, meta_token): ad_id for ad_id in ad_ids}
            for index, future in enumerate(as_completed(futures), 1):
                ad_id = futures[future]
                try:
                    meta_cache[ad_id] = future.result()
                except Exception as exc:
                    meta_cache[ad_id] = {**meta_ad_details("", meta_token), "meta_lookup_status": "META_API_ERROR", "meta_error": str(exc)}
                progress.progress(index / len(ad_ids), text=f"Resolved {index:,} of {len(ad_ids):,} ads")

    empty_meta = meta_ad_details("", meta_token)
    for column in empty_meta:
        result[column] = result["ad_id"].astype(str).map(lambda ad_id, c=column: meta_cache.get(ad_id, empty_meta).get(c, ""))

    final = lead_df.merge(result, on="customer_phone", how="left")
    final.loc[final["customer_phone"].eq(""), "status"] = "INVALID_CUSTOMER_PHONE"
    final["status"] = final["status"].fillna("NO_RESULT")
    final["campaign_name_for_mapping"] = final["meta_campaign_name"].fillna("")
    final["country"] = final["campaign_name_for_mapping"].map(infer_country)
    final["product"] = final["campaign_name_for_mapping"].map(infer_product)
    final["vendor"] = final["product"].map(PRODUCT_VENDOR).fillna("UNMATCHED")
    final["agent_match_status"] = final["assigned_agent_name"].eq("UNMATCHED AGENT").map({True: "UNMATCHED", False: "MATCHED BY PHONE"})

    summary = {
        "Uploaded lead rows": uploaded_rows,
        "Final detailed report rows": len(final),
        "Valid customer-phone rows": int(final["customer_phone"].ne("").sum()),
        "Invalid customer-phone rows": invalid_rows,
        "Unique phones fetched": len(valid_phones),
        "Duplicate phone rows": duplicate_rows,
        "Lead rows with chat found": int(final["messages_found"].fillna(0).astype(float).gt(0).sum()),
        "Lead rows with ad ID": int(final["ad_id"].fillna("").astype(str).str.strip().ne("").sum()),
        "Matched campaign names": int(final["meta_campaign_name"].fillna("").astype(str).str.strip().ne("").sum()),
        "Matched products": int(final["product"].ne("UNMATCHED").sum()),
        "Matched agents": int(final["assigned_agent_name"].ne("UNMATCHED AGENT").sum()),
    }
    st.session_state["report_df"] = final
    st.session_state["summary"] = summary
    progress.empty()
    st.success(f"Report generated. Total leads: {uploaded_rows:,}. Final report rows: {len(final):,}.")

if "report_df" in st.session_state:
    df = st.session_state["report_df"]
    summary = st.session_state["summary"]
    a, b, c, d, e = st.columns(5)
    a.metric("Total leads", f"{summary['Uploaded lead rows']:,}")
    b.metric("Chats found", f"{summary['Lead rows with chat found']:,}")
    c.metric("Ad IDs found", f"{summary['Lead rows with ad ID']:,}")
    d.metric("Products matched", f"{summary['Matched products']:,}")
    e.metric("Agents matched", f"{summary['Matched agents']:,}")

    if summary["Uploaded lead rows"] != summary["Final detailed report rows"]:
        st.error("Reconciliation failure: uploaded rows and detailed report rows do not match.")
    else:
        st.success("Reconciliation passed: every uploaded lead row is present in the detailed report.")

    tabs = st.tabs(["Summary", "Country / Vendor / Product", "Agents", "Detailed report", "Data quality"])
    with tabs[0]:
        st.dataframe(pd.DataFrame(list(summary.items()), columns=["Metric", "Value"]), use_container_width=True, hide_index=True)
        left, right = st.columns(2)
        with left:
            st.subheader("Country-wise leads")
            st.dataframe(df.groupby("country", dropna=False).size().reset_index(name="leads").sort_values("leads", ascending=False), use_container_width=True, hide_index=True)
        with right:
            st.subheader("Vendor-wise leads")
            st.dataframe(df.groupby("vendor", dropna=False).size().reset_index(name="leads").sort_values("leads", ascending=False), use_container_width=True, hide_index=True)
    with tabs[1]:
        report = df.groupby(["country", "vendor", "product"], dropna=False).size().reset_index(name="leads").sort_values(["country", "leads"], ascending=[True, False])
        st.dataframe(report, use_container_width=True, hide_index=True)
    with tabs[2]:
        agents = df.groupby(["assigned_agent_name", "assigned_agent_phone"], dropna=False).size().reset_index(name="assigned_leads").sort_values("assigned_leads", ascending=False)
        st.dataframe(agents, use_container_width=True, hide_index=True)
    with tabs[3]:
        preferred = [
            "lead_row_number", "customer_phone", "assigned_agent_phone", "assigned_agent_name",
            "country", "vendor", "product", "ad_id", "meta_campaign_name", "meta_adset_name",
            "meta_ad_name", "headline", "status", "messages_found", "error",
        ]
        remaining = [column for column in df.columns if column not in preferred]
        st.dataframe(df[preferred + remaining], use_container_width=True, hide_index=True, height=650)
    with tabs[4]:
        q1, q2, q3, q4 = st.columns(4)
        q1.metric("Invalid phones", summary["Invalid customer-phone rows"])
        q2.metric("Duplicate phone rows", summary["Duplicate phone rows"])
        q3.metric("Unmatched products", int(df["product"].eq("UNMATCHED").sum()))
        q4.metric("Unmatched agents", int(df["assigned_agent_name"].eq("UNMATCHED AGENT").sum()))
        st.subheader("Unmatched campaign names")
        unmatched = df[df["product"].eq("UNMATCHED")][["customer_phone", "meta_campaign_name", "meta_ad_name", "headline"]]
        st.dataframe(unmatched, use_container_width=True, hide_index=True)

    excel = build_excel(df, summary)
    st.download_button(
        "Download complete Excel report",
        data=excel,
        file_name="doubletick_lead_intelligence_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
        use_container_width=True,
    )
