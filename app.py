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

GITHUB_API_BASE = f"https://api.github.com/repos/{GITHUB_USERNAME}/{REPO_NAME}/"

def is_vpn(ip):
    """Check if the given IP is associated with a VPN."""
    # This is a placeholder function. Replace with an actual VPN detection API.
    return "Yes" if "vpn" in ip else "No"

def get_existing_entries(class_name):
    """Fetch existing Student IDs and IPs from the attendance file."""
    file_path = f"attendance_{class_name}.csv"
    url = f"{GITHUB_API_BASE}/{file_path}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    
    existing_ids = set()
    existing_ips = set()
    defaulters = {}
    sha = None
    
    try:
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            content = response.json()
            sha = content.get("sha")
            file_data = base64.b64decode(content["content"]).decode("utf-8").strip()
            lines = file_data.split("\n")[1:]  # Skip header
            
            for line in lines:
                parts = line.split(", ")
                if len(parts) >= 5:
                    existing_ids.add(parts[0])
                    existing_ips.add(parts[4])
    except requests.RequestException:
        pass
    
    return existing_ids, existing_ips, sha, defaulters

def update_attendance(class_name, student_id, student_name, ip, vpn_status, gps_status):
    """Update attendance, ensuring no duplicate Student ID or IP."""
    existing_ids, existing_ips, sha, defaulters = get_existing_entries(class_name)
    
    # Prevent duplicate entries
    if student_id in existing_ids or ip in existing_ips:
        defaulter_file = f"defaulter_{class_name}.csv"
        defaulter_url = f"{GITHUB_API_BASE}/{defaulter_file}"
        
        # Add to defaulter list
        new_defaulter = f"{student_id}, {student_name}, {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}, {vpn_status}, {ip}\n"
        
        existing_defaulters = "Student ID, Name, Date, Time, VPN Used, IP Address\n"
        sha_defaulter = None
        
        try:
            response = requests.get(defaulter_url, headers={"Authorization": f"token {GITHUB_TOKEN}"}, timeout=5)
            if response.status_code == 200:
                content = response.json()
                sha_defaulter = content.get("sha")
                file_data = base64.b64decode(content["content"]).decode("utf-8").strip()
                existing_defaulters += "\n".join(file_data.split("\n")[1:]) + "\n"
        except requests.RequestException:
            pass  # If file not found, create new
        
        updated_defaulter_data = existing_defaulters + new_defaulter
        encoded_defaulter_data = base64.b64encode(updated_defaulter_data.encode("utf-8")).decode("utf-8")
        
        payload = {"message": f"Updated defaulter list for {class_name}", "content": encoded_defaulter_data, "branch": "main"}
        if sha_defaulter:
            payload["sha"] = sha_defaulter
        
        try:
            requests.put(defaulter_url, headers={"Authorization": f"token {GITHUB_TOKEN}"}, json=payload, timeout=10)
        except requests.RequestException:
            pass  # Ignore if update fails
        
        return False, defaulters
    
    # Proceed with normal attendance entry
    file_path = f"attendance_{class_name}.csv"
    url = f"{GITHUB_API_BASE}/{file_path}"
    current_time = datetime.datetime.now().strftime("%Y-%m-%d, %H:%M:%S")
    new_entry = f"{student_id}, {student_name}, {current_time}, {vpn_status}, {ip}\n"
    
    existing_data = "Student ID, Name, Date, Time, VPN Used, IP Address\n"
    try:
        response = requests.get(url, headers={"Authorization": f"token {GITHUB_TOKEN}"}, timeout=5)
        if response.status_code == 200:
            content = response.json()
            file_data = base64.b64decode(content["content"]).decode("utf-8")
            existing_data += "\n".join(file_data.strip().split("\n")[1:]) + "\n"
    except requests.RequestException:
        pass  # If file not found, start fresh
    
    updated_data = existing_data + new_entry
    encoded_data = base64.b64encode(updated_data.encode("utf-8")).decode("utf-8")
    
    payload = {"message": f"Updated attendance for {class_name}", "content": encoded_data, "branch": "main"}
    if sha:
        payload["sha"] = sha
    
    try:
        response = requests.put(url, headers={"Authorization": f"token {GITHUB_TOKEN}"}, json=payload, timeout=10)
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

if __name__ == "__main__":
    app.run(debug=True)
