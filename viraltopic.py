import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta, timezone
import re

# -----------------------------
# CONFIG
# -----------------------------
API_KEY = st.secrets.get("AIzaSyAUHpprPXVoeRc9R_0vc77PXZEjxRXOUwg", "")  # Streamlit Secrets
YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEO_URL = "https://www.googleapis.com/youtube/v3/videos"
YOUTUBE_CHANNEL_URL = "https://www.googleapis.com/youtube/v3/channels"

st.set_page_config(page_title="Viral Topics Tool", layout="wide")
st.title("YouTube Viral Topics Tool (Last Days Viral by Views)")

# -----------------------------
# INPUTS
# -----------------------------
days = st.number_input("Last how many days? (default 3)", min_value=1, max_value=30, value=3)

max_subs = st.number_input(
    "Max subscribers (0 = no filter)",
    min_value=0, max_value=100_000_000, value=0, step=1000
)

st.caption("Keywords: one per line (apni marzi se edit karo)")
default_kw = """Affair Relationship Stories
"""

keywords_text = st.text_area("Keywords", value=default_kw, height=160, key="kw_editor")
keywords = [k.strip() for k in keywords_text.split("\n") if k.strip()]

exclude_shorts = st.checkbox("Exclude Shorts (<60s)?", value=True)

max_per_keyword = st.selectbox("Results per keyword", [10, 25, 50], index=2)

lang_map = {
    "Any": "",
    "English": "en",
    "Urdu": "ur",
    "Hindi": "hi",
    "Punjabi": "pa",
    "Arabic": "ar",
}
lang_label = st.selectbox("Language (search hint)", list(lang_map.keys()), index=0)
relevance_lang = lang_map[lang_label]

# -----------------------------
# HELPERS
# -----------------------------
def yt_get(url, params):
    r = requests.get(url, params=params, timeout=30)
    if r.status_code != 200:
        return None, f"HTTP {r.status_code}: {r.text[:200]}"
    return r.json(), None

def chunk(lst, n=50):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]

def parse_yt_time(ts):
    # example: 2026-02-07T10:20:30Z
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))

def parse_iso8601_duration(d):
    # PT#H#M#S -> seconds
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", d or "")
    if not m:
        return 0
    h = int(m.group(1) or 0)
    mi = int(m.group(2) or 0)
    s = int(m.group(3) or 0)
    return h * 3600 + mi * 60 + s

# -----------------------------
# RUN
# -----------------------------
if st.button("Fetch Viral Videos"):
    if not API_KEY:
        st.error("YOUTUBE_API_KEY missing. Streamlit Secrets me add karo.")
        st.stop()

    if not keywords:
        st.warning("Please add at least 1 keyword.")
        st.stop()

    start_date = (datetime.now(timezone.utc) - timedelta(days=int(days))).isoformat().replace("+00:00", "Z")

    all_video_ids = []
    video_meta = {}  # videoId -> {keyword, title, channelTitle, channelId, publishedAt, url}

    # -------- SEARCH --------
    for kw in keywords:
        st.write(f"🔎 Searching: **{kw}**")

        search_params = {
            "part": "snippet",
            "q": kw,
            "type": "video",
            "order": "viewCount",
            "publishedAfter": start_date,
            "maxResults": int(max_per_keyword),
            "key": API_KEY,
        }

        # language hint (ranking)
        if relevance_lang:
            search_params["relevanceLanguage"] = relevance_lang

        data, err = yt_get(YOUTUBE_SEARCH_URL, search_params)
        if err:
            st.error(f"Search error for '{kw}': {err}")
            continue

        items = (data or {}).get("items", [])
        if not items:
            st.info(f"No videos found for: {kw}")
            continue

        for it in items:
            vid = (it.get("id") or {}).get("videoId")
            sn = it.get("snippet") or {}
            if not vid:
                continue

            # store first-seen meta (avoid overwriting)
            if vid not in video_meta:
                video_meta[vid] = {
                    "Keyword": kw,
                    "Title": sn.get("title", ""),
                    "Channel": sn.get("channelTitle", ""),
                    "ChannelId": sn.get("channelId", ""),
                    "PublishedAt": sn.get("publishedAt", ""),
                    "URL": f"https://www.youtube.com/watch?v={vid}",
                }
                all_video_ids.append(vid)

    if not all_video_ids:
        st.warning("No videos collected. Try increasing days or changing keywords.")
        st.stop()

    # -------- CHANNEL SUBSCRIBERS --------
    channel_ids = list({m.get("ChannelId") for m in video_meta.values() if m.get("ChannelId")})
    channel_subs = {}  # channelId -> int subs or None if hidden

    for ch_ids in chunk(channel_ids, 50):
        ch_params = {
            "part": "statistics",
            "id": ",".join(ch_ids),
            "key": API_KEY,
        }
        ch_data, err = yt_get(YOUTUBE_CHANNEL_URL, ch_params)
        if err:
            st.error(f"Channel stats error: {err}")
            continue

        for ch in (ch_data or {}).get("items", []):
            cid = ch.get("id")
            stats = (ch.get("statistics") or {})
            subs = stats.get("subscriberCount")
            channel_subs[cid] = int(subs) if subs is not None else None

    # -------- VIDEO STATS + DETAILS --------
    rows = []
    now = datetime.now(timezone.utc)

    for ids in chunk(all_video_ids, 50):
        # statistics + snippet (language) + contentDetails (duration)
        stats_params = {
            "part": "statistics,snippet,contentDetails",
            "id": ",".join(ids),
            "key": API_KEY
        }
        stats_data, err = yt_get(YOUTUBE_VIDEO_URL, stats_params)
        if err:
            st.error(f"Stats error: {err}")
            continue

        for v in (stats_data or {}).get("items", []):
            vid = v.get("id")
            stats = (v.get("statistics") or {})
            views = int(stats.get("viewCount", 0) or 0)

            meta = video_meta.get(vid, {})
            published_str = meta.get("PublishedAt", "")
            if not published_str:
                continue

            # Duration & Shorts filter
            duration_iso = (v.get("contentDetails") or {}).get("duration", "")
            duration_sec = parse_iso8601_duration(duration_iso)
            if exclude_shorts and duration_sec < 60:
                continue

            # Subscribers filter
            ch_id = meta.get("ChannelId", "")
            subs = channel_subs.get(ch_id)  # int or None
            if max_subs > 0 and subs is not None and subs > max_subs:
                continue

            # Language column
            vsn = (v.get("snippet") or {})
            vid_lang = vsn.get("defaultAudioLanguage") or vsn.get("defaultLanguage") or ""

            published = parse_yt_time(published_str)
            age_days = max((now - published).total_seconds() / 86400.0, 0.01)  # avoid divide by zero
            views_per_day = views / age_days

            rows.append({
                "Keyword": meta.get("Keyword", ""),
                "Title": meta.get("Title", ""),
                "Channel": meta.get("Channel", ""),
                "Subscribers": subs,
                "Language": vid_lang,
                "DurationSec": duration_sec,
                "PublishedAt": published_str,
                "Views": views,
                "Views/Day": round(views_per_day, 2),
                "URL": meta.get("URL", ""),
            })

    # ✅ IMPORTANT: this must be aligned with "for ids in chunk" (not inside it)
    if not rows:
        st.warning("No stats rows after filters. Try increasing days / max_subs=0 / disable shorts filter.")
        st.stop()

    df = pd.DataFrame(rows).sort_values("Views/Day", ascending=False)

    st.success(f"Found {len(df)} videos. Sorted by Views/Day (viral speed).")

    st.dataframe(
        df,
        use_container_width=True,
        column_config={"URL": st.column_config.LinkColumn("URL")}
    )

    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download CSV",
        data=csv,
        file_name="viral_videos_last_days.csv",
        mime="text/csv"
    )
