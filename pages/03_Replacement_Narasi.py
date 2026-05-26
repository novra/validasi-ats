import time
from html import escape
from datetime import datetime

import pandas as pd
import requests
import streamlit as st
from streamlit_gsheets import GSheetsConnection

from auth_config import AUTHORIZED_REPLACEMENT_USERS, REPLACEMENT_USER_CREDENTIALS
from sheet_lock import get_sheet_write_lock
from sheet_range_update import update_sheet_cells_with_full_update_fallback


st.set_page_config(layout="wide", page_title="Replacement Narasi")

conn = st.connection("gsheets", type=GSheetsConnection)

DELIMITER_TEXT = "----- INI PEMBATAS SAJA -----"
WORKSHEET_NAME = "Sheet1"
MAX_SHEET_CELL_CHARS = 50000
LOAD_DATA_TTL_SECONDS = 20
BASE_COLUMNS = ["instruction_ats", "input", "output_ats", "validator", "status"]
PROTECTED_LABELING_COLUMNS = {"instruction_ats", "output_ats", "validator", "status"}
REPLACEMENT_COLUMNS = [
    "replacement_user",
    "replacement_status",
    "replacement_model",
    "replacement_original_input",
    "replacement_narrative",
    "replacement_saved_at",
]
DEFAULT_MODELS = [
    "Qwen/Qwen2.5-7B-Instruct-1M",
    "Qwen/Qwen3-4B-Thinking-2507",
    "google/gemma-2-2b-it",
    "meta-llama/Llama-3.1-8B-Instruct:cerebras",
    "openai/gpt-oss-120b:cerebras",
    "deepseek-ai/DeepSeek-V3-0324",
]


st.markdown(
    """
<style>
    .source-box {
        min-height: 520px;
        max-height: 760px;
        overflow-y: auto;
        background: #f8fafc;
        border: 1px solid #cbd5e1;
        border-radius: 8px;
        padding: 16px;
        white-space: pre-wrap;
        line-height: 1.7;
        color: #1f2937;
    }
    .task-header {
        background: #ecfeff;
        border-left: 5px solid #0891b2;
        border-radius: 8px;
        padding: 12px 14px;
        margin: 18px 0 12px 0;
    }
</style>
""",
    unsafe_allow_html=True,
)


def normalize_cell(value):
    if pd.isna(value):
        return ""

    text = str(value).strip()
    if text.lower() in {"nan", "none", "<na>"}:
        return ""
    return text


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
    return conn.read(worksheet=WORKSHEET_NAME, ttl=0)


def clear_display_sheet_cache():
    read_sheet_for_display.clear()


def load_data():
    last_error = None
    for _ in range(3):
        try:
            df = read_sheet_for_display()
            if df is not None and not df.empty:
                return df
            clear_display_sheet_cache()
        except Exception as e:
            last_error = e
        time.sleep(0.5)

    if last_error:
        st.error(f"Gagal membaca Google Sheet: {last_error}")
    return None


def unclaimed_pool_mask(df):
    return (
        (df["input"].str.contains(DELIMITER_TEXT, case=False, na=False, regex=False))
        & (df["status"] == "Done")
        & (df["replacement_status"] != "Done")
        & (df["replacement_user"] == "")
    )


def active_replacement_mask(df, username):
    replacement_status = df["replacement_status"].map(normalize_cell)
    return (
        (df["replacement_user"] == username)
        & (replacement_status != "Done")
        & (
            (replacement_status == "Claimed")
            | (
                df["input"].str.contains(DELIMITER_TEXT, case=False, na=False, regex=False)
                & (df["status"] == "Done")
            )
        )
    )


def merge_update_rows(pending_df, changed_indices, changed_columns, expected_values=None):
    latest_df = conn.read(worksheet=WORKSHEET_NAME, ttl=0)
    if latest_df is None or latest_df.empty:
        raise ValueError("Google Sheet terbaru kosong atau tidak dapat dibaca.")

    latest_data = prepare_sheet_data(latest_df)
    pending_data = prepare_sheet_data(pending_df)

    if len(latest_data) < len(pending_data):
        raise ValueError(
            f"Jumlah baris Google Sheet terbaru ({len(latest_data)}) lebih sedikit dari data lokal ({len(pending_data)})."
        )

    for index in changed_indices:
        if index not in latest_data.index or index not in pending_data.index:
            raise ValueError(f"Baris {index + 1} tidak ditemukan saat sinkronisasi.")

        if expected_values:
            for col, expected_by_row in expected_values.items():
                if col not in latest_data.columns:
                    latest_data[col] = ""
                expected_value = expected_by_row.get(index, "") if isinstance(expected_by_row, dict) else expected_by_row
                if isinstance(expected_value, (list, tuple, set)):
                    expected_matches = normalize_cell(latest_data.at[index, col]) in {
                        normalize_cell(value) for value in expected_value
                    }
                else:
                    expected_matches = normalize_cell(latest_data.at[index, col]) == normalize_cell(expected_value)
                if not expected_matches:
                    raise ValueError(
                        f"Baris {index + 1} sudah berubah di Google Sheet. Muat ulang halaman sebelum menyimpan."
                    )

        for col in changed_columns:
            if col not in latest_data.columns:
                latest_data[col] = ""
            latest_data.at[index, col] = pending_data.at[index, col]

    return latest_data


def update_rows(df, changed_indices, changed_columns, expected_values=None):
    try:
        protected_changes = PROTECTED_LABELING_COLUMNS.intersection(changed_columns)
        if protected_changes:
            protected_list = ", ".join(sorted(protected_changes))
            st.error(f"Penyimpanan replacement dibatalkan: kolom labeling tidak boleh diubah ({protected_list}).")
            return False

        with get_sheet_write_lock():
            sheet_data = merge_update_rows(df, changed_indices, changed_columns, expected_values)
            update_sheet_cells_with_full_update_fallback(
                conn,
                WORKSHEET_NAME,
                sheet_data,
                changed_indices,
                changed_columns,
            )
            clear_display_sheet_cache()
            return True
    except Exception as e:
        st.error(f"Gagal menyimpan ke Google Sheet: {e}")
        return False


def claim_tasks(df, username, batch_size):
    with get_sheet_write_lock():
        latest_df = conn.read(worksheet=WORKSHEET_NAME, ttl=0)
        if latest_df is None or latest_df.empty:
            st.error("Tidak dapat mengambil tugas: Google Sheet kosong atau tidak dapat dibaca.")
            return 0

        latest_data = prepare_sheet_data(latest_df)
        available_indices = latest_data[unclaimed_pool_mask(latest_data)].head(batch_size).index.tolist()
        if not available_indices:
            st.info("Tidak ada data replacement baru yang bisa diambil.")
            return 0

        expected_values = {
            "input": {index: latest_data.at[index, "input"] for index in available_indices},
            "status": {index: "Done" for index in available_indices},
            "replacement_user": {index: "" for index in available_indices},
            "replacement_status": {index: "" for index in available_indices},
        }
        latest_data.loc[available_indices, "replacement_user"] = username
        latest_data.loc[available_indices, "replacement_status"] = "Claimed"
        latest_data.loc[available_indices, "replacement_original_input"] = latest_data.loc[available_indices, "input"]

        if update_rows(
            latest_data,
            available_indices,
            ["replacement_user", "replacement_status", "replacement_original_input"],
            expected_values,
        ):
            return len(available_indices)
        return 0


def build_generation_prompt(source_text):
    return (
        "Anda adalah asisten penulisan data klinis berbahasa Indonesia.\n"
        "Tugas: ubah data rekam medis mentah berikut menjadi narasi kasus yang utuh, lengkap, alami, dan mudah dibaca.\n\n"
        "Aturan wajib:\n"
        f"- Hapus seluruh teks pembatas `{DELIMITER_TEXT}`.\n"
        "- Ubah format SOAP, bullet, tabel, simbol, singkatan umum, dan potongan frasa menjadi kalimat naratif yang mengalir.\n"
        "- Jangan meringkas secara berlebihan. Masukkan seluruh informasi medis penting yang tersedia.\n"
        "- Pertahankan detail keluhan, onset/durasi, riwayat, faktor risiko, pemeriksaan fisik, tanda vital, pemeriksaan penunjang, diagnosis/asesmen, tindakan, terapi, edukasi, dan rencana kontrol bila tersedia.\n"
        "- Jika ada beberapa bagian yang dipisahkan pembatas, gabungkan semuanya menjadi alur kasus yang runtut, bukan memilih salah satu bagian saja.\n"
        "- Jangan menambahkan fakta baru yang tidak ada pada data sumber.\n"
        "- Jika ada bagian yang tidak jelas, tulis secara netral tanpa mengarang.\n"
        "- Gunakan bahasa Indonesia klinis yang rapi. Boleh memakai beberapa paragraf agar informasi tidak hilang.\n"
        "- Jangan menulis ulang label SOAP sebagai daftar.\n\n"
        f"Data sumber:\n{source_text}\n\nNarasi kasus:"
    )


def call_huggingface_model(model_id, source_text, temperature, max_new_tokens, fallback_model_ids=None):
    token = get_secret_value("HUGGINGFACE_API_KEY", "HUGGINGFACE_API_TOKEN", "HF_TOKEN")
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    headers["Content-Type"] = "application/json"

    model_ids = [model_id]
    for fallback_model_id in fallback_model_ids or []:
        if fallback_model_id not in model_ids:
            model_ids.append(fallback_model_id)

    prompt = build_generation_prompt(source_text)
    errors = []
    for current_model_id in model_ids:
        payload = {
            "model": current_model_id,
            "messages": [
                {
                    "role": "system",
                    "content": "Anda menulis ulang data medis mentah menjadi narasi klinis bahasa Indonesia.",
                },
                {"role": "user", "content": prompt},
            ],
            "max_tokens": int(max_new_tokens),
            "temperature": float(temperature),
        }

        try:
            response = requests.post(
                "https://router.huggingface.co/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=120,
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
                    if isinstance(error_value, dict):
                        error_detail = error_value.get("message", "")
                    else:
                        error_detail = str(error_value)
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
        "Semua model yang dicoba gagal melalui Hugging Face Inference Providers. "
        "Pastikan token memiliki permission Inference Providers dan billing/free-tier aktif. "
        + "; ".join(errors)
    )


def clean_narrative(text):
    narrative = normalize_cell(text).replace(DELIMITER_TEXT, " ")
    paragraphs = [
        " ".join(paragraph.split())
        for paragraph in narrative.splitlines()
        if paragraph.strip()
    ]
    return "\n\n".join(paragraphs)


def save_replacement_draft(df, index, row, username, draft_narrative, selected_model):
    cleaned_narrative = clean_narrative(draft_narrative)
    if not cleaned_narrative:
        st.error("Draft narasi wajib diisi sebelum disimpan.")
        return False
    if DELIMITER_TEXT in cleaned_narrative:
        st.error("Draft narasi masih mengandung teks pembatas.")
        return False
    if len(cleaned_narrative) > MAX_SHEET_CELL_CHARS:
        st.error(f"Draft narasi melebihi {MAX_SHEET_CELL_CHARS:,} karakter.")
        return False

    original_input = normalize_cell(row.get("replacement_original_input")) or normalize_cell(row.get("input"))
    expected_values = {
        "input": {index: normalize_cell(row.get("input"))},
        "replacement_user": {index: [username, ""]},
        "replacement_status": {index: [normalize_cell(row.get("replacement_status")), "Claimed", ""]},
        "replacement_original_input": {index: [normalize_cell(row.get("replacement_original_input")), ""]},
    }
    df.at[index, "replacement_user"] = username
    df.at[index, "replacement_status"] = "Claimed"
    df.at[index, "replacement_model"] = st.session_state.get(
        f"replacement_used_model_{index}",
        selected_model,
    )
    df.at[index, "replacement_original_input"] = original_input
    df.at[index, "replacement_narrative"] = cleaned_narrative
    df.at[index, "replacement_saved_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return update_rows(
        df,
        [index],
        [
            "replacement_user",
            "replacement_status",
            "replacement_model",
            "replacement_original_input",
            "replacement_narrative",
            "replacement_saved_at",
        ],
        expected_values,
    )


def save_replacement_final(df, index, row, username, final_narrative, selected_model, original_input):
    cleaned_narrative = clean_narrative(final_narrative)
    if not cleaned_narrative:
        st.error("Narasi final wajib diisi.")
        return False
    if DELIMITER_TEXT in cleaned_narrative:
        st.error("Narasi final masih mengandung teks pembatas.")
        return False
    if len(cleaned_narrative) > MAX_SHEET_CELL_CHARS:
        st.error(f"Narasi final melebihi {MAX_SHEET_CELL_CHARS:,} karakter.")
        return False

    expected_values = {
        "input": {index: normalize_cell(row.get("input"))},
        "status": {index: "Done"},
        "replacement_user": {index: username},
        "replacement_status": {index: normalize_cell(row.get("replacement_status"))},
        "replacement_original_input": {index: normalize_cell(row.get("replacement_original_input"))},
    }
    df.at[index, "input"] = cleaned_narrative
    df.at[index, "replacement_user"] = username
    df.at[index, "replacement_status"] = "Done"
    df.at[index, "replacement_model"] = st.session_state.get(
        f"replacement_used_model_{index}",
        selected_model,
    )
    df.at[index, "replacement_original_input"] = original_input
    df.at[index, "replacement_narrative"] = cleaned_narrative
    df.at[index, "replacement_saved_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return update_rows(
        df,
        [index],
        [
            "input",
            "replacement_user",
            "replacement_status",
            "replacement_model",
            "replacement_original_input",
            "replacement_narrative",
            "replacement_saved_at",
        ],
        expected_values,
    )


if not st.session_state.get("replacement_logged_in", False):
    st.title("Login Replacement Narasi")
    st.markdown("### Masuk sebagai user replacement")

    col_login, col_info = st.columns([1, 2])
    with col_login:
        selected_user = st.selectbox(
            "User:",
            options=AUTHORIZED_REPLACEMENT_USERS,
            index=None,
            placeholder="Pilih user...",
        )
        password = st.text_input("Password:", type="password", placeholder="Masukkan password 6 karakter")

        if st.button("Masuk", type="primary", use_container_width=True):
            if not selected_user:
                st.error("Pilih user terlebih dahulu.")
            elif REPLACEMENT_USER_CREDENTIALS.get(selected_user) == password:
                st.session_state["replacement_logged_in"] = True
                st.session_state["replacement_username"] = selected_user
                st.rerun()
            else:
                st.error("User atau password tidak sesuai.")

    with col_info:
        st.info(
            "User replacement yang tersedia: user 1, user 2, dan user 3. "
            "Tugas hanya mengambil data dengan status Done dan input berisi pembatas."
        )
    st.stop()


username = st.session_state["replacement_username"]

st.markdown(
    """
<style>
    [data-testid="collapsedControl"] { display: none; }
    [data-testid="stSidebarNav"] { display: none; }
</style>
""",
    unsafe_allow_html=True,
)

col_home, col_logout = st.sidebar.columns(2)
with col_home:
    if st.button("Kembali", use_container_width=True):
        st.session_state["replacement_logged_in"] = False
        st.session_state.pop("replacement_username", None)
        st.switch_page("app.py")
with col_logout:
    if st.button("Logout", use_container_width=True):
        st.session_state["replacement_logged_in"] = False
        st.session_state.pop("replacement_username", None)
        st.rerun()

st.sidebar.caption(f"User aktif: {username}")

st.title("Replacement Data Input ke Narasi")
st.caption(f"Filter: kolom input mengandung `{DELIMITER_TEXT}` dan status bernilai `Done`.")

df = load_data()
if df is None or df.empty:
    st.error("Google Sheet kosong atau tidak dapat diakses.")
    st.stop()

df = prepare_sheet_data(df)

available_count = len(df[unclaimed_pool_mask(df)])
my_active_df = df[
    active_replacement_mask(df, username)
].copy()
my_done_count = len(df[(df["replacement_user"] == username) & (df["replacement_status"] == "Done")])
all_done_count = len(df[df["replacement_status"] == "Done"])

st.sidebar.metric("Tersedia", available_count)
st.sidebar.metric("Tugas Aktif Saya", len(my_active_df))
st.sidebar.metric("Selesai Saya", my_done_count)
st.sidebar.metric("Total Replacement Done", all_done_count)

with st.sidebar.expander("Pengaturan Model", expanded=True):
    model_choice = st.selectbox("Model Hugging Face:", DEFAULT_MODELS + ["Custom model"], index=0)
    custom_model = st.text_input("Custom model id:", placeholder="contoh: Qwen/Qwen2.5-7B-Instruct-1M")
    selected_model = custom_model.strip() if model_choice == "Custom model" and custom_model.strip() else model_choice
    temperature = st.slider("Temperature", min_value=0.1, max_value=1.5, value=0.7, step=0.1)
    max_new_tokens = st.slider("Max output tokens", min_value=256, max_value=4096, value=1536, step=128)

auto_save_draft = st.sidebar.toggle(
    "Auto-save draft",
    value=True,
    help="Menyimpan perubahan narasi sebagai draft dengan replacement_status tetap Claimed.",
)

if not get_secret_value("HUGGINGFACE_API_KEY", "HUGGINGFACE_API_TOKEN", "HF_TOKEN"):
    st.warning(
        "Token Hugging Face belum ditemukan di Streamlit secrets. "
        "Generate tetap dicoba tanpa token, tetapi bisa terkena rate limit atau ditolak oleh model tertentu."
    )

with st.form("claim_replacement_form"):
    st.markdown("### Ambil Tugas Replacement")
    batch_size = st.number_input("Jumlah baris yang ingin diambil:", min_value=1, max_value=25, value=5)
    submitted_claim = st.form_submit_button("Ambil Tugas", type="primary", use_container_width=True)
    if submitted_claim:
        claimed = claim_tasks(df, username, batch_size)
        if claimed:
            st.success(f"Berhasil mengambil {claimed} tugas replacement.")
            st.rerun()

st.divider()

if my_active_df.empty:
    st.info("Belum ada tugas aktif. Ambil tugas baru dari panel di atas.")
else:
    st.markdown(f"### Area Kerja ({len(my_active_df)} data)")

for index, row in my_active_df.iterrows():
    original_input = normalize_cell(row.get("replacement_original_input")) or normalize_cell(row.get("input"))
    generated_key = f"replacement_generated_{index}"
    editor_key = f"replacement_editor_{index}"
    pending_editor_key = f"replacement_editor_pending_{index}"
    final_confirm_key = f"replacement_final_confirm_{index}"
    notice_key = f"replacement_notice_{index}"

    if editor_key not in st.session_state:
        st.session_state[editor_key] = normalize_cell(row.get("replacement_narrative"))
    if pending_editor_key in st.session_state:
        st.session_state[editor_key] = st.session_state.pop(pending_editor_key)

    escaped_original_input = escape(original_input)

    st.markdown(
        f"""
        <div class="task-header">
            <strong>Data #{index + 1}</strong> - diklaim oleh {username}
        </div>
        """,
        unsafe_allow_html=True,
    )
    if notice_key in st.session_state:
        st.warning(st.session_state.pop(notice_key))

    col_source, col_editor = st.columns(2, gap="large")
    with col_source:
        st.markdown("**Input Asli**")
        st.markdown(f"<div class='source-box'>{escaped_original_input}</div>", unsafe_allow_html=True)

    with col_editor:
        st.markdown("**Narasi Replacement**")
        narrative_value = st.text_area(
            "Narasi Replacement",
            key=editor_key,
            height=560,
            max_chars=MAX_SHEET_CELL_CHARS,
            label_visibility="collapsed",
            placeholder="Generate dari Hugging Face atau tulis narasi final di sini...",
        )

    saved_narrative = normalize_cell(row.get("replacement_narrative"))
    current_clean_narrative = clean_narrative(st.session_state.get(editor_key, ""))
    if (
        auto_save_draft
        and current_clean_narrative
        and current_clean_narrative != saved_narrative
        and DELIMITER_TEXT not in current_clean_narrative
    ):
        if save_replacement_draft(df, index, row, username, current_clean_narrative, selected_model):
            st.toast(f"Draft Data #{index + 1} tersimpan.", icon="✅")
            row = df.loc[index]

    col_generate, col_copy, col_draft, col_save = st.columns([1.2, 1, 1.1, 1.2], gap="small")
    with col_generate:
        if st.button("Generate Narasi", key=f"generate_{index}", type="primary", use_container_width=True):
            with st.spinner(f"Memanggil model {selected_model}..."):
                try:
                    generated_text, used_model, finish_reason = call_huggingface_model(
                        selected_model,
                        original_input,
                        temperature,
                        max_new_tokens,
                        DEFAULT_MODELS,
                    )
                    cleaned_text = clean_narrative(generated_text)
                    if not cleaned_text:
                        st.error("Model tidak mengembalikan narasi. Coba generate ulang atau pilih model lain.")
                    else:
                        st.session_state[generated_key] = cleaned_text
                        st.session_state[pending_editor_key] = cleaned_text
                        st.session_state[f"replacement_used_model_{index}"] = used_model
                        if finish_reason == "length":
                            st.session_state[notice_key] = (
                                "Narasi kemungkinan masih terpotong karena mencapai batas output token. "
                                "Naikkan Max output tokens lalu generate ulang."
                            )
                        st.success(
                            f"Narasi berhasil dibuat dengan model {used_model}. "
                            "Anda bisa generate ulang atau edit sebelum simpan."
                        )
                        st.rerun()
                except Exception as e:
                    st.error(f"Gagal generate narasi: {e}")

    with col_copy:
        if st.button("Bersihkan Pembatas", key=f"clean_{index}", use_container_width=True):
            st.session_state[pending_editor_key] = clean_narrative(narrative_value)
            st.rerun()

    with col_draft:
        if st.button("Simpan Draft", key=f"save_replacement_draft_{index}", use_container_width=True):
            if save_replacement_draft(df, index, row, username, st.session_state.get(editor_key, ""), selected_model):
                st.success(f"Draft Data #{index + 1} tersimpan. Status tetap Claimed dan masih menjadi tugas aktif.")
                time.sleep(0.3)
                st.rerun()

    with col_save:
        if st.button("Simpan Final", key=f"save_replacement_{index}", use_container_width=True):
            final_narrative = clean_narrative(st.session_state.get(editor_key, ""))
            if not final_narrative:
                st.error("Narasi final wajib diisi.")
            elif DELIMITER_TEXT in final_narrative:
                st.error("Narasi final masih mengandung teks pembatas.")
            elif len(final_narrative) > MAX_SHEET_CELL_CHARS:
                st.error(f"Narasi final melebihi {MAX_SHEET_CELL_CHARS:,} karakter.")
            else:
                st.session_state[final_confirm_key] = True

    if st.session_state.get(final_confirm_key):
        st.warning("data tidak dapat diubah kembali, yakin untuk simpan ?")
        col_confirm_final, col_cancel_final = st.columns([1, 1], gap="small")
        with col_confirm_final:
            if st.button(
                "Ya, Simpan Final",
                key=f"confirm_save_replacement_{index}",
                type="primary",
                use_container_width=True,
            ):
                if save_replacement_final(
                    df,
                    index,
                    row,
                    username,
                    st.session_state.get(editor_key, ""),
                    selected_model,
                    original_input,
                ):
                    st.session_state.pop(final_confirm_key, None)
                    st.success(f"Data #{index + 1} berhasil disimpan sebagai narasi.")
                    time.sleep(0.5)
                    st.rerun()
        with col_cancel_final:
            if st.button("Batal", key=f"cancel_save_replacement_{index}", use_container_width=True):
                st.session_state.pop(final_confirm_key, None)
                st.rerun()

    with st.expander("Preview metadata", expanded=False):
        st.write(
            {
                "row_sheet": index + 1,
                "status": row.get("status", ""),
                "validator": row.get("validator", ""),
                "replacement_status": row.get("replacement_status", ""),
                "model_terpilih": selected_model,
            }
        )

    st.divider()
