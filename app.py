from flask import Flask, request, jsonify
import requests
import base64
import os
import datetime
from dotenv import load_dotenv

app = Flask(__name__)

# Load environment variables
load_dotenv()

GITHUB_USERNAME = os.getenv("GITHUB_USERNAME")
REPO_NAME = os.getenv("REPO_NAME")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
IPINFO_TOKEN = os.getenv("IPINFO_TOKEN")

GITHUB_API_BASE = f"https://api.github.com/repos/{GITHUB_USERNAME}/{REPO_NAME}/contents"

def is_vpn(ip):
    """Detect if a VPN or Proxy is being used."""
    try:
        response = requests.get(f"https://ipinfo.io/{ip}?token={IPINFO_TOKEN}", timeout=5)
        response.raise_for_status()
        data = response.json()
        return "Yes" if data.get("privacy", {}).get("vpn") or data.get("privacy", {}).get("proxy") else "No"
    except requests.RequestException:
        return "Unknown"

def get_existing_entries(class_name):
    """Fetch attendance data and return existing student IDs and IPs."""
    file_path = f"attendance_{class_name}.csv"
    url = f"{GITHUB_API_BASE}/{file_path}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    
    try:
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 404:
            return set(), set(), None, {}
        
        response.raise_for_status()
        content = response.json()
        sha = content.get("sha")
        file_data = base64.b64decode(content["content"]).decode("utf-8")
        
        existing_ids, existing_ips = set(), set()
        defaulters = {}
        
        lines = file_data.strip().split("\n")[1:]
        for line in lines:
            parts = line.split(", ")
            if len(parts) >= 5:
                sid, ip = parts[0].strip(), parts[4].strip()
                existing_ids.add(sid)
                existing_ips.add(ip)
                if sid in defaulters:
                    defaulters[sid] += 1
                else:
                    defaulters[sid] = 1
        
        return existing_ids, existing_ips, sha, defaulters
    except requests.RequestException:
        return set(), set(), None, {}

def update_attendance(class_name, student_id, student_name, ip, vpn_status, gps_status):
    """Update attendance, ensuring no duplicate Student ID or IP."""
    existing_ids, existing_ips, sha, defaulters = get_existing_entries(class_name)
    
    # 🚨 Block duplicate student IDs or IPs
    if student_id in existing_ids or ip in existing_ips:
        if student_id in defaulters:
            defaulters[student_id] += 1
        else:
            defaulters[student_id] = 1
        print(f"❌ Duplicate Entry Detected: Student ID {student_id} or IP {ip}.")
        return False, defaulters
    
    file_path = f"attendance_{class_name}.csv"
    url = f"{GITHUB_API_BASE}/{file_path}"
    current_time = datetime.datetime.now().strftime("%Y-%m-%d, %H:%M:%S")
    new_entry = f"{student_id}, {student_name}, {current_time}, {vpn_status}, {ip}\n"
    
    # 🚀 Fetch existing data properly
    existing_data = "Student ID, Name, Date, Time, VPN Used, IP Address\n"
    try:
        response = requests.get(url, headers={"Authorization": f"token {GITHUB_TOKEN}"}, timeout=5)
        if response.status_code == 200:
            content = response.json()
            file_data = base64.b64decode(content["content"]).decode("utf-8")
            existing_data += "\n".join(file_data.strip().split("\n")[1:]) + "\n"  # Append existing records
    except requests.RequestException:
        pass  # If file not found, start fresh

    updated_data = existing_data + new_entry  # Properly merge old and new entries
    encoded_data = base64.b64encode(updated_data.encode("utf-8")).decode("utf-8")

    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    payload = {"message": f"Updated attendance for {class_name}", "content": encoded_data, "branch": "main"}
    if sha:
        payload["sha"] = sha  # Ensure correct file updates

    try:
        response = requests.put(url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        return response.status_code in [200, 201], defaulters
    except requests.RequestException:
        return False, defaulters


@app.route("/submit_attendance", methods=["POST"])
def submit_attendance():
    """API endpoint to handle attendance submission."""
    data = request.json
    student_id = data.get("student_id")
    student_name = data.get("student_name")
    class_name = data.get("class_name")
    ip = request.remote_addr
    gps_status = data.get("gps_status", "No")

    if not student_id or not student_name or not class_name:
        return jsonify({"status": "error", "message": "Missing required fields"}), 400

    if gps_status == "No":
        return jsonify({"status": "error", "message": "GPS is required"}), 403

    vpn_status = is_vpn(ip)
    success, defaulters = update_attendance(class_name, student_id, student_name, ip, vpn_status, gps_status)

    if success:
        return jsonify({"status": "success", "message": "Attendance recorded"})
    else:
        return jsonify({"status": "error", "message": "Duplicate entry detected", "defaulters": defaulters}), 409

