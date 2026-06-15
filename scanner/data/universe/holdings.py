from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, timezone
from dateutil import parser
import io
from pathlib import Path
from typing import Final
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd

DEFAULT_OUTPUT_DIR: Final[Path] = Path(__file__).resolve().parent 
DEFAULT_CLEAN_FILENAME: Final[str] = "sp500_current.csv"
EXPECTED_MIN_SYMBOLS: Final[int] = 450
EXPECTED_MAX_SYMBOLS: Final[int] = 550
REQUIRED_HEADER_COLUMNS: Final[set[str]] = {
    "Name",
    "Ticker",
    "Weight",
}


def locate_holdings_download_url() -> str:
    """The goal with this function is to automate the way of finding and returning the string url for the download where we can obtain the csv, for now it is manual"""

    return "https://www.ssga.com/us/en/intermediary/library-content/products/fund-data/etfs/us/holdings-daily-us-en-spy.xlsx"


def fetch_file_bytes(url: str, timeout_seconds: int = 30) -> bytes:
    """This function takes in the url as a parameter, packages up a request, then attempts to open the request. If successful returns the body of the response sent by the server."""

    # package up the webrequest
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/csv,*/*;q=0.9",
        },
    )

    try:
        # attempt to make the request
        with urlopen(request, timeout=timeout_seconds) as response:
            return response.read()
    except HTTPError as exc:
        raise RuntimeError(
            f"iShares returned HTTP {exc.code} while fetching holdings."
        # exception chaining: remember both the original low-level problems with the new higher-level problem (RuntimeError)
        ) from exc
    except URLError as exc:
        raise RuntimeError(
            "Unable to reach page for the holdings file. "
            "If you already downloaded the file, rerun with --input <path>."
        ) from exc


def find_header_row(rows: list[list[str]]) -> int:
    """this function loops through the entire list of lists to look for the row that contains the headers"""

    for row_index, row in enumerate(rows):
        # convert the row to a set and compare if it matches what is intended
        normalized_cells = {cell.strip() for cell in row if cell.strip()}
        if REQUIRED_HEADER_COLUMNS.issubset(normalized_cells):
            return row_index
    # if we make it through the entire function without finding a matching row
    raise ValueError("Could not locate the holdings table header in the file.")


def extract_holdings_as_of(rows: list[list[str]], header_row: int) -> date | None:
    """This function looks through all the rows before the header rows and looks column by column for the string: 'Holdings:'. That may need to change according to the actual information in the data."""

    # loop through the rows that come before the header row
    for row in rows[:header_row]:
        for column_index, cell in enumerate(row):
            if cell.strip() != "Holdings:":
                continue

            # if we have reached the end of the row
            if column_index + 1 >= len(row):
                continue

            # take the cell next to the "Fund Hold..." cell
            raw_value = str(row[column_index + 1]).strip()
            # incase that is empty
            if not raw_value:
                continue

            try:
                parsed = parser.parse(raw_value.replace("_", " "), fuzzy=True)
            except (parser.ParserError, ValueError, TypeError, OverflowError):
                continue
        
            return parsed.date()

    return None


def parse_holdings_file(raw_file: bytes) -> tuple[pd.DataFrame, date | None]:
    """Take the raw bytes and convert them into a nice data frame, return the data frame and the holdings as of date object. Since we may at times have xlxs files we need to consider both xlxs and csv."""

    # decode the bytes into one full string
    if raw_file.startswith(b"PK\x03\x04"):
        raw_excel = pd.read_excel(
            io.BytesIO(raw_file),
            engine="openpyxl",
            header=None,
            dtype="string",
        )

        rows = raw_excel.fillna("").astype(str).values.tolist()

        header_row = find_header_row(rows)

        holdings_as_of = extract_holdings_as_of(rows, header_row)

        holdings = pd.read_excel(
            io.BytesIO(raw_file),
            engine="openpyxl",
            header=header_row,
            dtype="string"
        )

    else:
        text = raw_file.decode("utf-8-sig")

        rows = list(csv.reader(io.StringIO(text)))

        header_row = find_header_row(rows)

        holdings_as_of = extract_holdings_as_of(rows, header_row)
    
        holdings = pd.read_csv(
            io.StringIO(text),
            skiprows=header_row,
            dtype="string"
        )
     
    holdings.columns = [str(column).strip() for column in holdings.columns]
    holdings = holdings.dropna(how="all").reset_index(drop=True)
    
    return holdings, holdings_as_of


def normalize_symbol(symbol: str) -> str:
    """
    clean up symbols, (BRK.B -> BRK-B)
    """

    cleaned = symbol.strip().upper()
    return cleaned.replace(".", "-")


def optional_column(frame: pd.DataFrame, column_name: str) -> pd.Series:
    """
    Take the data from and look for a particular column, if not return a Series of the same length as the rows in the data set
    """

    if column_name in frame.columns:
        return frame[column_name]
    return pd.Series([pd.NA] * len(frame), index=frame.index)


def build_clean_universe(
        holdings: pd.DataFrame,
        *,
        holdings_as_of: date | None,
        downloaded_at_utc: str,
        min_symbols: int = EXPECTED_MIN_SYMBOLS,
        max_symbols: int = EXPECTED_MAX_SYMBOLS,
    ) -> pd.DataFrame:
    """takes in the holdings, holding date, date of this pull. cleans and returns a data frame of the cleaned holdings"""

    # check to see if you are missing any required columns
    missing_columns = REQUIRED_HEADER_COLUMNS.difference(holdings.columns)
    if missing_columns:
        # set of missing value to string
        missing_list = ", ".join(sorted(missing_columns))
        raise ValueError(f"IVV holdings CSV is missing required columns: {missing_list}")

    # create the clean copy and remove unnecessary columns
    cleaned = holdings.copy()
    cleaned = holdings.drop(columns=["Identifier", "SEDOL", "Sector", "Shares Held", "Local Currency"])

    cleaned["Ticker"] = cleaned["Ticker"].astype("string").str.strip()

    # keep only rows where ticker column isnt empty
    cleaned = cleaned[cleaned["Ticker"].notna() & (cleaned["Ticker"] != "")]

    # drop duplicates
    cleaned = cleaned.drop_duplicates(subset="Ticker", keep="first")

    # build the data frame
    output = pd.DataFrame(
        {
            "holdings_as_of": holdings_as_of.isoformat() if holdings_as_of else pd.NA,
            "downloaded_at_utc": downloaded_at_utc,
            "source": "ishares_ivv",
            "source_ticker": cleaned["Ticker"],
            "name": cleaned["Name"],
            "weight": cleaned["Weight"]
        }
    )

    print(output[:10])

    # final check to ensure we didnt collect more or less than what was intended
    symbol_count = len(output)
    if symbol_count < min_symbols or symbol_count > max_symbols:
        raise RuntimeError(
            "Unexpected universe size after normalization: "
            f"{symbol_count} symbols. Expected between {min_symbols} and {max_symbols}."
        )

    return output


def write_outputs(
    *,
    raw_file: bytes,
    clean_universe: pd.DataFrame,
    output_dir: Path,
    holdings_as_of: date | None,
) -> tuple[Path, Path]:
    """
    create both paths and write to them. return the paths
    """

    # create the directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # date label for the raw file name
    snapshot_date = holdings_as_of.isoformat() if holdings_as_of else date.today().isoformat()
    # create the path files
    raw_path = output_dir / f"ivv_holdings_{snapshot_date}.csv"
    clean_path = output_dir / DEFAULT_CLEAN_FILENAME

    # create the files
    raw_path.write_bytes(raw_file)
    clean_universe.to_csv(clean_path, index=False)

    return raw_path, clean_path


def build_argument_parser() -> argparse.ArgumentParser:
    """
    This function is for setting up how the script can accept inputs from the command line incase we use a csv as input rather than downloading from web.
    """

    # Object for parsing command line strings into python objects
    parser = argparse.ArgumentParser(
        description=(
            "Download the official holdings CSV and build a "
            "clean current S&P 500 universe file."
        )
    )
    # adding parameters for arguments when running from the command line
    parser.add_argument(
        "--input",
        type=Path,
        help="Optional local holdings CSV to parse instead of downloading.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory for the raw snapshot and cleaned universe file. Default: {DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument(
        "--url",
        default=None,
        help="Override the holdings CSV URL.",
    )

    return parser


def main() -> int:
    # define the possible command line arguments
    parser = build_argument_parser()
    # store the arguments
    args = parser.parse_args()

    # if there is input, read it, if not default path
    if args.input:
        # read_
        raw_file = args.input.read_bytes()
    else:
        download_url = args.url or locate_holdings_download_url()
        # get the raw bytes from website
        raw_file = fetch_file_bytes(download_url)

    # a time stamp for when it was downloaded
    downloaded_at_utc = (
        datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )

    # clean up the raw_csv into a nice df and extract the date when it was last uploaded
    holdings, holdings_as_of = parse_holdings_file(raw_file)

    clean_universe = build_clean_universe(
        holdings,
        holdings_as_of=holdings_as_of,
        downloaded_at_utc=downloaded_at_utc,
    )
    raw_path, clean_path = write_outputs(
        raw_file=raw_file,
        clean_universe=clean_universe,
        output_dir=args.output_dir,
        holdings_as_of=holdings_as_of,
    )

    # date/date-time object to string
    holdings_date_label = holdings_as_of.isoformat() if holdings_as_of else "unknown"
    
    print(f"Holdings as of: {holdings_date_label}")
    print(f"Clean equity universe size: {len(clean_universe)} symbols")
    print(f"Raw snapshot written to: {raw_path}")
    print(f"Cleaned universe written to: {clean_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())