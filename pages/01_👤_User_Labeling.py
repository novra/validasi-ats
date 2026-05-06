import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection
import time
from auth_config import AUTHORIZED_USERS, USER_CREDENTIALS
from sheet_lock import get_sheet_write_lock

# --- KONFIGURASI HALAMAN ---
st.set_page_config(layout="wide", page_title="Online ATS Validator")

# --- CSS KUSTOM ---
st.markdown("""
<style>
    .scroll-box {
        height: 300px; overflow-y: auto; padding: 15px;
        border: 1px solid #e5e7eb; border-radius: 8px;
        background-color: #f9fafb; font-size: 14px; color: #1f2937;
    }
    .box-header {
        font-weight: bold; text-transform: uppercase; font-size: 12px;
        margin-bottom: 8px; color: #6b7280; display: block;
    }
    /* Warna Kategori ATS */
    .ats-cat-1 { background-color: #fee2e2; color: #991b1b; padding: 10px; border-radius: 5px; border: 1px solid #fca5a5; }
    .ats-cat-2 { background-color: #ffedd5; color: #9a3412; padding: 10px; border-radius: 5px; border: 1px solid #fdba74; }
    .ats-cat-3 { background-color: #dcfce7; color: #166534; padding: 10px; border-radius: 5px; border: 1px solid #86efac; }
    .ats-cat-4 { background-color: #dbeafe; color: #1e40af; padding: 10px; border-radius: 5px; border: 1px solid #93c5fd; }
    .ats-cat-5 { background-color: #f3f4f6; color: #374151; padding: 10px; border-radius: 5px; border: 1px solid #d1d5db; }
    .ats-title { font-weight: bold; font-size: 1.1em; display: block; border-bottom: 1px solid rgba(0,0,0,0.1); margin-bottom: 5px; padding-bottom: 3px; }
    .ats-list { margin-left: 15px; font-size: 0.85em; }
    
    /* Styling untuk textarea agar lebih legah */
    .stTextArea > div > div > textarea {
        background-color: #f9fafb !important;
        border: 2px solid #e5e7eb !important;
        border-radius: 8px !important;
        font-size: 14px !important;
        padding: 12px !important;
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif !important;
        line-height: 1.6 !important;
    }
    
    .stTextArea > div > div > textarea:focus {
        border-color: #3b82f6 !important;
        box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1) !important;
    }
    
    /* Styling untuk disabled textarea */
    .stTextArea > div > div > textarea:disabled {
        background-color: #f3f4f6 !important;
        color: #6b7280 !important;
        cursor: not-allowed !important;
    }
    
    /* Styling khusus untuk INPUT reference box */
    .input-reference-box {
        background: linear-gradient(135deg, #fef3f2 0%, #fef9f7 100%);
        border: 3px solid #f4a261;
        border-radius: 10px;
        padding: 18px;
        margin-bottom: 25px;
        color: #2d2d2d;
        font-size: 16px;
        line-height: 1.8;
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        word-wrap: break-word;
        white-space: pre-wrap;
        box-shadow: 0 2px 8px rgba(244, 162, 97, 0.15);
    }
    
    .input-reference-header {
        font-weight: 700;
        color: #e76f51;
        font-size: 14px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        margin-bottom: 12px;
        padding-bottom: 8px;
        border-bottom: 2px solid #e76f51;
        display: flex;
        align-items: center;
        gap: 8px;
    }
    
    /* Meningkatkan visibility textarea untuk instruction dan output */
    .work-textarea .stTextArea > div > div > textarea {
        background-color: #ffffff !important;
        border: 2px solid #cbd5e1 !important;
        border-radius: 8px !important;
        font-size: 15px !important;
        padding: 14px !important;
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif !important;
        line-height: 1.7 !important;
        color: #1f2937 !important;
    }
    
    .work-textarea .stTextArea > div > div > textarea:focus {
        border-color: #0ea5e9 !important;
        box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.2) !important;
    }
    
    .work-textarea .stTextArea > div > div > textarea:disabled {
        background-color: #f1f5f9 !important;
        color: #64748b !important;
        border-color: #cbd5e1 !important;
    }
</style>
""", unsafe_allow_html=True)

# --- KONEKSI KE GOOGLE SHEETS ---
conn = st.connection("gsheets", type=GSheetsConnection)

SHEET_COLUMNS = ['instruction_ats', 'input', 'output_ats', 'validator', 'status']
MIN_NONEMPTY_INPUT_ROWS = 1
MAX_SHEET_CELL_CHARS = 50000
LENGTH_LIMIT_COLUMNS = ['instruction_ats', 'output_ats']

def normalize_cell(value):
    if pd.isna(value):
        return ''

    text = str(value).strip()
    if text.lower() in {'nan', 'none', '<na>'}:
        return ''
    return text

def has_required_ats_fields(row):
    return (
        normalize_cell(row.get('instruction_ats', '')) != ''
        and normalize_cell(row.get('output_ats', '')) != ''
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

def get_current_ats_length_violations(index, instruction_value, output_value):
    values = {
        'instruction_ats': instruction_value,
        'output_ats': output_value,
    }
    return [
        (index + 1, col, len(normalize_cell(value)))
        for col, value in values.items()
        if len(normalize_cell(value)) > MAX_SHEET_CELL_CHARS
    ]

def show_length_violation_error(violations, action_label="Penyimpanan"):
    details = ", ".join(
        f"baris {row} kolom {col}: {length:,} karakter"
        for row, col, length in violations
    )
    st.error(
        f"{action_label} dibatalkan: {details}. "
        f"Batas maksimal Google Sheets adalah {MAX_SHEET_CELL_CHARS:,} karakter per cell."
    )

def fill_ats_shortcut(index, value):
    st.session_state[f"instr_{index}"] = value
    st.session_state[f"output_{index}"] = value

def sync_task_widget_state(index, row):
    source_signature = (
        normalize_cell(row.get('input', '')),
        normalize_cell(row.get('instruction_ats', '')),
        normalize_cell(row.get('output_ats', '')),
        normalize_cell(row.get('status', '')),
    )
    source_key = f"task_source_{index}"

    if st.session_state.get(source_key) != source_signature:
        st.session_state[f"instr_{index}"] = source_signature[1]
        st.session_state[f"output_{index}"] = source_signature[2]
        st.session_state[source_key] = source_signature

@st.cache_resource
def get_claim_lock():
    return get_sheet_write_lock()

def get_available_data_mask(data):
    return (
        (data['input'] != '')
        & (data['instruction_ats'] == '')
        & (data['output_ats'] == '')
        & (data['validator'] == '')
        & (data['status'] == '')
    )

@st.cache_data(ttl=0)
def load_data():
    last_error = None
    for _ in range(3):
        try:
            df = conn.read(worksheet="Sheet1", ttl=0)
            if df is not None and not df.empty:
                return df
        except Exception as e:
            last_error = e
        time.sleep(0.5)

    if last_error:
        st.error(f"Error membaca Google Sheet: {last_error}")
    return df if 'df' in locals() else None

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
                if not isinstance(allowed_values, (list, tuple, set)):
                    allowed_values = [allowed_values]
                latest_value = normalize_cell(latest_data.at[index, col])
                allowed_values = {normalize_cell(value) for value in allowed_values}
                if latest_value not in allowed_values:
                    raise ValueError(
                        f"Baris {index + 1} sudah berubah di Google Sheet. Muat ulang halaman sebelum menyimpan."
                    )

        for col in changed_columns:
            if col not in pending_data.columns:
                raise ValueError(f"Kolom {col} tidak ditemukan saat sinkronisasi.")
            if col not in latest_data.columns:
                latest_data[col] = ''
            latest_data.at[index, col] = pending_data.at[index, col]

    return latest_data

def update_data(df, changed_indices=None, changed_columns=None, expected_values=None, show_errors=True):
    with get_claim_lock():
        return update_data_unlocked(df, changed_indices, changed_columns, expected_values, show_errors)

def update_data_unlocked(df, changed_indices=None, changed_columns=None, expected_values=None, show_errors=True):
    try:
        expected_rows = st.session_state.get('loaded_sheet_rows')
        if df is None or df.empty:
            if show_errors:
                st.error("Penyimpanan dibatalkan: data yang akan ditulis kosong.")
            return False

        if changed_indices is None or changed_columns is None:
            if show_errors:
                st.error("Penyimpanan dibatalkan: perubahan baris/kolom tidak diketahui.")
            return False

        sheet_data = merge_with_latest_sheet(df, changed_indices, changed_columns, expected_values)
        nonempty_input_rows = sheet_data['input'].fillna('').astype(str).str.strip().ne('').sum()

        if nonempty_input_rows < MIN_NONEMPTY_INPUT_ROWS:
            if show_errors:
                st.error("Penyimpanan dibatalkan: kolom input terbaca kosong. Muat ulang data sebelum mencoba lagi.")
            return False

        if expected_rows is not None and len(sheet_data) < expected_rows:
            if show_errors:
                st.error(
                    f"Penyimpanan dibatalkan: jumlah baris turun dari {expected_rows} ke {len(sheet_data)}. "
                    "Ini mencegah Google Sheet tertimpa oleh data hasil filter."
                )
            return False

        done_without_required_fields = [
            index + 1
            for index in changed_indices
            if index in sheet_data.index
            and normalize_cell(sheet_data.at[index, 'status']) == "Done"
            and not has_required_ats_fields(sheet_data.loc[index])
        ]
        if done_without_required_fields:
            if show_errors:
                rows = ", ".join(map(str, done_without_required_fields))
                st.error(
                    f"Penyimpanan dibatalkan: baris {rows} belum mengisi instruction_ats dan output_ats."
                )
            return False

        length_violations = get_ats_length_violations(sheet_data, changed_indices)
        if length_violations:
            if show_errors:
                show_length_violation_error(length_violations)
            return False

        conn.update(worksheet="Sheet1", data=sheet_data)
        st.session_state['loaded_sheet_rows'] = len(sheet_data)
        # Clear cache untuk force reload data
        load_data.clear()
        st.cache_data.clear()
        return True
    except Exception as e:
        if show_errors:
            st.error(f"Gagal menyimpan ke Google Sheets: {e}")
        return False

def claim_new_tasks(batch_size):
    with get_claim_lock():
        available_indices = []
        for _ in range(3):
            latest_df = conn.read(worksheet="Sheet1", ttl=0)
            if latest_df is None or latest_df.empty:
                st.error("Tidak dapat mengambil tugas: Google Sheet kosong atau tidak dapat dibaca.")
                return 0

            latest_data = prepare_sheet_data(latest_df)
            available_indices = latest_data[get_available_data_mask(latest_data)].head(batch_size).index

            if len(available_indices) == 0:
                st.error("Data habis diambil orang lain!")
                return 0

            latest_data.loc[available_indices, 'validator'] = username
            latest_data.loc[available_indices, 'status'] = ''

            saved = update_data_unlocked(
                latest_data,
                list(available_indices),
                ['validator', 'status'],
                expected_values={
                    'instruction_ats': '',
                    'output_ats': '',
                    'validator': '',
                    'status': ''
                },
                show_errors=False
            )
            if saved:
                break
        else:
            st.warning("Tugas yang tersedia baru saja berubah. Silakan klik Ambil Tugas Baru lagi.")
            load_data.clear()
            st.cache_data.clear()
            return 0

        verified_df = conn.read(worksheet="Sheet1", ttl=0)
        verified_data = prepare_sheet_data(verified_df)
        verified_count = len(
            [
                index for index in available_indices
                if index in verified_data.index
                and verified_data.at[index, 'validator'] == username
                and verified_data.at[index, 'instruction_ats'] == ''
                and verified_data.at[index, 'output_ats'] == ''
                and verified_data.at[index, 'status'] == ''
            ]
        )

        if verified_count != len(available_indices):
            st.error("Sebagian tugas gagal dikunci karena ada update bersamaan. Silakan ambil ulang.")
            load_data.clear()
            st.cache_data.clear()
            return 0

        return verified_count

def auto_save_progress(df, index):
    if index not in df.index:
        return

    if df.at[index, 'status'] == "Done":
        return

    instr_key = f"instr_{index}"
    output_key = f"output_{index}"
    current_instr = st.session_state.get(instr_key, "")
    current_output = st.session_state.get(output_key, "")

    if (
        df.at[index, 'instruction_ats'] == current_instr
        and df.at[index, 'output_ats'] == current_output
        and df.at[index, 'status'] == "Pending"
    ):
        return

    expected_instruction = df.at[index, 'instruction_ats']
    expected_output = df.at[index, 'output_ats']

    df.at[index, 'instruction_ats'] = current_instr
    df.at[index, 'output_ats'] = current_output
    df.at[index, 'validator'] = username
    df.at[index, 'status'] = "Pending"

    if update_data(
        df,
        [index],
        ['instruction_ats', 'output_ats', 'validator', 'status'],
        expected_values={
            'instruction_ats': expected_instruction,
            'output_ats': expected_output,
            'validator': username,
            'status': ['', 'Pending']
        }
    ):
        st.toast("Progress tersimpan otomatis.", icon="✅")

def show_ats_guidance():
    with st.expander("📘 PANDUAN TRIASE ATS (KLIK UNTUK MEMBUKA)", expanded=False):
        cols = st.columns(5)
        with cols[0]:
            st.markdown("<div class='ats-cat-1'><span class='ats-title'>KAT 1: SEGERA (Red)</span><ul class='ats-list'><li>Henti Jantung/Napas</li><li>Sumbatan Jalan Napas</li><li>Kejang Terus Menerus</li><li>GCS < 9 (Koma)</li><li>Ancaman Kekerasan Segera</li></ul></div>", unsafe_allow_html=True)
        with cols[1]:
            st.markdown("<div class='ats-cat-2'><span class='ats-title'>KAT 2: 10 MENIT (Orange)</span><ul class='ats-list'><li>Nyeri Dada Kardiak</li><li>Sesak Berat/Stridor</li><li>Sepsis (Tak Stabil)</li><li>GCS < 13 (Bingung)</li><li>Nyeri Hebat (7-10)</li><li>Stroke Akut</li></ul></div>", unsafe_allow_html=True)
        with cols[2]:
            st.markdown("<div class='ats-cat-3'><span class='ats-title'>KAT 3: 30 MENIT (Green)</span><ul class='ats-list'><li>Hipertensi Berat</li><li>Sesak Sedang</li><li>Nyeri Sedang (4-6)</li><li>Sepsis (Stabil)</li><li>Cedera Tungkai Sedang</li><li>Anak Berisiko</li></ul></div>", unsafe_allow_html=True)
        with cols[3]:
            st.markdown("<div class='ats-cat-4'><span class='ats-title'>KAT 4: 60 MENIT (Blue)</span><ul class='ats-list'><li>Perdarahan Ringan</li><li>Cedera Kepala Ringan</li><li>Nyeri Sedang (Berisiko)</li><li>Muntah/Diare (Tanpa Dehidrasi)</li><li>Trauma Minor</li></ul></div>", unsafe_allow_html=True)
        with cols[4]:
            st.markdown("<div class='ats-cat-5'><span class='ats-title'>KAT 5: 120 MENIT (White)</span><ul class='ats-list'><li>Nyeri Minimal</li><li>Luka Minor (Lecet)</li><li>Ganti Perban/Kontrol</li><li>Imunisasi</li><li>Gejala Kronis</li></ul></div>", unsafe_allow_html=True)

if 'username' not in st.session_state:
    st.title("🔐 Login Tim Validator")
    st.markdown("### Silakan pilih nama dan masukkan password Anda untuk mulai bekerja")
    
    col1, col2 = st.columns([1, 2])
    with col1:
        selected_user = st.selectbox(
            "Nama Validator:",
            options=AUTHORIZED_USERS,
            index=None,
            placeholder="Pilih nama Anda..."
        )
        user_password = st.text_input(
            "Password:",
            type="password",
            placeholder="Masukkan password 6 karakter"
        )
        
        if st.button("🔓 Masuk", type="primary", use_container_width=True):
            if not selected_user:
                st.error("Silakan pilih nama terlebih dahulu!")
            elif not user_password:
                st.error("Silakan masukkan password Anda!")
            elif len(user_password) != 6:
                st.error("Password harus terdiri dari 6 karakter!")
            elif USER_CREDENTIALS.get(selected_user) == user_password:
                st.session_state['username'] = selected_user
                st.rerun()
            else:
                st.error("Nama atau password tidak sesuai!")
    
    with col2:
        st.info("""
        **Authorized Users:**
        - dr.Dhaifina
        - dr.Dian
        - dr.Natalia
        - dr.Wulan

        Gunakan password unik 6 karakter sesuai akun masing-masing.
        """)
    st.stop()

# --- APP UTAMA ---
username = st.session_state['username']

# Hide automatic page navigation untuk user yang sudah login
st.markdown("""
<style>
    /* Hide page navigation dari sidebar ketika user sudah login */
    [data-testid="collapsedControl"] { display: none; }
    [data-testid="stSidebarNav"] { display: none; }
</style>
""", unsafe_allow_html=True)

st.sidebar.header(f"👤 User: {username}")
st.sidebar.divider()

# Tombol navigasi custom
col1, col2 = st.sidebar.columns(2)
with col1:
    if st.sidebar.button("🏠 Kembali", use_container_width=True, help="Kembali ke halaman utama"):
        del st.session_state['username']
        st.switch_page("app.py")

with col2:
    if st.sidebar.button("🚪 Logout", use_container_width=True):
        del st.session_state['username']
        st.rerun()

st.sidebar.divider()

st.title("🏥 Validator ATS Online")
show_ats_guidance()

# --- LOAD DATA ---
try:
    df = load_data()
    
    if df is None or df.empty:
        st.error("❌ Data dari Google Sheet kosong atau tidak dapat diakses!")
        st.info("💡 Pastikan:")
        st.info("   1. Google Sheet sudah dikonfigurasi di Streamlit secrets")
        st.info("   2. Sheet memiliki kolom: instruction_ats, input, output_ats, validator, status")
        st.info("   3. Data sudah tersedia di Sheet1")
        st.stop()

    st.session_state['loaded_sheet_rows'] = len(df)
    
    # Cek kolom yang tersedia (gunakan nama kolom dari Google Sheet)
    # Priority: gunakan kolom yang sudah ada, jika tidak ada buat baru
    if 'instruction_ats' not in df.columns and 'instruksi_ats' in df.columns:
        df.rename(columns={'instruksi_ats': 'instruction_ats'}, inplace=True)
    elif 'instruction_ats' not in df.columns:
        df['instruction_ats'] = ""
    
    if 'validator' not in df.columns and 'nama_validator' in df.columns:
        df.rename(columns={'nama_validator': 'validator'}, inplace=True)
    elif 'validator' not in df.columns:
        df['validator'] = ""
    
    # Pastikan kolom penting ada
    required_cols = ['instruction_ats', 'input', 'output_ats', 'status', 'validator']
    for col in required_cols:
        if col not in df.columns:
            df[col] = ""
    
    # KONVERSI DATA KE STRING - LEBIH ROBUST
    # Handle NaN, None, dan nilai null lainnya
    for col in required_cols:
        df[col] = df[col].fillna('').astype(str).str.strip()
        # Hilangkan string 'nan' 
        df[col] = df[col].replace('nan', '').str.strip()
        # Hilangkan 'none' (case-insensitive)
        df[col] = df[col].mask(df[col].str.lower() == 'none', '')
        # Final strip setelah semua cleaning
        df[col] = df[col].str.strip()
    
    # Debug info (untuk test purposes)
    if 'debug_mode' not in st.session_state:
        st.session_state['debug_mode'] = False
    
    # Show debug toggle di sidebar
    if st.sidebar.checkbox("🔍 Debug Mode", value=False):
        st.sidebar.write(f"**Total baris Google Sheet:** {len(df)}")
        st.sidebar.write(f"**Kolom yang ada:** {list(df.columns)}")
        
        # Debug breakdown untuk data availability
        st.sidebar.divider()
        st.sidebar.write("**DEBUG: Data Availability Breakdown**")
        
        data_with_input = len(df[df['input'] != ''])
        data_with_empty_validator = len(df[df['validator'] == ''])
        data_with_empty_status = len(df[df['status'] == ''])
        data_with_done_status = len(df[df['status'] == 'Done'])
        data_with_empty_or_done = len(df[(df['status'] == '') | (df['status'] == 'Done')])
        
        st.sidebar.write(f"✓ Data dengan input terisi: {data_with_input}")
        st.sidebar.write(f"✓ Data dengan validator kosong: {data_with_empty_validator}")
        st.sidebar.write(f"✓ Data dengan status kosong: {data_with_empty_status}")
        st.sidebar.write(f"✓ Data dengan status 'Done': {data_with_done_status}")
        st.sidebar.write(f"✓ Data dengan status kosong/Done: {data_with_empty_or_done}")
        
        available_count = len(df[get_available_data_mask(df)])
        st.sidebar.write(f"🎯 **DATA TERSEDIA (hanya input terisi): {available_count}**")
        
        st.sidebar.divider()
        st.sidebar.write("**Data Preview:**")
        st.sidebar.dataframe(df.head(3), use_container_width=True)
        
        st.sidebar.write("**Status Values (Sample):**")
        st.sidebar.write(df[['input', 'validator', 'status']].head(10))
    
except Exception as e:
    st.error(f"❌ Gagal memuat data: {e}")
    import traceback
    st.error(traceback.format_exc())
    st.stop()

# --- LOGIKA DATA TERSEDIA (PENDING vs DONE) ---
# Data tersedia untuk diambil jika:
# 1. Kolom input tidak kosong (harus ada input untuk diproses)
# 2. Kolom instruction_ats kosong
# 3. Kolom output_ats kosong
# 4. Kolom validator kosong (belum diambil siapapun)
# 5. Kolom status kosong (belum pernah dikerjakan)

has_input_mask = df['input'] != ''
available_data_mask = get_available_data_mask(df)

# Data milik user ini
my_all_tasks = df[has_input_mask & (df['validator'] == username)]

# Data milik user ini yang BELUM SELESAI (Status bukan 'Done')
# Termasuk: data baru (status kosong), data sedang dikerjakan, etc
# TIDAK termasuk: data yang sudah Done
my_pending_tasks = my_all_tasks[my_all_tasks['status'] != 'Done']
my_done_tasks = my_all_tasks[my_all_tasks['status'] == 'Done']

# Hitung Statistik
sisa_pool = len(df[available_data_mask])
total_dikerjakan_saya = len(my_all_tasks)
sisa_tugas_saya = len(my_pending_tasks)
selesai_saya = len(my_done_tasks)

st.sidebar.divider()
st.sidebar.metric("📊 Sisa Data Tersedia", sisa_pool)
st.sidebar.metric("📋 Total Tugas Saya", total_dikerjakan_saya)
st.sidebar.metric("✅ Selesai Saya", selesai_saya)
st.sidebar.metric("⏳ Tugas Aktif Saya", sisa_tugas_saya)

# --- BAGIAN AMBIL TUGAS ---
# Tombol ambil tugas muncul jika:
# 1. TIDAK ADA tugas aktif (pending == 0)
# 2. Ada data tersedia di pool (sisa_pool > 0)

if sisa_tugas_saya == 0 and sisa_pool > 0:
    if total_dikerjakan_saya > 0:
        st.success("🎉 Hebat! Anda telah menyelesaikan semua tugas sebelumnya. Siap ambil lagi?")
    else:
        st.info("👋 Halo! Anda belum memiliki tugas aktif.")
    
    with st.form("ambil_tugas_form"):
        st.write("### 📥 Ambil paket data baru untuk dilabeli")
        batch_size = st.number_input("Jumlah baris yang ingin diambil:", min_value=5, max_value=100, value=10)
        
        col1, col2 = st.columns(2)
        with col1:
            submitted = st.form_submit_button("🚀 Ambil Tugas Baru", type="primary", use_container_width=True)
        with col2:
            st.form_submit_button("❌ Batal", use_container_width=True)
        
        if submitted:
            with st.spinner("Mengambil data..."):
                claimed_count = claim_new_tasks(batch_size)
                if claimed_count > 0:
                    st.success(f"Berhasil mengambil {claimed_count} data baru!")
                    time.sleep(1)
                    st.rerun()

# --- BAGIAN AREA KERJA ---
show_history = st.checkbox("📚 Tampilkan riwayat tugas yang sudah selesai", value=False)

if show_history:
    # Tampilkan semua tugas milik user (Active + Done)
    working_df = my_all_tasks.copy()
    st.subheader(f"📋 Semua Tugas Saya ({len(working_df)} data)")
else:
    # Tampilkan hanya tugas aktif (Pending)
    working_df = my_pending_tasks.copy()
    st.subheader(f"📝 Area Kerja - Tugas Aktif ({len(working_df)} data)")

if not working_df.empty:
    for index, row in working_df.iterrows():
        with st.container():
            # Tanda visual jika sudah selesai
            is_done = row.get('status') == 'Done'
            sync_task_widget_state(index, row)
            status_icon = "✅ SELESAI" if is_done else "⏳ BELUM SELESAI"
            
            # Header dengan status
            header_color = "#dcfce7" if is_done else "#dbeafe"
            st.markdown(f"""
            <div style="background-color:{header_color}; padding: 12px; border-radius: 8px; margin-bottom: 20px; border-left: 5px solid {'#16a34a' if is_done else '#1e40af'};">
                <h3 style="margin: 0; color: {'#166534' if is_done else '#1e40af'};">📌 Data #{index + 1} - {status_icon}</h3>
            </div>
            """, unsafe_allow_html=True)
            
            # ROW 1: INPUT (Read-only, Referensi) - Full Width
            # Tampilkan sebagai custom box (bukan textarea) untuk clarity maksimal
            input_text = row.get('input', '')
            st.markdown(f"""
            <div class='input-reference-box'>
                <div class='input-reference-header'>📖 INPUT / REFERENSI PASIEN</div>
                <div style="white-space: pre-wrap; font-size: 16px; line-height: 1.9; color: #2d2d2d;">
                    {input_text}
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            # ROW 2: INSTRUCTION_ATS dan OUTPUT_ATS - 2 columns
            st.markdown("<span class='box-header' style='color:#0369a1; margin-top: 15px; margin-bottom: 15px; font-size: 14px;'>✏️ ISI DATA BERIKUT (KOLOM WAJIB DIISI):</span>", unsafe_allow_html=True)
            
            col_instr, col_output = st.columns(2, gap="medium")
            
            with col_instr:
                st.markdown("""
                <div style='background-color: #f0f9ff; padding: 10px; border-radius: 6px; border-left: 4px solid #0284c7; margin-bottom: 10px;'>
                    <span style='font-weight: 700; color: #0369a1; font-size: 13px;'>✍️ INSTRUCTION ATS</span>
                </div>
                """, unsafe_allow_html=True)
                instruksi_val = st.text_area(
                    label="Instruction ATS",
                    value=row.get('instruction_ats', ''),
                    height=140,
                    max_chars=MAX_SHEET_CELL_CHARS,
                    label_visibility="collapsed",
                    key=f"instr_{index}",
                    placeholder="Isi klasifikasi ATS berdasarkan instruksi...",
                    disabled=is_done,
                    on_change=auto_save_progress,
                    args=(df, index)
                )
            
            with col_output:
                st.markdown("""
                <div style='background-color: #f0fce7; padding: 10px; border-radius: 6px; border-left: 4px solid #22c55e; margin-bottom: 10px;'>
                    <span style='font-weight: 700; color: #166534; font-size: 13px;'>✍️ OUTPUT ATS</span>
                </div>
                """, unsafe_allow_html=True)
                output_val = st.text_area(
                    label="Output ATS",
                    value=row.get('output_ats', ''),
                    height=140,
                    max_chars=MAX_SHEET_CELL_CHARS,
                    label_visibility="collapsed",
                    key=f"output_{index}",
                    placeholder="Isi hasil triase/output ATS...",
                    disabled=is_done,
                    on_change=auto_save_progress,
                    args=(df, index)
                )

            st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)
            col_similar, col_too_many = st.columns(2, gap="small")
            with col_similar:
                st.button(
                    "Serupa",
                    key=f"shortcut_serupa_{index}",
                    use_container_width=True,
                    disabled=is_done,
                    on_click=fill_ats_shortcut,
                    args=(index, "serupa")
                )
            with col_too_many:
                st.button(
                    "Kasus terlalu banyak",
                    key=f"shortcut_too_many_{index}",
                    use_container_width=True,
                    disabled=is_done,
                    on_click=fill_ats_shortcut,
                    args=(index, "kasus terlalu banyak")
                )

            can_mark_done = (
                normalize_cell(instruksi_val) != ''
                and normalize_cell(output_val) != ''
            )
            if not is_done and not can_mark_done:
                st.warning("Isi instruction_ats dan output_ats sebelum menandai tugas sebagai selesai.")

            current_length_violations = get_current_ats_length_violations(index, instruksi_val, output_val)
            if current_length_violations:
                show_length_violation_error(current_length_violations)
             
            # ROW 3: BUTTONS
            st.markdown("<div style='margin-top: 15px;'></div>", unsafe_allow_html=True)
            
            col_save, col_done, col_status = st.columns([2, 2, 2], gap="small")
            
            with col_save:
                if st.button(
                    "💾 Simpan Progress",
                    key=f"save_{index}",
                    use_container_width=True,
                    disabled=is_done
                ):
                    with st.spinner("💫 Menyimpan progress..."):
                        current_length_violations = get_current_ats_length_violations(index, instruksi_val, output_val)
                        if current_length_violations:
                            show_length_violation_error(current_length_violations)
                            st.stop()
                        expected_instruction = row.get('instruction_ats', '')
                        expected_output = row.get('output_ats', '')
                        df.at[index, 'instruction_ats'] = instruksi_val
                        df.at[index, 'output_ats'] = output_val
                        df.at[index, 'validator'] = username
                        # Set status ke "Pending" untuk menandakan sedang dikerjakan
                        df.at[index, 'status'] = "Pending"
                        if update_data(
                            df,
                            [index],
                            ['instruction_ats', 'output_ats', 'validator', 'status'],
                            expected_values={
                                'instruction_ats': expected_instruction,
                                'output_ats': expected_output,
                                'validator': username,
                                'status': ['', 'Pending']
                            }
                        ):
                            st.toast("✅ Progress tersimpan! Status: Sedang Dikerjakan", icon="✅")
                            time.sleep(0.3)
            
            with col_done:
                if st.button(
                    "✅ Tandai Selesai",
                    key=f"done_{index}",
                    use_container_width=True,
                    type="primary",
                    disabled=is_done or not can_mark_done
                ):
                    with st.spinner("💫 Menyelesaikan data..."):
                        current_length_violations = get_current_ats_length_violations(index, instruksi_val, output_val)
                        if current_length_violations:
                            show_length_violation_error(current_length_violations, action_label="Tandai selesai")
                            st.stop()
                        expected_instruction = row.get('instruction_ats', '')
                        expected_output = row.get('output_ats', '')
                        df.at[index, 'instruction_ats'] = instruksi_val
                        df.at[index, 'output_ats'] = output_val
                        df.at[index, 'validator'] = username
                        if not can_mark_done:
                            st.error("Tidak bisa menandai selesai: instruction_ats dan output_ats wajib diisi.")
                            st.stop()
                        df.at[index, 'status'] = "Done"
                        if update_data(
                            df,
                            [index],
                            ['instruction_ats', 'output_ats', 'validator', 'status'],
                            expected_values={
                                'instruction_ats': expected_instruction,
                                'output_ats': expected_output,
                                'validator': username,
                                'status': ['', 'Pending']
                            }
                        ):
                            st.toast("✅ Data selesai! Status diubah ke Done.", icon="✅")
                            time.sleep(0.5)
                            if not show_history:
                                st.rerun()
            
            with col_status:
                status_text = "🎉 SELESAI" if is_done else "⏳ Aktif"
                st.markdown(f"""
                <div style="text-align: center; padding: 10px; background-color: {'#dcfce7' if is_done else '#fef08a'}; border-radius: 6px; border: 1px solid {'#bbf7d0' if is_done else '#fcd34d'};">
                    <small style="font-weight: bold; color: {'#166534' if is_done else '#92400e'};"><strong>{status_text}</strong></small>
                </div>
                """, unsafe_allow_html=True)
            
            st.divider()

elif sisa_tugas_saya == 0 and sisa_pool == 0 and total_dikerjakan_saya == 0:
    # User baru, tidak ada tugas, tidak ada data tersedia
    st.warning("⚠️ Saat ini tidak ada data untuk diambil. Mohon tunggu atau hubungi administrator.")

elif sisa_tugas_saya == 0 and sisa_pool == 0 and total_dikerjakan_saya > 0:
    # User sudah selesai semua, tidak ada data tersedia
    st.balloons()
    st.success("🎉 Luar biasa! Anda telah menyelesaikan SEMUA tugas yang tersedia!")
    st.info("📢 Semua data telah habis dan selesai divalidasi. Terima kasih atas kontribusi Anda!")

else:
    # Kondisi lain
    if sisa_pool == 0:
        st.info("ℹ️ Tidak ada data baru yang tersedia untuk diambil saat ini.")
