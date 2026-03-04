"""Filing-level financial statement scraper.

Instead of guessing from XBRL taxonomy concepts, this module goes
straight to the actual 10-K / 10-Q filing on EDGAR, finds the
financial statements as the company presented them, and extracts
every single line item with its values.

How it works:
1. Find a filing's accession number from the submissions API.
2. Fetch FilingSummary.xml from the filing archive — this lists all
   report pages (R1.htm, R2.htm, ...) and their short names.
3. Match report short names to identify the Income Statement,
   Balance Sheet, and Cash Flow Statement.
4. Fetch each report's HTML page and parse the table rows to get
   every line item label and its period values, exactly as presented.
"""

import re
import time
import xml.etree.ElementTree as ET

import requests
import pandas as pd
from bs4 import BeautifulSoup

import sys
sys.path.insert(0, ".")
from config import SEC_USER_AGENT, SEC_REQUEST_DELAY


# -------------------------------------------------------------------------
# Patterns to identify which report is which financial statement.
# Matched against the <ShortName> or <LongName> in FilingSummary.xml.
# -------------------------------------------------------------------------

_IS_PATTERNS = [
    r"(?i)(?:consolidated\s+)?statements?\s+of\s+(?:income|operations|earnings)",
    r"(?i)(?:consolidated\s+)?income\s+statements?",
    r"(?i)(?:consolidated\s+)?statements?\s+of\s+comprehensive\s+(?:income|loss)",
    r"(?i)(?:consolidated\s+)?results?\s+of\s+operations?",
]

_BS_PATTERNS = [
    r"(?i)(?:consolidated\s+)?balance\s+sheets?",
    r"(?i)(?:consolidated\s+)?statements?\s+of\s+financial\s+(?:position|condition)",
]

_CF_PATTERNS = [
    r"(?i)(?:consolidated\s+)?statements?\s+of\s+cash\s+flows?",
]

# Patterns to exclude (parenthetical notes, policies, etc.)
_EXCLUDE_PATTERNS = [
    r"(?i)parenthetical",
    r"(?i)(?:notes|details|policies|additional|components|schedule)",
    r"(?i)comprehensive income.*(?:details|components)",
]


def _matches(text, patterns):
    """Check if text matches any of the given regex patterns."""
    return any(re.search(p, text) for p in patterns)


def _is_excluded(text):
    return _matches(text, _EXCLUDE_PATTERNS)


class FilingScraper:
    """Scrape financial statements directly from an EDGAR filing's HTML reports."""

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

    def _get(self, url, as_json=False):
        """Make a rate-limited GET request."""
        self._rate_limit()
        resp = self.session.get(url)
        resp.raise_for_status()
        if as_json:
            return resp.json()
        return resp

    # ------------------------------------------------------------------
    # Step 1: Build the filing archive base URL
    # ------------------------------------------------------------------

    def _filing_base_url(self, cik, accession_number):
        """Build the base URL for a filing's archive directory.

        Args:
            cik: CIK string (will strip leading zeros).
            accession_number: Accession number with dashes (e.g. '0000320193-23-000106').

        Returns:
            URL like https://www.sec.gov/Archives/edgar/data/320193/000032019323000106/
        """
        cik_clean = str(int(cik))  # strip leading zeros
        acc_no_dashes = accession_number.replace("-", "")
        return f"https://www.sec.gov/Archives/edgar/data/{cik_clean}/{acc_no_dashes}/"

    # ------------------------------------------------------------------
    # Step 2: Parse FilingSummary.xml to find the report pages
    # ------------------------------------------------------------------

    def get_filing_reports(self, cik, accession_number):
        """Fetch and parse FilingSummary.xml to get the list of report pages.

        Returns:
            List of dicts with keys:
                - 'short_name': Short report name (e.g. "BALANCE SHEETS")
                - 'long_name': Full report name
                - 'url': HTML file name (e.g. "R2.htm")
                - 'position': Report position number
                - 'category': 'Statements', 'Notes', 'Cover', etc.
        """
        base_url = self._filing_base_url(cik, accession_number)
        summary_url = base_url + "FilingSummary.xml"

        resp = self._get(summary_url)
        root = ET.fromstring(resp.content)

        # Handle namespace — FilingSummary.xml may or may not have one
        ns = ""
        if root.tag.startswith("{"):
            ns = root.tag.split("}")[0] + "}"

        reports = []
        for report in root.iter(f"{ns}Report"):
            short_name = report.findtext(f"{ns}ShortName", "").strip()
            long_name = report.findtext(f"{ns}LongName", "").strip()
            html_file = report.findtext(f"{ns}HtmlFileName", "").strip()
            position = report.findtext(f"{ns}Position", "0").strip()
            category = report.findtext(f"{ns}MenuCategory", "").strip()

            if html_file:
                reports.append({
                    "short_name": short_name,
                    "long_name": long_name,
                    "url": html_file,
                    "position": int(position) if position.isdigit() else 0,
                    "category": category,
                })

        return reports

    def identify_statements(self, reports):
        """Match reports to the three core financial statements.

        Returns:
            Dict with keys 'income_statement', 'balance_sheet', 'cash_flow',
            each mapping to the report dict (or None if not found).
        """
        result = {
            "income_statement": None,
            "balance_sheet": None,
            "cash_flow": None,
        }

        # Filter to 'Statements' category first, fall back to all
        statement_reports = [r for r in reports if r["category"] == "Statements"]
        if not statement_reports:
            statement_reports = reports

        for report in statement_reports:
            name = report["long_name"] or report["short_name"]
            if _is_excluded(name):
                continue

            if result["balance_sheet"] is None and _matches(name, _BS_PATTERNS):
                result["balance_sheet"] = report
            elif result["income_statement"] is None and _matches(name, _IS_PATTERNS):
                result["income_statement"] = report
            elif result["cash_flow"] is None and _matches(name, _CF_PATTERNS):
                result["cash_flow"] = report

        return result

    # ------------------------------------------------------------------
    # Step 3: Fetch and parse an individual report HTML page
    # ------------------------------------------------------------------

    def parse_report_html(self, cik, accession_number, html_filename):
        """Fetch a report HTML page (e.g. R2.htm) and parse its financial table.

        Returns:
            Dict with:
                - 'title': Statement title from the page
                - 'periods': List of column header strings (period labels)
                - 'line_items': List of dicts, each with:
                    - 'label': The line item text
                    - 'values': List of values (one per period), None for blanks
                    - 'is_bold': Whether the row was bold (likely a total/subtotal)
                    - 'indent': Indentation level (0, 1, 2, ...)
                    - 'is_abstract': Whether this is a section header with no values
        """
        base_url = self._filing_base_url(cik, accession_number)
        url = base_url + html_filename

        resp = self._get(url)
        soup = BeautifulSoup(resp.content, "lxml")

        # Find the main table
        table = soup.find("table")
        if not table:
            return {"title": "", "periods": [], "line_items": []}

        rows = table.find_all("tr")
        if not rows:
            return {"title": "", "periods": [], "line_items": []}

        # ---- Extract title ----
        title = ""
        title_tag = soup.find("th", colspan=True)
        if title_tag:
            title = title_tag.get_text(strip=True)

        # ---- Extract period headers ----
        periods = []
        header_row = None
        for row in rows:
            ths = row.find_all("th")
            if len(ths) >= 2:
                # This is likely the header row with period dates
                period_texts = []
                for th in ths:
                    text = th.get_text(separator=" ", strip=True)
                    # Skip the label column header
                    if text and not re.match(r"(?i)^(months?\s+ended|year\s+ended|line\s*items?|$)", text):
                        period_texts.append(text)
                if period_texts:
                    periods = period_texts
                    header_row = row
                    break

        # If no clear header found, look for dates in the first couple rows
        if not periods:
            for row in rows[:5]:
                cells = row.find_all(["th", "td"])
                for cell in cells:
                    text = cell.get_text(strip=True)
                    # Look for date patterns
                    if re.search(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|January|February|March|April|June|July|August|September|October|November|December)\b.*\d{4}", text):
                        periods.append(text)

        # ---- Extract line items ----
        line_items = []
        for row in rows:
            tds = row.find_all("td")
            if not tds:
                continue

            # First cell is usually the label
            label_cell = tds[0]
            label = label_cell.get_text(separator=" ", strip=True)

            # Skip empty rows, header-only rows, pure number rows
            if not label or label.startswith("$") or re.match(r"^[\d,.\-()]+$", label):
                continue

            # Skip rows that are just dates or period headers
            if re.match(r"^(?:Three|Six|Nine|Twelve)\s+Months?\s+Ended", label, re.IGNORECASE):
                continue
            if re.match(r"^(?:Year|Fiscal\s+Year)\s+Ended", label, re.IGNORECASE):
                continue

            # Detect indentation from CSS or nested elements
            indent = 0
            style = label_cell.get("style", "")
            padding_match = re.search(r"padding-left:\s*(\d+)", style)
            if padding_match:
                # Roughly convert pixels to indent level
                indent = int(padding_match.group(1)) // 15
            # Also check for &nbsp; or nested spans
            raw_html = str(label_cell)
            nbsp_count = raw_html.count("&nbsp;") + raw_html.count("\xa0")
            if nbsp_count > indent:
                indent = min(nbsp_count // 2, 5)

            # Detect bold (totals / subtotals)
            is_bold = bool(
                label_cell.find("b") or
                label_cell.find("strong") or
                "font-weight:bold" in style or
                "font-weight: bold" in style or
                "font-weight:700" in style
            )

            # Extract values from remaining cells
            values = []
            for td in tds[1:]:
                text = td.get_text(strip=True)
                # Clean up currency formatting
                text = text.replace("$", "").replace(",", "").replace("—", "").replace("–", "")
                text = text.replace("\xa0", "").strip()

                if not text or text == "—" or text == "–":
                    values.append(None)
                    continue

                # Handle parentheses = negative
                negative = False
                if text.startswith("(") and text.endswith(")"):
                    negative = True
                    text = text[1:-1].strip()

                try:
                    num = float(text)
                    if negative:
                        num = -num
                    values.append(num)
                except ValueError:
                    values.append(None)

            # Determine if this is an abstract/section header (no numeric values)
            is_abstract = all(v is None for v in values) if values else True

            line_items.append({
                "label": label,
                "values": values,
                "is_bold": is_bold,
                "indent": indent,
                "is_abstract": is_abstract,
            })

        return {
            "title": title,
            "periods": periods,
            "line_items": line_items,
        }

    # ------------------------------------------------------------------
    # Step 4: Convert parsed data into a DataFrame
    # ------------------------------------------------------------------

    def statement_to_dataframe(self, parsed):
        """Convert a parsed statement dict into a pandas DataFrame.

        Rows = line items (with indentation shown via leading spaces).
        Columns = fiscal periods.
        """
        if not parsed["line_items"]:
            return pd.DataFrame()

        periods = parsed["periods"]
        rows = {}

        for item in parsed["line_items"]:
            label = item["label"]

            # Add indent prefix for visual hierarchy
            if item["indent"] > 0:
                label = "  " * item["indent"] + label

            # Handle duplicate labels by appending a counter
            original_label = label
            counter = 1
            while label in rows:
                counter += 1
                label = f"{original_label} ({counter})"

            # Map values to periods
            val_dict = {}
            for i, period in enumerate(periods):
                if i < len(item["values"]):
                    val_dict[period] = item["values"][i]
                else:
                    val_dict[period] = None

            rows[label] = val_dict

        df = pd.DataFrame(rows).T
        df.index.name = "Line Item"
        return df

    # ------------------------------------------------------------------
    # High-level: scrape all 3 statements from a single filing
    # ------------------------------------------------------------------

    def scrape_filing_statements(self, cik, accession_number):
        """Scrape all three financial statements from a specific filing.

        Args:
            cik: Company CIK (zero-padded or not).
            accession_number: Filing accession number (with dashes).

        Returns:
            Dict with:
                - 'Income Statement': DataFrame
                - 'Balance Sheet': DataFrame
                - 'Cash Flow Statement': DataFrame
                - 'raw': Dict of raw parsed data for each statement
                - 'reports': The full list of reports found in FilingSummary.xml
        """
        print(f"      Fetching FilingSummary.xml...")
        reports = self.get_filing_reports(cik, accession_number)
        print(f"      Found {len(reports)} report pages in filing")

        statements_map = self.identify_statements(reports)

        result = {
            "Income Statement": pd.DataFrame(),
            "Balance Sheet": pd.DataFrame(),
            "Cash Flow Statement": pd.DataFrame(),
            "raw": {},
            "reports": reports,
        }

        name_map = {
            "income_statement": "Income Statement",
            "balance_sheet": "Balance Sheet",
            "cash_flow": "Cash Flow Statement",
        }

        for key, display_name in name_map.items():
            report = statements_map[key]
            if report is None:
                print(f"      WARNING: Could not identify {display_name} in filing")
                continue

            print(f"      Parsing {display_name} from {report['url']} "
                  f"({report['short_name']})...")

            parsed = self.parse_report_html(cik, accession_number, report["url"])
            df = self.statement_to_dataframe(parsed)
            result[display_name] = df
            result["raw"][display_name] = parsed

            n_items = len(parsed["line_items"])
            n_periods = len(parsed["periods"])
            print(f"        → {n_items} line items x {n_periods} periods")

        return result

    def scrape_multiple_filings(self, cik, accession_numbers):
        """Scrape statements from multiple filings and combine the data.

        This lets you build a time series across multiple 10-K or 10-Q
        filings, since each filing typically only shows 1-3 periods.

        Args:
            cik: Company CIK.
            accession_numbers: List of accession numbers (newest first).

        Returns:
            Dict with combined DataFrames for each statement.
        """
        all_statements = {
            "Income Statement": [],
            "Balance Sheet": [],
            "Cash Flow Statement": [],
        }

        for acc in accession_numbers:
            try:
                result = self.scrape_filing_statements(cik, acc)
                for name in all_statements:
                    df = result[name]
                    if not df.empty:
                        all_statements[name].append(df)
            except Exception as e:
                print(f"      Error scraping {acc}: {e}")
                continue

        # Combine DataFrames — merge on line items, union of periods
        combined = {}
        for name, dfs in all_statements.items():
            if not dfs:
                combined[name] = pd.DataFrame()
                continue

            # Start with the most recent filing
            merged = dfs[0]
            for df in dfs[1:]:
                # Add columns (periods) that aren't already present
                for col in df.columns:
                    if col not in merged.columns:
                        # Match rows by label
                        for idx in df.index:
                            if idx in merged.index:
                                merged.loc[idx, col] = df.loc[idx, col]
                            else:
                                # New line item from older filing — add it
                                merged.loc[idx, col] = df.loc[idx, col]

            # Sort columns chronologically (try to parse dates)
            try:
                sorted_cols = sorted(merged.columns, key=lambda x: pd.to_datetime(x, format="mixed"))
                merged = merged[sorted_cols]
            except Exception:
                pass  # Keep original order if date parsing fails

            combined[name] = merged

        return combined
