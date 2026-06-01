#!/usr/bin/env python3
"""
Kaohsiung schedule updater — CINEMA half (definitive, no API key).

Reads in89 showtimes straight from atmovies (server-side, no CORS, no quotas),
keeps only ENGLISH-AUDIO films, and writes them into schedule.json.
The PERFORMANCE & ART half of schedule.json is left untouched (curated snapshot).

No GEMINI key, no rate limits, nothing to run out. Pure standard library.
"""
import re, json, os, sys, time, datetime, urllib.request, urllib.error

THEATER   = "t07728"          # 大立 in89
AREA      = "a07"             # Kaohsiung
OUT       = "schedule.json"
DAYS      = 3                 # rolling 3-day board (the furthest cinemas publish)
TZ        = datetime.timezone(datetime.timedelta(hours=8))   # Taipei
UA        = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"

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
}
EN_LABELS  = ("英文版", "英語版")
DUB_LABELS = ("中文版", "國語版", "日文版", "韓文版", "粵語版", "台語版")

def country(code):
    m = re.match(r"f.([a-z]{2})", code)
    return m.group(1) if m else ""

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")

def parse_day(html, date_s, url):
    """Return list of English-audio film entries for one day's showtime page."""
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
        version = next((lab for lab in EN_LABELS + DUB_LABELS if lab in seg), "")
        if version in DUB_LABELS:
            continue                                   # dubbed / non-English audio
        english = (version in EN_LABELS) or (code in TITLE_DICT) or (country(code) == "en")
        if not english:
            continue
        times = sorted({f"{int(h):02d}:{mn}" for h, mn in re.findall(r"(\d{1,2})[:：](\d{2})", seg)})
        if not times:
            continue
        title = TITLE_DICT.get(code, title_zh)
        fmt = "English dub" if version in EN_LABELS else ""
        key = title + "|" + date_s
        if key in out:
            out[key]["times"] = sorted(set(out[key]["times"]) | set(times))
        else:
            out[key] = {"film": title, "date": date_s, "times": times,
                        "format": fmt, "srcs": ["atmovies"], "source": url}
    return list(out.values())

def scrape_cinema():
    today = datetime.datetime.now(TZ).date()
    entries = []
    for d in range(DAYS):
        day = today + datetime.timedelta(days=d)
        ymd = day.strftime("%Y%m%d")
        url = f"https://www.atmovies.com.tw/showtime/{THEATER}/{AREA}/{ymd}/"
        got = []
        for attempt in range(3):                 # retry if a day comes back empty
            try:
                got = parse_day(fetch(url), day.isoformat(), url)
                if got:
                    break
            except Exception as ex:
                print(f"  {day.isoformat()} attempt {attempt+1}: {ex}", file=sys.stderr)
            if attempt < 2:
                time.sleep(6)
        entries.extend(got)
        print(f"{day.isoformat()}: {len(got)} English-language showings")
    return entries

def main():
    data = {"cinema": {}, "culture": {}}
    if os.path.exists(OUT):
        try:
            data = json.load(open(OUT, encoding="utf-8"))
        except Exception:
            pass
    entries = scrape_cinema()
    if entries:
        data.setdefault("cinema", {})["IN89"] = entries
        print(f"cinema: wrote {len(entries)} entries")
    else:
        print("cinema: nothing parsed — keeping previous data", file=sys.stderr)
    data["updatedAt"] = datetime.datetime.now(TZ).isoformat()
    data["label"] = "cinema auto-updated " + datetime.datetime.now(TZ).strftime("%d %b %Y %H:%M") + " (Taipei)"
    json.dump(data, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("wrote", OUT)

if __name__ == "__main__":
    main()
