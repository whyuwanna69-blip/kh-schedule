# Kaohsiung Culture Schedule — auto-updating

A static page (`index.html`) that shows in89 English-language showtimes (rolling ~3 days)
plus a 30-day performance & art agenda for Kaohsiung. A daily GitHub Action refreshes the
data; the page just reads it on open. No server, no in-browser API calls.

## How it works
1. `.github/workflows/update.yml` runs `scrape.py` once a day (06:00 Taipei).
2. `scrape.py` asks Google **Gemini** (with Google Search grounding) for current listings,
   translates to English, and writes `schedule.json`. The Action commits it.
3. `index.html` fetches `schedule.json` from this repo's raw URL on load. Because it runs on
   GitHub's servers (not your browser), there's no CORS wall and the key is never exposed.

## One-time setup (≈5 clicks)
1. **Create the repo** named exactly **`kh-schedule`** under your account
   `whyuwanna69-blip` (so the path matches the URL baked into `index.html`).
   If you use a different name/branch, edit the `DATA_URL` line near the top of the
   `index.html` script and the raw URL accordingly.
2. **Add these files** to the repo, keeping the workflow in its folder:
   ```
   index.html
   scrape.py
   schedule.json
   README.md
   .github/workflows/update.yml      <-- create the .github/workflows/ folders; this is "update.yml"
   ```
3. **Add your Gemini key as a Secret:** repo → **Settings → Secrets and variables → Actions
   → New repository secret**. Name it **`GEMINI_API_KEY`**, paste your key from
   https://aistudio.google.com/apikey . (The key lives only in GitHub Secrets.)
4. **Enable Actions:** open the **Actions** tab, accept enabling workflows. Open
   **"Update schedule" → Run workflow** to do the first run now (otherwise it waits for the
   daily cron). Confirm `schedule.json` gets a new commit.
5. **Open `index.html`** (double-click the file, or host it anywhere). It will load the
   freshly published `schedule.json`. Hit **Refresh** any time to re-pull.

## Notes
- The cinema board only ever shows ~3 days — that's the furthest cinemas publish.
- If a venue returns nothing on a given run, its previous data is kept (non-destructive).
- If GitHub can't be reached, `index.html` falls back to the data baked into it.
- Cron time: edit the `cron:` line in `update.yml` (`0 22 * * *` = 06:00 Taipei).
- Want to add Vie Show or change venues? Edit the `IN89`/`CULTURE` lists in `scrape.py`.
