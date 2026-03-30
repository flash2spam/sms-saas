from flask import Flask, render_template, jsonify, request, redirect, session
import threading
import bot
import os

app = Flask(__name__)
app.secret_key = "secret123"

# 🔥 INIT DB (IMPORTANT)
bot.init_db()

bot_thread = None

# 🔐 LOGIN (Render env)
USERNAME = os.environ.get("USERNAME", "admin")
PASSWORD = os.environ.get("PASSWORD", "1234")

# ===== LOGIN =====
@app.route("/", methods=["GET","POST"])
def login():
    if request.method == "POST":
        if request.form["username"] == USERNAME and request.form["password"] == PASSWORD:
            session["logged"] = True
            return redirect("/dashboard")
        return "❌ login incorrect"
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
        bot_thread.start()
    return {"status":"started"}

@app.route("/pause", methods=["POST"])
def pause():
    bot.pause_event.clear()
    return {"status":"paused"}

@app.route("/resume", methods=["POST"])
def resume():
    bot.pause_event.set()
    return {"status":"resumed"}

# ===== STATS =====
@app.route("/stats")
def stats():
    return {
        "success": bot.SUCCESS_COUNT,
        "fail": bot.FAIL_COUNT
    }

# ===== HISTORY (simple) =====
@app.route("/history")
def history():
    return {"data": []}  # tu peux améliorer après

# ===== DEVICES (SQLITE) =====
@app.route("/devices")
def devices():
    return {"devices": bot.get_devices()}

@app.route("/add_device", methods=["POST"])
def add_device():
    try:
        d = request.get_json(force=True)

        bot.add_device(
            d["name"],
            d["device_id"],
            d["username"],
            d["password"]
        )

        return {"status":"ok"}

    except Exception as e:
        print("❌ ADD DEVICE ERROR:", e)
        return {"status":"error","message":str(e)}

@app.route("/delete_device", methods=["POST"])
def delete_device():
    bot.delete_device(request.json["name"])
    return {"status":"ok"}

@app.route("/toggle_device", methods=["POST"])
def toggle():
    name = request.json["name"]
    devices = bot.get_devices()

    for d in devices:
        if d["name"] == name:
            bot.update_device(name, "active", 0 if d["active"] else 1)

    return {"status":"ok"}

# ===== MESSAGE =====
@app.route("/set_message", methods=["POST"])
def set_message():
    bot.MESSAGE_TEXT = request.json["message"]
    return {"status":"ok"}

# ===== SETTINGS =====
@app.route("/set_settings", methods=["POST"])
def settings():
    data = request.json
    bot.DELAY = float(data["delay"])
    bot.PAUSE_EVERY = int(data["pause_every"])
    bot.PAUSE_TIME = int(data["pause_time"])
    return {"status":"ok"}

# ===== UPLOAD =====
@app.route("/upload", methods=["POST"])
def upload():
    file = request.files["file"]

    if file:
        os.makedirs("uploads", exist_ok=True)
        file.save("uploads/contacts.csv")
        return {"status":"ok"}

    return {"status":"fail"}

# ===== RUN (Render compatible) =====
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
