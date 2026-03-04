"""Parse XBRL company facts into structured financial statements.

UNIVERSAL PARSER — discovers ALL line items reported by a company
in their SEC filings, instead of relying on a hardcoded concept list.

Classification logic:
- Balance Sheet: XBRL "instant" values (point-in-time, no start date)
- Income Statement vs Cash Flow: "duration" values classified by concept
  name keyword patterns (cash flow concepts contain keywords like
  "CashProvided", "Payments", "Proceeds", etc.)

Line items are auto-labeled using the XBRL label field from EDGAR.
"""

import re
import pandas as pd


# -------------------------------------------------------------------------
# Keyword patterns for classifying duration concepts into IS vs CF.
# If a concept name matches any CF pattern, it goes to Cash Flow.
# Otherwise it's classified as Income Statement.
# -------------------------------------------------------------------------

_CF_KEYWORDS = [
    r"NetCashProvided",
    r"NetCashUsed",
    r"CashProvided",
    r"CashUsed",
    r"PaymentsToAcquire",
    r"PaymentsFor",
    r"PaymentsOf",
    r"ProceedsFrom",
    r"RepaymentsOf",
    r"IncreaseDecreaseIn(?!come)",  # working capital changes, not income
    r"EffectOfExchangeRate.*Cash",
    r"CashCashEquivalents.*Period",
    r"CashAndCashEquivalents.*Period",
    r"Depreciation.*(?:Operating|Activities)",
    r"DepreciationDepletionAndAmortization$",
    r"ShareBasedCompensation$",
    r"DeferredIncomeTax(?:Expense)?(?:Benefit)?$",
    r"AmortizationOf",
    r"GainLossOn(?:Sale|Disposition|Extinguishment)",
    r"CapitalExpenditure",
    r"PurchaseOfInvestment",
    r"SaleOfInvestment",
    r"IssuanceOfDebt",
    r"IssuanceOfStock",
    r"RepurchaseOf",
    r"DividendsPaid",
    r"PaymentsOfDividends",
    r"Operating(?:Activities|CashFlow)",
    r"Investing(?:Activities|CashFlow)",
    r"Financing(?:Activities|CashFlow)",
]

_CF_PATTERN = re.compile("|".join(_CF_KEYWORDS), re.IGNORECASE)

# Concepts that are ambiguous (appear on both IS and CF) — force to IS
_FORCE_IS_CONCEPTS = {
    "NetIncomeLoss",
    "ProfitLoss",
    "IncomeTaxExpenseBenefit",
    "DepreciationAndAmortization",
}

# -------------------------------------------------------------------------
# Concept name → human-readable label conversion
# -------------------------------------------------------------------------

def _concept_to_label(concept_name, xbrl_label=None):
    """Convert a CamelCase XBRL concept name to a readable label.

    Uses the XBRL-provided label if available, otherwise converts
    CamelCase to spaced words.
    """
    if xbrl_label:
        return xbrl_label
    # Insert space before uppercase letters that follow lowercase
    label = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", concept_name)
    # Insert space before uppercase letters followed by lowercase (acronyms)
    label = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", label)
    return label


# -------------------------------------------------------------------------
# Priority ordering — well-known concepts appear first in each statement
# -------------------------------------------------------------------------

IS_PRIORITY = [
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "SalesRevenueNet",
    "SalesRevenueGoodsNet",
    "SalesRevenueServicesNet",
    "CostOfRevenue",
    "CostOfGoodsAndServicesSold",
    "CostOfGoodsSold",
    "GrossProfit",
    "ResearchAndDevelopmentExpense",
    "SellingGeneralAndAdministrativeExpense",
    "SellingAndMarketingExpense",
    "GeneralAndAdministrativeExpense",
    "OperatingExpenses",
    "CostsAndExpenses",
    "OperatingIncomeLoss",
    "InterestExpense",
    "InterestExpenseDebt",
    "InterestIncome",
    "InterestIncomeExpenseNet",
    "OtherNonoperatingIncomeExpense",
    "NonoperatingIncomeExpense",
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    "IncomeTaxExpenseBenefit",
    "NetIncomeLoss",
    "ProfitLoss",
    "NetIncomeLossAvailableToCommonStockholdersBasic",
    "ComprehensiveIncomeNetOfTax",
    "EarningsPerShareBasic",
    "EarningsPerShareDiluted",
    "WeightedAverageNumberOfSharesOutstandingBasic",
    "WeightedAverageNumberOfShareOutstandingBasicAndDiluted",
    "WeightedAverageNumberOfDilutedSharesOutstanding",
]

BS_PRIORITY = [
    "CashAndCashEquivalentsAtCarryingValue",
    "Cash",
    "ShortTermInvestments",
    "MarketableSecuritiesCurrent",
    "AvailableForSaleSecuritiesCurrent",
    "AccountsReceivableNetCurrent",
    "AccountsReceivableNet",
    "InventoryNet",
    "InventoryFinishedGoods",
    "InventoryWorkInProcess",
    "InventoryRawMaterials",
    "PrepaidExpenseAndOtherAssetsCurrent",
    "OtherAssetsCurrent",
    "AssetsCurrent",
    "PropertyPlantAndEquipmentNet",
    "PropertyPlantAndEquipmentGross",
    "AccumulatedDepreciationDepletionAndAmortizationPropertyPlantAndEquipment",
    "OperatingLeaseRightOfUseAsset",
    "Goodwill",
    "IntangibleAssetsNetExcludingGoodwill",
    "OtherAssetsNoncurrent",
    "Assets",
    "AccountsPayableCurrent",
    "AccruedLiabilitiesCurrent",
    "ShortTermBorrowings",
    "DebtCurrent",
    "CommercialPaper",
    "DeferredRevenueCurrent",
    "ContractWithCustomerLiabilityCurrent",
    "OtherLiabilitiesCurrent",
    "LiabilitiesCurrent",
    "LongTermDebt",
    "LongTermDebtNoncurrent",
    "OperatingLeaseLiabilityNoncurrent",
    "DeferredRevenueNoncurrent",
    "DeferredTaxLiabilitiesNoncurrent",
    "OtherLiabilitiesNoncurrent",
    "Liabilities",
    "CommonStockValue",
    "CommonStockSharesOutstanding",
    "AdditionalPaidInCapital",
    "AdditionalPaidInCapitalCommonStock",
    "RetainedEarningsAccumulatedDeficit",
    "AccumulatedOtherComprehensiveIncomeLossNetOfTax",
    "TreasuryStockValue",
    "StockholdersEquity",
    "MinorityInterest",
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    "LiabilitiesAndStockholdersEquity",
]

CF_PRIORITY = [
    "NetIncomeLoss",
    "ProfitLoss",
    "DepreciationDepletionAndAmortization",
    "DepreciationAndAmortization",
    "ShareBasedCompensation",
    "AllocatedShareBasedCompensationExpense",
    "DeferredIncomeTaxExpenseBenefit",
    "DeferredIncomeTaxesAndTaxCredits",
    "OtherNoncashIncomeExpense",
    "IncreaseDecreaseInAccountsReceivable",
    "IncreaseDecreaseInInventories",
    "IncreaseDecreaseInAccountsPayable",
    "IncreaseDecreaseInOtherOperatingLiabilities",
    "IncreaseDecreaseInOtherOperatingAssets",
    "IncreaseDecreaseInAccruedLiabilities",
    "IncreaseDecreaseInContractWithCustomerLiability",
    "NetCashProvidedByUsedInOperatingActivities",
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PaymentsToAcquireBusinessesNetOfCashAcquired",
    "PaymentsToAcquireInvestments",
    "PaymentsToAcquireAvailableForSaleSecuritiesDebt",
    "ProceedsFromSaleOfAvailableForSaleSecuritiesDebt",
    "ProceedsFromMaturitiesPrepaymentsAndCallsOfAvailableForSaleSecurities",
    "ProceedsFromSaleOfPropertyPlantAndEquipment",
    "PaymentsToAcquireOtherInvestments",
    "ProceedsFromSaleOfOtherInvestments",
    "NetCashProvidedByUsedInInvestingActivities",
    "PaymentsOfDividends",
    "PaymentsOfDividendsCommonStock",
    "PaymentsForRepurchaseOfCommonStock",
    "ProceedsFromIssuanceOfCommonStock",
    "ProceedsFromStockOptionsExercised",
    "ProceedsFromIssuanceOfLongTermDebt",
    "RepaymentsOfLongTermDebt",
    "ProceedsFromRepaymentsOfShortTermDebt",
    "ProceedsFromRepaymentsOfCommercialPaper",
    "NetCashProvidedByUsedInFinancingActivities",
    "EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect",
    "CashAndCashEquivalentsPeriodIncreaseDecrease",
]


# -------------------------------------------------------------------------
# Core extraction helpers
# -------------------------------------------------------------------------

def _get_unit_values(concept_data):
    """Get the best unit values from a concept (prefer USD, then shares, etc.)."""
    units = concept_data.get("units", {})
    for unit_key in ["USD", "shares", "USD/shares", "pure"]:
        if unit_key in units:
            return units[unit_key], unit_key
    # Fall back to first available unit
    for unit_key, vals in units.items():
        return vals, unit_key
    return [], None


def _is_instant(values):
    """Check if values are instant (balance sheet) vs duration (IS/CF).

    Instant values have no 'start' date — they represent a point in time.
    Duration values have both 'start' and 'end' — they represent a period.
    """
    for v in values:
        if "start" in v and v["start"]:
            return False
        # If there's an 'end' but no 'start', it's instant
        if "end" in v:
            return True
    return False


def _classify_concept(concept_name, values):
    """Classify a concept into 'BS', 'IS', or 'CF'.

    Logic:
    - Instant values → Balance Sheet
    - Duration values with CF keywords → Cash Flow
    - Everything else → Income Statement
    """
    if _is_instant(values):
        return "BS"

    # Duration — check if it's a cash flow concept
    if concept_name in _FORCE_IS_CONCEPTS:
        return "IS"

    if _CF_PATTERN.search(concept_name):
        return "CF"

    return "IS"


def _filter_annual(values):
    """Keep only annual (10-K / FY) data points."""
    results = []
    for v in values:
        if v.get("form") == "10-K" and v.get("fp") == "FY":
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
    sorted_periods = sorted(by_period.items(), key=lambda x: x[0], reverse=True)
    return [v for _, v in sorted_periods]


# -------------------------------------------------------------------------
# Universal discovery
# -------------------------------------------------------------------------

def discover_all_concepts(facts, quarterly=False, max_periods=20):
    """Scan ALL us-gaap concepts and classify them into financial statements.

    Args:
        facts: The 'facts' dict from EDGAR company facts JSON.
        quarterly: If True, filter for quarterly data; otherwise annual.
        max_periods: Max number of periods to keep per concept.

    Returns:
        Dict with keys 'IS', 'BS', 'CF', each mapping to a dict of:
            concept_name -> {
                'label': str,
                'unit': str,
                'values': {period_end_date: value, ...}
            }
    """
    period_filter = _filter_quarterly if quarterly else _filter_annual
    gaap = facts.get("us-gaap", {})

    classified = {"IS": {}, "BS": {}, "CF": {}}

    for concept_name, concept_data in gaap.items():
        values, unit = _get_unit_values(concept_data)
        if not values:
            continue

        # Filter to the desired periodicity
        filtered = period_filter(values)
        if not filtered:
            continue

        # Deduplicate
        deduped = _deduplicate_by_period(filtered)[:max_periods]
        if not deduped:
            continue

        # Classify
        statement = _classify_concept(concept_name, values)

        # Build period -> value map
        period_values = {}
        for v in deduped:
            period_values[v["end"]] = v["val"]

        label = concept_data.get("label", _concept_to_label(concept_name))

        classified[statement][concept_name] = {
            "label": label,
            "unit": unit,
            "values": period_values,
        }

    return classified


def _sort_concepts(concepts_dict, priority_list):
    """Sort concepts: priority items first (in order), then rest alphabetically by label."""
    priority_set = set(priority_list)
    priority_order = {name: i for i, name in enumerate(priority_list)}

    priority_items = []
    other_items = []

    for concept_name, data in concepts_dict.items():
        if concept_name in priority_set:
            priority_items.append((concept_name, data))
        else:
            other_items.append((concept_name, data))

    priority_items.sort(key=lambda x: priority_order.get(x[0], 999))
    other_items.sort(key=lambda x: x[1]["label"])

    return priority_items + other_items


def _build_universal_df(concepts_dict, priority_list):
    """Build a DataFrame from discovered concepts.

    Rows = line items (using XBRL labels), Columns = fiscal period end dates.
    """
    sorted_concepts = _sort_concepts(concepts_dict, priority_list)

    all_periods = set()
    rows = {}

    for concept_name, data in sorted_concepts:
        label = data["label"]
        unit = data["unit"]

        # Append unit hint for non-USD items
        if unit and unit not in ("USD",):
            display_label = f"{label} [{unit}]"
        else:
            display_label = label

        # Handle duplicate labels by appending concept name
        if display_label in rows:
            display_label = f"{display_label} ({concept_name})"

        rows[display_label] = data["values"]
        all_periods.update(data["values"].keys())

    if not rows:
        return pd.DataFrame()

    sorted_periods = sorted(all_periods)
    df = pd.DataFrame(rows).T
    df = df.reindex(columns=sorted_periods)
    df.index.name = "Line Item"
    return df


# -------------------------------------------------------------------------
# Public API
# -------------------------------------------------------------------------

def get_income_statement(facts, quarterly=False, max_periods=20):
    """Extract ALL income statement line items as a DataFrame."""
    discovered = discover_all_concepts(facts, quarterly, max_periods)
    return _build_universal_df(discovered["IS"], IS_PRIORITY)


def get_balance_sheet(facts, quarterly=False, max_periods=20):
    """Extract ALL balance sheet line items as a DataFrame."""
    discovered = discover_all_concepts(facts, quarterly, max_periods)
    return _build_universal_df(discovered["BS"], BS_PRIORITY)


def get_cash_flow_statement(facts, quarterly=False, max_periods=20):
    """Extract ALL cash flow statement line items as a DataFrame."""
    discovered = discover_all_concepts(facts, quarterly, max_periods)
    return _build_universal_df(discovered["CF"], CF_PRIORITY)


def get_all_statements(facts, quarterly=False, max_periods=20):
    """Return all three financial statements as a dict of DataFrames.

    Discovers every us-gaap concept in the XBRL data and classifies
    each one into Income Statement, Balance Sheet, or Cash Flow.
    """
    discovered = discover_all_concepts(facts, quarterly, max_periods)
    return {
        "Income Statement": _build_universal_df(discovered["IS"], IS_PRIORITY),
        "Balance Sheet": _build_universal_df(discovered["BS"], BS_PRIORITY),
        "Cash Flow Statement": _build_universal_df(discovered["CF"], CF_PRIORITY),
    }
