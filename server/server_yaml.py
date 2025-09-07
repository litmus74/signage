import os
import yaml
from flask import Flask, jsonify, request, send_from_directory
from datetime import datetime

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CLIENTS_DIR = os.path.join(BASE_DIR, "clients")
STATIC_DIR = os.path.join(BASE_DIR, "static")

os.makedirs(CLIENTS_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)

def log_event(message):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {message}")

def load_client_config(display_id):
    filepath = os.path.join(CLIENTS_DIR, f"{display_id}.yaml")
    if not os.path.exists(filepath):
        log_event(f"⚠️ YAML file not found for display_id '{display_id}'")
        return None
    with open(filepath, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data

@app.route("/config/<display_id>")
def get_config(display_id):
    log_event(f"Received request from {display_id}")
    data = load_client_config(display_id)
    if not data:
        return jsonify({"error": "Display ID not found"}), 404

    # Add current timestamp overlay to each slide (optional)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for slide in data.get("slides", []):
        slide.setdefault("overlays", []).append({"text": now, "x": 1600, "y": 50})

    # Normalize logo and media paths to URLs
    host_url = f"http://{request.host}"
    if "logo" in data and data["logo"] and not data["logo"].startswith("http"):
        data["logo"] = f"{host_url}/{data['logo']}"
    if "background_image" in data and data["background_image"] and not data["background_image"].startswith("http"):
        data["background_image"] = f"{host_url}/{data['background_image']}"

    # Normalize slide media sources
    for slide in data.get("slides", []):
        for side in ["left", "right"]:
            conf = slide.get(side, {})
            if conf.get("type") in ["image", "video"]:
                src = conf.get("source")
                if src and not src.startswith("http"):
                    conf["source"] = f"{host_url}/{src}"

    return jsonify(data)

@app.route("/static/<path:filename>")
def serve_static(filename):
    return send_from_directory(STATIC_DIR, filename)

if __name__ == "__main__":
    log_event("Server starting on 0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)