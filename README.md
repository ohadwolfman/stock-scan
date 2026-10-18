# Stock Scan

Stock Scan is a Python tool for collecting market and company data for a customizable watchlist of stocks. It uses Yahoo Finance through `yfinance` and produces a tab-separated snapshot with price and trading metrics, technical indicators, and selected company fundamentals. The quality data is cached locally to reduce repeated requests.

## Current workflow

1. Edit the categorized ticker watchlist in `stock_scan_yfinance.py` as needed.
2. Run the scanner:

   ```powershell
   .\.venv\Scripts\Activate.ps1
   python .\stock_scan_yfinance.py
   ```

   Or install the dependencies in a Python environment and run the second command:

   ```powershell
   python -m pip install -r requirements.txt
   ```

3. Review the generated `stock_scan_snapshot.txt`. Each run overwrites this file with the latest available data.
4. For the weekly analysis, manually use the snapshot together with `prompts/weekly-market-brief-v7.txt` and submit the prompt to Claude.
5. Review Claude's analysis and manually replace the `חבילת_המשך` (follow-up package) block in the prompt with the updated package for the next run.

The weekly analysis and follow-up package are currently manual. The scanner does not submit prompts to Claude, evaluate or approve its analysis, update the follow-up package, or send email. The prompt contains a spot-data section, but the script's current run flow only writes the snapshot file.

## Future goal

Automate the workflow so a run collects the latest data, prepares the weekly analysis, and emails the resulting report. A later iteration could also carry the reviewed `חבילת_המשך` forward automatically. Any generated analysis or proposed package should remain reviewable before being treated as an investment decision or used in the next run.

## Project files

- `stock_scan_yfinance.py` - watchlist configuration, data collection, calculations, caching, and snapshot generation.
- `stock_scan_snapshot.txt` - latest generated market-data snapshot; overwritten on each run.
- `stock_scan_quality_cache.json` - local cache for company quality metrics.
- `prompts/weekly-market-brief-v7.txt` - Hebrew prompt for the weekly market analysis, including the manually maintained follow-up package.
- `requirements.txt` - Python package dependencies.