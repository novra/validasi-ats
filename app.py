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
    return conn.read(worksheet="Sheet1", ttl=0) 

def update_data(df):
    try:
        conn.update(worksheet="Sheet1", data=df)
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

# --- LOAD DATA ---
try:
    df = load_data()
    for col in ['validator', 'instruction_ats', 'status']:
        if col not in df.columns: df[col] = ""
    
    # KONVERSI DATA KE STRING
    df['validator'] = df['validator'].astype(str).replace('nan', '')
    df['instruction_ats'] = df['instruction_ats'].astype(str).replace('nan', '')
    df['status'] = df['status'].astype(str).replace('nan', '')
    
except Exception as e:
    st.error(f"Gagal memuat data: {e}")
    st.stop()

# --- LOGIKA BARU (PENDING vs DONE) ---
# 1. Cari data yang belum diambil siapapun
unassigned_mask = (df['validator'].str.strip() == "") | (df['validator'] == "nan")

# 2. Cari data milik user ini
my_all_tasks = df[df['validator'] == username]

# 3. Cari data milik user ini yang BELUM SELESAI (Status bukan 'Done')
my_pending_tasks = my_all_tasks[my_all_tasks['status'] != 'Done']

# Hitung Statistik
sisa_pool = len(df[unassigned_mask])
total_dikerjakan_saya = len(my_all_tasks)
sisa_tugas_saya = len(my_pending_tasks)

st.sidebar.divider()
st.sidebar.metric("Sisa Data Global", sisa_pool)
st.sidebar.metric("Total Tugas Saya", total_dikerjakan_saya)
st.sidebar.metric("Sisa Tugas Aktif", sisa_tugas_saya)

# --- BAGIAN AMBIL TUGAS (LOGIKA DIPERBAIKI) ---
# Tombol ambil tugas muncul jika TIDAK ADA tugas aktif (pending == 0).
# Jadi walaupun total tugas saya 10, tapi kalau semuanya 'Done', form ini akan muncul lagi.

if sisa_tugas_saya == 0 and sisa_pool > 0:
    if total_dikerjakan_saya > 0:
        st.success("🎉 Hebat! Anda telah menyelesaikan semua tugas sebelumnya. Siap ambil lagi?")
    else:
        st.info("👋 Halo! Anda belum memiliki tugas aktif.")
    
    with st.form("ambil_tugas_form"):
        st.write("Ambil paket data baru:")
        batch_size = st.number_input("Jumlah baris:", min_value=5, max_value=50, value=10)
        submitted = st.form_submit_button("🚀 Ambil Tugas Baru")
        
        if submitted:
            current_indices = df[unassigned_mask].head(batch_size).index
            if len(current_indices) == 0:
                st.error("Data habis diambil orang lain!")
            else:
                with st.spinner("Mengambil data..."):
                    df.loc[current_indices, 'validator'] = username
                    if update_data(df):
                        st.success(f"Berhasil mengambil {len(current_indices)} data baru!")
                        time.sleep(1)
                        st.rerun()

# --- BAGIAN AREA KERJA (HANYA MENAMPILKAN TUGAS AKTIF) ---
# Kita filter agar yang ditampilkan di layar kerja HANYA yang belum selesai
# agar user fokus pada tugas barunya.

# Jika ingin melihat history (yang sudah Done), bisa dibuat toggle opsional
show_history = st.checkbox("Tampilkan tugas yang sudah selesai (History)", value=False)

if show_history:
    # Tampilkan semua tugas (Active + Done)
    working_df = my_all_tasks.copy()
else:
    # Tampilkan hanya tugas aktif (Pending)
    working_df = my_pending_tasks.copy()

if not working_df.empty:
    st.subheader(f"📝 Area Kerja ({len(working_df)} data)")
    
    # Urutkan agar tugas yang belum selesai muncul paling atas
    # working_df = working_df.sort_values(by='status', ascending=True) 

    for index, row in working_df.iterrows():
        with st.container():
            # Tanda visual jika sudah selesai
            is_done = row.get('status') == 'Done'
            status_icon = "✅ SELESAI" if is_done else "⏳ BELUM SELESAI"
            bg_color = "#dcfce7" if is_done else "white"
            
            st.markdown(f"### Data #{index + 1} - {status_icon}")
            
            c1, c2, c3 = st.columns(3)
            with c1:
                st.markdown(f"<span class='box-header'>Instruction</span><div class='scroll-box'>{row.get('instruction', '-')}</div>", unsafe_allow_html=True)
            with c2:
                st.markdown(f"<span class='box-header'>Input</span><div class='scroll-box'>{row.get('input', '-')}</div>", unsafe_allow_html=True)
            with c3:
                st.markdown(f"<span class='box-header'>Output</span><div class='scroll-box'>{row.get('output', '-')}</div>", unsafe_allow_html=True)
            
            st.markdown("<span class='box-header' style='color:#b45309; margin-top:10px;'>👉 Instruction ATS</span>", unsafe_allow_html=True)
            
            new_val = st.text_area(
                label="Input ATS", 
                value=row['instruction_ats'], 
                height=150,
                label_visibility="collapsed", 
                key=f"txt_{index}",
                placeholder="Isi instruksi ATS...",
                disabled=False # Bisa diubah true jika ingin mengunci data yang sudah Done
            )
            
            col_btn, col_info = st.columns([1, 5])
            with col_btn:
                # Ubah teks tombol jika sudah selesai
                btn_label = "💾 Update" if is_done else "💾 Simpan"
                if st.button(f"{btn_label} #{index+1}", key=f"btn_{index}", type="primary"):
                    with st.spinner("Menyimpan..."):
                        df.at[index, 'instruction_ats'] = new_val
                        df.at[index, 'status'] = "Done"
                        update_data(df)
                        st.toast("Tersimpan!", icon="✅")
                        # Opsional: Rerun agar data hilang dari list 'Pending' jika mode history mati
                        if not show_history: 
                            time.sleep(0.5)
                            st.rerun()
            
            st.divider()

elif sisa_pool == 0 and sisa_tugas_saya == 0:
    st.balloons()
    st.success("🎉 Semua data global telah habis dan selesai divalidasi!")
else:
    # Kondisi aneh: punya tugas selesai, tapi pool habis, dll.
    if sisa_pool == 0:
         st.warning("Tidak ada data baru yang tersedia.")
