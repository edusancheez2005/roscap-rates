#!/usr/bin/env python3
"""Roscap rates feed.

Downloads the three reference rates shown on the roscap.co.uk home page and writes
rates.json next to this file. Runs on a schedule (GitHub Actions); the website reads
the resulting file. The visitor's browser never calls the sources directly.

Sources (public, free, no keys):
  US Federal Funds Rate      FRED CSV, series DFEDTARU (target range upper) and DFEDTARL (lower)
  Bank of England Base Rate  the Bank's own Bank Rate history page
  EURIBOR 3-Month            daily fixings table on euribor-rates.eu; when that cannot be read or is
                             behind, the Bank of Finland's daily series, then the Deutsche Bundesbank's,
                             then the Banco de Espana's (the same figure everywhere; the last two show a
                             fixing on the next working day)

Rules: standard library only; certificates are always verified (a source whose certificate does
not check out counts as unreadable, it is never read anyway); if a source cannot be read or
parsed, keep that rate's previous values from the existing rates.json and mark it stale; never
write zeros.
"""
import csv
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


def get(url, timeout=40, encoding="utf-8"):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:  # default context: certificate and host name are verified
        return r.read().decode(encoding, "replace")


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


# ---------------------------------------------------------------------------------------------
# Euribor 3-month. One benchmark, set once a day by the European Money Markets Institute; every
# source below republishes that same figure. Four sources, asked in this order:
#   1. euribor-rates.eu      a fixing appears the next calendar day (Friday's on Saturday)
#   2. Bank of Finland       the series behind the Bank's own Euribor page; it had Friday's fixing
#                            over the weekend (seen on Sunday 15 Nov 2026), ahead of the next two
#   3. Deutsche Bundesbank   official series, a fixing appears the next working day (Friday's on Monday)
#   4. Banco de Espana       official table, same delay as the Bundesbank
# The script stops at the first source that has the fixing due by now (that of the last weekday
# before today); if none has it, it uses the newest fixing any of them has.
# History: on 13-14 Nov 2026 euribor-rates.eu moved to new servers and began presenting a
# certificate from a private authority, which fails verification. The feed refused it, correctly,
# and Euribor went stale. The two central banks at the end were added on 15 Nov so that the feed no
# longer depends on one website, and the Bank of Finland the same evening because the other two
# were a working day behind. When the website's certificate is valid again it is used again
# without any change here.
EURIBOR_SITE = "https://www.euribor-rates.eu/en/current-euribor-rates/2/euribor-rate-3-months/"
EURIBOR_FINLAND = "https://www.suomenpankki.fi/api/interestrates/euribor"
EURIBOR_BUNDESBANK = "https://api.statistiken.bundesbank.de/rest/download/BBIG1/D.D0.EUR.MMKT.EURIBOR.M03.BID._Z?format=csv&lang=en"
EURIBOR_BDE = "https://www.bde.es/webbe/es/estadisticas/compartido/datos/csv/ti_1_7.csv"
SPANISH_MONTHS = {m: i for i, m in enumerate("ENE FEB MAR ABR MAY JUN JUL AGO SEP OCT NOV DIC".split(), 1)}


def clean_fixings(pairs, today):
    """(date, value) pairs -> one value per date, oldest first. Raises unless the result can be a
    run of Euribor fixings: two or more, the latest not in the future, the last two within a week
    of each other, values and the last move of a believable size."""
    rows = sorted(dict(pairs).items())
    if len(rows) < 2:
        raise ValueError("fewer than two fixings found")
    (prev_date, prev), (last_date, last) = rows[-2], rows[-1]
    if last_date > today.isoformat():
        raise ValueError(f"latest fixing dated {last_date}, in the future")
    gap = (dt.date.fromisoformat(last_date) - dt.date.fromisoformat(prev_date)).days
    if gap > 7:
        raise ValueError(f"last two fixings {gap} days apart ({prev_date}, {last_date})")
    if not (-2 < prev < 15 and -2 < last < 15) or abs(last - prev) > 0.5:
        raise ValueError(f"values out of range ({prev}, {last})")
    return rows


def euribor_site(today):
    cells = [
        (c[0], c[1]) for c in table_rows(get(EURIBOR_SITE))
        if len(c) >= 2 and re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", c[0]) and "%" in c[1]
    ]
    if not cells:
        raise ValueError("Euribor table not found")
    # The page has shown dates as month/day/year; a reader in Europe may get day/month/year. Try both
    # and keep the one that gives real dates forming a recent run (the wrong order gives impossible
    # dates, a date in the future, or "fixings" a month apart). The page also lists the first fixing
    # of each month and year again in two more tables; clean_fixings keeps one value per date.
    problems = []
    for order in ("month/day", "day/month"):
        try:
            pairs = []
            for text, value in cells:
                a, b, y = (int(x) for x in text.split("/"))
                m, d = (a, b) if order == "month/day" else (b, a)
                pairs.append((dt.date(y, m, d).isoformat(), float(value.replace("%", "").replace(",", ".").strip())))
            return clean_fixings(pairs, today)
        except ValueError as e:
            problems.append(f"as {order}: {e}")
    raise ValueError("Euribor table dates not understood (" + "; ".join(problems) + ")")


def euribor_finland(today):
    data = json.loads(get(EURIBOR_FINLAND).lstrip("﻿"))
    series = data.get("euribor3kk") if isinstance(data, dict) else None  # "3 kk": three months, in Finnish
    if not isinstance(series, list):
        raise ValueError("Euribor 3-month series not found")
    pairs = []
    for row in series:
        try:
            date, value = str(row["date"])[:10], float(row["value"])
        except (KeyError, TypeError, ValueError):  # a day with no value
            continue
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            pairs.append((date, value))
    return clean_fixings(pairs, today)


def euribor_bundesbank(today):
    pairs = []
    for line in get(EURIBOR_BUNDESBANK).splitlines():
        parts = line.split(",")
        if len(parts) >= 2 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", parts[0].strip()):
            try:
                pairs.append((parts[0].strip(), float(parts[1])))
            except ValueError:  # "." on days with no fixing (weekends, holidays)
                continue
    return clean_fixings(pairs, today)


def euribor_bde(today):
    rows = list(csv.reader(get(EURIBOR_BDE, timeout=60, encoding="latin-1").splitlines()))
    col = None
    for r in rows[:12]:  # the heading rows describe each column; find Euribor "A 3 meses"
        for i, c in enumerate(r):
            text = c.lower()
            if "eur" in text and "bor" in text and "a 3 meses" in text:
                col = i
    if col is None:
        raise ValueError("Euribor 3-month column not found")
    pairs = []
    for r in rows:
        m = re.fullmatch(r"(\d{1,2}) ([A-Z]{3}) (\d{4})", r[0].strip()) if r else None
        if not m or len(r) <= col or m.group(2) not in SPANISH_MONTHS:
            continue
        try:
            date = dt.date(int(m.group(3)), SPANISH_MONTHS[m.group(2)], int(m.group(1))).isoformat()
            pairs.append((date, float(r[col])))
        except ValueError:  # "_" on days with no fixing
            continue
    return clean_fixings(pairs, today)


EURIBOR_SOURCES = (
    ("euribor-rates.eu", "euribor-site", euribor_site),
    ("Bank of Finland", "euribor-finland", euribor_finland),
    ("Deutsche Bundesbank", "euribor-bundesbank", euribor_bundesbank),
    ("Banco de Espana", "euribor-bde", euribor_bde),
)


def expected_fixing(today):
    """The fixing that is public by now: that of the last weekday before today (a fixing may be
    republished free of charge a day after it is set). On a bank holiday there was none, and the
    script then simply asks every source."""
    day = today - dt.timedelta(days=1)
    while day.weekday() > 4:
        day -= dt.timedelta(days=1)
    return day.isoformat()


def euribor(previous=None, simulate=""):
    today = dt.date.today()
    expected = expected_fixing(today)
    held = (previous or {}).get("as_of", "")
    held_ok = bool(previous) and isinstance(held, str) and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", held)) and held <= today.isoformat()
    published = previous.get("value") if held_ok else None
    best, skipped = None, []
    for name, key, fn in EURIBOR_SOURCES:
        try:
            if key == simulate:
                raise RuntimeError("simulated outage requested by RATES_SIMULATE_FAIL (test, not a real failure)")
            rows = fn(today)
            # Same benchmark, same number: a source that gives another figure for the day already published
            # here is reading something else (another maturity, a misread page) and is not used.
            theirs = dict(rows).get(held) if isinstance(published, (int, float)) else None
            if theirs is not None and abs(theirs - published) > 0.0005:
                raise ValueError(f"gives {theirs} for {held}, where {published} is already published")
        except Exception as e:
            skipped.append(f"{name}: {e}")
            continue
        if best is None or rows[-1][0] > best[1][-1][0]:
            best = (name, rows)
        if best[1][-1][0] >= expected:
            break
    for note in skipped:  # shown in the run log; not a failure while another source answered
        print("NOTE euribor source not used, " + note, file=sys.stderr)
    if best is None:
        raise RuntimeError("no Euribor source could be used (" + "; ".join(skipped) + ")")
    name, rows = best
    as_of, latest = rows[-1]
    # Never step back: the website shows a fixing a day or more before the central banks do, so after
    # it fails they can be behind what is already published here. Keep the newer fixing until they catch up.
    if held_ok and as_of < held:
        print(f"NOTE euribor: {name} is at {as_of}; keeping the {held} fixing already published", file=sys.stderr)
        return {k: v for k, v in previous.items() if k not in ("stale", "fetched_at")}
    change = round(latest - rows[-2][1], 4)
    return {
        "name": "EURIBOR 3-Month",
        "value": latest,
        "display": f"{latest:.3f}%",
        "change": change,
        "change_display": fmt_change(change, 3),
        "change_basis": "move since the previous daily fixing",
        "as_of": as_of,
        "changed_on": as_of,
        "source": f"Euribor 3-month daily fixing, via {name}",
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

    # RATES_SIMULATE_FAIL=euribor (or boe / fed) pretends that rate cannot be read at all, to test the alert
    # path. euribor-site (or euribor-finland / euribor-bundesbank / euribor-bde) pretends one Euribor source
    # is down, to test that the next one takes over.
    simulate = os.environ.get("RATES_SIMULATE_FAIL", "").strip().lower()

    rates, failures = {}, []
    for key, fn in (("boe", boe), ("fed", fed), ("euribor", euribor)):
        try:
            if key == simulate:
                raise RuntimeError("simulated outage requested by RATES_SIMULATE_FAIL (test, not a real failure)")
            reading = euribor(previous.get("euribor"), simulate) if key == "euribor" else fn()
            rates[key] = dict(reading, stale=False, fetched_at=stamp)
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
