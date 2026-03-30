from flask import Flask, render_template, request, redirect, session
import threading
import bot
import os

app = Flask(__name__)
app.secret_key = "secret123"

# 🔥 INIT DB
bot.init_db()

bot_thread = None

# 🔐 LOGIN (Render env)
USERNAME = os.environ.get("USERNAME", "admin")
PASSWORD = os.environ.get("PASSWORD", "1234")

# ===== LOGIN =====
@app.route("/", methods=["GET","POST"])
def login():
    if request.method == "POST":
        if request.form.get("username") == USERNAME and request.form.get("password") == PASSWORD:
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
        bot_thread.daemon = True  # 🔥 IMPORTANT (Render stabilité)
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

# ===== HISTORY =====
@app.route("/history")
def history():
    return {"data": []}

# ===== DEVICES =====
@app.route("/devices")
def devices():
    return {"devices": bot.get_devices()}

@app.route("/add_device", methods=["POST"])
def add_device():
    try:
        d = request.get_json(force=True)

        if not d.get("name") or not d.get("device_id"):
            return {"status":"error","message":"missing fields"}

        bot.add_device(
            d["name"],
            d["device_id"],
            d.get("username",""),
            d.get("password","")
        )

        return {"status":"ok"}

    except Exception as e:
        print("❌ ADD DEVICE ERROR:", e)
        return {"status":"error","message":str(e)}

@app.route("/delete_device", methods=["POST"])
def delete_device():
    try:
        name = request.json.get("name")
        bot.delete_device(name)
        return {"status":"ok"}
    except Exception as e:
        return {"status":"error","message":str(e)}

@app.route("/toggle_device", methods=["POST"])
def toggle():
    try:
        name = request.json.get("name")
        devices = bot.get_devices()

        for d in devices:
            if d["name"] == name:
                bot.update_device(name, "active", 0 if d["active"] else 1)

        return {"status":"ok"}
    except Exception as e:
        return {"status":"error","message":str(e)}

# ===== MESSAGE =====
@app.route("/set_message", methods=["POST"])
def set_message():
    bot.MESSAGE_TEXT = request.json.get("message", "")
    return {"status":"ok"}

# ===== SETTINGS =====
@app.route("/set_settings", methods=["POST"])
def settings():
    data = request.json

    bot.DELAY = float(data.get("delay", 2))
    bot.PAUSE_EVERY = int(data.get("pause_every", 10))
    bot.PAUSE_TIME = int(data.get("pause_time", 30))

    return {"status":"ok"}

# ===== UPLOAD =====
@app.route("/upload", methods=["POST"])
def upload():
    try:
        file = request.files.get("file")

        if file:
            os.makedirs("uploads", exist_ok=True)
            file.save("uploads/contacts.csv")
            return {"status":"ok"}

        return {"status":"fail"}

    except Exception as e:
        return {"status":"error","message":str(e)}

# ===== RUN =====
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
