"""
Hapag-Lloyd carrier adapter, built fresh against the current SPA
(FEASIBILITY.md §09 Step 3) - NOT a port of HL Tracking/scraping.py,
which targeted the legacy tracking form that's since been retired
(FEASIBILITY.md's live-check correction). Both search() and the
taxonomy/state-engine handling below come from a live exploration
session against the real site (2026-07-13), not assumption.

search() uses direct URL navigation - tracking_url + container as a
route param (e.g. .../tracking/#/FCIU4746425) - rather than typing into
the visible search box. Live testing found the search input reliably
obstructed in an automated browser session by a promotional image
carousel and, separately, a stuck OneTrust preference-panel overlay
(neither obstruction is visible in a normal manual session - likely a
CSS stacking quirk specific to the automated window/viewport size).
Deep-linking sidesteps that whole class of problem entirely and is
faster besides; the Cloudflare challenge clears automatically for this
navigation the same as the earlier interactive check found.

The per-container event history is read directly from
.hal-event-tracking .hal-event elements via textContent, which are
already rendered in the DOM regardless of the summary row's expand/
collapse state (the expand button just toggles a CSS display property)
- so search() never needs to click that button at all, avoiding a
second class of UI-interaction fragility.

New wording discovered live, not present in the legacy-form vocabulary
the taxonomy was originally seeded from: "Gated in"/"Gated out" (added
to events/taxonomy.yaml) and "Discharged" reused for a later rail-ramp
unload, not just the original vessel discharge (handled in
shipment_state/engine.py's AMBIGUOUS_INLAND_CATEGORIES).
"""
import json
import time

import pandas as pd

from tracking_control_tower.carriers.base import CarrierAdapter, RawPage, StealthProfile
from tracking_control_tower.shipment_state.models import RawEvent
from tracking_control_tower.utils.chrome_version import detect_installed_chrome_major_version

TRACKING_URL = "https://www.hapag-lloyd.com/solutions/tracking/#/"
COOKIE_BUTTON_ID = "onetrust-accept-btn-handler"
RESULTS_TABLE_SELECTOR = "table.q-table"
EVENT_ROW_SELECTOR = ".hal-event-tracking .hal-event"
EVENT_COL_SELECTOR = ".hal-event__col"


class HLAdapter(CarrierAdapter):
    vessel_prefixes = ["HL"]
    carrier_name = "Hapag-Lloyd"
    tracking_url = TRACKING_URL

    def __init__(self, headless: bool = False):
        self.stealth_profile = StealthProfile(headless=headless)
        self._driver = None

    # --- search(): live browser session ---

    def _ensure_driver(self):
        if self._driver is not None:
            return
        import undetected_chromedriver as uc
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        options = uc.ChromeOptions()
        options.add_argument("--start-maximized")
        if self.stealth_profile.headless:
            options.add_argument("--headless=new")
        # version_main pinned to the actually-installed Chrome build -
        # see utils/chrome_version.py for why leaving this on uc's
        # default (0/auto) intermittently downloads a chromedriver that
        # doesn't match the local browser and makes every launch fail.
        version_main = detect_installed_chrome_major_version()
        driver = uc.Chrome(options=options, version_main=version_main)
        # Assigned immediately, not at the end of setup - a crash during
        # driver.get() below (a launch/resource failure) would otherwise
        # leave self._driver as None with the Chrome window still open,
        # so close()/__exit__ never calls quit() on it - a leaked
        # process every time setup fails partway through.
        self._driver = driver

        # Clear the OneTrust consent banner once, on the bare landing
        # page, the same way MSCAdapter does at session setup - not
        # per-container. Doing this before any container-specific
        # tracking request (rather than after the first one) keeps the
        # scraping requests themselves indistinguishable from a normal
        # user who has already dismissed the banner. Waits adaptively
        # for the button to exist rather than a fixed sleep + one-shot
        # find - a fixed sleep that's occasionally too short would
        # silently skip the click with no retry, leaving the banner up
        # for the rest of the session. Still uses a JS-triggered click
        # (not a plain Selenium .click()): live testing found the
        # search input obstructed by a promotional carousel in
        # automated sessions (see module docstring), and a native click
        # would throw "element click intercepted" in the same way if
        # anything overlaps the button's click point - JS dispatch
        # bypasses that regardless of what's stacked on top.
        driver.get(TRACKING_URL)
        wait = WebDriverWait(driver, 20)
        try:
            button = wait.until(EC.presence_of_element_located((By.ID, COOKIE_BUTTON_ID)))
            driver.execute_script("arguments[0].click();", button)
        except Exception:
            pass  # no consent prompt, or already accepted
        time.sleep(2)

    def search(self, container: str) -> RawPage:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        try:
            # _ensure_driver() used to be called before this try block -
            # a launch failure there would crash the entire batch
            # (including any other carrier's already-completed work,
            # since the Excel report only gets written at the very end)
            # instead of landing as a normal per-container error.
            self._ensure_driver()

            # Capture the outgoing rows before reloading to a new
            # container's URL. MaerskAdapter's original deep-link design
            # (same pattern: driver.get() per container, fixed sleep,
            # read) turned out to have no way of confirming a freshly
            # loaded page's content actually belonged to the container
            # just requested - a real batch run caught three different
            # containers all reporting one stale/mismatched result with
            # no error raised. Waiting for the previous page's rows to
            # go stale before trusting a fresh read closes the same gap
            # here, without needing HL's fuller no-reload rewrite (its
            # search box is obstructed by a carousel in automated
            # sessions - see module docstring - so typing into it isn't
            # a viable alternative the way it was for Maersk).
            old_rows = self._driver.find_elements(By.CSS_SELECTOR, EVENT_ROW_SELECTOR)
            stale_marker = old_rows[0] if old_rows else None

            self._driver.get(f"{TRACKING_URL}{container}")
            time.sleep(6)  # Cloudflare challenge + SPA render

            wait = WebDriverWait(self._driver, 15)
            if stale_marker is not None:
                try:
                    wait.until(EC.staleness_of(stale_marker))
                except Exception:
                    pass  # didn't go stale in time - fall through and read anyway
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, RESULTS_TABLE_SELECTOR)))

            rows = self._driver.find_elements(By.CSS_SELECTOR, EVENT_ROW_SELECTOR)
            structured = []
            for row in rows:
                cols = row.find_elements(By.CSS_SELECTOR, EVENT_COL_SELECTOR)
                values = [
                    self._driver.execute_script("return arguments[0].textContent.trim();", c)
                    for c in cols
                ]
                if len(values) >= 6:
                    structured.append({
                        "event": values[0], "location": values[1], "date": values[2],
                        "time": values[3], "transport": values[4], "voyage": values[5],
                    })

            return RawPage(container=container, text=json.dumps(structured))
        except Exception as e:
            self._recover_if_session_dead()
            return RawPage(container=container, error=str(e))

    def _recover_if_session_dead(self) -> None:
        """See MaerskAdapter._recover_if_session_dead() - same fix,
        same root cause (a hung page can take the whole WebDriver
        session down with it, cascading one transient failure into
        every remaining container in the batch via "invalid session
        id"). Both carriers drive a real uc.Chrome() session the same
        way, so both need this."""
        if self._driver is None:
            return
        try:
            _ = self._driver.title
            return  # still alive - the failure was something else, leave the session as-is
        except Exception:
            pass
        try:
            self._driver.quit()
        except Exception:
            pass
        self._driver = None
        try:
            self._ensure_driver()
        except Exception:
            pass  # next search()'s own _ensure_driver() call will surface this properly

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
        if raw.error or not raw.text:
            return []

        try:
            structured = json.loads(raw.text)
        except json.JSONDecodeError:
            return []

        events: list[RawEvent] = []
        for row in structured:
            transport = (row.get("transport") or "").strip()
            voyage = (row.get("voyage") or "").strip()
            vessel_info = f"{transport} {voyage}".strip() if voyage else transport or None

            events.append(RawEvent(
                container=raw.container,
                date=self._parse_datetime(row.get("date", ""), row.get("time", "")),
                raw_text=row.get("event", ""),
                location=row.get("location") or None,
                vessel_info=vessel_info,
                source="HL",
                scraped_at=raw.scraped_at,
            ))
        return events

    @staticmethod
    def _parse_datetime(date_str: str, time_str: str):
        if not date_str:
            return None
        combined = f"{date_str} {time_str}".strip()
        parsed = pd.to_datetime(combined, errors="coerce")
        return None if pd.isna(parsed) else parsed.to_pydatetime()
