import streamlit as st
import pandas as pd
from io import BytesIO
from streamlit_gsheets import GSheetsConnection
import plotly.graph_objects as go
import plotly.express as px
import os
import requests
from difflib import SequenceMatcher
import re
import time
from auth_config import AUTHORIZED_USERS, ADMIN_CREDENTIALS, AUTHORIZED_ADMINS, REPLACEMENT_ADMINS, SYNTHETIC_DATA_ADMINS
from sheet_lock import get_sheet_write_lock
from sheet_range_update import append_sheet_rows, update_sheet_cells
from synthetic_ats_data import ATS_LEVELS, generate_synthetic_ats_cases, get_synthetic_balance_summary

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
SYNTHETIC_SIMILARITY_THRESHOLD = 0.86
SYNTHETIC_CASE_ID_PATTERN = re.compile(r"^ATS-SYN-(\d+)$")
GEMINI_RETRY_DELAYS = [15, 45, 90]
GEMINI_INTER_REQUEST_DELAY_SECONDS = 6
SYNTHETIC_FULL_TOTAL = 700
SYNTHETIC_INPUT_ONLY_TOTAL = 50

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

        update_sheet_cells("Sheet1", sheet_data, changed_indices, changed_columns)
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

            update_sheet_cells(
                "Sheet1",
                latest_data,
                selected_indices,
                ['input', 'instruction_ats', 'output_ats', 'status'],
            )
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

def get_clean_done_examples(data, limit=40):
    prepared_data = prepare_sheet_data(data)
    clean_mask = (
        (prepared_data["status"] == "Done")
        & (prepared_data["input"] != "")
        & (prepared_data["instruction_ats"] != "")
        & (prepared_data["output_ats"] != "")
        & ~prepared_data["instruction_ats"].str.contains(PROBLEM_PATTERN, case=False, na=False, regex=True)
        & ~prepared_data["output_ats"].str.contains(PROBLEM_PATTERN, case=False, na=False, regex=True)
    )
    examples = prepared_data[clean_mask].copy()
    if len(examples) > limit:
        examples = examples.sample(n=limit, random_state=20260518)
    return examples[["input", "instruction_ats", "output_ats"]].to_dict("records")

def get_clean_input_examples(data, limit=40):
    prepared_data = prepare_sheet_data(data)
    clean_mask = (
        (prepared_data["input"] != "")
        & ~prepared_data["input"].str.contains(PROBLEM_PATTERN, case=False, na=False, regex=True)
    )
    examples = prepared_data[clean_mask].copy()
    if len(examples) > limit:
        examples = examples.sample(n=limit, random_state=20260519)
    return examples["input"].tolist()

def get_next_synthetic_start_number(data):
    if data is None or data.empty or "synthetic_case_id" not in data.columns:
        return 1

    max_number = 0
    for value in data["synthetic_case_id"].fillna("").astype(str).str.strip():
        match = SYNTHETIC_CASE_ID_PATTERN.match(value)
        if match:
            max_number = max(max_number, int(match.group(1)))
    return max_number + 1

def make_synthetic_draft(existing_data, learning_notes=""):
    return generate_synthetic_ats_cases(
        total_cases=SYNTHETIC_FULL_TOTAL,
        learning_notes=learning_notes,
        start_number=get_next_synthetic_start_number(existing_data),
    )

def make_input_only_synthetic_draft(existing_data):
    draft = generate_synthetic_ats_cases(
        total_cases=SYNTHETIC_INPUT_ONLY_TOTAL,
        start_number=get_next_synthetic_start_number(existing_data),
    )
    draft["instruction_ats"] = ""
    draft["output_ats"] = ""
    draft["validator"] = ""
    draft["status"] = ""
    return draft

def remove_existing_synthetic_rows(draft, existing_data):
    if draft is None or draft.empty:
        return draft

    latest_data = prepare_sheet_data(existing_data)
    existing_ids = set()
    if "synthetic_case_id" in latest_data.columns:
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

    cleaned_draft = draft.copy()
    cleaned_draft["synthetic_case_id"] = cleaned_draft["synthetic_case_id"].fillna("").astype(str).str.strip()
    cleaned_draft["input"] = cleaned_draft["input"].fillna("").astype(str).str.strip()
    return cleaned_draft[
        ~cleaned_draft["synthetic_case_id"].isin(existing_ids)
        & ~cleaned_draft["input"].isin(existing_inputs)
    ].copy()

def refill_synthetic_draft(draft, existing_data, learning_notes="", input_only=False, target_total=SYNTHETIC_FULL_TOTAL):
    cleaned_draft = remove_existing_synthetic_rows(draft, existing_data)
    next_start = max(
        get_next_synthetic_start_number(existing_data),
        get_next_synthetic_start_number(cleaned_draft),
    )

    if len(cleaned_draft) != len(draft) or len(cleaned_draft) != target_total:
        cleaned_draft = generate_synthetic_ats_cases(
            total_cases=target_total,
            learning_notes=learning_notes,
            start_number=next_start,
        )
        if input_only:
            cleaned_draft["instruction_ats"] = ""
            cleaned_draft["output_ats"] = ""
            cleaned_draft["validator"] = ""
            cleaned_draft["status"] = ""

    return cleaned_draft.head(target_total).reset_index(drop=True)

def learn_existing_ats_style_with_gemini(examples, api_key):
    if not api_key:
        raise ValueError("API key Gemini belum diisi.")
    if not examples:
        raise ValueError("Tidak ada data Done yang bersih untuk dipelajari.")

    example_text = "\n\n".join(
        (
            f"Contoh {idx + 1}\n"
            f"INPUT:\n{example['input'][:1600]}\n"
            f"INSTRUCTION_ATS:\n{example['instruction_ats'][:2400]}\n"
            f"OUTPUT_ATS:\n{example['output_ats'][:1200]}"
        )
        for idx, example in enumerate(examples)
    )
    prompt = (
        "Anda adalah analis data triase ATS. Pelajari pola data pelabelan ATS berikut untuk membuat panduan "
        "pembuatan data sintetis baru. Prioritas utama adalah mempelajari cara pengisian INSTRUCTION_ATS. "
        "Jangan menyalin data pasien secara verbatim dan jangan membuat kasus baru di jawaban ini.\n\n"
        f"{example_text}\n\n"
        "Kembalikan panduan dalam bahasa Indonesia dengan format persis berikut:\n"
        "POLA_KONTEKS:\n"
        "- jelaskan pola konteks yang terlihat di instruction_ats existing, termasuk detail klinis yang wajib ada.\n\n"
        "POLA_PENGETAHUAN:\n"
        "- jelaskan cara pengetahuan ATS ditulis, istilah yang sering dipakai, dan tingkat detailnya.\n\n"
        "POLA_INTERVENSI_IGD:\n"
        "- jelaskan pola intervensi penyelamatan nyawa/penanganan IGD yang biasanya dicantumkan.\n\n"
        "POLA_INSTRUKSI:\n"
        "- jelaskan gaya kalimat instruksi, cara meminta klasifikasi, dan batasan jawaban.\n\n"
        "POLA_OUTPUT:\n"
        "- jelaskan format output_ats existing untuk analisis dan kesimpulan.\n\n"
        "ATURAN_GENERASI:\n"
        "- tulis 6 sampai 10 aturan praktis agar synthetic instruction_ats mirip gaya data Done existing."
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
                "maxOutputTokens": 1600,
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

def learn_existing_input_style_with_gemini(input_examples, api_key):
    if not api_key:
        raise ValueError("API key Gemini belum ditemukan dari secret GEMINI_API_KEY.")
    if not input_examples:
        raise ValueError("Tidak ada input existing yang bersih untuk dipelajari.")

    example_text = "\n\n".join(
        f"CONTOH INPUT {index + 1}:\n{example[:1800]}"
        for index, example in enumerate(input_examples)
    )
    prompt = (
        "Anda adalah analis data triase IGD. Pelajari gaya narasi INPUT existing berikut untuk membuat "
        "data input sintetis baru. Jangan menyalin kasus atau kalimat secara verbatim. Fokus pada pola bahasa, "
        "urutan informasi, kedalaman detail, dan variasi klinis yang perlu dipertahankan.\n\n"
        f"{example_text}\n\n"
        "Kembalikan panduan singkat dalam bahasa Indonesia dengan format:\n"
        "POLA_NARASI_INPUT:\n"
        "- pola pembukaan, kronologi, keluhan, gejala penyerta, tanda vital, riwayat, dan observasi triase.\n\n"
        "ATURAN_VARIASI:\n"
        "- 8 sampai 12 aturan agar input sintetis bervariasi tinggi dan tidak sama dengan data existing.\n\n"
        "HAL_YANG_DIHINDARI:\n"
        "- pola repetitif, frasa yang terlalu sering, dan hal yang membuat kasus tampak duplikat."
    )
    response = post_gemini_generate_content(
        api_key,
        prompt,
        {
            "temperature": 0.25,
            "maxOutputTokens": 1400,
        },
        timeout=90,
    )
    payload = response.json()
    parts = payload.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    learned_text = "\n".join(part.get("text", "") for part in parts).strip()
    if not learned_text:
        raise ValueError("Hasil pembelajaran gaya input Gemini kosong.")
    return learned_text

def learn_existing_input_style_locally(input_examples):
    if not input_examples:
        raise ValueError("Tidak ada input existing yang bersih untuk dipelajari.")

    text_series = pd.Series(input_examples).fillna("").astype(str)
    lengths = text_series.map(len)
    common_terms = []
    clinical_keywords = [
        "IGD", "triase", "keluhan", "tanda vital", "GCS", "TD", "HR", "RR", "SpO2",
        "riwayat", "nyeri", "sesak", "demam", "muntah", "diare", "perdarahan",
        "lemas", "pusing", "batuk", "trauma", "jatuh", "kesadaran",
    ]
    lower_blob = " ".join(text_series.str.lower().tolist())
    for keyword in clinical_keywords:
        if keyword.lower() in lower_blob:
            common_terms.append(keyword)

    avg_length = int(lengths.mean()) if not lengths.empty else 0
    min_length = int(lengths.min()) if not lengths.empty else 0
    max_length = int(lengths.max()) if not lengths.empty else 0
    paragraph_style = "beberapa paragraf pendek" if text_series.str.contains(r"\n\s*\n", regex=True).mean() >= 0.25 else "satu paragraf naratif atau paragraf pendek"

    return (
        "POLA_NARASI_INPUT:\n"
        f"- Input existing cenderung memakai {paragraph_style}.\n"
        f"- Panjang narasi berkisar sekitar {min_length}-{max_length} karakter, rata-rata {avg_length} karakter.\n"
        "- Narasi perlu memuat cara datang, kronologi keluhan, gejala penyerta, kondisi umum, riwayat, observasi triase, dan tanda vital.\n"
        f"- Istilah klinis yang tampak relevan untuk dipertahankan: {', '.join(common_terms[:12]) or 'keluhan, tanda vital, riwayat, observasi triase'}.\n\n"
        "ATURAN_VARIASI:\n"
        "- Buat kasus baru yang berbeda secara klinis, bukan parafrase dari input existing.\n"
        "- Variasikan usia, jenis kelamin, cara datang, durasi keluhan, gejala penyerta, riwayat penyakit, tanda vital, dan observasi awal.\n"
        "- Hindari memakai urutan kalimat yang sama untuk semua kasus.\n"
        "- Pertahankan konsistensi antara level ATS target dan derajat kegawatan narasi.\n"
        "- Gunakan tanda vital yang masuk akal untuk setiap level ATS.\n"
        "- Buat detail yang cukup untuk pelabel menentukan prioritas, tetapi jangan mengisi output/label ATS.\n\n"
        "HAL_YANG_DIHINDARI:\n"
        "- Jangan menyalin ID, kronologi, frasa panjang, kombinasi gejala, atau tanda vital dari existing.\n"
        "- Hindari frasa repetitif seperti pembukaan dan penutup yang identik di banyak kasus.\n"
        "- Hindari kasus yang hanya berbeda umur atau jenis kelamin tetapi substansi klinisnya sama."
    )

def learn_existing_input_style(input_examples, api_key):
    try:
        return learn_existing_input_style_with_gemini(input_examples, api_key), "Gemini"
    except requests.HTTPError as e:
        status_code = e.response.status_code if e.response is not None else None
        if status_code != 429:
            raise
        return learn_existing_input_style_locally(input_examples), "fallback lokal karena Gemini rate limited"

def post_gemini_generate_content(api_key, prompt, generation_config, timeout=90):
    last_error = None
    for attempt_index in range(len(GEMINI_RETRY_DELAYS) + 1):
        try:
            response = requests.post(
                "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
                headers={
                    "x-goog-api-key": api_key,
                    "Content-Type": "application/json",
                },
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": generation_config,
                },
                timeout=timeout,
            )
            response.raise_for_status()
            return response
        except requests.HTTPError as e:
            last_error = e
            status_code = e.response.status_code if e.response is not None else None
            if status_code not in {429, 500, 502, 503, 504} or attempt_index >= len(GEMINI_RETRY_DELAYS):
                raise
            retry_after = None
            if e.response is not None:
                retry_after_header = e.response.headers.get("Retry-After")
                if retry_after_header:
                    try:
                        retry_after = int(retry_after_header)
                    except ValueError:
                        retry_after = None
        except requests.RequestException as e:
            last_error = e
            if attempt_index >= len(GEMINI_RETRY_DELAYS):
                raise
            retry_after = None

        delay_seconds = retry_after or GEMINI_RETRY_DELAYS[attempt_index]
        time.sleep(delay_seconds)

    raise last_error

def diversify_input_only_with_gemini(draft, api_key, batch_size=1, input_learning_notes=""):
    if not api_key:
        raise ValueError("API key Gemini belum ditemukan dari secret GEMINI_API_KEY.")

    varied_rows = []
    draft = draft.copy()
    for start_index in range(0, len(draft), batch_size):
        if start_index > 0:
            time.sleep(GEMINI_INTER_REQUEST_DELAY_SECONDS)

        batch = draft.iloc[start_index:start_index + batch_size].copy()
        case_text = "\n\n".join(
            (
                f"ID: {row['synthetic_case_id']}\n"
                f"Level target: {row['synthetic_ats_level']} / {row['synthetic_ats_category']}\n"
                f"Narasi awal:\n{row['input'][:1400]}"
            )
            for _, row in batch.iterrows()
        )
        prompt = (
            "Anda membantu membuat data sintetis input triase IGD berbahasa Indonesia. "
            "Tulis ulang setiap narasi agar variasi kasus tinggi, natural, gamblang, dan cukup detail. "
            "Pertahankan level target ATS, tingkat kegawatan, dan tanda vital utama. "
            "Jangan isi instruction_ats/output_ats/validator/status. Jangan menyalin narasi awal secara verbatim. "
            "Variasikan kronologi, pilihan kata, gejala penyerta, riwayat, cara datang, dan observasi triase. "
            "Pastikan narasi baru tidak sama dengan data existing dan tidak terasa seperti parafrase ringan.\n\n"
            f"Panduan gaya input existing yang harus diikuti tanpa menyalin isinya:\n{input_learning_notes or 'Belum ada panduan khusus.'}\n\n"
            f"{case_text}\n\n"
            "Kembalikan hanya dengan format:\n"
            "ID: ATS-SYN-xxxx\n"
            "INPUT: narasi baru satu paragraf atau beberapa paragraf pendek\n\n"
            "Ulangi untuk semua ID, jangan tambah ID baru."
        )
        response = post_gemini_generate_content(
            api_key,
            prompt,
            {
                "temperature": 0.85,
                "maxOutputTokens": 1600,
            },
            timeout=90,
        )
        payload = response.json()
        parts = payload.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        result_text = "\n".join(part.get("text", "") for part in parts).strip()

        parsed_inputs = {}
        current_id = None
        current_lines = []
        for line in result_text.splitlines():
            stripped = line.strip()
            if stripped.startswith("ID:"):
                if current_id and current_lines:
                    parsed_inputs[current_id] = "\n".join(current_lines).strip()
                current_id = stripped.replace("ID:", "", 1).strip()
                current_lines = []
            elif stripped.startswith("INPUT:"):
                current_lines.append(stripped.replace("INPUT:", "", 1).strip())
            elif current_id:
                current_lines.append(line)
        if current_id and current_lines:
            parsed_inputs[current_id] = "\n".join(current_lines).strip()

        for _, row in batch.iterrows():
            row_copy = row.copy()
            varied_input = parsed_inputs.get(row["synthetic_case_id"], "").strip()
            if varied_input:
                row_copy["input"] = varied_input
            row_copy["instruction_ats"] = ""
            row_copy["output_ats"] = ""
            row_copy["validator"] = ""
            row_copy["status"] = ""
            varied_rows.append(row_copy)

    return pd.DataFrame(varied_rows).reset_index(drop=True)

def parse_gemini_input_cases(result_text):
    parsed_inputs = {}
    current_id = None
    current_lines = []
    for line in result_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("ID:"):
            if current_id and current_lines:
                parsed_inputs[current_id] = "\n".join(current_lines).strip()
            current_id = stripped.replace("ID:", "", 1).strip()
            current_lines = []
        elif stripped.startswith("INPUT:"):
            current_lines.append(stripped.replace("INPUT:", "", 1).strip())
        elif current_id:
            current_lines.append(line)
    if current_id and current_lines:
        parsed_inputs[current_id] = "\n".join(current_lines).strip()
    return parsed_inputs

def generate_input_only_cases_with_gemini(existing_data, api_key, input_learning_notes="", total_cases=SYNTHETIC_INPUT_ONLY_TOTAL):
    if not api_key:
        raise ValueError("API key Gemini belum ditemukan dari secret GEMINI_API_KEY.")

    cases_per_level = total_cases // len(ATS_LEVELS)
    start_number = get_next_synthetic_start_number(existing_data)
    clean_examples = get_clean_input_examples(existing_data, limit=20)
    example_text = "\n\n".join(
        f"EXISTING INPUT {index + 1}:\n{example[:1000]}"
        for index, example in enumerate(clean_examples)
    )
    generated_rows = []
    next_number = start_number

    for level_key, level_color, ats_category in ATS_LEVELS:
        target_ids = [
            f"ATS-SYN-{case_number:04d}"
            for case_number in range(next_number, next_number + cases_per_level)
        ]
        next_number += cases_per_level
        prompt = (
            "Anda membuat data input sintetis triase IGD baru dalam bahasa Indonesia. "
            "Pelajari gaya data existing, tetapi buat kasus yang benar-benar berbeda secara klinis dan naratif. "
            "Jangan menyalin kasus, frasa khas, kronologi, kombinasi tanda vital, atau susunan kalimat dari data existing. "
            "Setiap input harus berupa narasi gamblang dan cukup detail: cara datang, kronologi, keluhan utama, "
            "gejala penyerta, kondisi umum, riwayat, observasi triase, dan tanda vital. "
            "Jangan isi instruction_ats, output_ats, validator, atau status.\n\n"
            f"Panduan gaya input existing:\n{input_learning_notes or 'Gunakan gaya narasi IGD natural, detail, dan tidak repetitif.'}\n\n"
            f"Contoh existing yang harus dipelajari gayanya tetapi tidak boleh disalin:\n{example_text}\n\n"
            f"Buat {cases_per_level} kasus baru untuk target {ats_category}/{level_color}. "
            "Pastikan variasi tinggi antar kasus: keluhan, usia, kronologi, gejala penyerta, riwayat, cara datang, "
            "dan tanda vital tidak berpola sama. Gunakan ID berikut persis:\n"
            f"{', '.join(target_ids)}\n\n"
            "Kembalikan hanya dengan format berulang:\n"
            "ID: ATS-SYN-xxxx\n"
            "INPUT: narasi kasus baru\n"
        )
        response = post_gemini_generate_content(
            api_key,
            prompt,
            {
                "temperature": 0.95,
                "maxOutputTokens": 7000,
            },
            timeout=120,
        )
        payload = response.json()
        parts = payload.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        parsed_inputs = parse_gemini_input_cases(
            "\n".join(part.get("text", "") for part in parts).strip()
        )

        local_fallback = generate_synthetic_ats_cases(
            total_cases=SYNTHETIC_FULL_TOTAL,
            seed=20260519 + next_number,
            start_number=900000 + next_number,
        )
        fallback_candidates = local_fallback[local_fallback["synthetic_ats_level"] == level_color].reset_index(drop=True)

        for index, synthetic_id in enumerate(target_ids):
            input_text = parsed_inputs.get(synthetic_id, "").strip()
            if not input_text and not fallback_candidates.empty:
                fallback_row = fallback_candidates.iloc[index % len(fallback_candidates)]
                input_text = fallback_row["input"].replace(fallback_row["synthetic_case_id"], synthetic_id)

            generated_rows.append(
                {
                    "instruction_ats": "",
                    "input": input_text,
                    "output_ats": "",
                    "validator": "",
                    "status": "",
                    "synthetic_case_id": synthetic_id,
                    "synthetic_ats_level": level_color,
                    "synthetic_ats_category": ats_category,
                }
            )

        time.sleep(GEMINI_INTER_REQUEST_DELAY_SECONDS)

    return pd.DataFrame(generated_rows)

def get_problematic_similarity_case_ids(similarity_result):
    if not similarity_result:
        return []

    case_ids = set()
    for pair in similarity_result.get("duplicate_pairs", []):
        case_ids.add(pair.get("kasus_1", ""))
        case_ids.add(pair.get("kasus_2", ""))
    for pair in similarity_result.get("existing_pairs", []):
        case_ids.add(pair.get("kasus_sintetis", ""))
    return sorted(case_id for case_id in case_ids if case_id)

def diversify_problematic_input_only_locally(draft, similarity_result, max_cases=20):
    problematic_ids = get_problematic_similarity_case_ids(similarity_result)[:max_cases]
    if not problematic_ids:
        return draft.copy(), 0

    draft = draft.copy()
    valid_level_colors = {level_color for _, level_color, _ in ATS_LEVELS}
    changed_count = 0

    for offset, synthetic_id in enumerate(problematic_ids):
        row_matches = draft.index[draft["synthetic_case_id"] == synthetic_id].tolist()
        if not row_matches:
            continue

        row_index = row_matches[0]
        target_color = draft.at[row_index, "synthetic_ats_level"]
        if target_color not in valid_level_colors:
            continue

        varied_pool = generate_synthetic_ats_cases(
            total_cases=SYNTHETIC_FULL_TOTAL,
            seed=20260518 + 1000 + offset,
            start_number=900000 + (offset * 700),
        )
        varied_candidates = varied_pool[varied_pool["synthetic_ats_level"] == target_color]
        if varied_candidates.empty:
            continue

        varied_row = varied_candidates.iloc[offset % len(varied_candidates)]
        draft.at[row_index, "input"] = varied_row["input"].replace(varied_row["synthetic_case_id"], synthetic_id)
        draft.at[row_index, "instruction_ats"] = ""
        draft.at[row_index, "output_ats"] = ""
        draft.at[row_index, "validator"] = ""
        draft.at[row_index, "status"] = ""
        changed_count += 1

    return draft.reset_index(drop=True), changed_count

def diversify_problematic_input_only_with_gemini(draft, similarity_result, api_key, max_cases=5, input_learning_notes=""):
    problematic_ids = get_problematic_similarity_case_ids(similarity_result)
    problematic_ids = problematic_ids[:max_cases]
    if not problematic_ids:
        return draft.copy(), 0

    draft = draft.copy()
    target_mask = draft["synthetic_case_id"].isin(problematic_ids)
    target_rows = draft[target_mask].copy()
    varied_rows = diversify_input_only_with_gemini(
        target_rows,
        api_key,
        batch_size=1,
        input_learning_notes=input_learning_notes,
    )
    varied_rows = varied_rows.set_index("synthetic_case_id")

    for index, row in draft[target_mask].iterrows():
        synthetic_id = row["synthetic_case_id"]
        if synthetic_id in varied_rows.index:
            draft.at[index, "input"] = varied_rows.at[synthetic_id, "input"]
            draft.at[index, "instruction_ats"] = ""
            draft.at[index, "output_ats"] = ""
            draft.at[index, "validator"] = ""
            draft.at[index, "status"] = ""

    return draft.reset_index(drop=True), len(problematic_ids)

def normalize_similarity_text(value):
    return " ".join(normalize_cell(value).lower().split())

def get_high_similarity_pairs(candidate_texts, reference_texts=None, threshold=SYNTHETIC_SIMILARITY_THRESHOLD, limit=30):
    candidate_texts = [normalize_similarity_text(text) for text in candidate_texts]
    reference_texts = [normalize_similarity_text(text) for text in reference_texts] if reference_texts is not None else None
    pairs = []

    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity

        if reference_texts is None:
            vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=1)
            matrix = vectorizer.fit_transform(candidate_texts)
            similarity_matrix = cosine_similarity(matrix)
            for left_index in range(len(candidate_texts)):
                for right_index in range(left_index + 1, len(candidate_texts)):
                    score = float(similarity_matrix[left_index, right_index])
                    if score >= threshold:
                        pairs.append((left_index, right_index, score))
        else:
            combined_texts = candidate_texts + reference_texts
            vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=1)
            matrix = vectorizer.fit_transform(combined_texts)
            similarity_matrix = cosine_similarity(matrix[:len(candidate_texts)], matrix[len(candidate_texts):])
            for candidate_index in range(similarity_matrix.shape[0]):
                for reference_index in range(similarity_matrix.shape[1]):
                    score = float(similarity_matrix[candidate_index, reference_index])
                    if score >= threshold:
                        pairs.append((candidate_index, reference_index, score))
    except Exception:
        if reference_texts is None:
            for left_index in range(len(candidate_texts)):
                for right_index in range(left_index + 1, len(candidate_texts)):
                    score = SequenceMatcher(None, candidate_texts[left_index], candidate_texts[right_index]).ratio()
                    if score >= threshold:
                        pairs.append((left_index, right_index, score))
        else:
            for candidate_index, candidate_text in enumerate(candidate_texts):
                for reference_index, reference_text in enumerate(reference_texts):
                    score = SequenceMatcher(None, candidate_text, reference_text).ratio()
                    if score >= threshold:
                        pairs.append((candidate_index, reference_index, score))

    return sorted(pairs, key=lambda item: item[2], reverse=True)[:limit]

def validate_synthetic_similarity(synthetic_data, existing_data, threshold=SYNTHETIC_SIMILARITY_THRESHOLD):
    synthetic_data = synthetic_data.copy()
    synthetic_data["input"] = synthetic_data["input"].fillna("").astype(str).str.strip()
    synthetic_data = synthetic_data[synthetic_data["input"] != ""].copy()

    synthetic_inputs = synthetic_data["input"].tolist()
    synthetic_ids = synthetic_data["synthetic_case_id"].fillna("").astype(str).tolist()
    duplicate_pairs = get_high_similarity_pairs(synthetic_inputs, threshold=threshold)

    existing_inputs = (
        prepare_sheet_data(existing_data)["input"]
        .fillna("")
        .astype(str)
        .str.strip()
    )
    existing_inputs = existing_inputs[existing_inputs != ""].tolist()
    existing_pairs = get_high_similarity_pairs(synthetic_inputs, existing_inputs, threshold=threshold)

    return {
        "duplicate_pairs": [
            {
                "kasus_1": synthetic_ids[left_index],
                "kasus_2": synthetic_ids[right_index],
                "similarity": round(score, 3),
                "input_1": synthetic_inputs[left_index],
                "input_2": synthetic_inputs[right_index],
            }
            for left_index, right_index, score in duplicate_pairs
        ],
        "existing_pairs": [
            {
                "kasus_sintetis": synthetic_ids[candidate_index],
                "baris_existing": reference_index + 1,
                "similarity": round(score, 3),
                "input_sintetis": synthetic_inputs[candidate_index],
                "input_existing": existing_inputs[reference_index],
            }
            for candidate_index, reference_index, score in existing_pairs
        ],
    }

def adjudicate_similarity_with_gemini(similarity_result, api_key, max_pairs=12):
    if not api_key:
        raise ValueError("API key Gemini belum ditemukan dari secret GEMINI_API_KEY.")

    candidate_pairs = []
    for pair in similarity_result.get("duplicate_pairs", []):
        candidate_pairs.append(
            {
                "tipe": "antar_sintetis",
                "label": f"{pair['kasus_1']} vs {pair['kasus_2']}",
                "similarity": pair["similarity"],
                "teks_1": pair["input_1"],
                "teks_2": pair["input_2"],
            }
        )
    for pair in similarity_result.get("existing_pairs", []):
        candidate_pairs.append(
            {
                "tipe": "sintetis_vs_existing",
                "label": f"{pair['kasus_sintetis']} vs existing row {pair['baris_existing']}",
                "similarity": pair["similarity"],
                "teks_1": pair["input_sintetis"],
                "teks_2": pair["input_existing"],
            }
        )

    candidate_pairs = sorted(candidate_pairs, key=lambda item: item["similarity"], reverse=True)[:max_pairs]
    if not candidate_pairs:
        return "Tidak ada kandidat similarity tinggi untuk dinilai Gemini.", False

    pair_text = "\n\n".join(
        (
            f"PASANGAN {idx + 1}\n"
            f"Tipe: {pair['tipe']}\n"
            f"Label: {pair['label']}\n"
            f"Skor similarity awal: {pair['similarity']}\n"
            f"Teks A:\n{pair['teks_1'][:1800]}\n"
            f"Teks B:\n{pair['teks_2'][:1800]}"
        )
        for idx, pair in enumerate(candidate_pairs)
    )
    prompt = (
        "Anda adalah reviewer data triase IGD. Nilai apakah pasangan kasus berikut terlalu mirip secara klinis, "
        "bukan hanya mirip kata-kata. Pertimbangkan keluhan utama, kronologi, tanda vital, tingkat kegawatan, "
        "temuan awal, dan konteks triase.\n\n"
        f"{pair_text}\n\n"
        "Kembalikan jawaban dalam bahasa Indonesia dengan format berikut:\n"
        "RINGKASAN:\n"
        "- jumlah pasangan yang dinilai terlalu mirip secara klinis.\n\n"
        "DETAIL:\n"
        "- [Label pasangan] KEPUTUSAN: TERLALU_MIRIP atau AMAN. ALASAN: ... SARAN_EDIT: ...\n\n"
        "WAJIB_SIMILARITY_BERMASALAH: YA atau TIDAK\n"
        "Gunakan YA jika minimal satu pasangan TERLALU_MIRIP."
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
                "temperature": 0.1,
                "maxOutputTokens": 2200,
            },
        },
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    candidates = payload.get("candidates", [])
    if not candidates:
        raise ValueError("Gemini tidak mengembalikan hasil adjudikasi similarity.")
    parts = candidates[0].get("content", {}).get("parts", [])
    result_text = "\n".join(part.get("text", "") for part in parts).strip()
    if not result_text:
        raise ValueError("Hasil adjudikasi Gemini kosong.")

    has_problem = "WAJIB_SIMILARITY_BERMASALAH: YA" in result_text.upper()
    return result_text, has_problem

def append_synthetic_ats_cases(
    total_cases=SYNTHETIC_FULL_TOTAL,
    synthetic_data=None,
    status_value="Done",
    validator_value="sintetis",
    input_only=False,
):
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

            if input_only:
                synthetic_data["instruction_ats"] = ""
                synthetic_data["output_ats"] = ""
                synthetic_data["validator"] = ""
                synthetic_data["status"] = ""
            else:
                synthetic_data["validator"] = validator_value
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
            updated_indices = []
            append_rows = []
            latest_ids = latest_data["synthetic_case_id"].fillna("").astype(str).str.strip()
            protected_existing_rows = []
            for _, row in synthetic_data.iterrows():
                synthetic_id = str(row.get("synthetic_case_id", "")).strip()
                input_value = str(row.get("input", "")).strip()
                if synthetic_id and synthetic_id in existing_ids:
                    if input_only:
                        continue

                    row_index = latest_ids[latest_ids == synthetic_id].index[0]
                    current_validator = normalize_cell(latest_data.at[row_index, "validator"])
                    if current_validator not in {"", "sintetis"}:
                        protected_existing_rows.append(row_index + 1)
                        continue

                    for col in synthetic_data.columns:
                        latest_data.at[row_index, col] = row.get(col, "")
                    updated_count += 1
                    updated_indices.append(row_index)
                elif input_value not in existing_inputs:
                    append_rows.append(row)

            if protected_existing_rows:
                rows = ", ".join(map(str, protected_existing_rows[:20]))
                st.error(
                    "Tambah data sintetis dibatalkan: ada synthetic_case_id yang sudah dipakai/dipegang user "
                    f"pada baris {rows}. Buat draft batch berikutnya agar tidak menimpa pekerjaan user."
                )
                return 0, len(latest_data)

            missing_data = pd.DataFrame(append_rows)
            if missing_data.empty and updated_count == 0:
                return 0, len(latest_data)

            update_columns = list(synthetic_data.columns)
            if updated_count:
                update_sheet_cells("Sheet1", latest_data, sorted(set(updated_indices)), update_columns)

            if not missing_data.empty:
                missing_data = prepare_sheet_data(missing_data.fillna(""))
                append_sheet_rows("Sheet1", missing_data)

            updated_data = pd.concat([latest_data, missing_data], ignore_index=True, sort=False).fillna("")
            updated_data = prepare_sheet_data(updated_data)
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
        st.session_state["synthetic_ats_draft"] = make_synthetic_draft(df)
    if "synthetic_learning_notes" not in st.session_state:
        st.session_state["synthetic_learning_notes"] = ""
    if "synthetic_similarity_result" not in st.session_state:
        st.session_state["synthetic_similarity_result"] = None
    if "synthetic_gemini_similarity_review" not in st.session_state:
        st.session_state["synthetic_gemini_similarity_review"] = None
    if "synthetic_input_only_draft" not in st.session_state:
        st.session_state["synthetic_input_only_draft"] = make_input_only_synthetic_draft(df)
    if "synthetic_input_only_similarity_result" not in st.session_state:
        st.session_state["synthetic_input_only_similarity_result"] = None
    if "synthetic_input_learning_notes" not in st.session_state:
        st.session_state["synthetic_input_learning_notes"] = ""

    st.session_state["synthetic_ats_draft"] = refill_synthetic_draft(
        st.session_state["synthetic_ats_draft"],
        df,
        st.session_state["synthetic_learning_notes"],
        target_total=SYNTHETIC_FULL_TOTAL,
    )
    st.session_state["synthetic_input_only_draft"] = refill_synthetic_draft(
        st.session_state["synthetic_input_only_draft"],
        df,
        input_only=True,
        target_total=SYNTHETIC_INPUT_ONLY_TOTAL,
    )

    synthetic_preview = st.session_state["synthetic_ats_draft"].copy()
    full_tab, input_only_tab = st.tabs(["Data Sintetis Lengkap", "Input Saja"])
    with full_tab:
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
                    st.session_state["synthetic_ats_draft"] = make_synthetic_draft(df, learned_notes)
                    st.session_state["synthetic_similarity_result"] = None
                    st.session_state["synthetic_gemini_similarity_review"] = None
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
                st.session_state["synthetic_ats_draft"] = make_synthetic_draft(
                    df,
                    st.session_state["synthetic_learning_notes"],
                )
                st.session_state["synthetic_similarity_result"] = None
                st.session_state["synthetic_gemini_similarity_review"] = None
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

        current_draft_start = get_next_synthetic_start_number(synthetic_preview) - len(synthetic_preview)
        current_draft_next_start = get_next_synthetic_start_number(synthetic_preview)
        st.caption(
            f"Rentang ID draft saat ini: ATS-SYN-{current_draft_start:04d} "
            f"sampai ATS-SYN-{current_draft_next_start - 1:04d}."
        )

        edit_col1, edit_col2, edit_col3 = st.columns(3)
        with edit_col1:
            if st.button("Simpan Perubahan Data Ini", use_container_width=True):
                st.session_state["synthetic_ats_draft"].at[selected_index, "input"] = edited_input.strip()
                st.session_state["synthetic_ats_draft"].at[selected_index, "instruction_ats"] = edited_instruction.strip()
                st.session_state["synthetic_ats_draft"].at[selected_index, "output_ats"] = edited_output.strip()
                st.session_state["synthetic_ats_draft"].at[selected_index, "validator"] = "sintetis"
                st.session_state["synthetic_similarity_result"] = None
                st.session_state["synthetic_gemini_similarity_review"] = None
                st.success(f"Perubahan {selected_case_id} disimpan di draft.")
                st.rerun()
        with edit_col2:
            if st.button("Reset Semua Draft Sintetis", use_container_width=True):
                st.session_state["synthetic_ats_draft"] = make_synthetic_draft(
                    df,
                    st.session_state["synthetic_learning_notes"],
                )
                st.session_state["synthetic_similarity_result"] = None
                st.session_state["synthetic_gemini_similarity_review"] = None
                st.success("Draft data sintetis dikembalikan ke versi awal.")
                st.rerun()
        with edit_col3:
            if st.button("Buat Draft 700 Data Berikutnya", use_container_width=True):
                st.session_state["synthetic_ats_draft"] = generate_synthetic_ats_cases(
                    total_cases=SYNTHETIC_FULL_TOTAL,
                    learning_notes=st.session_state["synthetic_learning_notes"],
                    start_number=current_draft_next_start,
                )
                st.session_state["synthetic_similarity_result"] = None
                st.session_state["synthetic_gemini_similarity_review"] = None
                st.success("Draft 700 data berikutnya dibuat dengan ID lanjutan.")
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

        similarity_col1, similarity_col2 = st.columns([1, 2])
        with similarity_col1:
            if st.button("Cek Similarity", use_container_width=True):
                st.session_state["synthetic_similarity_result"] = validate_synthetic_similarity(
                    st.session_state["synthetic_ats_draft"],
                    df,
                )
                st.session_state["synthetic_gemini_similarity_review"] = None
                st.rerun()
        with similarity_col2:
            st.caption(
                f"Ambang similarity: {SYNTHETIC_SIMILARITY_THRESHOLD:.2f}. "
                "Data yang terlalu mirip harus diedit sebelum disimpan."
            )

        similarity_result = st.session_state["synthetic_similarity_result"]
        has_similarity_problem = False
        requires_gemini_similarity_review = False
        has_gemini_similarity_problem = False
        if similarity_result is None:
            st.warning("Cek similarity belum dijalankan untuk draft terbaru.")
            has_similarity_problem = True
        else:
            duplicate_pairs = similarity_result["duplicate_pairs"]
            existing_pairs = similarity_result["existing_pairs"]
            has_similarity_problem = bool(duplicate_pairs or existing_pairs)
            if duplicate_pairs:
                st.error("Ada data sintetis yang terlalu mirip satu sama lain.")
                st.dataframe(
                    pd.DataFrame(duplicate_pairs).drop(columns=["input_1", "input_2"]),
                    use_container_width=True,
                    hide_index=True,
                )
            if existing_pairs:
                st.error("Ada data sintetis yang terlalu mirip dengan input existing.")
                st.dataframe(
                    pd.DataFrame(existing_pairs).drop(columns=["input_sintetis", "input_existing"]),
                    use_container_width=True,
                    hide_index=True,
                )
            if not has_similarity_problem:
                st.success("Similarity aman: tidak ada pasangan yang melewati ambang kemiripan.")
            else:
                requires_gemini_similarity_review = True

                if st.button("Review Similarity dengan Gemini", use_container_width=True):
                    try:
                        review_text, has_problem = adjudicate_similarity_with_gemini(
                            similarity_result,
                            gemini_api_key,
                        )
                        st.session_state["synthetic_gemini_similarity_review"] = {
                            "text": review_text,
                            "has_problem": has_problem,
                        }
                        st.rerun()
                    except Exception as e:
                        st.error(f"Gagal review similarity dengan Gemini: {e}")

                gemini_review = st.session_state["synthetic_gemini_similarity_review"]
                if gemini_review is None:
                    st.warning("Kandidat similarity tinggi perlu direview Gemini sebelum data bisa disimpan.")
                else:
                    has_gemini_similarity_problem = gemini_review["has_problem"]
                    st.text_area(
                        "Hasil review similarity Gemini",
                        value=gemini_review["text"],
                        height=260,
                    )
                    if has_gemini_similarity_problem:
                        st.error("Gemini menilai masih ada pasangan kasus yang terlalu mirip secara klinis.")
                    else:
                        st.success("Gemini menilai kandidat similarity tinggi masih aman secara klinis.")

        can_save_synthetic = (
            confirm_synthetic_append
            and bool(st.session_state["synthetic_learning_notes"])
            and (
                not has_similarity_problem
                or (
                    requires_gemini_similarity_review
                    and st.session_state["synthetic_gemini_similarity_review"] is not None
                    and not has_gemini_similarity_problem
                )
            )
        )
        if confirm_synthetic_append and not st.session_state["synthetic_learning_notes"]:
            st.warning("Jalankan pembelajaran Gemini terlebih dahulu sebelum menyimpan ke Google Sheet.")
        if confirm_synthetic_append and has_similarity_problem:
            st.warning("Selesaikan pengecekan similarity dan review Gemini sebelum menyimpan ke Google Sheet.")
        save_progress_col, save_final_col = st.columns(2)
        with save_progress_col:
            if st.button(
                "Simpan Progress ke Google Sheet",
                use_container_width=True,
                disabled=not can_save_synthetic,
            ):
                saved_count, total_rows_after = append_synthetic_ats_cases(
                    total_cases=SYNTHETIC_FULL_TOTAL,
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
                    total_cases=SYNTHETIC_FULL_TOTAL,
                    synthetic_data=st.session_state["synthetic_ats_draft"],
                    status_value="Done",
                )
                if saved_count:
                    st.success(
                        f"Final {saved_count} data sintetis tersimpan. "
                        f"Total baris sheet sekarang {total_rows_after}."
                    )
                    st.session_state["synthetic_ats_draft"] = generate_synthetic_ats_cases(
                        total_cases=SYNTHETIC_FULL_TOTAL,
                        learning_notes=st.session_state["synthetic_learning_notes"],
                        start_number=current_draft_next_start,
                    )
                    st.rerun()
                else:
                    st.info("Tidak ada data yang disimpan; semua ID/input sudah sama atau terduplikasi.")

    with input_only_tab:
        input_only_preview = st.session_state["synthetic_input_only_draft"].copy()
        st.caption(
            "Mode ini hanya menambahkan 50 data input. Kolom instruction_ats, output_ats, validator, "
            "dan status akan dikosongkan agar data masuk ke pool pelabelan user."
        )
        clean_input_examples = get_clean_input_examples(df)
        st.caption(f"Input existing bersih yang tersedia untuk dipelajari Gemini: {len(clean_input_examples)} contoh.")
        learn_input_col1, learn_input_col2 = st.columns(2)
        with learn_input_col1:
            if st.button("Pelajari Gaya Input Existing", use_container_width=True):
                try:
                    learned_input_notes, learning_source = learn_existing_input_style(
                        clean_input_examples,
                        gemini_api_key,
                    )
                    st.session_state["synthetic_input_learning_notes"] = learned_input_notes
                    st.session_state["synthetic_input_only_similarity_result"] = None
                    st.success(f"Pembelajaran gaya narasi input selesai memakai {learning_source}.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Gagal mempelajari gaya input existing: {e}")
        with learn_input_col2:
            if st.session_state["synthetic_input_learning_notes"]:
                st.success("Panduan gaya input existing sudah tersedia untuk variasi Gemini.")
            else:
                st.info("Pelajari gaya input existing agar variasi Gemini mengikuti pola data sheet tanpa menyalin isinya.")

        if st.session_state["synthetic_input_learning_notes"]:
            st.text_area(
                "Panduan gaya input existing",
                value=st.session_state["synthetic_input_learning_notes"],
                height=160,
            )

        st.dataframe(
            get_synthetic_balance_summary(input_only_preview),
            use_container_width=True,
            hide_index=True,
        )

        input_only_start = get_next_synthetic_start_number(input_only_preview) - len(input_only_preview)
        input_only_next_start = get_next_synthetic_start_number(input_only_preview)
        st.caption(
            f"Rentang ID draft input saja: ATS-SYN-{input_only_start:04d} "
            f"sampai ATS-SYN-{input_only_next_start - 1:04d}."
        )

        input_only_case_options = input_only_preview["synthetic_case_id"].tolist()
        selected_input_only_case_id = st.selectbox(
            "Pilih data input sintetis",
            options=input_only_case_options,
            key="selected_input_only_synthetic_case_id",
        )
        selected_input_only_index = input_only_preview.index[
            input_only_preview["synthetic_case_id"] == selected_input_only_case_id
        ][0]
        selected_input_only_row = input_only_preview.loc[selected_input_only_index]

        input_only_detail_col1, input_only_detail_col2, input_only_detail_col3 = st.columns(3)
        input_only_detail_col1.metric("ID", selected_input_only_row["synthetic_case_id"])
        input_only_detail_col2.metric("Level", selected_input_only_row["synthetic_ats_level"])
        input_only_detail_col3.metric("Kategori", selected_input_only_row["synthetic_ats_category"])

        edited_input_only = st.text_area(
            "Input",
            value=selected_input_only_row["input"],
            height=260,
            key=f"synthetic_input_only_{selected_input_only_case_id}",
        )

        input_only_edit_col1, input_only_edit_col2, input_only_edit_col3 = st.columns(3)
        with input_only_edit_col1:
            if st.button("Simpan Perubahan Input Ini", use_container_width=True):
                st.session_state["synthetic_input_only_draft"].at[selected_input_only_index, "input"] = edited_input_only.strip()
                st.session_state["synthetic_input_only_draft"].at[selected_input_only_index, "instruction_ats"] = ""
                st.session_state["synthetic_input_only_draft"].at[selected_input_only_index, "output_ats"] = ""
                st.session_state["synthetic_input_only_draft"].at[selected_input_only_index, "validator"] = ""
                st.session_state["synthetic_input_only_draft"].at[selected_input_only_index, "status"] = ""
                st.session_state["synthetic_input_only_similarity_result"] = None
                st.success(f"Perubahan {selected_input_only_case_id} disimpan di draft input saja.")
                st.rerun()
        with input_only_edit_col2:
            if st.button("Reset Draft Input Saja", use_container_width=True):
                st.session_state["synthetic_input_only_draft"] = make_input_only_synthetic_draft(df)
                st.session_state["synthetic_input_only_similarity_result"] = None
                st.success("Draft input saja dikembalikan ke versi awal.")
                st.rerun()
        with input_only_edit_col3:
            if st.button("Buat 50 Input Berikutnya", use_container_width=True):
                next_input_only = generate_synthetic_ats_cases(
                    total_cases=SYNTHETIC_INPUT_ONLY_TOTAL,
                    start_number=input_only_next_start,
                )
                next_input_only["instruction_ats"] = ""
                next_input_only["output_ats"] = ""
                next_input_only["validator"] = ""
                next_input_only["status"] = ""
                st.session_state["synthetic_input_only_draft"] = next_input_only
                st.session_state["synthetic_input_only_similarity_result"] = None
                st.success("Draft 50 input berikutnya dibuat dengan ID lanjutan.")
                st.rerun()

        generate_gemini_col1, generate_gemini_col2 = st.columns([1, 2])
        with generate_gemini_col1:
            if st.button(
                "Generate 50 Input Baru dengan Gemini",
                use_container_width=True,
                disabled=not st.session_state["synthetic_input_learning_notes"],
            ):
                try:
                    st.session_state["synthetic_input_only_draft"] = generate_input_only_cases_with_gemini(
                        df,
                        gemini_api_key,
                        input_learning_notes=st.session_state["synthetic_input_learning_notes"],
                        total_cases=SYNTHETIC_INPUT_ONLY_TOTAL,
                    )
                    st.session_state["synthetic_input_only_similarity_result"] = None
                    st.success("Gemini berhasil membuat 50 input baru dari gaya data existing.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Gagal generate 50 input baru dengan Gemini: {e}")
        with generate_gemini_col2:
            st.caption(
                "Pelajari Gaya Input Existing terlebih dahulu. Gemini akan membuat 10 input per level ATS "
                "dengan ID lanjutan dan instruksi agar kasus berbeda dari data existing. Setelah generate, "
                "tetap jalankan Cek Similarity Input Saja sebelum menyimpan."
            )

        problematic_input_count = len(
            get_problematic_similarity_case_ids(st.session_state["synthetic_input_only_similarity_result"])
        )
        gemini_input_col1, gemini_input_col2 = st.columns([1, 2])
        with gemini_input_col1:
            max_gemini_variation_cases = st.number_input(
                "Jumlah maksimal input divariasikan",
                min_value=1,
                max_value=20,
                value=min(5, max(problematic_input_count, 1)),
                step=1,
                disabled=problematic_input_count == 0,
            )
            if st.button(
                "Variasikan Input yang Similar dengan Gemini",
                use_container_width=True,
                disabled=problematic_input_count == 0,
            ):
                try:
                    try:
                        varied_draft, varied_count = diversify_problematic_input_only_with_gemini(
                            st.session_state["synthetic_input_only_draft"],
                        st.session_state["synthetic_input_only_similarity_result"],
                        gemini_api_key,
                        max_cases=int(max_gemini_variation_cases),
                        input_learning_notes=st.session_state["synthetic_input_learning_notes"],
                    )
                        variation_source = "Gemini"
                    except requests.HTTPError as e:
                        status_code = e.response.status_code if e.response is not None else None
                        if status_code != 429:
                            raise
                        varied_draft, varied_count = diversify_problematic_input_only_locally(
                            st.session_state["synthetic_input_only_draft"],
                            st.session_state["synthetic_input_only_similarity_result"],
                            max_cases=int(max_gemini_variation_cases),
                        )
                        variation_source = "fallback lokal karena Gemini masih rate limited"

                    st.session_state["synthetic_input_only_draft"] = varied_draft
                    st.session_state["synthetic_input_only_similarity_result"] = None
                    st.success(
                        f"Variasi narasi {varied_count} input yang terdeteksi similar berhasil dibuat memakai {variation_source}."
                    )
                    st.rerun()
                except Exception as e:
                    st.error(f"Gagal meningkatkan variasi input dengan Gemini: {e}")
        with gemini_input_col2:
            st.caption(
                f"Terdeteksi {problematic_input_count} input similar. Gemini hanya akan menulis ulang input bermasalah "
                "secara bertahap. Jika Gemini tetap rate limited, aplikasi otomatis memakai variasi lokal."
            )

        st.dataframe(
            input_only_preview[
                [
                    "synthetic_case_id",
                    "synthetic_ats_level",
                    "synthetic_ats_category",
                    "input",
                    "instruction_ats",
                    "output_ats",
                    "validator",
                    "status",
                ]
            ],
            use_container_width=True,
            hide_index=True,
        )

        input_only_similarity_col1, input_only_similarity_col2 = st.columns([1, 2])
        with input_only_similarity_col1:
            if st.button("Cek Similarity Input Saja", use_container_width=True):
                st.session_state["synthetic_input_only_similarity_result"] = validate_synthetic_similarity(
                    st.session_state["synthetic_input_only_draft"],
                    df,
                )
                st.rerun()
        with input_only_similarity_col2:
            st.caption(
                f"Ambang similarity: {SYNTHETIC_SIMILARITY_THRESHOLD:.2f}. "
                "Input yang terlalu mirip harus diedit sebelum disimpan."
            )

        input_only_similarity_result = st.session_state["synthetic_input_only_similarity_result"]
        input_only_has_similarity_problem = False
        if input_only_similarity_result is None:
            st.warning("Cek similarity input saja belum dijalankan untuk draft terbaru.")
            input_only_has_similarity_problem = True
        else:
            input_only_duplicate_pairs = input_only_similarity_result["duplicate_pairs"]
            input_only_existing_pairs = input_only_similarity_result["existing_pairs"]
            input_only_has_similarity_problem = bool(input_only_duplicate_pairs or input_only_existing_pairs)
            if input_only_duplicate_pairs:
                st.error("Ada input sintetis yang terlalu mirip satu sama lain.")
                st.dataframe(
                    pd.DataFrame(input_only_duplicate_pairs).drop(columns=["input_1", "input_2"]),
                    use_container_width=True,
                    hide_index=True,
                )
            if input_only_existing_pairs:
                st.error("Ada input sintetis yang terlalu mirip dengan input existing.")
                st.dataframe(
                    pd.DataFrame(input_only_existing_pairs).drop(columns=["input_sintetis", "input_existing"]),
                    use_container_width=True,
                    hide_index=True,
                )
            if not input_only_has_similarity_problem:
                st.success("Similarity input saja aman.")

        confirm_input_only_append = st.checkbox(
            "Saya sudah meninjau input sintetis dan yakin ingin menyimpannya ke Google Sheet.",
            key="confirm_input_only_append",
        )
        if confirm_input_only_append and input_only_has_similarity_problem:
            st.warning("Selesaikan pengecekan similarity input saja sebelum menyimpan.")

        if st.button(
            "Simpan 50 Input Saja ke Google Sheet",
            type="primary",
            use_container_width=True,
            disabled=not confirm_input_only_append or input_only_has_similarity_problem,
        ):
            saved_count, total_rows_after = append_synthetic_ats_cases(
                total_cases=SYNTHETIC_INPUT_ONLY_TOTAL,
                synthetic_data=st.session_state["synthetic_input_only_draft"],
                input_only=True,
            )
            if saved_count:
                st.success(
                    f"Berhasil menyimpan {saved_count} input sintetis. "
                    f"Total baris sheet sekarang {total_rows_after}."
                )
                next_input_only = generate_synthetic_ats_cases(
                    total_cases=SYNTHETIC_INPUT_ONLY_TOTAL,
                    start_number=input_only_next_start,
                )
                next_input_only["instruction_ats"] = ""
                next_input_only["output_ats"] = ""
                next_input_only["validator"] = ""
                next_input_only["status"] = ""
                st.session_state["synthetic_input_only_draft"] = next_input_only
                st.session_state["synthetic_input_only_similarity_result"] = None
                st.rerun()
            else:
                st.info("Tidak ada input baru yang disimpan; semua ID/input sudah sama atau terduplikasi.")

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
