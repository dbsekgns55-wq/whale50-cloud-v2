Whale50 V4.7.1 – Monthly partial indicator repair (2 root files)

What this fixes:
- Monthly data with 52-77 completed bars gets partial long/short indicator scores.
- The visible current Ichimoku cloud is unavailable until 78 completed bars.
- Keep the V4.7 sell-by-amount and shared-seller TOP tables.
- Historical backtests and existing performance data remain unchanged.

For GitHub whale50-cloud-v2:
1. Extract the ZIP.
2. Upload BOTH dashboard.html and whale50_signals.py to the repository ROOT, replacing each existing file.
3. Commit changes.
4. Actions -> Whale50 Cloud Collector and Website -> Run workflow (main).
5. After success, refresh the Pages site with Ctrl+F5.

If the site still says '76 completed bars / 78 required', confirm that GitHub main's whale50_signals.py has the line:
    minimum=52 if frame=='1mo' else 78
Also check the last GitHub Actions run actually succeeded; a previous successful Pages build can remain displayed after a failed run.

Important: directional scores are not actual probabilities, and 13F changes are not confirmed executed trading amounts.
