import math
import re

import streamlit as st


SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
MAX_VALUE_RANGES_PER_BATCH = 500


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
    service_account_info = dict(config.get("gcp_service_account", {}))
    if not service_account_info:
        raise RuntimeError("Service account Google Sheets tidak ditemukan di Streamlit secrets.")

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


def get_sheet_headers(worksheet):
    service = get_sheets_values_service()
    result = service.get(
        spreadsheetId=get_spreadsheet_id(),
        range=f"{quote_worksheet_name(worksheet)}!1:1",
    ).execute()
    return result.get("values", [[]])[0]


def ensure_sheet_headers(worksheet, required_columns):
    headers = list(get_sheet_headers(worksheet))
    missing_columns = [column for column in required_columns if column not in headers]
    if not missing_columns:
        return headers

    headers = headers + missing_columns
    end_col = column_index_to_letter(len(headers))
    get_sheets_values_service().update(
        spreadsheetId=get_spreadsheet_id(),
        range=f"{quote_worksheet_name(worksheet)}!A1:{end_col}1",
        valueInputOption="USER_ENTERED",
        body={"values": [headers]},
    ).execute()
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
        service.batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={
                "valueInputOption": "USER_ENTERED",
                "data": value_ranges[start:start + MAX_VALUE_RANGES_PER_BATCH],
            },
        ).execute()


def append_sheet_rows(worksheet, data):
    if data is None or data.empty:
        return

    headers = ensure_sheet_headers(worksheet, list(data.columns))
    rows = []
    for _, row in data.iterrows():
        rows.append([normalize_cell_for_sheet(row.get(column, "")) for column in headers])

    get_sheets_values_service().append(
        spreadsheetId=get_spreadsheet_id(),
        range=f"{quote_worksheet_name(worksheet)}!A1",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": rows},
    ).execute()
