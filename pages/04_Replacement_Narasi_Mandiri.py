from datetime import datetime
from io import BytesIO
from pathlib import Path
import time

import pandas as pd
import requests
import streamlit as st

from sheet_range_update import (
    column_index_to_letter,
    execute_google_request_with_retry,
    get_sheets_values_service,
    get_spreadsheet_id,
    quote_worksheet_name,
)


st.set_page_config(layout="wide", page_title="Replacement Narasi Mandiri")

DELIMITER_TEXT = "----- INI PEMBATAS SAJA -----"
WORKSHEET_NAME = "Sheet1"
LOAD_DATA_TTL_SECONDS = 20
MAX_CELL_CHARS = 50000
AUTOSAVE_DIR = Path("outputs")
AUTOSAVE_XLSX = AUTOSAVE_DIR / "hasil_replacement_huggingface_autosave.xlsx"
AUTOSAVE_CSV = AUTOSAVE_DIR / "hasil_replacement_huggingface_autosave.csv"
SINGLE_REPLACEMENT_USER = "user replacement"
SINGLE_REPLACEMENT_PASSWORD = "novia2313"
BASE_COLUMNS = ["instruction_ats", "input", "output_ats", "validator", "status"]
DEFAULT_MODELS = [
    "deepseek-ai/DeepSeek-V3-0324",
    "Qwen/Qwen2.5-72B-Instruct",
    "Qwen/Qwen2.5-7B-Instruct-1M",
    "meta-llama/Llama-3.3-70B-Instruct",
    "meta-llama/Llama-3.1-8B-Instruct",
]
HF_REQUEST_TIMEOUT_SECONDS = 240
HF_ROW_RETRY_DELAYS = [0, 5, 15]
REPLACEMENT_COLUMNS = [
    "replacement_user",
    "replacement_status",
    "replacement_model",
    "replacement_original_input",
    "replacement_extracted_input",
    "replacement_narrative",
    "replacement_saved_at",
    "replacement_notes",
]
OUTPUT_COLUMNS = [
    "replacement_original_input",
    "replacement_extracted_input",
    "replacement_narrative",
    "replacement_status",
    "replacement_model",
    "replacement_saved_at",
    "hf_replacement_status",
    "hf_replacement_model",
    "hf_replacement_saved_at",
    "hf_replacement_notes",
]
FORBIDDEN_REPLACEMENT_TOPICS = [
    "diagnosis",
    "diagnosa",
    "diagnosa banding",
    "asesmen",
    "assesmen",
    "assessment",
    "kode icd",
    "obat",
    "resep",
    "terapi",
    "dosis",
    "tindakan lanjut",
    "tindak lanjut",
    "penanganan lanjut",
    "penanganan lebih lanjut",
    "rencana",
    "kontrol",
    "rujuk",
    "rawat inap",
]
FOREIGN_LANGUAGE_MARKERS = [
    "patient",
    "complaint",
    "history",
    "examination",
    "diagnosis",
    "treatment",
    "follow up",
    "follow-up",
    "medication",
    "therapy",
    "the patient",
    "el paciente",
    "le patient",
]


def normalize_cell(value):
    if pd.isna(value):
        return ""

    text = str(value).strip()
    if text.lower() in {"nan", "none", "<na>"}:
        return ""
    return text


def clean_text(text):
    cleaned = normalize_cell(text).replace(DELIMITER_TEXT, " ")
    paragraphs = [
        " ".join(paragraph.split())
        for paragraph in cleaned.splitlines()
        if paragraph.strip()
    ]
    return "\n\n".join(paragraphs)


def get_secret_value(*keys):
    for key in keys:
        try:
            value = st.secrets.get(key)
            if value:
                return value
        except Exception:
            pass
    try:
        huggingface = st.secrets.get("huggingface", {})
        if hasattr(huggingface, "get"):
            return huggingface.get("api_token") or huggingface.get("token")
    except Exception:
        pass

    def find_nested_secret(container):
        if not hasattr(container, "items"):
            return ""
        for nested_key, nested_value in container.items():
            if nested_key in keys and nested_value:
                return nested_value
            found_value = find_nested_secret(nested_value)
            if found_value:
                return found_value
        return ""

    try:
        return find_nested_secret(st.secrets)
    except Exception:
        pass
    return ""


def prepare_sheet_data(df):
    sheet_df = df.copy()

    if "instruction_ats" not in sheet_df.columns and "instruksi_ats" in sheet_df.columns:
        sheet_df = sheet_df.rename(columns={"instruksi_ats": "instruction_ats"})
    if "validator" not in sheet_df.columns and "nama_validator" in sheet_df.columns:
        sheet_df = sheet_df.rename(columns={"nama_validator": "validator"})

    for col in BASE_COLUMNS + REPLACEMENT_COLUMNS:
        if col not in sheet_df.columns:
            sheet_df[col] = ""
        sheet_df[col] = sheet_df[col].map(normalize_cell)

    legacy_cols = ["instruksi_ats", "nama_validator"]
    sheet_df = sheet_df.drop(columns=[col for col in legacy_cols if col in sheet_df.columns])

    ordered_cols = (
        BASE_COLUMNS
        + REPLACEMENT_COLUMNS
        + [col for col in sheet_df.columns if col not in BASE_COLUMNS + REPLACEMENT_COLUMNS]
    )
    return sheet_df[ordered_cols]


@st.cache_data(ttl=LOAD_DATA_TTL_SECONDS)
def read_sheet_for_display():
    service = get_sheets_values_service()
    spreadsheet_id = get_spreadsheet_id()
    header_result = execute_google_request_with_retry(
        lambda: service.get(
            spreadsheetId=spreadsheet_id,
            range=f"{quote_worksheet_name(WORKSHEET_NAME)}!1:1",
        )
    )
    header_values = header_result.get("values", [[]])
    headers = [normalize_cell(header) for header in (header_values[0] if header_values else [])]
    headers = [header for header in headers if header]
    if not headers:
        return pd.DataFrame()

    end_column = column_index_to_letter(len(headers))
    result = execute_google_request_with_retry(
        lambda: service.get(
            spreadsheetId=spreadsheet_id,
            range=f"{quote_worksheet_name(WORKSHEET_NAME)}!A:{end_column}",
        )
    )
    values = result.get("values", [])
    if not values:
        return pd.DataFrame()

    rows = values[1:]
    normalized_rows = [
        row + [""] * (len(headers) - len(row))
        for row in rows
    ]
    return pd.DataFrame(normalized_rows, columns=headers)


def clear_display_sheet_cache():
    read_sheet_for_display.clear()


def load_sheet_data():
    last_error = None
    retry_delays = [0, 3, 8, 15, 30]
    for attempt, delay in enumerate(retry_delays, start=1):
        if delay:
            time.sleep(delay)
        try:
            df = read_sheet_for_display()
            if df is not None:
                return prepare_sheet_data(df)
        except Exception as e:
            last_error = e
            clear_display_sheet_cache()

    if last_error:
        st.session_state["sheet_load_error"] = str(last_error)
        st.error(f"Gagal membaca Google Sheet setelah {len(retry_delays)} percobaan: {last_error}")
    return None


def replacement_candidate_mask(df):
    return (
        (df["input"].str.contains(DELIMITER_TEXT, case=False, na=False, regex=False))
        & (df["status"] == "Done")
        & (df["replacement_status"].map(normalize_cell) == "")
        & (df["replacement_user"].map(normalize_cell) == "")
    )


def replacement_pending_mask(df):
    return (
        replacement_candidate_mask(df)
        & (df["hf_replacement_status"] != "Done")
    )


def find_forbidden_terms(text):
    lowered_text = clean_text(text).lower()
    return [
        topic
        for topic in FORBIDDEN_REPLACEMENT_TOPICS
        if topic in lowered_text
    ]


def find_foreign_language_markers(text):
    lowered_text = clean_text(text).lower()
    return [
        marker
        for marker in FOREIGN_LANGUAGE_MARKERS
        if marker in lowered_text
    ]


def build_extraction_prompt(source_text):
    return (
        "Anda adalah asisten ekstraksi data klinis berbahasa Indonesia.\n"
        "Tugas: ambil hanya data klinis yang boleh dipakai untuk membuat narasi kasus triase.\n\n"
        "Aturan wajib:\n"
        "- Seluruh jawaban wajib menggunakan bahasa Indonesia yang baik dan benar. Jangan memakai bahasa Inggris atau bahasa lain.\n"
        "- Gunakan istilah klinis Indonesia yang lazim; istilah medis baku boleh dipakai bila umum digunakan di IGD.\n"
        f"- Hapus seluruh teks pembatas `{DELIMITER_TEXT}`.\n"
        "- Ambil keluhan utama, onset/durasi, gejala penyerta, riwayat relevan, faktor risiko, pemeriksaan fisik, tanda vital, dan hasil pemeriksaan penunjang bila tersedia.\n"
        "- Hilangkan seluruh diagnosis, diagnosa banding, asesmen/assessment, kesimpulan penyakit, kode ICD, obat, resep, terapi farmakologis, dosis, tindakan/prosedur lanjutan, edukasi, rencana kontrol, rujukan, rawat inap, dan instruksi tindak lanjut.\n"
        "- Bila satu kalimat mencampur data observasi dengan diagnosis/obat/tindakan lanjutan, pertahankan hanya data observasinya.\n"
        "- Jangan menambahkan fakta baru.\n"
        "- Tulis hasil sebagai data bersih terstruktur singkat dengan label: Identitas, Keluhan, Riwayat, Pemeriksaan, Penunjang, Catatan.\n"
        "- Jika suatu label tidak punya informasi, jangan tulis label tersebut.\n\n"
        f"Data sumber:\n{source_text}\n\nData klinis bersih:"
    )


def build_generation_prompt(source_text):
    return (
        "Anda adalah asisten penulisan data klinis berbahasa Indonesia.\n"
        "Tugas: ubah data klinis bersih berikut menjadi narasi kasus yang utuh, alami, dan mudah dibaca.\n\n"
        "Aturan wajib:\n"
        "- Seluruh narasi wajib menggunakan bahasa Indonesia yang baik dan benar. Jangan memakai bahasa Inggris atau bahasa lain.\n"
        "- Gunakan gaya bahasa klinis Indonesia yang rapi, natural, dan mudah dipahami tenaga kesehatan.\n"
        f"- Hapus seluruh teks pembatas `{DELIMITER_TEXT}` bila masih ada.\n"
        "- Ubah format bullet, tabel, simbol, singkatan umum, dan potongan frasa menjadi kalimat naratif yang mengalir.\n"
        "- Pertahankan keluhan, onset/durasi, riwayat, faktor risiko, pemeriksaan fisik, tanda vital, dan pemeriksaan penunjang yang tersedia.\n"
        "- Jangan menulis diagnosis, diagnosa banding, asesmen/assessment, kesimpulan penyakit, kode ICD, obat, resep, terapi farmakologis, dosis, tindakan/prosedur lanjutan, edukasi, rencana kontrol, rujukan, rawat inap, atau instruksi tindak lanjut.\n"
        "- Jangan menambahkan fakta baru.\n"
        "- Gunakan bahasa Indonesia klinis yang rapi dalam beberapa paragraf bila diperlukan.\n"
        "- Jangan menulis ulang label SOAP sebagai daftar.\n\n"
        f"Data sumber:\n{source_text}\n\nNarasi kasus:"
    )


def build_replacement_prompt(source_text):
    return (
        "Anda adalah asisten penulisan data klinis berbahasa Indonesia.\n"
        "Tugas: dari data rekam medis mentah, buat data klinis bersih dan narasi replacement.\n\n"
        "Aturan wajib:\n"
        "- Seluruh jawaban wajib menggunakan bahasa Indonesia yang baik dan benar. Jangan memakai bahasa Inggris atau bahasa lain.\n"
        "- Hapus seluruh diagnosis, diagnosa banding, asesmen/assessment, kesimpulan penyakit, kode ICD, obat, resep, terapi farmakologis, dosis, tindakan/prosedur lanjutan, edukasi, rencana kontrol, rujukan, rawat inap, dan instruksi tindak lanjut.\n"
        "- Pertahankan keluhan utama, onset/durasi, gejala penyerta, riwayat relevan, faktor risiko, pemeriksaan fisik, tanda vital, dan hasil penunjang bila tersedia.\n"
        "- Jangan menambahkan fakta baru.\n"
        f"- Hapus teks pembatas `{DELIMITER_TEXT}`.\n"
        "- Kembalikan jawaban dengan format persis:\n"
        "DATA_KLINIS_BERSIH:\n"
        "[data bersih terstruktur singkat]\n\n"
        "NARASI_REPLACEMENT:\n"
        "[narasi klinis rapi dalam bahasa Indonesia]\n\n"
        f"Data sumber:\n{source_text}"
    )


def split_replacement_response(text):
    cleaned = normalize_cell(text)
    marker = "NARASI_REPLACEMENT:"
    if marker in cleaned:
        extracted_part, narrative_part = cleaned.split(marker, 1)
        extracted_part = extracted_part.replace("DATA_KLINIS_BERSIH:", "").strip()
        return clean_text(extracted_part), clean_text(narrative_part)
    return "", clean_text(cleaned.replace("DATA_KLINIS_BERSIH:", ""))


def call_huggingface_model(model_id, prompt, temperature, max_output_tokens, fallback_model_ids=None):
    token = get_secret_value("HUGGINGFACE_API_KEY", "HUGGINGFACE_API_TOKEN", "HF_TOKEN")
    if not token:
        raise ValueError(
            "Token Hugging Face belum ditemukan. Tambahkan HUGGINGFACE_API_KEY, "
            "HUGGINGFACE_API_TOKEN, HF_TOKEN, atau [huggingface].api_token di .streamlit/secrets.toml."
        )

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    model_ids = [model_id]
    for fallback_model_id in fallback_model_ids or []:
        if fallback_model_id not in model_ids:
            model_ids.append(fallback_model_id)

    errors = []
    for current_model_id in model_ids:
        payload = {
            "model": current_model_id,
            "messages": [
                {
                    "role": "system",
                    "content": "Anda menulis ulang data medis menjadi narasi klinis bahasa Indonesia yang baik dan benar.",
                },
                {"role": "user", "content": prompt},
            ],
            "max_tokens": int(max_output_tokens),
            "temperature": float(temperature),
        }
        try:
            response = requests.post(
                "https://router.huggingface.co/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=HF_REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            result = response.json()
        except requests.HTTPError as e:
            status_code = e.response.status_code if e.response is not None else ""
            error_detail = ""
            if e.response is not None:
                try:
                    error_body = e.response.json()
                    error_value = error_body.get("error", "")
                    error_detail = error_value.get("message", "") if isinstance(error_value, dict) else str(error_value)
                except Exception:
                    error_detail = e.response.text[:200]
            errors.append(f"{current_model_id}: HTTP {status_code} {error_detail}".strip())
            if status_code in {400, 402, 403, 404, 429, 503}:
                continue
            raise

        choices = result.get("choices", []) if isinstance(result, dict) else []
        first_choice = choices[0] if choices else {}
        message = first_choice.get("message", {})
        generated_text = normalize_cell(message.get("content", ""))
        finish_reason = normalize_cell(first_choice.get("finish_reason", ""))
        if generated_text:
            return generated_text, current_model_id, finish_reason
        errors.append(f"{current_model_id}: respons kosong")

    raise ValueError(
        "Semua model Hugging Face yang dicoba gagal. Pastikan token memiliki akses Inference Providers "
        "dan kuota/billing Hugging Face aktif. "
        + "; ".join(errors)
    )


def call_huggingface_replacement(model_id, source_text, temperature, max_output_tokens):
    return call_huggingface_model(
        model_id,
        build_replacement_prompt(source_text),
        temperature,
        max_output_tokens,
        DEFAULT_MODELS,
    )


def prepare_dataframe(df):
    prepared_df = df.copy()
    for col in prepared_df.columns:
        prepared_df[col] = prepared_df[col].map(normalize_cell)
    for col in REPLACEMENT_COLUMNS:
        if col not in prepared_df.columns:
            prepared_df[col] = ""
        else:
            prepared_df[col] = prepared_df[col].map(normalize_cell)
    return prepared_df


def dataframe_to_excel_bytes(df):
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="replacement_result")
    return output.getvalue()


def autosave_result(df):
    AUTOSAVE_DIR.mkdir(exist_ok=True)
    df.to_excel(AUTOSAVE_XLSX, index=False, sheet_name="replacement_result")
    df.to_csv(AUTOSAVE_CSV, index=False, encoding="utf-8-sig")


def load_autosave_result():
    if AUTOSAVE_XLSX.exists():
        return prepare_dataframe(pd.read_excel(AUTOSAVE_XLSX))
    if AUTOSAVE_CSV.exists():
        return prepare_dataframe(pd.read_csv(AUTOSAVE_CSV))
    return pd.DataFrame()


def process_rows(df, row_indices, input_column, selected_model, temperature, max_output_tokens, session_key):
    progress_bar = st.progress(0)
    status_area = st.empty()
    total_rows = len(row_indices)

    for position, row_index in enumerate(row_indices, start=1):
        source_text = normalize_cell(df.at[row_index, input_column])
        status_area.info(f"Memproses baris {row_index + 1} ({position}/{total_rows})...")

        last_error = None
        replacement_text = ""
        used_model = selected_model
        finish_reason = ""
        for retry_index, delay in enumerate(HF_ROW_RETRY_DELAYS, start=1):
            if delay:
                status_area.warning(
                    f"Retry baris {row_index + 1} setelah gagal ({retry_index}/{len(HF_ROW_RETRY_DELAYS)})."
                )
                time.sleep(delay)
            try:
                replacement_text, used_model, finish_reason = call_huggingface_replacement(
                    selected_model,
                    source_text,
                    temperature,
                    max_output_tokens,
                )
                break
            except Exception as e:
                last_error = e

        if not replacement_text:
            df.at[row_index, "replacement_original_input"] = source_text[:MAX_CELL_CHARS]
            df.at[row_index, "hf_replacement_model"] = used_model
            df.at[row_index, "hf_replacement_saved_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            df.at[row_index, "hf_replacement_status"] = "Error"
            df.at[row_index, "hf_replacement_notes"] = f"gagal memproses: {last_error}"
            st.session_state[session_key] = df.copy()
            autosave_result(df)
            progress_bar.progress(position / total_rows)
            continue

        cleaned_extracted, cleaned_narrative = split_replacement_response(replacement_text)
        if not cleaned_extracted:
            cleaned_extracted = clean_text(source_text)
        forbidden_terms = find_forbidden_terms(cleaned_narrative)
        foreign_language_markers = find_foreign_language_markers(cleaned_narrative)

        df.at[row_index, "replacement_original_input"] = source_text[:MAX_CELL_CHARS]
        df.at[row_index, "replacement_extracted_input"] = cleaned_extracted[:MAX_CELL_CHARS]
        df.at[row_index, "replacement_narrative"] = cleaned_narrative[:MAX_CELL_CHARS]
        df.at[row_index, "hf_replacement_model"] = used_model
        df.at[row_index, "hf_replacement_saved_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        df.at[row_index, "hf_replacement_status"] = "Review" if forbidden_terms or foreign_language_markers else "Done"

        notes = []
        if finish_reason.lower() in {"length", "max_tokens"}:
            notes.append("output terpotong")
        if forbidden_terms:
            notes.append("cek: " + ", ".join(forbidden_terms))
        if foreign_language_markers:
            notes.append("cek bahasa asing: " + ", ".join(foreign_language_markers))
        df.at[row_index, "hf_replacement_notes"] = "; ".join(notes)

        st.session_state[session_key] = df.copy()
        autosave_result(df)
        progress_bar.progress(position / total_rows)

    status_area.success(f"Selesai memproses {total_rows} baris.")
    return df


if not st.session_state.get("hf_replacement_logged_in", False):
    st.title("Login Replacement Narasi Mandiri")
    st.markdown("### Masuk untuk replacement narasi mandiri")

    col_login, col_info = st.columns([1, 2])
    with col_login:
        selected_user = st.text_input("User:", value=SINGLE_REPLACEMENT_USER)
        password = st.text_input("Password:", type="password", placeholder="Masukkan password")
        if st.button("Masuk", type="primary", use_container_width=True):
            if selected_user.strip() == SINGLE_REPLACEMENT_USER and password == SINGLE_REPLACEMENT_PASSWORD:
                st.session_state["hf_replacement_logged_in"] = True
                st.rerun()
            else:
                st.error("User atau password tidak sesuai.")

    with col_info:
        st.info("Menu ini mengambil data dari Google Sheet, memproses hasilnya di session lokal, dan tidak menulis balik ke Google Sheet.")
    st.stop()


st.sidebar.caption(f"User aktif: {SINGLE_REPLACEMENT_USER}")
if st.sidebar.button("Logout", use_container_width=True):
    st.session_state["hf_replacement_logged_in"] = False
    st.session_state.pop("sheet_replacement_df", None)
    st.session_state.pop("sheet_replacement_summary", None)
    st.rerun()

st.title("Replacement Narasi Mandiri")
st.caption(
    f"Ambil semua data Google Sheet dengan filter input mengandung `{DELIMITER_TEXT}` "
    "status bernilai `Done`, replacement_status kosong, dan replacement_user kosong; "
    "proses lokal per 100 data dengan Hugging Face, lalu unduh satu file gabungan."
)

with st.sidebar.expander("Pengaturan Hugging Face", expanded=True):
    model_choice = st.selectbox("Model Hugging Face:", DEFAULT_MODELS + ["Custom model"], index=0)
    custom_model = st.text_input("Custom model id:", placeholder="contoh: deepseek-ai/DeepSeek-V3-0324")
    selected_model = custom_model.strip() if model_choice == "Custom model" and custom_model.strip() else model_choice
    temperature = st.slider("Temperature", min_value=0.0, max_value=1.5, value=0.4, step=0.1)
    max_output_tokens = st.slider("Max output tokens", min_value=256, max_value=4096, value=1536, step=128)

if not get_secret_value("HUGGINGFACE_API_KEY", "HUGGINGFACE_API_TOKEN", "HF_TOKEN"):
    st.warning(
        "Token Hugging Face belum ditemukan. Isi `HUGGINGFACE_API_KEY` atau `[huggingface].api_token` di `.streamlit/secrets.toml` "
        "sebelum memproses data."
    )

col_load, col_autosave, col_clear = st.columns([1, 1, 1])
with col_load:
    if st.button("Ambil Data dari Google Sheet", type="primary", use_container_width=True):
        clear_display_sheet_cache()
        st.session_state.pop("sheet_load_error", None)
        sheet_df = load_sheet_data()
        if sheet_df is None:
            st.error("Pengambilan data dibatalkan karena Google Sheet belum berhasil dibaca.")
        elif sheet_df.empty:
            st.error("Google Sheet terbaca, tetapi tidak ada data di worksheet.")
        else:
            candidate_df = sheet_df[replacement_candidate_mask(sheet_df)].copy()
            candidate_df = prepare_dataframe(candidate_df)
            st.session_state["sheet_replacement_summary"] = {
                "total_candidate": len(candidate_df),
                "replacement_user_filled": int(candidate_df["replacement_user"].map(normalize_cell).ne("").sum()),
                "replacement_user_empty": int(candidate_df["replacement_user"].map(normalize_cell).eq("").sum()),
                "old_replacement_done": int(candidate_df["replacement_status"].map(normalize_cell).eq("Done").sum()),
            }
            st.session_state["sheet_replacement_df"] = candidate_df
            autosave_result(candidate_df)
            st.success(f"Berhasil mengambil {len(candidate_df)} kandidat replacement dari Google Sheet.")
            st.rerun()
with col_autosave:
    if st.button("Muat Autosave", use_container_width=True):
        autosave_df = load_autosave_result()
        if autosave_df.empty:
            st.warning("File autosave belum ada atau kosong.")
        else:
            st.session_state["sheet_replacement_df"] = autosave_df
            st.session_state["sheet_replacement_summary"] = {
                "total_candidate": len(autosave_df),
                "replacement_user_filled": int(autosave_df["replacement_user"].map(normalize_cell).ne("").sum()) if "replacement_user" in autosave_df.columns else 0,
                "replacement_user_empty": int(autosave_df["replacement_user"].map(normalize_cell).eq("").sum()) if "replacement_user" in autosave_df.columns else 0,
                "old_replacement_done": int(autosave_df["replacement_status"].map(normalize_cell).eq("Done").sum()) if "replacement_status" in autosave_df.columns else 0,
            }
            st.success(f"Autosave dimuat: {len(autosave_df)} baris.")
            st.rerun()
with col_clear:
    if st.button("Bersihkan Data Session", use_container_width=True):
        st.session_state.pop("sheet_replacement_df", None)
        st.session_state.pop("sheet_replacement_summary", None)
        st.rerun()

if "sheet_replacement_df" not in st.session_state:
    st.info("Klik `Ambil Data dari Google Sheet` untuk menarik data yang perlu replacement.")
    st.stop()

df = prepare_dataframe(st.session_state["sheet_replacement_df"].copy())
if df.empty:
    st.warning("Tidak ada data replacement yang memenuhi kriteria.")
    st.stop()

input_column = "input"
replacement_df = df.copy()
if "hf_replacement_status" not in replacement_df.columns:
    replacement_df["hf_replacement_status"] = ""
retry_error_rows = st.checkbox(
    "Coba ulang baris Error",
    value=False,
    help="Aktifkan bila ingin memproses ulang baris yang sebelumnya timeout/gagal.",
)
completed_statuses = ["Done"] if retry_error_rows else ["Done", "Error"]
pending_indices = replacement_df[
    ~replacement_df["hf_replacement_status"].map(normalize_cell).isin(completed_statuses)
].index.tolist()
error_count = int(replacement_df["hf_replacement_status"].map(normalize_cell).eq("Error").sum())
done_count = int(replacement_df["hf_replacement_status"].map(normalize_cell).eq("Done").sum())

summary = st.session_state.get("sheet_replacement_summary", {})
col_total, col_done_session, col_pending_session, col_batch = st.columns(4)
col_total.metric("Total Kandidat Replacement", summary.get("total_candidate", len(replacement_df)))
col_done_session.metric("Selesai Hugging Face", done_count)
col_pending_session.metric("Sisa Diproses Hugging Face", len(pending_indices))
col_batch.metric("Ukuran Batch", min(100, len(pending_indices)) if pending_indices else 0)
if error_count:
    st.warning(f"{error_count} baris gagal diproses dan ditandai Error. Baris ini tetap tersimpan di hasil unduhan.")

st.caption(
    f"Hasil sementara disimpan di session dan autosave lokal: `{AUTOSAVE_XLSX}` serta `{AUTOSAVE_CSV}`."
)

with st.expander("Rincian Filter Google Sheet", expanded=False):
    st.write(
        {
            "kriteria": f"input mengandung `{DELIMITER_TEXT}` dan status = Done",
            "tambahan_filter": "replacement_status kosong dan replacement_user kosong",
            "total_kandidat_diambil": summary.get("total_candidate", len(replacement_df)),
            "replacement_user_kosong": summary.get("replacement_user_empty", 0),
            "replacement_user_terisi_tetap_diambil": summary.get("replacement_user_filled", 0),
            "replacement_status_done_lama_tetap_diambil": summary.get("old_replacement_done", 0),
        }
    )

raw_excel_bytes = dataframe_to_excel_bytes(replacement_df)
raw_csv_bytes = replacement_df.to_csv(index=False).encode("utf-8-sig")
col_raw_excel, col_raw_csv = st.columns(2)
with col_raw_excel:
    st.download_button(
        "Download File Gabungan XLSX",
        data=raw_excel_bytes,
        file_name="file_gabungan_replacement_huggingface.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
with col_raw_csv:
    st.download_button(
        "Download File Gabungan CSV",
        data=raw_csv_bytes,
        file_name="file_gabungan_replacement_huggingface.csv",
        mime="text/csv",
        use_container_width=True,
    )

with st.expander("Preview data yang akan diproses", expanded=True):
    preview_columns = [
        col
        for col in [input_column, "status", "replacement_status", "hf_replacement_status", "replacement_narrative", "hf_replacement_notes"]
        if col in replacement_df.columns
    ]
    st.dataframe(replacement_df[preview_columns].head(50), use_container_width=True, height=320)

batch_size = st.number_input(
    "Jumlah baris diproses sekali jalan:",
    min_value=1,
    max_value=max(1, min(100, len(pending_indices) or 1)),
    value=max(1, min(100, len(pending_indices) or 1)),
)

col_process, col_reset = st.columns([1, 1])
with col_process:
    process_clicked = st.button(
        "Proses 100 Data Berikutnya",
        type="primary",
        use_container_width=True,
        disabled=not pending_indices,
    )
with col_reset:
    if st.button("Reset Hasil Session", use_container_width=True):
        for col in [
            "replacement_original_input",
            "replacement_extracted_input",
            "replacement_narrative",
            "hf_replacement_status",
            "hf_replacement_model",
            "hf_replacement_saved_at",
            "hf_replacement_notes",
        ]:
            if col in df.columns:
                df[col] = ""
        st.session_state["sheet_replacement_df"] = df
        autosave_result(df)
        st.rerun()

if process_clicked:
    selected_indices = pending_indices[: int(batch_size)]
    try:
        st.session_state["sheet_replacement_df"] = process_rows(
            df,
            selected_indices,
            input_column,
            selected_model,
            temperature,
            max_output_tokens,
            "sheet_replacement_df",
        )
        st.rerun()
    except Exception as e:
        st.error(f"Gagal memproses data: {e}")

result_df = st.session_state["sheet_replacement_df"]
excel_bytes = dataframe_to_excel_bytes(result_df)
csv_bytes = result_df.to_csv(index=False).encode("utf-8-sig")

st.markdown("### Unduh Hasil")
col_download_excel, col_download_csv = st.columns(2)
with col_download_excel:
    st.download_button(
        "Download XLSX",
        data=excel_bytes,
        file_name="hasil_replacement_huggingface.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
with col_download_csv:
    st.download_button(
        "Download CSV",
        data=csv_bytes,
        file_name="hasil_replacement_huggingface.csv",
        mime="text/csv",
        use_container_width=True,
    )
