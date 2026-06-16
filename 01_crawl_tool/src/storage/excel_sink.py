"""CSV → Excel converter with aggressive control-char sanitization.

openpyxl and xlsxwriter both enforce strict XML 1.0 character validity.
Transaction descriptions often contain odd control characters that slip
through — we scrub them with a conservative regex before writing.
"""
import os
import re

import pandas as pd

try:
    from ..observability import log
except ImportError:  # pragma: no cover
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from observability import log  # type: ignore


_INVALID_XML_RE = re.compile(
    r"[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f-\x84\x86-\x9f"
    r"\ud800-\udfff﷐-﷟￾￿]"
)
_INVALID_CTRL_RE = re.compile(r"[\000-\010]|[\013-\014]|[\016-\037]")


def _sanitize(value):
    if pd.isna(value) or not isinstance(value, str):
        return value
    value = _INVALID_XML_RE.sub("", value)
    value = _INVALID_CTRL_RE.sub("", value)
    return value


def convert_to_excel(csv_file, excel_file=None):
    """Convert `csv_file` to an Excel file next to it. Default output path
    is the same filename with .xlsx suffix.
    """
    if excel_file is None:
        excel_file = csv_file.replace(".csv", ".xlsx")

    try:
        if not os.path.exists(csv_file):
            return
        log("📊 Converting to Excel...", "INFO")

        df = pd.read_csv(
            csv_file, encoding="utf-8-sig", on_bad_lines="skip", low_memory=False,
        )

        try:
            df = df.applymap(_sanitize) if hasattr(df, "applymap") else df.map(_sanitize)
        except Exception:
            for col in df.columns:
                if df[col].dtype == "object" or str(df[col].dtype) == "string":
                    df[col] = df[col].apply(_sanitize)

        df.columns = [_sanitize(c) for c in df.columns]

        try:
            import xlsxwriter  # noqa: F401
            engine = "xlsxwriter"
        except ImportError:
            engine = "openpyxl"

        df.to_excel(excel_file, index=False, engine=engine)
        log(f"✅ Excel: {os.path.basename(excel_file)} ({len(df):,} rows)", "SUCCESS")
    except Exception as e:
        log(f"❌ Excel conversion failed: {e}", "ERROR")
