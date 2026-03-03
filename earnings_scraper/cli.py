"""Command-line interface for the earnings scraper.

Usage:
    python -m earnings_scraper.cli AAPL              # Full 3-statement model
    python -m earnings_scraper.cli AAPL --quarterly   # Quarterly data
    python -m earnings_scraper.cli AAPL --transcripts # Include earnings press releases
    python -m earnings_scraper.cli AAPL MSFT GOOG     # Multiple tickers
"""

import argparse
import sys

sys.path.insert(0, ".")
from earnings_scraper.edgar import EdgarClient
from earnings_scraper.financials import get_all_statements
from earnings_scraper.transcripts import TranscriptScraper
from earnings_scraper.excel_output import export_to_excel


def run_for_ticker(ticker, quarterly=False, include_transcripts=False, output_dir=None):
    """Run the full pipeline for a single ticker."""
    print(f"\n{'='*60}")
    print(f"  Processing: {ticker.upper()}")
    print(f"{'='*60}")

    # Step 1: Fetch financial data from EDGAR
    print(f"\n[1/3] Fetching financial data from SEC EDGAR...")
    client = EdgarClient()
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
        scraper = TranscriptScraper()
        releases = scraper.get_earnings_press_releases(cik, max_results=3)
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
  python -m earnings_scraper.cli AAPL MSFT GOOG --transcripts
  python -m earnings_scraper.cli AAPL -o my_models/
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
        help="Pull quarterly data instead of annual (default: annual)",
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

    args = parser.parse_args()

    print("Earnings Scraper v1.0")
    print("Pulling data from SEC EDGAR (no API key required)")

    results = []
    for ticker in args.tickers:
        try:
            path = run_for_ticker(
                ticker,
                quarterly=args.quarterly,
                include_transcripts=args.transcripts,
                output_dir=args.output_dir,
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
