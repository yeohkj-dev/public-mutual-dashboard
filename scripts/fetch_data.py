"""Fetch Public Mutual "Public" series unit trust prices and build data/funds.js.

Pulls the latest NAVs, EPF eligibility and fund attributes from the endpoints
behind https://www.publicmutual.com.my/Fund-Price-UT and /fund-explorer-list,
plus month-end NAV history for the chart and return calculations.

Usage:  python scripts/fetch_data.py [--years 5]
Stdlib only, so it runs as-is in GitHub Actions.
"""
import argparse
import calendar
import http.cookiejar
import json
import re
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

BASE = "https://www.publicmutual.com.my"
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "funds.js"

CATEGORY = {
    "EQ": "Equity",
    "BA": "Mixed Asset / Balanced",
    "BF": "Bond / Fixed Income",
    "MM": "Money Market",
    "OA": "Fund-of-Funds",
}
MANDATE = {"LOCAL": "Malaysia only", "FOREIGN": "Foreign", "MIX": "Malaysia + Foreign"}

# Investment focus inferred from the fund name (first match wins).
REGION_RULES = [
    (r"\bCHINA\b", "China"),
    (r"\bINDIA\b", "India"),
    (r"INDONESIA", "Indonesia"),
    (r"VIETNAM", "Vietnam"),
    (r"JAPAN", "Japan"),
    (r"SINGAPORE", "Singapore"),
    (r"AUSTRALIA", "Australia"),
    (r"\bU\.?S\.?\b", "United States"),
    (r"\bASEAN\b|SOUTH-EAST ASIA", "ASEAN"),
    (r"FAR-EAST|FAR EAST|ASIA|PACIFIC|REGIONAL", "Asia Pacific"),
    (r"GLOBAL|WORLD|INTERNATIONAL", "Global"),
]
THEME_RULES = [
    (r"TECHNOLOGY|DIGITAL|INNOVATIVE|ARTIFICIAL", "Technology"),
    (r"HEALTH", "Healthcare"),
    (r"REIT|PROPERTY", "REITs / Property"),
    (r"SUKUK|BOND", "Bonds / Sukuk"),
    (r"MONEY MARKET|CASH", "Cash / Money Market"),
    (r"DIVIDEND|INCOME", "Dividend / Income"),
    (r"SMALL|EMERGING", "Small & Mid Cap"),
    (r"SUSTAINABLE|ESG|CARBON|GREEN|CLIMATE", "Sustainability / ESG"),
    (r"GOLD", "Gold"),
    (r"INFRASTRUCTURE|INDUSTRY|TELCO|CONSUMER|SECTOR|LIFESTYLE", "Sector / Thematic"),
    (r"INDEX", "Index tracking"),
    (r"GROWTH|AGGRESSIVE|STRATEGIC|SELECT|OPPORTUNIT|FOCUS|ALPHA", "Growth"),
]


class Client:
    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.tokens = {}

    def _get(self, path, headers=None):
        req = urllib.request.Request(BASE + path, headers={"User-Agent": "Mozilla/5.0", **(headers or {})})
        for attempt in range(3):
            try:
                with self.opener.open(req, timeout=60) as r:
                    return r.read().decode("utf-8")
            except Exception as e:  # noqa: BLE001 - retry any network error
                if attempt == 2:
                    raise
                print(f"  retry {path}: {e}", file=sys.stderr)
                time.sleep(3)

    def token(self, page):
        if page not in self.tokens:
            html = self._get(page)
            m = re.search(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"', html)
            if not m:
                raise RuntimeError(f"No verification token on {page}")
            self.tokens[page] = m.group(1)
        return self.tokens[page]

    def api(self, page, path):
        body = self._get(path, {"RequestVerificationToken": self.token(page), "Content-Type": "application/json"})
        return json.loads(body).get("ResultData") or []

    def prices(self, d=None):
        q = d.strftime("%d-%m-%Y") if d else ""
        return self.api("/Fund-Price-UT", f"/FundPriceUT/GetAllUTFundPriceByDate?date={q}")

    def explorer(self):
        return self.api("/fund-explorer-list", "/FundExplorerList/GetFundExplorerData?date=")


def is_public_series(f):
    return not f["IsPbFund"] and not f["IsESeriesFund"]


def match(rules, name, default):
    for pattern, label in rules:
        if re.search(pattern, name):
            return label
    return default


def month_ends(latest, years):
    out = []
    y, m = latest.year, latest.month
    for _ in range(years * 12 + 1):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        out.append(date(y, m, calendar.monthrange(y, m)[1]))
    return out


def shift_months(d, n):
    m = d.month - 1 - n
    y = d.year + m // 12
    m = m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=5)
    args = ap.parse_args()

    c = Client()
    print("Fetching latest prices...")
    latest_rows = [f for f in c.prices() if is_public_series(f)]
    latest = datetime.fromisoformat(latest_rows[0]["Date"]).date()
    print(f"  {len(latest_rows)} Public series funds, price date {latest}")

    explorer = {f["FundAbbr"]: f for f in c.explorer()}

    # Snapshot dates: month-ends for the chart, plus exact anchors for returns.
    targets = set(month_ends(latest, args.years))
    for n in (1, 3, 6, 12, 36, 60):
        targets.add(shift_months(latest, n))
    targets.add(date(latest.year - 1, 12, 31))
    targets = sorted(t for t in targets if t < latest)

    wanted = {f["FundAbbr"] for f in latest_rows}
    history = {}  # iso date -> {abbr: nav}
    for i, t in enumerate(targets, 1):
        d, actual, navs = t, None, {}
        # Walk back over weekends / holidays. Foreign funds skip their own
        # market holidays, so keep going a few days to fill those gaps too.
        for _ in range(12):
            rows = c.prices(d)
            time.sleep(0.2)
            d -= timedelta(days=1)
            if not rows:
                continue
            actual = actual or datetime.fromisoformat(rows[0]["Date"]).date().isoformat()
            for f in rows:
                if is_public_series(f) and f["FundAbbr"] not in navs:
                    navs[f["FundAbbr"]] = f["Nav"]
            if wanted <= navs.keys() or (t - d).days > 7:
                break
        if not actual:
            print(f"  [{i}/{len(targets)}] {t}: no data", file=sys.stderr)
            continue
        history[actual] = navs
        print(f"  [{i}/{len(targets)}] {t} -> {actual} ({len(navs)} funds)")

    history[latest.isoformat()] = {f["FundAbbr"]: f["Nav"] for f in latest_rows}
    dates = sorted(history)

    funds = []
    for f in latest_rows:
        abbr, name = f["FundAbbr"], f["FundDesc"]
        x = explorer.get(abbr, {})
        mandate = f["ForeignExposureCode"]
        if mandate == "LOCAL":
            region = "Malaysia"
        elif mandate == "MIX":
            region = match(REGION_RULES, name, "Malaysia + Regional")
        else:
            region = match(REGION_RULES, name, "Global / Multi-region")
        funds.append({
            "code": f["FundCode"],
            "name": name,
            "abbr": abbr,
            "nav": f["Nav"],
            "change": f["Change"],
            "changePct": f["ChangePercent"],
            "date": latest.isoformat(),
            "currency": f["CurrencyCode"],
            "category": CATEGORY.get(f["FundCategoryCode"], f["FundCategoryCode"]),
            "mandate": MANDATE.get(mandate, mandate),
            "region": region,
            "theme": match(THEME_RULES, name, "Diversified"),
            "islamic": f["IsIslamic"],
            "epf": x.get("IsEpfQualified"),  # None = not listed in Fund Explorer
            "risk": x.get("RiskLevel"),
            "distribution": x.get("DistPolicy"),
            "history": [history[d].get(abbr) for d in dates],
        })

    payload = {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "priceDate": latest.isoformat(),
        "source": BASE + "/Fund-Price-UT",
        "dates": dates,
        "funds": funds,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("window.FUND_DATA = " + json.dumps(payload, separators=(",", ":")) + ";\n", encoding="utf-8")
    print(f"Wrote {OUT} ({len(funds)} funds, {len(dates)} dates)")


if __name__ == "__main__":
    main()
