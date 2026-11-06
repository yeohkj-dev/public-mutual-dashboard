# Handoff guide for Claude (or any AI assistant)

If the owner says "go read the link" or points you at
<https://github.com/yeohkj-dev/public-mutual-dashboard>, this file is where to start.
It explains what the project is, how it keeps itself updated, and how to continue the work.

用户以后只需要说"去看这个链接继续"，Claude 读完这份文件就知道怎么接手。

## What this is

A static dashboard of Public Mutual (Malaysia) funds, published on GitHub Pages:

- Live page: <https://yeohkj-dev.github.io/public-mutual-dashboard/>
- Repo: <https://github.com/yeohkj-dev/public-mutual-dashboard> (owner: `yeohkj-dev`)

It covers:

- **Unit trust:** the "Public" series only (not PB, not Public e-Series), split into EPF qualified vs non-EPF.
- **PRS:** Private Retirement Scheme funds, split into conventional vs Islamic (EPF does not apply).
- Per fund: name, abbreviation, price (NAV), price date, daily change, EPF status, asset class, region, theme, risk level, returns (1M, 3M, 6M, YTD, 1Y, 3Y p.a., 5Y p.a.), 5-year chart, top 10 holdings.
- Top 10 rankings, a world indices table and chart, and a benchmark-index overlay on the fund chart.
- **Drop alert banner:** flags top 10 EPF funds (by 1-year return) that are more than 10% below their 5-year month-end high. Constants `ALERT_DROP` and `ALERT_TOP` in `index.html`. The owner wants this shown on the page only (no email, no GitHub issue).

## It updates itself — no Claude needed

`.github/workflows/update-data.yml` runs on GitHub's servers every day:

- Scheduled for 04:00 UTC (12:00 noon Malaysia time). GitHub usually starts it 30–50 minutes late; new data is live around 1 pm MYT.
- It runs the three scripts, commits changed `data/*.js` files as `github-actions[bot]`, and GitHub Pages redeploys.
- It uses the repo's built-in `GITHUB_TOKEN`. It does **not** depend on any Claude account, API key, or the owner's computer.
- Holdings and indices steps are `continue-on-error`, so a bad day on those sources never blocks the price update. Each script keeps previous data for anything it fails to fetch.
- If a scheduled run fails, GitHub emails the repo owner.
- GitHub pauses scheduled workflows in public repos after 60 days with no repository activity. The daily data commit counts as activity, so this only matters if runs stop committing for two months. Re-enable on the Actions tab if it ever happens.

Check on it:

```bash
gh run list -R yeohkj-dev/public-mutual-dashboard --limit 10
```

Run it by hand (or use the "Run workflow" button on the Actions tab):

```bash
gh workflow run update-data.yml -R yeohkj-dev/public-mutual-dashboard
```

## Files

| Path | What it is |
|---|---|
| `index.html` | The whole dashboard: HTML, CSS and plain JavaScript, no build step, no libraries. Charts are hand-drawn SVG. |
| `data/funds.js` | `window.FUND_DATA` — prices and month-end NAV history (5 years) for `schemes.ut` and `schemes.prs` |
| `data/holdings.js` | `window.FUND_HOLDINGS` — per-fund top 10 holdings and country / sector / asset breakdowns, keyed by fund abbreviation |
| `data/indices.js` | `window.WORLD_INDICES` — 18 world indices: level, returns, weekly closes |
| `scripts/fetch_data.py` | Prices (stdlib only) |
| `scripts/fetch_holdings.py` | Holdings from report PDFs (needs `pymupdf`) |
| `scripts/fetch_indices.py` | World indices (stdlib only) |
| `.github/workflows/update-data.yml` | The daily job |

Data files are `.js` (not `.json`) so `index.html` also works when opened straight from disk.

## Data sources and how they are read

All Public Mutual endpoints need a session cookie plus the `__RequestVerificationToken` hidden field from the matching HTML page; `Client` in `fetch_data.py` handles this.

- **Prices:** `/FundPriceUT/GetAllUTFundPriceByDate?date=dd-MM-yyyy` (token from `/Fund-Price-UT`) and `/FundPricePRS/GetAllPrsFundPriceByDate` (token from `/fund-price-prs`). Empty `date` = latest. Unit trust "Public" series = `IsPbFund == false and IsESeriesFund == false`.
- **History:** the same endpoint for month-end dates plus exact return anchors. Foreign funds skip their own market holidays, so the script walks back up to a week to fill gaps.
- **EPF, risk level, distribution policy:** `/FundExplorerList/GetFundExplorerData` (token from `/fund-explorer-list`), field `IsEpfQualified`.
- **Holdings:** latest annual / semi-annual report PDF via `/ECommunicationUT/GetFundReportBySchemeCode` + `/DownloadDocByDocId` (PRS: `/ECommunicationPRS/...`). The parser reads the "INVESTMENTS - <date>" / "FINANCIAL INSTRUMENTS - <date>" table: bold lines are headings (asset class in caps, country, sector), regular lines are holdings, the last number on a row is % of NAV, and a bare "TOTAL" row ends the list. Reports are cached by document id, so only new reports are downloaded. Money-market reports list no individual holdings.
- **Region / theme:** inferred from the fund name plus the Local / Foreign / Mix mandate tag (`REGION_RULES`, `THEME_RULES` in `fetch_data.py`).
- **World indices:** Yahoo Finance chart API (`query1.finance.yahoo.com/v8/finance/chart/<symbol>`), unofficial, no key. SET (Thailand) and VN-Index have no history there, so they are left out. Stooq is behind a bot check; don't use it.

## Known limits (tell the owner when relevant)

- Returns are price (NAV) returns; dividends are not added back, so income funds look lower than their total return. A dividend payout can also trigger the drop alert.
- "High" for the alert is the highest **month-end** price in 5 years, so the true peak may be higher.
- Holdings can be several months old (they come from the latest report).
- Index levels are in local currency, while funds are in ringgit.

## Working on it

- Preview locally: `python -m http.server 8765` in the repo folder, then open <http://localhost:8765>.
- The bot commits data every day, so always `git pull --rebase origin main` before pushing. If `data/*.js` conflicts, keep whichever is newer, or just re-run the scripts.
- After changing a script, run it locally once and check the page before pushing; then trigger the workflow and check the run succeeds.
- Keep `index.html` dependency-free and working on a phone (no horizontal scroll at 375px).

## Owner's preferences

- Writes in English or Chinese; reply in the same language.
- Wants results and reports as plain **HTML files**, not Claude Artifacts.
- Push to GitHub when they ask; the GitHub CLI on their machine is signed in as `yeohkj-dev`.
- Not investment advice: keep the page's disclaimer.
