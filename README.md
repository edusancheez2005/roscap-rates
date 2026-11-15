# Roscap rates feed

Keeps the three reference rates on the roscap.co.uk home page current: Bank of England Base Rate,
US Federal Funds Rate, EURIBOR 3-Month.

How it works, in one line: GitHub runs `fetch_rates.py` every three hours, the script downloads the
numbers from their sources and writes `rates.json`, GitHub serves that file at a public
address, and the website's script reads it. Nothing on GitHub has any access to the website.

## Files

- `fetch_rates.py`: the program. Standard library only. Downloads FRED (Fed target range), the Bank
  of England's Bank Rate history page, and the Euribor 3-month daily fixing (four sources, see below),
  works out the change, and writes `rates.json`. If a rate cannot be read, it keeps that rate's last
  good value and marks it stale.
- `test_fetch_rates.py`: tests for the Euribor part. No network needed: `python -m unittest -v`.
- `.github/workflows/update-rates.yml`: the timer. Every three hours at 47 minutes past (UTC), plus a manual button. GitHub can start scheduled jobs late, sometimes by hours, so the job runs often; it only commits when something changed.
- `rates.json`: the output the website reads.
- `webflow-footer-script.html`: the replacement for the Xano block in the Home page's footer code
  (not part of the repo; it goes into Webflow).

## Where it lives (set up 17 October 2026)

- Repository: https://github.com/edusancheez2005/roscap-rates (public, Edu's account)
- The file the website reads: https://edusancheez2005.github.io/roscap-rates/rates.json
- Runs: https://github.com/edusancheez2005/roscap-rates/actions (each run shows the numbers it wrote)
- First run on GitHub's machines: 17 Oct 2026 13:02 UTC, success. The address serves JSON with
  `access-control-allow-origin: *`, so the website can read it.

## Checking it is alive

Open the Actions page above. A green tick every three hours or so means it is working. Open the rates.json address
and look at `updated`; if it is more than a day old, press "Run workflow" on the Actions page and read
the log of that run. To move the feed to a Roscap organisation later: GitHub repository Settings >
Transfer ownership; then change the address in the Webflow footer script to match.

## Where Euribor comes from (four sources, since 15 November 2026)

Euribor is one benchmark, set once a day by the European Money Markets Institute. Every source below
republishes that same figure (checked on 15 November 2026: the fixings of 2 to 12 November are identical
in all of them, and the two central bank series at the end agree on every fixing of the last twelve months).

The script asks these in order:

1. **euribor-rates.eu**: shows a fixing the next calendar day (Friday's on Saturday).
2. **Bank of Finland** (`suomenpankki.fi/api/interestrates/euribor`, the series behind the Bank's own
   Euribor page; the 3-month series is `euribor3kk`): it had Friday's fixing over the weekend, ahead of
   the next two.
3. **Deutsche Bundesbank** (official series `BBIG1.D.D0.EUR.MMKT.EURIBOR.M03.BID._Z`): shows a fixing
   on the next working day (Friday's on Monday, around midday UK time).
4. **Banco de Espana** (official table `ti_1_7.csv`): same delay as the Bundesbank.

Which one is used: the script stops at the first source that has the fixing due by now (that of the last
weekday before today). If none has it, it uses the newest fixing any of them has. The run log says which
source was used ("NOTE euribor source not used, ..." lines name the ones that were not), and `rates.json`
says it in the `source` field.

Two safeguards:

- A source must agree with what is already published. If a source gives another figure for the day
  whose fixing is already in `rates.json`, it is reading something else (another maturity, a misread
  page) and is not used.
- The published fixing never steps back to an older one when a slower source takes over.

Why four: on 13-14 November 2026 euribor-rates.eu moved to new servers and began presenting a security
certificate from a private authority, which fails verification. The script refused to read it (that is
the right behaviour: a certificate is how the script knows it is talking to the real site) and Euribor
stayed on the 12 November fixing, marked stale. The Bundesbank and the Banco de Espana were added on
15 November so that the feed no longer depends on one website, and the Bank of Finland the same evening
because those two were a working day behind. When the website's certificate is valid again the script
uses it again by itself.

Certificates are always verified. Do not "fix" a certificate error by switching verification off or
by trusting a site's certificate by hand: the website would then show whatever anyone in between sends.

## What the numbers mean

- Fed: the target range, shown as "3.75% - 4.00%". Change = the size of the last decision.
- Bank of England: Bank Rate. Change = the size of the last decision that moved it (today -0.25%, the December 2025 cut; it stays -0.25% while the Bank holds).
- Euribor 3-month: the latest daily fixing. Change = move since the previous fixing.

## Things to know

- If a rate cannot be read (for Euribor: from none of its four sources), the script keeps that rate's
  last good value, marks it `stale`, holds the `updated` date back to the last time all three were fresh,
  and the GitHub run turns red (GitHub emails the repository owner, and the run adds a comment to the
  open issue "Rates feed: a source could not be read"). The website keeps showing the last good numbers
  meanwhile, with "awaiting update" under the rate.
- Scheduled jobs on GitHub pause after 60 days without any commit. Euribor changes most days, so the
  job commits most days and this does not arise; if it ever does, the "Run workflow" button restarts it.
- If every source disagrees with the Euribor fixing already published (a fixing corrected after the
  event, or a wrong figure in `rates.json`), the run fails in the same way. Check the figure, then delete
  the `"euribor"` block from `rates.json` and run again: the script writes it afresh.
- The organisation that publishes Euribor states that redisplaying it on a commercial site needs a
  licence. Many sites redisplay it regardless. Roscap's call, not a technical matter. The central banks
  say the same about their copies: the Bundesbank's series header and the Bank of Finland's Euribor page
  both state that commercial use needs a licence agreement with the European Money Markets Institute.
- "Real time" here means the same day for the Fed and the Bank, which move eight times a year at announced
  times. Euribor is fixed once a day around 10:00 UK and is free to republish only a day later, so the
  feed shows yesterday's fixing at best. The three-hourly runs catch all of them even when GitHub starts a run late.
