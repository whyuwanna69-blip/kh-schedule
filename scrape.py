#!/usr/bin/env python3
"""
Kaohsiung culture schedule scraper.
Runs in GitHub Actions (server-side, no CORS), calls Gemini with Google Search
grounding to pull current listings, and writes schedule.json.

- CINEMA: in89 only, English-language films + times, next ~3 days.
- PERFORMANCE/ART: 30-day window across the venues.

Non-destructive: if a venue returns nothing this run, its previous data is kept.
Needs env var GEMINI_API_KEY (set as a GitHub repo Secret).
"""
import os, json, re, sys, time, datetime, urllib.request, urllib.error

KEY   = os.environ.get("GEMINI_API_KEY", "").strip()
MODEL = "gemini-2.5-flash"   # free-tier eligible model
OUT   = "schedule.json"

TZ       = datetime.timezone(datetime.timedelta(hours=8))   # Asia/Taipei
TODAY    = datetime.datetime.now(TZ).date()
TODAY_S  = TODAY.isoformat()
END_S    = (TODAY + datetime.timedelta(days=29)).isoformat()
CINE_END = (TODAY + datetime.timedelta(days=3)).isoformat()

# in89 (commercial multiplex) — the only daily-showtime board
IN89 = {
    "id": "IN89",
    "name": "in89 (Dali) Cinema",
    "zh": "大立in89豪華影城",
    "url": "https://www.atmovies.com.tw/showtime/t07728/a07/",
    "hint": "大立in89豪華影城 高雄 時刻表 atmovies showtimes",
}

# 30-day venues  (cat: perf or art)
CULTURE = [
    ("WWY",   "perf", "Weiwuying (Nat. Kaohsiung Center for the Arts)", "衛武營",
     "https://www.npac-weiwuying.org/programs?lang=en",
     "Weiwuying National Kaohsiung Center for the Arts upcoming concerts opera theatre dance program"),
    ("MUSIC", "perf", "Kaohsiung City Music Hall", "高雄市音樂館",
     "https://kaohsiungmusichall.kcg.gov.tw/", "高雄市音樂館 近期 演出 音樂會 節目表"),
    ("CULT",  "perf", "Kaohsiung Cultural Center (Jhih-De / Jhih-Shan Hall)", "高雄市文化中心 至德堂 至善廳",
     "https://www.opentix.life/", "高雄市文化中心 至德堂 至善廳 演出 節目 OPENTIX 高雄"),
    ("DADONG","perf", "Dadong Arts Center", "大東文化藝術中心",
     "https://dadongcenter.kcg.gov.tw/", "大東文化藝術中心 演出 展覽 節目 近期"),
    ("KMFA",  "art",  "Kaohsiung Museum of Fine Arts", "高雄市立美術館",
     "https://www.kmfa.gov.tw/english/index.htm", "Kaohsiung Museum of Fine Arts KMFA current and upcoming exhibitions dates"),
    ("ALIEN", "art",  "ALIEN Art Centre", "金馬賓館當代美術館",
     "https://www.alien.com.tw/", "金馬賓館當代美術館 ALIEN Art Centre Kaohsiung current exhibition dates"),
    ("PIER2", "art",  "Pier-2 Art Center", "駁二藝術特區",
     "https://pier2.org/", "駁二藝術特區 Pier-2 Art Center Kaohsiung 展覽 活動 exhibitions events"),
    ("NEIWEI","art",  "Neiwei Theater / Neiwei Arts Center", "內惟藝術中心 內惟戲院",
     "https://www.nwac.org.tw/tw/activity-list", "內惟藝術中心 內惟戲院 放映 展覽 活動 節目"),
    ("KFA",   "art",  "Kaohsiung Film Archive", "高雄市電影館",
     "https://kfa.kcg.gov.tw/", "高雄市電影館 節目 放映 影展 近期"),
]


def gemini(prompt, search=True, retries=3):
    if not KEY:
        raise RuntimeError("GEMINI_API_KEY is not set")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    body = {"contents": [{"parts": [{"text": prompt}]}]}
    if search:
        body["tools"] = [{"google_search": {}}]
    payload = json.dumps(body).encode("utf-8")
    for attempt in range(retries):
        req = urllib.request.Request(
            url, data=payload,
            headers={"x-goog-api-key": KEY, "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                data = json.loads(r.read().decode("utf-8"))
            parts = (data.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
            return "".join(p.get("text", "") for p in parts if "text" in p)
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries - 1:
                wait = 25 * (attempt + 1)
                print(f"  429 rate-limited; waiting {wait}s then retrying...")
                time.sleep(wait)
                continue
            raise
    return ""


def extract_array(text):
    """Pull the first balanced JSON array out of an LLM response."""
    if not text:
        return []
    t = re.sub(r"```json|```", "", text)
    start = t.find("[")
    if start < 0:
        return []
    depth = 0; instr = False; esc = False
    for i in range(start, len(t)):
        c = t[i]
        if instr:
            if esc: esc = False
            elif c == "\\": esc = True
            elif c == '"': instr = False
        else:
            if c == '"': instr = True
            elif c == "[": depth += 1
            elif c == "]":
                depth -= 1
                if depth == 0:
                    js = t[start:i + 1]
                    try:
                        return json.loads(js)
                    except Exception:
                        last = js.rfind("}")
                        if last > 0:
                            try:
                                return json.loads(js[:last + 1] + "]")
                            except Exception:
                                return []
                        return []
    return []


CINEMA_PROMPT = f"""Use web search (atmovies.com.tw per-cinema showtime pages, and the cinema's own site) to find the ENGLISH-LANGUAGE films screening at this cinema in Kaohsiung, Taiwan, day by day from {TODAY_S} through {CINE_END}, WITH showtimes.
CINEMA: {IN89['name']} ({IN89['zh']})
HINTS: {IN89['hint']}
OFFICIAL: {IN89['url']}
INCLUDE ONLY English-audio films: live-action Hollywood / Western films (in Taiwan these play in original English with Chinese subtitles), and the English-dub (英語版/英文版) version of animated films.
EXCLUDE Mandarin / Chinese / Japanese / Korean-language films, and any Mandarin-dubbed (國語版/中文版) screening.
Return ONLY a JSON array, no prose/fences. One object per film per day:
{{"film":"English title","date":"YYYY-MM-DD","times":["HH:MM","HH:MM"],"format":"2D|IMAX|4DX|Gold Class or empty","source":"https url"}}
Use 24-hour zero-padded HH:MM. Only days/times actually published. If none, return []."""


def culture_prompt(v):
    return f"""Use web search to find scheduled public events at this venue in Kaohsiung, Taiwan, between {TODAY_S} and {END_S} (30-day window).
VENUE: {v[2]} ({v[3]})
HINTS: {v[5]}
OFFICIAL: {v[4]}
Return ONLY a JSON array, no prose/fences. Up to 12 items, soonest first:
{{"date":"YYYY-MM-DD","end":"YYYY-MM-DD or empty","title":"English title","type":"concert|opera|theater|dance|exhibition|event","note":"<=12 word English detail","source":"https url"}}
Rules: only verifiable dated events overlapping the window; translate Chinese to natural English; museums/Pier-2 = exhibitions with full date range in "end"; performance venues = concert/opera/theatre/dance with date. If none, []."""


def norm_time(t):
    m = re.search(r"(\d{1,2})[:：](\d{2})", str(t))
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else str(t).strip()


def main():
    # load previous (non-destructive)
    prev = {"cinema": {}, "culture": {}}
    if os.path.exists(OUT):
        try:
            prev = json.load(open(OUT, encoding="utf-8"))
        except Exception:
            pass
    cinema = dict(prev.get("cinema") or {})
    culture = dict(prev.get("culture") or {})

    # --- cinema: in89 ---
    try:
        arr = extract_array(gemini(CINEMA_PROMPT, search=True))
        out = []
        for e in arr:
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(e.get("date", ""))):
                continue
            out.append({
                "film": e.get("film", "").strip(),
                "date": e["date"],
                "times": sorted({norm_time(x) for x in (e.get("times") or []) if x}),
                "format": e.get("format", ""),
                "srcs": ["auto"],
                "source": e.get("source") or IN89["url"],
            })
        if out:
            cinema["IN89"] = out
            print(f"IN89: {len(out)} film-day entries")
        else:
            print("IN89: no data this run (keeping previous)")
    except Exception as ex:
        print(f"IN89 failed: {ex} (keeping previous)", file=sys.stderr)

    # --- culture: 30-day venues ---
    for v in CULTURE:
        time.sleep(6)   # stay under the free-tier ~1-request-per-4-6s limit
        vid, cat = v[0], v[1]
        try:
            arr = extract_array(gemini(culture_prompt(v), search=True))
            out = []
            for e in arr:
                title = (e.get("title") or "").strip()
                if not title:
                    continue
                out.append({
                    "title": title,
                    "date": e.get("date", ""),
                    "end": e.get("end", ""),
                    "type": e.get("type", "event"),
                    "note": e.get("note", ""),
                    "srcs": ["auto"],
                    "source": e.get("source") or v[4],
                    "venueId": vid,
                    "cat": cat,
                })
            if out:
                culture[vid] = out
                print(f"{vid}: {len(out)} events")
            else:
                print(f"{vid}: no data this run (keeping previous)")
        except Exception as ex:
            print(f"{vid} failed: {ex} (keeping previous)", file=sys.stderr)

    payload = {
        "updatedAt": datetime.datetime.now(TZ).isoformat(),
        "label": "auto-updated " + datetime.datetime.now(TZ).strftime("%d %b %Y %H:%M") + " (Taipei)",
        "cinema": cinema,
        "culture": culture,
    }
    json.dump(payload, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
