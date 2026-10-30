"""Fetch world stock market indices for reference alongside the funds.

Uses Yahoo Finance's public chart data (unofficial; no key needed). Writes
data/indices.js with the latest level, returns and weekly closes for 5 years.

Usage:  python scripts/fetch_indices.py
Stdlib only.
"""
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "indices.js"

# (symbol, display name, market / region, group)
INDICES = [
    ("^KLSE", "FBM KLCI", "Malaysia", "Asia"),
    ("^STI", "Straits Times Index", "Singapore", "Asia"),
    ("^JKSE", "Jakarta Composite", "Indonesia", "Asia"),
    ("^HSI", "Hang Seng", "Hong Kong", "Asia"),
    ("000001.SS", "Shanghai Composite", "China", "Asia"),
    ("^TWII", "Taiwan Weighted", "Taiwan", "Asia"),
    ("^KS11", "KOSPI", "South Korea", "Asia"),
    ("^N225", "Nikkei 225", "Japan", "Asia"),
    ("^BSESN", "BSE Sensex", "India", "Asia"),
    ("^AXJO", "S&P/ASX 200", "Australia", "Asia"),
    ("^GSPC", "S&P 500", "United States", "Americas"),
    ("^IXIC", "Nasdaq Composite", "United States", "Americas"),
    ("^DJI", "Dow Jones Industrial", "United States", "Americas"),
    ("^STOXX50E", "Euro Stoxx 50", "Eurozone", "Europe"),
    ("^FTSE", "FTSE 100", "United Kingdom", "Europe"),
    ("^GDAXI", "DAX", "Germany", "Europe"),
    ("URTH", "MSCI World (iShares ETF)", "Global", "Global"),
    ("GC=F", "Gold (USD/oz)", "Global", "Commodity"),
]

PERIODS = {"1M": 1, "3M": 3, "6M": 6, "1Y": 12, "3Y": 36, "5Y": 60}


def chart(symbol):
    # A little over 5 years, so the 5Y return has a starting point.
    start = int((datetime.now(timezone.utc) - timedelta(days=5 * 365 + 30)).timestamp())
    end = int(datetime.now(timezone.utc).timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}"
           f"?period1={start}&period2={end}&interval=1d")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())["chart"]["result"][0]
        except Exception as e:  # noqa: BLE001 - retry any network error
            if attempt == 2:
                raise
            print(f"  retry {symbol}: {e}", file=sys.stderr)
            time.sleep(3)


def shift_months(d, n):
    m = d.month - 1 - n
    y = d.year + m // 12
    m = m % 12 + 1
    for day in range(d.day, 0, -1):
        try:
            return date(y, m, day)
        except ValueError:
            continue


def close_on_or_before(series, target):
    """Latest close on or before target (within 10 days), else None."""
    for d, v in reversed(series):
        if d <= target:
            return v if (target - d).days <= 10 else None
    return None


def build(symbol, name, market, group):
    res = chart(symbol)
    meta = res["meta"]
    tz = timezone(timedelta(seconds=meta.get("gmtoffset", 0)))
    closes = res["indicators"]["quote"][0]["close"]
    series = [(datetime.fromtimestamp(t, tz).date(), c) for t, c in zip(res["timestamp"], closes) if c is not None]
    last_d, last = series[-1]
    prev = series[-2][1] if len(series) > 1 else None

    ret = {}
    for k, months in PERIODS.items():
        a = close_on_or_before(series, shift_months(last_d, months))
        if a:
            r = last / a
            ret[k] = round(((r ** (12 / months) - 1) if months > 12 else (r - 1)) * 100, 2)
        else:
            ret[k] = None
    ytd = close_on_or_before(series, date(last_d.year - 1, 12, 31))
    ret["YTD"] = round((last / ytd - 1) * 100, 2) if ytd else None

    # Weekly closes (last trading day of each ISO week) keep the file small.
    weekly = {}
    for d, v in series:
        weekly[d.isocalendar()[:2]] = (d, v)
    weekly = sorted(weekly.values())

    return {
        "symbol": symbol,
        "name": name,
        "market": market,
        "group": group,
        "currency": meta.get("currency"),
        "last": round(last, 2),
        "date": last_d.isoformat(),
        "dayPct": round((last / prev - 1) * 100, 2) if prev else None,
        "ret": ret,
        "dates": [d.isoformat() for d, _ in weekly],
        "closes": [round(v, 2) for _, v in weekly],
    }


def main():
    out = []
    for symbol, name, market, group in INDICES:
        try:
            out.append(build(symbol, name, market, group))
            print(f"{name}: {out[-1]['last']} ({out[-1]['date']})")
        except Exception as e:  # noqa: BLE001 - skip one bad symbol, keep the rest
            print(f"{name} ({symbol}) failed: {e}", file=sys.stderr)
        time.sleep(0.3)
    payload = {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "source": "Yahoo Finance",
        "indices": out,
    }
    OUT.write_text("window.WORLD_INDICES = " + json.dumps(payload, separators=(",", ":")) + ";\n", encoding="utf-8")
    print(f"Wrote {OUT} ({len(out)} indices)")


if __name__ == "__main__":
    main()
