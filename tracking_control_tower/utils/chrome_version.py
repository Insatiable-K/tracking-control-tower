"""
undetected_chromedriver's own version auto-detection (version_main=0,
the default) does not inspect the locally installed Chrome binary at
all - Patcher.fetch_release_number() just fetches the latest STABLE
channel chromedriver from Google's servers. Whenever that's ahead of
whatever Chrome build is actually installed on this machine (a routine
silent auto-update lag in either direction), every uc.Chrome() launch
fails with SessionNotCreatedException ("this version of ChromeDriver
only supports Chrome version X, current browser version is Y") and the
browser window opens and immediately closes. Confirmed by reading
patcher.py directly, not guessed.

detect_installed_chrome_major_version() reads the installed chrome.exe
file's own version metadata (no execution - a running Chrome instance
would otherwise just forward `--version` to it as a new-tab command and
never print anything) so callers can pass version_main= explicitly and
pin the chromedriver download to match the browser that is actually
on this machine, however it drifts over time.
"""
import subprocess

import undetected_chromedriver as uc


def detect_installed_chrome_major_version() -> int | None:
    chrome_path = uc.find_chrome_executable()
    if not chrome_path:
        return None
    try:
        output = subprocess.check_output(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f'(Get-Item "{chrome_path}").VersionInfo.ProductVersion',
            ],
            text=True,
            timeout=10,
        ).strip()
        return int(output.split(".")[0])
    except Exception:
        return None
