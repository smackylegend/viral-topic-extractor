import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta, timezone

# -----------------------------
# CONFIG
# -----------------------------
API_KEY = "AIzaSyAUHpprPXVoeRc9R_0vc77PXZEjxRXOUwg"   # ✅ better: Streamlit Secrets use karo
YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEO_URL = "https://www.googleapis.com/youtube/v3/videos"
YOUTUBE_CHANNEL_URL = "https://www.googleapis.com/youtube/v3/channels"

st.set_page_config(page_title="Viral Topics Tool", layout="wide")
st.title("YouTube Viral Topics Tool (Last Days Viral by Views)")

# -----------------------------
# INPUTS
# -----------------------------
days = st.number_input("Last how many days? (default 3)", min_value=1, max_value=30, value=3)

st.caption("Keywords: one per line (apni marzi se edit karo)")
default_kw = """Affair Relationship Stories
"""

keywords_text = st.text_area("Keywords", value=default_kw, height=160, key="kw_editor")
keywords = [k.strip() for k in keywords_text.split("\n") if k.strip()]

exclude_shorts = st.checkbox("Exclude Shorts / very short videos?", value=True)
# If exclude_shorts = True → medium+ only (4 min+). If False → any duration.
duration_filter = "medium" if exclude_shorts else "any"

max_per_keyword = st.selectbox("Results per keyword", [10, 25, 50], index=2)

max_subs = st.number_input(
    "Max subscribers (0 = no filter)",
    min_value=0, max_value=100_000_000, value=0, step=1000
)

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
        yield lst[i:i+n]

def parse_yt_time(ts):
    # example: 2026-02-07T10:20:30Z
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))

# -----------------------------
# RUN
# -----------------------------
if st.button("Fetch Viral Videos"):
    if not API_KEY or API_KEY == "PASTE_YOUR_API_KEY_HERE":
        st.error("API_KEY set karo (aur behtar hai Secrets me).")
        st.stop()

    if not keywords:
        st.warning("Please add at least 1 keyword.")
        st.stop()

    start_date = (datetime.now(timezone.utc) - timedelta(days=int(days))).isoformat().replace("+00:00", "Z")

    all_video_ids = []
    video_meta = {}  # videoId -> {keyword, title, channelTitle, publishedAt}

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

        # duration filter (optional)
        if duration_filter != "any":
            search_params["videoDuration"] = duration_filter  # "medium" => 4-20 min (shorts mostly gone)

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
                    "PublishedAt": sn.get("publishedAt", ""),
                    "URL": f"https://www.youtube.com/watch?v={vid}",
                    "ChannelId": sn.get("channelId", ""),
                }
                all_video_ids.append(vid)

    if not all_video_ids:
        st.warning("No videos collected. Try increasing days or turning off Exclude Shorts.")
        st.stop()
        
if not all_video_ids:
    st.warning("No videos collected. Try increasing days or turning off Exclude Shorts.")
    st.stop()

    # Fetch channel subscribers
channel_ids = list({m.get("ChannelId") for m in video_meta.values() if m.get("ChannelId")})
channel_subs = {}  # channelId -> int subs or None if hidden

for ch_ids in chunk(channel_ids, 50):
    ch_params = {"part": "statistics", "id": ",".join(ch_ids), "key": API_KEY}
    ch_data, err = yt_get(YOUTUBE_CHANNEL_URL, ch_params)
    if err:
        st.error(f"Channel stats error: {err}")
        continue

    for ch in (ch_data or {}).get("items", []):
        cid = ch.get("id")
        stats = (ch.get("statistics") or {})
        subs = stats.get("subscriberCount")
        channel_subs[cid] = int(subs) if subs is not None else None
    
    # Fetch video stats in batches
    rows = []
    now = datetime.now(timezone.utc)

    for ids in chunk(all_video_ids, 50):
        stats_params = {"part": "statistics,snippet", "id": ",".join(ids), "key": API_KEY}
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

            published = parse_yt_time(published_str)
            age_days = max((now - published).total_seconds() / 86400.0, 0.01)  # avoid divide by zero
            views_per_day = views / age_days

            rows.append({
                "Keyword": meta.get("Keyword", ""),
                "Title": meta.get("Title", ""),
                "Channel": meta.get("Channel", ""),
                "PublishedAt": published_str,
                "Views": views,
                "Views/Day": round(views_per_day, 2),
                "URL": meta.get("URL", ""),
                "Subscribers": subs,
                "Language": vid_lang,
            })
ch_id = meta.get("ChannelId", "")
subs = channel_subs.get(ch_id)  # int or None



vsn = (v.get("snippet") or {})
vid_lang = vsn.get("defaultAudioLanguage") or vsn.get("defaultLanguage") or ""

    if not rows:
        st.warning("No stats rows. Try again.")
        st.stop()

    df = pd.DataFrame(rows).sort_values("Views/Day", ascending=False)

    st.success(f"Found {len(df)} videos. Sorted by Views/Day (viral speed).")

    st.dataframe(
        df,
        use_container_width=True,
        column_config={"URL": st.column_config.LinkColumn("URL")}
    )

    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button("Download CSV", data=csv, file_name="viral_videos_last_days.csv", mime="text/csv")
