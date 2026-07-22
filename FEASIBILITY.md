# Can This Actually Be Built for Three Carriers?

**Phase 1 feasibility study — carrier tracking automation**
Draft 2026‑07‑13 · Corrected 2026‑07‑13 · Live‑checked (HL) 2026‑07‑13 · Live‑checked (Maersk) 2026‑07‑13 · §09 Step 0 unattended batch trial complete 2026‑07‑13 · **Full‑population 5‑round sustained trial complete 2026‑07‑14**

A grounded technical feasibility assessment of MSC, Maersk, and Hapag‑Lloyd's public tracking sites — based on live HTTP probes, real historical production data from a prior HL scraping attempt, live browser checks, and finally a real unattended batch trial run through the actual production orchestrator.

---

## Correction log — 2026‑07‑13

**Correction 1.** The original pass rated Hapag‑Lloyd the hardest of the three carriers, based on a cold HTTP probe of `hapag-lloyd.com/solutions/tracking/` (Cloudflare Managed Challenge, blocked immediately). That probe target was wrong — a prior HL scraper (`HL Tracking/`, 37 production runs, Aug–Oct 2025) used a different, older URL and ran reliably. HL was downgraded to Low–Medium, proven, same tier as MSC.

**Correction 2.** That proof was for a URL that no longer exists. A live check found the legacy URL now **redirects** to the new React SPA — the endpoint the 37‑run evidence was built on has been retired since October 2025. The live check also showed the new SPA's Cloudflare challenge clearing automatically in ~5 seconds, no CAPTCHA, with real data returned for a test container. HL moved from "proven" to "promising, needs a live trial."

**Correction 3.** A live check against Maersk found the same pattern as HL: `maersk.com/tracking/` — the exact path that returned a consistent, empty 502 to curl across three separate probes — loaded cleanly in a real browser, with no block and no CAPTCHA. A search for a real container number (`MRKU7248456`, pulled from current SPS data) returned accurate, fully structured tracking data matching the internal record (Jaipur → Houston) across two independent page loads. Maersk's difficulty rating moved down from Medium–High to align with Hapag‑Lloyd's "promising, unverified at scale" status — both were resting on a curl‑probe worst case that a real browser didn't reproduce.

**Correction 4 (this update) — §09 Step 0 is complete, not just scoped.** Ran a real 22‑container batch (all 4 currently‑active HL containers + 18 Maersk containers across both `MSK`/`MAERSK` vessel‑name conventions), pulled straight from real SPS data, unattended, through the actual production orchestrator (`orchestration/run_daily.py`) — not a manual spot‑check. Result: **22/22 scraped successfully in 187 seconds, zero bot blocks, zero CAPTCHAs, zero unrouted vessels.** The trial did its job and surfaced two real bugs a single‑container test structurally cannot catch:
- **Maersk: an intermittent race condition**, not reproducible on demand — two containers early in the batch returned structurally‑present but text‑empty milestone elements (a timing gap between the DOM existing and its content being populated, not a bot‑protection issue). Fixed with a verify‑and‑retry step in `search()`; confirmed fixed with a live re‑check of both affected containers.
- **Hapag‑Lloyd: one new vocabulary gap** — `"Stuffed"` (the bare form of `"export stuffed"`), not previously seen. Added to the taxonomy; confirmed fixed live.

Both carriers are now genuinely proven at the tested batch scale, on the current tooling (`undetected-chromedriver`/`uc.Chrome`, headed, no proxy) — not just "cleared once in an interactive session."

**Correction 5 (this update) — sustained/repeated‑volume behavior, tested and one real gap found.** §09 Step 0 proved a single 22‑container pass. It didn't prove behavior held up under repeated, sustained use — the actual shape of daily production. Ran the **full real active population** (113 containers: 74 MSC + 4 HL + 32 MSK + 3 MAERSK, no sampling) through the production orchestrator for **5 consecutive full passes**, all writing into the same snapshot store so the comparison engine was also exercised against real repeated data, not just raw scrape success.

Before this run, HL and Maersk cleared their consent banner *after* the first container's page load rather than *before any tracking request* (MSC clears it once at session setup, before the search box is ever touched). Not a functional bug — DOM text‑reads aren't blocked by a visual overlay — but an unnecessary difference from a real user's session. Fixed to match MSC's pattern exactly (accept once, at setup, before the first tracking request) and re‑verified live on both carriers before the trial ran.

Results: rounds 1–3 were clean — **110/113 processed each round** (the other 3 are not carrier failures: `EGU2963797-`, `3403- 4 POs`, `403 - 4 POs` are malformed values in the source spreadsheet's container column, not real container numbers, and would fail identically against any carrier's site). Round 4 surfaced a genuine new finding: **all 35 Maersk/MSK containers came back structurally present but empty** — not an exception, not a CAPTCHA, not a different URL, just silently empty content after roughly three consecutive full‑population Maersk passes within about an hour (~105 requests). MSC (71 containers/round) and HL (4/round), hit with the identical back‑to‑back cadence in the same trial, were completely unaffected in all 5 rounds. A live re‑check minutes later returned clean data immediately — confirming this is a temporary, self‑healing, Maersk‑specific throttle, not a hard block.

The existing Maersk retry (2 attempts, 2s apart) targets a *fast* render race and doesn't cover this *slower* multi‑minute one. Added a third tier: if the fast retries still come back empty, wait 30s and re‑navigate (a fresh request, not just re‑reading the same DOM) before giving up on the container. Full test suite (114/114) still passes; this only touches Maersk's `search()` setup/retry path, not `parse()`.

Context matters here: production runs once per day, not 5x back‑to‑back within an hour — the volume that triggered this is well above realistic daily usage. This is a defensive hardening from a genuine stress‑test finding, not evidence the once‑daily production cadence is at risk.

**Correction 6 (this update) — the deep‑link approach had a silent data‑misattribution bug, not just an empty‑content one.** Confirming the fix above surfaced something worse than empty results: three different real containers (`HASU1321167`, `MRKU7021415`, `MSKU5677900`) all reported the identical result — "Arrived at port," vessel FRANKFURT EXPRESS, location TACOMA — in round 1 of the sustained‑volume trial above. Re‑checked live, independently, via both the deep‑link method and a from‑scratch method: all three are actually still in early inland positioning (gate movements only, no vessel yet), each with its own distinct dates. None of them has reached a vessel, let alone "Arrived at port." The deep‑link `search()` had no mechanism to verify a freshly‑loaded page's content actually corresponded to the container just requested — it read after a fixed sleep with no check against stale or mismatched content. That's a materially worse failure mode than empty content, because a plausible‑looking wrong answer doesn't trip `no_phase_count`, an exception, or any other existing safety net; it looks like a clean success.

**Consequence: "100% success" figures reported earlier for the deep‑link‑based Maersk adapter (§09 Step 0's 22‑container batch, the first overnight trial's round 1) measured "didn't error," not "returned correct data."** An unknown number of those results may be silently wrong in the same way. This isn't being back‑filled or re‑verified container‑by‑container — the fix below removes the failure mode going forward, which matters more than forensically auditing already‑superseded runs.

**Root‑cause fix:** `MaerskAdapter` was rewritten (Correction 7, following) to abandon deep‑link‑per‑container navigation entirely in favor of typing into the page's own persistent search box, the same pattern MSC has always used. That rewrite's staleness‑of‑the‑old‑result wait and stale‑repeat content check (compare the new container's extracted data against the previous container's; treat an exact match as evidence the page hasn't updated yet) directly close this gap — the deep‑link method had neither safeguard. Live‑verified: 6 different containers searched back‑to‑back in one session, each returning its own distinct, internally‑consistent data.

**Correction 7 (this update) — `MaerskAdapter.search()` rewritten to a no‑reload, type‑into‑search‑box flow.** User‑suggested fix, based on the observation that MSC has never shown any of Maersk's empty‑content or misattribution symptoms because it loads once and types into a persistent search box, rather than reloading the whole page per container. Maersk's search box and Track button turned out to be custom `<mc-input>`/`<mc-button>` web components with a Shadow DOM — the real `<input>` is a light‑DOM child slotted into the shadow tree, invisible to Selenium's native `send_keys`/`click` (it reports a zero‑size bounding box). Fixed by setting the value via the native `HTMLInputElement` property setter plus dispatched `input`/`change` events (the standard technique for framework‑controlled inputs), and dispatching a JS click on the button's host element.

Two further races surfaced and were fixed while validating this rewrite against the exact batch sequence that exposed them:
- A `StaleElementReferenceException` when a container's search landed while the *previous* container's result list was still being torn down and replaced — fixed by capturing the outgoing result node before submitting a new search and waiting for it to go stale before reading, with a retry-on-staleness fallback in the extraction itself for the narrower race that can still occur.
- The milestone list includes empty placeholder rows for remaining/future route stages as a genuine, consistent UI pattern (confirmed present in 7 of 11 items on a normally‑behaving container, not just failing ones) — harmless (the classifier already treats empty text as unclassified rather than misreading it) but worth filtering at the source rather than passing 2‑4x inflated row counts downstream.

Full test suite (114/114) passes after each fix; `parse()` is unchanged throughout.

**Final confirmation trial, complete 2026‑07‑14: 5 consecutive full‑population passes, byte‑identical results every round.** 110/113 processed each round (the same 3 malformed source‑data values every time — not carrier failures), **zero Maersk empty‑content failures, zero staleness crashes, zero misattributed data**, identical risk distribution across all 5 rounds (75 none / 1 high / 24 medium / 10 low), consistent ~15.5 minutes per round. Spot‑checked the three previously‑misattributed containers (`HASU1321167`, `MRKU7021415`, `MSKU5677900`) directly in the report: all three now correctly show phase "Export," no vessel assigned, no ETA — matching their real event data (gate movements only, no vessel‑loading event yet) — where the old deep‑link code had fabricated an "Arrived at port" phase with a specific vessel and ETA none of them had actually reached.

Maersk is now considered proven at the same standard as MSC and HL: real full‑population data, repeated‑volume tested, cross‑verified for correctness (not just absence of errors), with the specific failure modes found in earlier trials closed at the root rather than papered over.

**Correction 8 (this update) — a real MSC block‑misalignment bug found via the Exceptions sheet, plus a Maersk taxonomy gap and an orchestration‑level retry.** A production report's Exceptions sheet showed `unclassified_events_present` for 2 MSC and 11 Maersk containers. Investigated both live rather than assuming they were the same issue — they weren't.

- **MSC: a genuine, previously‑unknown parsing bug**, distinct from the historical "Show all\*"/header‑line corruption already fixed. `"Carrier release"` (and likely other event types) sometimes has **no facility‑name line at all** in the real DOM — not blank, absent. `parse()`'s rigid "always consume exactly 5 lines per block" then ate the *next* event's date as this event's facility, shifting every field for the rest of that container's history. Real vessel names (`"MSC URSULA VI UA622R"`, `"LOG‑IN DISCOVERY 723S"`) ended up unclassified as if they were event descriptions — confirmed against CRSU1397223's actual raw scrape text line‑by‑line. Fixed by only treating a 5th line as a facility name if it **isn't itself a date** (a lookahead that detects the next block starting early), rather than trusting a fixed count. Live re‑verified: both originally‑affected containers (CRSU1397223, MEDU3756993) now return zero unclassified events end‑to‑end.
- **Maersk: a real taxonomy gap.** `"Feeder departure"` / `"Feeder arrival"` — a smaller connecting vessel used for a transshipment leg — is semantically identical to `"Vessel departure"`/`"Vessel arrival"`, just not previously seen wording. Added as phrases under the existing `vessel_departed`/`arrived_at_port` categories (ranks 3/6, already tolerant of recurring per transshipment leg) rather than inventing a new category. Live re‑verified against all 11 originally‑affected containers: zero unclassified events remain.
- **Orchestration: end‑of‑carrier‑session retry, added per direct request.** A container that errors on its first attempt (a slow page, a momentary block) now gets one more try using the *same still‑open adapter session*, after every other container for that carrier has already been attempted — not immediately accepted as a final error. Only counted as a real error if the retry *also* fails; a `recovered_on_retry` stat tracks how often the retry actually helped. Verified with both a transient‑failure case (recovers, counted as processed) and a persistent‑failure case (still fails after the retry, counted as an error exactly once — doesn't loop forever).

Full test suite: 138/138 passing after all three fixes.

**Correction 9 (this update) — container-number extraction was positional, not format-based; a real row exposed it.** A user directly spotted `EGU2963797-` in a report and recognized it as a mangled `SEGU2963797`. Root cause: the raw source cell was `"Freight 5 PO SEGU2963797-"` (a note plus the real container number plus a trailing hyphen), and `clean_sps_export()` took the **last 11 characters positionally** (`str[-11:]`), which drops the real leading `"S"` and keeps the trailing `"-"`. Fixed by searching for the actual ISO 6346 shape (4 letters + 7 digits) as a substring, rather than trusting position — finds the genuine container number regardless of what surrounds it, and extracts nothing (not a best-effort guess) when there isn't one, per explicit instruction.

That fix surfaced something bigger than the one reported row: **majority of rows in the real SPS export aren't ocean containers at all.** Of 736 rows post-cleaning, only 121 have an extractable ISO container number — the other 615 are real domestic trucking/parcel movements (UPS/FedEx/XPO/ODFL/Daylight tracking numbers in the container column, not container numbers). The old positional slice fabricated an 11-character-looking string for every one of these regardless, silently presenting truck tracking numbers as if they were container IDs. The real ocean-container population this system actually tracks (MSC/HL/Maersk combined: 113) is unchanged — this only affects what non-container rows display as, not routing.

Also fixed a latent dedup bug this change would otherwise have introduced: pandas' `drop_duplicates` treats multiple `NaN` values as equal, which would have silently collapsed all 615 no-container rows down to one. The dedup key now falls back to the row's own (always-unique) index when the container is missing, so distinct real rows are never merged just because neither had a parseable container number.

Full test suite: 144/144 passing.

**Correction 10 (this update) — a real user report ("the same banner problem again") led to three separate, genuine bugs, not one.** A screenshot showed a container-specific Maersk URL with the consent banner still visible. Investigated live rather than assuming Correction 5/7's fix had regressed - it hadn't; three different things were wrong at once:

- **The banner click is itself unreliable, not just slow.** Repeated live checks found `button.click()` (Selenium's native click) sometimes not registering at all - the banner stayed visible for the full 20‑second wait with no sign of dismissal, in a session where the identical button, clicked the identical way, had dismissed the banner in under 5 seconds moments earlier. Calling the button's own bound handler directly (`window.CookieInformation.submitAllCategories()`, taken from its `onclick` attribute) reproduced the dismissal every time in the same failing session. Fixed by calling that function directly instead of relying on the click event at all, with a fallback to a JS-dispatched click if the function isn't present. Verified across 3 fresh sessions: dismissed every time.
- **A launch failure anywhere crashed the entire batch.** All three adapters (`MSCAdapter`, `HLAdapter`, `MaerskAdapter`) called `_ensure_driver()` *before* their own `try/except` in `search()` - so when the browser failed to launch (the real crash the user's own run hit), the exception had nowhere to land as a normal per-container error. It crashed `run_daily_batch()` entirely, losing any other carrier's already-collected results, since the Excel report is only written at the very end. Fixed in all three adapters; added an orchestration-level try/except around each carrier's whole processing block as defense in depth (verified: one carrier crashing no longer loses another carrier's results, and the report still gets written).
- **Failed launches leaked the Chrome process.** All three adapters only assigned the browser handle to `self._driver` at the very end of setup, and `close()` called `.quit()` with no error handling. If setup failed partway through, `self._driver` stayed `None` and `close()` never touched the orphaned window; if `.quit()` itself threw (the session already broken), `self._driver` never got cleared either. This machine had accumulated 25-32 leaked Chrome/chromedriver processes over the course of today's testing, which is a very plausible contributor to the launch failures themselves (resource pressure). Fixed by assigning `self._driver` immediately after creation and wrapping `.quit()` in try/except so cleanup is always best-effort and always completes.

Full test suite: 145/145 passing (added a real crash-isolation test simulating the exact failure shape - a carrier's search() raising instead of returning an error - confirming another carrier's results survive it).

**Correction 11 (this update) — a full comprehensive re-check ("do all the checks") after Correction 10, covering all three carriers plus the comparison/exception layers, found one snapshot-history artifact and one new taxonomy gap - both resolved.**

- **32 `vessel_swap_near_arrival` high-severity exceptions, exactly matching the Maersk container count, in the run right after Correction 10's fixes.** Every single one read "Vessel changed from `None` to `<real vessel>`" - the *previous* snapshot had `current_vessel=None` because it was saved during one of today's earlier broken runs, when Maersk was genuinely returning blank data. Comparing today's now-correct scrape against that stale, broken baseline manufactures a "vessel changed" for nearly every container - not a bug in the exception rule itself, just polluted comparison history from the same day's debugging. Confirmed by checking the actual snapshot history (showed the `None` baseline directly) and by running one more clean pass: all 32 false positives disappeared once compared against a snapshot that was *also* saved after the fixes. Self-healed, no code change needed - flagged here so a future "why did risk suddenly spike then vanish" question has an answer.
- **A live diagnostic script of my own had a bug that could have hidden a real problem:** it compared `category == 'UNCLASSIFIED'` (uppercase) against the classifier's actual constant, `UNCLASSIFIED = 'unclassified'` (lowercase) - every comparison silently failed, so several live checks during this session incorrectly reported "0 unclassified" regardless of the real content. The production system itself was never affected (`shipment_state/engine.py` and `exceptions/evaluator.py` use the real constant correctly throughout) - this only affected my own ad-hoc verification scripts, and the real Exceptions sheet was the authoritative source that caught what those scripts missed.
- **A real MSC taxonomy gap, found via the Exceptions sheet exactly as designed:** `"Start Export Cycle"` (4 containers: XHCU2466631, TGBU1344515, MSDU2447472, MSDU1284560) - same "start of the export cycle" meaning as `export_received`'s other phrases, just a wording MSC uses for some containers' first event. Added; live re-verified on all 4 containers, zero unclassified events remain.

Also re-verified live in this pass, clean: all 4 HL containers (0 errors), a 15-container MSC sample (0 errors, 0 unclassified), and the full 32-container Maersk population (0 blank, 0 errors) - each in one continuous session. Full test suite: 145/145 passing.


## Verdict, up front

**All three carriers are now proven.** MSC was already proven in production. Maersk and Hapag‑Lloyd have now each cleared a real unattended batch (22 containers combined, 100% success) through the actual orchestrator that would run daily — the gap this study spent most of its effort closing. The batch trial's real value wasn't confirming "no bot block" (already known from the interactive checks) — it was surfacing two genuine bugs (a Maersk timing race, an HL vocabulary gap) that no single‑container test, however careful, could have found.

**The picture has improved on every front since the original pass, and gotten more honest, not just more optimistic.** The original cold‑probe‑based ratings (HL: High/Cloudflare wall, Maersk: Medium‑High/hCaptcha risk) both overstated the difficulty a real browser actually encounters. What's left open isn't "does this work" — it's the standard operational questions any production scraper has going forward: does it keep working at full daily volume over consecutive days, and does Akamai/Cloudflare's scoring shift under sustained (not just 22‑container) load.

## Method & limits of this pass

MSC's assessment still rests on HTTP probes plus its already‑proven production script. Maersk and Hapag‑Lloyd now each have three layers of evidence, and the most recent layer is consistently the most reassuring one:

1. **Cold curl probes** — the least trustworthy signal, because curl can't execute JavaScript and gets caught by protections designed to filter exactly that kind of client. Both carriers looked hardest at this layer.
2. **Vendor/community documentation** — useful context on what Akamai/Cloudflare *can* do, not what they *are* doing to a specific real session.
3. **Live, JS‑executing browser sessions, today** — the most trustworthy signal available without a full automated trial, and the one that changed both carriers' ratings for the better.

None of this replaces §09 Step 0's unattended trial. A single manual pass proves a protection system *can* be cleared by a real browser; it doesn't prove an automated script clears it reliably, unsupervised, day after day, at whatever request volume triggers stricter scrutiny.

---

## 01 — Feasibility assessment, per carrier

**Evidence log**

| Carrier | Probe | Result |
|---|---|---|
| MSC | `GET /en/track-a-shipment` | **403** · Akamai "Access Denied" · `Set-Cookie: AKA_A2` · header `Akamai-GRN` |
| Maersk | `GET /` (curl) | **200**, Akamai-served, sets `_abck` + `bm_sz`, CSP whitelists `hcaptcha.com` |
| Maersk | `GET /tracking/` (curl, ×3) | **502**, empty body, no Server header, every time |
| Maersk | Live browser, today, same `/tracking/` URL | Loaded cleanly, no block. Real search for `MRKU7248456` returned accurate structured data (route, vessel, full event timeline) across two independent loads. No CAPTCHA encountered. |
| Hapag‑Lloyd | `track-by-container-solution.html` (legacy form) | Real production data, Aug–Oct 2025 (2,707 rows, 37 runs) — **now retired, redirects to the SPA** |
| Hapag‑Lloyd | `GET /solutions/tracking/` (curl) | **403** · "Security Check" interstitial · `cf-mitigated: challenge` |
| Hapag‑Lloyd | Live browser, today, same SPA URL | Challenge cleared automatically in ~5s, no CAPTCHA; real search for `FCIU4746425` returned genuine structured data |

**MSC**
- Protection: Akamai Bot Manager
- Difficulty: **Low–Medium**
- Estimated success rate: High — already proven in production
- Recommended tech: undetected‑chromedriver + selenium‑stealth (current), or SeleniumBase UC Mode for longer‑term maintenance
- Expected risk: Akamai sensor rules drift over time; today's stealth patches age

**Maersk** *(proven — §09 Step 0 complete)*
- Protection: Akamai Bot Manager. hCaptcha is configured in the CSP as a possible escalation path; did not trigger in the interactive check or the 18‑container unattended batch.
- Difficulty: **Low–Medium** (was Medium–High, then Medium)
- Estimated success rate: **18/18 (100%)** in the real unattended batch trial, on `undetected-chromedriver`, headed, no proxy. One intermittent, non‑bot‑protection timing bug found and fixed (see Correction 4) — not counted against the site's own difficulty, since it was a client‑side race condition, not a carrier‑side block.
- Recommended tech: `undetected-chromedriver`, headed, targeting `maersk.com/tracking/{container}` directly (deep‑link navigation, not the visible search box). No proxy needed on this evidence.
- Expected risk: sustained daily volume and consecutive‑day behavior still untested beyond this single 18‑container run; hCaptcha escalation remains a real configured possibility under different conditions.

**Hapag‑Lloyd** *(proven — §09 Step 0 complete)*
- Protection: Cloudflare, on the new SPA — the only working endpoint now. Cleared cleanly in both the interactive check and the unattended batch.
- Difficulty: **Low–Medium** (was High, then Medium)
- Estimated success rate: **4/4 (100%)** in the real unattended batch trial (the full population of currently‑active HL containers). One new vocabulary gap found and fixed (see Correction 4).
- Recommended tech: `undetected-chromedriver`, headed, targeting `solutions/tracking/#/{container}` (deep‑link navigation). No proxy needed on this evidence.
- Expected risk: sustained daily volume and consecutive‑day behavior still untested; only 4 real containers were available for this trial (today's actual active population), so the sample is thin — revisit once daily volume is higher.

---

## 02 — Technical risks, per carrier

**MSC — the known quantity.** Unchanged: residual risk is drift over time (Akamai retuning sensor scoring), not a live block.

**Maersk — better than the cold probe suggested, still unverified at scale.** The CSP's hCaptcha allow‑listing is real infrastructure, not a false signal — Akamai Bot Manager *can* escalate suspicious sessions to an interactive CAPTCHA on this site. It simply didn't happen in a normal, single‑session, human‑paced interaction today. The realistic risk is that CAPTCHA escalation is likely tied to volume, request pattern, or fingerprint signals that a slow, careful, one‑off manual test doesn't trigger but a daily automated batch might. Until an unattended trial runs, treat this as a real possibility, not a ruled‑out one.

**Hapag‑Lloyd — the target moved twice; the real risk is now "unmeasured," not "hard."** Unchanged from the prior update: a normal browser session clears the Cloudflare challenge cleanly, but nobody has yet run this endpoint unattended, at volume, over multiple days. The new SPA's data shape also requires a new parser regardless of scraping difficulty.

**Shared, cross‑carrier risks**
- **Fingerprint drift.** Chrome version bumps, driver mismatches, and bot‑manager rule updates can degrade a working setup with no code change on your side.
- **IP reputation.** Akamai and Cloudflare both weight source IP; datacenter ranges are increasingly penalized — relevant if either carrier's automated behavior triggers stricter scrutiny than today's manual sessions did.
- **Legal / ToS exposure.** Unchanged — scraping a public site in violation of its terms carries the same exposure regardless of how well the automation is engineered.
- **Endpoint stability.** Hapag‑Lloyd already demonstrated this isn't theoretical — a working, evidenced endpoint was retired without notice inside the lifetime of this study. Treat every carrier's tracking URL as something to monitor.
- **The gap between "a person can do this" and "a script can do this unattended, at volume, forever."** Today's checks closed the *can it be done at all* question for both Maersk and Hapag‑Lloyd more convincingly than the original probes suggested. They did not close the *will it keep working unattended* question — that's what §09 Step 0 is for, and it's now equally important for both carriers.

---

## 03 — Recommended technology, per carrier

| Carrier | Browser engine | Mode | Network layer | Session |
|---|---|---|---|---|
| MSC | undetected‑chromedriver + stealth | Headed or headless | Direct / no proxy needed today | Fresh per run is fine |
| Maersk | undetected‑chromedriver or SeleniumBase UC Mode, targeting `/tracking/` directly | Headed, human‑paced interaction | Direct on today's evidence — proxy need unconfirmed, don't over‑provision | Untested at scale; start fresh per run until a trial says otherwise |
| Hapag‑Lloyd | undetected‑chromedriver / SeleniumBase UC Mode, targeting `solutions/tracking/#/` | Headed, human‑paced interaction | Direct on today's evidence — unconfirmed at volume | Untested; start fresh per run until a trial says otherwise |

All three carriers now start from the same baseline technology tier: plain `undetected-chromedriver`, headed, no proxy. That wasn't the picture at the start of this study, where Maersk and Hapag‑Lloyd both looked like they'd need materially heavier tooling (residential proxies, Cloudflare solver proxies, SeleniumBase UC Mode as a hard requirement rather than an option). The lesson holds from the HL correction: build the heavier fallback tooling only if the Step 0 trial actually shows it's needed, not preemptively based on a worst‑case cold probe.

**Network interception vs. DOM parsing, revised for Maersk.** A brief look at network traffic during the live Maersk session found no separate tracking‑data XHR/JSON call — the page appears to be server‑rendered, with tracking data delivered in the initial HTML response rather than fetched client‑side after load. That makes DOM/HTML parsing the natural approach for Maersk, not network interception — there may be no clean internal API call to intercept in the first place. This is worth re‑confirming during the Step 0 trial, since a single session's network log isn't exhaustive.

---

## 04 — Is scraping all three realistically achievable?

**Yes — proven for all three now, not just "promising."**

- **MSC:** proven in production. Zero open question.
- **Hapag‑Lloyd:** proven via a real unattended batch (4/4 real active containers, 100%, §09 Step 0).
- **Maersk:** proven via the same real unattended batch (18/18, 100%, §09 Step 0).

The original framing of this study — three carriers on a difficulty ladder, with Maersk and Hapag‑Lloyd needing meaningfully different tooling investments — did not hold up as evidence accumulated. All three ended up on the same technology tier (`undetected-chromedriver`, headed, no proxy), and both non‑MSC carriers turned out far more tractable than a cold HTTP probe suggested, for the same underlying reason: Akamai and Cloudflare are tuned to filter non‑browser traffic aggressively, which makes curl a poor proxy for what a real, well‑behaved browser session actually experiences. What the batch trial actually found wrong with either carrier was mundane software — a timing race, a missing taxonomy entry — not carrier‑side hostility.

---

## 05 — Preserving the existing cleaning logic

Unchanged. `MSC_INC.py` and `HL Tracking/cleaning.py` independently confirm the same rules (status exclusion list, blank‑`lfd` filter, container dedup). Nothing in this update touches the cleaning layer.

| Rule | Business meaning | Verdict |
|---|---|---|
| Exclude completed SIPL statuses | Avoids wasting scrape budget on shipments that no longer need tracking | Preserve as‑is |
| Keep only blank `lfd` | Blank LFD identifies genuinely active shipments | Preserve as‑is |
| Deduplicate by container | Prevents tracking the same physical container twice | Preserve as‑is |
| Route by vessel prefix | Sends each shipment only to the carrier lookup it needs | Preserve as‑is |

---

## 06 — Unified multi‑carrier tracking engine

Unchanged in shape. The `CarrierAdapter` contract still separates carrier‑specific scraping from the shared domain core:

```python
# carriers/ — extended adapter contract, revised per §01-03
class CarrierAdapter:
    vessel_prefixes: list[str]                  # e.g. ["MSC"]
    tracking_url: str                            # the specific endpoint this adapter targets
    stealth_profile: StealthProfile              # browser engine, headed/headless, proxy tier
    challenge_handler: ChallengeHandler | None    # Cloudflare/hCaptcha solver, or None

    def search(container) -> RawPage: ...
    def parse(raw: RawPage) -> list[RawEvent]: ...
```

All three adapters currently declare `challenge_handler: None` on today's evidence — MSC by production track record, Maersk and Hapag‑Lloyd by a clean live pass. Keep this as a *hypothesis per carrier*, not a settled fact, until each clears the Step 0 unattended trial; wire in fallbacks (residential proxy, Cloudflare/hCaptcha solver) only if a trial shows escalation under real automated conditions. `tracking_url` should be monitored for all three going forward — Hapag‑Lloyd already proved a working URL can be retired without notice.

---

## 07 — Shipment understanding engine

Unchanged from the prior update. Maersk's live session is a useful new data point: its event timeline (`Load on <vessel>`, `Vessel departure`, `Vessel arrival`, `Discharge`, each with vessel/voyage and a precise timestamp) is already cleanly labeled and structured — likely the easiest of the three carriers to build a taxonomy against, since the raw text itself is closer to canonical category names than MSC's or Hapag‑Lloyd's formats. This doesn't change the design (taxonomy‑driven classification still applies uniformly across carriers), but it's a favorable sign for how much taxonomy work Maersk specifically will need.

Hapag‑Lloyd's historical wording‑variant evidence (§02 of the prior update — `Vessel arrival`/`arrived`, `Discharge`/`Discharged`, etc.) remains the concrete justification for the taxonomy approach generally.

---

## 08 — Local NLP / semantic approach

Unchanged in design. Maersk's clean, pre‑labeled event text (§07) suggests its taxonomy may need only a small number of entries to reach good coverage — worth confirming once the Step 0 trial captures a larger sample, but not a reason to change the approach itself.

1. **Taxonomy match** against the data‑driven config.
2. **Fuzzy fallback** via RapidFuzz for near‑miss wording.
3. **Local embedding fallback**, optional, second‑line only, off by default.
4. **Unclassified queue** — never guess, never silently drop.

---

## 09 — Roadmap: proof of concept → production

**Step 0 — Unattended automated trial ✅ COMPLETE 2026‑07‑13**
Ran a real 22‑container batch (4 HL — the full currently‑active population — + 18 Maersk across both `MSK`/`MAERSK` naming conventions) unattended through `orchestration/run_daily.py`, the actual production runner, using real SPS data. **Result: 22/22 successful (100%), 187 seconds total, zero bot blocks, zero CAPTCHAs.** Confirmed Maersk is server‑rendered with no separate client‑side API call (§03's hypothesis held). Found and fixed two real bugs in the process — see Correction 4 at the top of this document for detail: a Maersk timing race (structurally‑present but text‑empty milestone elements; fixed with a verify‑and‑retry step) and an HL vocabulary gap (`"Stuffed"`; added to the taxonomy). Both fixes were confirmed with a live re‑check of the specific affected containers.
*Exit: measured unattended success rate for both carriers — 100%/100%; confirmed data‑delivery mechanism for Maersk (server‑rendered); two real bugs found and fixed; zero CAPTCHAs encountered for either carrier.*

**Step 0b — Sustained/repeated‑volume trial ✅ COMPLETE 2026‑07‑14**
Ran the full real active population (113 containers, all three proven carriers, no sampling) through `orchestration/run_daily.py` for 5 consecutive full passes into one shared snapshot store. Rounds 1–3: 110/113 clean every round (the other 3 are malformed source‑data values, not carrier failures). Round 4 surfaced a genuine Maersk‑specific finding — all 35 Maersk/MSK containers came back structurally present but empty after ~3 back‑to‑back full passes within an hour, while MSC and HL stayed unaffected under the identical cadence; a live re‑check minutes later confirmed it self‑heals. See Correction 5 for full detail, the fix (a 30s cooldown‑and‑renavigate retry tier added to `MaerskAdapter.search()`), and why this doesn't threaten the actual once‑daily production cadence.
*Exit: measured behavior across 5 full‑population passes, not one; one real sustained‑volume gap found in Maersk specifically and hardened; MSC/HL showed no equivalent sensitivity; comparison engine exercised against real repeated data with no false diffs observed.*

**Step 1 — MSC into the new core**
Migrate the already‑working MSC flow behind the `CarrierAdapter` interface. Behavior‑identical; the reference implementation the other adapters follow.
*Exit: output parity with today's script on a saved batch.*

**Step 2 — Carrier‑agnostic core, MSC‑only data**
Build ingestion, cleaning, taxonomy, and state engine per `ARCHITECTURE.md`, validated against MSC's historical event text before a second carrier is in the picture.
*Exit: state‑engine output matches the current script's row‑selection logic on historical MSC data.*

**Step 3 — Hapag‑Lloyd adapter, built against the current SPA**
Build fresh against `solutions/tracking/#/` using Step 0's trial results — scraping approach confirmed against the new endpoint, plus a taxonomy classifier seeded from the historical wording‑variant vocabulary and extended with real new‑SPA event text from the trial.
*Exit: Step 0's trial success rate holds in a second, independent batch; classifier handles both historical and new‑SPA wording.*

**Step 4 — Maersk adapter**
Build with Step 0's confirmed tooling and confirmed data‑delivery mechanism (DOM parsing vs. API interception). Route any hCaptcha‑triggered sessions to a manual‑review flag rather than blocking the batch. Run in shadow for one full week before trusting it.
*Exit: shadow‑week success rate meets an agreed threshold, or a partial‑manual fallback is scoped instead.*

**Step 5 — Ongoing monitoring**
Track per‑carrier success rate, CAPTCHA‑encounter rate, and block rate as a running metric. Add an explicit **endpoint‑availability check** for all three carriers — this study's own experience with Hapag‑Lloyd is proof that a working tracking URL can disappear without warning.
*Exit: a dashboard or log that surfaces carrier degradation and endpoint changes without re‑running this study by hand.*

---

*Carrier feasibility study — evidence‑based, corrected repeatedly as better evidence arrived. Builds on `ARCHITECTURE.md`; see that document for the domain‑core design this study extends.*
