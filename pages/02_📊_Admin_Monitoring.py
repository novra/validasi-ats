import streamlit as st
import pandas as pd
from io import BytesIO
from streamlit_gsheets import GSheetsConnection
import plotly.graph_objects as go
import plotly.express as px
import os
import requests
import time
from auth_config import AUTHORIZED_USERS, ADMIN_CREDENTIALS, AUTHORIZED_ADMINS, REPLACEMENT_ADMINS, SYNTHETIC_DATA_ADMINS
from sheet_lock import get_sheet_write_lock
from synthetic_ats_data import generate_synthetic_ats_cases, get_synthetic_balance_summary

# --- KONFIGURASI HALAMAN ---
st.set_page_config(layout="wide", page_title="Admin Monitoring Pelabelan")

# --- KONEKSI KE GOOGLE SHEETS ---
conn = st.connection("gsheets", type=GSheetsConnection)

SHEET_COLUMNS = ['instruction_ats', 'input', 'output_ats', 'validator', 'status']
MIN_NONEMPTY_INPUT_ROWS = 1
MAX_SHEET_CELL_CHARS = 50000
LENGTH_LIMIT_COLUMNS = ['instruction_ats', 'output_ats']
PROBLEM_KEYWORDS_LABEL = "sama, serupa, double, seperti sebelumnya, atau terlalu banyak"
PROBLEM_PATTERN = r"\b(?:sama|serupa|double)\b|seperti\s+sebelumnya|terlalu\s+banyak"

def normalize_cell(value):
    if pd.isna(value):
        return ''

    text = str(value).strip()
    if text.lower() in {'nan', 'none', '<na>'}:
        return ''
    return text

def remember_loaded_sheet(df):
    if df is not None and not df.empty:
        st.session_state['admin_last_good_sheet_df'] = df.copy()
        st.session_state['admin_last_good_sheet_at'] = time.strftime("%Y-%m-%d %H:%M:%S")

def read_sheet_with_retry(attempts=3, delay_seconds=0.5):
    last_error = None
    last_df = None

    for _ in range(attempts):
        try:
            last_df = conn.read(worksheet="Sheet1", ttl=0)
            if last_df is not None and not last_df.empty:
                return last_df, None
        except Exception as e:
            last_error = e
        time.sleep(delay_seconds)

    return last_df, last_error

def load_data():
    last_df, last_error = read_sheet_with_retry()
    if last_df is not None and not last_df.empty:
        remember_loaded_sheet(last_df)
        return last_df

    cached_df = st.session_state.get('admin_last_good_sheet_df')
    if cached_df is not None and not cached_df.empty:
        cached_at = st.session_state.get('admin_last_good_sheet_at', 'sebelumnya')
        if last_error:
            st.warning(
                f"Google Sheet sedang tidak dapat dibaca ({last_error}). "
                f"Menampilkan data terakhir yang berhasil dimuat pada {cached_at}."
            )
        else:
            st.warning(
                "Google Sheet terbaca kosong sesaat. "
                f"Menampilkan data terakhir yang berhasil dimuat pada {cached_at}."
            )
        return cached_df.copy()

    if last_error:
        st.error(f"Error membaca Google Sheet: {last_error}")
    return last_df

def prepare_sheet_data(df):
    sheet_df = df.copy()

    for col in SHEET_COLUMNS:
        if col not in sheet_df.columns:
            sheet_df[col] = ''
        sheet_df[col] = sheet_df[col].map(normalize_cell)

    legacy_cols = ['instruksi_ats', 'nama_validator']
    sheet_df = sheet_df.drop(columns=[col for col in legacy_cols if col in sheet_df.columns])

    ordered_cols = SHEET_COLUMNS + [col for col in sheet_df.columns if col not in SHEET_COLUMNS]
    return sheet_df[ordered_cols]

def row_has_problem_label(row):
    instruction = normalize_cell(row.get('instruction_ats', ''))
    output = normalize_cell(row.get('output_ats', ''))
    return (
        pd.Series([instruction]).str.contains(PROBLEM_PATTERN, case=False, na=False, regex=True).iloc[0]
        or pd.Series([output]).str.contains(PROBLEM_PATTERN, case=False, na=False, regex=True).iloc[0]
    )

def get_ats_length_violations(df, changed_indices):
    violations = []
    for index in changed_indices:
        if index not in df.index:
            continue
        for col in LENGTH_LIMIT_COLUMNS:
            value_length = len(normalize_cell(df.at[index, col]))
            if value_length > MAX_SHEET_CELL_CHARS:
                violations.append((index + 1, col, value_length))
    return violations

def merge_with_latest_sheet(df, changed_indices, changed_columns, expected_values=None):
    latest_df = conn.read(worksheet="Sheet1", ttl=0)
    if latest_df is None or latest_df.empty:
        raise ValueError("Google Sheet terbaru kosong atau tidak dapat dibaca.")

    latest_data = prepare_sheet_data(latest_df)
    pending_data = prepare_sheet_data(df)

    if len(latest_data) < len(pending_data):
        raise ValueError(
            f"Jumlah baris Google Sheet terbaru ({len(latest_data)}) lebih sedikit dari data lokal ({len(pending_data)})."
        )

    if len(latest_data) > len(pending_data):
        for col in pending_data.columns:
            if col not in latest_data.columns:
                latest_data[col] = ''

    for index in changed_indices:
        if index not in pending_data.index or index not in latest_data.index:
            raise ValueError(f"Baris {index + 1} tidak ditemukan saat sinkronisasi.")

        if expected_values:
            for col, allowed_values in expected_values.items():
                if col not in latest_data.columns:
                    latest_data[col] = ''
                if isinstance(allowed_values, dict):
                    allowed_values = allowed_values.get(index, '')
                if not isinstance(allowed_values, (list, tuple, set)):
                    allowed_values = [allowed_values]
                latest_value = normalize_cell(latest_data.at[index, col])
                allowed_values = {normalize_cell(value) for value in allowed_values}
                if latest_value not in allowed_values:
                    raise ValueError(
                        f"Baris {index + 1} sudah berubah di Google Sheet. Muat ulang halaman sebelum melakukan replace."
                    )

        for col in changed_columns:
            if col not in pending_data.columns:
                raise ValueError(f"Kolom {col} tidak ditemukan saat sinkronisasi.")
            if col not in latest_data.columns:
                latest_data[col] = ''
            latest_data.at[index, col] = pending_data.at[index, col]

    return latest_data

def update_data(df, changed_indices=None, changed_columns=None, expected_values=None):
    with get_sheet_write_lock():
        return update_data_unlocked(df, changed_indices, changed_columns, expected_values)

def update_data_unlocked(df, changed_indices=None, changed_columns=None, expected_values=None):
    try:
        expected_rows = st.session_state.get('admin_loaded_sheet_rows')
        if df is None or df.empty:
            st.error("Update dibatalkan: data yang akan ditulis kosong.")
            return False

        if changed_indices is None or changed_columns is None:
            st.error("Update dibatalkan: perubahan baris/kolom tidak diketahui.")
            return False

        sheet_data = merge_with_latest_sheet(df, changed_indices, changed_columns, expected_values)
        nonempty_input_rows = sheet_data['input'].fillna('').astype(str).str.strip().ne('').sum()

        if nonempty_input_rows < MIN_NONEMPTY_INPUT_ROWS:
            st.error("Update dibatalkan: kolom input terbaca kosong. Muat ulang data sebelum mencoba lagi.")
            return False

        if expected_rows is not None and len(sheet_data) < expected_rows:
            st.error(
                f"Update dibatalkan: jumlah baris turun dari {expected_rows} ke {len(sheet_data)}. "
                "Ini mencegah Google Sheet tertimpa oleh data hasil filter."
            )
            return False

        length_violations = get_ats_length_violations(sheet_data, changed_indices)
        if length_violations:
            details = ", ".join(
                f"baris {row} kolom {col}: {length:,} karakter"
                for row, col, length in length_violations
            )
            st.error(
                f"Update dibatalkan: {details}. "
                f"Batas maksimal Google Sheets adalah {MAX_SHEET_CELL_CHARS:,} karakter per cell."
            )
            return False

        conn.update(worksheet="Sheet1", data=sheet_data)
        st.session_state['admin_loaded_sheet_rows'] = len(sheet_data)
        return True
    except Exception as e:
        st.error(f"Gagal update Google Sheet: {e}")
        return False

def replace_problem_inputs(selected_indices, replacement_input, expected_values):
    try:
        with get_sheet_write_lock():
            expected_rows = st.session_state.get('admin_loaded_sheet_rows')
            latest_df, latest_error = read_sheet_with_retry()
            if latest_df is None or latest_df.empty:
                if latest_error:
                    st.error(f"Replace dibatalkan: Google Sheet terbaru tidak dapat dibaca ({latest_error}).")
                else:
                    st.error("Replace dibatalkan: Google Sheet terbaru kosong atau tidak dapat dibaca.")
                return False

            normalized_replacement_input = replacement_input.strip()
            replacement_input_length = len(normalize_cell(normalized_replacement_input))
            if replacement_input_length > MAX_SHEET_CELL_CHARS:
                st.error(
                    f"Replace dibatalkan: input baru berisi {replacement_input_length:,} karakter. "
                    f"Batas maksimal Google Sheets adalah {MAX_SHEET_CELL_CHARS:,} karakter per cell."
                )
                return False

            latest_data = prepare_sheet_data(latest_df)
            if expected_rows is not None and len(latest_data) < expected_rows:
                st.error(
                    f"Replace dibatalkan: jumlah baris turun dari {expected_rows} ke {len(latest_data)}. "
                    "Muat ulang data sebelum mencoba lagi."
                )
                return False

            for index in selected_indices:
                if index not in latest_data.index:
                    st.error(f"Replace dibatalkan: baris {index + 1} tidak ditemukan di Google Sheet terbaru.")
                    return False

                for col, expected_by_row in expected_values.items():
                    if col not in latest_data.columns:
                        latest_data[col] = ''
                    latest_value = normalize_cell(latest_data.at[index, col])
                    expected_value = normalize_cell(expected_by_row.get(index, ''))
                    if latest_value != expected_value:
                        st.error(
                            f"Replace dibatalkan: baris {index + 1} sudah berubah oleh admin/user lain. "
                            "Muat ulang halaman sebelum mencoba lagi."
                        )
                        return False

                if not row_has_problem_label(latest_data.loc[index]):
                    st.error(
                        f"Replace dibatalkan: baris {index + 1} sudah tidak masuk filter label bermasalah. "
                        "Muat ulang halaman sebelum mencoba lagi."
                    )
                    return False

            latest_data.loc[selected_indices, 'input'] = normalized_replacement_input
            latest_data.loc[selected_indices, ['instruction_ats', 'output_ats']] = ''
            latest_data.loc[selected_indices, 'status'] = 'Pending'

            length_violations = get_ats_length_violations(latest_data, selected_indices)
            if length_violations:
                details = ", ".join(
                    f"baris {row} kolom {col}: {length:,} karakter"
                    for row, col, length in length_violations
                )
                st.error(
                    f"Replace dibatalkan: {details}. "
                    f"Batas maksimal Google Sheets adalah {MAX_SHEET_CELL_CHARS:,} karakter per cell."
                )
                return False

            conn.update(worksheet="Sheet1", data=latest_data)
            st.session_state['admin_loaded_sheet_rows'] = len(latest_data)
            remember_loaded_sheet(latest_data)

            verified_df, verified_error = read_sheet_with_retry()
            if verified_df is None or verified_df.empty:
                if verified_error:
                    st.warning(
                        f"Replace tersimpan, tetapi verifikasi Google Sheet belum dapat dibaca ({verified_error}). "
                        "Dashboard akan memakai data terbaru dari proses replace."
                    )
                else:
                    st.warning(
                        "Replace tersimpan, tetapi verifikasi Google Sheet terbaca kosong. "
                        "Dashboard akan memakai data terbaru dari proses replace."
                    )
                return True

            verified_data = prepare_sheet_data(verified_df)
            remember_loaded_sheet(verified_data)
            for index in selected_indices:
                if index not in verified_data.index:
                    st.warning(
                        f"Replace terkirim, tetapi baris {index + 1} tidak ditemukan saat verifikasi. "
                        "Muat ulang halaman untuk melihat data terbaru."
                    )
                    return False

                if (
                    normalize_cell(verified_data.at[index, 'input']) != normalized_replacement_input
                    or normalize_cell(verified_data.at[index, 'instruction_ats']) != ''
                    or normalize_cell(verified_data.at[index, 'output_ats']) != ''
                    or normalize_cell(verified_data.at[index, 'status']) != 'Pending'
                ):
                    st.warning(
                        "Replace terkirim, tetapi hasil verifikasi berbeda dari yang diharapkan. "
                        "Muat ulang halaman untuk melihat data terbaru."
                    )
                    return False

            return True
    except Exception as e:
        st.error(f"Gagal replace input: {e}")
        return False

def get_gemini_api_key_from_secrets():
    try:
        if "GEMINI_API_KEY" in st.secrets:
            return str(st.secrets["GEMINI_API_KEY"]).strip()
    except Exception:
        pass
    return os.environ.get("GEMINI_API_KEY", "").strip()

def get_clean_done_examples(data, limit=24):
    prepared_data = prepare_sheet_data(data)
    clean_mask = (
        (prepared_data["status"] == "Done")
        & (prepared_data["input"] != "")
        & (prepared_data["instruction_ats"] != "")
        & (prepared_data["output_ats"] != "")
        & ~prepared_data["instruction_ats"].str.contains(PROBLEM_PATTERN, case=False, na=False, regex=True)
        & ~prepared_data["output_ats"].str.contains(PROBLEM_PATTERN, case=False, na=False, regex=True)
    )
    examples = prepared_data[clean_mask].head(limit)
    return examples[["input", "instruction_ats", "output_ats"]].to_dict("records")

def learn_existing_ats_style_with_gemini(examples, api_key):
    if not api_key:
        raise ValueError("API key Gemini belum diisi.")
    if not examples:
        raise ValueError("Tidak ada data Done yang bersih untuk dipelajari.")

    example_text = "\n\n".join(
        (
            f"Contoh {idx + 1}\n"
            f"INPUT:\n{example['input'][:1200]}\n"
            f"INSTRUCTION_ATS:\n{example['instruction_ats'][:1200]}\n"
            f"OUTPUT_ATS:\n{example['output_ats'][:1200]}"
        )
        for idx, example in enumerate(examples)
    )
    prompt = (
        "Pelajari pola data pelabelan ATS berikut. Buat ringkasan gaya penulisan yang aman untuk dipakai "
        "sebagai panduan membuat data sintetis baru. Jangan menyalin data pasien secara verbatim. "
        "Fokus pada struktur konteks, tingkat detail klinis, format instruksi, format output, dan istilah triase.\n\n"
        f"{example_text}\n\n"
        "Kembalikan ringkasan singkat dalam bahasa Indonesia, maksimal 10 bullet."
    )
    response = requests.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
        headers={
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        },
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 900,
            },
        },
        timeout=45,
    )
    response.raise_for_status()
    payload = response.json()
    candidates = payload.get("candidates", [])
    if not candidates:
        raise ValueError("Gemini tidak mengembalikan hasil pembelajaran.")
    parts = candidates[0].get("content", {}).get("parts", [])
    learned_text = "\n".join(part.get("text", "") for part in parts).strip()
    if not learned_text:
        raise ValueError("Hasil pembelajaran Gemini kosong.")
    return learned_text

def append_synthetic_ats_cases(total_cases=700, synthetic_data=None, status_value="Done"):
    try:
        with get_sheet_write_lock():
            latest_df, latest_error = read_sheet_with_retry()
            if latest_df is None or latest_df.empty:
                if latest_error:
                    st.error(f"Tambah data sintetis dibatalkan: Google Sheet tidak dapat dibaca ({latest_error}).")
                else:
                    st.error("Tambah data sintetis dibatalkan: Google Sheet kosong atau tidak dapat dibaca.")
                return 0, 0

            latest_data = prepare_sheet_data(latest_df)
            if synthetic_data is None:
                synthetic_data = generate_synthetic_ats_cases(total_cases=total_cases)
            else:
                synthetic_data = synthetic_data.copy()

            for col in ['instruction_ats', 'input', 'output_ats', 'validator', 'status']:
                if col not in synthetic_data.columns:
                    synthetic_data[col] = ""
            synthetic_data['input'] = synthetic_data['input'].fillna('').astype(str).str.strip()
            synthetic_data = synthetic_data[synthetic_data['input'] != ''].copy()
            if synthetic_data.empty:
                st.error("Tambah data sintetis dibatalkan: tidak ada input sintetis yang terisi.")
                return 0, len(latest_data)

            synthetic_data["validator"] = "sintetis"
            synthetic_data["status"] = status_value

            if "synthetic_case_id" not in latest_data.columns:
                latest_data["synthetic_case_id"] = ""
            for col in synthetic_data.columns:
                if col not in latest_data.columns:
                    latest_data[col] = ""

            existing_ids = set(
                latest_data["synthetic_case_id"]
                .fillna("")
                .astype(str)
                .str.strip()
            )
            existing_inputs = set(
                latest_data["input"]
                .fillna("")
                .astype(str)
                .str.strip()
            )

            updated_count = 0
            append_rows = []
            latest_ids = latest_data["synthetic_case_id"].fillna("").astype(str).str.strip()
            for _, row in synthetic_data.iterrows():
                synthetic_id = str(row.get("synthetic_case_id", "")).strip()
                input_value = str(row.get("input", "")).strip()
                if synthetic_id and synthetic_id in existing_ids:
                    row_index = latest_ids[latest_ids == synthetic_id].index[0]
                    for col in synthetic_data.columns:
                        latest_data.at[row_index, col] = row.get(col, "")
                    updated_count += 1
                elif input_value not in existing_inputs:
                    append_rows.append(row)

            missing_data = pd.DataFrame(append_rows)
            if missing_data.empty and updated_count == 0:
                return 0, len(latest_data)

            updated_data = pd.concat([latest_data, missing_data], ignore_index=True, sort=False).fillna("")
            updated_data = prepare_sheet_data(updated_data)
            conn.update(worksheet="Sheet1", data=updated_data)
            st.session_state['admin_loaded_sheet_rows'] = len(updated_data)
            remember_loaded_sheet(updated_data)
            return len(missing_data) + updated_count, len(updated_data)
    except Exception as e:
        st.error(f"Gagal menambahkan data sintetis ke Google Sheet: {e}")
        return 0, 0

# --- LOGIN ADMIN ---
if not st.session_state.get('admin_logged_in', False):
    st.title("🔐 Admin Monitoring Panel")
    st.markdown("### Silakan pilih admin dan masukkan password untuk mengakses monitoring")
    
    col1, col2 = st.columns([1, 2])
    with col1:
        selected_admin = st.selectbox(
            "User Admin:",
            options=AUTHORIZED_ADMINS,
            index=None,
            placeholder="Pilih user admin..."
        )
        admin_pass = st.text_input("Password Admin:", type="password", placeholder="Masukkan password...")
        
        if st.button("🔓 Akses Admin", type="primary", use_container_width=True):
            if selected_admin and admin_pass == ADMIN_CREDENTIALS.get(selected_admin):
                st.session_state['admin_logged_in'] = True
                st.session_state['admin_username'] = selected_admin
                st.rerun()
            else:
                st.error("❌ Password salah!")
    
    st.stop()

# --- LOGOUT ADMIN ---
# Hide automatic page navigation untuk admin yang sudah login
st.markdown("""
<style>
    /* Hide page navigation dari sidebar ketika admin sudah login */
    [data-testid="collapsedControl"] { display: none; }
    [data-testid="stSidebarNav"] { display: none; }
</style>
""", unsafe_allow_html=True)

col1, col2 = st.sidebar.columns(2)
with col1:
    if st.sidebar.button("🏠 Kembali", use_container_width=True, help="Kembali ke halaman utama"):
        st.session_state['admin_logged_in'] = False
        st.session_state.pop('admin_username', None)
        st.switch_page("app.py")

with col2:
    if st.sidebar.button("🚪 Logout", use_container_width=True):
        st.session_state['admin_logged_in'] = False
        st.session_state.pop('admin_username', None)
        st.rerun()

st.sidebar.divider()
admin_username = st.session_state.get('admin_username', 'admin')
can_replace_input = admin_username in REPLACEMENT_ADMINS
can_manage_synthetic_data = admin_username in SYNTHETIC_DATA_ADMINS
is_synthetic_only_admin = can_manage_synthetic_data and admin_username not in REPLACEMENT_ADMINS and admin_username != "admin"
st.sidebar.caption(f"Admin aktif: {admin_username}")

if is_synthetic_only_admin:
    st.title("Tambah Data Sintetis ATS")
    st.markdown("Akun ini hanya dapat menambahkan data sintetis seimbang ke Google Sheet.")
else:
    st.title("📊 Admin Monitoring Panel - Pelabelan ATS")
    st.markdown("Dashboard monitoring progress pelabelan masing-masing user")

# --- LOAD DATA ---
try:
    df = load_data()
    if df is None or df.empty:
        st.error("Google Sheet kosong atau tidak dapat diakses.")
        st.stop()

    st.session_state['admin_loaded_sheet_rows'] = len(df)

    # Rename jika kolom yang lama ada
    if 'nama_validator' in df.columns and 'validator' not in df.columns:
        df.rename(columns={'nama_validator': 'validator'}, inplace=True)
    if 'instruksi_ats' in df.columns and 'instruction_ats' not in df.columns:
        df.rename(columns={'instruksi_ats': 'instruction_ats'}, inplace=True)

    for col in ['validator', 'instruction_ats', 'status', 'input', 'output_ats']:
        if col not in df.columns: df[col] = ""
    
    # KONVERSI DATA KE STRING - LEBIH ROBUST
    # Handle NaN, None, dan nilai null lainnya
    for col in ['validator', 'instruction_ats', 'status', 'input', 'output_ats']:
        df[col] = df[col].fillna('').astype(str).str.strip()
        # Hilangkan string 'nan' 
        df[col] = df[col].replace('nan', '').str.strip()
        # Hilangkan 'none' (case-insensitive)
        df[col] = df[col].mask(df[col].str.lower() == 'none', '')
        # Final strip setelah semua cleaning
        df[col] = df[col].str.strip()
    
    has_input_mask = df['input'] != ''
    
except Exception as e:
    st.error(f"Gagal memuat data: {e}")
    st.stop()

# --- DATA SINTETIS ATS ---
if can_manage_synthetic_data:
    if "synthetic_ats_draft" not in st.session_state:
        st.session_state["synthetic_ats_draft"] = generate_synthetic_ats_cases(total_cases=700)
    if "synthetic_learning_notes" not in st.session_state:
        st.session_state["synthetic_learning_notes"] = ""

    synthetic_preview = st.session_state["synthetic_ats_draft"].copy()
    with st.expander("Tambah 700 data sintetis ATS seimbang", expanded=is_synthetic_only_admin):
        st.caption(
            "Akan membuat 140 kasus untuk tiap level: merah, orange, hijau, biru, dan putih. "
            "Kolom instruction_ats, output_ats, validator, dan status ikut disiapkan sebelum disimpan."
        )

        clean_examples = get_clean_done_examples(df)
        st.caption(f"Data Done bersih yang tersedia untuk dipelajari Gemini: {len(clean_examples)} contoh.")
        gemini_api_key = get_gemini_api_key_from_secrets()
        if gemini_api_key:
            st.success("Gemini API key ditemukan dari secret GEMINI_API_KEY.")
        else:
            st.warning("Gemini API key belum ditemukan. Tambahkan GEMINI_API_KEY di Streamlit secrets.")

        learn_col1, learn_col2 = st.columns(2)
        with learn_col1:
            if st.button("Pelajari Data Existing dengan Gemini", use_container_width=True):
                try:
                    learned_notes = learn_existing_ats_style_with_gemini(
                        clean_examples,
                        gemini_api_key,
                    )
                    st.session_state["synthetic_learning_notes"] = learned_notes
                    st.session_state["synthetic_ats_draft"] = generate_synthetic_ats_cases(
                        total_cases=700,
                        learning_notes=learned_notes,
                    )
                    st.success("Gemini selesai mempelajari pola data Done yang bersih.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Gagal mempelajari data existing dengan Gemini: {e}")
        with learn_col2:
            if st.button(
                "Generate Ulang Draft dari Hasil Belajar",
                use_container_width=True,
                disabled=not st.session_state["synthetic_learning_notes"],
            ):
                st.session_state["synthetic_ats_draft"] = generate_synthetic_ats_cases(
                    total_cases=700,
                    learning_notes=st.session_state["synthetic_learning_notes"],
                )
                st.success("Draft sintetis dibuat ulang dari hasil pembelajaran.")
                st.rerun()

        if st.session_state["synthetic_learning_notes"]:
            st.text_area(
                "Ringkasan pembelajaran Gemini",
                value=st.session_state["synthetic_learning_notes"],
                height=180,
            )
        else:
            st.info("Jalankan pembelajaran Gemini terlebih dahulu agar draft mengikuti pola data Done existing.")

        st.dataframe(
            get_synthetic_balance_summary(synthetic_preview),
            use_container_width=True,
            hide_index=True,
        )

        existing_synthetic_count = 0
        if "synthetic_case_id" in df.columns:
            existing_synthetic_count = df["synthetic_case_id"].fillna("").astype(str).str.strip().ne("").sum()
        st.caption(f"Data sintetis yang sudah terdeteksi di sheet saat ini: {existing_synthetic_count}")

        st.markdown("#### Review dan edit data")
        case_options = synthetic_preview["synthetic_case_id"].tolist()
        selected_case_id = st.selectbox(
            "Pilih data sintetis",
            options=case_options,
            key="selected_synthetic_case_id",
        )
        selected_index = synthetic_preview.index[
            synthetic_preview["synthetic_case_id"] == selected_case_id
        ][0]
        selected_row = synthetic_preview.loc[selected_index]

        detail_col1, detail_col2, detail_col3 = st.columns(3)
        detail_col1.metric("ID", selected_row["synthetic_case_id"])
        detail_col2.metric("Level", selected_row["synthetic_ats_level"])
        detail_col3.metric("Kategori", selected_row["synthetic_ats_category"])

        edited_input = st.text_area(
            "Input",
            value=selected_row["input"],
            height=220,
            key=f"synthetic_input_{selected_case_id}",
        )
        edited_instruction = st.text_area(
            "Instruction ATS",
            value=selected_row["instruction_ats"],
            height=260,
            key=f"synthetic_instruction_{selected_case_id}",
        )
        edited_output = st.text_area(
            "Output ATS",
            value=selected_row["output_ats"],
            height=220,
            key=f"synthetic_output_{selected_case_id}",
        )

        edit_col1, edit_col2 = st.columns(2)
        with edit_col1:
            if st.button("Simpan Perubahan Data Ini", use_container_width=True):
                st.session_state["synthetic_ats_draft"].at[selected_index, "input"] = edited_input.strip()
                st.session_state["synthetic_ats_draft"].at[selected_index, "instruction_ats"] = edited_instruction.strip()
                st.session_state["synthetic_ats_draft"].at[selected_index, "output_ats"] = edited_output.strip()
                st.session_state["synthetic_ats_draft"].at[selected_index, "validator"] = "sintetis"
                st.success(f"Perubahan {selected_case_id} disimpan di draft.")
                st.rerun()
        with edit_col2:
            if st.button("Reset Semua Draft Sintetis", use_container_width=True):
                st.session_state["synthetic_ats_draft"] = generate_synthetic_ats_cases(
                    total_cases=700,
                    learning_notes=st.session_state["synthetic_learning_notes"],
                )
                st.success("Draft data sintetis dikembalikan ke versi awal.")
                st.rerun()

        st.dataframe(
            synthetic_preview[
                [
                    "synthetic_case_id",
                    "synthetic_ats_level",
                    "synthetic_ats_category",
                    "validator",
                    "status",
                    "input",
                    "instruction_ats",
                    "output_ats",
                ]
            ],
            use_container_width=True,
            hide_index=True,
        )

        confirm_synthetic_append = st.checkbox(
            "Saya sudah meninjau data sintetis dan yakin ingin menyimpannya ke Google Sheet.",
            key="confirm_synthetic_append",
        )
        can_save_synthetic = confirm_synthetic_append and bool(st.session_state["synthetic_learning_notes"])
        if confirm_synthetic_append and not st.session_state["synthetic_learning_notes"]:
            st.warning("Jalankan pembelajaran Gemini terlebih dahulu sebelum menyimpan ke Google Sheet.")
        save_progress_col, save_final_col = st.columns(2)
        with save_progress_col:
            if st.button(
                "Simpan Progress ke Google Sheet",
                use_container_width=True,
                disabled=not can_save_synthetic,
            ):
                saved_count, total_rows_after = append_synthetic_ats_cases(
                    total_cases=700,
                    synthetic_data=st.session_state["synthetic_ats_draft"],
                    status_value="Pending",
                )
                if saved_count:
                    st.success(
                        f"Progress {saved_count} data sintetis tersimpan. "
                        f"Total baris sheet sekarang {total_rows_after}."
                    )
                    st.rerun()
                else:
                    st.info("Tidak ada data yang disimpan; semua ID/input sudah sama atau terduplikasi.")
        with save_final_col:
            if st.button(
                "Simpan Final ke Google Sheet",
                type="primary",
                use_container_width=True,
                disabled=not can_save_synthetic,
            ):
                saved_count, total_rows_after = append_synthetic_ats_cases(
                    total_cases=700,
                    synthetic_data=st.session_state["synthetic_ats_draft"],
                    status_value="Done",
                )
                if saved_count:
                    st.success(
                        f"Final {saved_count} data sintetis tersimpan. "
                        f"Total baris sheet sekarang {total_rows_after}."
                    )
                    st.session_state["synthetic_ats_draft"] = generate_synthetic_ats_cases(
                        total_cases=700,
                        learning_notes=st.session_state["synthetic_learning_notes"],
                    )
                    st.rerun()
                else:
                    st.info("Tidak ada data yang disimpan; semua ID/input sudah sama atau terduplikasi.")

if is_synthetic_only_admin:
    st.stop()

# --- KALKULASI STATISTIK ---
def calculate_stats(df, username):
    user_data = df[df['validator'] == username]
    total = len(user_data)
    done = len(user_data[user_data['status'] == 'Done'])
    pending = len(user_data[(user_data['status'] != 'Done') & (user_data['status'] != '')])
    available = len(user_data[(user_data['validator'] != '') & (user_data['status'] == '')])  # Diambil tapi belum dimulai
    
    return {
        'username': username,
        'total': total,
        'done': done,
        'pending': pending,
        'available': available,
        'progress_pct': (done / total * 100) if total > 0 else 0
    }

# --- HITUNG STATISTIK GLOBAL ---
visible_df = df[has_input_mask].copy()

problem_text_mask = (
    visible_df['instruction_ats'].str.contains(PROBLEM_PATTERN, case=False, na=False, regex=True)
    | visible_df['output_ats'].str.contains(PROBLEM_PATTERN, case=False, na=False, regex=True)
)

total_data = len(visible_df)
unassigned_mask = (
    (visible_df['input'] != '')
    & (visible_df['instruction_ats'] == '')
    & (visible_df['output_ats'] == '')
    & (visible_df['validator'] == '')
    & (visible_df['status'] == '')
)
total_done = len(visible_df[visible_df['status'] == 'Done'])
total_pending = len(visible_df[(visible_df['validator'] != '') & (visible_df['status'] != 'Done') & (visible_df['status'] != '')])
total_available = len(visible_df[(visible_df['validator'] != '') & (visible_df['status'] == '')])
total_unassigned = len(visible_df[unassigned_mask])
total_failed_labeled = len(visible_df[problem_text_mask])
ready_ats_mask = (
    (visible_df['status'] == 'Done')
    & (visible_df['instruction_ats'] != '')
    & (visible_df['output_ats'] != '')
    & ~problem_text_mask
)
total_ready_ats = len(visible_df[ready_ats_mask])
ready_ats_df = visible_df[ready_ats_mask].copy()
instruction_lengths = visible_df['instruction_ats'].map(lambda value: len(normalize_cell(value)))
output_lengths = visible_df['output_ats'].map(lambda value: len(normalize_cell(value)))
over_limit_mask = (
    (instruction_lengths > MAX_SHEET_CELL_CHARS)
    | (output_lengths > MAX_SHEET_CELL_CHARS)
)
near_limit_mask = (
    (instruction_lengths > int(MAX_SHEET_CELL_CHARS * 0.9))
    | (output_lengths > int(MAX_SHEET_CELL_CHARS * 0.9))
)
total_over_length_limit = int(over_limit_mask.sum())
total_near_length_limit = int(near_limit_mask.sum())
max_instruction_length = int(instruction_lengths.max()) if not instruction_lengths.empty else 0
max_output_length = int(output_lengths.max()) if not output_lengths.empty else 0

# --- TAMPILKAN STATISTIK GLOBAL ---
st.markdown("### 📈 Statistik Keseluruhan")
col1, col2, col3, col4, col5 = st.columns(5)

with col1:
    st.metric("📊 Total Data", total_data)
with col2:
    st.metric("✅ Selesai (Done)", total_done)
with col3:
    st.metric("⏳ Sedang Dikerjakan", total_pending)
with col4:
    st.metric("📋 Diambil (Belum Dimulai)", total_available)
with col5:
    st.metric("🆓 Tersedia Diambil", total_unassigned)

col6, col7 = st.columns(2)
with col6:
    st.metric("Gagal Dilabeli", total_failed_labeled)
with col7:
    st.metric("ATS Siap Pakai", total_ready_ats)

col8, col9, col10, col11 = st.columns(4)
with col8:
    st.metric("ATS > Batas Karakter", total_over_length_limit)
with col9:
    st.metric("ATS Mendekati Batas", total_near_length_limit)
with col10:
    st.metric("Max instruction_ats", max_instruction_length)
with col11:
    st.metric("Max output_ats", max_output_length)

if total_over_length_limit > 0:
    st.warning(
        f"Ada {total_over_length_limit} data dengan instruction_ats/output_ats melebihi "
        f"{MAX_SHEET_CELL_CHARS:,} karakter. Penyimpanan/update untuk baris tersebut akan dibatalkan."
    )

st.divider()

# --- REKAP PROGRESS PER USER ---
st.markdown("### 👥 Progress Masing-Masing User")

user_stats = []
for user in AUTHORIZED_USERS:
    stats = calculate_stats(visible_df, user)
    user_stats.append(stats)

# Buat dataframe untuk ditampilkan
stats_df = pd.DataFrame(user_stats)

# --- TAB VIEW ---
tab1, tab2, tab3 = st.tabs(["📊 Tabel Ringkas", "📈 Grafik Progress", "📋 Detail Per User"])

# TAB 1: TABEL RINGKAS
with tab1:
    st.markdown("#### Ringkasan Progress Semua User")
    
    # Buat display dataframe yang lebih rapi
    display_df = stats_df.copy()
    display_df.columns = ['User', 'Total Tugas', 'Selesai ✅', 'Sedang Dikerjakan ⏳', 'Belum Dimulai 📋', 'Progress %']
    
    # Format kolom progress sebagai persentase
    display_df['Progress %'] = display_df['Progress %'].apply(lambda x: f"{x:.1f}%")
    
    # Gunakan st.dataframe dengan styling
    st.dataframe(
        display_df,
        use_container_width=True,
        height=300,
        column_config={
            "Progress %": st.column_config.ProgressColumn(
                "Progress %",
                min_value=0,
                max_value=100,
            )
        }
    )

# TAB 2: GRAFIK PROGRESS
with tab2:
    col_chart1, col_chart2 = st.columns(2)
    
    with col_chart1:
        st.markdown("#### Progress Masing-Masing User")
        
        # Create bar chart for progress
        fig_bar = go.Figure()
        
        fig_bar.add_trace(go.Bar(
            x=stats_df['username'],
            y=stats_df['progress_pct'],
            name='Progress (%)',
            marker=dict(
                color=stats_df['progress_pct'],
                colorscale='Viridis',
                showscale=True
            ),
            text=stats_df['progress_pct'].apply(lambda x: f'{x:.1f}%'),
            textposition='auto',
        ))
        
        fig_bar.update_layout(
            title="Progress Pelabelan (%)",
            xaxis_title="User",
            yaxis_title="Progress (%)",
            height=400,
            showlegend=False
        )
        
        st.plotly_chart(fig_bar, use_container_width=True)
    
    with col_chart2:
        st.markdown("#### Status Distribusi")
        
        # Create allocation chart
        status_data = {
            'Selesai (Done)': total_done,
            'Sedang Dikerjakan': total_pending,
            'Belum Dimulai': total_available,
            'Belum Diambil': total_unassigned
        }
        
        colors = ['#16a34a', '#f59e0b', '#fbbf24', '#e5e7eb']
        fig_pie = go.Figure(
            data=[go.Pie(
                labels=list(status_data.keys()),
                values=list(status_data.values()),
                marker=dict(colors=colors),
                textposition='inside',
                textinfo='label+value+percent'
            )]
        )
        
        fig_pie.update_layout(
            title="Distribusi Status Data",
            height=400,
        )
        
        st.plotly_chart(fig_pie, use_container_width=True)

# TAB 3: DETAIL PER USER
with tab3:
    st.markdown("#### Detail Progress Setiap User")
    
    for user_stat in user_stats:
        user = user_stat['username']
        
        # Buat container untuk setiap user
        with st.container():
            # Header user
            col_header1, col_header2, col_header3, col_header4 = st.columns(4)
            
            with col_header1:
                st.metric(f"👤 {user}", f"{user_stat['total']} Tugas")
            with col_header2:
                st.metric("✅ Selesai", user_stat['done'])
            with col_header3:
                st.metric("⏳ Aktif", user_stat['pending'])
            with col_header4:
                progress_color = "#16a34a" if user_stat['progress_pct'] >= 50 else "#f59e0b"
                st.markdown(f"""
                <div style="text-align: center; padding: 20px; background-color: {progress_color}15; border-radius: 8px; border-left: 4px solid {progress_color};">
                    <h3 style="margin: 0; color: {progress_color};">{user_stat['progress_pct']:.1f}%</h3>
                    <small style="color: #666;">Progress</small>
                </div>
                """, unsafe_allow_html=True)
            
            # Progress bar
            st.progress(user_stat['progress_pct'] / 100, text=f"Progress: {user_stat['progress_pct']:.1f}%")
            
            st.divider()

# --- DETAIL TABEL LENGKAP ---
st.markdown("### 📋 Tabel Detail Semua Data")

# Filter options
col_filter1, col_filter2, col_filter3 = st.columns(3)

with col_filter1:
    filter_user = st.multiselect(
        "Filter by User:",
        options=["Semua"] + AUTHORIZED_USERS,
        default="Semua"
    )

with col_filter2:
    filter_status = st.multiselect(
        "Filter by Status:",
        options=["Semua"] + ["Done", "Belum Dimulai", "Sedang Dikerjakan", "Belum Diambil"],
        default="Semua"
    )

with col_filter3:
    show_cols = st.multiselect(
        "Pilih Kolom yang Ditampilkan:",
        options=['validator', 'input', 'instruction_ats', 'output_ats', 'status'],
        default=['validator', 'status', 'instruction_ats', 'output_ats']
    )

# Apply filters
filtered_df = visible_df.copy()

if "Semua" not in filter_user and filter_user:
    filtered_df = filtered_df[filtered_df['validator'].isin(filter_user)]

if "Semua" not in filter_status and filter_status:
    status_map = {
        "Done": "Done",
        "Belum Dimulai": "",
        "Sedang Dikerjakan": lambda x: x != "Done" and x != "",
        "Belum Diambil": ""
    }
    
    status_filters = []
    for status in filter_status:
        if status == "Done":
            status_filters.append(filtered_df['status'] == "Done")
        elif status == "Belum Dimulai":
            status_filters.append((filtered_df['validator'] != '') & (filtered_df['status'] == ''))
        elif status == "Sedang Dikerjakan":
            status_filters.append((filtered_df['status'] != 'Done') & (filtered_df['status'] != ''))
        elif status == "Belum Diambil":
            status_filters.append(
                (filtered_df['input'] != '')
                & (filtered_df['instruction_ats'] == '')
                & (filtered_df['output_ats'] == '')
                & (filtered_df['validator'] == '')
                & (filtered_df['status'] == '')
            )
    
    if status_filters:
        filtered_df = filtered_df[pd.concat(status_filters, axis=1).any(axis=1)]

# Select columns to display
if show_cols:
    display_detail_df = filtered_df[show_cols].copy()
    display_detail_df.index = display_detail_df.index + 1  # Tampilkan index dari 1
    
    st.dataframe(
        display_detail_df,
        use_container_width=True,
        height=500
    )
    
    st.info(f"Total: {len(filtered_df)} data")

# --- REPLACE INPUT BERDASARKAN LABEL BERMASALAH ---
st.divider()
st.markdown("### Replace Input Berdasarkan Label Bermasalah")

problem_mask = (
    has_input_mask
    & (
        df['instruction_ats'].str.contains(PROBLEM_PATTERN, case=False, na=False, regex=True)
        | df['output_ats'].str.contains(PROBLEM_PATTERN, case=False, na=False, regex=True)
    )
)
problem_df = df[problem_mask].copy()

st.caption(f"Filter otomatis mencari data dengan instruction_ats atau output_ats yang mengandung kata: {PROBLEM_KEYWORDS_LABEL}.")
st.metric("Data terfilter", len(problem_df))

if problem_df.empty:
    st.info(f"Tidak ada data dengan instruction_ats atau output_ats yang mengandung kata: {PROBLEM_KEYWORDS_LABEL}.")
else:
    preview_cols = ['validator', 'status', 'input', 'instruction_ats', 'output_ats']
    preview_df = problem_df[preview_cols].copy()
    preview_df.insert(0, 'row_sheet', preview_df.index + 1)

    st.dataframe(
        preview_df,
        use_container_width=True,
        height=300
    )

    row_options = {
        f"Row {index + 1} - {str(row.get('instruction_ats', '') or row.get('output_ats', ''))[:80]}": index
        for index, row in problem_df.iterrows()
    }

    selected_rows = st.multiselect(
        "Pilih baris yang input-nya akan diganti:",
        options=list(row_options.keys())
    )

    replacement_input = st.text_area(
        "Data input baru:",
        height=180,
        placeholder="Tempel data input baru di sini..."
    )

    confirm_replace = st.checkbox("Saya yakin ingin mengganti input untuk baris yang dipilih.")
    if not can_replace_input:
        st.warning("Admin ini tidak memiliki akses untuk proses replacement.")

    if st.button("Replace Input Terpilih", type="primary", use_container_width=True, disabled=not can_replace_input):
        selected_indices = [row_options[label] for label in selected_rows]

        if not selected_indices:
            st.error("Pilih minimal satu baris terlebih dahulu.")
        elif not replacement_input.strip():
            st.error("Isi data input baru terlebih dahulu.")
        elif not confirm_replace:
            st.error("Centang konfirmasi sebelum melakukan replace.")
        else:
            expected_replace_values = {
                'input': {
                    index: df.at[index, 'input']
                    for index in selected_indices
                },
                'instruction_ats': {
                    index: df.at[index, 'instruction_ats']
                    for index in selected_indices
                },
                'output_ats': {
                    index: df.at[index, 'output_ats']
                    for index in selected_indices
                },
                'status': {
                    index: df.at[index, 'status']
                    for index in selected_indices
                },
                'validator': {
                    index: df.at[index, 'validator']
                    for index in selected_indices
                },
            }
            if replace_problem_inputs(selected_indices, replacement_input, expected_replace_values):
                st.success(f"Berhasil mengganti input untuk {len(selected_indices)} baris.")
                st.rerun()

# --- STATISTIK DOWNLOAD ---
st.markdown("### 📥 Export Data")

col_export1, col_export2 = st.columns(2)

with col_export1:
    # Export sebagai CSV
    csv = filtered_df.to_csv(index=False)
    st.download_button(
        label="📄 Download CSV",
        data=csv,
        file_name="monitoring_pelabelan.csv",
        mime="text/csv",
        use_container_width=True
    )

with col_export2:
    # Export statistics sebagai CSV
    stats_csv = stats_df.to_csv(index=False)
    st.download_button(
        label="📊 Download Statistik",
        data=stats_csv,
        file_name="statistik_pelabelan.csv",
        mime="text/csv",
        use_container_width=True
    )

st.markdown("#### Export ATS Siap Pakai")
st.caption("Berisi data status Done dengan instruction_ats dan output_ats terisi, tanpa kata bermasalah.")

ready_export_df = ready_ats_df.copy()
ready_export_df.insert(0, 'row_sheet', ready_export_df.index + 1)

col_ready_csv, col_ready_excel = st.columns(2)

with col_ready_csv:
    ready_csv = ready_export_df.to_csv(index=False)
    st.download_button(
        label="Download ATS Siap Pakai CSV",
        data=ready_csv,
        file_name="ats_siap_pakai.csv",
        mime="text/csv",
        use_container_width=True,
        disabled=ready_export_df.empty
    )

with col_ready_excel:
    excel_buffer = BytesIO()
    excel_ready = True
    try:
        with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
            ready_export_df.to_excel(writer, index=False, sheet_name="ATS Siap Pakai")
    except Exception:
        excel_ready = False

    st.download_button(
        label="Download ATS Siap Pakai Excel",
        data=excel_buffer.getvalue() if excel_ready else b"",
        file_name="ats_siap_pakai.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
        disabled=ready_export_df.empty or not excel_ready
    )
    if not excel_ready:
        st.caption("Export Excel belum tersedia karena dependency Excel tidak aktif. Gunakan CSV.")

st.divider()
st.caption("🔒 Admin Monitoring Panel - Akses Terbatas")
