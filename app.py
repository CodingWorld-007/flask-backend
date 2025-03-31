from flask import Flask, request, jsonify, abort
import requests
import os
import base64
import datetime
from dotenv import load_dotenv

app = Flask(__name__)

# Load environment variables
load_dotenv()

GITHUB_USERNAME = os.getenv("GITHUB_USERNAME")
REPO_NAME = os.getenv("REPO_NAME")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
IPINFO_TOKEN = os.getenv("IPINFO_TOKEN")
BRANCH_NAME = os.getenv("BRANCH_NAME", "main")

GITHUB_API_BASE = f"https://api.github.com/repos/{GITHUB_USERNAME}/{REPO_NAME}/contents"

def is_vpn(ip):
    """Detect VPN or Proxy usage via IPInfo API."""
    if not IPINFO_TOKEN:
        return "Unknown"  # If the token is missing, we can't check

    try:
        response = requests.get(f"https://ipinfo.io/{ip}?token={IPINFO_TOKEN}", timeout=5)
        response.raise_for_status()
        data = response.json()

        if data.get("bogon") or data.get("privacy", {}).get("vpn") or data.get("privacy", {}).get("proxy"):
            return "Yes"
        return "No"
    except requests.RequestException:
        return "Unknown"

def get_existing_entries(class_name):
    """Fetch attendance data from GitHub and return existing student IDs and IPs."""
    file_path = f"attendance_{class_name}.csv"
    url = f"{GITHUB_API_BASE}/{file_path}?ref={BRANCH_NAME}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}

    try:
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 404:
            return set(), None  # No file exists yet

        response.raise_for_status()
        content = response.json()
        sha = content.get("sha")  # Required for updating the file
        file_data = base64.b64decode(content["content"]).decode("utf-8")

        existing_ids = set()
        lines = file_data.strip().split("\n")[1:]  # Skip header
        for line in lines:
            parts = line.split(", ")
            if len(parts) >= 9:
                existing_ids.add(parts[1].strip())  # Student Roll

        return existing_ids, sha
    except requests.RequestException:
        return set(), None


def update_attendance(class_name, student_name, student_roll, qr_code, ip, vpn_status, gps_status, lat, lng, time):
    """Update attendance while preventing duplicates."""
    existing_rolls, sha = get_existing_entries(class_name)

    if student_roll in existing_rolls:
        print(f"❌ Duplicate Entry Detected: Student Roll {student_roll}.")
        return False

    file_path = f"attendance_{class_name}.csv"
    url = f"{GITHUB_API_BASE}/{file_path}"

    new_entry = f"{student_name}, {student_roll}, {class_name}, {qr_code}, {lat}, {lng}, {time}, {vpn_status}, {gps_status}, {ip}\n"

    # Fetch existing data correctly
    existing_data = "Student Name, Student Roll, Class Name, QR Code, Latitude, Longitude, Time, VPN Used, GPS Status, IP Address\n"

    try:
        response = requests.get(url, headers={"Authorization": f"token {GITHUB_TOKEN}"})
        response.raise_for_status()  # Raise an exception for bad status codes

        content = response.json()
        existing_content = base64.b64decode(content["content"]).decode("utf-8")

        existing_data += existing_content

    except requests.exceptions.HTTPError as http_err:
        if http_err.response.status_code == 404:
            print(f"File not found, creating new. {http_err}")
            # File does not exist, so we skip the adding existing content.
        else:
            print(f"HTTP error occurred: {http_err}")
            return False
    except requests.exceptions.RequestException as err:
        print(f"An error occurred: {err}")
        return False
    except KeyError as key_err:
        print(f"A key error occurred: {key_err}")
        return False
    except Exception as err:
        print(f"An unexpected error occurred: {err}")
        return False

    existing_data += new_entry  # Add new entry at the bottom

    encoded_data = base64.b64encode(existing_data.encode("utf-8")).decode("utf-8")

    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    payload = {
        "message": f"Updated attendance for {class_name}",
        "content": encoded_data,
        "branch": BRANCH_NAME
    }
    if sha:
        payload["sha"] = sha  # Needed if file exists

    try:
        response = requests.put(url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        return response.status_code in [200, 201]
    except requests.exceptions.RequestException as e:
        print(f"GitHub API Error: {e}")
        return False

def is_valid_location(lat, lng):
    """Check if the location is within a valid range."""
    # Example: Check if within a certain latitude and longitude range
    min_lat, max_lat = 28.0, 29.0
    min_lng, max_lng = 77.0, 78.0
    print(f"Checking location: lat={lat}, lng={lng}")
    print(f"Checking type location: lat={type(lat)}, lng={type(lng)}")
    try:
        return min_lat <= float(lat) <= max_lat and min_lng <= float(lng) <= max_lng
    except ValueError:
        print("Error: Invalid latitude or longitude format.")
        return False  # Or handle it in a way appropriate for your app

@app.route("/submit_attendance", methods=["POST"])
def submit_attendance():
    """API endpoint to handle attendance submission."""
    data = request.json
    student_name = data.get("student_name")
    student_roll = data.get("student_roll")
    class_name = data.get("class_name")
    qr_code = data.get("qr_code")
    lat = data.get("lat")
    lng = data.get("lng")
    time = data.get("time")
    ip = request.remote_addr
    gps_status = data.get("gps_status")

    if not student_name or not student_roll or not class_name or not qr_code or not lat or not lng or not time:
        return jsonify({"status": "error", "message": "Missing required fields"}), 400
    
    try:
        float_lat = float(lat)
        float_lng = float(lng)
        if not is_valid_location(float_lat, float_lng):
            return jsonify({"status": "error", "message": "Invalid location"}), 403
        
        vpn_status = is_vpn(ip)
        if update_attendance(class_name, student_name, student_roll, qr_code, ip, vpn_status, gps_status, float_lat, float_lng, time):
            return jsonify({"status": "success", "message": "Attendance recorded"}), 200
        else:
            return jsonify({"status": "error", "message": "Duplicate entry detected"}), 409
    except ValueError:
        return jsonify({"status": "error", "message": "Invalid latitude or longitude format."}), 400


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)