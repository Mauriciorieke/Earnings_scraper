"""Parse XBRL company facts into structured financial statements.

Extracts income statement, balance sheet, and cash flow statement line items
from SEC EDGAR XBRL data and organises them by fiscal period.
"""

from datetime import datetime
import pandas as pd


# -------------------------------------------------------------------------
# XBRL concept mappings for the three financial statements.
# Maps human-readable names to us-gaap taxonomy concept names.
# -------------------------------------------------------------------------

INCOME_STATEMENT_CONCEPTS = {
    "Revenue": [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueNet",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
    ],
    "Cost of Revenue": [
        "CostOfRevenue",
        "CostOfGoodsAndServicesSold",
        "CostOfGoodsSold",
    ],
    "Gross Profit": [
        "GrossProfit",
    ],
    "Research & Development": [
        "ResearchAndDevelopmentExpense",
    ],
    "SG&A": [
        "SellingGeneralAndAdministrativeExpense",
    ],
    "Operating Expenses": [
        "OperatingExpenses",
        "CostsAndExpenses",
    ],
    "Operating Income": [
        "OperatingIncomeLoss",
    ],
    "Interest Expense": [
        "InterestExpense",
        "InterestExpenseDebt",
    ],
    "Income Before Tax": [
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    ],
    "Income Tax Expense": [
        "IncomeTaxExpenseBenefit",
    ],
    "Net Income": [
        "NetIncomeLoss",
        "ProfitLoss",
    ],
    "EPS (Basic)": [
        "EarningsPerShareBasic",
    ],
    "EPS (Diluted)": [
        "EarningsPerShareDiluted",
    ],
    "Shares Outstanding (Basic)": [
        "WeightedAverageNumberOfShareOutstandingBasicAndDiluted",
        "WeightedAverageNumberOfSharesOutstandingBasic",
    ],
    "Shares Outstanding (Diluted)": [
        "WeightedAverageNumberOfDilutedSharesOutstanding",
    ],
}

BALANCE_SHEET_CONCEPTS = {
    "Cash & Equivalents": [
        "CashAndCashEquivalentsAtCarryingValue",
        "Cash",
    ],
    "Short-Term Investments": [
        "ShortTermInvestments",
        "AvailableForSaleSecuritiesCurrent",
        "MarketableSecuritiesCurrent",
    ],
    "Accounts Receivable": [
        "AccountsReceivableNetCurrent",
        "AccountsReceivableNet",
    ],
    "Inventory": [
        "InventoryNet",
    ],
    "Total Current Assets": [
        "AssetsCurrent",
    ],
    "PP&E (Net)": [
        "PropertyPlantAndEquipmentNet",
    ],
    "Goodwill": [
        "Goodwill",
    ],
    "Total Assets": [
        "Assets",
    ],
    "Accounts Payable": [
        "AccountsPayableCurrent",
    ],
    "Short-Term Debt": [
        "ShortTermBorrowings",
        "DebtCurrent",
    ],
    "Total Current Liabilities": [
        "LiabilitiesCurrent",
    ],
    "Long-Term Debt": [
        "LongTermDebt",
        "LongTermDebtNoncurrent",
    ],
    "Total Liabilities": [
        "Liabilities",
    ],
    "Retained Earnings": [
        "RetainedEarningsAccumulatedDeficit",
    ],
    "Total Stockholders Equity": [
        "StockholdersEquity",
    ],
    "Total Liabilities & Equity": [
        "LiabilitiesAndStockholdersEquity",
    ],
}

CASH_FLOW_CONCEPTS = {
    "Net Income (CF)": [
        "NetIncomeLoss",
        "ProfitLoss",
    ],
    "Depreciation & Amortization": [
        "DepreciationDepletionAndAmortization",
        "DepreciationAndAmortization",
        "DepreciationAmortizationAndAccretionNet",
    ],
    "Stock-Based Compensation": [
        "ShareBasedCompensation",
        "AllocatedShareBasedCompensationExpense",
    ],
    "Cash from Operations": [
        "NetCashProvidedByUsedInOperatingActivities",
    ],
    "Capital Expenditures": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
    ],
    "Acquisitions": [
        "PaymentsToAcquireBusinessesNetOfCashAcquired",
    ],
    "Purchases of Investments": [
        "PaymentsToAcquireInvestments",
        "PaymentsToAcquireAvailableForSaleSecuritiesDebt",
    ],
    "Cash from Investing": [
        "NetCashProvidedByUsedInInvestingActivities",
    ],
    "Dividends Paid": [
        "PaymentsOfDividends",
        "PaymentsOfDividendsCommonStock",
    ],
    "Share Repurchases": [
        "PaymentsForRepurchaseOfCommonStock",
    ],
    "Debt Issuance / Repayment": [
        "ProceedsFromRepaymentsOfShortTermDebt",
    ],
    "Cash from Financing": [
        "NetCashProvidedByUsedInFinancingActivities",
    ],
    "Net Change in Cash": [
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect",
        "CashAndCashEquivalentsPeriodIncreaseDecrease",
    ],
}


def _extract_concept_values(facts, concept_names, taxonomy="us-gaap"):
    """Search for the first matching concept and return its reported values.

    Args:
        facts: The 'facts' dict from EDGAR company facts JSON.
        concept_names: Ordered list of XBRL concept names to try.
        taxonomy: XBRL taxonomy namespace (default 'us-gaap').

    Returns:
        List of dicts with keys: 'end', 'val', 'form', 'fy', 'fp', 'filed'.
        Empty list if no matching concept is found.
    """
    tax_data = facts.get(taxonomy, {})
    for concept in concept_names:
        concept_data = tax_data.get(concept)
        if concept_data is None:
            continue
        # Prefer USD units; fall back to 'shares' or 'USD/shares'
        for unit_key in ["USD", "shares", "USD/shares", "pure"]:
            units = concept_data.get("units", {}).get(unit_key)
            if units:
                return units
    return []


def _filter_annual(values):
    """Keep only annual (10-K / FY) data points without segment/dimension tags."""
    results = []
    for v in values:
        if v.get("form") == "10-K" and v.get("fp") == "FY":
            # Skip dimensioned / segment-level breakdowns
            if "frame" in v or "segment" not in str(v):
                results.append(v)
    return results


def _filter_quarterly(values):
    """Keep only quarterly (10-Q) data points."""
    results = []
    for v in values:
        if v.get("form") in ("10-Q", "10-K") and v.get("fp") in ("Q1", "Q2", "Q3", "Q4"):
            results.append(v)
    return results


def _deduplicate_by_period(values):
    """Keep the most recently filed value for each fiscal period end date."""
    by_period = {}
    for v in values:
        end = v.get("end")
        if not end:
            continue
        existing = by_period.get(end)
        if existing is None or v.get("filed", "") > existing.get("filed", ""):
            by_period[end] = v
    # Sort by period end descending (most recent first)
    sorted_periods = sorted(by_period.items(), key=lambda x: x[0], reverse=True)
    return [v for _, v in sorted_periods]


def _build_statement_df(facts, concept_map, period_filter, max_periods=20):
    """Build a DataFrame for one financial statement.

    Rows = line items, Columns = fiscal period end dates.
    """
    rows = {}
    all_periods = set()

    for label, concepts in concept_map.items():
        raw = _extract_concept_values(facts, concepts)
        filtered = period_filter(raw)
        deduped = _deduplicate_by_period(filtered)[:max_periods]
        row_data = {}
        for v in deduped:
            end = v["end"]
            all_periods.add(end)
            row_data[end] = v["val"]
        rows[label] = row_data

    # Sort periods chronologically
    sorted_periods = sorted(all_periods)
    df = pd.DataFrame(rows).T
    # Reindex to sorted periods
    df = df.reindex(columns=sorted_periods)
    df.index.name = "Line Item"
    return df


def get_income_statement(facts, quarterly=False, max_periods=20):
    """Extract income statement data as a DataFrame."""
    filt = _filter_quarterly if quarterly else _filter_annual
    return _build_statement_df(facts, INCOME_STATEMENT_CONCEPTS, filt, max_periods)


def get_balance_sheet(facts, quarterly=False, max_periods=20):
    """Extract balance sheet data as a DataFrame."""
    filt = _filter_quarterly if quarterly else _filter_annual
    return _build_statement_df(facts, BALANCE_SHEET_CONCEPTS, filt, max_periods)


def get_cash_flow_statement(facts, quarterly=False, max_periods=20):
    """Extract cash flow statement data as a DataFrame."""
    filt = _filter_quarterly if quarterly else _filter_annual
    return _build_statement_df(facts, CASH_FLOW_CONCEPTS, filt, max_periods)


def get_all_statements(facts, quarterly=False, max_periods=20):
    """Return all three financial statements as a dict of DataFrames."""
    return {
        "Income Statement": get_income_statement(facts, quarterly, max_periods),
        "Balance Sheet": get_balance_sheet(facts, quarterly, max_periods),
        "Cash Flow Statement": get_cash_flow_statement(facts, quarterly, max_periods),
    }
