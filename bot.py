import sqlite3
import threading
import time
import requests
import csv
import os
import random

pause_event = threading.Event()
pause_event.set()

running = True

SUCCESS_COUNT = 0
FAIL_COUNT = 0

DELAY = 2
PAUSE_EVERY = 10
PAUSE_TIME = 30

MESSAGE_TEXT = "🔥 Message depuis ton SaaS"

# ===== TEMPLATES DE MESSAGES =====
# Chaque template doit contenir {message} pour insérer le message principal
# Tu peux aussi utiliser {phone} pour le numéro du destinataire
MESSAGE_TEMPLATES = []

DB = "data.db"
CSV_PATH = "uploads/contacts.csv"


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
        active INTEGER DEFAULT 1,
        success INTEGER DEFAULT 0,
        fail INTEGER DEFAULT 0,
        sent INTEGER DEFAULT 0
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS blacklist (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phone TEXT UNIQUE
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phone TEXT,
        device TEXT,
        status TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Table pour stocker les templates de messages
    c.execute("""
    CREATE TABLE IF NOT EXISTS message_templates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        content TEXT NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.commit()
    conn.close()


# ===== TEMPLATES =====
def add_template(content):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("INSERT INTO message_templates (content) VALUES (?)", (content,))
    conn.commit()
    conn.close()

def get_templates():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    rows = c.execute("SELECT id, content, created_at FROM message_templates ORDER BY id DESC").fetchall()
    conn.close()
    return [{"id": r[0], "content": r[1], "created_at": r[2]} for r in rows]

def delete_template(tid):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("DELETE FROM message_templates WHERE id=?", (tid,))
    conn.commit()
    conn.close()

def get_random_message():
    """Retourne un message aléatoire parmi les templates, ou le message par défaut."""
    templates = get_templates()
    if templates:
        chosen = random.choice(templates)
        return chosen["content"]
    return MESSAGE_TEXT


# ===== DEVICES =====
def add_device(name, device_id, username, password):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
        INSERT INTO devices (name, device_id, username, password, active, success, fail, sent)
        VALUES (?, ?, ?, ?, 1, 0, 0, 0)
    """, (name, device_id, username, password))
    conn.commit()
    conn.close()


def get_devices():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    rows = c.execute("SELECT * FROM devices").fetchall()
    conn.close()
    return [{
        "id": r[0], "name": r[1], "device_id": r[2],
        "username": r[3], "password": r[4],
        "active": bool(r[5]), "success": r[6],
        "fail": r[7], "sent": r[8]
    } for r in rows]


def update_device(name, field, value):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute(f"UPDATE devices SET {field}=? WHERE name=?", (value, name))
    conn.commit()
    conn.close()


def delete_device(name):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("DELETE FROM devices WHERE name=?", (name,))
    conn.commit()
    conn.close()


# ===== BLACKLIST =====
def add_blacklist(phone):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO blacklist (phone) VALUES (?)", (phone,))
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    conn.close()


def remove_blacklist(phone):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("DELETE FROM blacklist WHERE phone=?", (phone,))
    conn.commit()
    conn.close()


def get_blacklist():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    rows = c.execute("SELECT phone FROM blacklist").fetchall()
    conn.close()
    return [r[0] for r in rows]


def is_blacklisted(phone):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    row = c.execute("SELECT 1 FROM blacklist WHERE phone=?", (phone,)).fetchone()
    conn.close()
    return row is not None


# ===== HISTORY =====
def add_history(phone, device, status):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("INSERT INTO history (phone, device, status) VALUES (?, ?, ?)",
              (phone, device, status))
    conn.commit()
    conn.close()


def get_history(filter_status=None, limit=100):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    if filter_status:
        rows = c.execute(
            "SELECT phone, device, status, timestamp FROM history WHERE status=? ORDER BY id DESC LIMIT ?",
            (filter_status, limit)
        ).fetchall()
    else:
        rows = c.execute(
            "SELECT phone, device, status, timestamp FROM history ORDER BY id DESC LIMIT ?",
            (limit,)
        ).fetchall()
    conn.close()
    return [{"phone": r[0], "device": r[1], "status": r[2], "timestamp": r[3]} for r in rows]


# ===== CSV HELPERS =====
def remove_phone_from_csv(phone):
    if not os.path.exists(CSV_PATH):
        return
    try:
        with open(CSV_PATH, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        remaining = [r for r in rows if r.get("phone", "").strip() != phone]
        with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["phone"])
            writer.writeheader()
            writer.writerows(remaining)
        print(f"🗑️  {phone} retiré du CSV ({len(remaining)} restants)")
    except Exception as e:
        print(f"⚠️  Erreur suppression CSV: {e}")


def delete_csv():
    if os.path.exists(CSV_PATH):
        os.remove(CSV_PATH)
        print("🗑️  CSV supprimé")


def csv_exists():
    return os.path.exists(CSV_PATH)


def csv_count():
    if not os.path.exists(CSV_PATH):
        return 0
    try:
        with open(CSV_PATH, newline="", encoding="utf-8") as f:
            return sum(1 for _ in csv.DictReader(f))
    except Exception:
        return 0


# ===== MAIN BOT =====
def main():
    global SUCCESS_COUNT, FAIL_COUNT

    if not os.path.exists(CSV_PATH):
        print("❌ Pas de CSV")
        return

    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    print(f"📋 {len(rows)} numéros chargés")

    index = 0
    session_sent = 0  # compteur pour délai adaptatif

    for row in rows:

        if not running:
            print("⛔ Bot arrêté")
            break

        while not pause_event.is_set():
            time.sleep(1)

        devices = [d for d in get_devices() if d["active"]]

        if not devices:
            print("❌ Aucun device actif")
            break

        device = devices[index % len(devices)]
        index += 1

        phone = row.get("phone", "").strip()
        if not phone:
            continue

        if is_blacklisted(phone):
            print(f"🚫 {phone} blacklisté — ignoré")
            remove_phone_from_csv(phone)
            continue

        # ===== ROTATION DU MESSAGE =====
        message = get_random_message()
        print(f"💬 Template utilisé: {message[:40]}...")

        try:
            r = requests.post(
                "https://api.sms-gate.app/3rdparty/v1/message",
                json={
                    "device": device["device_id"],
                    "phoneNumbers": [phone],
                    "message": message
                },
                auth=(device["username"], device["password"]),
                timeout=30
            )

            print(f"📨 {phone} | {r.status_code}")

            if r.status_code < 300:
                SUCCESS_COUNT += 1
                session_sent += 1
                update_device(device["name"], "success", device["success"] + 1)
                update_device(device["name"], "sent", device["sent"] + 1)
                add_history(phone, device["name"], "success")
                remove_phone_from_csv(phone)
            else:
                FAIL_COUNT += 1
                update_device(device["name"], "fail", device["fail"] + 1)
                update_device(device["name"], "sent", device["sent"] + 1)
                add_history(phone, device["name"], "fail")

        except Exception as e:
            print(f"❌ ERREUR: {e}")
            FAIL_COUNT += 1
            add_history(phone, device["name"], "fail")

        # ===== DÉLAI ADAPTATIF =====
        # Pause longue toutes les PAUSE_EVERY SMS
        current_device = get_devices()
        for d in current_device:
            if d["name"] == device["name"] and d["sent"] > 0 and d["sent"] % PAUSE_EVERY == 0:
                print(f"⏸️  Pause longue {PAUSE_TIME}s après {PAUSE_EVERY} SMS")
                time.sleep(PAUSE_TIME)
                break

        # Pause très longue toutes les 50 SMS (protection opérateur)
        if session_sent > 0 and session_sent % 50 == 0:
            extra = random.randint(120, 300)
            print(f"🛡️  Anti-ban: pause {extra}s après 50 SMS")
            time.sleep(extra)
        else:
            # Délai de base aléatoire
            time.sleep(random.uniform(DELAY, DELAY + 1.5))

    print(f"✅ Campagne terminée — {SUCCESS_COUNT} envoyés, {FAIL_COUNT} erreurs")
