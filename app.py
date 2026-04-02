from flask import Flask, render_template, request, redirect, session, jsonify
import threading
import bot
import os
import csv
import sqlite3
import hashlib
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "ultra_secret_key_2026")

DB = "data.db"
bot.init_db()

bot_thread = None


# ═══════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════
def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()


def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_users_and_tickets():
    conn = get_db()
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

    c.execute("""
    CREATE TABLE IF NOT EXISTS tickets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        username TEXT NOT NULL,
        subject TEXT NOT NULL,
        message TEXT NOT NULL,
        status TEXT DEFAULT 'open',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS ticket_replies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticket_id INTEGER NOT NULL,
        author TEXT NOT NULL,
        role TEXT DEFAULT 'user',
        message TEXT NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS ticket_reads (
        ticket_id INTEGER,
        user_id INTEGER,
        last_read DATETIME DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(ticket_id, user_id)
    )
    """)

    # ✅ FIX ADMIN (IMPORTANT)
    admin = c.execute("SELECT * FROM users WHERE username='admin'").fetchone()

    if not admin:
        c.execute(
            "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
            ("admin", hash_pw("admin123"), "admin")
        )

    conn.commit()
    conn.close()


init_users_and_tickets()


def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    conn.close()
    return dict(user) if user else None


def require_login(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user_id"):
            return redirect("/?error=login_required")
        return f(*args, **kwargs)
    return decorated


def require_admin(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        u = current_user()
        if not u or u["role"] != "admin":
            return jsonify({"status": "error", "message": "Admin requis"}), 403
        return f(*args, **kwargs)
    return decorated


# ═══════════════════════════════════════════════
# AUTH
# ═══════════════════════════════════════════════
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        conn = get_db()
        user = conn.execute(
            "SELECT * FROM users WHERE username=?",
            (username,)
        ).fetchone()
        conn.close()

        # ✅ FIX LOGIN (hash + ancien password)
        if user:
            if user["password"] == hash_pw(password) or user["password"] == password:
                session["user_id"] = user["id"]
                session["username"] = user["username"]
                session["role"] = user["role"]
                return redirect("/dashboard")

        return redirect("/?error=1")

    return render_template("login.html")


@app.route("/dashboard")
@require_login
def dashboard():
    return render_template("index.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


@app.route("/me")
@require_login
def me():
    u = current_user()
    return jsonify({"username": u["username"], "role": u["role"], "id": u["id"]})


@app.route("/change_password", methods=["POST"])
@require_login
def change_password():
    pw = request.json.get("password", "").strip()
    if not pw:
        return jsonify({"status": "error", "message": "Mot de passe vide"})
    conn = get_db()
    conn.execute("UPDATE users SET password=? WHERE id=?", (hash_pw(pw), session["user_id"]))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})


# ═══════════════════════════════════════════════
# BOT (FIX START)
# ═══════════════════════════════════════════════
@app.route("/start", methods=["POST"])
@require_login
def start():
    global bot_thread
    if bot_thread is None or not bot_thread.is_alive():
        bot.running = True
        bot.pause_event.set()  # ✅ IMPORTANT
        bot_thread = threading.Thread(target=bot.main)
        bot_thread.daemon = True
        bot_thread.start()
    return jsonify({"status": "started"})


@app.route("/pause", methods=["POST"])
@require_login
def pause():
    bot.pause_event.clear()
    return jsonify({"status": "paused"})


@app.route("/resume", methods=["POST"])
@require_login
def resume():
    bot.pause_event.set()
    return jsonify({"status": "resumed"})


@app.route("/stop", methods=["POST"])
@require_login
def stop():
    bot.running = False
    bot.pause_event.set()
    return jsonify({"status": "stopped"})


# ═══════════════════════════════════════════════
# STATS
# ═══════════════════════════════════════════════
@app.route("/stats")
@require_login
def stats():
    return jsonify({
        "success": bot.SUCCESS_COUNT,
        "fail": bot.FAIL_COUNT,
        "remaining": bot.csv_count()
    })


@app.route("/history")
@require_login
def history():
    filter_status = request.args.get("filter")
    return jsonify({"data": bot.get_history(filter_status=filter_status, limit=100)})


# ═══════════════════════════════════════════════
# DEVICES
# ═══════════════════════════════════════════════
@app.route("/devices")
@require_login
def devices():
    return jsonify({"devices": bot.get_devices()})


@app.route("/add_device", methods=["POST"])
@require_login
def add_device():
    try:
        d = request.get_json(force=True)
        if not d.get("name") or not d.get("device_id"):
            return jsonify({"status": "error", "message": "Champs manquants"})
        bot.add_device(d["name"], d["device_id"], d.get("username", ""), d.get("password", ""))
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@app.route("/delete_device", methods=["POST"])
@require_login
def delete_device():
    bot.delete_device(request.json["name"])
    return jsonify({"status": "ok"})


@app.route("/toggle_device", methods=["POST"])
@require_login
def toggle():
    name = request.json["name"]
    for d in bot.get_devices():
        if d["name"] == name:
            bot.update_device(name, "active", 0 if d["active"] else 1)
    return jsonify({"status": "ok"})


# ═══════════════════════════════════════════════
# MESSAGE & SETTINGS
# ═══════════════════════════════════════════════
@app.route("/set_message", methods=["POST"])
@require_login
def set_message():
    bot.MESSAGE_TEXT = request.json.get("message", "")
    return jsonify({"status": "ok"})


@app.route("/set_settings", methods=["POST"])
@require_login
def settings():
    data = request.json
    bot.DELAY = float(data.get("delay", 2))
    bot.PAUSE_EVERY = int(data.get("pause_every", 10))
    bot.PAUSE_TIME = int(data.get("pause_time", 30))
    return jsonify({"status": "ok"})


# ═══════════════════════════════════════════════
# TEMPLATES
# ═══════════════════════════════════════════════
@app.route("/templates")
@require_login
def get_templates():
    conn = get_db()
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM templates ORDER BY id DESC"
    ).fetchall()]
    conn.close()
    return jsonify({"data": rows})


@app.route("/add_template", methods=["POST"])
@require_login
def add_template():
    content = request.json.get("content", "").strip()
    if not content:
        return jsonify({"status": "error", "message": "Contenu vide"})
    conn = get_db()
    conn.execute("INSERT INTO templates (content) VALUES (?)", (content,))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})


@app.route("/delete_template", methods=["POST"])
@require_login
def delete_template():
    tid = request.json.get("id")
    conn = get_db()
    conn.execute("DELETE FROM templates WHERE id=?", (tid,))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})


# ═══════════════════════════════════════════════
# CSV
# ═══════════════════════════════════════════════
@app.route("/upload", methods=["POST"])
@require_login
def upload():
    try:
        file = request.files.get("file")
        if not file:
            return jsonify({"status": "error", "message": "Aucun fichier"})
        os.makedirs("uploads", exist_ok=True)
        file.save(bot.CSV_PATH)
        return jsonify({"status": "ok", "count": bot.csv_count()})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@app.route("/delete_csv", methods=["POST"])
@require_login
def delete_csv():
    bot.delete_csv()
    return jsonify({"status": "ok"})


@app.route("/csv_status")
@require_login
def csv_status():
    return jsonify({"exists": bot.csv_exists(), "count": bot.csv_count()})


@app.route("/contacts")
@require_login
def contacts():
    path = bot.CSV_PATH
    if not os.path.exists(path):
        return jsonify({"data": [], "count": 0})
    try:
        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        return jsonify({"data": rows[:200], "count": len(rows)})
    except Exception:
        return jsonify({"data": [], "count": 0})


@app.route("/delete_contact", methods=["POST"])
@require_login
def delete_contact():
    phone = request.json["phone"]
    path = bot.CSV_PATH
    try:
        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        rows = [r for r in rows if r["phone"] != phone]
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["phone"])
            writer.writeheader()
            writer.writerows(rows)
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


# ═══════════════════════════════════════════════
# BLACKLIST
# ═══════════════════════════════════════════════
@app.route("/blacklist")
@require_login
def get_blacklist():
    return jsonify({"data": bot.get_blacklist()})


@app.route("/add_blacklist", methods=["POST"])
@require_login
def add_blacklist():
    phone = request.json.get("phone", "").strip()
    if not phone:
        return jsonify({"status": "error", "message": "Numéro vide"})
    bot.add_blacklist(phone)
    return jsonify({"status": "ok"})


@app.route("/remove_blacklist", methods=["POST"])
@require_login
def remove_blacklist():
    bot.remove_blacklist(request.json.get("phone", ""))
    return jsonify({"status": "ok"})


# ═══════════════════════════════════════════════
# RUN
# ═══════════════════════════════════════════════
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
