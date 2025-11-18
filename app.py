import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection

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
</style>
""", unsafe_allow_html=True)

# --- KONEKSI KE GOOGLE SHEETS ---
conn = st.connection("gsheets", type=GSheetsConnection)

def load_data():
    # Baca data, force sebagai string untuk menghindari error tipe data
    return conn.read(worksheet="Sheet1", ttl=5)

def update_data(df):
    conn.update(worksheet="Sheet1", data=df)
    st.cache_data.clear()

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
if 'username' not in st.session_state:
    st.title("🔐 Login Tim Validator")
    c1, c2 = st.columns([1, 2])
    with c1:
        user_input = st.text_input("Masukkan Nama Anda (tanpa spasi):")
        if st.button("Masuk", type="primary"):
            if user_input:
                st.session_state['username'] = user_input.strip()
                st.rerun()
    st.stop()

# --- APP UTAMA ---
username = st.session_state['username']
st.sidebar.header(f"User: {username}")
if st.sidebar.button("Logout"):
    del st.session_state['username']
    st.rerun()

st.title("🏥 Validator ATS Online")
show_ats_guidance()

try:
    df = load_data()
    
    # --- PERBAIKAN UTAMA DISINI ---
    # 1. Pastikan kolom ada
    for col in ['validator', 'instruction_ats', 'status']:
        if col not in df.columns:
            df[col] = ""
            
    # 2. KONVERSI KE STRING (PENTING AGAR TIDAK ERROR)
    # Kita ubah NaN menjadi string kosong "" dan paksa tipe data jadi string
    df['validator'] = df['validator'].astype(str).replace('nan', '')
    df['instruction_ats'] = df['instruction_ats'].astype(str).replace('nan', '')
    df['status'] = df['status'].astype(str).replace('nan', '')
    
except Exception as e:
    st.error(f"Gagal memuat data. Error: {e}")
    st.stop()

# Filter Data (Sekarang aman karena sudah pasti string)
unassigned_mask = df['validator'].str.strip() == ""
my_rows_mask = df['validator'] == username

st.sidebar.divider()
st.sidebar.metric("Sisa Belum Diambil", len(df[unassigned_mask]))
st.sidebar.metric("Tugas Saya", len(df[my_rows_mask]))

# Ambil Tugas
if len(df[my_rows_mask]) == 0 and len(df[unassigned_mask]) > 0:
    st.info("Anda belum memiliki tugas aktif.")
    with st.form("ambil_tugas"):
        batch_size = st.number_input("Ambil baris data:", min_value=5, max_value=50, value=10)
        if st.form_submit_button("Ambil Tugas"):
            available_indices = df[unassigned_mask].head(batch_size).index
