"""Tests for the Euribor part of fetch_rates.py. Standard library only, no network:
    python -m unittest -v
"""
import datetime as dt
import unittest
from unittest import mock

import fetch_rates as fr

TODAY = dt.date(2026, 11, 15)  # a Sunday; the latest fixing that can be public is Friday 13 Nov


def site_page(rows, extra=()):
    """A page shaped like the website's: a daily table, then the monthly and yearly tables."""
    def table(pairs):
        return "<table>" + "".join(f"<tr><td>{d}</td><td>{v} %</td></tr>" for d, v in pairs) + "</table>"
    return "<html><body>" + table(rows) + table(extra) + "</body></html>"


US_PAGE = site_page(
    [("11/13/2026", "2.775"), ("11/12/2026", "2.766"), ("11/11/2026", "2.754"), ("11/10/2026", "2.738"),
     ("11/9/2026", "2.773"), ("11/6/2026", "2.794"), ("11/5/2026", "2.812"), ("11/4/2026", "2.759"),
     ("11/3/2026", "2.765"), ("11/2/2026", "2.714")],
    extra=[("11/2/2026", "2.714"), ("10/1/2026", "2.650"), ("1/2/2026", "2.030")],
)
EU_PAGE = site_page(
    [("13/11/2026", "2.775"), ("12/11/2026", "2.766"), ("11/11/2026", "2.754"), ("10/11/2026", "2.738"),
     ("09/11/2026", "2.773"), ("06/11/2026", "2.794"), ("05/11/2026", "2.812"), ("04/11/2026", "2.759"),
     ("03/11/2026", "2.765"), ("02/11/2026", "2.714")],
    extra=[("02/11/2026", "2.714"), ("01/10/2026", "2.650"), ("02/01/2026", "2.030")],
)
BUNDESBANK_CSV = "﻿" + "\n".join([
    '"",BBIG1.D.D0.EUR.MMKT.EURIBOR.M03.BID._Z,BBIG1.D.D0.EUR.MMKT.EURIBOR.M03.BID._Z_FLAGS',
    '"",Money market rates / EURIBOR (R)  three-month funds / Daily quotations / ST0316,',
    "last update,2026-11-13 12:59:53,",
    "2026-11-06,2.794,",
    "2026-11-07,.,No value available",
    "2026-11-08,.,No value available",
    "2026-11-09,2.773,",
    "2026-11-10,2.738,",
    "2026-11-11,2.754,",
    "2026-11-12,2.766,",
])
BDE_CSV = "\n".join([
    '"CÓDIGO DE LA SERIE",D_DNBAA572,D_DNBAC172,D_DNBAD172,D_DNBAE172',
    '"DESCRIPCIÓN DE LA SERIE","Tipos de interés. UEM. STR. 1 día","Tipos de interés. UEM. Mercado monetario. Euríbor. A 1 mes","Tipos de interés. UEM. Mercado monetario. Euríbor. A 3 meses","Tipos de interés. UEM. Mercado monetario. Euríbor. A 6 meses"',
    '"FRECUENCIA","LABORABLE","DIARIA","DIARIA","DIARIA"',
    '"09 NOV 2026","2.442","2.476","2.773","3.001"',
    '"10 NOV 2026","2.442","2.475","2.738","3.018"',
    '"11 NOV 2026","2.439","_","_","3.010"',
    '"12 NOV 2026","2.443","2.479","2.766","3.023"',
    '"FUENTE","","REFINITIV","REFINITIV","REFINITIV"',
])


class CleanFixings(unittest.TestCase):
    def test_one_value_per_date_oldest_first(self):
        rows = fr.clean_fixings([("2026-11-12", 2.766), ("2026-11-11", 2.754), ("2026-11-12", 2.766)], TODAY)
        self.assertEqual(rows, [("2026-11-11", 2.754), ("2026-11-12", 2.766)])

    def test_refuses_what_cannot_be_fixings(self):
        for pairs in (
            [("2026-11-12", 2.766)],                                 # only one
            [("2026-11-12", 2.766), ("2026-11-16", 2.775)],          # latest in the future
            [("2026-10-12", 2.700), ("2026-11-12", 2.766)],          # a month apart
            [("2026-11-11", 2.754), ("2026-11-12", 27.66)],          # not a rate
            [("2026-11-11", 2.754), ("2026-11-12", 3.766)],          # a one-day move of a full point
        ):
            with self.assertRaises(ValueError):
                fr.clean_fixings(pairs, TODAY)


class Website(unittest.TestCase):
    def read(self, page, today=TODAY):
        with mock.patch.object(fr, "get", return_value=page):
            return fr.euribor_site(today)

    def test_month_day_year_page(self):
        rows = self.read(US_PAGE)
        self.assertEqual(rows[-2:], [("2026-11-12", 2.766), ("2026-11-13", 2.775)])

    def test_day_month_year_page(self):
        rows = self.read(EU_PAGE)
        self.assertEqual(rows[-2:], [("2026-11-12", 2.766), ("2026-11-13", 2.775)])
        self.assertEqual(rows[0], ("2026-01-02", 2.03))

    def test_dates_that_read_either_way(self):
        # the first twelve days of a month: every date is a valid date in both orders
        days = [12, 11, 10, 9, 8, 5, 4, 3, 2, 1]
        values = [f"{2.70 + d / 1000:.3f}" for d in days]
        dmy = site_page([(f"{d:02d}/06/2026", v) for d, v in zip(days, values)])
        mdy = site_page([(f"6/{d}/2026", v) for d, v in zip(days, values)])
        for page in (dmy, mdy):
            rows = self.read(page, today=dt.date(2026, 6, 13))
            self.assertEqual(rows[-2:], [("2026-06-11", 2.711), ("2026-06-12", 2.712)])
        # December, where 12/12 reads the same both ways
        dmy = site_page([(f"{d:02d}/12/2026", v) for d, v in zip(days, values)])
        rows = self.read(dmy, today=dt.date(2026, 12, 12))
        self.assertEqual(rows[-2:], [("2026-12-11", 2.711), ("2026-12-12", 2.712)])

    def test_page_without_the_table(self):
        with self.assertRaises(ValueError):
            self.read("<html><body><p>Maintenance</p></body></html>")

    def test_every_day_of_two_years_in_both_date_orders(self):
        # Build the page as it would look on each day of 2026 and 2027 (the last ten fixings, then the first
        # fixing of each of the last twelve months and of the last three years), in both date orders, and
        # check the latest two fixings come out right whichever order the page uses.
        weekdays = [dt.date(2024, 1, 1) + dt.timedelta(days=i) for i in range(4 * 366)]
        weekdays = [d for d in weekdays if d.weekday() < 5 and d <= dt.date(2027, 12, 31)]
        value = {d: round(2 + (d.toordinal() % 97) / 1000, 3) for d in weekdays}  # day-to-day moves stay small
        month_firsts, year_firsts = {}, {}
        for d in weekdays:
            month_firsts.setdefault((d.year, d.month), d)
            year_firsts.setdefault(d.year, d)
        checked = 0
        for today in (dt.date(2026, 1, 1) + dt.timedelta(days=i) for i in range(730)):
            public = [d for d in weekdays if d < today]  # a fixing shows the day after
            daily = public[-10:][::-1]
            firsts_of_month = [d for d in sorted(month_firsts.values()) if d < today][-12:]
            firsts_of_year = [d for d in sorted(year_firsts.values()) if d < today][-3:]
            for fmt in ("{d.month}/{d.day}/{d.year}", "{d.day:02d}/{d.month:02d}/{d.year}"):
                page = site_page([(fmt.format(d=d), f"{value[d]:.3f}") for d in daily],
                                 extra=[(fmt.format(d=d), f"{value[d]:.3f}") for d in firsts_of_month + firsts_of_year])
                rows = self.read(page, today=today)
                self.assertEqual(rows[-2:], [(d.isoformat(), value[d]) for d in public[-2:]], f"{today} {fmt}")
                checked += 1
        self.assertEqual(checked, 1460)


class CentralBanks(unittest.TestCase):
    def test_bundesbank(self):
        with mock.patch.object(fr, "get", return_value=BUNDESBANK_CSV):
            rows = fr.euribor_bundesbank(TODAY)
        self.assertEqual(rows[0], ("2026-11-06", 2.794))
        self.assertEqual(rows[-1], ("2026-11-12", 2.766))
        self.assertEqual(len(rows), 5)  # the two weekend days carry no value

    def test_banco_de_espana(self):
        with mock.patch.object(fr, "get", return_value=BDE_CSV):
            rows = fr.euribor_bde(TODAY)
        self.assertEqual(rows, [("2026-11-09", 2.773), ("2026-11-10", 2.738), ("2026-11-12", 2.766)])

    def test_banco_de_espana_without_the_column(self):
        with mock.patch.object(fr, "get", return_value=BDE_CSV.replace("A 3 meses", "A 2 meses")):
            with self.assertRaises(ValueError):
                fr.euribor_bde(TODAY)


class Choosing(unittest.TestCase):
    """euribor(): which source is used, and that the published fixing never steps back."""
    SITE = [("2026-11-12", 2.766), ("2026-11-13", 2.775)]
    BANK = [("2026-11-11", 2.754), ("2026-11-12", 2.766)]

    def run_with(self, site, bundesbank, bde, previous=None, simulate=""):
        def source(result):
            m = mock.Mock()
            m.side_effect = result if isinstance(result, Exception) else None
            m.return_value = None if isinstance(result, Exception) else result
            return m
        s, b, e = source(site), source(bundesbank), source(bde)
        sources = (("euribor-rates.eu", "euribor-site", s), ("Deutsche Bundesbank", "euribor-bundesbank", b), ("Banco de Espana", "euribor-bde", e))
        with mock.patch.object(fr, "EURIBOR_SOURCES", sources), mock.patch.object(fr.dt, "date", wraps=dt.date) as d:
            d.today.return_value = TODAY
            return fr.euribor(previous, simulate), (s.call_count, b.call_count, e.call_count)

    def test_website_when_it_answers(self):
        out, calls = self.run_with(self.SITE, self.BANK, self.BANK)
        self.assertEqual((out["display"], out["change_display"], out["as_of"]), ("2.775%", "+0.009%", "2026-11-13"))
        self.assertIn("euribor-rates.eu", out["source"])
        self.assertEqual(calls, (1, 0, 0))  # up to date, so nobody else is asked

    def test_bundesbank_when_the_website_certificate_fails(self):
        out, calls = self.run_with(OSError("CERTIFICATE_VERIFY_FAILED"), self.BANK, self.BANK)
        self.assertEqual((out["display"], out["change_display"], out["as_of"]), ("2.766%", "+0.012%", "2026-11-12"))
        self.assertIn("Deutsche Bundesbank", out["source"])
        self.assertEqual(calls, (1, 1, 0))

    def test_banco_de_espana_when_both_others_fail(self):
        out, calls = self.run_with(OSError("down"), OSError("down"), self.BANK)
        self.assertIn("Banco de Espana", out["source"])
        self.assertEqual(calls, (1, 1, 1))

    def test_no_source_at_all_is_a_failure(self):
        with self.assertRaises(RuntimeError):
            self.run_with(OSError("a"), OSError("b"), OSError("c"))

    def test_never_steps_back(self):
        published = {"name": "EURIBOR 3-Month", "value": 2.775, "display": "2.775%", "change": 0.009, "change_display": "+0.009%",
                     "as_of": "2026-11-13", "changed_on": "2026-11-13", "source": "Euribor 3-month daily fixing, via euribor-rates.eu",
                     "stale": False, "fetched_at": "2026-11-14T10:00:00Z"}
        out, _ = self.run_with(OSError("CERTIFICATE_VERIFY_FAILED"), self.BANK, self.BANK, previous=published)
        self.assertEqual((out["display"], out["as_of"]), ("2.775%", "2026-11-13"))
        self.assertNotIn("stale", out)
        self.assertNotIn("fetched_at", out)

    def test_a_published_date_in_the_future_is_not_kept(self):
        wrong = {"value": 9.9, "display": "9.900%", "as_of": "2026-12-11", "changed_on": "2026-12-11"}
        out, _ = self.run_with(OSError("down"), self.BANK, self.BANK, previous=wrong)
        self.assertEqual((out["display"], out["as_of"]), ("2.766%", "2026-11-12"))

    def test_website_that_stopped_updating(self):
        old = [("2026-11-03", 2.765), ("2026-11-04", 2.759)]
        out, calls = self.run_with(old, self.BANK, self.BANK)
        self.assertEqual(out["as_of"], "2026-11-12")
        self.assertIn("Deutsche Bundesbank", out["source"])
        self.assertEqual(calls, (1, 1, 0))

    def test_simulated_outage_of_one_source(self):
        out, calls = self.run_with(self.SITE, self.BANK, self.BANK, simulate="euribor-site")
        self.assertIn("Deutsche Bundesbank", out["source"])
        self.assertEqual(calls, (0, 1, 0))


if __name__ == "__main__":
    unittest.main()
