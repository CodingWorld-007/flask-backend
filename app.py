from flask import Flask, request, jsonify, abort
import requests
import os
import base64
from dotenv import load_dotenv

app = Flask(__name__)

# Load environment variables
load_dotenv()

GITHUB_USERNAME = os.getenv("GITHUB_USERNAME")
REPO_NAME = os.getenv("REPO_NAME")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
IPINFO_TOKEN = os.getenv("IPINFO_TOKEN")
BRANCH_NAME = os.getenv("BRANCH_NAME", "main")
RAILWAY_TOKEN = os.getenv("RAILWAY_TOKEN") # NEW
GITHUB_API_BASE = f"https://api.github.com/repos/{GITHUB_USERNAME}/{REPO_NAME}/contents"

# Error handling
class InvalidUsage(Exception):
    status_code = 400

    def __init__(self, message, status_code=None, payload=None):
        Exception.__init__(self)
        self.message = message
        if status_code is not None:
            self.status_code = status_code
        self.payload = payload

    def to_dict(self):
        rv = dict(self.payload or ())
        rv['message'] = self.message
        return rv


@app.errorhandler(InvalidUsage)
def handle_invalid_usage(error):
    response = jsonify(error.to_dict())
    response.status_code = error.status_code
    return response


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
    """Fetch attendance data from GitHub and return existing student rolls and sha."""
    file_path = f"attendance_{class_name}.csv"
    url = f"{GITHUB_API_BASE}/{file_path}?ref={BRANCH_NAME}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}

    try:
        response = requests.get(url, headers=headers, timeout=5)
        response.raise_for_status()

        if response.status_code == 404:
            return set(), None  # No file exists yet
        content = response.json()
        sha = content.get("sha")
        file_data = base64.b64decode(content["content"]).decode("utf-8")

        existing_rolls = set()
        lines = file_data.strip().split("\n")[1:]  # Skip header
        for line in lines:
            parts = line.split(", ")
            if len(parts) >= 9:
                existing_rolls.add(parts[1].strip())  # Student Roll

        return existing_rolls, sha
    except requests.RequestException as e:
        raise InvalidUsage(f"Error fetching data from GitHub: {e}", 500)


def update_attendance(class_name, student_name, student_roll, qr_code, ip, vpn_status, gps_status, lat, lng, time):
    """Update attendance while preventing duplicates."""
    existing_rolls, sha = get_existing_entries(class_name)

    if student_roll in existing_rolls:
        raise InvalidUsage("Duplicate entry detected", 409)

    file_path = f"attendance_{class_name}.csv"
    url = f"{GITHUB_API_BASE}/{file_path}"
    new_entry = f"{student_name}, {student_roll}, {class_name}, {qr_code}, {lat}, {lng}, {time}, {vpn_status}, {gps_status}, {ip}\n"

    # Fetch existing data correctly
    existing_data = "Student Name, Student Roll, Class Name, QR Code, Latitude, Longitude, Time, VPN Used, GPS Status, IP Address\n"

    try:
        response = requests.get(url, headers={"Authorization": f"token {GITHUB_TOKEN}"})
        if response.status_code == 404:
            print("File not found, creating new.")
            # File does not exist, so we skip the adding existing content.
        else:
            response.raise_for_status()
            content = response.json()
            existing_content = base64.b64decode(content["content"]).decode("utf-8")
            existing_data += existing_content

    except requests.RequestException as e:
        raise InvalidUsage(f"Error fetching or creating file on GitHub: {e}", 500)

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
        return True
    except requests.RequestException as e:
        raise InvalidUsage(f"GitHub API Error: {e}", 500)


def is_valid_location(lat, lng):
    """Check if the location is within a valid range."""
    min_lat, max_lat = 28.0, 29.0
    min_lng, max_lng = 77.0, 78.0
    try:
        return min_lat <= float(lat) <= max_lat and min_lng <= float(lng) <= max_lng
    except ValueError:
        raise InvalidUsage("Invalid latitude or longitude format.", 400)


def validate_token(auth_header):
    """Validates the API token from the Authorization header."""
    if not auth_header:
        raise InvalidUsage('Authorization header missing', 401)

    if not auth_header.startswith('Bearer '):
        raise InvalidUsage('Invalid authorization format', 401)

    token = auth_header.split(' ')[1]

    if token != RAILWAY_TOKEN:
        raise InvalidUsage('Invalid API token', 401)


@app.route("/submit_attendance", methods=["POST"])
def submit_attendance():
    """API endpoint to handle attendance submission."""
    # Validate API token
    auth_header = request.headers.get('Authorization')
    validate_token(auth_header)

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
        raise InvalidUsage("Missing required fields", 400)

    try:
        float_lat = float(lat)
        float_lng = float(lng)
    except ValueError:
        raise InvalidUsage("Invalid latitude or longitude format.", 400)

    if not is_valid_location(float_lat, float_lng):
        raise InvalidUsage("Invalid location", 403)

    vpn_status = is_vpn(ip)

    try:
        update_attendance(class_name, student_name, student_roll, qr_code, ip, vpn_status, gps_status, float_lat, float_lng, time)
        return jsonify({"status": "success", "message": "Attendance recorded"}), 200
    except InvalidUsage as e:
        raise e


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)