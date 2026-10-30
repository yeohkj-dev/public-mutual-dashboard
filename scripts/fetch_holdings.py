"""Extract each fund's holdings from Public Mutual's latest annual / semi-annual report.

Reports come from https://www.publicmutual.com.my/funds-report-ut and
/funds-report-prs (the "Fund Report / Fund Fact Sheet" pages). The
"INVESTMENTS - <date>" section of each report lists every holding with its
% of NAV, grouped by asset class, country and sector.

Writes data/holdings.js. Reports already parsed (same document id) are reused,
so re-runs only download reports that changed.

Usage:  python scripts/fetch_holdings.py [--only PAIF,PBOND]
Needs:  pip install pymupdf
"""
import argparse
import base64
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_data import BASE, Client  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "holdings.js"
FUNDS = ROOT / "data" / "funds.js"
PREFIX = "window.FUND_HOLDINGS = "

SOURCES = {
    "ut": ("/funds-report-ut", "/ECommunicationUT"),
    "prs": ("/funds-report-prs", "/ECommunicationPRS"),
}

COUNTRIES = {
    "Australia", "Austria", "Belgium", "Bermuda", "Brazil", "Canada", "Cayman Islands", "China", "Denmark",
    "Finland", "France", "Germany", "Hong Kong", "India", "Indonesia", "Ireland", "Israel", "Italy", "Japan",
    "Jersey", "Korea", "South Korea", "Luxembourg", "Malaysia", "Mexico", "Netherlands", "New Zealand", "Norway",
    "Philippines", "Singapore", "Spain", "Sweden", "Switzerland", "Taiwan", "Thailand", "United Kingdom",
    "United States", "Vietnam", "Saudi Arabia", "United Arab Emirates", "Qatar", "Kuwait", "Uruguay",
    "Outside Malaysia",
}
NUM = re.compile(r"^\(?-?[\d,]+(\.\d+)?\)?$|^#$|^-$")
HEADING_RE = re.compile(r"(INVESTMENTS|FINANCIAL INSTRUMENTS)\s*-\s*(\d{1,2}\s[A-Za-z]+\s\d{4})")


def to_pct(tok):
    if tok in ("#", "-"):
        return 0.05 if tok == "#" else 0.0
    return float(tok.strip("()").replace(",", ""))


def clean(text):
    text = re.sub(r"\s*\(cont[’']d\)", "", text)
    text = re.sub(r"\s*\(related party\)", "", text)
    text = re.sub(r"(\w)- (\w)", r"\1-\2", text)  # re-join hyphenated line breaks
    text = text.replace("ﬁ ", "fi").replace("ﬁ", "fi").replace("ﬂ", "fl")  # ligatures
    return re.sub(r"\s+", " ", text).strip()


def column_lines(spans):
    """Group spans into lines: [(bold, name, [numbers])] top to bottom."""
    rows = {}
    for sp in spans:
        rows.setdefault(round(sp["bbox"][3]), []).append(sp)
    heads = [sp["bbox"][0] for sp in spans if set(sp["text"].split()) & {"Fair", "Nominal", "Quantity", "Cost"}]
    num_x = min(heads) - 25
    out = []
    for key in sorted(rows):
        names, nums, bold = [], [], True
        for sp in sorted(rows[key], key=lambda sp: sp["bbox"][0]):
            t = sp["text"].strip()
            if not t:
                continue
            if sp["bbox"][0] >= num_x and NUM.match(t):
                nums.append(t)
            else:
                names.append(t)
                bold = bold and ("Bold" in sp["font"] or bool(sp["flags"] & 16))
        out.append((bold and bool(names), clean(" ".join(names)), nums))
    return out


def parse_report(pdf_bytes):
    """Return holdings [{name, pct, asset, country, sector}] and the 'as at' date.

    Headings (asset class, country, sector) are bold; holding names are regular
    weight and may wrap over several lines, with the figures on the last line.
    Only page halves that carry the "Fair ... Percent of NAV" table header are
    read, which skips the asset-allocation summary and other-language pages.
    """
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    holdings, as_at = [], None
    asset = country = sector = None
    in_section = False
    for page in doc:
        text = page.get_text()
        m = HEADING_RE.search(text)
        if m:
            in_section = True
            as_at = as_at or m.group(2)
        if not in_section:
            continue
        width = page.rect.width
        spans = [sp for b in page.get_text("dict")["blocks"] for l in b.get("lines", []) for sp in l["spans"]]
        found = False
        for lo, hi in ((0, width / 2), (width / 2, width)):
            col = [sp for sp in spans if lo <= sp["bbox"][0] < hi]
            words = {w for sp in col for w in sp["text"].split()}
            if not {"Fair", "Percent"} <= words:
                continue
            found = True
            pending, prev_heading = [], None
            for bold, name, nums in column_lines(col):
                if not name and not nums:
                    continue
                if (name.upper() == "TOTAL" and nums) or name.startswith("Effective yield"):
                    return holdings, as_at  # end of the holdings list
                if re.match(r"-\s*[A-Za-z]", name):
                    pending = []  # "- Equity securities" style rows belong to summary tables
                    continue
                if name.upper().startswith("TOTAL") or name.startswith("#") or "•" in name:
                    pending, prev_heading = [], None
                    continue
                if len(nums) >= 2 and name or (len(nums) >= 2 and pending):
                    full = clean(" ".join(pending + [name]))
                    pct = to_pct(nums[-1])
                    if full and pct <= 100:
                        holdings.append({"name": full, "pct": pct, "asset": asset, "country": country, "sector": sector})
                    pending, prev_heading = [], None
                    continue
                if nums:  # subtotal row
                    pending, prev_heading = [], None
                    continue
                if not bold:
                    pending.append(name)
                    prev_heading = None
                    continue
                if HEADING_RE.search(name.upper()) or re.match(r"\d+\.", name):
                    continue
                if set(name.split()) & {"Fair", "Percent", "Nominal", "Quantity", "NAV"} or re.fullmatch(r"[\W\d%]*|MYR.*|\(in.*", name):
                    continue
                letters = re.sub(r"[^A-Za-z]", "", name)
                caps = letters.isupper() and len(letters) > 3
                pending = []
                if caps:
                    asset = clean(asset + " " + name.title()) if prev_heading == "asset" else name.title()
                    country = sector = None
                    prev_heading = "asset"
                elif name in COUNTRIES:
                    country, sector, prev_heading = name, None, "country"
                else:
                    sector = clean(sector + " " + name).replace("Ringgit denominated", "Ringgit-denominated") if prev_heading == "sector" else name
                    prev_heading = "sector"
        if in_section and not found and holdings:
            break  # holdings section has ended
    return holdings, as_at


def summarise(holdings):
    def group(key):
        if not any(h[key] for h in holdings):
            return []
        out = {}
        for h in holdings:
            k = h[key] or "Unspecified"
            out[k] = round(out.get(k, 0) + h["pct"], 2)
        return sorted(([k, v] for k, v in out.items()), key=lambda kv: -kv[1])

    return {
        "count": len(holdings),
        "top": sorted(holdings, key=lambda h: -h["pct"])[:10],
        "byCountry": group("country"),
        "bySector": group("sector"),
        "byAsset": group("asset"),
    }


def load_existing():
    if OUT.exists():
        body = OUT.read_text(encoding="utf-8")
        return json.loads(body[len(PREFIX):].rstrip().rstrip(";"))
    return {"funds": {}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated fund abbreviations to (re)parse")
    args = ap.parse_args()
    only = set(args.only.split(",")) if args.only else None

    body = FUNDS.read_text(encoding="utf-8")
    data = json.loads(body[body.index("{"):].rstrip().rstrip(";"))
    wanted = {k: {f["code"]: f["abbr"] for f in s["funds"]} for k, s in data["schemes"].items()}

    existing = load_existing()
    result = {}
    c = Client()
    for scheme, (page, api) in SOURCES.items():
        for code, abbr in wanted[scheme].items():
            if only and abbr not in only:
                if abbr in existing["funds"]:
                    result[abbr] = existing["funds"][abbr]
                continue
            reports = c.api(page, f"{api}/GetFundReportBySchemeCode?schemeCode={code}")
            reports = [r for r in reports if r.get("E_DocId")]
            if not reports:
                print(f"{abbr}: no report", file=sys.stderr)
                continue
            latest = max(reports, key=lambda r: datetime.strptime(r["Date"], "%d/%m/%Y"))
            prev = existing["funds"].get(abbr)
            if prev and prev.get("docId") == latest["E_DocId"] and not only:
                result[abbr] = prev
                continue
            doc = c.api(page, f"{api}/DownloadDocByDocId?docId={latest['E_DocId']}")
            try:
                holdings, as_at = parse_report(base64.b64decode(doc["FileBytes"]))
            except Exception as e:  # noqa: BLE001 - one bad PDF shouldn't stop the run
                print(f"{abbr}: parse failed: {e}", file=sys.stderr)
                continue
            report_date = datetime.strptime(latest["Date"], "%d/%m/%Y")
            if as_at:
                report_date = datetime.strptime(" ".join(as_at.split()).title(), "%d %B %Y")
            result[abbr] = {
                "docId": latest["E_DocId"],
                "report": latest["Type"],
                "asAt": report_date.date().isoformat(),
                "url": BASE + page,
                **summarise(holdings),
            }
            total = sum(h["pct"] for h in holdings)
            print(f"{abbr}: {latest['Type']} {as_at} - {len(holdings)} holdings, {total:.1f}% of NAV")
            time.sleep(0.3)

    payload = {"generated": datetime.now().isoformat(timespec="seconds"), "funds": result}
    OUT.write_text(PREFIX + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
    print(f"Wrote {OUT} ({len(result)} funds)")


if __name__ == "__main__":
    main()
