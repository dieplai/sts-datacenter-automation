import os
import sys

# Load config
try:
    from . import config
except ImportError:
    import src.config as config

from .utils import log

def main():
    """
    Main entry point for Vietnam Customs Data Scraper (Pro Detail Mode Only)
    """
    log("\n" + "="*60, "INFO")
    log("VIETNAM CUSTOMS DATA SCRAPER - PRO 2026 DETAIL MODE ONLY", "INFO")
    log("="*60, "INFO")
    
    # Route directly to the detail mode. Re-raise so run.py can
    # sys.exit(1) — otherwise supervisor sees exit 0 and treats a
    # crashed login as a clean completion.
    try:
        from .scraper import core_pro_detail
        core_pro_detail.main()
    except Exception as e:
        log(f"❌ Core Detail Mode execution failed: {e}", "ERROR")
        import traceback
        traceback.print_exc()
        raise

if __name__ == "__main__":
    main()
