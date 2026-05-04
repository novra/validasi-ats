import threading

SHEET_WRITE_LOCK = threading.RLock()

def get_sheet_write_lock():
    return SHEET_WRITE_LOCK
