TARGET_URL = "https://pro.52wmb.com"
PRO_LOGIN_URL = "https://pro.52wmb.com/user/login?redirect=%2FWorkbenches"
DETAIL_COUNTRY = "Vietnam"
DETAIL_SUBMODE = "multi"
INTERMEDIATE_FORMAT = "csv"
DETAIL_MAX_PAGES = None
SAVE_EXCEL = False
OUTPUT_DIR = r"D:\datacenter\bronze\2026"

USERNAME = "kay.nguyen@stsgroup.org.vn"
PASSWORD = "khanh009500"
TRANSACTIONS_BATCH = [
    {'name': '52_Export_Full', 'hs_code': '52', 'data_type': 'Export data', 'start_date': '2026-01-01', 'end_date': '2026-05-31', 'buyer': '', 'expected': 0},
    {'name': '54_Export_Full', 'hs_code': '54', 'data_type': 'Export data', 'start_date': '2026-01-01', 'end_date': '2026-05-31', 'buyer': '', 'expected': 0},
    {'name': '53_Export_New', 'hs_code': '53', 'data_type': 'Export data', 'start_date': '2026-04-01', 'end_date': '2026-05-31', 'buyer': '', 'expected': 0},
    {'name': '55_Export_New', 'hs_code': '55', 'data_type': 'Export data', 'start_date': '2026-04-01', 'end_date': '2026-05-31', 'buyer': '', 'expected': 0},
]
