#!/usr/bin/env python3
"""
Kaohsiung schedule updater — CINEMA half (definitive, no API key).

Reads showtimes straight from atmovies for four Kaohsiung cinemas, keeps only
ENGLISH-AUDIO films, tags premium formats (IMAX / 4DX / ScreenX / Gold Class /
3D / restored), and writes them into schedule.json. The PERFORMANCE & ART half
is left untouched (curated snapshot).

No GEMINI key, no rate limits, nothing to run out. Pure standard library.
"""
import re, json, os, sys, time, datetime, urllib.request, urllib.error

# cinema key -> atmovies theater code.  Keys MUST match CINEMA_IDS in index.html.
THEATERS = {
    "IN89":    "t07728",   # in89 Dali  (大立in89豪華影城)
    "IN89P2":  "t07702",   # in89 Pier-2 (in89駁二電影院)
    "VIESHOW": "t07703",   # Vie Show FE21 (高雄大遠百威秀影城)
    "DREAM":   "t07707",   # Showtime Dream Mall (高雄夢時代秀泰影城)
}
AREA = "a07"               # Kaohsiung
OUT  = "schedule.json"
DAYS = 3                   # rolling 3-day board (the furthest cinemas publish)
TZ   = datetime.timezone(datetime.timedelta(hours=8))   # Taipei
UA   = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"

# English title for known films, keyed by the stable atmovies code.
# Unknown codes fall back to the Chinese title; add new ones here over time.
TITLE_DICT = {
    "fben26657236": "The Backrooms",
    "fmen30825738": "The Mandalorian and Grogu",
    "ften51745960": "Top Gun: Maverick",
    "fTatm0754001": "Top Gun (1986 re-release)",
    "fmen17490712": "Mortal Kombat II",
    "fden33612209": "The Devil Wears Prada 2",
    "fmen11378946": "Michael (Michael Jackson biopic)",
    "fsen28650488": "The Super Mario Galaxy Movie",
    "fhen26443616": "Tanuki World (狸想世界) - animation",
    "fLatm0874041": "The Last Emperor (restored)",
    "flen23464902": "The Lobster",
    "fben39018643": "Billie Eilish: concert film",
}
EN_AUDIO  = ("英文版", "英語版")
DUB_AUDIO = ("中文版", "國語版", "日文版", "日語版", "韓文版", "韓語版", "粵語版", "台語版")

def country(code):
    m = re.match(r"f.([a-z]{2})", code)
    return m.group(1) if m else ""

def screening_tag(seg):
    """Build the display tag for one screening: audio (English) + premium format."""
    tags, up = [], seg.upper()
    if any(a in seg for a in EN_AUDIO):
        tags.append("English")
    if "IMAX" in up:                                   tags.append("IMAX")
    if "4DX" in up:                                    tags.append("4DX")
    if "SCREEN X" in up or "SCREENX" in up:            tags.append("ScreenX")
    if "GOLD CLASS" in up:                             tags.append("Gold Class")
    if "HFR" in up:                                    tags.append("HFR 3D")
    elif re.search(r"\b3D|３D|3D版", seg):              tags.append("3D")
    if "4K" in up:                                     tags.append("4K Restored")
    elif "數位修復" in seg:                             tags.append("Restored")
    return " · ".join(tags)

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")

def parse_day(html, date_s, url):
    """Return English-audio screenings for one day's showtime page (tagged by format)."""
    matches = list(re.finditer(
        r'href="[^"]*?/movie/(f[A-Za-z]{1,5}\d+)/?"[^>]*>\s*([^<>]{1,60}?)\s*</a>', html))
    out = {}
    for i, m in enumerate(matches):
        code, title_zh = m.group(1), m.group(2).strip()
        if not title_zh or title_zh.startswith("其他"):
            continue
        seg = html[m.end(): matches[i + 1].start() if i + 1 < len(matches) else len(html)]
        cut = seg.find("其他戲院")
        if cut != -1:
            seg = seg[:cut]
        has_dub = any(d in seg for d in DUB_AUDIO)
        has_en  = any(e in seg for e in EN_AUDIO)
        if has_dub and not has_en:
            continue                                   # dubbed / non-English audio
        english = has_en or (code in TITLE_DICT) or (country(code) == "en")
        if not english:
            continue
        times = sorted({f"{int(h):02d}:{mn}" for h, mn in re.findall(r"(\d{1,2})[:：](\d{2})", seg)})
        if not times:
            continue
        title = TITLE_DICT.get(code, title_zh)
        tag = screening_tag(seg)
        key = (title, date_s, tag)
        if key in out:
            out[key]["times"] = sorted(set(out[key]["times"]) | set(times))
        else:
            out[key] = {"film": title, "date": date_s, "times": times,
                        "format": tag, "srcs": ["atmovies"], "source": url}
    return list(out.values())

def page_date(html):
    """The date atmovies prints on the page header, e.g. 2026/06/01 -> 2026-06-01."""
    m = re.search(r"(20\d{2})/(\d{2})/(\d{2})", html)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None

def scrape_one(code):
    today = datetime.datetime.now(TZ).date()
    horizon = {(today + datetime.timedelta(days=d)).isoformat() for d in range(DAYS)}
    base = f"https://www.atmovies.com.tw/showtime/{code}/{AREA}/"
    # plain URL serves TODAY; dated URLs serve future days
    urls = [base] + [f"{base}{(today + datetime.timedelta(days=d)).strftime('%Y%m%d')}/" for d in range(DAYS)]
    collected = {}
    for url in urls:
        for attempt in range(3):
            try:
                html = fetch(url)
                d = page_date(html)
                if d and d in horizon:
                    for e in parse_day(html, d, url):
                        k = (e["date"], e["film"], e["format"])
                        if k in collected:
                            collected[k]["times"] = sorted(set(collected[k]["times"]) | set(e["times"]))
                        else:
                            collected[k] = e
                break                       # page loaded; no need to retry this URL
            except Exception as ex:
                print(f"    {url} attempt {attempt+1}: {ex}", file=sys.stderr)
                if attempt < 2:
                    time.sleep(6)
        time.sleep(1)                       # be polite between requests
    return list(collected.values())

def main():
    data = {"cinema": {}, "culture": {}}
    if os.path.exists(OUT):
        try:
            data = json.load(open(OUT, encoding="utf-8"))
        except Exception:
            pass
    data.setdefault("cinema", {})
    for key, code in THEATERS.items():
        print(f"[{key}] {code}")
        entries = scrape_one(code)
        if entries:
            data["cinema"][key] = entries
            counts = {}
            for e in entries:
                counts[e["date"]] = counts.get(e["date"], 0) + 1
            for d in sorted(counts):
                print(f"    {d}: {counts[d]} screenings")
            print(f"    -> wrote {len(entries)} screenings")
        else:
            print(f"    nothing parsed — keeping previous data for {key}", file=sys.stderr)
        time.sleep(2)                       # be polite between cinemas
    data["updatedAt"] = datetime.datetime.now(TZ).isoformat()
    data["label"] = "cinemas auto-updated " + datetime.datetime.now(TZ).strftime("%d %b %Y %H:%M") + " (Taipei)"
    json.dump(data, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("wrote", OUT)

if __name__ == "__main__":
    main()
