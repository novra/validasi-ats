import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection
import time

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
</style>
""", unsafe_allow_html=True)

# --- KONEKSI KE GOOGLE SHEETS ---
conn = st.connection("gsheets", type=GSheetsConnection)

@st.cache_data(ttl=0)
def load_data():
    try:
        df = conn.read(worksheet="Sheet1", ttl=0)
        return df
    except Exception as e:
        st.error(f"❌ Error membaca Google Sheet: {e}")
        return None

def update_data(df):
    try:
        conn.update(worksheet="Sheet1", data=df)
        # Clear cache untuk force reload data
        load_data.clear()
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"Gagal menyimpan ke Google Sheets: {e}")
        return False

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

# --- LOGIN ---
AUTHORIZED_USERS = [
    "dr.Dhaifina",
    "dr.Dian",
    "dr.Natalia",
    "dr.Wulan"
]

if 'username' not in st.session_state:
    st.title("🔐 Login Tim Validator")
    st.markdown("### Silakan pilih nama Anda untuk mulai bekerja")
    
    col1, col2 = st.columns([1, 2])
    with col1:
        selected_user = st.selectbox(
            "Nama Validator:",
            options=AUTHORIZED_USERS,
            index=None,
            placeholder="Pilih nama Anda..."
        )
        
        if st.button("🔓 Masuk", type="primary", use_container_width=True):
            if selected_user:
                st.session_state['username'] = selected_user
                st.rerun()
            else:
                st.error("Silakan pilih nama terlebih dahulu!")
    
    with col2:
        st.info("""
        **Authorized Users:**
        - dr.Dhaifina
        - dr.Dian
        - dr.Natalia
        - dr.Wulan
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
        st.info("   2. Sheet memiliki kolom: input, nama_validator, status, instruksi_ats, output_ats")
        st.info("   3. Data sudah tersedia di Sheet1")
        st.stop()
    
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
    
    # Filter hanya data yang memiliki input (tidak kosong)
    df = df[df['input'] != '']
    
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
        
        available_count = len(df[(df['input'] != '') & (df['validator'] == '') & ((df['status'] == '') | (df['status'] == 'Done'))])
        st.sidebar.write(f"🎯 **DATA TERSEDIA (kombinasi ketiga kondisi): {available_count}**")
        
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
# 1. Kolom validator kosong (belum diambil siapapun)
# 2. Kolom status kosong (belum pernah dikerjakan) ATAU status = 'Done' (sudah selesai, bisa diambil ulang)
# 3. Kolom input tidak kosong (harus ada input untuk diproses)

available_data_mask = (df['input'] != '') & (df['validator'] == '') & ((df['status'] == '') | (df['status'] == 'Done'))

# Data milik user ini
my_all_tasks = df[df['validator'] == username]

# Data milik user ini yang BELUM SELESAI (Status bukan 'Done' dan tidak kosong)
my_pending_tasks = my_all_tasks[(my_all_tasks['status'] != 'Done') & (my_all_tasks['status'] != '')]

# Hitung Statistik
sisa_pool = len(df[available_data_mask])
total_dikerjakan_saya = len(my_all_tasks)
sisa_tugas_saya = len(my_pending_tasks)

st.sidebar.divider()
st.sidebar.metric("📊 Sisa Data Tersedia", sisa_pool)
st.sidebar.metric("📋 Total Tugas Saya", total_dikerjakan_saya)
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
            available_indices = df[available_data_mask].head(batch_size).index
            if len(available_indices) == 0:
                st.error("❌ Data habis diambil orang lain!")
            else:
                with st.spinner("⏳ Mengambil data..."):
                    df.loc[available_indices, 'validator'] = username
                    # Pastikan status kosong untuk data baru yang diambil
                    df.loc[available_indices, 'status'] = ''
                    if update_data(df):
                        st.success(f"✅ Berhasil mengambil {len(available_indices)} data baru!")
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
            status_icon = "✅ SELESAI" if is_done else "⏳ BELUM SELESAI"
            
            # Header dengan status
            header_color = "#dcfce7" if is_done else "#dbeafe"
            st.markdown(f"""
            <div style="background-color:{header_color}; padding: 12px; border-radius: 8px; margin-bottom: 20px; border-left: 5px solid {'#16a34a' if is_done else '#1e40af'};">
                <h3 style="margin: 0; color: {'#166534' if is_done else '#1e40af'};">📌 Data #{index + 1} - {status_icon}</h3>
            </div>
            """, unsafe_allow_html=True)
            
            # ROW 1: INPUT (Read-only, Referensi) - Full Width
            st.markdown("<span class='box-header' style='color:#374151;'>📖 INPUT (Referensi - Jangan Diubah)</span>", unsafe_allow_html=True)
            st.text_area(
                label="Input Reference", 
                value=row.get('input', ''),
                height=100,
                label_visibility="collapsed", 
                key=f"input_{index}",
                disabled=True
            )
            
            # ROW 2: INSTRUCTION_ATS dan OUTPUT_ATS - 2 columns
            st.markdown("<span class='box-header' style='color:#b45309; margin-top: 15px;'>✏️ ISI DATA BERIKUT:</span>", unsafe_allow_html=True)
            
            col_instr, col_output = st.columns(2, gap="medium")
            
            with col_instr:
                st.markdown("<span class='box-header' style='color:#7c2d12;'>Instruction ATS</span>", unsafe_allow_html=True)
                instruksi_val = st.text_area(
                    label="Instruction ATS",
                    value=row.get('instruction_ats', ''),
                    height=120,
                    label_visibility="collapsed",
                    key=f"instr_{index}",
                    placeholder="Isi instruction ATS di sini...",
                    disabled=is_done
                )
            
            with col_output:
                st.markdown("<span class='box-header' style='color:#7c2d12;'>Output ATS</span>", unsafe_allow_html=True)
                output_val = st.text_area(
                    label="Output ATS",
                    value=row.get('output_ats', ''),
                    height=120,
                    label_visibility="collapsed",
                    key=f"output_{index}",
                    placeholder="Isi output ATS di sini...",
                    disabled=is_done
                )
            
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
                        df.at[index, 'instruction_ats'] = instruksi_val
                        df.at[index, 'output_ats'] = output_val
                        if update_data(df):
                            st.toast("✅ Progress tersimpan!", icon="✅")
                            time.sleep(0.3)
            
            with col_done:
                if st.button(
                    "✅ Tandai Selesai",
                    key=f"done_{index}",
                    use_container_width=True,
                    type="primary",
                    disabled=is_done
                ):
                    with st.spinner("💫 Menyelesaikan data..."):
                        df.at[index, 'instruction_ats'] = instruksi_val
                        df.at[index, 'output_ats'] = output_val
                        df.at[index, 'status'] = "Done"
                        if update_data(df):
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
