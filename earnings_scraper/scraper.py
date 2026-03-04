"""High-level scraper API for programmatic use.

Use this module when importing earnings_scraper as a library
instead of running it from the command line.
"""

import sys
sys.path.insert(0, ".")

from earnings_scraper.edgar import EdgarClient
from earnings_scraper.filing_scraper import FilingScraper
from earnings_scraper.financials import (
    get_all_statements,
    get_income_statement,
    get_balance_sheet,
    get_cash_flow_statement,
)
from earnings_scraper.transcripts import TranscriptScraper
from earnings_scraper.excel_output import export_to_excel


class EarningsScraper:
    """Main interface for scraping earnings data.

    Default mode scrapes directly from the filing HTML (10-K / 10-Q),
    extracting every single line item as the company presents it.

    Example:
        scraper = EarningsScraper()
        result = scraper.scrape("AAPL")
        print(result["income_statement"])
        print(f"Excel saved to: {result['excel_path']}")
    """

    def __init__(self, user_agent=None):
        self.edgar = EdgarClient(user_agent=user_agent)
        self.filing_scraper = FilingScraper(user_agent=user_agent)
        self.transcript_scraper = TranscriptScraper(user_agent=user_agent)

    def scrape(self, ticker, quarterly=False, num_filings=1,
               include_transcripts=False, output_dir=None):
        """Scrape financial statements from actual filing HTML and export to Excel.

        This is the recommended method — it pulls every line item exactly
        as the company presents it in their 10-K or 10-Q.

        Args:
            ticker: Stock ticker symbol (e.g. 'AAPL').
            quarterly: If True, scrape 10-Q instead of 10-K.
            num_filings: Number of filings to combine (more = more history).
            include_transcripts: If True, also fetch earnings press releases.
            output_dir: Directory to save the Excel file.

        Returns:
            Dict with:
                - company_name: str
                - cik: str
                - income_statement: DataFrame
                - balance_sheet: DataFrame
                - cash_flow_statement: DataFrame
                - excel_path: str
                - transcripts: list (if include_transcripts=True)
        """
        form_type = "10-Q" if quarterly else "10-K"
        info = self.edgar.get_company_info(ticker)
        cik = info["cik"]
        company_name = info["company_name"]

        filings = self.edgar.get_recent_filings(ticker, [form_type])
        if not filings:
            raise ValueError(f"No {form_type} filings found for {ticker}")

        filings_to_use = filings[:num_filings]

        if num_filings == 1:
            statements = self.filing_scraper.scrape_filing_statements(
                cik, filings_to_use[0]["accessionNumber"]
            )
            statements.pop("raw", None)
            statements.pop("reports", None)
        else:
            acc_numbers = [f["accessionNumber"] for f in filings_to_use]
            statements = self.filing_scraper.scrape_multiple_filings(cik, acc_numbers)

        excel_path = export_to_excel(statements, company_name, ticker, output_dir)

        result = {
            "company_name": company_name,
            "cik": cik,
            "income_statement": statements.get("Income Statement"),
            "balance_sheet": statements.get("Balance Sheet"),
            "cash_flow_statement": statements.get("Cash Flow Statement"),
            "excel_path": excel_path,
        }

        if include_transcripts:
            result["transcripts"] = self.transcript_scraper.get_earnings_press_releases(
                cik, max_results=5
            )

        return result

    def scrape_xbrl(self, ticker, quarterly=False, include_transcripts=False,
                    output_dir=None):
        """Scrape using the XBRL taxonomy approach (discovers all us-gaap concepts).

        This is the legacy method. Use scrape() for the filing-based approach.
        """
        data = self.edgar.get_financial_data(ticker)
        facts = data["facts"]
        statements = get_all_statements(facts, quarterly=quarterly)

        excel_path = export_to_excel(
            statements, data["company_name"], ticker, output_dir
        )

        result = {
            "company_name": data["company_name"],
            "cik": data["cik"],
            "income_statement": statements["Income Statement"],
            "balance_sheet": statements["Balance Sheet"],
            "cash_flow_statement": statements["Cash Flow Statement"],
            "excel_path": excel_path,
        }

        if include_transcripts:
            result["transcripts"] = self.transcript_scraper.get_earnings_press_releases(
                data["cik"], max_results=5
            )

        return result

    def get_filings(self, ticker, form_types=None):
        """Get recent SEC filings for a ticker."""
        return self.edgar.get_recent_filings(ticker, form_types)

    def get_statements(self, ticker, quarterly=False, num_filings=1):
        """Get parsed financial statements without exporting to Excel.

        Uses the filing HTML approach by default.
        """
        form_type = "10-Q" if quarterly else "10-K"
        info = self.edgar.get_company_info(ticker)
        cik = info["cik"]

        filings = self.edgar.get_recent_filings(ticker, [form_type])
        if not filings:
            raise ValueError(f"No {form_type} filings found for {ticker}")

        if num_filings == 1:
            statements = self.filing_scraper.scrape_filing_statements(
                cik, filings[0]["accessionNumber"]
            )
            statements.pop("raw", None)
            statements.pop("reports", None)
            return statements
        else:
            acc_numbers = [f["accessionNumber"] for f in filings[:num_filings]]
            return self.filing_scraper.scrape_multiple_filings(cik, acc_numbers)
