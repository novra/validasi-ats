USER_CREDENTIALS = {
    "dr.Dhaifina": "DH261A",
    "dr.Dian": "DN482B",
    "dr.Natalia": "NT593C",
    "dr.Wulan": "WL704D",
}

AUTHORIZED_USERS = list(USER_CREDENTIALS.keys())

ADMIN_CREDENTIALS = {
    "admin": "TriaseBRIN2026",
    "admin_replacement": "ReplaceATS2026",
    "admin_synthetic": "SyntheticATS2026",
}

AUTHORIZED_ADMINS = list(ADMIN_CREDENTIALS.keys())
REPLACEMENT_ADMINS = ["admin", "admin_replacement"]
SYNTHETIC_DATA_ADMINS = ["admin_synthetic"]

REPLACEMENT_USER_CREDENTIALS = {
    "user 1": "RP101A",
    "user 2": "RP202B",
    "user 3": "RP303C",
}

AUTHORIZED_REPLACEMENT_USERS = list(REPLACEMENT_USER_CREDENTIALS.keys())
