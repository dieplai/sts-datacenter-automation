"""Pure helpers over transaction dicts — no side effects, no I/O."""

try:
    from ..observability import log
except ImportError:  # pragma: no cover
    import os, sys
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from observability import log  # type: ignore


_DATE_FIELDS = ("date", "Transaction Date", "transaction_date", "bill_date")
_ID_FIELDS = ("bill_no", "export_declaration_number", "bill_id", "date")


def extract_transaction_date(transaction):
    """Return the trade date as a YYYY-MM-DD-ish string, or None.

    Tries several field names (API key + display name) because transactions
    may come back from different pipelines (live click, historical CSV).
    """
    if not transaction:
        return None
    for field in _DATE_FIELDS:
        value = transaction.get(field)
        if not value:
            continue
        s = str(value).strip()
        if not s or s.lower() in ("nan", "none", "nat"):
            continue
        if len(s) >= 10:
            return s
    log(f"⚠️ Could not extract date from transaction: "
        f"{list(transaction.keys())[:10]}", "WARNING")
    return None


def get_transaction_id(transaction):
    """Composite identifier (bill_no|export_declaration_number|bill_id|date).

    Returns a pipe-joined string or None. Used for dedupe + logging.
    """
    if not transaction:
        return None
    parts = [str(transaction[f]) for f in _ID_FIELDS if transaction.get(f)]
    return "|".join(parts) if parts else None
