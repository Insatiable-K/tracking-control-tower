"""
Business rules carried over unchanged from MSC_INC.py and HL Tracking/cleaning.py.

Per FEASIBILITY.md §05, every rule here was verified intentional (not incidental)
and confirmed identical across both carriers' independent implementations.
Do not "clean up" these values without checking the operational impact first.
"""

EXPECTED_COLUMNS = [
    "sipl", "supplier", "port_eta", "rail_eta", "location_eta",
    "ship_to_location", "purchase_location", "container", "vessel",
    "lfd", "sipl_status", "status", "initiated_on", "eta_date",
    "fr_forwarder", "departure_port",
]

DATE_COLUMNS = ["port_eta", "rail_eta", "location_eta", "lfd", "initiated_on", "eta_date"]

STATUSES_TO_REMOVE = [
    "Scheduled for Delivery", "On Hold", "On Exam", "Damaged", "At branch",
    "Carrier Yard", "Prepull", "Freight invoice Needed", "Delivery Pending",
]

VESSEL_PREFIXES = [
    "MSC", "HL", "CMA", "HMM", "WH", "MSK", "MAERSK", "ZIM", "EG", "COSCO", "ESL",
]

RAIL_LOCATIONS = ["Denver", "Kansas City Hub", "SB Chicago"]
