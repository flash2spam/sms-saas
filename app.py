from flask import Flask, render_template, request, redirect, session, jsonify
import threading
import bot
import os
import csv
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "secret_multicompte_123")

bot.init_db()

# Un thread de bot par utilisateur
bot_threads = {}


# ===== HELPERS SESSION =====
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user_id"):
            return redirect("/")
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user_id"):
            return redirect("/")
        if session.get("role") != "admin":
            return jsonify({"status": "error", "message": "Accès admin requis"}), 403
        return f(*args, **kwargs)
    return decorated


def current_user_id():
    return session.get("user_id")


# ===== LOGIN =====
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        user = bot.get_user_by_credentials(username, password)
        if user:
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            return redirect("/dashboard")
        return redirect("/?error=1")
    return render_template("login.html")


@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("index.html",
                           username=session.get("username"),
                           role=session.get("role"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# ===== ADMIN — GESTION UTILISATEURS =====
@app.route("/admin/users")
@admin_required
def admin_users():
    return jsonify({"users": bot.get_all_users()})


@app.route("/admin/create_user", methods=["POST"])
@admin_required
def admin_create_user():
    d = request.get_json(force=True)
    username = d.get("username", "").strip()
    password = d.get("password", "").strip()
    role = d.get("role", "user")
    if not username or not password:
        return jsonify({"status": "error", "message": "Champs manquants"})
    ok = bot.create_user(username, password, role)
    if ok:
        return jsonify({"status": "ok"})
    return jsonify({"status": "error", "message": "Nom d'utilisateur déjà pris"})


@app.route("/admin/delete_user", methods=["POST"])
@admin_required
def admin_delete_user():
    uid = request.get_json(force=True).get("id")
    if uid == current_user_id():
        return jsonify({"status": "error", "message": "Tu ne peux pas supprimer ton propre compte"})
    bot.delete_user(uid)
    return jsonify({"status": "ok"})


@app.route("/admin/reset_password", methods=["POST"])
@admin_required
def admin_reset_password():
    d = request.get_json(force=True)
    bot.update_user_password(d.get("id"), d.get("password", ""))
    return jsonify({"status": "ok"})


# Changer son propre mot de passe
@app.route("/change_password", methods=["POST"])
@login_required
def change_password():
    d = request.get_json(force=True)
    new_pass = d.get("password", "").strip()
    if not new_pass:
        return jsonify({"status": "error", "message": "Mot de passe vide"})
    bot.update_user_password(current_user_id(), new_pass)
    return jsonify({"status": "ok"})


# ===== ME =====
@app.route("/me")
@login_required
def me():
    return jsonify({
        "id": session.get("user_id"),
        "username": session.get("username"),
        "role": session.get("role")
    })


# ===== BOT =====
@app.route("/start", methods=["POST"])
@login_required
def start():
    uid = current_user_id()
    t = bot_threads.get(uid)
    if t is None or not t.is_alive():
        bot.running = True
        new_thread = threading.Thread(target=bot.main, args=(uid,))
        new_thread.daemon = True
        new_thread.start()
        bot_threads[uid] = new_thread
    return {"status": "started"}


@app.route("/pause", methods=["POST"])
@login_required
def pause():
    bot.pause_event.clear()
    return {"status": "paused"}


@app.route("/resume", methods=["POST"])
@login_required
def resume():
    bot.pause_event.set()
    return {"status": "resumed"}


@app.route("/stop", methods=["POST"])
@login_required
def stop():
    bot.running = False
    bot.pause_event.set()
    return {"status": "stopped"}


# ===== STATS =====
@app.route("/stats")
@login_required
def stats():
    uid = current_user_id()
    return {
        "success": bot.SUCCESS_COUNT,
        "fail": bot.FAIL_COUNT,
        "remaining": bot.csv_count(uid)
    }


# ===== DEVICES =====
@app.route("/devices")
@login_required
def devices():
    return {"devices": bot.get_devices(current_user_id())}


@app.route("/add_device", methods=["POST"])
@login_required
def add_device():
    try:
        d = request.get_json(force=True)
        if not d.get("name") or not d.get("device_id"):
            return {"status": "error", "message": "Champs manquants"}
        bot.add_device(d["name"], d["device_id"], d.get("username", ""), d.get("password", ""), current_user_id())
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.route("/delete_device", methods=["POST"])
@login_required
def delete_device():
    try:
        bot.delete_device(request.json["name"], current_user_id())
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.route("/toggle_device", methods=["POST"])
@login_required
def toggle():
    try:
        name = request.json["name"]
        uid = current_user_id()
        for d in bot.get_devices(uid):
            if d["name"] == name:
                bot.update_device(name, "active", 0 if d["active"] else 1, uid)
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ===== MESSAGE =====
@app.route("/set_message", methods=["POST"])
@login_required
def set_message():
    bot.MESSAGE_TEXT = request.json.get("message", "")
    return {"status": "ok"}


# ===== TEMPLATES =====
@app.route("/templates")
@login_required
def get_templates():
    return {"data": bot.get_templates(current_user_id())}


@app.route("/add_template", methods=["POST"])
@login_required
def add_template():
    content = request.json.get("content", "").strip()
    if not content:
        return {"status": "error", "message": "Contenu vide"}
    bot.add_template(content, current_user_id())
    return {"status": "ok"}


@app.route("/delete_template", methods=["POST"])
@login_required
def delete_template():
    tid = request.json.get("id")
    if not tid:
        return {"status": "error", "message": "ID manquant"}
    bot.delete_template(tid, current_user_id())
    return {"status": "ok"}


# ===== SETTINGS =====
@app.route("/set_settings", methods=["POST"])
@login_required
def settings():
    data = request.json
    bot.DELAY = float(data.get("delay", 2))
    bot.PAUSE_EVERY = int(data.get("pause_every", 10))
    bot.PAUSE_TIME = int(data.get("pause_time", 30))
    return {"status": "ok"}


# ===== UPLOAD CSV =====
@app.route("/upload", methods=["POST"])
@login_required
def upload():
    try:
        file = request.files.get("file")
        if not file:
            return {"status": "error", "message": "Aucun fichier"}
        os.makedirs("uploads", exist_ok=True)
        uid = current_user_id()
        path = bot.get_csv_path(uid)
        file.save(path)
        count = bot.csv_count(uid)
        print(f"✅ CSV uploadé — {count} contacts (user_id={uid})")
        return {"status": "ok", "count": count}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.route("/delete_csv", methods=["POST"])
@login_required
def delete_csv():
    try:
        bot.delete_csv(current_user_id())
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.route("/csv_status")
@login_required
def csv_status():
    uid = current_user_id()
    return {
        "exists": bot.csv_exists(uid),
        "count": bot.csv_count(uid)
    }


# ===== CONTACTS =====
@app.route("/contacts")
@login_required
def contacts():
    path = bot.get_csv_path(current_user_id())
    if not os.path.exists(path):
        return {"data": [], "count": 0}
    try:
        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        return {"data": rows[:200], "count": len(rows)}
    except Exception:
        return {"data": [], "count": 0}


@app.route("/delete_contact", methods=["POST"])
@login_required
def delete_contact():
    phone = request.json["phone"]
    path = bot.get_csv_path(current_user_id())
    try:
        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        rows = [r for r in rows if r["phone"] != phone]
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["phone"])
            writer.writeheader()
            writer.writerows(rows)
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ===== BLACKLIST =====
@app.route("/blacklist")
@login_required
def get_blacklist():
    return {"data": bot.get_blacklist(current_user_id())}


@app.route("/add_blacklist", methods=["POST"])
@login_required
def add_blacklist():
    phone = request.json.get("phone", "").strip()
    if not phone:
        return {"status": "error", "message": "Numéro vide"}
    bot.add_blacklist(phone, current_user_id())
    return {"status": "ok"}


@app.route("/remove_blacklist", methods=["POST"])
@login_required
def remove_blacklist():
    phone = request.json.get("phone", "")
    bot.remove_blacklist(phone, current_user_id())
    return {"status": "ok"}


# ===== HISTORIQUE =====
@app.route("/history")
@login_required
def history():
    filter_status = request.args.get("filter")
    data = bot.get_history(current_user_id(), filter_status=filter_status, limit=100)
    return {"data": data}


# ===== RUN =====
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
