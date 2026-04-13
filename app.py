from flask import Flask, render_template, request, redirect, session, jsonify
import threading
import bot
import os
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "secret_multicompte_123")

bot.init_db()


# ===== HELPERS =====
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


def uid():
    return session.get("user_id")


def ctx():
    return bot.get_ctx(uid())


# ===== LOGIN =====
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = bot.get_user_by_credentials(
            request.form.get("username"),
            request.form.get("password")
        )
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
    return render_template("index.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# ===== ME =====
@app.route("/me")
@login_required
def me():
    return jsonify({
        "id": session.get("user_id"),
        "username": session.get("username"),
        "role": session.get("role")
    })


# ===== ADMIN =====
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
    user_id = request.get_json(force=True).get("id")
    if user_id == uid():
        return jsonify({"status": "error", "message": "Tu ne peux pas supprimer ton propre compte"})
    bot.delete_user(user_id)
    return jsonify({"status": "ok"})


@app.route("/admin/reset_password", methods=["POST"])
@admin_required
def admin_reset_password():
    d = request.get_json(force=True)
    bot.update_user_password(d.get("id"), d.get("password", ""))
    return jsonify({"status": "ok"})


@app.route("/change_password", methods=["POST"])
@login_required
def change_password():
    new_pass = request.get_json(force=True).get("password", "").strip()
    if not new_pass:
        return jsonify({"status": "error", "message": "Mot de passe vide"})
    bot.update_user_password(uid(), new_pass)
    return jsonify({"status": "ok"})


# ===== BOT =====
@app.route("/start", methods=["POST"])
@login_required
def start():
    c = ctx()
    if c["thread"] is None or not c["thread"].is_alive():
        c["running"] = True
        c["pause_event"].set()
        t = threading.Thread(target=bot.main, args=(uid(),))
        t.daemon = True
        t.start()
        c["thread"] = t
    return {"status": "started"}


@app.route("/pause", methods=["POST"])
@login_required
def pause():
    ctx()["pause_event"].clear()
    return {"status": "paused"}


@app.route("/resume", methods=["POST"])
@login_required
def resume():
    ctx()["pause_event"].set()
    return {"status": "resumed"}


@app.route("/stop", methods=["POST"])
@login_required
def stop():
    c = ctx()
    c["running"] = False
    c["pause_event"].set()
    return {"status": "stopped"}


# ===== STATS =====
@app.route("/stats")
@login_required
def stats():
    c = ctx()
    return {
        "success": c["SUCCESS_COUNT"],
        "fail": c["FAIL_COUNT"],
        "remaining": bot.csv_count(uid())
    }


# ===== DEVICES =====
@app.route("/devices")
@login_required
def devices():
    return {"devices": bot.get_devices(uid())}


@app.route("/add_device", methods=["POST"])
@login_required
def add_device():
    try:
        d = request.get_json(force=True)
        if not d.get("name"):
            return {"status": "error", "message": "Nom manquant"}
        device_type = d.get("type", "smsgate")
        if device_type == "textnow":
            if not d.get("username") or not d.get("sid_cookie"):
                return {"status": "error", "message": "Username et cookie SID requis pour TextNow"}
        else:
            if not d.get("device_id"):
                return {"status": "error", "message": "Device ID requis pour SMS Gate"}
        bot.add_device(
            d["name"],
            device_type,
            d.get("device_id", ""),
            d.get("username", ""),
            d.get("password", ""),
            d.get("sid_cookie", ""),
            uid()
        )
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.route("/delete_device", methods=["POST"])
@login_required
def delete_device():
    try:
        bot.delete_device(request.json["name"], uid())
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.route("/toggle_device", methods=["POST"])
@login_required
def toggle():
    try:
        name = request.json["name"]
        for d in bot.get_devices(uid()):
            if d["name"] == name:
                bot.update_device(name, "active", 0 if d["active"] else 1, uid())
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ===== MESSAGE =====
@app.route("/set_message", methods=["POST"])
@login_required
def set_message():
    ctx()["MESSAGE_TEXT"] = request.json.get("message", "")
    return {"status": "ok"}


# ===== TEMPLATES =====
@app.route("/templates")
@login_required
def get_templates():
    return {"data": bot.get_templates(uid())}


@app.route("/add_template", methods=["POST"])
@login_required
def add_template():
    content = request.json.get("content", "").strip()
    if not content:
        return {"status": "error", "message": "Contenu vide"}
    bot.add_template(content, uid())
    return {"status": "ok"}


@app.route("/delete_template", methods=["POST"])
@login_required
def delete_template():
    tid = request.json.get("id")
    if not tid:
        return {"status": "error", "message": "ID manquant"}
    bot.delete_template(tid, uid())
    return {"status": "ok"}


# ===== SETTINGS =====
@app.route("/set_settings", methods=["POST"])
@login_required
def settings():
    data = request.json
    c = ctx()
    c["DELAY"] = float(data.get("delay", 2))
    c["PAUSE_EVERY"] = int(data.get("pause_every", 10))
    c["PAUSE_TIME"] = int(data.get("pause_time", 30))
    return {"status": "ok"}


# ===== UPLOAD CSV =====
@app.route("/upload", methods=["POST"])
@login_required
def upload():
    try:
        file = request.files.get("file")
        if not file:
            return {"status": "error", "message": "Aucun fichier"}
        csv_content = file.read().decode("utf-8", errors="ignore")
        count = bot.import_contacts_from_csv(csv_content, uid())
        return {"status": "ok", "count": count}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.route("/delete_csv", methods=["POST"])
@login_required
def delete_csv():
    try:
        bot.delete_csv(uid())
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.route("/csv_status")
@login_required
def csv_status():
    return {
        "exists": bot.csv_exists(uid()),
        "count": bot.csv_count(uid())
    }


# ===== CONTACTS =====
@app.route("/contacts")
@login_required
def contacts():
    rows = bot.get_contacts(uid(), limit=200)
    count = bot.count_contacts(uid())
    return {"data": rows, "count": count}


@app.route("/delete_contact", methods=["POST"])
@login_required
def delete_contact():
    phone = request.json["phone"]
    try:
        bot.delete_single_contact(phone, uid())
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ===== BLACKLIST =====
@app.route("/blacklist")
@login_required
def get_blacklist():
    return {"data": bot.get_blacklist(uid())}


@app.route("/add_blacklist", methods=["POST"])
@login_required
def add_blacklist():
    phone = request.json.get("phone", "").strip()
    if not phone:
        return {"status": "error", "message": "Numéro vide"}
    bot.add_blacklist(phone, uid())
    return {"status": "ok"}


@app.route("/remove_blacklist", methods=["POST"])
@login_required
def remove_blacklist():
    phone = request.json.get("phone", "")
    bot.remove_blacklist(phone, uid())
    return {"status": "ok"}


# ===== HISTORIQUE =====
@app.route("/history")
@login_required
def history():
    filter_status = request.args.get("filter")
    data = bot.get_history(uid(), filter_status=filter_status, limit=100)
    return {"data": data}


# ===== TICKETS SUPPORT =====
@app.route("/tickets")
@login_required
def get_tickets():
    user_id = uid()
    role = session.get("role")
    tickets = bot.get_tickets(user_id, role)
    return jsonify({"tickets": tickets})


@app.route("/tickets/create", methods=["POST"])
@login_required
def create_ticket():
    d = request.get_json(force=True)
    subject = d.get("subject", "").strip()
    message = d.get("message", "").strip()
    if not subject or not message:
        return jsonify({"status": "error", "message": "Sujet et message requis"})
    bot.create_ticket(uid(), subject, message)
    return jsonify({"status": "ok"})


@app.route("/tickets/<int:ticket_id>/replies")
@login_required
def get_ticket_replies(ticket_id):
    user_id = uid()
    role = session.get("role")
    ticket = bot.get_ticket_by_id(ticket_id, user_id, role)
    if not ticket:
        return jsonify({"status": "error", "message": "Ticket introuvable"}), 404
    replies = bot.get_replies(ticket_id)
    # Marquer comme lu
    bot.mark_ticket_read(ticket_id, user_id, role)
    return jsonify({"ticket": ticket, "replies": replies})


@app.route("/tickets/<int:ticket_id>/reply", methods=["POST"])
@login_required
def reply_ticket(ticket_id):
    user_id = uid()
    role = session.get("role")
    ticket = bot.get_ticket_by_id(ticket_id, user_id, role)
    if not ticket:
        return jsonify({"status": "error", "message": "Ticket introuvable"}), 404
    message = request.get_json(force=True).get("message", "").strip()
    if not message:
        return jsonify({"status": "error", "message": "Message vide"})
    bot.add_reply(ticket_id, user_id, session.get("username"), role, message)
    # Changer statut: si admin répond → answered, si user répond → open
    new_status = "answered" if role == "admin" else "open"
    bot.update_ticket_status(ticket_id, new_status)
    return jsonify({"status": "ok"})


@app.route("/tickets/<int:ticket_id>/close", methods=["POST"])
@login_required
def close_ticket(ticket_id):
    if session.get("role") != "admin":
        return jsonify({"status": "error", "message": "Admin requis"}), 403
    bot.update_ticket_status(ticket_id, "closed")
    return jsonify({"status": "ok"})


@app.route("/tickets/<int:ticket_id>/delete", methods=["POST"])
@login_required
def delete_ticket(ticket_id):
    if session.get("role") != "admin":
        return jsonify({"status": "error", "message": "Admin requis"}), 403
    bot.delete_ticket(ticket_id)
    return jsonify({"status": "ok"})


@app.route("/tickets/unread_count")
@login_required
def unread_count():
    count = bot.get_unread_count(uid(), session.get("role"))
    return jsonify({"count": count})


# ===== RUN =====
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
