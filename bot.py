import sqlite3
import threading
import time
import requests
import csv
import os

pause_event = threading.Event()
pause_event.set()

running = True

SUCCESS_COUNT = 0
FAIL_COUNT = 0

DELAY = 2
PAUSE_EVERY = 10
PAUSE_TIME = 30

MESSAGE_TEXT = "🔥 Message SaaS"

DB = "data.db"

# ===== INIT DB =====
def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS devices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        device_id TEXT,
        username TEXT,
        password TEXT,
        active INTEGER,
        success INTEGER,
        fail INTEGER,
        sent INTEGER
    )
    """)

    conn.commit()
    conn.close()

# ===== ADD =====
def add_device(name, device_id, username, password):
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    c.execute("""
    INSERT INTO devices (name, device_id, username, password, active, success, fail, sent)
    VALUES (?, ?, ?, ?, 1, 0, 0, 0)
    """, (name, device_id, username, password))

    conn.commit()
    conn.close()

# ===== GET =====
def get_devices():
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    rows = c.execute("SELECT * FROM devices").fetchall()
    conn.close()

    devices = []
    for r in rows:
        devices.append({
            "name": r[1],
            "device_id": r[2],
            "username": r[3],
            "password": r[4],
            "active": bool(r[5]),
            "success": r[6],
            "fail": r[7],
            "sent": r[8]
        })

    return devices

# ===== UPDATE =====
def update_device(name, field, value):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute(f"UPDATE devices SET {field}=? WHERE name=?", (value, name))
    conn.commit()
    conn.close()

# ===== DELETE =====
def delete_device(name):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("DELETE FROM devices WHERE name=?", (name,))
    conn.commit()
    conn.close()

# ===== BOT =====
def main():
    global SUCCESS_COUNT, FAIL_COUNT

    file_path = "uploads/contacts.csv"

    if not os.path.exists(file_path):
        print("❌ Pas de CSV")
        return

    with open(file_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    index = 0

    for row in rows:

        if not running:
            break

        while not pause_event.is_set():
            time.sleep(1)

        devices = [d for d in get_devices() if d["active"]]

        if not devices:
            print("❌ Aucun device actif")
            break

        device = devices[index % len(devices)]
        index += 1

        phone = row.get("phone")
        if not phone:
            continue

        try:
            r = requests.post(
                "https://api.sms-gate.app/3rdparty/v1/message",
                json={
                    "device": device["device_id"],
                    "phoneNumbers": [phone],
                    "message": MESSAGE_TEXT
                },
                auth=(device["username"], device["password"])
            )

            if r.status_code < 300:
                SUCCESS_COUNT += 1
                update_device(device["name"], "success", device["success"]+1)
            else:
                FAIL_COUNT += 1
                update_device(device["name"], "fail", device["fail"]+1)

            update_device(device["name"], "sent", device["sent"]+1)

        except Exception as e:
            print("❌", e)

        time.sleep(DELAY)
