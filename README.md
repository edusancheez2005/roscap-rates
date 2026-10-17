# Roscap rates feed

Keeps the three reference rates on the roscap.co.uk home page current: Bank of England Base Rate,
US Federal Funds Rate, EURIBOR 3-Month.

How it works, in one line: GitHub runs `fetch_rates.py` twice a day, the script downloads the
numbers from their official sources and writes `rates.json`, GitHub serves that file at a public
address, and the website's script reads it. Nothing on GitHub has any access to the website.

## Files

- `fetch_rates.py`: the program. Standard library only. Downloads FRED (Fed target range), the Bank
  of England's Bank Rate history page, and the Euribor 3-month daily table, works out the change,
  and writes `rates.json`. If one source fails, it keeps that rate's last good value and marks it stale.
- `.github/workflows/update-rates.yml`: the timer. 12:30 and 19:30 UTC daily, plus a manual button.
- `rates.json`: the output the website reads.
- `webflow-footer-script.html`: the replacement for the Xano block in the Home page's footer code
  (not part of the repo; it goes into Webflow).

## Setting it up (Edu, about 15 minutes, once)

1. On github.com, create a free organisation named `roscap` (optional but keeps it off a personal
   account; add Clemente as an owner). Inside it, create a new repository `roscap-rates`, **Public**,
   no README.
2. Add the files. "Add file" > "Upload files" for `fetch_rates.py` and `rates.json`. For the workflow,
   "Add file" > "Create new file", type the name `.github/workflows/update-rates.yml` (GitHub creates
   the folders), paste the contents, commit.
3. Settings > Pages > Build and deployment > Source "Deploy from a branch" > branch `main`, folder
   `/ (root)` > Save. After a minute the file is live at
   `https://roscap.github.io/roscap-rates/rates.json` (replace `roscap` with the organisation or
   user name you used).
4. Actions tab > "Update rates" > "Run workflow". If the run fails on the push step with a
   permission error: Settings > Actions > General > Workflow permissions > "Read and write
   permissions" > Save, then run it again.
5. Send the `rates.json` address to Claude. The Webflow footer script gets switched from the Xano
   address to this one, the "Updated" line is added, and the section goes live on the next publish.

## What the numbers mean

- Fed: the target range, shown as "3.75% - 4.00%". Change = the size of the last decision.
- Bank of England: Bank Rate. Change = the size of the last decision that moved it (today -0.25%, the December 2025 cut; it stays -0.25% while the Bank holds).
- Euribor 3-month: the latest daily fixing. Change = move since the previous fixing.

## Things to know

- Scheduled jobs on GitHub pause after 60 days without any commit. Euribor changes most days, so the
  job commits most days and this does not arise; if it ever does, the "Run workflow" button restarts it.
- The organisation that publishes Euribor states that redisplaying it on a commercial site needs a
  licence. Many sites redisplay it regardless. Roscap's call, not a technical matter.
- "Real time" here means the same day. The Fed and the Bank move eight times a year at announced
  times; Euribor publishes once a day around 10:00 UK. The two daily runs catch all of them.
