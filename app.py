from flask import Flask, render_template, request, redirect, session, jsonify
import sqlite3
import hashlib
import os

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "ultra_secret_key_2026")

# =========================
# UTILS
# =========================
def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def get_db():
    conn = sqlite3.connect("data.db")
    conn.row_factory = sqlite3.Row
    return conn

# =========================
# INIT DB
# =========================
def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT,
        role TEXT
    )
    """)

    # assure admin toujours présent
    admin = c.execute("SELECT * FROM users WHERE username='admin'").fetchone()

    if not admin:
        c.execute(
            "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
            ("admin", hash_pw("admin123"), "admin")
        )

    conn.commit()
    conn.close()

init_db()

# =========================
# LOGIN
# =========================
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        conn = get_db()
        user = conn.execute(
            "SELECT * FROM users WHERE username=?",
            (username,)
        ).fetchone()

        if user:
            if user["password"] == hash_pw(password) or user["password"] == password:
                session["user_id"] = user["id"]
                session["username"] = user["username"]
                session["role"] = user["role"]
                return redirect("/dashboard")

        return redirect("/?error=1")

    return render_template("login.html")

# =========================
# LOGOUT
# =========================
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# =========================
# AUTH DECORATOR
# =========================
def login_required(f):
    from functools import wraps

    @wraps(f)
    def wrap(*args, **kwargs):
        if "user_id" not in session:
            return redirect("/?error=login_required")
        return f(*args, **kwargs)
    return wrap

# =========================
# DASHBOARD
# =========================
@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("index.html")

# =========================
# BOT CONTROL
# =========================
@app.route("/start", methods=["POST"])
def start():
    from bot import start_bot
    start_bot()
    return jsonify({"status": "started"})

@app.route("/pause", methods=["POST"])
def pause():
    from bot import pause_bot
    pause_bot()
    return jsonify({"status": "paused"})

@app.route("/resume", methods=["POST"])
def resume():
    from bot import resume_bot
    resume_bot()
    return jsonify({"status": "resumed"})

@app.route("/stop", methods=["POST"])
def stop():
    from bot import stop_bot
    stop_bot()
    return jsonify({"status": "stopped"})

@app.route("/status")
def status():
    from bot import is_running, is_paused
    return jsonify({
        "running": is_running,
        "paused": is_paused
    })

# =========================
# RUN
# =========================
if __name__ == "__main__":
    app.run(debug=True)
