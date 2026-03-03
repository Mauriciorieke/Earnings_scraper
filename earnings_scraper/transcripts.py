"""Earnings call transcript scraper.

Scrapes earnings call transcript data from SEC EDGAR 8-K filings
(which often contain earnings press releases and call transcripts)
and provides helpers for extracting key sections.
"""

import re
import time
import requests
from bs4 import BeautifulSoup

import sys
sys.path.insert(0, ".")
from config import SEC_USER_AGENT, SEC_REQUEST_DELAY


class TranscriptScraper:
    """Scrape earnings-related 8-K filings and press releases from EDGAR."""

    def __init__(self, user_agent=None):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": user_agent or SEC_USER_AGENT,
            "Accept-Encoding": "gzip, deflate",
        })
        self._last_request_time = 0

    def _rate_limit(self):
        elapsed = time.time() - self._last_request_time
        if elapsed < SEC_REQUEST_DELAY:
            time.sleep(SEC_REQUEST_DELAY - elapsed)
        self._last_request_time = time.time()

    def _get(self, url):
        self._rate_limit()
        resp = self.session.get(url)
        resp.raise_for_status()
        return resp

    def get_earnings_8k_filings(self, cik, max_results=10):
        """Find 8-K filings (earnings press releases) for a company.

        Item 2.02 of an 8-K is "Results of Operations and Financial Condition",
        which is the standard earnings press release filing.

        Args:
            cik: Zero-padded 10-digit CIK string.
            max_results: Maximum filings to return.

        Returns:
            List of dicts with accession numbers and filing dates.
        """
        url = (
            f"https://efts.sec.gov/LATEST/search-index?"
            f"q=%228-K%22&forms=8-K&dateRange=custom"
            f"&startdt=2019-01-01"
        )
        # Use the submissions endpoint instead for reliability
        submissions_url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        data = self._get(submissions_url).json()
        recent = data.get("filings", {}).get("recent", {})

        forms = recent.get("form", [])
        accessions = recent.get("accessionNumber", [])
        dates = recent.get("filingDate", [])
        primary_docs = recent.get("primaryDocument", [])

        results = []
        for i, form in enumerate(forms):
            if form == "8-K" and len(results) < max_results:
                results.append({
                    "form": form,
                    "accessionNumber": accessions[i],
                    "filingDate": dates[i],
                    "primaryDocument": primary_docs[i] if i < len(primary_docs) else None,
                    "cik": cik,
                })
        return results

    def get_filing_document(self, cik, accession_number, document_name):
        """Download and parse a specific filing document from EDGAR.

        Args:
            cik: The CIK (with or without zero-padding).
            accession_number: The accession number (with dashes).
            document_name: The primary document filename.

        Returns:
            Parsed text content of the filing.
        """
        acc_no_dashes = accession_number.replace("-", "")
        url = (
            f"https://www.sec.gov/Archives/edgar/data/"
            f"{cik.lstrip('0')}/{acc_no_dashes}/{document_name}"
        )
        resp = self._get(url)
        soup = BeautifulSoup(resp.content, "lxml")
        return soup.get_text(separator="\n", strip=True)

    def extract_earnings_sections(self, text):
        """Extract key sections from an earnings press release or transcript.

        Looks for common section headers in earnings documents and returns
        a dict mapping section names to their content.
        """
        section_patterns = [
            (r"(?i)(financial\s+highlights?)", "Financial Highlights"),
            (r"(?i)(results?\s+of\s+operations?)", "Results of Operations"),
            (r"(?i)(revenue|net\s+sales)", "Revenue"),
            (r"(?i)(guidance|outlook|forecast)", "Guidance / Outlook"),
            (r"(?i)(segment\s+results?|business\s+segments?)", "Segment Results"),
            (r"(?i)(balance\s+sheet|financial\s+position)", "Balance Sheet"),
            (r"(?i)(cash\s+flow)", "Cash Flow"),
            (r"(?i)(earnings\s+per\s+share|EPS)", "EPS"),
        ]

        sections = {}
        lines = text.split("\n")

        for i, line in enumerate(lines):
            for pattern, name in section_patterns:
                if re.search(pattern, line):
                    # Grab this line plus the next 30 lines as the section
                    section_text = "\n".join(lines[i:i + 30])
                    if name not in sections:
                        sections[name] = section_text

        return sections

    def get_earnings_press_releases(self, cik, max_results=5):
        """Get parsed earnings press releases for a company.

        Returns a list of dicts, each with filing metadata and extracted text.
        """
        filings = self.get_earnings_8k_filings(cik, max_results)
        releases = []

        for filing in filings:
            doc = filing.get("primaryDocument")
            if not doc:
                continue
            try:
                text = self.get_filing_document(
                    cik, filing["accessionNumber"], doc
                )
                sections = self.extract_earnings_sections(text)
                releases.append({
                    "filingDate": filing["filingDate"],
                    "accessionNumber": filing["accessionNumber"],
                    "fullText": text[:5000],  # First 5000 chars as preview
                    "sections": sections,
                })
            except Exception:
                # Skip filings that can't be parsed
                continue

        return releases
