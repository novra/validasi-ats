import math
import re
import time

import streamlit as st


SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
MAX_VALUE_RANGES_PER_BATCH = 500
SHEETS_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
SHEETS_RETRY_DELAYS = [1, 2, 4, 8]


def normalize_cell_for_sheet(value):
    if value is None:
        return ""
    try:
        if isinstance(value, float) and math.isnan(value):
            return ""
    except TypeError:
        pass
    text = str(value)
    if text.strip().lower() in {"nan", "none", "<na>"}:
        return ""
    return text


def column_index_to_letter(index):
    letters = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def quote_worksheet_name(worksheet):
    return f"'{str(worksheet).replace(chr(39), chr(39) + chr(39))}'"


def get_gsheets_secret_config():
    try:
        return st.secrets["connections"]["gsheets"]
    except Exception as exc:
        raise RuntimeError("Konfigurasi connections.gsheets tidak ditemukan di Streamlit secrets.") from exc


def as_plain_dict(value):
    if value is None:
        return {}
    try:
        return dict(value)
    except Exception:
        return {}


def get_nested_secret(*keys):
    current = st.secrets
    for key in keys:
        try:
            current = current[key]
        except Exception:
            return {}
    return as_plain_dict(current)


def get_service_account_info(config):
    candidate_paths = [
        ("connections", "gsheets", "gcp_service_account"),
        ("connections", "gsheets", "service_account"),
        ("connections", "gsheets", "credentials"),
        ("gcp_service_account",),
        ("google_service_account",),
        ("service_account",),
    ]

    for path in candidate_paths:
        candidate = get_nested_secret(*path)
        if candidate.get("type") == "service_account" and candidate.get("client_email"):
            return candidate

    direct_config = as_plain_dict(config)
    if direct_config.get("type") == "service_account" and direct_config.get("client_email"):
        return direct_config

    return {}


@st.cache_resource
def get_sheets_values_service():
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise RuntimeError(
            "Dependency Google Sheets API belum tersedia. "
            "Pastikan google-api-python-client dan google-auth terinstall."
        ) from exc

    config = get_gsheets_secret_config()
    service_account_info = get_service_account_info(config)
    if not service_account_info:
        raise RuntimeError(
            "Service account Google Sheets tidak ditemukan di Streamlit secrets. "
            "Untuk update per-row, tambahkan blok [connections.gsheets.gcp_service_account] "
            "dari JSON service account dan share Google Sheet ke client_email tersebut sebagai Editor."
        )

    credentials = service_account.Credentials.from_service_account_info(
        service_account_info,
        scopes=SCOPES,
    )
    return build("sheets", "v4", credentials=credentials, cache_discovery=False).spreadsheets().values()


def get_spreadsheet_id():
    config = get_gsheets_secret_config()
    spreadsheet_id = config.get("spreadsheet")
    if not spreadsheet_id:
        raise RuntimeError("Spreadsheet ID tidak ditemukan di Streamlit secrets.")
    spreadsheet_id = str(spreadsheet_id).strip()
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", spreadsheet_id)
    return match.group(1) if match else spreadsheet_id


def get_google_api_status_code(error):
    response = getattr(error, "resp", None)
    status = getattr(response, "status", None)
    try:
        return int(status)
    except (TypeError, ValueError):
        return None


def execute_google_request_with_retry(request):
    last_error = None
    for attempt_index, delay in enumerate([0] + SHEETS_RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        try:
            return request().execute()
        except Exception as exc:
            last_error = exc
            status_code = get_google_api_status_code(exc)
            if (
                status_code not in SHEETS_RETRYABLE_STATUS_CODES
                or attempt_index >= len(SHEETS_RETRY_DELAYS)
            ):
                raise

    raise last_error


@st.cache_data(ttl=300)
def get_sheet_headers(worksheet):
    service = get_sheets_values_service()
    spreadsheet_id = get_spreadsheet_id()
    result = execute_google_request_with_retry(
        lambda: service.get(
            spreadsheetId=spreadsheet_id,
            range=f"{quote_worksheet_name(worksheet)}!1:1",
        )
    )
    return result.get("values", [[]])[0]


def ensure_sheet_headers(worksheet, required_columns):
    headers = list(get_sheet_headers(worksheet))
    missing_columns = [column for column in required_columns if column not in headers]
    if not missing_columns:
        return headers

    headers = headers + missing_columns
    end_col = column_index_to_letter(len(headers))
    service = get_sheets_values_service()
    spreadsheet_id = get_spreadsheet_id()
    execute_google_request_with_retry(
        lambda: service.update(
            spreadsheetId=spreadsheet_id,
            range=f"{quote_worksheet_name(worksheet)}!A1:{end_col}1",
            valueInputOption="USER_ENTERED",
            body={"values": [headers]},
        )
    )
    get_sheet_headers.clear()
    return headers


def update_sheet_cells(worksheet, data, row_indices, columns):
    row_indices = [] if row_indices is None else list(row_indices)
    columns = [] if columns is None else list(columns)
    if not row_indices or not columns:
        return

    headers = ensure_sheet_headers(worksheet, list(data.columns))
    header_positions = {header: index + 1 for index, header in enumerate(headers)}
    value_ranges = []

    for row_index in row_indices:
        if row_index not in data.index:
            raise ValueError(f"Baris {row_index + 1} tidak ditemukan saat update per-cell.")
        sheet_row = row_index + 2
        for column in columns:
            if column not in header_positions:
                raise ValueError(f"Kolom {column} tidak ditemukan di header Google Sheet.")
            col_letter = column_index_to_letter(header_positions[column])
            value_ranges.append(
                {
                    "range": f"{quote_worksheet_name(worksheet)}!{col_letter}{sheet_row}",
                    "values": [[normalize_cell_for_sheet(data.at[row_index, column])]],
                }
            )

    service = get_sheets_values_service()
    spreadsheet_id = get_spreadsheet_id()
    for start in range(0, len(value_ranges), MAX_VALUE_RANGES_PER_BATCH):
        execute_google_request_with_retry(
            lambda start=start: service.batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={
                    "valueInputOption": "USER_ENTERED",
                    "data": value_ranges[start:start + MAX_VALUE_RANGES_PER_BATCH],
                },
            )
        )


def is_missing_service_account_error(error):
    return "Service account Google Sheets tidak ditemukan" in str(error)


def update_sheet_cells_with_full_update_fallback(conn, worksheet, data, row_indices, columns):
    try:
        update_sheet_cells(worksheet, data, row_indices, columns)
        return "row"
    except RuntimeError as exc:
        if not is_missing_service_account_error(exc):
            raise
        st.warning(
            "Service account untuk update per-row belum tersedia. "
            "Aplikasi memakai fallback update penuh sementara; tambahkan "
            "[connections.gsheets.gcp_service_account] agar update aman per-row aktif."
        )
        conn.update(worksheet=worksheet, data=data)
        return "full"


def append_sheet_rows(worksheet, data):
    if data is None or data.empty:
        return

    headers = ensure_sheet_headers(worksheet, list(data.columns))
    rows = []
    for _, row in data.iterrows():
        rows.append([normalize_cell_for_sheet(row.get(column, "")) for column in headers])

    service = get_sheets_values_service()
    spreadsheet_id = get_spreadsheet_id()
    execute_google_request_with_retry(
        lambda: service.append(
            spreadsheetId=spreadsheet_id,
            range=f"{quote_worksheet_name(worksheet)}!A1",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": rows},
        )
    )
