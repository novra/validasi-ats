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
</style>
""", unsafe_allow_html=True)

# --- KONEKSI KE GOOGLE SHEETS ---
conn = st.connection("gsheets", type=GSheetsConnection)

def load_data():
    # TTL 0 berarti jangan cache terlalu lama saat development/debugging
    return conn.read(worksheet="Sheet1", ttl=0) 

def update_data(df):
    try:
        conn.update(worksheet="Sheet1", data=df)
        st.cache_data.clear() # Wajib clear cache agar data baru terbaca
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

# --- LOAD & CLEAN DATA ---
try:
    df = load_data()
    
    # Pastikan kolom wajib ada
    for col in ['validator', 'instruction_ats', 'status']:
        if col not in df.columns:
            df[col] = ""
            
    # KONVERSI KE STRING (PENTING)
    df['validator'] = df['validator'].astype(str).replace('nan', '')
    df['instruction_ats'] = df['instruction_ats'].astype(str).replace('nan', '')
    df['status'] = df['status'].astype(str).replace('nan', '')
    
except Exception as e:
    st.error(f"Gagal memuat data. Error: {e}")
    st.stop()

# --- LOGIKA FILTER ---
# Strip whitespace agar spasi tidak dianggap karakter
unassigned_mask = (df['validator'].str.strip() == "") | (df['validator'] == "nan")
my_rows_mask = df['validator'] == username

sisa_tugas = len(df[unassigned_mask])
tugas_saya = len(df[my_rows_mask])

st.sidebar.divider()
st.sidebar.metric("Sisa Data Belum Diambil", sisa_tugas)
st.sidebar.metric("Tugas Saya", tugas_saya)

# --- BAGIAN AMBIL TUGAS ---
# Hanya muncul jika user belum punya tugas ATAU tugas sudah selesai semua tapi masih mau ambil lagi
if tugas_saya == 0 and sisa_tugas > 0:
    st.info("👋 Halo! Anda belum memiliki tugas aktif.")
    
    with st.form("ambil_tugas_form"):
        st.write("Pilih jumlah data yang ingin divalidasi:")
        batch_size = st.number_input("Jumlah baris:", min_value=5, max_value=50, value=10)
        
        # Tombol Submit
        submitted = st.form_submit_button("🚀 Ambil Tugas Sekarang")
        
        if submitted:
            # Cek lagi ketersediaan data di dalam blok submit
            current_indices = df[unassigned_mask].head(batch_size).index
            
            if len(current_indices) == 0:
                st.error("Maaf, data sudah habis diambil orang lain barusan!")
            else:
                with st.spinner("Sedang mengunci data untuk Anda di Google Sheets..."):
                    # Lakukan update
                    df.loc[current_indices, 'validator'] = username
                    
                    # Simpan ke Cloud
                    success = update_data(df)
                    
                    if success:
                        st.success(f"Berhasil mengambil {len(current_indices)} data!")
                        time.sleep(1) # Jeda sebentar agar user lihat pesan sukses
                        st.rerun()
                    else:
                        st.error("Gagal menyimpan. Coba lagi.")

# --- BAGIAN AREA KERJA ---
user_df = df[df['validator'] == username].copy()

if not user_df.empty:
    st.subheader(f"📝 Area Kerja Anda (Batch {len(user_df)} data)")
    st.info("Tips: Data tersimpan otomatis ke Google Sheets setiap kali Anda menekan tombol 'Simpan'.")

    for index, row in user_df.iterrows():
        with st.container():
            st.markdown(f"### Data #{index + 1}")
            c1, c2, c3 = st.columns(3)
            
            # Tampilan 3 Kolom Scrollable
            with c1:
                st.markdown(f"<span class='box-header'>Instruction / Konteks</span><div class='scroll-box'>{row.get('instruction', '-')}</div>", unsafe_allow_html=True)
            with c2:
                st.markdown(f"<span class='box-header'>Input Pasien</span><div class='scroll-box'>{row.get('input', '-')}</div>", unsafe_allow_html=True)
            with c3:
                st.markdown(f"<span class='box-header'>Output / Respons Awal</span><div class='scroll-box'>{row.get('output', '-')}</div>", unsafe_allow_html=True)
            
            # Input Area
            st.markdown("<span class='box-header' style='color:#b45309; margin-top:10px;'>👉 Instruction ATS (Wajib Diisi)</span>", unsafe_allow_html=True)
            
            # Unique key untuk text area sangat penting agar tidak reset saat mengetik
            new_val = st.text_area(
                label="Input ATS", 
                value=row['instruction_ats'], 
                height=150,
                label_visibility="collapsed", 
                key=f"txt_{index}",
                placeholder="Masukkan instruksi ATS di sini..."
            )
            
            # Tombol Simpan Per Baris
            col_btn, col_info = st.columns([1, 5])
            with col_btn:
                if st.button(f"💾 Simpan #{index+1}", key=f"btn_{index}", type="primary"):
                    with st.spinner("Menyimpan..."):
                        df.at[index, 'instruction_ats'] = new_val
                        df.at[index, 'status'] = "Done"
                        update_data(df)
                        st.toast(f"Baris #{index+1} tersimpan!", icon="✅")
            with col_info:
                if row.get('status') == 'Done':
                    st.markdown("✅ **Tersimpan di Cloud**")
            
            st.divider()

elif sisa_tugas == 0 and tugas_saya == 0:
    st.balloons()
    st.success("🎉 Luar biasa! Semua data dalam spreadsheet telah selesai divalidasi oleh tim.")
