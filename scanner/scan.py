import pandas as pd

from pathlib import Path
from typing import Final
from scanner.filters import baseline_filters as baseline
from scanner.filters import trend_filters as trend

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
UNIVERSE_PATH: Final[Path] = (
    PROJECT_ROOT / "scanner" / "data" / "universe" / "sp500_current.csv"
)
DEFAULT_OUTPUT_PATH : Final[Path] = (
    PROJECT_ROOT / "scanner" / "uptrend.csv"
)

def main():
    universe = pd.read_csv(UNIVERSE_PATH)

    results = []

    # for each stock in universe run the baseline filters:
    for symbol in universe["source_ticker"]:
        # get historical candle data
        candles = baseline.get_historical_daily_candles(symbol)

        # calculate the 3 baseline filters
        average_volume = baseline.calc_average_volume(candles)
        relative_volume = baseline.calc_relative_volume(candles, average_volume)
        atr = baseline.calc_average_true_range(candles)

        # calculate the trend filters
        sma_20 = trend.calc_sma(candles, 20)
        sma_50 = trend.calc_sma(candles, 50)
        sma_200 = trend.calc_sma(candles, 200)

        # current price
        current_price = candles["close"].iloc[-1]

        # if meets conditions
        if baseline.passes_baseline_filters(average_volume, relative_volume, atr):
            # add to results

            if trend.passes_trend_filters(current_price, sma_20, sma_50, sma_200):
                results.append(
                    {
                        "symbol": symbol,
                        "last_price": current_price,
                        "average_volume": f"{average_volume:.0f}",
                        "relative_volume": f"{relative_volume:.1f}",
                        "average_true_range": f"{atr:.2f}",
                        "sma_20": f"{sma_20:.2f}",
                        "sma_50": f"{sma_50:.2f}",
                        "sma_200": f"{sma_200:.2f}",
                    }
                )

    result_df = pd.DataFrame(results)

    result_df.to_csv(DEFAULT_OUTPUT_PATH, index=False)

    return 0