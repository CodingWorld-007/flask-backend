from flask import Flask, request, jsonify, abort
import requests
import os
import base64
import logging
import math
from dotenv import load_dotenv
import datetime

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.DEBUG)

# Load environment variables
load_dotenv()

GITHUB_USERNAME = os.getenv("GITHUB_USERNAME")
REPO_NAME = os.getenv("REPO_NAME")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
RAILWAY_TOKEN = os.getenv("RAILWAY_TOKEN")
FIREBASE_SECRET = os.getenv("FIREBASE_SECRET")
FIREBASE_URL = os.getenv("FIREBASE_URL")
GITHUB_API_BASE = f"https://api.github.com/repos/{GITHUB_USERNAME}/{REPO_NAME}/contents"

# Constants
DISTANCE_THRESHOLD = 250
CSV_HEADER = "Student Name, Student Roll, Class Name, QR Code, Latitude, Longitude, Time, GPS Status, Device ID, Duplicate\n"  # Added Duplicate flag

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
        rv['status'] = "error"
        return rv

@app.errorhandler(InvalidUsage)
def handle_invalid_usage(error):
    response = jsonify(error.to_dict())
    response.status_code = error.status_code
    return response

def create_new_file(class_name, new_entry):
    """Create a new attendance CSV file on GitHub."""
    file_path = f"attendance_{class_name}.csv"
    url = f"{GITHUB_API_BASE}/{file_path}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    data = CSV_HEADER + new_entry
    encoded_data = base64.b64encode(data.encode("utf-8")).decode("utf-8")

    payload = {
        "message": f"Created attendance file for {class_name}",
        "content": encoded_data,
        "branch": "main"
    }

    try:
        response = requests.put(url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        logging.info(f"Created new file for class {class_name} on GitHub.")
        return True
    except requests.RequestException as e:
        logging.error(f"Error creating file on GitHub: {e}")
        raise InvalidUsage(f"Error creating file on GitHub: {e}", 500)

def get_existing_entries(class_name):
    """Fetch attendance data from GitHub and return existing entries and sha."""
    file_path = f"attendance_{class_name}.csv"
    url = f"{GITHUB_API_BASE}/{file_path}?ref=main"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}

    try:
        response = requests.get(url, headers=headers, timeout=5)
        logging.debug(f"get_existing_entries(): Response from GitHub: {response.status_code}")
        if response.status_code == 404:
            logging.info(f"File for class {class_name} not found on GitHub.")
            return None, []

        response.raise_for_status()
        content = response.json()
        sha = content.get("sha")
        file_data = base64.b64decode(content["content"]).decode("utf-8")

        existing_entries = []
        lines = file_data.strip().split("\n")[1:]  # Skip header
        for line in lines:
            existing_entries.append(line)

        return sha, existing_entries
    except requests.RequestException as e:
        logging.error(f"Error fetching data from GitHub: {e}")
        raise InvalidUsage(f"Error fetching data from GitHub: {e}", 500)
    
def update_attendance(class_name, student_name, student_roll, qr_code, gps_status, lat, lng, time, device_id):
    """
    Update attendance and handle duplicate entries.
    """
    sha, existing_entries = get_existing_entries(class_name)
    new_entry = f"{student_name}, {student_roll}, {class_name}, {qr_code}, {lat}, {lng}, {time}, {gps_status}, {device_id}, No\n"  # Default: Not a duplicate

    if sha is None:
        create_new_file(class_name, new_entry)
        return True

    is_duplicate = False
    today_date = datetime.datetime.now().strftime("%Y-%m-%d")  # Get today's date
    for entry in existing_entries:
        parts = entry.split(", ")
        if len(parts) >= 10:  # Ensure the entry has enough parts
            entry_student_name = parts[0]
            entry_student_roll = parts[1]
            entry_time_str = parts[6]  # time
            try:
                entry_time = datetime.datetime.strptime(entry_time_str, "%H:%M:%S")
                entry_date = entry_time.strftime("%Y-%m-%d")
                if entry_date == today_date and entry_student_name == student_name and entry_student_roll == student_roll:
                    is_duplicate = True
                    break
            except ValueError:
                logging.error(f"Invalid time format in entry: {entry}")
                continue

    if is_duplicate:
        logging.warning(f"Duplicate entry detected for {student_name} - {student_roll}")
        new_entry = f"{student_name}, {student_roll}, {class_name}, {qr_code}, {lat}, {lng}, {time}, {gps_status}, {device_id}, Yes\n"  # Mark as duplicate

    file_path = f"attendance_{class_name}.csv"
    url = f"{GITHUB_API_BASE}/{file_path}"

    existing_data = CSV_HEADER
    for entry in existing_entries:
        existing_data += entry + "\n"
    existing_data += new_entry

    encoded_data = base64.b64encode(existing_data.encode("utf-8")).decode("utf-8")
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    payload = {
        "message": f"Updated attendance for {class_name}",
        "content": encoded_data,
        "branch": "main"
    }
    if sha:
        payload["sha"] = sha

    try:
        response = requests.put(url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        return True
    except requests.RequestException as e:
        logging.error(f"GitHub API Error: {e}")
        raise InvalidUsage(f"GitHub API Error: {e}", 500)


def calculate_distance(lat1, lon1, lat2, lon2):
    """Calculate the distance between two points using the Haversine formula."""
    R = 6371  # Radius of the Earth in kilometers
    dLat = math.radians(lat2 - lat1)
    dLon = math.radians(lon2 - lon1)
    lat1 = math.radians(lat1)
    lat2 = math.radians(lat2)
    a = math.sin(dLat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dLon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    distance = R * c * 1000  # Convert to meters
    return distance


def get_teacher_location(class_name):
    """Fetch the teacher's location from Firebase."""
    logging.debug(f"get_teacher_location(): Fetching teacher location for class '{class_name}'")
    try:
        url = f"{FIREBASE_URL}/locations/{class_name}.json?auth={FIREBASE_SECRET}"
        logging.debug(f"get_teacher_location(): Firebase URL: {url}")
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        logging.debug(f"get_teacher_location(): Data received from Firebase: {data}")

        if data:
            return data.get("lat"), data.get("lng")
        else:
            logging.warning(f"get_teacher_location(): No data found for class '{class_name}'")
            return None, None
    except requests.RequestException as e:
        logging.error(f"get_teacher_location(): Error fetching teacher location from Firebase: {e}")
        return None, None
    
def is_valid_location(lat, lng, class_name):
    """Check if the location is within a valid range."""
    teacher_lat, teacher_lng = get_teacher_location(class_name)
    logging.debug(f"is_valid_location(): Teacher location: lat={teacher_lat}, lng={teacher_lng}")

    if teacher_lat is None or teacher_lng is None:
        logging.warning("Teacher location not found or data incomplete.")
        return False

    distance = calculate_distance(lat, lng, teacher_lat, teacher_lng)
    logging.debug(f"is_valid_location(): Distance from teacher: {distance} meters")

    if distance > DISTANCE_THRESHOLD:
        logging.warning("Student is too far from the class.")
        return False
    return True


def validate_token(auth_header):
    """Validates the API token from the Authorization header."""
    if not auth_header:
        raise InvalidUsage('Authorization header missing', 401)

    if not auth_header.startswith('Bearer '):
        raise InvalidUsage('Invalid authorization format', 401)

    token = auth_header.split(' ')[1]

    if token != RAILWAY_TOKEN:
        logging.warning(f"Invalid API token received: '{token}', expected: '{RAILWAY_TOKEN}'")
        raise InvalidUsage('Invalid API token', 401)


@app.route("/submit_attendance", methods=["POST"])
def submit_attendance():
    """API endpoint to handle attendance submission."""
    logging.debug("Received a request to /submit_attendance")

    # Validate API token
    auth_header = request.headers.get('Authorization')
    validate_token(auth_header)

    data = request.get_json()
    logging.debug(f"Received data: {data}")

    student_name = data.get("student_name")
    student_roll = data.get("student_roll")
    class_name = data.get("class_name")
    qr_code = data.get("qr_code")
    lat = data.get("lat")
    lng = data.get("lng")
    time = data.get("time")
    gps_status = data.get("gps_status")
    device_id = data.get("device_id")

    if not student_name or not student_roll or not class_name or not qr_code or not lat or not lng or not time or not gps_status or not device_id:
        logging.warning("Missing required fields in request")
        raise InvalidUsage("Missing required fields", 400)

    try:
        float_lat = float(lat)
        float_lng = float(lng)
    except ValueError:
        logging.warning(f"Invalid latitude or longitude format received: lat='{lat}', lng='{lng}'")
        raise InvalidUsage("Invalid latitude or longitude format.", 400)

    logging.debug(f"Received latitude: {float_lat}, longitude: {float_lng}")

    if not is_valid_location(float_lat, float_lng, class_name):
        logging.warning(f"Invalid location: lat={float_lat}, lng={float_lng}")
        raise InvalidUsage("You are too far from the class.", 403)

    try:
        update_attendance(class_name, student_name, student_roll, qr_code, gps_status, float_lat, float_lng, time, device_id)
        return jsonify({"status": "success", "message": "Attendance recorded."}), 200
    except InvalidUsage as e:
        raise e
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")
        raise InvalidUsage("An unexpected error occurred", 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)