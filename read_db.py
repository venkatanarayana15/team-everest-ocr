import os
import sqlite3
import re

folder = r"C:\Users\priya\.gemini\antigravity-ide\conversations"
dbs = [f for f in os.listdir(folder) if f.endswith(".db")]

for db in dbs:
    db_path = os.path.join(folder, db)
    try:
        with open(db_path, "rb") as f:
            data = f.read()
            
        ascii_strings = re.findall(b"[a-zA-Z0-9_\\-\\.\\:\/\\=\\?\\&\\%\\+\\@\\,\\;\\!\\*\\(\\)\\[\\]\\{\\}\\<\\>\\~\\^\\#]{8,}", data)
        seen = set()
        for s in ascii_strings:
            try:
                s_dec = s.decode('ascii')
                if s_dec in seen:
                    continue
                seen.add(s_dec)
                if "api_key" in s_dec.lower() or "chandra" in s_dec.lower():
                    if len(s_dec) < 150:
                        print(f"Db {db}: {s_dec}")
            except Exception:
                pass
    except Exception as e:
        print(f"Error reading {db}: {e}")
