"""
MSC carrier adapter - the reference implementation the other adapters
follow (FEASIBILITY.md §09 Step 1). search() ports MSC_INC.py's proven
Selenium flow behavior-identically: same URL, same driver setup (plain
selenium.webdriver.Chrome + manual CDP/selenium-stealth patches - note
MSC_INC.py imports undetected_chromedriver but never actually calls
uc.Chrome(), so this preserves that exact combination rather than
"improving" it, since FEASIBILITY.md validated THIS specific setup as
already proven in production, not a hypothetical better one), same
cookie handling, same XPaths, same 6-second wait.

parse()'s 5-line block grouping is NOT behavior-identical - a live
search() run against a real container (MEDU5655981) traced the exact
root cause of FEASIBILITY.md's ~8.5% historical parsing-artifact
finding: the raw section text includes a literal column-header row
("Date\\nLocation\\nDescription\\n...") and a "Show all*" UI toggle
string injected between rows, neither of which are event data.
MSC_INC.py's bad_descriptions filter only cleaned up the header row
after the fact; it never accounted for "Show all*", which shifts every
block's alignment by one line for the rest of the page, corrupting
every subsequent event's fields. Filtering both known non-data strings
out before grouping fixes it at the source rather than downstream. This
is a raw-scrape parsing defect, not a classification-ambiguity call the
roadmap deferred to the taxonomy layer - there's nothing ambiguous
about "Show all*" not being tracking data.

parse() is a pure function and is fully unit-tested without a browser.
search() needs a live Selenium session and is exercised separately -
see tests/run_msc_live_check.py and tests/test_msc_adapter.py for which
is which.
"""
import re
import time
from datetime import datetime

import pandas as pd

from tracking_control_tower.carriers.base import CarrierAdapter, RawPage, StealthProfile
from tracking_control_tower.shipment_state.models import RawEvent

TRACKING_URL = "https://www.msc.com/en/track-a-shipment"

COOKIE_BUTTON_XPATH = '//*[@id="onetrust-accept-btn-handler"]'
TRACKING_INPUT_SELECTOR = "#trackingNumber"
TRACKING_SECTION_XPATH = (
    "/html/body/div[1]/div[1]/div/div[3]/div/div/div/div[1]/div/div/div[3]/div/div/div[2]"
)
POD_ETA_XPATH = (
    "/html/body/div[1]/div[1]/div/div[3]/div/div/div/div[1]/div/div/div[3]"
    "/div/div/div[1]/div/div[4]/div/div/div/span[2]"
)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)

# Real strings confirmed via a live search() run against MEDU5655981 -
# the column-header row and a "Show all*" pagination toggle, both
# embedded in the section's own text, neither of them event data.
_NON_DATA_LINES = {
    "Date",
    "Location",
    "Description",
    "Empty/Laden/Vessel/Voyage",
    "Equipment handling facility name",
    "Show all*",
}

# A real live scrape of CRSU1397223 caught a second, more serious block-
# alignment bug on top of the "Show all*"/header-line one above: "Carrier
# release" (and likely other event types) has no "Equipment handling
# facility name" line rendered in the DOM at all for that row, not a
# blank one - it's genuinely absent, not empty. Treating every block as a
# rigid 5 lines then consumed the NEXT event's date as this event's
# facility, corrupting every subsequent event's fields for the rest of
# that container's history (the same failure MODE as the historical
# "Show all*" bug - one skipped/extra line poisoning everything after it
# - just a different cause: a missing optional field instead of an
# injected one). Detecting a facility candidate that's actually a date
# (the next block already starting) is what makes the block boundary
# correct regardless of whether a given event has 4 or 5 real fields.
_DATE_LINE = re.compile(r"^\d{1,2}[/-]\d{1,2}[/-]\d{4}$")


def _pad_date_str(date_str: str) -> str:
    """Port of MSC_INC.py's pad_date_str - MSC's raw dates are dash-separated
    D-M-Y with inconsistent zero-padding (e.g. "5-6-2025")."""
    if not date_str:
        return date_str
    parts = date_str.split("-")
    if len(parts) != 3:
        return date_str
    day, month, year = parts
    return f"{day.zfill(2)}-{month.zfill(2)}-{year}"


class MSCAdapter(CarrierAdapter):
    vessel_prefixes = ["MSC"]
    carrier_name = "MSC"
    tracking_url = TRACKING_URL

    def __init__(self, headless: bool = False):
        self.stealth_profile = StealthProfile(headless=headless)
        self._driver = None
        self._wait = None

    # --- search(): live browser session, ported from MSC_INC.py ---

    def _ensure_driver(self):
        if self._driver is not None:
            return
        import chromedriver_autoinstaller
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium_stealth import stealth

        chromedriver_autoinstaller.install()

        options = Options()
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--log-level=3")
        if self.stealth_profile.headless:
            options.add_argument("--headless=new")
        options.add_argument(f"user-agent={_USER_AGENT}")
        options.set_capability("pageLoadStrategy", "eager")

        driver = webdriver.Chrome(options=options)
        # Assigned immediately, not at the end of setup - a crash during
        # driver.get() below (a launch/resource failure) would otherwise
        # leave self._driver as None with the Chrome window still open,
        # so close()/__exit__ never calls quit() on it - a leaked
        # process every time setup fails partway through.
        self._driver = driver
        self._By = By
        self._EC = EC
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": """
                    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                    window.chrome = { runtime: {} };
                    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
                """
            },
        )
        stealth(
            driver, languages=["en-US", "en"], vendor="Google Inc.", platform="Win32",
            webgl_vendor="Intel Inc.", renderer="Intel Iris OpenGL Engine", fix_hairline=True,
        )

        wait = WebDriverWait(driver, 20)
        self._wait = wait
        driver.get(TRACKING_URL)
        try:
            wait.until(EC.element_to_be_clickable((By.XPATH, COOKIE_BUTTON_XPATH))).click()
        except Exception:
            pass  # no cookie prompt, or already accepted

    def search(self, container: str) -> RawPage:
        try:
            # _ensure_driver() used to be called before this try block -
            # a launch failure there would crash the entire batch
            # (including any other carrier's already-completed work,
            # since the Excel report only gets written at the very end)
            # instead of landing as a normal per-container error.
            self._ensure_driver()
            By, EC = self._By, self._EC

            input_box = self._wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, TRACKING_INPUT_SELECTOR)))
            input_box.clear()
            from selenium.webdriver.common.keys import Keys
            input_box.send_keys(container)
            input_box.send_keys(Keys.RETURN)
            time.sleep(6)

            section = self._wait.until(EC.presence_of_element_located((By.XPATH, TRACKING_SECTION_XPATH)))
            raw_text = section.text.strip()

            try:
                pod_eta_text = self._wait.until(
                    EC.presence_of_element_located((By.XPATH, POD_ETA_XPATH))
                ).text.strip()
            except Exception:
                pod_eta_text = None

            return RawPage(container=container, text=raw_text, pod_eta_text=pod_eta_text)
        except Exception as e:
            return RawPage(container=container, error=str(e))

    def close(self) -> None:
        if self._driver is not None:
            try:
                self._driver.quit()
            except Exception:
                # quit() itself throws when the session/window is
                # already broken - best-effort cleanup: always clear
                # the reference even if telling a dead session to quit
                # doesn't succeed (see MaerskAdapter.close() for detail).
                pass
            self._driver = None

    # --- parse(): pure function, no browser needed ---

    def parse(self, raw: RawPage) -> list[RawEvent]:
        if raw.error:
            return []

        events: list[RawEvent] = []
        lines = [line.strip() for line in raw.text.split("\n") if line.strip()]
        lines = [line for line in lines if line not in _NON_DATA_LINES]

        i = 0
        while i + 4 <= len(lines):
            date_str, location, description, vessel_info = lines[i:i + 4]
            i += 4
            # The facility line is optional per-event, not always
            # present - if what follows is itself a date, that's the
            # NEXT event starting, not this event's facility name.
            facility = None
            if i < len(lines) and not _DATE_LINE.match(lines[i]):
                facility = lines[i]
                i += 1

            events.append(RawEvent(
                container=raw.container,
                date=self._parse_date(date_str),
                raw_text=description,
                location=location,
                vessel_info=vessel_info,
                facility=facility,
                source="MSC",
                scraped_at=raw.scraped_at,
            ))

        if raw.pod_eta_text:
            pod_eta_date = self._parse_date(raw.pod_eta_text)
            if pod_eta_date is not None:
                # Mirrors MSC_INC.py's separate POD ETA field: not part
                # of the block-based history, so it's not a real event -
                # but it's the container's current best full-route ETA,
                # and the classifier already recognizes "Estimated Time
                # of Arrival" as the estimated_arrival projection
                # category regardless of where the date came from.
                events.append(RawEvent(
                    container=raw.container,
                    date=pod_eta_date,
                    raw_text="Estimated Time of Arrival",
                    source="MSC",
                    scraped_at=raw.scraped_at,
                ))

        return events

    @staticmethod
    def _parse_date(date_str: str) -> datetime | None:
        padded = _pad_date_str(date_str.strip())
        parsed = pd.to_datetime(padded, dayfirst=True, errors="coerce")
        return None if pd.isna(parsed) else parsed.to_pydatetime()
