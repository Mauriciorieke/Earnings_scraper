"""Configuration for the earnings scraper."""

# SEC EDGAR requires a User-Agent header with your name and email.
# Update these before running the scraper.
SEC_USER_AGENT = "EarningsScraper admin@example.com"

# SEC EDGAR base URLs
EDGAR_BASE_URL = "https://efts.sec.gov/LATEST"
EDGAR_SUBMISSIONS_URL = "https://data.sec.gov/submissions"
EDGAR_COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts"

# Rate limiting: SEC allows 10 requests/sec max
SEC_REQUEST_DELAY = 0.15  # seconds between requests

# Default number of years of historical data to pull
DEFAULT_HISTORY_YEARS = 5

# Output directory
OUTPUT_DIR = "output"
