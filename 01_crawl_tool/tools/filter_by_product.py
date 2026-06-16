"""
filter_by_product.py
--------------------
Filter output CSV/XLSX files by keywords in the 'Product Description' column.

Usage:
    python tools/filter_by_product.py                        # uses defaults below
    python tools/filter_by_product.py --input output/detail_Vietnam_best_pacific.csv
    python tools/filter_by_product.py --input output/         # processes entire folder
    python tools/filter_by_product.py --keywords spandex polyester nylon
"""

import argparse
import os
import sys
import pandas as pd

# ── Defaults ────────────────────────────────────────────────────────────────
DEFAULT_INPUT   = "output"          # folder or single file
DEFAULT_KEYWORDS = ["spandex", "polyester"]
DEFAULT_OUTPUT  = "output/filtered" # output directory
PRODUCT_COL     = "Product Description"
# ────────────────────────────────────────────────────────────────────────────


def collect_files(path: str) -> list[str]:
    """Return a list of CSV/XLSX files from a file path or directory."""
    if os.path.isfile(path):
        return [path]
    files = []
    for f in os.listdir(path):
        if f.lower().endswith((".csv", ".xlsx")) and not f.startswith("~"):
            files.append(os.path.join(path, f))
    return sorted(files)


def load_file(filepath: str) -> pd.DataFrame:
    if filepath.lower().endswith(".csv"):
        return pd.read_csv(filepath, low_memory=False, dtype=str)
    return pd.read_excel(filepath, dtype=str)


def save_file(df: pd.DataFrame, out_path: str) -> None:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    if out_path.lower().endswith(".csv"):
        df.to_csv(out_path, index=False, encoding="utf-8-sig")
    else:
        df.to_excel(out_path, index=False)


def filter_df(df: pd.DataFrame, keywords: list[str]) -> pd.DataFrame:
    """Keep rows where Product Description contains ANY of the keywords (case-insensitive)."""
    if PRODUCT_COL not in df.columns:
        return pd.DataFrame()           # column missing → skip

    pattern = "|".join(keywords)        # e.g. "spandex|polyester"
    mask = df[PRODUCT_COL].str.contains(pattern, case=False, na=False)
    return df[mask].copy()


def process(input_path: str, keywords: list[str], output_dir: str) -> None:
    files = collect_files(input_path)
    if not files:
        print(f"[WARN] No CSV/XLSX files found in: {input_path}")
        return

    print(f"Keywords  : {keywords}")
    print(f"Files     : {len(files)}")
    print(f"Output dir: {output_dir}\n")

    total_in = total_out = 0
    for fp in files:
        try:
            df = load_file(fp)
        except Exception as e:
            print(f"  [ERROR] Could not read {fp}: {e}")
            continue

        if PRODUCT_COL not in df.columns:
            print(f"  [SKIP ] '{PRODUCT_COL}' column not found in {os.path.basename(fp)}")
            continue

        filtered = filter_df(df, keywords)
        n_in, n_out = len(df), len(filtered)
        total_in += n_in
        total_out += n_out

        if n_out == 0:
            print(f"  [NONE ] {os.path.basename(fp):55s}  {n_in:>7,} rows → 0 matches")
            continue

        # Build output filename: <stem>_filtered.<ext>
        base = os.path.basename(fp)
        stem, ext = os.path.splitext(base)
        out_name = f"{stem}_filtered{ext}"
        out_path = os.path.join(output_dir, out_name)

        save_file(filtered, out_path)
        print(f"  [SAVED] {base:55s}  {n_in:>7,} rows → {n_out:>7,} matches  →  {out_name}")

    print(f"\nDone. {total_out:,} / {total_in:,} total rows matched.")


def main():
    parser = argparse.ArgumentParser(
        description="Filter output files by Product Description keywords."
    )
    parser.add_argument(
        "--input", "-i",
        default=DEFAULT_INPUT,
        help=f"Input file or folder (default: {DEFAULT_INPUT})"
    )
    parser.add_argument(
        "--keywords", "-k",
        nargs="+",
        default=DEFAULT_KEYWORDS,
        help=f"Keywords to match (default: {DEFAULT_KEYWORDS})"
    )
    parser.add_argument(
        "--output", "-o",
        default=DEFAULT_OUTPUT,
        help=f"Output directory (default: {DEFAULT_OUTPUT})"
    )
    args = parser.parse_args()

    # Resolve paths relative to the project root (scrape_new/)
    script_dir   = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)   # tools/ → scrape_new/

    input_path  = args.input  if os.path.isabs(args.input)  else os.path.join(project_root, args.input)
    output_dir  = args.output if os.path.isabs(args.output) else os.path.join(project_root, args.output)

    process(input_path, [kw.lower() for kw in args.keywords], output_dir)


if __name__ == "__main__":
    main()
