from __future__ import annotations

from datetime import date
import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "scanner"
    / "data"
    / "universe"
    / "fetch_ivv_holdings.py"
)
SPEC = importlib.util.spec_from_file_location("fetch_ivv_holdings", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

SAMPLE_IVV_CSV = """Fund Holdings as of,"Apr 16, 2026"
Inception Date,"May 15, 2000"
Shares Outstanding,"1,098,300,000"
Stock,Official Holdings Snapshot

Ticker,Name,Sector,Asset Class,Market Value,Weight (%),Notional Value,Quantity,CUSIP,ISIN,SEDOL,Price,Location,Exchange,Currency,FX Rate,Accrual Date
AAPL,APPLE INC,Information Technology,Equity,21500000000,6.85,21500000000,100000000,037833100,US0378331005,2046251,215.00,United States,NASDAQ,USD,1,
BRK.B,BERKSHIRE HATHAWAY INC CLASS B,Financials,Equity,10000000000,1.23,10000000000,20000000,084670702,US0846707026,2073390,500.00,United States,NYSE,USD,1,
ESM6,S&P 500 FUTURES,Derivatives,Derivative,5000000,0.01,5000000,10,,,,,United States,CME,USD,1,
"""


class FetchIvvHoldingsTests(unittest.TestCase):
    def test_parse_holdings_csv_finds_dynamic_header_and_metadata(self) -> None:
        holdings, holdings_as_of = MODULE.parse_holdings_csv(
            SAMPLE_IVV_CSV.encode("utf-8")
        )

        self.assertEqual(holdings_as_of, date(2026, 4, 16))
        self.assertEqual(list(holdings.columns[:4]), ["Ticker", "Name", "Sector", "Asset Class"])
        self.assertEqual(len(holdings), 3)

    def test_build_clean_universe_keeps_equities_and_normalizes_symbols(self) -> None:
        holdings, holdings_as_of = MODULE.parse_holdings_csv(
            SAMPLE_IVV_CSV.encode("utf-8")
        )

        clean_universe = MODULE.build_clean_universe(
            holdings,
            holdings_as_of=holdings_as_of,
            downloaded_at_utc="2026-04-19T05:00:00Z",
            min_symbols=1,
            max_symbols=10,
        )

        self.assertEqual(clean_universe["symbol"].tolist(), ["AAPL", "BRK-B"])
        self.assertEqual(clean_universe["source_ticker"].tolist(), ["AAPL", "BRK.B"])
        self.assertEqual(clean_universe["cusip"].tolist(), ["037833100", "084670702"])
        self.assertTrue((clean_universe["asset_class"] == "Equity").all())
        self.assertTrue((clean_universe["holdings_as_of"] == "2026-04-16").all())


if __name__ == "__main__":
    unittest.main()
