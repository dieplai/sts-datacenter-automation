"""Application config — split by concern.

Public defaults (committed) live in submodules; user-specific values (creds,
proxy, scrape-filter tweaks) live in `_local.py`, which is gitignored and
imported LAST so its definitions override the defaults.

The flat re-export at the bottom keeps old call sites working:

    from src import config
    config.USERNAME          # from _local (or env fallback)
    config.PROXY_HOST        # from _local
    config.DETAIL_START_DATE # from scrape_filters.py (override in _local)

Layout:
  auth.py            USERNAME, PASSWORD, TARGET_URL, PRO_LOGIN_URL
  proxy.py           PROXY_HOST/PORT/USER/PASS + FAST_API_USE_PROXY
  settings.py        paths, CHROMEDRIVER_PATH, TEST_MODE, FAST_API_* knobs
  scrape_filters.py  DETAIL_* filters, TRANSACTIONS_BATCH, TEST_SEARCH_CONFIG
  _local.py          your overrides (gitignored)
  _local.example.py  template to copy into _local.py
"""
from .auth import *        # noqa: F401, F403
from .proxy import *       # noqa: F401, F403
from .settings import *    # noqa: F401, F403
from .scrape_filters import *  # noqa: F401, F403

# Optional user overrides — imported last so any name defined in _local.py
# wins over the committed defaults.
try:
    from ._local import *  # noqa: F401, F403
except ImportError:
    # No local file yet. The scraper will fail at login with placeholder
    # credentials — see docs/SETUP.md for how to create _local.py.
    pass
