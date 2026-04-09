import streamlit as st

# --- KONFIGURASI HALAMAN ---
st.set_page_config(
    layout="centered",
    page_title="Aplikasi Pelabelan ATS",
    initial_sidebar_state="collapsed"
)

# --- CSS KUSTOM ---
st.markdown("""
<style>
    .hero-section {
        padding: 40px 30px;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        border-radius: 12px;
        color: white;
        margin-bottom: 30px;
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.1);
        text-align: center;
    }
    
    .hero-section h1 {
        font-size: 2.2em;
        margin: 0 0 10px 0;
    }
    
    .hero-section p {
        font-size: 1em;
        margin: 8px 0;
        opacity: 0.95;
    }
    
    .feature-card {
        background-color: #f0f4ff;
        padding: 18px;
        border-radius: 8px;
        border-left: 4px solid #667eea;
        margin: 10px 0;
    }
    
    .feature-card h4 {
        color: #667eea;
        margin-top: 0;
        margin-bottom: 10px;
    }
    
    .user-badge {
        background-color: #f0f4ff;
        padding: 12px;
        border-radius: 6px;
        text-align: center;
        margin: 8px 0;
    }
    
    .user-badge h5 {
        margin: 0;
        color: #667eea;
        font-size: 0.95em;
    }
    
    .user-badge small {
        color: #888;
        font-size: 0.85em;
    }
</style>
""", unsafe_allow_html=True)

# --- HOMEPAGE ---
st.markdown("""
<div class='hero-section'>
    <h1>🏥 Aplikasi Pelabelan ATS</h1>
    <p><strong>Sistem Triase Automated Template Scoring</strong></p>
    <p>Platform kolaboratif untuk pelabelan data Medical Records</p>
</div>
""", unsafe_allow_html=True)

# --- NAVIGASI ---
col1, col2 = st.columns(2, gap="medium")

with col1:
    if st.button("👤 User Labeling", use_container_width=True, type="primary", help="Mulai mengisi data"):
        st.switch_page("pages/01_👤_User_Labeling.py")

with col2:
    if st.button("📊 Admin Monitoring", use_container_width=True, help="Pantau progress validator"):
        st.switch_page("pages/02_📊_Admin_Monitoring.py")

st.divider()

# --- INFO SECTION ---
st.markdown("### 📋 Fitur Utama")

col1, col2 = st.columns(2)

with col1:
    st.markdown("""
    <div class='feature-card'>
        <h4>👤 User Labeling</h4>
        <ul style="margin: 0; padding-left: 20px;">
            <li>Isi instruksi_ats & output_ats</li>
            <li>Simpan progress kapan saja</li>
            <li>Kelola tugas dengan mudah</li>
        </ul>
    </div>
    """, unsafe_allow_html=True)

with col2:
    st.markdown("""
    <div class='feature-card'>
        <h4>📊 Admin Dashboard</h4>
        <ul style="margin: 0; padding-left: 20px;">
            <li>Monitor progress semua user</li>
            <li>Lihat statistik real-time</li>
            <li>Export laporan CSV</li>
        </ul>
    </div>
    """, unsafe_allow_html=True)

st.divider()

st.markdown("### 👥 Validator Terauthorisasi")

users = ["dr.Dhaifina", "dr.Dian", "dr.Natalia", "dr.Wulan"]
col1, col2, col3, col4 = st.columns(4, gap="small")

for col, user in zip([col1, col2, col3, col4], users):
    with col:
        st.markdown(f"""
        <div class='user-badge'>
            <h5>👨‍⚕️ {user}</h5>
            <small>Validator</small>
        </div>
        """, unsafe_allow_html=True)

st.divider()

st.markdown("""
### 🚀 Quick Start

**Untuk User:**
1. Klik "User Labeling" → Pilih nama → Ambil tugas
2. Isi Instruksi ATS & Output ATS sesuai input
3. Klik "Simpan Progress" atau "Tandai Selesai"

**Untuk Admin:**
1. Klik "Admin Monitoring" → Masukkan password
2. Lihat dashboard progress semua user
3. Filter dan export data sesuai kebutuhan
""")

st.divider()
st.caption("🔒 Aplikasi Pelabelan ATS | v1.0")
