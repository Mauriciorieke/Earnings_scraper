"""SEC EDGAR API client for fetching company financial data.

Uses the free EDGAR XBRL API to pull structured financial statement data
(income statement, balance sheet, cash flow) without needing API keys.
"""

import time
import requests

import sys
sys.path.insert(0, ".")
from config import (
    SEC_USER_AGENT,
    EDGAR_SUBMISSIONS_URL,
    EDGAR_COMPANY_FACTS_URL,
    SEC_REQUEST_DELAY,
)


class EdgarClient:
    """Client for the SEC EDGAR API."""

    def __init__(self, user_agent=None):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": user_agent or SEC_USER_AGENT,
            "Accept-Encoding": "gzip, deflate",
        })
        self._last_request_time = 0

    def _rate_limit(self):
        """Respect SEC rate limits."""
        elapsed = time.time() - self._last_request_time
        if elapsed < SEC_REQUEST_DELAY:
            time.sleep(SEC_REQUEST_DELAY - elapsed)
        self._last_request_time = time.time()

    def _get(self, url):
        """Make a rate-limited GET request."""
        self._rate_limit()
        resp = self.session.get(url)
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Ticker / CIK resolution
    # ------------------------------------------------------------------

    def get_cik(self, ticker):
        """Resolve a stock ticker to a zero-padded 10-digit CIK string.

        Uses the EDGAR full-text search to find the CIK for a given ticker.
        """
        url = f"https://efts.sec.gov/LATEST/search-index?q=%22{ticker}%22&dateRange=custom&startdt=2020-01-01&forms=10-K,10-Q"
        # Simpler approach: use the company tickers JSON
        self._rate_limit()
        resp = self.session.get("https://www.sec.gov/files/company_tickers.json")
        resp.raise_for_status()
        tickers = resp.json()

        ticker_upper = ticker.upper()
        for entry in tickers.values():
            if entry.get("ticker", "").upper() == ticker_upper:
                return str(entry["cik_str"]).zfill(10)

        raise ValueError(f"Ticker '{ticker}' not found in SEC EDGAR.")

    # ------------------------------------------------------------------
    # Company submissions (filings metadata)
    # ------------------------------------------------------------------

    def get_submissions(self, cik):
        """Fetch filing metadata for a company from EDGAR submissions API.

        Returns the JSON blob with recent filings and company info.
        """
        url = f"{EDGAR_SUBMISSIONS_URL}/CIK{cik}.json"
        return self._get(url)

    def get_recent_filings(self, ticker, form_types=None):
        """Get recent filings for a ticker, optionally filtered by form type.

        Args:
            ticker: Stock ticker symbol (e.g. 'AAPL').
            form_types: List of form types to filter (e.g. ['10-K', '10-Q']).
                        Defaults to ['10-K', '10-Q'].

        Returns:
            List of dicts with filing metadata (accession number, date, form).
        """
        if form_types is None:
            form_types = ["10-K", "10-Q"]

        cik = self.get_cik(ticker)
        submissions = self.get_submissions(cik)
        recent = submissions.get("filings", {}).get("recent", {})

        forms = recent.get("form", [])
        accessions = recent.get("accessionNumber", [])
        dates = recent.get("filingDate", [])
        primary_docs = recent.get("primaryDocument", [])

        filings = []
        for i, form in enumerate(forms):
            if form in form_types:
                filings.append({
                    "form": form,
                    "accessionNumber": accessions[i],
                    "filingDate": dates[i],
                    "primaryDocument": primary_docs[i] if i < len(primary_docs) else None,
                    "cik": cik,
                })

        return filings

    # ------------------------------------------------------------------
    # XBRL company facts (structured financial data)
    # ------------------------------------------------------------------

    def get_company_facts(self, cik):
        """Fetch all XBRL facts for a company (all filings, all line items).

        This is the core data source for financial statement numbers.
        Returns structured data organized by taxonomy and concept.
        """
        url = f"{EDGAR_COMPANY_FACTS_URL}/CIK{cik}.json"
        return self._get(url)

    def get_financial_data(self, ticker):
        """High-level method: get all structured financial data for a ticker.

        Returns:
            dict with 'company_name', 'cik', and 'facts' (the XBRL data).
        """
        cik = self.get_cik(ticker)
        facts = self.get_company_facts(cik)
        return {
            "company_name": facts.get("entityName", ticker),
            "cik": cik,
            "facts": facts.get("facts", {}),
        }

    def get_company_info(self, ticker):
        """Get company name and CIK without fetching full XBRL facts.

        Returns:
            dict with 'company_name', 'cik'.
        """
        cik = self.get_cik(ticker)
        submissions = self.get_submissions(cik)
        return {
            "company_name": submissions.get("name", ticker),
            "cik": cik,
        }

    def get_latest_filing(self, ticker, form_type="10-K"):
        """Get the single most recent filing of a given type.

        Args:
            ticker: Stock ticker symbol.
            form_type: '10-K' or '10-Q'.

        Returns:
            Dict with filing metadata, or None if not found.
        """
        filings = self.get_recent_filings(ticker, [form_type])
        return filings[0] if filings else None
