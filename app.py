from flask import Flask, render_template, jsonify, request, redirect, session
import threading
import bot
import os

app = Flask(__name__)
app.secret_key = "secret123"

bot.load_devices()
bot_thread = None
import os

USERNAME = os.environ.get("USERNAME", "papa")
PASSWORD = os.environ.get("PASSWORD", "2026Money$")
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

# ===== BOT CONTROL =====
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
    return {"success":bot.SUCCESS_COUNT,"fail":bot.FAIL_COUNT}

@app.route("/history")
def history():
    return {"data":bot.HISTORY[-50:]}

# ===== DEVICES =====
@app.route("/devices")
def devices():
    return {"devices":bot.DEVICES}

@app.route("/add_device", methods=["POST"])
def add_device():
    d=request.json
    bot.add_device(d["name"],d["device_id"],d["username"],d["password"])
    return {"status":"ok"}

@app.route("/delete_device", methods=["POST"])
def delete_device():
    name=request.json["name"]
    bot.DEVICES=[d for d in bot.DEVICES if d["name"]!=name]
    bot.save_devices()
    return {"status":"ok"}

@app.route("/toggle_device", methods=["POST"])
def toggle():
    name=request.json["name"]
    for d in bot.DEVICES:
        if d["name"]==name:
            d["active"]=not d["active"]
    bot.save_devices()
    return {"status":"ok"}

# ===== MESSAGE =====
@app.route("/set_message", methods=["POST"])
def set_message():
    bot.MESSAGE_TEXT = request.json["message"]
    return {"status":"ok"}

# ===== SETTINGS =====
@app.route("/set_settings", methods=["POST"])
def settings():
    data=request.json
    bot.DELAY=float(data["delay"])
    bot.PAUSE_EVERY=int(data["pause_every"])
    bot.PAUSE_TIME=int(data["pause_time"])
    return {"status":"ok"}

# ===== UPLOAD =====
@app.route("/upload", methods=["POST"])
def upload():
    file=request.files["file"]
    if file:
        os.makedirs("uploads", exist_ok=True)
        file.save("uploads/contacts.csv")
        return {"status":"ok"}
    return {"status":"fail"}

# ===== RENDER COMPATIBLE =====
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
