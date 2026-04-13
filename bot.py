import sqlite3
import threading
import time
import requests
import csv
import os
import random
import io

DB = "data.db"

# ===== CONTEXTE PAR UTILISATEUR =====
_user_contexts = {}
_ctx_lock = threading.Lock()

def get_ctx(user_id):
    with _ctx_lock:
        if user_id not in _user_contexts:
            _user_contexts[user_id] = {
                "running": False,
                "pause_event": threading.Event(),
                "thread": None,
                "SUCCESS_COUNT": 0,
                "FAIL_COUNT": 0,
                "DELAY": 2.0,
                "PAUSE_EVERY": 10,
                "PAUSE_TIME": 30,
                "MESSAGE_TEXT": "🔥 Message depuis ton SaaS",
            }
            _user_contexts[user_id]["pause_event"].set()
        return _user_contexts[user_id]


# ===== INIT DB =====
def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT DEFAULT 'user',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    admin_user = os.environ.get("USERNAME", "admin")
    admin_pass = os.environ.get("PASSWORD", "1234")
    c.execute("""
        INSERT OR IGNORE INTO users (username, password, role)
        VALUES (?, ?, 'admin')
    """, (admin_user, admin_pass))

    c.execute("""
    CREATE TABLE IF NOT EXISTS devices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL DEFAULT 1,
        name TEXT,
        type TEXT DEFAULT 'smsgate',
        device_id TEXT,
        username TEXT,
        password TEXT,
        sid_cookie TEXT DEFAULT '',
        active INTEGER DEFAULT 1,
        success INTEGER DEFAULT 0,
        fail INTEGER DEFAULT 0,
        sent INTEGER DEFAULT 0,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)

    # Migration si colonnes manquantes
    for col, defval in [("type", "TEXT DEFAULT 'smsgate'"), ("sid_cookie", "TEXT DEFAULT ''")]:
        try:
            c.execute(f"ALTER TABLE devices ADD COLUMN {col} {defval}")
        except Exception:
            pass

    c.execute("""
    CREATE TABLE IF NOT EXISTS blacklist (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL DEFAULT 1,
        phone TEXT,
        UNIQUE(user_id, phone),
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL DEFAULT 1,
        phone TEXT,
        device TEXT,
        status TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS message_templates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL DEFAULT 1,
        content TEXT NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS contacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        phone TEXT NOT NULL,
        UNIQUE(user_id, phone),
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)

    # ===== TABLES TICKETS =====
    c.execute("""
    CREATE TABLE IF NOT EXISTS tickets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        subject TEXT NOT NULL,
        message TEXT NOT NULL,
        status TEXT DEFAULT 'open',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS ticket_replies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticket_id INTEGER NOT NULL,
        author_id INTEGER NOT NULL,
        author TEXT NOT NULL,
        role TEXT NOT NULL,
        message TEXT NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(ticket_id) REFERENCES tickets(id)
    )
    """)

    # read_by stocke les user_ids qui ont lu ce ticket (format CSV simple)
    try:
        c.execute("ALTER TABLE tickets ADD COLUMN read_by TEXT DEFAULT ''")
    except Exception:
        pass

    conn.commit()
    conn.close()


# ===== GESTION UTILISATEURS =====
def get_all_users():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    rows = c.execute("SELECT id, username, role, created_at FROM users ORDER BY id").fetchall()
    conn.close()
    return [{"id": r[0], "username": r[1], "role": r[2], "created_at": r[3]} for r in rows]


def get_user_by_credentials(username, password):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    row = c.execute(
        "SELECT id, username, role FROM users WHERE username=? AND password=?",
        (username, password)
    ).fetchone()
    conn.close()
    if row:
        return {"id": row[0], "username": row[1], "role": row[2]}
    return None


def get_user_by_id(user_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    row = c.execute("SELECT id, username, role FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()
    if row:
        return {"id": row[0], "username": row[1], "role": row[2]}
    return None


def create_user(username, password, role="user"):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                  (username, password, role))
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False


def delete_user(user_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("DELETE FROM devices WHERE user_id=?", (user_id,))
    c.execute("DELETE FROM blacklist WHERE user_id=?", (user_id,))
    c.execute("DELETE FROM history WHERE user_id=?", (user_id,))
    c.execute("DELETE FROM message_templates WHERE user_id=?", (user_id,))
    c.execute("DELETE FROM contacts WHERE user_id=?", (user_id,))
    c.execute("DELETE FROM tickets WHERE user_id=?", (user_id,))
    c.execute("DELETE FROM users WHERE id=?", (user_id,))
    conn.commit()
    conn.close()
    with _ctx_lock:
        _user_contexts.pop(user_id, None)


def update_user_password(user_id, new_password):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("UPDATE users SET password=? WHERE id=?", (new_password, user_id))
    conn.commit()
    conn.close()


# ===== CONTACTS DB =====
def import_contacts_from_csv(csv_content, user_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("DELETE FROM contacts WHERE user_id=?", (user_id,))
    count = 0
    reader = csv.DictReader(io.StringIO(csv_content))
    for row in reader:
        phone = row.get("phone", "").strip()
        if phone:
            try:
                c.execute("INSERT OR IGNORE INTO contacts (user_id, phone) VALUES (?, ?)", (user_id, phone))
                count += 1
            except Exception:
                pass
    conn.commit()
    conn.close()
    return count


def get_contacts(user_id, limit=200):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    rows = c.execute(
        "SELECT phone FROM contacts WHERE user_id=? ORDER BY id LIMIT ?",
        (user_id, limit)
    ).fetchall()
    conn.close()
    return [{"phone": r[0]} for r in rows]


def count_contacts(user_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    row = c.execute("SELECT COUNT(*) FROM contacts WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return row[0] if row else 0


def remove_phone_from_db(phone, user_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("DELETE FROM contacts WHERE phone=? AND user_id=?", (phone, user_id))
    conn.commit()
    conn.close()


def delete_all_contacts(user_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("DELETE FROM contacts WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()


def delete_single_contact(phone, user_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("DELETE FROM contacts WHERE phone=? AND user_id=?", (phone, user_id))
    conn.commit()
    conn.close()


def csv_exists(user_id):
    return count_contacts(user_id) > 0

def csv_count(user_id):
    return count_contacts(user_id)

def delete_csv(user_id):
    delete_all_contacts(user_id)


# ===== TEMPLATES =====
def add_template(content, user_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("INSERT INTO message_templates (user_id, content) VALUES (?, ?)", (user_id, content))
    conn.commit()
    conn.close()


def get_templates(user_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    rows = c.execute(
        "SELECT id, content, created_at FROM message_templates WHERE user_id=? ORDER BY id DESC",
        (user_id,)
    ).fetchall()
    conn.close()
    return [{"id": r[0], "content": r[1], "created_at": r[2]} for r in rows]


def delete_template(tid, user_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("DELETE FROM message_templates WHERE id=? AND user_id=?", (tid, user_id))
    conn.commit()
    conn.close()


def get_random_message(user_id):
    templates = get_templates(user_id)
    if templates:
        return random.choice(templates)["content"]
    return get_ctx(user_id)["MESSAGE_TEXT"]


# ===== DEVICES =====
def add_device(name, device_type, device_id, username, password, sid_cookie, user_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
        INSERT INTO devices (user_id, name, type, device_id, username, password, sid_cookie, active, success, fail, sent)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1, 0, 0, 0)
    """, (user_id, name, device_type, device_id, username, password, sid_cookie))
    conn.commit()
    conn.close()


def get_devices(user_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    rows = c.execute("""
        SELECT id, user_id, name, type, device_id, username, password, sid_cookie, active, success, fail, sent
        FROM devices WHERE user_id=?
    """, (user_id,)).fetchall()
    conn.close()
    return [{
        "id": r[0], "user_id": r[1], "name": r[2], "type": r[3],
        "device_id": r[4], "username": r[5], "password": r[6],
        "sid_cookie": r[7], "active": bool(r[8]),
        "success": r[9], "fail": r[10], "sent": r[11]
    } for r in rows]


def update_device(name, field, value, user_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute(f"UPDATE devices SET {field}=? WHERE name=? AND user_id=?", (value, name, user_id))
    conn.commit()
    conn.close()


def delete_device(name, user_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("DELETE FROM devices WHERE name=? AND user_id=?", (name, user_id))
    conn.commit()
    conn.close()


# ===== TEXTNOW SENDER =====
def send_textnow(phone, message, username, sid_cookie):
    try:
        sess = requests.Session()
        sess.cookies.set("SID", sid_cookie, domain=".textnow.com")
        sess.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.textnow.com/messaging",
            "Origin": "https://www.textnow.com",
        })
        payload = {
            "contact_value": phone,
            "contact_type": 2,
            "message": message,
            "read": 1,
            "message_direction": 2,
            "message_type": 1,
            "from_name": username,
        }
        r = sess.post(
            f"https://www.textnow.com/api/users/{username}/messages",
            json=payload,
            timeout=30
        )
        print(f"📨 TextNow → {phone} | {r.status_code}")
        return r.status_code < 300
    except Exception as e:
        print(f"❌ TextNow ERREUR: {e}")
        return False


# ===== BLACKLIST =====
def add_blacklist(phone, user_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO blacklist (user_id, phone) VALUES (?, ?)", (user_id, phone))
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    conn.close()


def remove_blacklist(phone, user_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("DELETE FROM blacklist WHERE phone=? AND user_id=?", (phone, user_id))
    conn.commit()
    conn.close()


def get_blacklist(user_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    rows = c.execute("SELECT phone FROM blacklist WHERE user_id=?", (user_id,)).fetchall()
    conn.close()
    return [r[0] for r in rows]


def is_blacklisted(phone, user_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    row = c.execute("SELECT 1 FROM blacklist WHERE phone=? AND user_id=?", (phone, user_id)).fetchone()
    conn.close()
    return row is not None


# ===== HISTORY =====
def add_history(phone, device, status, user_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("INSERT INTO history (user_id, phone, device, status) VALUES (?, ?, ?, ?)",
              (user_id, phone, device, status))
    conn.commit()
    conn.close()


def get_history(user_id, filter_status=None, limit=100):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    if filter_status:
        rows = c.execute(
            "SELECT phone, device, status, timestamp FROM history WHERE user_id=? AND status=? ORDER BY id DESC LIMIT ?",
            (user_id, filter_status, limit)
        ).fetchall()
    else:
        rows = c.execute(
            "SELECT phone, device, status, timestamp FROM history WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user_id, limit)
        ).fetchall()
    conn.close()
    return [{"phone": r[0], "device": r[1], "status": r[2], "timestamp": r[3]} for r in rows]


# ===== TICKETS =====
def get_tickets(user_id, role):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    if role == "admin":
        rows = c.execute("""
            SELECT t.id, t.user_id, u.username, t.subject, t.message, t.status, t.created_at, t.read_by,
                   (SELECT COUNT(*) FROM ticket_replies WHERE ticket_id=t.id) as reply_count
            FROM tickets t JOIN users u ON t.user_id=u.id
            ORDER BY t.id DESC
        """).fetchall()
    else:
        rows = c.execute("""
            SELECT t.id, t.user_id, u.username, t.subject, t.message, t.status, t.created_at, t.read_by,
                   (SELECT COUNT(*) FROM ticket_replies WHERE ticket_id=t.id) as reply_count
            FROM tickets t JOIN users u ON t.user_id=u.id
            WHERE t.user_id=?
            ORDER BY t.id DESC
        """, (user_id,)).fetchall()
    conn.close()

    result = []
    for r in rows:
        read_by = r[7] or ""
        read_ids = [x for x in read_by.split(",") if x]
        # unread: admin voit unread si non lu par admin, user voit unread si a une réponse admin non lue
        unread = 0
        if role == "admin" and str(user_id) not in read_ids:
            unread = 1
        elif role != "admin":
            # compte les réponses admin non lues
            uid_str = str(user_id)
            if uid_str not in read_ids and r[8] > 0:
                unread = 1
        result.append({
            "id": r[0], "user_id": r[1], "username": r[2],
            "subject": r[3], "message": r[4], "status": r[5],
            "created_at": r[6], "reply_count": r[8], "unread": unread
        })
    return result


def get_ticket_by_id(ticket_id, user_id, role):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    if role == "admin":
        row = c.execute("""
            SELECT t.id, t.user_id, u.username, t.subject, t.message, t.status, t.created_at
            FROM tickets t JOIN users u ON t.user_id=u.id
            WHERE t.id=?
        """, (ticket_id,)).fetchone()
    else:
        row = c.execute("""
            SELECT t.id, t.user_id, u.username, t.subject, t.message, t.status, t.created_at
            FROM tickets t JOIN users u ON t.user_id=u.id
            WHERE t.id=? AND t.user_id=?
        """, (ticket_id, user_id)).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id": row[0], "user_id": row[1], "username": row[2],
        "subject": row[3], "message": row[4], "status": row[5], "created_at": row[6]
    }


def create_ticket(user_id, subject, message):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("INSERT INTO tickets (user_id, subject, message, status) VALUES (?, ?, ?, 'open')",
              (user_id, subject, message))
    conn.commit()
    conn.close()


def get_replies(ticket_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    rows = c.execute(
        "SELECT id, author, role, message, created_at FROM ticket_replies WHERE ticket_id=? ORDER BY id ASC",
        (ticket_id,)
    ).fetchall()
    conn.close()
    return [{"id": r[0], "author": r[1], "role": r[2], "message": r[3], "created_at": r[4]} for r in rows]


def add_reply(ticket_id, author_id, author, role, message):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute(
        "INSERT INTO ticket_replies (ticket_id, author_id, author, role, message) VALUES (?, ?, ?, ?, ?)",
        (ticket_id, author_id, author, role, message)
    )
    # Reset read_by quand une réponse est envoyée (force re-lecture)
    c.execute("UPDATE tickets SET read_by='' WHERE id=?", (ticket_id,))
    conn.commit()
    conn.close()


def update_ticket_status(ticket_id, status):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("UPDATE tickets SET status=? WHERE id=?", (status, ticket_id))
    conn.commit()
    conn.close()


def mark_ticket_read(ticket_id, user_id, role):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    row = c.execute("SELECT read_by FROM tickets WHERE id=?", (ticket_id,)).fetchone()
    if row:
        read_by = row[0] or ""
        ids = [x for x in read_by.split(",") if x]
        uid_str = str(user_id)
        if uid_str not in ids:
            ids.append(uid_str)
        c.execute("UPDATE tickets SET read_by=? WHERE id=?", (",".join(ids), ticket_id))
        conn.commit()
    conn.close()


def delete_ticket(ticket_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("DELETE FROM ticket_replies WHERE ticket_id=?", (ticket_id,))
    c.execute("DELETE FROM tickets WHERE id=?", (ticket_id,))
    conn.commit()
    conn.close()


def get_unread_count(user_id, role):
    tickets = get_tickets(user_id, role)
    return sum(1 for t in tickets if t["unread"] > 0)


# ===== MAIN BOT =====
def main(user_id):
    ctx = get_ctx(user_id)
    ctx["SUCCESS_COUNT"] = 0
    ctx["FAIL_COUNT"] = 0

    total = count_contacts(user_id)
    if total == 0:
        print(f"❌ Pas de contacts pour user {user_id}")
        ctx["running"] = False
        return

    print(f"📋 {total} numéros chargés (user_id={user_id})")

    index = 0
    session_sent = 0

    while ctx["running"]:
        contacts_list = get_contacts(user_id)
        if not contacts_list:
            print(f"✅ Plus de contacts (user {user_id})")
            break

        if not ctx["running"]:
            print(f"⛔ Bot arrêté (user {user_id})")
            break

        while not ctx["pause_event"].is_set():
            time.sleep(1)

        devices = [d for d in get_devices(user_id) if d["active"]]
        if not devices:
            print(f"❌ Aucun device actif (user {user_id})")
            break

        device = devices[index % len(devices)]
        index += 1

        phone = contacts_list[0].get("phone", "").strip()
        if not phone:
            remove_phone_from_db(phone, user_id)
            continue

        if is_blacklisted(phone, user_id):
            print(f"🚫 {phone} blacklisté — ignoré")
            remove_phone_from_db(phone, user_id)
            continue

        message = get_random_message(user_id)

        try:
            success = False
            if device.get("type") == "textnow":
                success = send_textnow(phone, message, device["username"], device["sid_cookie"])
            else:
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
                success = r.status_code < 300

            if success:
                ctx["SUCCESS_COUNT"] += 1
                session_sent += 1
                update_device(device["name"], "success", device["success"] + 1, user_id)
                update_device(device["name"], "sent", device["sent"] + 1, user_id)
                add_history(phone, device["name"], "success", user_id)
                remove_phone_from_db(phone, user_id)
            else:
                ctx["FAIL_COUNT"] += 1
                update_device(device["name"], "fail", device["fail"] + 1, user_id)
                update_device(device["name"], "sent", device["sent"] + 1, user_id)
                add_history(phone, device["name"], "fail", user_id)

        except Exception as e:
            print(f"❌ ERREUR: {e}")
            ctx["FAIL_COUNT"] += 1
            add_history(phone, device["name"], "fail", user_id)

        current_devices = get_devices(user_id)
        for d in current_devices:
            if d["name"] == device["name"] and d["sent"] > 0 and d["sent"] % ctx["PAUSE_EVERY"] == 0:
                print(f"⏸️  Pause {ctx['PAUSE_TIME']}s après {ctx['PAUSE_EVERY']} SMS")
                time.sleep(ctx["PAUSE_TIME"])
                break

        if session_sent > 0 and session_sent % 50 == 0:
            extra = random.randint(120, 300)
            print(f"🛡️  Anti-ban: pause {extra}s après 50 SMS")
            time.sleep(extra)
        else:
            time.sleep(random.uniform(ctx["DELAY"], ctx["DELAY"] + 1.5))

    ctx["running"] = False
    print(f"✅ Campagne terminée (user {user_id}) — {ctx['SUCCESS_COUNT']} envoyés, {ctx['FAIL_COUNT']} erreurs")
