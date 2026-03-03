# Earnings Scraper

Scrape earnings reports from SEC EDGAR and output formatted Excel workbooks with 3-statement financial models (Income Statement, Balance Sheet, Cash Flow Statement). Built to backlog historical data fast so you can take over with your own assumptions and forecasts.

No API keys required — pulls directly from SEC EDGAR's free XBRL API.

## Features

- **3-Statement Model Export** — Income Statement, Balance Sheet, and Cash Flow Statement parsed into a formatted Excel workbook with a summary dashboard
- **Earnings Press Releases** — Scrape 8-K filings to extract earnings highlights, guidance, and segment results
- **Multiple Tickers** — Process several companies in one run
- **Annual or Quarterly** — Toggle between annual (10-K) and quarterly (10-Q) data
- **Forecast-Ready** — Excel output includes a forecast assumptions section where you can plug in your own growth rates, margins, and projections

## Setup

```bash
# Clone the repo
git clone https://github.com/Mauriciorieke/Earnings_scraper.git
cd Earnings_scraper

# Install dependencies
pip install -r requirements.txt
```

Before running, update `config.py` with your name and email (SEC EDGAR requires a User-Agent header):

```python
SEC_USER_AGENT = "YourName your@email.com"
```

## Usage

### Command Line

```bash
# Pull annual data for Apple and export to Excel
python -m earnings_scraper.cli AAPL

# Quarterly data
python -m earnings_scraper.cli AAPL --quarterly

# Multiple tickers
python -m earnings_scraper.cli AAPL MSFT GOOG

# Include earnings press release data
python -m earnings_scraper.cli AAPL --transcripts

# Custom output directory
python -m earnings_scraper.cli AAPL -o my_models/
```

### Python API

```python
from earnings_scraper.scraper import EarningsScraper

scraper = EarningsScraper()

# Full pipeline: scrape + export to Excel
result = scraper.scrape("AAPL")
print(result["company_name"])
print(result["income_statement"])
print(f"Excel saved to: {result['excel_path']}")

# Just get the DataFrames without exporting
statements = scraper.get_statements("MSFT", quarterly=True)
print(statements["Balance Sheet"])

# Get recent SEC filings
filings = scraper.get_filings("GOOG", form_types=["10-K"])
```

## Output

Excel files are saved to the `output/` directory (configurable). Each workbook contains:

| Tab | Contents |
|-----|----------|
| **Summary** | Key metrics from all 3 statements + forecast assumption placeholders |
| **Income Statement** | Revenue, COGS, Gross Profit, OpEx, Operating Income, Net Income, EPS |
| **Balance Sheet** | Assets, Liabilities, Equity with current/non-current breakdowns |
| **Cash Flow Statement** | Operating, Investing, and Financing cash flows |

## Project Structure

```
Earnings_scraper/
├── config.py                          # Configuration (User-Agent, URLs, defaults)
├── requirements.txt                   # Python dependencies
├── setup.py                           # Package setup
├── earnings_scraper/
│   ├── __init__.py
│   ├── __main__.py                    # python -m earnings_scraper entry point
│   ├── cli.py                         # Command-line interface
│   ├── scraper.py                     # High-level API for programmatic use
│   ├── edgar.py                       # SEC EDGAR API client
│   ├── financials.py                  # XBRL data → financial statement parser
│   ├── transcripts.py                 # Earnings call / 8-K press release scraper
│   └── excel_output.py               # Excel workbook generator
└── output/                            # Generated Excel files go here
```

## Future Plans

- Automated assumption and forecast modeling
- Historical ratio analysis (margins, growth rates, returns)
- DCF model template generation
- Earnings call transcript NLP for sentiment and key takeaways
