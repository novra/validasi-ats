import random

import pandas as pd


ATS_LEVELS = [
    ("red", "Merah", "ATS 1"),
    ("orange", "Orange", "ATS 2"),
    ("green", "Hijau", "ATS 3"),
    ("blue", "Biru", "ATS 4"),
    ("white", "Putih", "ATS 5"),
]

SYNTHETIC_CASE_PREFIX = "ATS-SYN"

ATS_KNOWLEDGE = {
    "red": "ATS 1/Merah digunakan untuk kondisi mengancam nyawa yang membutuhkan penanganan segera tanpa menunggu.",
    "orange": "ATS 2/Orange digunakan untuk kondisi sangat gawat atau berisiko cepat memburuk yang harus dinilai dan ditangani sangat cepat.",
    "green": "ATS 3/Hijau digunakan untuk kondisi urgent dengan potensi memburuk, nyeri sedang, atau kebutuhan evaluasi dokter dalam waktu relatif cepat.",
    "blue": "ATS 4/Biru digunakan untuk kondisi semi-urgent, stabil, dan umumnya dapat menunggu dengan pemantauan.",
    "white": "ATS 5/Putih digunakan untuk kondisi non-urgent, stabil, keluhan ringan/kronis, atau kebutuhan administratif/kontrol.",
}

ATS_INTERVENTIONS = {
    "red": "Aktifkan resusitasi, nilai ABCDE, amankan jalan napas, berikan oksigen aliran tinggi/ventilasi, pasang akses IV, monitor jantung, kontrol perdarahan, dan siapkan obat/prosedur penyelamatan nyawa sesuai indikasi.",
    "orange": "Tempatkan di area emergensi, lakukan ABCDE cepat, berikan oksigen bila hipoksemia, pasang akses IV, monitor ketat, berikan analgesia/terapi awal, dan siapkan eskalasi resusitasi bila memburuk.",
    "green": "Lakukan penilaian primer dan sekunder, monitor tanda vital berkala, berikan analgesia/antipiretik/cairan sesuai kebutuhan, lakukan pemeriksaan penunjang terarah, dan observasi respons klinis.",
    "blue": "Lakukan pemeriksaan terarah, rawat luka/keluhan minor, berikan terapi simptomatik, edukasi tanda bahaya, dan rencanakan evaluasi lanjutan bila keluhan berubah.",
    "white": "Lakukan penilaian singkat, berikan edukasi, tindakan sederhana atau administrasi sesuai kebutuhan, dan arahkan kontrol rawat jalan bila tidak ada tanda bahaya.",
}

ATS_CONCLUSIONS = {
    "red": "Kesimpulan: ATS 1/Merah karena terdapat ancaman nyawa segera dan membutuhkan intervensi resusitasi tanpa penundaan.",
    "orange": "Kesimpulan: ATS 2/Orange karena kondisi berisiko tinggi atau sangat nyeri/berat sehingga membutuhkan penanganan sangat cepat.",
    "green": "Kesimpulan: ATS 3/Hijau karena pasien stabil tetapi memiliki keluhan urgent yang perlu evaluasi dan terapi dalam waktu cepat.",
    "blue": "Kesimpulan: ATS 4/Biru karena kondisi stabil, semi-urgent, dan tidak menunjukkan tanda bahaya mayor saat triase.",
    "white": "Kesimpulan: ATS 5/Putih karena keluhan ringan/non-urgent, tanda vital stabil, dan tidak ada indikasi kegawatan akut.",
}

NARRATIVE_OPENINGS = [
    "Pasien datang ke IGD diantar keluarga.",
    "Pasien tiba di ruang triase IGD dengan bantuan petugas.",
    "Pasien dibawa ke IGD setelah keluhan dirasakan semakin mengganggu.",
    "Pasien masuk ke IGD dan segera dilakukan penilaian awal oleh perawat triase.",
]

NARRATIVE_PROGRESSIONS = [
    "Menurut keluarga, keluhan muncul mendadak dan tampak lebih berat dibanding kondisi biasanya.",
    "Pasien menyampaikan keluhan bertambah jelas selama perjalanan menuju rumah sakit.",
    "Sebelum tiba di IGD, pasien sempat beristirahat di rumah namun keluhan tidak membaik.",
    "Keluarga mengatakan pasien tampak lebih lemah dan membutuhkan bantuan untuk mobilisasi.",
]

NARRATIVE_OBSERVATIONS = [
    "Saat triase, pasien tampak tidak nyaman dan membutuhkan pemantauan tanda vital.",
    "Pada pemeriksaan awal, petugas menilai kesadaran, jalan napas, pernapasan, sirkulasi, dan derajat nyeri.",
    "Kondisi umum pasien dinilai dari respons bicara, warna kulit, pola napas, dan kemampuan mengikuti instruksi.",
    "Petugas melakukan anamnesis singkat sambil memantau perubahan kondisi pasien.",
]

DEMOGRAPHICS = [
    ("Laki-laki", 2),
    ("Perempuan", 4),
    ("Laki-laki", 9),
    ("Perempuan", 16),
    ("Laki-laki", 24),
    ("Perempuan", 31),
    ("Laki-laki", 42),
    ("Perempuan", 55),
    ("Laki-laki", 67),
    ("Perempuan", 74),
]

LEVEL_SCENARIOS = {
    "red": [
        ("tidak sadar setelah ditemukan terjatuh di kamar mandi", "napas gasping, nadi karotis lemah", "GCS 5, TD 70/40, HR 132, RR 8, SpO2 78%"),
        ("henti napas mendadak saat tiba di IGD", "sianosis, tidak ada respons nyeri", "GCS 3, TD tidak terukur, HR 38, RR 0, SpO2 62%"),
        ("kejang terus-menerus selama lebih dari 15 menit", "mulut berbusa, trauma lidah, tidak sadar", "GCS 6, TD 160/98, HR 146, RR 10, SpO2 84%"),
        ("sesak sangat berat disertai suara stridor", "retraksi berat, sulit bicara, gelisah ekstrem", "GCS 10, TD 88/54, HR 138, RR 36, SpO2 76%"),
        ("luka tusuk dada dengan perdarahan aktif", "kulit dingin, pucat, penurunan kesadaran", "GCS 8, TD 74/42, HR 150, RR 34, SpO2 82%"),
        ("reaksi alergi berat setelah injeksi obat", "bengkak bibir, wheezing berat, hipotensi", "GCS 12, TD 78/45, HR 142, RR 32, SpO2 80%"),
        ("penurunan kesadaran mendadak pasca kecelakaan motor", "pupil anisokor, muntah proyektil", "GCS 7, TD 190/110, HR 54, RR 10, SpO2 86%"),
        ("luka bakar luas akibat ledakan kompor", "wajah terbakar, suara serak, jelaga di mulut", "GCS 11, TD 82/48, HR 148, RR 34, SpO2 79%"),
        ("perdarahan pasca melahirkan sangat banyak", "lemas, berkeringat dingin, hampir pingsan", "GCS 9, TD 68/38, HR 156, RR 30, SpO2 88%"),
        ("nyeri dada hebat lalu kolaps di ruang tunggu", "tidak responsif, napas tidak adekuat", "GCS 4, TD 60/35, HR 32, RR 6, SpO2 70%"),
    ],
    "orange": [
        ("nyeri dada kiri menjalar ke lengan sejak 40 menit", "keringat dingin, mual, tampak sangat cemas", "GCS 15, TD 92/58, HR 118, RR 24, SpO2 93%"),
        ("sesak berat sejak pagi pada riwayat asma", "hanya mampu bicara satu-dua kata", "GCS 15, TD 140/88, HR 126, RR 34, SpO2 88%"),
        ("kelemahan lengan dan bicara pelo mendadak", "onset 1 jam, wajah mencong", "GCS 14, TD 188/104, HR 96, RR 22, SpO2 96%"),
        ("demam tinggi dengan menggigil dan tampak toksik", "akral dingin, nyeri seluruh badan", "GCS 14, TD 86/52, HR 132, RR 28, SpO2 94%"),
        ("nyeri perut kanan bawah sangat hebat", "muntah berulang, nyeri tekan lepas", "GCS 15, TD 100/64, HR 122, RR 24, SpO2 97%"),
        ("trauma kepala dengan kebingungan setelah jatuh", "amnesia kejadian, muntah dua kali", "GCS 12, TD 150/92, HR 104, RR 22, SpO2 96%"),
        ("perdarahan saluran cerna berupa muntah darah", "lemas, pusing saat berdiri", "GCS 15, TD 90/55, HR 124, RR 24, SpO2 95%"),
        ("nyeri hebat skala 9 pada tungkai setelah kecelakaan", "deformitas jelas, sulit digerakkan", "GCS 15, TD 136/84, HR 116, RR 24, SpO2 98%"),
        ("bayi demam tinggi tampak sangat lemas", "minum menurun, tangisan lemah", "GCS sesuai usia menurun, TD 78/46, HR 168, RR 42, SpO2 94%"),
        ("pikiran bunuh diri dengan rencana jelas", "gelisah, membawa obat yang akan diminum", "GCS 15, TD 128/82, HR 112, RR 22, SpO2 98%"),
    ],
    "green": [
        ("sesak sedang sejak dua hari", "masih dapat bicara kalimat pendek", "GCS 15, TD 132/84, HR 102, RR 26, SpO2 94%"),
        ("nyeri perut sedang disertai diare", "tidak ada tanda dehidrasi berat", "GCS 15, TD 118/76, HR 96, RR 20, SpO2 98%"),
        ("demam tiga hari dengan nyeri menelan", "lemas tetapi masih sadar penuh", "GCS 15, TD 112/72, HR 104, RR 20, SpO2 98%"),
        ("luka robek cukup dalam di lengan", "perdarahan terkontrol dengan penekanan", "GCS 15, TD 124/78, HR 92, RR 18, SpO2 99%"),
        ("nyeri kepala berat bertahap sejak kemarin", "tidak ada kelemahan anggota gerak", "GCS 15, TD 168/96, HR 88, RR 18, SpO2 98%"),
        ("muntah berulang sejak malam", "mulut agak kering, masih buang air kecil", "GCS 15, TD 108/70, HR 104, RR 20, SpO2 98%"),
        ("nyeri pinggang kanan dengan demam ringan", "nyeri saat berkemih", "GCS 15, TD 122/76, HR 100, RR 20, SpO2 98%"),
        ("cedera pergelangan kaki setelah jatuh", "bengkak, nyeri skala 6, tidak bisa menapak", "GCS 15, TD 126/80, HR 94, RR 18, SpO2 99%"),
        ("anak demam dengan ruam dan tampak rewel", "minum masih mau, tidak sesak", "GCS 15, TD 96/62, HR 126, RR 28, SpO2 98%"),
        ("gula darah tinggi dengan banyak minum", "tidak muntah, tidak sesak kusmaul", "GCS 15, TD 130/82, HR 98, RR 20, SpO2 98%"),
    ],
    "blue": [
        ("batuk pilek tiga hari tanpa sesak", "demam ringan, nafsu makan menurun sedikit", "GCS 15, TD 118/74, HR 88, RR 18, SpO2 99%"),
        ("nyeri telinga sejak semalam", "tidak ada keluar cairan, demam ringan", "GCS 15, TD 116/72, HR 86, RR 18, SpO2 99%"),
        ("luka lecet luas di lutut setelah terjatuh", "perdarahan minimal, nyeri skala 4", "GCS 15, TD 120/78, HR 90, RR 18, SpO2 99%"),
        ("mual dan muntah dua kali setelah makan", "tidak diare, tidak dehidrasi", "GCS 15, TD 112/70, HR 92, RR 18, SpO2 99%"),
        ("nyeri gigi mengganggu sejak dua hari", "bengkak lokal kecil, tidak sulit menelan", "GCS 15, TD 122/78, HR 88, RR 18, SpO2 99%"),
        ("cedera jari tertimpa pintu", "memar, gerak terbatas, tidak ada deformitas berat", "GCS 15, TD 118/76, HR 84, RR 18, SpO2 99%"),
        ("ruam gatal menyebar setelah makan laut", "tanpa sesak, tanpa bengkak bibir", "GCS 15, TD 120/76, HR 90, RR 18, SpO2 99%"),
        ("nyeri punggung bawah setelah mengangkat barang", "tidak baal, tidak gangguan BAK", "GCS 15, TD 126/80, HR 86, RR 18, SpO2 99%"),
        ("mata merah dan berair sejak pagi", "penglihatan tetap baik, tidak nyeri berat", "GCS 15, TD 118/74, HR 82, RR 18, SpO2 99%"),
        ("diare cair tiga kali hari ini", "masih bisa minum, tidak tampak lemas", "GCS 15, TD 114/72, HR 90, RR 18, SpO2 99%"),
    ],
    "white": [
        ("kontrol luka operasi yang tampak kering", "tidak demam, tidak ada nyeri bermakna", "GCS 15, TD 118/76, HR 78, RR 16, SpO2 99%"),
        ("meminta surat keterangan sehat", "tidak ada keluhan akut", "GCS 15, TD 116/74, HR 76, RR 16, SpO2 99%"),
        ("gatal ringan di lengan sejak seminggu", "lesi kecil, tidak nyeri, tidak demam", "GCS 15, TD 120/78, HR 80, RR 16, SpO2 99%"),
        ("pilek ringan tanpa demam", "aktivitas normal, makan minum baik", "GCS 15, TD 114/72, HR 78, RR 16, SpO2 99%"),
        ("nyeri otot ringan setelah olahraga", "tidak ada trauma, nyeri skala 2", "GCS 15, TD 118/74, HR 82, RR 16, SpO2 99%"),
        ("permintaan ganti perban luka kecil", "luka bersih, tidak ada perdarahan", "GCS 15, TD 116/72, HR 78, RR 16, SpO2 99%"),
        ("keluhan rambut rontok kronis", "tidak ada gejala akut", "GCS 15, TD 112/70, HR 76, RR 16, SpO2 99%"),
        ("konsultasi hasil laboratorium rutin", "tidak ada keluhan saat ini", "GCS 15, TD 120/76, HR 80, RR 16, SpO2 99%"),
        ("lecet kecil di jari sejak kemarin", "sudah berhenti berdarah, nyeri minimal", "GCS 15, TD 118/74, HR 78, RR 16, SpO2 99%"),
        ("minta imunisasi sesuai jadwal", "kondisi umum baik, tidak demam", "GCS 15, TD 116/72, HR 76, RR 16, SpO2 99%"),
    ],
}


def extract_learning_section(learning_notes, section_name):
    if not learning_notes:
        return ""

    markers = [
        "POLA_KONTEKS:",
        "POLA_PENGETAHUAN:",
        "POLA_INTERVENSI_IGD:",
        "POLA_INSTRUKSI:",
        "POLA_OUTPUT:",
        "ATURAN_GENERASI:",
    ]
    start_marker = f"{section_name}:"
    start_index = learning_notes.find(start_marker)
    if start_index == -1:
        return ""

    content_start = start_index + len(start_marker)
    content_end = len(learning_notes)
    for marker in markers:
        if marker == start_marker:
            continue
        marker_index = learning_notes.find(marker, content_start)
        if marker_index != -1:
            content_end = min(content_end, marker_index)

    return learning_notes[content_start:content_end].strip()


def build_instruction_ats(level_key, learning_notes=""):
    context_style = extract_learning_section(learning_notes, "POLA_KONTEKS")
    knowledge_style = extract_learning_section(learning_notes, "POLA_PENGETAHUAN")
    intervention_style = extract_learning_section(learning_notes, "POLA_INTERVENSI_IGD")
    instruction_style = extract_learning_section(learning_notes, "POLA_INSTRUKSI")
    generation_rules = extract_learning_section(learning_notes, "ATURAN_GENERASI")

    context_guidance = (
        f"\n\nPola konteks dari data existing:\n{context_style}"
        if context_style else ""
    )
    knowledge_guidance = (
        f"\n\nPola pengetahuan dari data existing:\n{knowledge_style}"
        if knowledge_style else ""
    )
    intervention_guidance = (
        f"\n\nPola intervensi dari data existing:\n{intervention_style}"
        if intervention_style else ""
    )
    instruction_guidance = (
        f"\n\nPola instruksi dari data existing:\n{instruction_style}"
        if instruction_style else ""
    )
    rules_guidance = (
        f"\n\nAturan generasi dari data existing:\n{generation_rules}"
        if generation_rules else ""
    )

    return (
        "Konteks:\n"
        "Anda berperan sebagai dokter atau perawat IGD yang sedang melakukan triase awal terhadap pasien "
        "berdasarkan data input. Tugas Anda adalah menilai tingkat kegawatan, stabilitas tanda vital, "
        "risiko perburukan, dan kebutuhan intervensi segera sesuai prinsip Australian Triage Scale."
        f"{context_guidance}\n\n"
        f"Pengetahuan:\n{ATS_KNOWLEDGE[level_key]}{knowledge_guidance}\n\n"
        f"Intervensi penyelamatan nyawa segera yang umum di IGD:\n{ATS_INTERVENTIONS[level_key]}{intervention_guidance}\n\n"
        "Instruksi:\n"
        "Gunakan data pada kolom input sebagai kasus pasien yang harus dinilai. Tentukan level ATS yang paling tepat "
        "berdasarkan kondisi klinis, tanda vital, derajat kegawatan, risiko perburukan, kebutuhan waktu penanganan, "
        "dan kebutuhan intervensi segera. "
        "Berikan jawaban ringkas dan konsisten dengan format output ATS."
        f"{instruction_guidance}"
        f"{rules_guidance}"
    )


def build_output_ats(level_key, level_color, ats_category, complaint, clinical_signs, vital_signs):
    return (
        "Analisis singkat kondisi pasien:\n"
        f"- Keluhan utama: {complaint}.\n"
        f"- Temuan awal: {clinical_signs}.\n"
        f"- Tanda vital: {vital_signs}.\n"
        f"- Interpretasi triase: kondisi paling sesuai dengan {ats_category}/{level_color}.\n\n"
        f"{ATS_CONCLUSIONS[level_key]}"
    )


def build_case_narrative(case_id, gender, age, complaint, duration, clinical_signs, vital_signs, comorbidity, rng):
    opening = rng.choice(NARRATIVE_OPENINGS)
    progression = rng.choice(NARRATIVE_PROGRESSIONS)
    observation = rng.choice(NARRATIVE_OBSERVATIONS)
    pain_scale = rng.choice(["2/10", "4/10", "6/10", "8/10", "9/10"])
    intake = rng.choice([
        "makan dan minum masih cukup",
        "asupan makan menurun sejak keluhan memberat",
        "minum masih bisa tetapi lebih sedikit dari biasanya",
        "belum makan sejak keluhan muncul",
    ])
    prior_action = rng.choice([
        "Belum ada obat yang diminum sebelum datang ke IGD.",
        "Pasien sempat minum obat bebas di rumah namun keluhan belum membaik.",
        "Keluarga hanya melakukan observasi di rumah sebelum memutuskan ke IGD.",
        "Pasien langsung dibawa ke IGD karena keluarga khawatir dengan perubahan kondisinya.",
    ])

    return (
        f"ID Kasus: {case_id}\n\n"
        f"{opening} Pasien {gender}, {age} tahun, datang dengan keluhan utama {complaint}. "
        f"Keluhan dirasakan {duration}. {progression} {prior_action}\n\n"
        f"Pada anamnesis singkat, pasien/keluarga menjelaskan bahwa keluhan tersebut disertai temuan awal berupa "
        f"{clinical_signs}. Skala nyeri atau ketidaknyamanan saat triase diperkirakan {pain_scale}. "
        f"Riwayat yang diketahui: {comorbidity}. Untuk kebutuhan dasar, {intake}.\n\n"
        f"{observation} Tanda vital saat masuk: {vital_signs}. "
        f"Data ini merupakan catatan awal triase dan perlu digunakan untuk menentukan prioritas ATS berdasarkan "
        f"derajat kegawatan, risiko perburukan, stabilitas tanda vital, serta kebutuhan intervensi segera di IGD."
    )


def generate_synthetic_ats_cases(total_cases=700, seed=20260518, learning_notes=""):
    if total_cases % len(ATS_LEVELS) != 0:
        raise ValueError("total_cases harus habis dibagi 5 agar level ATS seimbang.")

    rng = random.Random(seed)
    cases_per_level = total_cases // len(ATS_LEVELS)
    rows = []
    global_number = 1

    for level_key, level_color, ats_category in ATS_LEVELS:
        scenarios = LEVEL_SCENARIOS[level_key]
        for level_number in range(1, cases_per_level + 1):
            gender, base_age = DEMOGRAPHICS[(level_number - 1) % len(DEMOGRAPHICS)]
            age = max(1, base_age + rng.choice([-2, -1, 0, 1, 2]))
            complaint, clinical_signs, vital_signs = scenarios[(level_number - 1) % len(scenarios)]
            duration = rng.choice([
                "10 menit",
                "30 menit",
                "1 jam",
                "3 jam",
                "sejak pagi",
                "1 hari",
                "2 hari",
                "3 hari",
            ])
            comorbidity = rng.choice([
                "tanpa riwayat penyakit berat",
                "riwayat hipertensi",
                "riwayat diabetes melitus",
                "riwayat asma",
                "riwayat penyakit jantung",
                "tidak diketahui riwayat penyakit sebelumnya",
            ])
            case_id = f"{SYNTHETIC_CASE_PREFIX}-{global_number:04d}"
            case_text = build_case_narrative(
                case_id,
                gender,
                age,
                complaint,
                duration,
                clinical_signs,
                vital_signs,
                comorbidity,
                rng,
            )
            rows.append(
                {
                    "instruction_ats": build_instruction_ats(level_key, learning_notes),
                    "input": case_text,
                    "output_ats": build_output_ats(
                        level_key,
                        level_color,
                        ats_category,
                        complaint,
                        clinical_signs,
                        vital_signs,
                    ),
                    "validator": "sintetis",
                    "status": "",
                    "synthetic_case_id": case_id,
                    "synthetic_ats_level": level_color,
                    "synthetic_ats_category": ats_category,
                }
            )
            global_number += 1

    rng.shuffle(rows)
    return pd.DataFrame(rows)


def get_synthetic_balance_summary(df):
    if "synthetic_ats_level" not in df.columns:
        return pd.DataFrame(columns=["synthetic_ats_level", "jumlah"])

    summary = (
        df["synthetic_ats_level"]
        .fillna("")
        .astype(str)
        .str.strip()
        .replace("", pd.NA)
        .dropna()
        .value_counts()
        .rename_axis("synthetic_ats_level")
        .reset_index(name="jumlah")
    )
    level_order = {level_color: index for index, (_, level_color, _) in enumerate(ATS_LEVELS)}
    summary["order"] = summary["synthetic_ats_level"].map(level_order).fillna(99)
    return summary.sort_values(["order", "synthetic_ats_level"]).drop(columns=["order"])
