"""
Maersk carrier adapter, built from a live exploration session against
the real site (2026-07-13) - FEASIBILITY.md's live check confirmed
Maersk clears Akamai cleanly for a real browser, but never explored the
actual page structure needed to build a scriptable adapter; this does.

search() types each container into the page's own search box and
clicks Track, reusing one open session for the whole batch - it does
NOT call driver.get() per container. This replaced an earlier
deep-link-per-container design (navigate straight to tracking/
{container}) after a sustained-volume trial found that repeated design
came back with every Maersk container in a round structurally present
but empty, in a way MSC (which has always typed into a persistent
search box rather than reloading) never showed under the same load.
Confirmed live: two different containers searched back-to-back in one
session, zero reloads, both returned correct real data.

The search box (mc-input[data-test="track-input"]) and Track button
(mc-button[data-test="track-button"]) are custom web components with a
Shadow DOM - the real <input> is a light-DOM child slotted into the
shadow tree, and Selenium's native send_keys/click can't reach it (it
reports a zero-size bounding box). Setting the value via the native
HTMLInputElement property setter + dispatching input/change events is
the standard workaround for framework-controlled inputs like this one;
the button is triggered with a JS-dispatched click on the custom
element itself rather than searching for an inner native <button>.

The milestone list uses clean, stable data-test attributes
(transport-plan-item, milestone, milestone-date, location-name) - by
far the least fragile of the three carriers' markup. One real quirk:
location is only rendered once per group of consecutive milestones at
the same place (a display convention, not missing data) - parse()
forward-fills it from the last seen value, the same way a human reading
the page would.
"""
import json
import re
import time

import pandas as pd

from tracking_control_tower.carriers.base import CarrierAdapter, RawPage, StealthProfile
from tracking_control_tower.shipment_state.models import RawEvent
from tracking_control_tower.utils.chrome_version import detect_installed_chrome_major_version

TRACKING_URL = "https://www.maersk.com/tracking/"
COOKIE_ACCEPT_SELECTOR = ".coi-banner__accept"
TRACK_INPUT_SELECTOR = 'mc-input[data-test="track-input"]'
TRACK_BUTTON_SELECTOR = 'mc-button[data-test="track-button"]'
TRANSPORT_ITEM_SELECTOR = 'li[data-test^="transport-plan-item"]'
LOCATION_SELECTOR = '[data-test="location-name"]'
MILESTONE_SELECTOR = '[data-test="milestone"]'
MILESTONE_DATE_SELECTOR = '[data-test="milestone-date"]'

# Standard technique for setting a value on a framework-controlled
# input: assigning .value directly is often ignored by the framework's
# own change tracking, but calling the value setter inherited from
# HTMLInputElement.prototype and then dispatching input/change bypasses
# that and matches what a real keystroke would trigger.
_SET_INPUT_VALUE_JS = """
    const input = arguments[0];
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
    setter.call(input, arguments[1]);
    input.dispatchEvent(new Event('input', {bubbles: true}));
    input.dispatchEvent(new Event('change', {bubbles: true}));
"""

_PAREN_VESSEL = re.compile(r"\(([^)]+)\)")
_LOAD_ON_VESSEL = re.compile(r"^load on (.+)$", re.IGNORECASE)


def _extract_vessel_info(event_text: str) -> str | None:
    match = _PAREN_VESSEL.search(event_text)
    if match:
        return match.group(1).strip()
    match = _LOAD_ON_VESSEL.match(event_text.strip())
    if match:
        return match.group(1).strip()
    return None


class MaerskAdapter(CarrierAdapter):
    vessel_prefixes = ["MSK", "MAERSK"]
    carrier_name = "Maersk"
    tracking_url = TRACKING_URL

    def __init__(self, headless: bool = False):
        self.stealth_profile = StealthProfile(headless=headless)
        self._driver = None
        self._last_container = None
        self._last_structured_json = None

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
        # Assigned immediately, not at the end of setup - a real crash
        # during driver.get() below (a launch/resource failure, not a
        # code bug) left self._driver as None with the Chrome window
        # still open, so close()/__exit__ never called quit() on it -
        # a leaked process every time setup failed partway through,
        # which compounds across a long batch run.
        self._driver = driver

        # Clear the consent banner once, on the bare landing page, the
        # same way MSCAdapter does at session setup - not per-container.
        # Doing this before any container-specific tracking request
        # (rather than after the first one) keeps the scraping requests
        # themselves indistinguishable from a normal user who has
        # already dismissed the banner. Uses an adaptive wait, not a
        # fixed sleep + one-shot find - a fixed sleep that's
        # occasionally too short would silently skip the click with no
        # retry, leaving the banner up for the rest of the session.
        #
        # COOKIE_ACCEPT_SELECTOR matches 4 elements on the real page,
        # not 1 - three are hidden, empty-text duplicates (a CMP
        # rendering quirk, confirmed by direct inspection) and only one
        # is the real, visible "Allow all" button. find_element (used
        # internally by element_to_be_clickable when given a locator)
        # only ever returns the first DOM match, which happened to be
        # the real button in every check so far - but that's an
        # ordering assumption, not a guarantee, so this waits for and
        # clicks whichever match is actually visible instead of
        # trusting position.
        driver.get(TRACKING_URL)
        wait = WebDriverWait(driver, 20)
        try:
            button = wait.until(lambda d: next(
                (el for el in d.find_elements(By.CSS_SELECTOR, COOKIE_ACCEPT_SELECTOR)
                 if el.is_displayed() and el.is_enabled()),
                False,
            ))
            # A real live check (repeated back-to-back) caught
            # button.click() - Selenium's native click - simply not
            # registering at all in some sessions: the banner stayed
            # visible for the full 20s wait below with no sign of
            # dismissal, even though the same button, clicked the same
            # way, dismissed the banner in under 5s in other sessions.
            # Calling the button's own bound handler directly
            # (confirmed via its onclick attribute:
            # "CookieInformation.submitAllCategories()") reproduced the
            # dismissal every time in the same failing session, so this
            # bypasses whatever makes the click event itself unreliable
            # here rather than working around it with more waiting.
            driver.execute_script(
                "if (window.CookieInformation) { window.CookieInformation.submitAllCategories(); } "
                "else { arguments[0].click(); }",
                button,
            )
            # Consent processing is itself variable-latency (0-3+
            # seconds observed across repeated checks, not a fixed
            # delay) - waiting for the button to actually stop being
            # displayed is what confirms it was really processed, not
            # just triggered.
            wait.until(lambda d: not button.is_displayed())
        except Exception:
            pass  # no consent prompt, already accepted, or didn't confirm in time - proceed regardless

    def search(self, container: str) -> RawPage:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        try:
            # _ensure_driver() used to be called before this try block -
            # a real run crashed the ENTIRE batch (including whatever
            # MSC/HL work had already succeeded, since the Excel report
            # only gets written at the very end) when the browser failed
            # to launch on the very first container, because that
            # exception had nowhere to land as a normal per-container
            # RawPage(error=...) the way every other failure here does.
            self._ensure_driver()

            # Capture the outgoing list before submitting a new search -
            # a real batch run caught the framework replacing the whole
            # <li> list rather than patching it in place (old and new
            # items briefly coexist, one read returned 18 items for a
            # container that only has 9 real events), and reading during
            # that overlap either mixes old+new rows together or hits a
            # StaleElementReferenceException moments later when the old
            # nodes get torn out from under an in-flight reference.
            # Waiting for the old node to go stale first - when one
            # exists - avoids reading during that window instead of
            # trying to detect the mixed state after the fact.
            old_items = self._driver.find_elements(By.CSS_SELECTOR, TRANSPORT_ITEM_SELECTOR)
            stale_marker = old_items[0] if old_items else None

            self._submit_search(container)

            wait = WebDriverWait(self._driver, 15)
            if stale_marker is not None:
                try:
                    wait.until(EC.staleness_of(stale_marker))
                except Exception:
                    pass  # didn't go stale in time - fall through to the readiness checks below
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, TRANSPORT_ITEM_SELECTOR)))

            def is_ready(rows: list[dict]) -> bool:
                has_data = any(row["event"] and row["date"] for row in rows)
                # Typing a new container and clicking Track doesn't
                # guarantee the milestone list has actually been
                # replaced yet - if it still matches the PREVIOUS
                # (different) container's content byte-for-byte, that's
                # the old render still showing, not a genuine
                # coincidence (two different containers essentially
                # never share an identical event/date/location history).
                is_stale_repeat = (
                    self._last_container is not None
                    and self._last_container != container
                    and json.dumps(rows) == self._last_structured_json
                )
                return has_data and not is_stale_repeat

            # A real batch run caught this: waiting for the <li> elements
            # to EXIST isn't the same as their text being populated yet -
            # an intermittent timing gap (not reproducible on demand,
            # confirmed by re-running the same two containers in
            # isolation and getting clean text both times) produced 8
            # structurally-present items with entirely empty event/date
            # text. Retry a couple of times with a short wait rather than
            # trusting the first read once elements exist.
            structured = self._extract_structured()
            for _ in range(2):
                if is_ready(structured):
                    break
                time.sleep(2)
                structured = self._extract_structured()

            # A sustained-volume trial (multiple full-population passes
            # in one session) caught a second, slower failure mode the
            # fast retry above doesn't cover: a container's search
            # coming back structurally present but empty even after the
            # fast retries. One longer cooldown, followed by a genuine
            # page reload (the one case where a hard navigation is still
            # used - a last-resort recovery if the in-page search flow
            # itself has gotten stuck, not the routine per-container
            # path), is worth trying before giving up on the container.
            if not is_ready(structured):
                time.sleep(30)
                self._driver.get(f"{TRACKING_URL}{container}")
                WebDriverWait(self._driver, 20).until(
                    lambda d: d.execute_script("return document.readyState") == "complete"
                )
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, TRANSPORT_ITEM_SELECTOR)))
                time.sleep(2)
                structured = self._extract_structured()

            self._last_container = container
            self._last_structured_json = json.dumps(structured)
            return RawPage(container=container, text=json.dumps(structured))
        except Exception as e:
            self._recover_if_session_dead()
            return RawPage(container=container, error=str(e))

    def _recover_if_session_dead(self) -> None:
        """A live batch run (2026-07-17) caught a single container's
        page hanging long enough to hit Selenium's 120s command
        timeout, which took the whole WebDriver session down with it -
        every other container queued behind it in the same session
        then failed too, with "invalid session id", cascading one
        transient hang into 30+ consecutive failures. Probing a cheap
        property after any search() failure and rebuilding the driver
        (fresh browser, banner cleared again) when the session is
        actually gone means only the container that hit the hang is
        lost, not the rest of the batch."""
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

    def _submit_search(self, container: str) -> None:
        from selenium.webdriver.common.by import By

        mc_input = self._driver.find_element(By.CSS_SELECTOR, TRACK_INPUT_SELECTOR)
        real_input = mc_input.find_element(By.TAG_NAME, "input")
        self._driver.execute_script(_SET_INPUT_VALUE_JS, real_input, container)
        time.sleep(1)
        mc_button = self._driver.find_element(By.CSS_SELECTOR, TRACK_BUTTON_SELECTOR)
        self._driver.execute_script("arguments[0].click();", mc_button)

    def _extract_structured(self, retries: int = 2) -> list[dict]:
        from selenium.common.exceptions import StaleElementReferenceException
        from selenium.webdriver.common.by import By

        for attempt in range(retries + 1):
            try:
                items = self._driver.find_elements(By.CSS_SELECTOR, TRANSPORT_ITEM_SELECTOR)
                structured = []
                for item in items:
                    loc_els = item.find_elements(By.CSS_SELECTOR, LOCATION_SELECTOR)
                    location = loc_els[0].text.replace("\n", " / ").strip() if loc_els else None

                    milestone_els = item.find_elements(By.CSS_SELECTOR, MILESTONE_SELECTOR)
                    date_els = item.find_elements(By.CSS_SELECTOR, MILESTONE_DATE_SELECTOR)
                    if not milestone_els or not date_els:
                        continue

                    full_text = milestone_els[0].text
                    date_text = date_els[0].text.strip()
                    event_text = full_text.replace(date_text, "").strip()

                    # The milestone list includes placeholder rows for
                    # remaining/future stages of the route - present in
                    # every container checked, not just early-stage ones
                    # (e.g. a fully-tracked container still showed 7 of
                    # these among 11 total items). They're a real,
                    # consistent UI pattern, not a rendering race - but
                    # they carry no information (no event, no date), so
                    # there's no reason to turn them into RawEvents and
                    # dilute real history with UNCLASSIFIED noise.
                    if not event_text and not date_text:
                        continue

                    structured.append({"location": location, "event": event_text, "date": date_text})
                return structured
            except StaleElementReferenceException:
                # The framework can still tear out and replace the list
                # while this is mid-read even after the staleness wait in
                # search() - re-querying everything fresh (not just
                # resuming) is the correct recovery, since a torn-out
                # list means every element handle from this attempt is
                # suspect, not just the one that raised.
                if attempt == retries:
                    raise
                time.sleep(1)
        return []

    def close(self) -> None:
        if self._driver is not None:
            try:
                self._driver.quit()
            except Exception:
                # quit() itself throws when the session/window is
                # already broken (the recurring "no such window" crash
                # this environment has been hitting) - without this,
                # self._driver never gets set to None and the exception
                # propagates out of __exit__, on top of whatever OS
                # process was already orphaned by the broken session.
                # Best-effort cleanup: always clear the reference even
                # if telling a dead session to quit doesn't succeed.
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
        last_location: str | None = None
        for row in structured:
            location = row.get("location") or last_location
            last_location = location

            event_text = row.get("event", "")
            events.append(RawEvent(
                container=raw.container,
                date=self._parse_datetime(row.get("date", "")),
                raw_text=event_text,
                location=location,
                vessel_info=_extract_vessel_info(event_text),
                source="Maersk",
                scraped_at=raw.scraped_at,
            ))
        return events

    @staticmethod
    def _parse_datetime(date_str: str):
        if not date_str:
            return None
        parsed = pd.to_datetime(date_str, errors="coerce")
        return None if pd.isna(parsed) else parsed.to_pydatetime()
