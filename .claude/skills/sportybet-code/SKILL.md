---
name: sportybet-code
description: Build a slip from the picks on SportyBet in the built-in browser, press Book Bet, and record the booking code for the dashboard. Use for "get me a SportyBet code", a slip pasted from the dashboard's Copy slip button, or the daily suggested slip.
---

Build a SportyBet booking code for a slip of picks. This never logs in and never places a bet: it only adds selections to SportyBet's betslip and presses **Book Bet**, which saves the slip under a code the user loads in their own SportyBet app.

Project folder: C:\Users\HP\Desktop\Sports Prediction (run commands from there).

## 1. Get the slip

- Daily suggested slip: `python src/slip.py` (3 safest best picks today). Variants: `--n 5`, `--odds 5`, `--days 2`, `--date YYYY-MM-DD`, `--sport volley`.
- A slip the user pasted from the dashboard: `python src/slip.py --text "<the pasted lines>"`.

It prints each pick with where it is on SportyBet (tab > market > button) and saves the slip for step 4. Run the daily update first if output/dashboard/upcoming.csv is not from today (`status.csv`).

## 2. Add each pick in the built-in browser

1. Open https://www.sportybet.com/ng/sport/football/today/ (or `/upcoming/` for later days; volleyball: `/ng/sport/volleyball/today/`). If the betslip already holds selections, clear it with its **Remove All** link first.
2. `find` the home team's name (SportyBet may name clubs differently: "PSG", "Wrexham AFC") and click it to open the match page.
3. Open the tab named in the slip listing (Main, Goals, Half, Bookings, Corners). Use `get_page_text` to locate the market and its price, then click the outcome button (scroll to it and take a screenshot to confirm the right market before clicking).
4. Note SportyBet's price for every pick. Skip a pick SportyBet does not offer, or whose game has started, and say so.
5. SportyBet "Bookings" counts cards; for a cards pick use the Bookings market with the same line.

## 3. Book it

Check the betslip shows exactly the intended picks, then click **Book Bet** (under the betslip). Read the code and the total odds from the popup (screenshot), then close the popup. Never click **Place Bet**, never log in, never enter a stake or personal details. If SportyBet asks for a login or shows a verification or "prove you're human" check, stop and tell the user.

## 4. Record and publish

1. `python src/slip.py --record <CODE> --odds-real <total odds> --label "<Safest 3 | 5 odds | Your slip>"` (add `--sport volley` for volleyball). This adds the code to output/dashboard/codes.csv.
2. Upload codes.csv to the dashboard https://claude.ai/artifact/Fj4Pw425ep9i4peD83DV4b: Artifact tool (publish, url = the dashboard, file_path = the csv's absolute path, asset = true); then ArtifactData get collection "datasets" doc "codes", and update it with if_version and {"source": {"kind": "file", "url": "<new /_blob url>", "name": "codes.csv"}, "updated": {"at": "<now ISO>", "by": "Claude (sportybet-code)"}}; delete the old asset only if no other dataset points to it.
3. Tell the user the code, the number of picks, SportyBet's total odds, and any pick that was skipped or priced under 1.20.
