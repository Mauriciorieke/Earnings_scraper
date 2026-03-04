"""Command-line interface for the earnings scraper.

Usage:
    python -m earnings_scraper.cli AAPL              # Scrape from actual 10-K filing
    python -m earnings_scraper.cli AAPL --quarterly   # Scrape from 10-Q filing
    python -m earnings_scraper.cli AAPL --filings 3   # Combine last 3 filings for more history
    python -m earnings_scraper.cli AAPL --transcripts # Include earnings press releases
    python -m earnings_scraper.cli AAPL MSFT GOOG     # Multiple tickers
    python -m earnings_scraper.cli AAPL --xbrl        # Use XBRL taxonomy mode (old method)
    python -m earnings_scraper.cli AAPL --edgartools   # Use edgartools library (5yr history)
    python -m earnings_scraper.cli AAPL --edgartools --years 3  # Custom year range
"""

import argparse
import sys

sys.path.insert(0, ".")
from earnings_scraper.edgar import EdgarClient
from earnings_scraper.filing_scraper import FilingScraper
from earnings_scraper.financials import get_all_statements
from earnings_scraper.transcripts import TranscriptScraper
from earnings_scraper.excel_output import export_to_excel
from earnings_scraper.edgartools_scraper import EdgarToolsScraper

def run_for_ticker(ticker, quarterly=False, include_transcripts=False,
                   output_dir=None, num_filings=1, use_xbrl=False,
                   use_edgartools=False, years=5):
    """Run the full pipeline for a single ticker."""
    print(f"\n{'='*60}")
    print(f"  Processing: {ticker.upper()}")
    print(f"{'='*60}")

    # ----- edgartools library mode -----
    if use_edgartools:
        scraper = EdgarToolsScraper()
        result = scraper.scrape(
            ticker,
            quarterly=quarterly,
            years=years,
            output_dir=output_dir,
        )
        return result["excel_path"]

    client = EdgarClient()

    if use_xbrl:
        # ----- Legacy XBRL taxonomy mode -----
        print(f"\n[1/3] Fetching XBRL data from SEC EDGAR...")
        data = client.get_financial_data(ticker)
        company_name = data["company_name"]
        cik = data["cik"]
        facts = data["facts"]
        print(f"      Company: {company_name} (CIK: {cik})")
        print(f"      Total XBRL concepts: {len(facts.get('us-gaap', {}))}")

        period_type = "quarterly" if quarterly else "annual"
        print(f"\n[2/3] Discovering ALL {period_type} line items from XBRL...")
        statements = get_all_statements(facts, quarterly=quarterly)
    else:
        # ----- New filing-based mode (default) -----
        form_type = "10-Q" if quarterly else "10-K"
        print(f"\n[1/3] Finding latest {form_type} filing(s) on SEC EDGAR...")

        info = client.get_company_info(ticker)
        company_name = info["company_name"]
        cik = info["cik"]
        print(f"      Company: {company_name} (CIK: {cik})")

        filings = client.get_recent_filings(ticker, [form_type])
        if not filings:
            raise ValueError(f"No {form_type} filings found for {ticker}")

        filings_to_use = filings[:num_filings]
        for f in filings_to_use:
            print(f"      Filing: {f['form']} filed {f['filingDate']} "
                  f"(accession: {f['accessionNumber']})")

        print(f"\n[2/3] Scraping financial statements from filing HTML...")
        scraper = FilingScraper()

        if num_filings == 1:
            filing = filings_to_use[0]
            statements = scraper.scrape_filing_statements(
                cik, filing["accessionNumber"]
            )
            # Remove non-DataFrame keys
            statements.pop("raw", None)
            statements.pop("reports", None)
        else:
            acc_numbers = [f["accessionNumber"] for f in filings_to_use]
            statements = scraper.scrape_multiple_filings(cik, acc_numbers)
    data = client.get_financial_data(ticker)
    company_name = data["company_name"]
    cik = data["cik"]
    print(f"      Company: {company_name} (CIK: {cik})")

    # Step 2: Parse into financial statements
    period_type = "quarterly" if quarterly else "annual"
    print(f"\n[2/3] Parsing {period_type} financial statements...")
    statements = get_all_statements(data["facts"], quarterly=quarterly)

    for name, df in statements.items():
        n_items = len(df.index)
        n_periods = len(df.columns)
        print(f"      {name}: {n_items} line items x {n_periods} periods")

    # Step 3: Export to Excel
    print(f"\n[3/3] Exporting to Excel...")
    filepath = export_to_excel(statements, company_name, ticker, output_dir)
    print(f"      Saved: {filepath}")

    # Optional: Fetch earnings press releases
    if include_transcripts:
        print(f"\n[+]   Fetching earnings press releases...")
        tscraper = TranscriptScraper()
        releases = tscraper.get_earnings_press_releases(cik, max_results=3)
        if releases:
            for r in releases:
                print(f"      - {r['filingDate']}: {len(r.get('sections', {}))} sections found")
                for section_name in r.get("sections", {}):
                    print(f"        * {section_name}")
        else:
            print("      No earnings press releases found.")

    print(f"\nDone: {ticker.upper()}")
    return filepath


def main():
    parser = argparse.ArgumentParser(
        description="Scrape earnings data from SEC EDGAR and export to Excel.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m earnings_scraper.cli AAPL
  python -m earnings_scraper.cli AAPL --quarterly
  python -m earnings_scraper.cli AAPL --filings 3
  python -m earnings_scraper.cli AAPL MSFT GOOG --transcripts
  python -m earnings_scraper.cli AAPL -o my_models/
  python -m earnings_scraper.cli AAPL --xbrl
  python -m earnings_scraper.cli AAPL --edgartools
  python -m earnings_scraper.cli AAPL --edgartools --years 3
        """,
    )
    parser.add_argument(
        "tickers",
        nargs="+",
        help="One or more stock ticker symbols (e.g. AAPL MSFT GOOG)",
    )
    parser.add_argument(
        "-q", "--quarterly",
        action="store_true",
        help="Pull from 10-Q filings instead of 10-K (default: 10-K)",
    )
    parser.add_argument(
        "-n", "--filings",
        type=int,
        default=1,
        help="Number of filings to scrape and combine (default: 1, latest only)",
    )
    parser.add_argument(
        "-t", "--transcripts",
        action="store_true",
        help="Also fetch and display earnings press release sections",
    )
    parser.add_argument(
        "-o", "--output-dir",
        default=None,
        help="Output directory for Excel files (default: output/)",
    )
    parser.add_argument(
        "--xbrl",
        action="store_true",
        help="Use XBRL taxonomy mode instead of filing HTML scraping",
    )
    parser.add_argument(
        "--edgartools",
        action="store_true",
        help="Use the edgartools library for data extraction (recommended for 5yr history)",
    )
    parser.add_argument(
        "-y", "--years",
        type=int,
        default=5,
        help="Number of years of history to pull (default: 5, used with --edgartools)",
    )

    args = parser.parse_args()

    print("Earnings Scraper v2.0")
    if args.edgartools:
        print("Using edgartools library for SEC EDGAR data extraction")
    else:
        print("Scraping directly from SEC filing documents (no API key required)")

    results = []
    for ticker in args.tickers:
        try:
            path = run_for_ticker(
                ticker,
                quarterly=args.quarterly,
                include_transcripts=args.transcripts,
                output_dir=args.output_dir,
                num_filings=args.filings,
                use_xbrl=args.xbrl,
                use_edgartools=args.edgartools,
                years=args.years,
            )
            results.append((ticker, path))
        except Exception as e:
            print(f"\nERROR processing {ticker}: {e}")
            continue

    if results:
        print(f"\n{'='*60}")
        print("  All files saved:")
        for ticker, path in results:
            print(f"    {ticker.upper()}: {path}")
        print(f"{'='*60}")


if __name__ == "__main__":
    main()
