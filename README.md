# NQ / DXY / Gold Pre-Session Briefing System

Fully free, automated pre-session market briefing for **NQ (Nasdaq futures)**,
**DXY (Dollar Index)**, and **Gold (GC)**. Runs on **GitHub Actions cron**
(free tier) — no Railway, no paid hosting, no paid APIs.

Every trading day it generates two reports:

- **Asia pre-session** — `reports/YYYY-MM-DD-asia.md` / `.json`
- **NY pre-session** — `reports/YYYY-MM-DD-ny.md` / `.json`

---

## 1. Cost model (why this is $0/month)

| Component | What it does | Cost |
|---|---|---|
| GitHub Actions | Runs the scheduler (cron) + executes the script | Free public-repo tier: 2,000 min/month (private) or unlimited (public repo). Each run takes ~30–60s → effectively unlimited for this use case. |
| Yahoo Finance via `yfinance` | Price data for NQ, DXY, Gold, 10Y yield | Free, unofficial, no key. |
| ForexFactory public JSON feed | Macro/economic calendar | Free, unofficial, no key. |
| GitHub repo storage | Stores report history | Free. |

**No paid database, no paid hosting, no Railway.** If you ever *do* want Railway,
only use its free trial credits, never upgrade to a paid plan — but this design
doesn't need Railway at all since GitHub Actions is the scheduler.

---

## 2. Honest limitations (read this before relying on it)

1. **No free source exists for options/gamma data** (call wall, put wall, gamma
   flip, net GEX, max pain, top OI). Every provider that has this (SqueezeMetrics,
   Unusual Whales, GammaLab, etc.) is paid. This system:
   - Uses **price action + ICT-lite levels** (prior day H/L/C, swing
     liquidity pools, fair value gaps, EMA trend) automatically, for free.
   - Lets you **optionally paste your own morning gamma data** into
     `data/manual_overrides.json` (the same shorthand you already track for
     NQ/GC — spot, call wall, put wall, gamma flip, net GEX, max pain, top OI).
     If present, it's layered into the report. If absent, the report says so
     explicitly instead of pretending to have it.
   - **DXY never uses gamma** — its options chain (ICE DX) is too thin to be
     meaningful, so DXY is always price action + macro/news only, by design.
   - Because gamma data is only ever as fresh as what you commit to the repo,
     **scheduled (cron) runs will use whatever is in `manual_overrides.json`
     at that moment** — update and commit it before a run if you want gamma
     layered in, or just let scheduled runs be price-action-only and paste
     gamma manually before an ad hoc `workflow_dispatch` run.

2. **Yahoo Finance (`yfinance`) is unofficial.** No SLA, can rate-limit, data
   is delayed slightly intraday. Fine for a bias/context briefing, not for
   execution-grade signals. A fallback ticker is tried automatically per
   instrument (see `config.yaml`) if the primary has no data (e.g. futures
   rollover gaps).

3. **The macro calendar feed** (`nfs.faireconomy.media/ff_calendar_thisweek.json`)
   is a public JSON endpoint ForexFactory serves for embeddable widgets — not
   an official API. It can change shape or go down without notice. The code
   is defensive: any single malformed event is skipped, and a total failure
   degrades to "macro calendar unavailable, trade on price action only"
   rather than crashing the whole report. (In this sandbox test environment
   it returned `403 Forbidden` due to the sandbox's outbound proxy — this is
   expected here and is exactly the kind of failure the fallback logic
   handles. From a normal GitHub Actions runner or your own machine it
   should resolve fine, but treat it as best-effort regardless.)

4. **Rate limits**: neither Yahoo nor the calendar feed publishes a formal
   rate limit for this kind of light use. Two scheduled runs/day plus
   occasional manual runs is trivial traffic. Don't loop-poll either source.

5. This is a **bias/context briefing tool**, not a signal generator or
   execution system. Treat "FINAL STANCE" as a starting lens for your own
   process, validated against the checklist in each report.

---

## 3. Project structure

```
nq-dxy-gold-briefing/
├── README.md
├── requirements.txt
├── config.yaml                     # instruments, sessions, thresholds - no secrets
├── main.py                         # CLI entry point
├── app/
│   ├── config.py                   # loads config.yaml + manual overrides
│   ├── data_fetch.py                # yfinance price/yield fetch, graceful fallback
│   ├── macro_calendar.py           # free macro calendar fetch, graceful fallback
│   ├── analysis.py                 # bias logic, ICT-lite levels, yield confluence
│   ├── report_generator.py         # builds report dict + renders markdown
│   ├── storage.py                  # save/load reports, history lookups
│   └── logger.py                   # logging setup
├── data/
│   └── manual_overrides.json       # OPTIONAL: paste your gamma/options data here
├── reports/
│   └── sample/                     # example output (synthetic demo data)
├── .github/workflows/
│   ├── asia-report.yml             # cron: 0 21 * * 0-4 (UTC)
│   └── ny-report.yml               # cron: 0 11 * * 1-5 (UTC)
└── tests/
    └── test_smoke.py               # confirms pipeline survives total data-source failure
```

---

## 4. Setup steps (go live today)

1. **Create a new GitHub repo** (public repo = unlimited free Actions minutes;
   private also works, just capped at 2,000 free min/month, which is far more
   than this needs).
2. Push this entire project to that repo:
   ```bash
   git init
   git add .
   git commit -m "Initial commit: free NQ/DXY/Gold briefing system"
   git branch -M main
   git remote add origin https://github.com/<you>/<repo>.git
   git push -u origin main
   ```
3. In the repo, go to **Settings → Actions → General → Workflow permissions**
   and set it to **"Read and write permissions"** (needed so the workflow can
   commit generated reports back to the repo).
4. That's it — no secrets, no API keys, no paid plan to configure.
5. To test immediately without waiting for the cron time: go to **Actions**
   tab → select **"Asia Pre-Session Report"** or **"NY Pre-Session Report"**
   → **Run workflow** (this is the `workflow_dispatch` trigger).

---

## 5. Exact cron schedules

| Workflow | Cron (UTC) | Meaning |
|---|---|---|
| `asia-report.yml` | `0 21 * * 0-4` | 21:00 UTC, Sun–Thu → lands before Sydney/Tokyo open (~22:00 UTC), covering Mon–Fri Asia sessions |
| `ny-report.yml` | `0 11 * * 1-5` | 11:00 UTC, Mon–Fri → ~2–2.5h before NY cash open (13:30 UTC standard time) |

GitHub Actions cron always runs in **UTC**, and schedules on the free tier can
be delayed a few minutes during high load — treat run times as "around" the
stated time, not to-the-second.

Both workflows also have `workflow_dispatch:` enabled, so you can trigger
either one manually any time from the **Actions** tab.

**Daylight saving note:** NY cash open shifts between 13:30 UTC (winter) and
14:30 UTC (summer DST). The cron above is fixed at 11:00 UTC year-round; if
you want tighter timing you can hardcode two schedules with a comment for
DST season, or just accept the ~1h buffer difference (still pre-session).

---

## 6. Local commands

```bash
# install deps
pip install -r requirements.txt

# generate a report right now
python main.py generate asia
python main.py generate ny

# show the most recently generated report
python main.py latest

# show the last 5 reports (any session)
python main.py history --n 5

# show a specific saved report
python main.py show --date 2026-07-18 --session asia
python main.py show --date 2026-07-18 --session ny

# run the smoke tests (no network required)
python -m pytest tests/ -v
```

---

## 7. Retrieving old reports

All reports are plain files committed to the repo under `reports/`, so you
can always:

- Browse them directly on GitHub (`reports/2026-07-18-asia.md`)
- `git pull` and read locally
- Use the CLI: `python main.py show --date 2026-07-18 --session asia`
- Use `python main.py history --n 5` to dump the last 5 reports for a quick
  side-by-side read (redirect to a file if you want to diff them:
  `python main.py history --n 5 > last5.txt`)

Nothing is stored in a database — the git history of `reports/*.json` and
`*.md` **is** the database. This is what makes it free and zero-maintenance.

---

## 8. Layering in your daily gamma/options data (optional)

Since call wall / put wall / gamma flip / net GEX / max pain / top OI have no
free API, paste your existing morning shorthand into
`data/manual_overrides.json` before running (or committing before a
scheduled run), in this shape:

```json
{
  "NQ": {
    "spot": 19850,
    "call_wall": 19900,
    "put_wall": 19700,
    "gamma_flip": 19800,
    "net_gex": "+1.2B",
    "max_pain": 19800,
    "top_oi": "19800C (exp 2026-07-18)"
  },
  "GC": {
    "spot": 2415,
    "call_wall": 2430,
    "put_wall": 2390,
    "gamma_flip": 2410,
    "net_gex": "-300M",
    "max_pain": 2410,
    "top_oi": "2430C (exp 2026-07-18)"
  }
}
```

DXY intentionally has no gamma section — it's always price-action + macro
only. If the file is missing or empty, reports still generate normally and
just state gamma data wasn't available for that run.

---

## 9. What "FINAL STANCE" means

Computed from NQ + Gold bias agreement (a simple risk-on/risk-off proxy pair),
with the 10Y yield direction folded in as a confluence note (not a hard
override):

- **BULLISH** — both NQ and Gold showing bullish bias
- **BEARISH** — both NQ and Gold showing bearish bias
- **NEUTRAL / WAIT** — mixed or unclear signals
- **WAIT** — insufficient/no data this run

This is intentionally simple and transparent (not a black box) — the full
reasoning (HTF trend, levels, yield direction, DXY/Gold confluence) is shown
above it in every report so you can override it with your own read.

---

## 10. Extending it

- Add more instruments: add an entry under `instruments:` in `config.yaml`
  with a valid Yahoo Finance ticker.
- Change session timing: edit the `cron:` line in the two workflow files.
- Swap the macro source: replace the URL in `macro_calendar.py` /
  `config.yaml` — the parser is defensive but you may need to adjust field
  names if you point it at a different feed's JSON schema.
