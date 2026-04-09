# 🔧 SETUP GUIDE - Aplikasi Pelabelan ATS

## 1️⃣ Konfigurasi Google Sheet

### Struktur Kolom Google Sheet (Sheet1)
Pastikan Google Sheet Anda memiliki kolom dengan Header Berikut (Row 1):

| Kolom | Nama | Keterangan |
|-------|------|-----------|
| A | `input` | Data input yang akan dibaca user sebagai referensi (READ-ONLY) |
| B | `instruksi_ats` | Instruksi ATS yang akan diisi oleh user |
| C | `output_ats` | Output ATS yang akan diisi oleh user |
| D | `status` | Status pengerjaan (Done atau kosong) |
| E | `nama_validator` | Nama user yang mengerjakan (auto-filled) |

**URL Google Sheet:** https://docs.google.com/spreadsheets/d/1dt0pOubE8FAxnUGn6I3BYRnp_9pWpeA3uWiEk1oZfDM/edit?gid=0#gid=0

---

## 2️⃣ Konfigurasi Streamlit Secrets

Untuk menghubungkan aplikasi dengan Google Sheet, setup file `.streamlit/secrets.toml`:

### Langkah 1: Buat File Secrets
```bash
mkdir .streamlit
touch .streamlit/secrets.toml
```

### Langkah 2: Isi secrets.toml
```toml
[connections.gsheets]
type = "gsheets"
spreadsheet = "1dt0pOubE8FAxnUGn6I3BYRnp_9pWpeA3uWiEk1oZfDM"
```

**Catatan:** 
- `spreadsheet` adalah ID di URL https://docs.google.com/spreadsheets/d/**[SPREADSHEET_ID]**/edit
- File ini HARUS ada dan tersimpan di local machine
- Jangan push secrets.toml ke GitHub!

### Langkah 3: Setup Google Service Account
1. Buka [Google Cloud Console](https://console.cloud.google.com/)
2. Buat Project baru (atau gunakan yang sudah ada)
3. Enable "Google Sheets API"
4. Buat Service Account:
   - Klik "Create Service Account"
   - Download JSON file
   - Copy isi JSON ke `.streamlit/secrets.toml` dengan format:

```toml
[connections.gsheets]
type = "gsheets"
spreadsheet = "1dt0pOubE8FAxnUGn6I3BYRnp_9pWpeA3uWiEk1oZfDM"

[connections.gsheets.gcp_service_account]
type = "service_account"
project_id = "YOUR_PROJECT_ID"
private_key_id = "YOUR_PRIVATE_KEY_ID"
private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
client_email = "YOUR_SERVICE_ACCOUNT_EMAIL"
client_id = "YOUR_CLIENT_ID"
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "YOUR_CERT_URL"
```

5. Share Google Sheet dengan email service account
   - Buka Google Sheet
   - Klik "Share"
   - Add email service account dengan akses "Editor"

---

## 3️⃣ Setup Streamlit Cloud (Deployment)

### Jika deploy ke Streamlit Cloud:

1. Push `.streamlit/secrets.toml` ke private repository (atau gunakan environment variables)
2. Di Streamlit Cloud Dashboard:
   - Pilih app Anda
   - Klik Settings → Secrets
   - Copy-paste isi `.streamlit/secrets.toml`

---

## 4️⃣ Menjalankan Aplikasi

### Local Development
```bash
streamlit run app.py
```

### Troubleshooting

**❌ Error: "Gagal memambaca Google Sheet"**
- Cek `.streamlit/secrets.toml` sudah benar
- Cek Service Account sudah di-share ke Google Sheet
- Cek ID Spreadsheet benar di secrets.toml

**❌ "Data dari Google Sheet kosong"**
- Pastikan Sheet1 memiliki kolom header: input, instruksi_ats, output_ats, status, nama_validator
- Pastikan ada minimal 1 baris data dengan nilai di kolom `input`
- Cek Google Sheet dibuka/shared dengan benar

**❌ "Area Kerja 0 data"**
- Login dengan salah satu user: dr.Dhaifina, dr.Dian, dr.Natalia, dr.Wulan
- Klik "Ambil Tugas Baru" untuk mengambil data dari pool
- Jika "Sisa Data Tersedia" = 0, berarti tidak ada data di Google Sheet yang memiliki kolom `input` kosong dan `nama_validator` kosong

---

## 5️⃣ Admin Monitoring Access

### Login Admin
- URL: [app_url]/📊_Admin_Monitoring
- Password: `admin123` (ganti di file `02_📊_Admin_Monitoring.py` jika perlu)

### Fitur Admin:
- 📊 Statistik real-time semua user
- 📈 Grafik progress pelabelan
- 📋 Tabel detail lengkap dengan filter
- 📥 Export data ke CSV

---

## 6️⃣ Struktur Alur Data

```
Google Sheet (Data Source)
    ↓
Streamlit Connection (read/write)
    ↓
App Pages:
  - Home (app.py)
  - User Labeling (pages/01_👤_User_Labeling.py)
  - Admin Monitoring (pages/02_📊_Admin_Monitoring.py)
```

---

## 📞 Support

Jika ada masalah, gunakan Debug Mode di sidebar User Labeling:
- ✅ Cek jumlah data
- ✅ Lihat kolom yang tersedia
- ✅ Preview data dari Google Sheet

---

**Last Updated:** April 9, 2026
