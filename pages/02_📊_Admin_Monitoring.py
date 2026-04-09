import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection
import plotly.graph_objects as go
import plotly.express as px

# --- KONFIGURASI HALAMAN ---
st.set_page_config(layout="wide", page_title="Admin Monitoring Pelabelan")

# --- AUTHORIZED ADMINS ---
AUTHORIZED_ADMINS = ["admin"]

# --- KONEKSI KE GOOGLE SHEETS ---
conn = st.connection("gsheets", type=GSheetsConnection)

def load_data():
    return conn.read(worksheet="Sheet1", ttl=0)

# --- LOGIN ADMIN ---
if 'admin_logged_in' not in st.session_state:
    st.title("🔐 Admin Monitoring Panel")
    st.markdown("### Silakan masukkan password admin untuk mengakses monitoring")
    
    col1, col2 = st.columns([1, 2])
    with col1:
        admin_pass = st.text_input("Password Admin:", type="password", placeholder="Masukkan password...")
        
        if st.button("🔓 Akses Admin", type="primary", use_container_width=True):
            if admin_pass == "admin123":  # Ganti dengan password yang lebih aman
                st.session_state['admin_logged_in'] = True
                st.rerun()
            else:
                st.error("❌ Password salah!")
    
    st.stop()

# --- LOGOUT ADMIN ---
if st.sidebar.button("🔓 Logout Admin"):
    st.session_state['admin_logged_in'] = False
    st.rerun()

st.title("📊 Admin Monitoring Panel - Pelabelan ATS")
st.markdown("Dashboard monitoring progress pelabelan masing-masing user")

# --- LOAD DATA ---
try:
    df = load_data()
    for col in ['validator', 'instruction_ats', 'status', 'input', 'output_ats']:
        if col not in df.columns: df[col] = ""
    
    # Rename jika kolom yang lama ada
    if 'nama_validator' in df.columns and 'validator' not in df.columns:
        df.rename(columns={'nama_validator': 'validator'}, inplace=True)
    if 'instruksi_ats' in df.columns and 'instruction_ats' not in df.columns:
        df.rename(columns={'instruksi_ats': 'instruction_ats'}, inplace=True)
    
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
    
    # Filter hanya data yang memiliki input (tidak kosong)
    df = df[df['input'] != '']
    
except Exception as e:
    st.error(f"Gagal memuat data: {e}")
    st.stop()

# --- DAFTAR USER ---
AUTHORIZED_USERS = [
    "dr.Dhaifina",
    "dr.Dian",
    "dr.Natalia",
    "dr.Wulan"
]

# --- KALKULASI STATISTIK ---
def calculate_stats(df, username):
    user_data = df[df['validator'] == username]
    total = len(user_data)
    done = len(user_data[user_data['status'] == 'Done'])
    pending = len(user_data[(user_data['status'] != 'Done') & (user_data['status'] != '')])
    available = len(user_data[user_data['status'] == ''])  # Diambil tapi belum dimulai
    
    return {
        'username': username,
        'total': total,
        'done': done,
        'pending': pending,
        'available': available,
        'progress_pct': (done / total * 100) if total > 0 else 0
    }

# --- HITUNG STATISTIK GLOBAL ---
total_data = len(df)
total_done = len(df[df['status'] == 'Done'])
total_pending = len(df[(df['status'] != 'Done') & (df['status'] != '')])
total_available = len(df[df['status'] == ''])
total_unassigned = len(df[df['validator'] == ''])

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

st.divider()

# --- REKAP PROGRESS PER USER ---
st.markdown("### 👥 Progress Masing-Masing User")

user_stats = []
for user in AUTHORIZED_USERS:
    stats = calculate_stats(df, user)
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
filtered_df = df.copy()

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
            status_filters.append(filtered_df['validator'] == '')
    
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

st.divider()
st.caption("🔒 Admin Monitoring Panel - Akses Terbatas")
