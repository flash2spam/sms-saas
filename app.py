from flask import Flask, render_template, request, redirect, session
import threading
import bot
import os
import csv

app = Flask(__name__)
app.secret_key = "secret123"

bot.init_db()

bot_thread = None

USERNAME = os.environ.get("USERNAME", "admin")
PASSWORD = os.environ.get("PASSWORD", "1234")


# ===== LOGIN =====
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("username") == USERNAME and request.form.get("password") == PASSWORD:
            session["logged"] = True
            return redirect("/dashboard")
        return redirect("/?error=1")
    return render_template("login.html")


@app.route("/dashboard")
def dashboard():
    if not session.get("logged"):
        return redirect("/")
    return render_template("index.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# ===== BOT =====
@app.route("/start", methods=["POST"])
def start():
    global bot_thread
    if bot_thread is None or not bot_thread.is_alive():
        bot.running = True
        bot_thread = threading.Thread(target=bot.main)
        bot_thread.daemon = True
        bot_thread.start()
    return {"status": "started"}


@app.route("/pause", methods=["POST"])
def pause():
    bot.pause_event.clear()
    return {"status": "paused"}


@app.route("/resume", methods=["POST"])
def resume():
    bot.pause_event.set()
    return {"status": "resumed"}


@app.route("/stop", methods=["POST"])
def stop():
    bot.running = False
    bot.pause_event.set()  # débloquer si en pause
    return {"status": "stopped"}


# ===== STATS =====
@app.route("/stats")
def stats():
    return {
        "success": bot.SUCCESS_COUNT,
        "fail": bot.FAIL_COUNT,
        "remaining": bot.csv_count()
    }


# ===== DEVICES =====
@app.route("/devices")
def devices():
    return {"devices": bot.get_devices()}


@app.route("/add_device", methods=["POST"])
def add_device():
    try:
        d = request.get_json(force=True)
        if not d.get("name") or not d.get("device_id"):
            return {"status": "error", "message": "Champs manquants"}
        bot.add_device(d["name"], d["device_id"], d.get("username", ""), d.get("password", ""))
        return {"status": "ok"}
    except Exception as e:
        print("❌ ADD DEVICE:", e)
        return {"status": "error", "message": str(e)}


@app.route("/delete_device", methods=["POST"])
def delete_device():
    try:
        bot.delete_device(request.json["name"])
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.route("/toggle_device", methods=["POST"])
def toggle():
    try:
        name = request.json["name"]
        for d in bot.get_devices():
            if d["name"] == name:
                bot.update_device(name, "active", 0 if d["active"] else 1)
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ===== MESSAGE =====
@app.route("/set_message", methods=["POST"])
def set_message():
    bot.MESSAGE_TEXT = request.json.get("message", "")
    return {"status": "ok"}


# ===== SETTINGS =====
@app.route("/set_settings", methods=["POST"])
def settings():
    data = request.json
    bot.DELAY = float(data.get("delay", 2))
    bot.PAUSE_EVERY = int(data.get("pause_every", 10))
    bot.PAUSE_TIME = int(data.get("pause_time", 30))
    return {"status": "ok"}


# ===== UPLOAD CSV =====
@app.route("/upload", methods=["POST"])
def upload():
    try:
        file = request.files.get("file")
        if not file:
            return {"status": "error", "message": "Aucun fichier"}
        os.makedirs("uploads", exist_ok=True)
        file.save(bot.CSV_PATH)
        count = bot.csv_count()
        print(f"✅ CSV uploadé — {count} contacts")
        return {"status": "ok", "count": count}
    except Exception as e:
        print("❌ UPLOAD ERROR:", e)
        return {"status": "error", "message": str(e)}


# ===== SUPPRIMER LE CSV =====
@app.route("/delete_csv", methods=["POST"])
def delete_csv():
    try:
        bot.delete_csv()
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ===== STATUT CSV =====
@app.route("/csv_status")
def csv_status():
    return {
        "exists": bot.csv_exists(),
        "count": bot.csv_count()
    }


# ===== CONTACTS =====
@app.route("/contacts")
def contacts():
    path = bot.CSV_PATH
    if not os.path.exists(path):
        return {"data": [], "count": 0}
    try:
        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        return {"data": rows[:200], "count": len(rows)}
    except Exception:
        return {"data": [], "count": 0}


@app.route("/delete_contact", methods=["POST"])
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
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ===== BLACKLIST =====
@app.route("/blacklist")
def get_blacklist():
    return {"data": bot.get_blacklist()}


@app.route("/add_blacklist", methods=["POST"])
def add_blacklist():
    phone = request.json.get("phone", "").strip()
    if not phone:
        return {"status": "error", "message": "Numéro vide"}
    bot.add_blacklist(phone)
    return {"status": "ok"}


@app.route("/remove_blacklist", methods=["POST"])
def remove_blacklist():
    phone = request.json.get("phone", "")
    bot.remove_blacklist(phone)
    return {"status": "ok"}


# ===== HISTORIQUE =====
@app.route("/history")
def history():
    filter_status = request.args.get("filter")
    data = bot.get_history(filter_status=filter_status, limit=100)
    return {"data": data}


# ===== RUN =====
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
