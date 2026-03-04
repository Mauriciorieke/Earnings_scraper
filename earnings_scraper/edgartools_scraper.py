"""Financial statement scraper using the edgartools library.

Uses the edgartools Python package to pull Balance Sheet, Income Statement,
and Cash Flow Statement data from SEC EDGAR for any public company,
going back up to 5 years (20 quarterly periods or 5 annual periods).

The edgartools library provides a clean, high-level API that handles
CIK resolution, XBRL parsing, and financial statement extraction.

Usage:
    from earnings_scraper.edgartools_scraper import EdgarToolsScraper

    scraper = EdgarToolsScraper()
    result = scraper.scrape("AAPL")
    print(f"Saved to: {result['excel_path']}")
"""

import pandas as pd
from edgar import Company, set_identity

import sys
sys.path.insert(0, ".")
from config import SEC_USER_AGENT, DEFAULT_HISTORY_YEARS
from earnings_scraper.excel_output import export_to_excel


class EdgarToolsScraper:
    """Scrape financial statements using the edgartools library."""

    def __init__(self, identity=None):
        """Initialize the scraper.

        Args:
            identity: SEC EDGAR identity string (name + email).
                      Defaults to the value in config.py.
        """
        set_identity(identity or SEC_USER_AGENT)

    def _get_statement_df(self, company, statement_type, periods, period_kind):
        """Fetch a financial statement as a DataFrame.

        Args:
            company: edgartools Company object.
            statement_type: One of 'income_statement', 'balance_sheet', 'cash_flow'.
            periods: Number of periods to fetch.
            period_kind: 'annual' or 'quarterly'.

        Returns:
            pandas DataFrame with line items as rows and periods as columns.
        """
        method_map = {
            "income_statement": company.income_statement,
            "balance_sheet": company.balance_sheet,
            "cash_flow": company.cash_flow,
        }

        fetch_fn = method_map[statement_type]
        try:
            df = fetch_fn(periods=periods, period=period_kind, as_dataframe=True)
            if df is not None and not df.empty:
                return df
        except Exception as e:
            print(f"      Warning: Could not fetch {statement_type} "
                  f"as DataFrame: {e}")

        # Fallback: try getting the MultiPeriodStatement and convert manually
        try:
            statement = fetch_fn(periods=periods, period=period_kind,
                                 as_dataframe=False)
            if statement is not None:
                df = self._statement_to_df(statement)
                if df is not None and not df.empty:
                    return df
        except Exception as e:
            print(f"      Warning: Could not fetch {statement_type}: {e}")

        return pd.DataFrame()

    def _statement_to_df(self, statement):
        """Convert a MultiPeriodStatement object to a DataFrame.

        Handles the case where as_dataframe=True doesn't work by
        manually extracting data from the statement object.
        """
        try:
            # Try the to_dataframe method if available
            if hasattr(statement, 'to_dataframe'):
                return statement.to_dataframe()
            # Try converting via repr/str parsing as last resort
            if hasattr(statement, 'data') and isinstance(statement.data, pd.DataFrame):
                return statement.data
            # Try direct DataFrame conversion
            return pd.DataFrame(statement)
        except Exception:
            return pd.DataFrame()

    def scrape(self, ticker, quarterly=False, years=None, output_dir=None):
        """Scrape all three financial statements and export to Excel.

        Args:
            ticker: Stock ticker symbol (e.g. 'AAPL', 'MSFT', 'GOOG').
            quarterly: If True, pull quarterly data instead of annual.
            years: Number of years of history (default: 5).
            output_dir: Directory to save Excel file. Defaults to config OUTPUT_DIR.

        Returns:
            Dict with:
                - company_name: str
                - ticker: str
                - income_statement: DataFrame
                - balance_sheet: DataFrame
                - cash_flow_statement: DataFrame
                - excel_path: str (path to the saved Excel file)
        """
        if years is None:
            years = DEFAULT_HISTORY_YEARS

        period_kind = "quarterly" if quarterly else "annual"
        periods = years * 4 if quarterly else years

        print(f"\n{'='*60}")
        print(f"  Processing: {ticker.upper()} (via edgartools)")
        print(f"{'='*60}")

        # Step 1: Look up the company
        print(f"\n[1/3] Looking up {ticker.upper()} on SEC EDGAR...")
        company = Company(ticker)
        company_name = company.name
        print(f"      Company: {company_name}")
        print(f"      CIK: {company.cik}")
        print(f"      Pulling {periods} {period_kind} periods ({years} years)")

        # Step 2: Fetch all three statements
        print(f"\n[2/3] Fetching financial statements...")

        print(f"      Fetching Income Statement...")
        is_df = self._get_statement_df(company, "income_statement",
                                       periods, period_kind)

        print(f"      Fetching Balance Sheet...")
        bs_df = self._get_statement_df(company, "balance_sheet",
                                       periods, period_kind)

        print(f"      Fetching Cash Flow Statement...")
        cf_df = self._get_statement_df(company, "cash_flow",
                                       periods, period_kind)

        statements = {
            "Income Statement": is_df,
            "Balance Sheet": bs_df,
            "Cash Flow Statement": cf_df,
        }

        # Print summary
        total_items = 0
        for name, df in statements.items():
            if df is not None and not df.empty:
                n_items = len(df.index)
                n_periods = len(df.columns)
                total_items += n_items
                print(f"      {name}: {n_items} line items x {n_periods} periods")
            else:
                print(f"      {name}: no data")
        print(f"      Total line items: {total_items}")

        # Step 3: Export to Excel
        print(f"\n[3/3] Exporting to Excel...")
        excel_path = export_to_excel(statements, company_name, ticker,
                                     output_dir)
        print(f"      Saved: {excel_path}")

        print(f"\nDone: {ticker.upper()}")
        return {
            "company_name": company_name,
            "ticker": ticker.upper(),
            "income_statement": is_df,
            "balance_sheet": bs_df,
            "cash_flow_statement": cf_df,
            "excel_path": excel_path,
        }
