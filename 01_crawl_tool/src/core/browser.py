"""Chrome/undetected-chromedriver initialization.

Handles:
- Proxy auth via a Chrome extension (Brightdata-style HTTP proxy with user/pass)
- Chrome major-version auto-detection (avoids driver mismatch across machines)
- Windows WinError 6 suppression on .quit()
- Retry loop with taskkill between attempts

Call `get_driver()` to obtain a ready-to-use Selenium WebDriver. Everything
else in this module is an internal helper.
"""
import os
import subprocess
import time
import zipfile

import undetected_chromedriver as uc

try:
    from .. import config
    from ..observability import log
except ImportError:  # pragma: no cover — run-as-script fallback
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import config  # type: ignore
    from observability import log  # type: ignore


# --- STABILITY PATCH FOR WINDOWS (WinError 6) ---------------------------
_original_uc_quit = uc.Chrome.quit


def _patched_uc_quit(self):
    try:
        _original_uc_quit(self)
    except OSError as e:
        if "[WinError 6]" in str(e):
            return
        raise
    except Exception:
        pass


uc.Chrome.quit = _patched_uc_quit


# --- INTERNAL HELPERS ---------------------------------------------------

def _create_proxy_auth_extension(host, port, user, password):
    """Build a Chrome extension zip that sets a fixed proxy + auth handler."""
    manifest_json = """
    {
        "version": "1.0.0",
        "manifest_version": 2,
        "name": "Chrome Proxy",
        "permissions": ["proxy", "tabs", "unlimitedStorage", "storage",
                        "<all_urls>", "webRequest", "webRequestBlocking"],
        "background": {"scripts": ["background.js"]},
        "minimum_chrome_version": "22.0.0"
    }
    """
    background_js = """
    var config = {
        mode: "fixed_servers",
        rules: {
            singleProxy: {scheme: "http", host: "%s", port: parseInt(%s)},
            bypassList: ["localhost"]
        }
    };
    chrome.proxy.settings.set({value: config, scope: "regular"}, function() {});
    function callbackFn(details) {
        return {authCredentials: {username: "%s", password: "%s"}};
    }
    chrome.webRequest.onAuthRequired.addListener(
        callbackFn, {urls: ["<all_urls>"]}, ['blocking']
    );
    """ % (host, port, user, password)

    plugin_dir = "plugin"
    os.makedirs(plugin_dir, exist_ok=True)
    plugin_file = os.path.join(plugin_dir, "proxy_auth_plugin.zip")
    with zipfile.ZipFile(plugin_file, "w") as zp:
        zp.writestr("manifest.json", manifest_json)
        zp.writestr("background.js", background_js)
    return os.path.abspath(plugin_file)


def _detect_chrome_major_version():
    """Return local Chrome major version (e.g. 146) or None.

    Runs the Chrome binary with --version on the standard install paths
    across macOS/Linux/Windows.
    """
    import re
    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    import shutil
    for cmd in ["google-chrome", "google-chrome-stable", "chromium"]:
        which_path = shutil.which(cmd)
        if which_path and which_path not in candidates:
            candidates.append(which_path)

    for path in candidates:
        if not os.path.exists(path):
            continue
        try:
            pattern = r"C:\\Program Files"
            if bool(re.search(pattern, path)):
                cmd = r'wmic datafile where name="C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" get Version'

                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    shell=True
                )

                output = result.stdout.strip()

                lines = [line.strip() for line in output.splitlines() if line.strip()]
                for line in lines:
                    for line in lines:
                        if line.lower() != "version":
                            version = line.strip()
                            major = int(version.split(".")[0])
                            print(major)
                            return major
            else:
                out = subprocess.run(
                    [path, "--version"], capture_output=True, text=True, timeout=5,
                )
                m = re.search(r"(\d+)\.\d+\.\d+\.\d+",
                            (out.stdout or "") + (out.stderr or ""))
                if m:
                    return int(m.group(1))
        except Exception:
            continue
    return None


def _kill_zombie_chrome():
    """Best-effort taskkill of orphaned Chrome/chromedriver (Windows only)."""
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.run(
            ["taskkill", "/F", "/IM", "chrome.exe", "/T"],
            capture_output=True, creationflags=flags,
        )
        subprocess.run(
            ["taskkill", "/F", "/IM", "chromedriver.exe", "/T"],
            capture_output=True, creationflags=flags,
        )
    except Exception:
        pass


def _final_setup(driver):
    driver.set_page_load_timeout(45)
    return driver


# --- PUBLIC ENTRY -------------------------------------------------------

def get_driver(headless=False):
    """Initialize undetected-chromedriver with proxy + version pinning + retry."""
    os.environ["no_proxy"] = "*"
    os.environ["NO_PROXY"] = "*"

    driver_path = getattr(config, "CHROMEDRIVER_PATH", None)

    # Priority: env CHROME_VERSION_MAIN > auto-detect > let UC decide
    version_main = None
    env_vm = os.environ.get("CHROME_VERSION_MAIN")
    if env_vm and env_vm.isdigit():
        version_main = int(env_vm)
        log(f"Using CHROME_VERSION_MAIN={version_main} from env", "DEBUG")
    else:
        version_main = _detect_chrome_major_version()
        if version_main:
            log(f"Auto-detected Chrome major version: {version_main}", "DEBUG")

    MAX_INIT_RETRIES = 3
    for attempt in range(1, MAX_INIT_RETRIES + 1):
        try:
            options = uc.ChromeOptions()
            options.page_load_strategy = "eager"
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--start-maximized")
            options.add_argument("--disable-popup-blocking")

            options.add_argument("--disable-background-timer-throttling")
            options.add_argument("--disable-backgrounding-occluded-windows")
            options.add_argument("--disable-renderer-backgrounding")
            options.add_argument("--disable-ipc-flooding-protection")
            options.add_argument(
                "--disable-features=CalculateNativeWinOcclusion,"
                "IntensiveWakeUpThrottling"
            )

            options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

            if config.PROXY_HOST:
                proxy_user = config.PROXY_USER
                try:
                    from .proxy_rotator import get_rotator
                    _rot = get_rotator()
                    if _rot.enabled and _rot.session_id:
                        proxy_user = f"{config.PROXY_USER}-session-{_rot.session_id}"
                        log(f"[browser] Chrome proxy username sticky-session={_rot.session_id}",
                            "DEBUG")
                except Exception as e:
                    log(f"[browser] ProxyRotator unavailable, fallback to static proxy: {e}",
                        "WARNING")
                proxy_plugin = _create_proxy_auth_extension(
                    config.PROXY_HOST, config.PROXY_PORT,
                    proxy_user, config.PROXY_PASS,
                )
                options.add_extension(proxy_plugin)

            kwargs = dict(options=options, headless=headless, use_subprocess=True)
            if version_main:
                kwargs["version_main"] = version_main

            if driver_path and os.path.exists(driver_path):
                log(f"Initializing driver with path: {driver_path} "
                    f"(Attempt {attempt}/{MAX_INIT_RETRIES})", "DEBUG")
                driver = uc.Chrome(driver_executable_path=driver_path, **kwargs)
            else:
                log(f"Initializing driver in auto-mode "
                    f"(Attempt {attempt}/{MAX_INIT_RETRIES})", "DEBUG")
                driver = uc.Chrome(**kwargs)
            return _final_setup(driver)

        except Exception as e:
            log(f"⚠️ Chrome initialization failed on attempt {attempt}: {e}",
                "WARNING")
            _kill_zombie_chrome()
            if attempt < MAX_INIT_RETRIES:
                log("🔄 Retrying in 3 seconds...", "INFO")
                time.sleep(3)
            else:
                log(f"❌ FATAL: Chrome failed to initialize after "
                    f"{MAX_INIT_RETRIES} attempts.", "ERROR")
                raise


# Backward-compat alias for any code still calling the pre-refactor name.
create_proxy_auth_extension = _create_proxy_auth_extension


def restart_with_new_proxy(driver, headless=False):
    """acc6: Quit current driver, rotate session-id, spawn new Chrome.

    Dùng từ DEEP recovery khi detect captcha/heavy block — Selenium
    extension không thay được runtime nên chỉ có cách restart Chrome.
    Cost ~15-30s (Chrome restart + re-login).
    """
    try:
        from .proxy_rotator import get_rotator
        rotator = get_rotator()
        rotator.rotate(reason="browser_restart")
    except Exception as e:
        log(f"[browser] rotator unavailable during restart: {e}", "WARNING")

    try:
        driver.quit()
    except Exception:
        pass
    _kill_zombie_chrome()
    time.sleep(2)
    return get_driver(headless=headless)
