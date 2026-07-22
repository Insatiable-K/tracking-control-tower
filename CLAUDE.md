# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Two systems live in this repo:

1. **`tracking_control_tower/`** — the current, actively-developed system. A carrier-agnostic Python package (real package with modules and a unit test suite, not a script) covering MSC, Hapag-Lloyd, and Maersk through one pipeline: clean → route by carrier → scrape → classify events against a taxonomy → infer shipment state → diff against history/SPS → evaluate exceptions → render Excel. Run it with `python run_tracking.py` (project root). See `ARCHITECTURE.md` for the design and `FEASIBILITY.md` for the real-data validation history (including several real bugs found and fixed via live batch trials — read the Correction log at the top before assuming any carrier adapter's behavior from the code alone).
2. **`MSC_INC.py`** — the original single-carrier (MSC-only) script `tracking_control_tower/` replaces. Left in place as reference/fallback, not maintained going forward. Documented below for historical context.

There is no git repo, no build system, and no dependency manifest (requirements.txt/pyproject.toml) for either — dependencies are whatever is installed in the local Python 3.13 environment. `tracking_control_tower/tests/` does have a real `unittest` suite (114 tests as of the last full run: `python -m unittest discover -s tracking_control_tower/tests`); `MSC_INC.py` has none.

## Running the new system

```
python run_tracking.py
```

Reads `1RAW.xlsx` (same input file, same expected schema as `MSC_INC.py` — see `EXPECTED_COLUMNS` in `tracking_control_tower/config/settings.py`), covers all three carriers in one run, and writes a single timestamped `Tracking_Report_<date>_<time>.xlsx` to the project root (sheets: `Shipment Report`, `Exceptions`, `SPS Updates`).

`tracking_control_tower/data/snapshots.db` and `checkpoints.db` are **persistent state, not per-run output** — they carry shipment history (for change detection) and resume state (for killed-run recovery) forward across every run. Don't delete them between runs; do treat them as safe to delete if you want to reset history/start over, since they're derived state, not a source of truth.

`HEADLESS = False` at the top of `run_tracking.py` matches every real validation trial in `FEASIBILITY.md` — all of them ran with a visible browser. Nothing has validated a headless run; don't flip it without re-validating against the live sites first, the same way every other change to carrier adapters in this repo has been.

Same live-scraping caveats as below apply: expect runs to be slow (each carrier scrapes one container at a time in a real browser), and MSC/HL/Maersk's DOM structure or search flow are each the most likely thing to break after a site redesign (see `tracking_control_tower/carriers/*.py` docstrings for what each adapter actually relies on and why).

## Running the legacy script

```
python MSC_INC.py
```

Requirements: Google Chrome installed locally. The script auto-installs a matching chromedriver via `chromedriver_autoinstaller` and drives a **visible** (non-headless) browser by default (`HEADLESS = False` near the top of the script, ~line 179). Flip that flag to `True` for headless runs.

Input file is hardcoded at the top of the script:
```
C:/Users/Abhay/OneDrive - Architectural Surfaces/Documents/Abhay/Tracking Automation/EDA Tracking/1RAW.xlsx
```
It must contain a sheet literally named `Sheet 1` with exactly 16 columns in the fixed order the script expects (see `expected_cols` near the top) — the script hard-exits if the column count doesn't match.

There are no CLI args, config files, or env vars — all tunables (sheet name, status filters, rail location list, vessel prefixes, xpaths) are literals inline in the script.

## Pipeline structure (single file, sequential stages)

`MSC_INC.py` runs as one long procedural script with numbered `# === N. STEP ===` comment banners marking stages. It is not organized into functions/modules except for two helpers (`track_container_and_parse`, `select_best_row`, `compare_eta`, `compare_vessels`, `pad_date_str`, `get_updated_eta`, `get_updated_vessel`, `extract_after_last_hyphen`). Understanding it means reading the whole file top to bottom; there's no per-file architecture to navigate.

The stages, in order:

1. **Load & clean raw Excel** — reads `1RAW.xlsx`, renames columns to the fixed `expected_cols` schema, parses date columns, trims/normalizes `sipl` and `container` string fields.
2. **Filter rows** — drops rows whose `sipl_status` is in a hardcoded exclusion list (delivered/on-hold/etc.), keeps only rows where `lfd` (last free day) is *missing* (i.e. not yet resolved), and de-duplicates on `container`.
3. **Segregate by carrier** — buckets rows into per-prefix DataFrames (`vessel_dfs['MSC']`, `['HL']`, `['CMA']`, etc., from a hardcoded `prefixes` list) based on the `vessel` column, plus a `mismatched` bucket for anything that doesn't match a known prefix. Writes `SIPL_filtered_<timestamp>.xlsx` with one sheet per carrier.
4. **Selenium scrape (MSC only)** — launches an `undetected_chromedriver`/`selenium-stealth` Chrome session against `https://www.msc.com/en/track-a-shipment`, and for every container in the `MSC` bucket, types it into the tracking box and scrapes the resulting shipment-history table by parsing the section's `.text` into fixed-size (5-line) row blocks via XPath (see `track_container_and_parse`). This is brittle by nature — MSC's DOM structure and XPaths (`tracking_section_xpath`, `pod_eta_xpath`) are the most likely thing to break after a site redesign. Writes `msc_scraped_results_<timestamp>.xlsx` (sheets: `Clean Data`, `Errors`).
5. **Merge scraped data with raw MSC records** on `container` (inner join for matches, anti-join for `missing_scraped_df`). Writes `merged_validation_output_<timestamp>.xlsx`.
6. **Reconcile / pick best row per container** (`select_best_row`) — for containers with multiple scraped history rows, prioritizes an "Estimated Time of Arrival" row, falling back through "Import Discharged from Vessel" → any row with a POD ETA → most recent row.
7. **Change detection** — `compare_eta` / `compare_vessels` flag whether the newly scraped ETA or vessel differs from the original raw-file value, producing `eta_changed`, `vessel_changed`, `eta_or_vessel_changed` columns.
8. **Rail vs non-rail split** — rows are split by `ship_to_location` against a hardcoded `rail_locations` list (`Denver`, `Kansas City Hub`, `SB Chicago`).
9. **Final output** — builds `output_df` (the "MSC Working" sheet) with `updated_eta`/`updated_vessel` columns computed only where a change was detected, and writes everything to `MSC_NonRail_Final_Working_<timestamp>.xlsx` with sheets: `non_rail_final`, `MSC Working`, `Missing_From_Scraped`, `Clean Data`, `Errors`.

## Working in tracking_control_tower/

- Read the target carrier adapter's module docstring (`carriers/msc.py`, `carriers/hl.py`, `carriers/maersk.py`) before changing its `search()` — each documents a specific, hard-won reason for its current interaction pattern (e.g. why Maersk types into its search box instead of reloading per container, why HL still reloads per container, why each carrier's cookie-consent handling is structured the way it is). These aren't arbitrary choices; `FEASIBILITY.md`'s Correction log has the real failures that drove each one.
- `events/taxonomy.yaml` is the event-classification vocabulary, seeded from real historical data and extended live as each carrier's actual site wording was discovered — don't add a category or phrase without a real observed example backing it.
- The state engine (`shipment_state/engine.py`), comparison engine (`comparison/`), and exception rules (`exceptions/rules.yaml`) all encode specific real-data findings (documented inline as comments) — same rule as the taxonomy: changes should be grounded in a real case, not a hypothetical one.
- `tracking_control_tower/tests/run_*_live_check.py` and `run_coverage_report.py`/`run_sample_report.py`/`run_state_engine_report.py` are real-data validation scripts, deliberately separate from the curated `test_*.py` unit tests — re-run them (per their own docstrings) after a meaningful change to a carrier adapter, the taxonomy, or the state engine, not just the unit suite.

## Working in MSC_INC.py (legacy)

- **Timestamped output files accumulate in the working directory** (`SIPL_filtered_*.xlsx`, `msc_scraped_results_*.xlsx`, `merged_validation_output_*.xlsx`, `MSC_NonRail_Final_Working_*.xlsx`) every run. The `OLD/` folder holds a long history of prior runs — treat it as an archive, not something to clean up or read for code.
- Column names/order in `expected_cols`, `statuses_to_remove`, `prefixes`, `rail_locations`, and the MSC XPaths are business logic tied to the actual source spreadsheet and live website — don't "simplify" or reorder them without confirming against a real `1RAW.xlsx` sample and the live MSC site, since correctness depends on exact string/positional matches.
- Several blocks are commented out in place (e.g. the optional MSC-only vessel filter around line 108-117, the duplicate-SIPL removal around line 132-139, the old-style file-load block around line 437-440) rather than deleted — this reflects deliberate toggling between run modes, not dead code to remove.
- Because this drives a real browser against a live third-party site with `time.sleep` waits, expect runs to be slow and somewhat flaky; failures per-container are caught and routed to the `Errors` sheet rather than aborting the whole run.
