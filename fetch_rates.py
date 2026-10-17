#!/usr/bin/env python3
"""Roscap rates feed.

Downloads the three reference rates shown on the roscap.co.uk home page and writes
rates.json next to this file. Runs on a schedule (GitHub Actions); the website reads
the resulting file. The visitor's browser never calls the sources directly.

Sources (public, free, no keys):
  US Federal Funds Rate      FRED CSV, series DFEDTARU (target range upper) and DFEDTARL (lower)
  Bank of England Base Rate  the Bank's own Bank Rate history page
  EURIBOR 3-Month            daily fixings table on euribor-rates.eu

Rules: standard library only; if a source cannot be read or parsed, keep that rate's
previous values from the existing rates.json and mark it stale; never write zeros.
"""
import datetime as dt
import html
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

OUT = Path(__file__).with_name("rates.json")
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; roscap-rates-feed/1.0; +https://www.roscap.co.uk)"}


def get(url, timeout=40):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def table_rows(page_html):
    """Yield the text cells of every <tr> in a page."""
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", page_html, flags=re.S):
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, flags=re.S)
        yield [html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in cells]


def fmt_change(x, decimals):
    sign = "+" if x > 0 else ""
    return f"{sign}{x:.{decimals}f}%"


def fred_series(series_id):
    """(date, value) rows, oldest first, missing values skipped."""
    rows = []
    for line in get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}").splitlines()[1:]:
        parts = line.split(",")
        if len(parts) < 2 or parts[1].strip() in ("", "."):
            continue
        rows.append((parts[0].strip(), float(parts[1])))
    if not rows:
        raise ValueError(f"FRED {series_id}: no rows")
    return rows


def last_move(rows):
    """Latest value, its date, the previous different value, and the date the latest value started."""
    latest_date, latest = rows[-1]
    started = latest_date
    previous = None
    for d, v in reversed(rows):
        if v != latest:
            previous = v
            break
        started = d
    return latest, latest_date, previous, started


def fed():
    upper = fred_series("DFEDTARU")
    lower = fred_series("DFEDTARL")
    hi, as_of, prev_hi, changed_on = last_move(upper)
    lo = lower[-1][1]
    change = round(hi - prev_hi, 4) if prev_hi is not None else 0.0
    return {
        "name": "US Federal Funds Rate",
        "value": hi,
        "range_low": lo,
        "range_high": hi,
        "display": f"{lo:.2f}% - {hi:.2f}%",
        "change": change,
        "change_display": fmt_change(change, 2),
        "change_basis": "size of the last Federal Reserve decision",
        "as_of": as_of,
        "changed_on": changed_on,
        "source": "Federal Reserve target range, via FRED (DFEDTARU, DFEDTARL)",
    }


def boe():
    rows = []
    for cells in table_rows(get("https://www.bankofengland.co.uk/boeapps/database/Bank-Rate.asp")):
        if len(cells) >= 2 and re.fullmatch(r"\d{1,2} \w{3} \d{2}", cells[0]):
            date = dt.datetime.strptime(cells[0], "%d %b %y").date().isoformat()
            rows.append((date, float(cells[1])))
    if len(rows) < 2:
        raise ValueError("Bank of England table not found")
    rows.sort()
    changed_on, latest = rows[-1]
    previous = rows[-2][1]
    change = round(latest - previous, 4)
    return {
        "name": "Bank of England Base Rate",
        "value": latest,
        "display": f"{latest:.2f}%",
        "change": change,
        "change_display": fmt_change(change, 2),
        "change_basis": "size of the last Bank of England decision",
        "as_of": dt.date.today().isoformat(),
        "changed_on": changed_on,
        "source": "Bank of England, Bank Rate history",
    }


def euribor():
    rows = []
    for cells in table_rows(get("https://www.euribor-rates.eu/en/current-euribor-rates/2/euribor-rate-3-months/")):
        if len(cells) >= 2 and re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", cells[0]) and "%" in cells[1]:
            m, d, y = cells[0].split("/")  # the English page uses month/day/year
            rows.append((f"{y}-{int(m):02d}-{int(d):02d}", float(cells[1].replace("%", "").strip())))
    if len(rows) < 2:
        raise ValueError("Euribor table not found")
    rows.sort()
    as_of, latest = rows[-1]
    previous = rows[-2][1]
    change = round(latest - previous, 4)
    return {
        "name": "EURIBOR 3-Month",
        "value": latest,
        "display": f"{latest:.3f}%",
        "change": change,
        "change_display": fmt_change(change, 3),
        "change_basis": "move since the previous daily fixing",
        "as_of": as_of,
        "changed_on": as_of,
        "source": "Euribor 3-month daily fixing, via euribor-rates.eu",
    }


def main():
    previous = {}
    if OUT.exists():
        try:
            previous = json.loads(OUT.read_text()).get("rates", {})
        except Exception:
            previous = {}

    now = dt.datetime.now(dt.timezone.utc)
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    # RATES_SIMULATE_FAIL=euribor (or boe / fed) pretends that source is down, to test the alert path.
    simulate = os.environ.get("RATES_SIMULATE_FAIL", "").strip().lower()

    rates, failures = {}, []
    for key, fn in (("boe", boe), ("fed", fed), ("euribor", euribor)):
        try:
            if key == simulate:
                raise RuntimeError("simulated outage requested by RATES_SIMULATE_FAIL (test, not a real failure)")
            rates[key] = dict(fn(), stale=False, fetched_at=stamp)
        except Exception as e:  # keep the last good values rather than publishing nothing
            failures.append(f"{key}: {e}")
            if key in previous:
                rates[key] = dict(previous[key], stale=True)  # keeps its old fetched_at

    if not rates:
        print("No rates fetched and no previous file to fall back on", file=sys.stderr)
        sys.exit(1)

    # "Updated" on the website means "all three numbers were last refreshed at this time", so it is
    # the OLDEST successful fetch among the three. A stale rate therefore holds the date back.
    oldest = min(r.get("fetched_at", stamp) for r in rates.values())
    oldest_dt = dt.datetime.strptime(oldest, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    out = {
        "updated": oldest,
        "updated_display": oldest_dt.strftime("%-d %B %Y"),
        "checked": stamp,
        "stale": [k for k, v in rates.items() if v.get("stale")],
        "rates": rates,
        "notes": "Change for the Fed and Bank of England is the size of the last policy decision; for Euribor it is the move since the previous daily fixing.",
    }
    OUT.write_text(json.dumps(out, indent=2) + "\n")
    print(f"wrote {OUT.name}: " + ", ".join(f"{k} {v['display']} ({v['change_display']})" for k, v in rates.items()))
    for f in failures:
        print("WARNING " + f, file=sys.stderr)
    if failures:  # the file is written; a non-zero exit makes the GitHub run show red so someone looks
        sys.exit(2)


if __name__ == "__main__":
    main()
