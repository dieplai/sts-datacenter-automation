import sys
import os
import time
import traceback
import importlib

# Windows: force UTF-8 stdout/stderr so emoji in log() don't raise
# UnicodeEncodeError when output is redirected to a file (default code
# page on Vietnamese Windows is cp1258 which can't represent emoji).
# Must happen before any print() or log() call.
if sys.platform == 'win32':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    # WindowsSelectorEventLoopPolicy avoids ProactorEventLoop incompatibilities
    # with httpx HTTP/2 (h2) used by the async detail fetcher.
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# --- PROXY BYPASS FOR DRIVER DOWNLOAD ---
os.environ['no_proxy'] = '*'
os.environ['NO_PROXY'] = '*'
# ----------------------------------------

def _write_exit_code(code):
    """Write exit code to EXIT_CODE_FILE so the bat supervisor can read it.
    Needed on Windows when stdout is piped through PowerShell Tee-Object —
    CMD only captures the last pipe segment's exit code (PowerShell's), not
    Python's. Python writes the real code to a temp file instead.
    """
    ec_file = os.environ.get('EXIT_CODE_FILE', '')
    if ec_file:
        try:
            with open(ec_file, 'w') as f:
                f.write(str(code))
        except Exception:
            pass


if __name__ == "__main__":
    try:
        from src.main import main
        main()
        _write_exit_code(0)
    except KeyboardInterrupt:
        print("\n[!] Script manually interrupted. Exiting...")
        _write_exit_code(130)
        sys.exit(130)
    except Exception as e:
        import traceback
        print(f"\n[!] Error: {e}")
        traceback.print_exc()
        _write_exit_code(1)
        sys.exit(1)
