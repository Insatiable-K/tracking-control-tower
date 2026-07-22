# -*- coding: utf-8 -*-
"""
Created on Thu Jul 10 19:33:06 2025

@author: Abhay
"""
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
import undetected_chromedriver as uc
import pandas as pd
from datetime import datetime
import chromedriver_autoinstaller
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
from selenium.webdriver.support.ui import WebDriverWait
from selenium_stealth import stealth

print("\n🚀 Starting the data cleaning and segregation process...\n")

# === 1. LOAD EXCEL FILE ===
try:
    excel_file = 'C:/Users/Abhay/OneDrive - Architectural Surfaces/Documents/Abhay/Tracking Automation/EDA Tracking/1RAW.xlsx'
    xls = pd.ExcelFile(excel_file)
    print("✅ Excel file loaded successfully!")
except FileNotFoundError:
    print("❌ Error: Excel file not found.")
    exit()
except Exception as e:
    print(f"❌ Unexpected error: {e}")
    exit()

# === 2. READ SPECIFIED SHEET ===
sheet_name = 'Sheet 1'
if sheet_name not in xls.sheet_names:
    print(f"❌ Sheet '{sheet_name}' not found.")
    exit()
df = xls.parse(sheet_name)
print(f"✅ Loaded data from sheet: {sheet_name} with {df.shape[0]} rows and {df.shape[1]} columns")


# === 3. RENAME COLUMNS SAFELY ===
expected_cols = [
    'sipl', 'supplier', 'port_eta', 'rail_eta', 'location_eta',
    'ship_to_location', 'purchase_location', 'container', 'vessel',
    'lfd', 'sipl_status', 'status', 'initiated_on', 'eta_date',
    'fr_forwarder', 'departure_port'
]
if len(df.columns) == len(expected_cols):
    df.columns = expected_cols
    print("✅ Columns renamed for clarity.")
else:
    print(f"❌ Unexpected number of columns: {len(df.columns)} instead of {len(expected_cols)}")
    print(f"Columns found: {df.columns}")
    exit()

# === 4. CONVERT DATE COLUMNS TO DATETIME ===
date_columns = ['port_eta', 'rail_eta', 'location_eta', 'lfd', 'initiated_on', 'eta_date']
for col in date_columns:
    df[col] = pd.to_datetime(df[col], errors='coerce', dayfirst=True)
print("✅ Date columns converted to datetime.")


# === 1. CLEAN SIPL COLUMN (lenient) ===
print("\n🔧 Cleaning SIPL column:")
initial_rows = len(df)
df['sipl'] = df['sipl'].astype(str).str.strip().str[:6]
rows_after_sipl = len(df)
print(f"  Rows before: {initial_rows}")
print(f"  Rows after SIPL cleaning (no drops): {rows_after_sipl}")

# === 2. CLEAN CONTAINER NUMBERS (lenient) ===
print("\n🔧 Cleaning container numbers:")
initial_rows = len(df)
df['container'] = df['container'].astype(str).str.strip().str[-11:]
rows_after_container = len(df)
print(f"  Rows before: {initial_rows}")
print(f"  Rows after container cleaning (no drops): {rows_after_container}")

# === 3. FILTER UNWANTED SIPL STATUSES (Case-Insensitive) ===
print("\n🔧 Filtering unwanted SIPL statuses:")
statuses_to_remove = [
    "Scheduled for Delivery", "On Hold", "On Exam", "Damaged", "At branch",
    "Carrier Yard", "Prepull", "Freight invoice Needed", "Delivery Pending"
]
df['sipl_status'] = df['sipl_status'].astype(str).str.strip()
statuses_to_remove_lower = [s.lower() for s in statuses_to_remove]
before_status_filter = len(df)
df = df[~df['sipl_status'].str.lower().isin(statuses_to_remove_lower)].copy()
after_status_filter = len(df)
print(f"  Rows before: {before_status_filter}")
print(f"  Rows after status filter: {after_status_filter}")
print(f"  ❌ Removed by status: {before_status_filter - after_status_filter}")

# === 4. FILTER WHERE 'lfd' IS MISSING ===
print("\n🔧 Filtering rows where 'lfd' is missing:")
before_lfd = len(df)
df = df[df['lfd'].isna()]
after_lfd = len(df)
print(f"  Rows before: {before_lfd}")
print(f"  Rows after LFD filter: {after_lfd}")
print(f"  ❌ Rows removed where 'lfd' present: {before_lfd - after_lfd}")

# === 5. FILTER ONLY VESSEL STARTING WITH 'MSC' (Optional) ===
#if 'vessel' in df.columns:
    #print("\n🔧 Filtering rows with Vessel starting with 'MSC':")
    #df['vessel'] = df['vessel'].astype(str)
    #before_vessel = len(df)
    #df = df[df['vessel'].str.startswith('MSC')]
    #after_vessel = len(df)
    #print(f"  Rows before: {before_vessel}")
    #print(f"  Rows after vessel filter: {after_vessel}")
    #print(f"  ❌ Removed by vessel filter: {before_vessel - after_vessel}")

# === 6. REMOVE DUPLICATE CONTAINER ENTRIES ===
print("\n🔧 Removing duplicate containers (keep first occurrence):")
before_dedup = len(df)
df = df.drop_duplicates(subset=['container'], keep='first')
after_dedup = len(df)
print(f"  Rows before: {before_dedup}")
print(f"  Rows after deduplication: {after_dedup}")
print(f"  ❌ Duplicate rows removed: {before_dedup - after_dedup}")

# === ✅ Final Output ===
print(f"\n✅ Final row count: {len(df)}")


# === 9. REMOVE DUPLICATE SIPL ENTRIES ===
#print("\nRemoving duplicate SIPL entries (keeping first occurrence):")
#before_dup = len(df)
#df = df.drop_duplicates(subset=['sipl'], keep='first')
#after_dup = len(df)
#print(f"  Rows before removing duplicates: {before_dup}")
#print(f"  Rows after removing duplicates: {after_dup}")
#print(f"  Duplicate SIPL rows removed: {before_dup - after_dup}")

# === 10. STANDARDIZE VESSEL NAMES AND SEGREGATE DATA ===
print("\nStandardizing vessel names and segregating data:")
df['vessel'] = df['vessel'].astype(str).str.strip().str.upper()

# No merging of MSK and MAERSK here; treat separately
prefixes = ['MSC', 'HL', 'CMA', 'HMM', 'WH', 'MSK', 'MAERSK', 'ZIM', 'EG', 'COSCO','ESL']

vessel_dfs = {}
for prefix in prefixes:
    vessel_dfs[prefix] = df[df['vessel'].str.startswith(prefix)].copy()
    print(f"  🔹 {prefix} vessels: {len(vessel_dfs[prefix])} rows")

pattern = '^(' + '|'.join(prefixes) + ')'
df_mismatched = df[~df['vessel'].str.match(pattern)].copy()
print(f"  🔹 Mismatched vessels: {len(df_mismatched)} rows")

# === 11. SAVE TO EXCEL WITH MULTIPLE SHEETS ===
print("\nSaving segregated data to Excel file...")
timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
output_filename = f"SIPL_filtered_{timestamp}.xlsx"

with pd.ExcelWriter(output_filename, engine='xlsxwriter') as writer:
    for prefix, vessel_df in vessel_dfs.items():
        vessel_df.to_excel(writer, sheet_name=prefix[:31], index=False)  # Sheet names max 31 chars
    df_mismatched.to_excel(writer, sheet_name='mismatched', index=False)

print(f"✅ Final filtered and segregated data saved as: {output_filename}")

print("\n🎉 Data cleaning and segregation process completed successfully!\n")

# === SETUP SELENIUM DRIVER ===




print("🚀 Setting up Selenium WebDriver...")

# === CONFIG ===
HEADLESS = False  # Set to True to run without opening a browser

# --- Auto install correct ChromeDriver ---
chromedriver_autoinstaller.install()

# --- Chrome Options ---
options = Options()
options.add_experimental_option("excludeSwitches", ["enable-automation"])
options.add_experimental_option("useAutomationExtension", False)
options.add_argument("--disable-blink-features=AutomationControlled")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--disable-gpu")
options.add_argument("--log-level=3")

if HEADLESS:
    options.add_argument("--headless=new")

# --- Optional: set realistic User-Agent ---
options.add_argument(
    "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Safari/537.36"
)

# --- Merge capabilities (instead of desired_capabilities argument) ---
caps = DesiredCapabilities.CHROME.copy()
caps["pageLoadStrategy"] = "eager"
options.set_capability("pageLoadStrategy", caps["pageLoadStrategy"])

# --- Start WebDriver (no desired_capabilities argument) ---
driver = webdriver.Chrome(options=options)

# --- Remove webdriver flag and make browser look normal ---
driver.execute_cdp_cmd(
    "Page.addScriptToEvaluateOnNewDocument",
    {
        "source": """
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5],
            });
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en'],
            });
        """
    },
)

# --- Apply Stealth Mode ---
stealth(
    driver,
    languages=["en-US", "en"],
    vendor="Google Inc.",
    platform="Win32",
    webgl_vendor="Intel Inc.",
    renderer="Intel Iris OpenGL Engine",
    fix_hairline=True,
)

wait = WebDriverWait(driver, 20)

# === OPEN MSC SITE ===
print("🌐 Opening MSC tracking page...")
driver.get("https://www.msc.com/en/track-a-shipment")
print("✅ MSC tracking page loaded in stealth mode.")



try:
    cookie_button_xpath = '//*[@id="onetrust-accept-btn-handler"]'
    wait.until(EC.element_to_be_clickable((By.XPATH, cookie_button_xpath))).click()
    print("🍪 Accepted cookies.")
except:
    print("🍪 No cookie prompt found or already accepted.")

# === TRACKING FUNCTION ===
def track_container_and_parse(container):
    try:
        input_box = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '#trackingNumber')))
        input_box.clear()
        input_box.send_keys(container)
        input_box.send_keys(Keys.RETURN)
        time.sleep(6)

        tracking_section_xpath = "/html/body/div[1]/div[1]/div/div[3]/div/div/div/div[1]/div/div/div[3]/div/div/div[2]"
        pod_eta_xpath = "/html/body/div[1]/div[1]/div/div[3]/div/div/div/div[1]/div/div/div[3]/div/div/div[1]/div/div[4]/div/div/div/span[2]"

        section = wait.until(EC.presence_of_element_located((By.XPATH, tracking_section_xpath)))
        raw_text = section.text.strip()

        try:
            pod_eta = wait.until(EC.presence_of_element_located((By.XPATH, pod_eta_xpath))).text.strip()
        except:
            pod_eta = ""

        scraped_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        lines = raw_text.split('\n')
        records = []
        block = []

        for line in lines:
            if line.strip():
                block.append(line.strip())
                if len(block) == 5:
                    records.append({
                        "Container #": container,
                        "Date": block[0],
                        "Location": block[1],
                        "Description": block[2],
                        "Vessel Info": block[3],
                        "Facility": block[4],
                        "POD ETA": pod_eta,
                        "Scraped At": scraped_at
                    })
                    block = []

        return records
    except Exception as e:
        return [{"Container #": container, "Error": str(e)}]

# === DATA PREP: Filter for MSC Containers ===

# Assuming `df` is already cleaned, filtered (e.g. lfd blank), and deduplicated

msc_df = df[df['vessel'].str.startswith('MSC')].copy()
#msc_containers = msc_df['container'].dropna().unique().tolist()
msc_containers = msc_df['container'].tolist()
print(f"🚛 Starting scrape for {len(msc_containers)} MSC containers...\n")

all_results = []
error_results = []

for i, container in enumerate(msc_containers, 1):
    print(f"\n🔍 Scraping container {i}/{len(msc_containers)}: {container}")
    
    start_time = time.time()  # Start timer
    
    records = track_container_and_parse(container)
    
    end_time = time.time()  # End timer
    duration = round(end_time - start_time, 2)

    if "Error" in records[0]:
        error_results.append(records[0])
        print(f"❌ Error for {container}: {records[0]['Error']}")
    else:
        all_results.extend(records)
        print(f"✅ Scraped {len(records)} records for container {container}")
    
    print(f"⏱️ Time taken: {duration} seconds")

    time.sleep(2)  # Small delay for respect to server



# === CLEANUP DRIVER ===
driver.quit()



# === CONVERT SCRAPED LIST TO DATAFRAME ===
scraped_df = pd.DataFrame(all_results)

print("✅ Scraped data converted to DataFrame.")
print(f"🔹 Total rows: {len(scraped_df)}")
print("🔹 Sample:")
print(scraped_df.head())

# === CLEAN COLUMN NAMES ===
scraped_df.columns = scraped_df.columns.str.strip().str.lower().str.replace(" ", "_")

# Rename for consistency
scraped_df.rename(columns={
    'container_#': 'container',
    'pod_eta': 'pod_eta_date'
}, inplace=True)

# === HANDLE EMPTY DATAFRAME ===
if scraped_df.empty:
    print("⚠️ No valid tracking data found. Skipping export.")
    exit()

# === FORMAT DATE STRINGS ===
def pad_date_str(date_str):
    if pd.isna(date_str) or date_str == '':
        return date_str
    parts = date_str.split('-')
    if len(parts) != 3:
        return date_str
    day, month, year = parts
    day = day.zfill(2)
    month = month.zfill(2)
    return f"{day}-{month}-{year}"

# Pad and convert dates
scraped_df['date'] = scraped_df['date'].apply(pad_date_str)
scraped_df['pod_eta_date'] = scraped_df['pod_eta_date'].apply(pad_date_str)

scraped_df['date'] = pd.to_datetime(scraped_df['date'], dayfirst=True, errors='coerce')
scraped_df['pod_eta_date'] = pd.to_datetime(scraped_df['pod_eta_date'], dayfirst=True, errors='coerce')

scraped_df['date'] = scraped_df['date'].dt.strftime('%m-%d-%Y')
scraped_df['pod_eta_date'] = scraped_df['pod_eta_date'].dt.strftime('%m-%d-%Y')

print("✅ Converted 'date' and 'pod_eta_date' to MM-DD-YYYY format.")

# === REMOVE JUNK UI SCRAPED ROWS ===
bad_descriptions = [
    "Description",
    "Empty/Laden/Vessel/Voyage",
    "Equipment handling facility name"
]

scraped_df = scraped_df[
    ~(scraped_df['description'].isin(bad_descriptions)) &
    ~(scraped_df['vessel_info'].isin(bad_descriptions)) &
    ~(scraped_df['facility'].isin(bad_descriptions))
].reset_index(drop=True)

print("✅ Removed non-data rows (UI junk rows).")
print(f"📉 Remaining rows: {len(scraped_df)}")
print("🔹 Sample cleaned data:")
print(scraped_df.head())

# === REORDER COLUMNS FOR OUTPUT ===
scraped_df = scraped_df[[
    'container', 'date', 'location', 'description', 'vessel_info',
    'facility', 'pod_eta_date', 'scraped_at'
]]

print("✅ Columns reordered.")
print("🔹 Final column names:", scraped_df.columns.tolist())

# === CREATE ERROR DATAFRAME ===
if error_results:
    error_df = pd.DataFrame(error_results)
else:
    error_df = pd.DataFrame(columns=["Container #", "Error"])

# === EXPORT TO EXCEL ===
timestamp_str = datetime.now().strftime("%m-%d-%Y_%H-%M-%S")
excel_filename = f"msc_scraped_results_{timestamp_str}.xlsx"

with pd.ExcelWriter(excel_filename, engine='openpyxl') as writer:
    scraped_df.to_excel(writer, sheet_name='Clean Data', index=False)
    error_df.to_excel(writer, sheet_name='Errors', index=False)

print(f"✅ Exported clean and error data to Excel: {excel_filename}")


import pandas as pd
from pandas import ExcelWriter

# --- Step 1: Load scraped data and trim containers (older style) ---

#msc_scraped_file = 'msc_scraped_results_07-22-2025_15-33-35.xlsx'
#msc_scraped_df = pd.read_excel(msc_scraped_file, sheet_name='Clean Data')


print("✅ MSC scraped data loaded!")
print("🔹 Shape:", scraped_df.shape)

scraped_df['container'] = scraped_df['container'].astype(str).str[-11:]
vessel_dfs['MSC']['container'] = vessel_dfs['MSC']['container'].astype(str).str[-11:]

# --- Step 2: Merge raw with scraped using inner join on 'container' ---

# Step 1: Inner merge to get matched containers
merged_df = pd.merge(
    vessel_dfs['MSC'],
    scraped_df,
    on='container',
    how='inner',
    suffixes=('_1raw', '_scraped')
)
print(f"✅ Merged raw MSC data with scraped updates. Rows: {len(merged_df)}")

# Step 2: Find containers in raw MSC data but missing in scraped_df
missing_scraped_df = vessel_dfs['MSC'][~vessel_dfs['MSC']['container'].isin(scraped_df['container'])]
print(f"⚠️ Containers in raw MSC data missing from scraped updates: {len(missing_scraped_df)}")

# Step 3: Export both matched and missing data to Excel
timestamp_str = datetime.now().strftime("%m-%d-%Y_%H-%M-%S")
output_file = f'merged_validation_output_{timestamp_str}.xlsx'
with pd.ExcelWriter(output_file, engine='xlsxwriter') as writer:
    merged_df.to_excel(writer, sheet_name='Matched_Containers', index=False)
    missing_scraped_df.to_excel(writer, sheet_name='Missing_From_Scraped', index=False)

print(f"📁 Exported matched and missing container info to: {output_file}")

# --- Step 3: Filter after merge on scraped 'description' ---

target_descriptions = [
    "Estimated Time of Arrival",
    "Import Discharged from Vessel",
    "Import Rail Departure",
    "Import Unloaded from Rail"
]

filtered_df = merged_df[merged_df['description'].isin(target_descriptions)].copy()

print(f"✅ Filtered merged data on description. Rows: {len(filtered_df)}")

# --- Step 4: Prepare date columns for processing ---

# Convert relevant date columns to datetime (coerce errors)
for col in ['port_eta', 'date', 'pod_eta_date', 'scraped_at']:
    filtered_df[col] = pd.to_datetime(filtered_df[col], errors='coerce')

# --- Step 5: Define your best row selection logic (adapted) ---

def select_best_row(group):
    # Step 1: Prioritize ETA rows
    eta_rows = group[group['description'] == 'Estimated Time of Arrival']
    if not eta_rows.empty:
        # Pick the ETA row with the latest pod_eta_date
        filtered = eta_rows[eta_rows['pod_eta_date'].notna()]
        if not filtered.empty:
            return filtered.sort_values(['pod_eta_date', 'scraped_at'], ascending=[False, False]).iloc[0]
        else:
            return eta_rows.sort_values(['date', 'scraped_at'], ascending=[False, False]).iloc[0]

    # Step 2: Fallback to Import Discharged if no ETA
    import_rows = group[group['description'] == 'Import Discharged from Vessel']
    if not import_rows.empty:
        filtered = import_rows[import_rows['pod_eta_date'].notna()]
        if not filtered.empty:
            return filtered.sort_values(['pod_eta_date', 'scraped_at'], ascending=[False, False]).iloc[0]
        else:
            return import_rows.sort_values(['date', 'scraped_at'], ascending=[False, False]).iloc[0]

    # Step 3: Fallback to any row with pod_eta_date
    filtered = group[group['pod_eta_date'].notna()]
    if not filtered.empty:
        return filtered.sort_values(['pod_eta_date', 'scraped_at'], ascending=[False, False]).iloc[0]

    # Step 4: Absolute fallback to latest date
    return group.sort_values(['date', 'scraped_at'], ascending=[False, False]).iloc[0]

# --- Step 6: Apply selection on container groups ---

final_df = filtered_df.groupby('container', group_keys=False).apply(select_best_row).reset_index(drop=True)

print(f"✅ Applied best row selection per container. Rows now: {len(final_df)}")

# --- Step 7: Format date columns to MM-DD-YYYY strings ---

for col in ['port_eta', 'date', 'pod_eta_date']:
    final_df[col] = pd.to_datetime(final_df[col], errors='coerce').dt.strftime('%m-%d-%Y')

# Rename date to date for consistency downstream
final_df.rename(columns={'date': 'date'}, inplace=True)

# --- Step 8: ETA Changed logic ---


def compare_eta(row):
    port_eta = row['port_eta']
    date = row['date']
    pod_eta = row['pod_eta_date']
    
    # Priority 1: Compare with pod_eta if available
    if pd.notna(port_eta) and pd.notna(pod_eta):
        return "No" if port_eta == pod_eta else "Yes"
    
    # Priority 2: Compare with date if pod_eta is missing
    if pd.notna(port_eta) and pd.isna(pod_eta) and pd.notna(date):
        return "No" if port_eta == date else "Yes"
    
    # Error: if both pod_eta and date are missing
    if pd.notna(port_eta) and pd.isna(pod_eta) and pd.isna(date):
        return "Error"
    
    # Fallback error for unexpected missing combinations
    return "Error"

# Apply the function to each row in the DataFrame
final_df['eta_changed'] = final_df.apply(compare_eta, axis=1)

# --- Step 9: Vessel Changed logic ---

def extract_after_last_hyphen(val):
    if pd.isna(val):
        return val
    parts = str(val).split('-')
    return parts[-1] if len(parts) > 1 else val

final_df['vessel_cleaned'] = final_df['vessel'].apply(extract_after_last_hyphen)
final_df['vessel_info_cleaned'] = final_df['vessel_info'].apply(extract_after_last_hyphen)

def compare_vessels(vessel, vessel_info):
    if pd.isna(vessel) or pd.isna(vessel_info):
        return 'Error'
    return 'No' if vessel == vessel_info else 'Yes'

final_df['vessel_changed'] = final_df.apply(
    lambda r: compare_vessels(r['vessel_cleaned'], r['vessel_info_cleaned']),
    axis=1
)


# --- Step 11: Split rail vs non-rail ---

rail_locations = ["Denver", "Kansas City Hub", "SB Chicago"]

rail_df = final_df[final_df['ship_to_location'].isin(rail_locations)].copy()
non_rail_df = final_df[~final_df['ship_to_location'].isin(rail_locations)].copy()

print(f"✅ Rail rows: {len(rail_df)}, Non-rail rows: {len(non_rail_df)}")

# --- Step 12: Date conversions & formatting for rail and non-rail ---

date_cols = ['port_eta', 'date', 'pod_eta_date']

for df_ in [rail_df, non_rail_df]:
    for col in date_cols:
        df_[col] = pd.to_datetime(df_[col], errors='coerce').dt.strftime('%m-%d-%Y')

print("✅ Date columns formatted to MM-DD-YYYY in rail and non-rail data.")
# --- Step 10: Prepare filtered output DataFrame with updates ---

# Define the output columns (with the new logic column inserted before 'vessel_changed')
columns_needed = [
    'sipl', 'port_eta', 'date', 'pod_eta_date', 'container', 'vessel', 'vessel_info',
    'location', 'eta_changed', 'vessel_changed'
]

# Add the new column based on logic before selecting final columns
final_df['eta_or_vessel_changed'] = final_df.apply(
    lambda row: 'Y' if row['eta_changed'] == 'Y' or row['vessel_changed'] == 'Y' else 'N',
    axis=1
)

# Reorder columns to insert the new column before 'vessel_changed'
columns_final = [
    'sipl', 'port_eta', 'date', 'pod_eta_date', 'container', 'vessel', 'vessel_info',
    'location', 'eta_changed','vessel_changed', 'eta_or_vessel_changed'
]

# Prepare the final DataFrame


# --- Prepare the final DataFrame ---
# --- Prepare the final DataFrame ---
output_df = non_rail_df[columns_needed].copy()

# --- Compute updated_eta and updated_vessel first ---
def get_updated_eta(row):
    if row['eta_changed'] == 'Yes':
        if pd.notna(row['pod_eta_date']):
            return row['pod_eta_date']
        elif pd.notna(row['date']):
            return row['date']
        else:
            return 'NA'
    return 'NA'

def get_updated_vessel(row):
    if row['vessel_changed'] == 'Yes':
        return row['vessel_info'] if pd.notna(row['vessel_info']) else 'NA'
    return 'NA'

output_df['updated_eta'] = output_df.apply(get_updated_eta, axis=1)
output_df['updated_vessel'] = output_df.apply(get_updated_vessel, axis=1)

# --- Add 'eta_or_vessel_changed' column AFTER 'vessel_changed' ---
output_df['eta_or_vessel_changed'] = output_df.apply(
    lambda row: 'Yes' if row['eta_changed'] == 'Yes' or row['vessel_changed'] == 'Yes' else 'No',
    axis=1
)

# Reorder columns to place the new column AFTER 'vessel_changed'
cols = output_df.columns.tolist()
if 'eta_or_vessel_changed' in cols:
    # Remove it and reinsert after 'vessel_changed'
    cols.remove('eta_or_vessel_changed')
    idx = cols.index('vessel_changed') + 1
    cols.insert(idx, 'eta_or_vessel_changed')
    output_df = output_df[cols]

print("✅ All columns prepared with 'eta_or_vessel_changed' added after 'vessel_changed'.")




# --- Step 13: Save results to Excel ---

# Define the final output Excel file
timestamp_str = datetime.now().strftime("%m-%d-%Y_%H-%M-%S")
output_excel_path = f"MSC_NonRail_Final_Working_{timestamp_str}.xlsx"

# Write all DataFrames to the final Excel file in separate sheets
with ExcelWriter(output_excel_path, engine='xlsxwriter') as writer:
    non_rail_df.to_excel(writer, sheet_name='non_rail_final', index=False)
    output_df.to_excel(writer, sheet_name='MSC Working', index=False)
    missing_scraped_df.to_excel(writer, sheet_name='Missing_From_Scraped', index=False)
    scraped_df.to_excel(writer, sheet_name='Clean Data', index=False)
    error_df.to_excel(writer, sheet_name='Errors', index=False)

print(f"✅ Final Excel file saved with all sheets: {output_excel_path}")


























