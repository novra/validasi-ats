import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection

# --- KONFIGURASI HALAMAN ---
st.set_page_config(layout="wide", page_title="Online ATS Validator")

# --- CSS KUSTOM UNTUK SCROLLBOX & WARNA ATS ---
st.markdown("""
<style>
    /* Style untuk Box Scrollable */
    .scroll-box {
        height: 300px; /* Tinggi tetap */
        overflow-y: auto; /* Scroll jika konten panjang */
        padding: 15px;
        border: 1px solid #e5e7eb;
        border-radius: 8px;
        background-color: #f9fafb;
        font-size: 14px;
        line-height: 1.5;
        color: #1f2937;
        margin-bottom: 10px;
    }
    .box-header {
        font-weight: bold;
        text-transform: uppercase;
        font-size: 12px;
        margin-bottom: 8px;
        color: #6b7280;
        display: block;
    }
    
    /* Warna Kategori ATS sesuai Panduan G24 V6 */
    .ats-cat-1 { background-color: #fee2e2; color: #991b1b; padding: 10px; border-radius: 5px; border: 1px solid #fca5a5; }
    .ats-cat-2 { background-color: #ffedd5; color: #9a3412; padding: 10px; border-radius: 5px; border: 1px solid #fdba74; }
    .ats-cat-3 { background-color: #dcfce7; color: #166534; padding: 10px; border-radius: 5px; border: 1px solid #86efac; }
    .ats-cat-4 { background-color: #dbeafe; color: #1e40af; padding: 10px; border-radius: 5px; border: 1px solid #93c5fd; }
    .ats-cat-5 { background-color: #f3f4f6; color: #374151; padding: 10px; border-radius: 5px; border: 1px solid #d1d5db; }
    
    .ats-title { font-weight: bold; font-size: 1.1em; display: block; border-bottom: 1px solid rgba(0,0,0,0.1); margin-bottom: 5px; padding-bottom: 3px; }
    .ats-list { margin-left: 15px; font-size: 0.85em; }
</style>
""", unsafe_allow_html=True)

# --- KONEKSI KE GOOGLE SHEETS ---
conn = st.connection("gsheets", type=GSheetsConnection)

def load_data():
    # Membaca data dengan cache time-to-live (TTL) 5 detik agar update cepat
    return conn.read(worksheet="Sheet1", usecols=list(range(7)), ttl=5)

def update_data(df):
    conn.update(worksheet="Sheet1", data=df)
    st.cache_data.clear()

# --- PANDUAN ATS (Helper Function) ---
def show_ats_guidance():
    with st.expander("📘 PANDUAN TRISE ATS (KLIK UNTUK MEMBUKA)", expanded=False):
        cols = st.columns(5)
        with cols[0]:
            st.markdown("""
            <div class='ats-cat-1'>
                <span class='ats-title'>KAT 1: SEGERA (Red)</span>
                <ul class='ats-list'>
                    <li>Henti Jantung/Napas</li>
                    <li>Sumbatan Jalan Napas</li>
                    <li>Kejang Terus Menerus</li>
                    <li>GCS < 9 (Koma)</li>
                    <li>Ancaman Kekerasan Segera</li>
                </ul>
            </div>
            """, unsafe_allow_html=True) # [cite: 148, 83]
        with cols[1]:
            st.markdown("""
            <div class='ats-cat-2'>
                <span class='ats-title'>KAT 2: 10 MENIT (Orange)</span>
                <ul class='ats-list'>
                    <li>Nyeri Dada Kardiak</li>
                    <li>Sesak Berat/Stridor</li>
                    <li>Sepsis (Tak Stabil)</li>
                    <li>GCS < 13 (Bingung)</li>
                    <li>Nyeri Hebat (7-10)</li>
                    <li>Stroke Akut</li>
                </ul>
            </div>
            """, unsafe_allow_html=True) # [cite: 153, 83]
        with cols[2]:
            st.markdown("""
            <div class='ats-cat-3'>
                <span class='ats-title'>KAT 3: 30 MENIT (Green)</span>
                <ul class='ats-list'>
                    <li>Hipertensi Berat</li>
                    <li>Sesak Sedang</li>
                    <li>Nyeri Sedang (4-6)</li>
                    <li>Sepsis (Stabil)</li>
                    <li>Cedera Tungkai Sedang</li>
                    <li>Anak Berisiko</li>
                </ul>
            </div>
            """, unsafe_allow_html=True) # [cite: 158, 83]
        with cols[3]:
            st.markdown("""
            <div class='ats-cat-4'>
                <span class='ats-title'>KAT 4: 60 MENIT (Blue)</span>
                <ul class='ats-list'>
                    <li>Perdarahan Ringan</li>
                    <li>Cedera Kepala Ringan</li>
                    <li>Nyeri Sedang (Berisiko)</li>
                    <li>Muntah/Diare (Tanpa Dehidrasi)</li>
                    <li>Trauma Minor</li>
                </ul>
            </div>
            """, unsafe_allow_html=True) # [cite: 163, 83]
        with cols[4]:
            st.markdown("""
            <div class='ats-cat-5'>
                <span class='ats-title'>KAT 5: 120 MENIT (White)</span>
                <ul class='ats-list'>
                    <li>Nyeri Minimal</li>
                    <li>Luka Minor (Lecet)</li>
                    <li>Ganti Perban/Kontrol</li>
                    <li>Imunisasi</li>
                    <li>Gejala Kronis</li>
                </ul>
            </div>
            """, unsafe_allow_html=True) # [cite: 163, 83]

# --- HALAMAN LOGIN ---
if 'username' not in st.session_state:
    st.title("🔐 Login Tim Validator")
    c1, c2 = st.columns([1, 2])
    with c1:
        user_input = st.text_input("Masukkan Nama Anda (tanpa spasi):")
        if st.button("Masuk", type="primary"):
            if user_input:
                st.session_state['username'] = user_input
                st.rerun()
    st.stop()

# --- APLIKASI UTAMA ---
username = st.session_state['username']

# Header & Sidebar
st.sidebar.header(f"User: {username}")
if st.sidebar.button("Logout"):
    del st.session_state['username']
    st.rerun()

st.title("🏥 Validator ATS Online")
st.markdown("Validasi data triase medis secara kolaboratif.")

# Tampilkan Panduan ATS
show_ats_guidance()

# Load Data
try:
    df = load_data()
    # Pastikan kolom wajib ada
    for col in ['validator', 'instruction_ats', 'status']:
        if col not in df.columns: df[col] = ""
except Exception as e:
    st.error(f"Gagal koneksi ke Google Sheet. Pastikan Secrets sudah diatur! Error: {e}")
    st.stop()

# Logika Locking / Pengambilan Batch
unassigned_mask = (df['validator'].isnull()) | (df['validator'] == "") | (df['validator'].str.strip() == "")
my_rows_mask = df['validator'] == username

# Statistik di Sidebar
st.sidebar.divider()
st.sidebar.metric("Total Data", len(df))
st.sidebar.metric("Sisa Belum Diambil", len(df[unassigned_mask]))
st.sidebar.metric("Tugas Saya", len(df[my_rows_mask]))

# Bagian Ambil Tugas Baru
if len(df[my_rows_mask]) == 0 and len(df[unassigned_mask]) > 0:
    st.info("Anda belum memiliki tugas aktif.")
    with st.form("ambil_tugas"):
        batch_size = st.number_input("Ambil berapa baris data?", min_value=5, max_value=50, value=10)
        submitted = st.form_submit_button("Ambil Tugas")
        if submitted:
            available_indices = df[unassigned_mask].head(batch_size).index
            df.loc[available_indices, 'validator'] = username
            update_data(df)
            st.success(f"Berhasil mengambil {len(available_indices)} baris data!")
            st.rerun()

# Bagian Validasi Data (Looping)
user_df = df[df['validator'] == username].copy()

if not user_df.empty:
    st.subheader(f"📝 Area Kerja (Batch {len(user_df)} data)")
    
    for index, row in user_df.iterrows():
        with st.container():
            st.markdown(f"### Data #{index + 1}")
            
            # --- LAYOUT BERDAMPINGAN (3 KOLOM) ---
            # Menggunakan HTML <div> dengan class 'scroll-box' agar bisa discroll
            c1, c2, c3 = st.columns(3)
            
            with c1:
                st.markdown(f"""
                <span class='box-header'>Instruction / Konteks</span>
                <div class='scroll-box'>{row.get('instruction', '-')}</div>
                """, unsafe_allow_html=True)
                
            with c2:
                st.markdown(f"""
                <span class='box-header'>Input Pasien</span>
                <div class='scroll-box'>{row.get('input', '-')}</div>
                """, unsafe_allow_html=True)
                
            with c3:
                st.markdown(f"""
                <span class='box-header'>Output / Respons Awal</span>
                <div class='scroll-box'>{row.get('output', '-')}</div>
                """, unsafe_allow_html=True)
            
            # --- INPUT AREA (FULL WIDTH DI BAWAHNYA) ---
            st.markdown("<span class='box-header' style='color:#b45309; margin-top:10px;'>👉 Instruction ATS (Wajib Diisi)</span>", unsafe_allow_html=True)
            
            current_val = row['instruction_ats'] if pd.notna(row['instruction_ats']) else ""
            
            # Text Area untuk input
            new_val = st.text_area(
                label="Label ATS",
                value=current_val, 
                height=150,
                label_visibility="collapsed",
                key=f"txt_{index}",
                placeholder="Tuliskan instruksi ATS yang benar di sini berdasarkan panduan di atas..."
            )
            
            # Tombol Simpan
            col_btn, col_info = st.columns([1, 5])
            with col_btn:
                if st.button(f"💾 Simpan #{index + 1}", key=f"btn_{index}", type="primary"):
                    df.at[index, 'instruction_ats'] = new_val
                    df.at[index, 'status'] = "Done"
                    update_data(df)
                    st.toast(f"Data baris #{index+1} berhasil disimpan!", icon="✅")
            with col_info:
                if row.get('status') == 'Done':
                    st.markdown("✅ *Tersimpan*")
            
            st.divider()
    
    st.success("Semua pekerjaan disimpan otomatis ke Google Sheets Pusat.")