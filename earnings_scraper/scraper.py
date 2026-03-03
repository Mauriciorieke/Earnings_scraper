"""High-level scraper API for programmatic use.

Use this module when importing earnings_scraper as a library
instead of running it from the command line.
"""

import sys
sys.path.insert(0, ".")

from earnings_scraper.edgar import EdgarClient
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

    Example:
        scraper = EarningsScraper()
        result = scraper.scrape("AAPL")
        print(result["income_statement"])
        print(f"Excel saved to: {result['excel_path']}")
    """

    def __init__(self, user_agent=None):
        self.edgar = EdgarClient(user_agent=user_agent)
        self.transcript_scraper = TranscriptScraper(user_agent=user_agent)

    def scrape(self, ticker, quarterly=False, include_transcripts=False, output_dir=None):
        """Scrape all financial data for a ticker and export to Excel.

        Args:
            ticker: Stock ticker symbol (e.g. 'AAPL').
            quarterly: If True, pull quarterly data instead of annual.
            include_transcripts: If True, also fetch earnings press releases.
            output_dir: Directory to save the Excel file.

        Returns:
            Dict with:
                - company_name: str
                - cik: str
                - income_statement: DataFrame
                - balance_sheet: DataFrame
                - cash_flow_statement: DataFrame
                - excel_path: str (path to saved file)
                - transcripts: list (if include_transcripts=True)
        """
        # Get raw XBRL data
        data = self.edgar.get_financial_data(ticker)
        facts = data["facts"]

        # Parse statements
        statements = get_all_statements(facts, quarterly=quarterly)

        # Export
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
        """Get recent SEC filings for a ticker.

        Args:
            ticker: Stock ticker symbol.
            form_types: List of form types (e.g. ['10-K', '10-Q', '8-K']).

        Returns:
            List of filing metadata dicts.
        """
        return self.edgar.get_recent_filings(ticker, form_types)

    def get_statements(self, ticker, quarterly=False):
        """Get parsed financial statements without exporting to Excel.

        Returns:
            Dict of DataFrames: 'Income Statement', 'Balance Sheet', 'Cash Flow Statement'.
        """
        data = self.edgar.get_financial_data(ticker)
        return get_all_statements(data["facts"], quarterly=quarterly)
