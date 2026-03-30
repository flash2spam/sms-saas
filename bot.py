import threading
import time
import csv
import os
import requests
import json

pause_event = threading.Event()
pause_event.set()

running = True

SUCCESS_COUNT = 0
FAIL_COUNT = 0

DELAY = 2
PAUSE_EVERY = 10
PAUSE_TIME = 30

MESSAGE_TEXT = "🔥 Message depuis ton SaaS"

BLACKLIST = []
DEVICES = []
HISTORY = []

FILE = "devices.json"

# ===== LOAD =====
def load_devices():
    global DEVICES
    if os.path.exists(FILE):
        with open(FILE, "r") as f:
            DEVICES = json.load(f)

# ===== SAVE =====
def save_devices():
    with open(FILE, "w") as f:
        json.dump(DEVICES, f)

# ===== ADD DEVICE =====
def add_device(name, device_id, username, password):
    DEVICES.append({
        "name": name,
        "device_id": device_id,
        "username": username,
        "password": password,
        "active": True,
        "success": 0,
        "fail": 0,
        "sent": 0
    })
    save_devices()

def get_active_devices():
    return [d for d in DEVICES if d["active"]]

# ===== MAIN =====
def main():
    global SUCCESS_COUNT, FAIL_COUNT

    load_devices()  # 🔥 reload devices

    file_path = "uploads/contacts.csv"

    if not os.path.exists(file_path):
        print("❌ Aucun CSV")
        return

    with open(file_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    index = 0

    for row in rows:

        if not running:
            break

        while not pause_event.is_set():
            time.sleep(1)

        devices = get_active_devices()
        if not devices:
            print("❌ Aucun device actif")
            break

        device = devices[index % len(devices)]
        index += 1

        # 🔥 FIX champs manquants (IMPORTANT)
        if "sent" not in device:
            device["sent"] = 0
        if "success" not in device:
            device["success"] = 0
        if "fail" not in device:
            device["fail"] = 0

        phone = row.get("phone")

        if not phone:
            continue

        if phone in BLACKLIST:
            continue

        try:
            response = requests.post(
                "https://api.sms-gate.app/3rdparty/v1/message",
                json={
                    "device": device["device_id"],
                    "phoneNumbers": [phone],
                    "message": MESSAGE_TEXT
                },
                auth=(device["username"], device["password"]),
                timeout=30
            )

            device["sent"] += 1

            print("📨", phone, "|", response.status_code)

            # ✅ SUCCESS si code < 300
            if response.status_code < 300:
                SUCCESS_COUNT += 1
                device["success"] += 1

                HISTORY.append({
                    "phone": phone,
                    "device": device["name"],
                    "status": "success"
                })

            else:
                FAIL_COUNT += 1
                device["fail"] += 1

                HISTORY.append({
                    "phone": phone,
                    "device": device["name"],
                    "status": "fail"
                })

        except Exception as e:
            print("❌ ERREUR:", e)
            FAIL_COUNT += 1
            device["fail"] += 1

        # ⏸️ pause automatique
        if device["sent"] % PAUSE_EVERY == 0:
            print(f"⏸️ Pause {PAUSE_TIME}s")
            time.sleep(PAUSE_TIME)

        save_devices()

        # ⏱️ délai entre SMS
        time.sleep(DELAY)