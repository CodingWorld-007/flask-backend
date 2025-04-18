from flask import Flask, request, jsonify, abort
import requests
import os
import base64
import logging
import math  # Import the math module
from dotenv import load_dotenv
import ipaddress

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.DEBUG)  # Set to DEBUG for more detail

# Load environment variables
load_dotenv()

GITHUB_USERNAME = os.getenv("GITHUB_USERNAME")
REPO_NAME = os.getenv("REPO_NAME")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
IPINFO_TOKEN = os.getenv("IPINFO_TOKEN")
RAILWAY_TOKEN = os.getenv("RAILWAY_TOKEN")
FIREBASE_SECRET = os.getenv("FIREBASE_SECRET")
FIREBASE_URL = os.getenv("FIREBASE_URL")
GITHUB_API_BASE = f"https://api.github.com/repos/{GITHUB_USERNAME}/{REPO_NAME}/contents"
# Constants
DISTANCE_THRESHOLD = 250
CSV_HEADER = "Student Name, Student Roll, Class Name, QR Code, Latitude, Longitude, Time, VPN Used, GPS Status, IP Address\n"

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

# Global variable to hold the known VPN ranges.
KNOWN_VPN_RANGES = []

def is_vpn(ip):
    """
    Detect VPN or Proxy usage via multiple checks, including IPInfo, CGNAT bypass, and known VPN ranges.
    """
    if not IPINFO_TOKEN:
        logging.warning("IPINFO_TOKEN is missing, VPN detection will be limited.")
        return "Unknown"

    try:
        # 1. Check for CGNAT (Bypass VPN checks if it's a CGNAT IP)
        if ip_in_cgnat_range(ip):
            logging.debug(f"IP {ip} is in CGNAT range. Skipping IPInfo VPN check.")
            return "No"

        # 2. IPInfo Check
        ipinfo_data = get_ipinfo_data(ip)
        if ipinfo_data:
            if is_ipinfo_flagged_as_vpn(ipinfo_data):
                logging.debug(f"IPInfo flagged {ip} as VPN or Proxy.")
                return "Yes"

        # 3. Check Known VPN Ranges
        if ip_in_known_vpn_range(ip):
          logging.debug(f"IP {ip} is in a known VPN range.")
          return "Yes"

        # 4. Fallback (Not Flagged)
        logging.debug(f"IP {ip} not detected as VPN.")
        return "No"

    except ValueError:
        logging.error(f"Invalid IP address: {ip}")
        return "Unknown"
    except Exception as e:
        logging.error(f"An unexpected error occurred while checking VPN status for IP {ip}: {e}")
        return "Unknown"
# Helper Functions

def ip_in_cgnat_range(ip):
    """Checks if an IP address is in a known CGNAT range."""
    cgnat_ranges = [
        ipaddress.ip_network('100.64.0.0/10'),  # Standard CGNAT range
        # Add other CGNAT ranges here if needed (e.g., ipaddress.ip_network('10.0.0.0/8'))
    ]
    ip_obj = ipaddress.ip_address(ip)
    for network in cgnat_ranges:
        if ip_obj in network:
            return True
    return False

def get_ipinfo_data(ip):
    """Fetches IPInfo data and returns it as a dictionary."""
    try:
        response = requests.get(f"https://ipinfo.io/{ip}?token={IPINFO_TOKEN}", timeout=5)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logging.error(f"Error checking IPInfo data for IP {ip}: {e}")
        return None

def is_ipinfo_flagged_as_vpn(ipinfo_data):
    """Checks if IPInfo data indicates VPN or proxy usage."""
    return (ipinfo_data.get("bogon") or
            ipinfo_data.get("privacy", {}).get("vpn") or
            ipinfo_data.get("privacy", {}).get("proxy") or
            ipinfo_data.get("privacy", {}).get("hosting"))

def ip_in_known_vpn_range(ip):
    """Checks if an IP address is in a list of known VPN ranges."""
    global KNOWN_VPN_RANGES

    if not KNOWN_VPN_RANGES:
      load_known_vpn_ranges("vpn_ip.txt")
    ip_obj = ipaddress.ip_address(ip)
    for network in KNOWN_VPN_RANGES:
        if ip_obj in network:
            return True
    return False

def load_known_vpn_ranges(filepath):
    """Loads known VPN IP ranges from a file."""
    global KNOWN_VPN_RANGES
    KNOWN_VPN_RANGES = []
    try:
        with open(filepath, 'r') as file:
            for line in file:
                line = line.strip()
                try:
                    # Try to interpret each line as an IP network (e.g., "103.173.14.0/24")
                    KNOWN_VPN_RANGES.append(ipaddress.ip_network(line))
                except ValueError:
                    try:
                        # If not a network, try to interpret it as a single IP address (e.g., "103.173.14.1")
                        KNOWN_VPN_RANGES.append(ipaddress.ip_network(line + "/32"))  # /32 means a single IP
                    except ValueError:
                        logging.warning(f"Invalid IP address or network in file: {line}")
    except FileNotFoundError:
        logging.error(f"File not found: {filepath}")

# Call to load the file
load_known_vpn_ranges("vpn_ip.txt")


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


import datetime

def add_to_defaulters(class_name, entry):
    """Adds an entry to the defaulters list file."""
    defaulters_file_path = f"defaulters_{class_name}.csv"
    url = f"{GITHUB_API_BASE}/{defaulters_file_path}"

    try:
        # Check if the file exists to fetch the current sha
        response = requests.get(url, headers={"Authorization": f"token {GITHUB_TOKEN}"})
        if response.status_code == 200:
            content = response.json()
            sha = content.get("sha")
            existing_content = base64.b64decode(content["content"]).decode("utf-8")
        else:
            sha = None
            existing_content = CSV_HEADER  # Add the header if the file does not exist yet

        new_data = existing_content + entry

        encoded_data = base64.b64encode(new_data.encode("utf-8")).decode("utf-8")

        payload = {
            "message": f"Added defaulter for {class_name}",
            "content": encoded_data,
            "branch": "main"
        }
        if sha:
            payload["sha"] = sha  # Update existing file

        response = requests.put(url, headers={"Authorization": f"token {GITHUB_TOKEN}"}, json=payload, timeout=10)
        response.raise_for_status()
        logging.info(f"Added entry to defaulters for class {class_name}.")

    except requests.RequestException as e:
        logging.error(f"Error adding entry to defaulters list on GitHub: {e}")
        raise InvalidUsage(f"Error adding entry to defaulters list on GitHub: {e}", 500)

def get_existing_entries(class_name):
    """Fetch attendance data from GitHub and return existing IPs and sha."""
    file_path = f"attendance_{class_name}.csv"
    url = f"{GITHUB_API_BASE}/{file_path}?ref=main"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}

    try:
        response = requests.get(url, headers=headers, timeout=5)
        logging.debug(f"get_existing_entries(): Response from GitHub: {response.status_code}")
        if response.status_code == 404:
            logging.info(f"File for class {class_name} not found on GitHub.")
            return set(), None, [] # No file exists yet

        response.raise_for_status()
        content = response.json()
        sha = content.get("sha")
        file_data = base64.b64decode(content["content"]).decode("utf-8")

        existing_ips = set()
        existing_entries = []
        lines = file_data.strip().split("\n")[1:]  # Skip header
        for line in lines:
            parts = line.split(", ")
            if len(parts) >= 10:
                existing_ips.add(parts[9].strip())  # IP
                existing_entries.append(line)  # Add the entire line

        return existing_ips, sha, existing_entries
    except requests.RequestException as e:
        logging.error(f"Error fetching data from GitHub: {e}")
        raise InvalidUsage(f"Error fetching data from GitHub: {e}", 500)

def update_attendance(class_name, student_name, student_roll, qr_code, ip, vpn_status, gps_status, lat, lng, time):
    """
    Update attendance while checking for duplicate IPs.
    """
    existing_ips, sha, existing_entries = get_existing_entries(class_name)
    new_entry = f"{student_name}, {student_roll}, {class_name}, {qr_code}, {lat}, {lng}, {time}, {vpn_status}, {gps_status}, {ip}\n"

    if ip in existing_ips:
        # Duplicate IP found
        logging.warning(f"Duplicate IP {ip} found. Adding previous entry to defaulters.")
        for entry in existing_entries:
            if entry.split(", ")[9].strip() == ip:
                add_to_defaulters(class_name, entry)
                existing_entries.remove(entry)
    
    if sha is None:
        create_new_file(class_name, new_entry)
        return True
    
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


def is_valid_location(lat, lng):
    """Check if the location is within a valid range."""
    teacher_lat, teacher_lng = get_teacher_location(request.json.get("class_name"))
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

    data = request.json
    logging.debug(f"Received data: {data}")

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
        logging.warning("Missing required fields in request")
        raise InvalidUsage("Missing required fields", 400)

    try:
        float_lat = float(lat)
        float_lng = float(lng)
    except ValueError:
        logging.warning(f"Invalid latitude or longitude format received: lat='{lat}', lng='{lng}'")
        raise InvalidUsage("Invalid latitude or longitude format.", 400)

    logging.debug(f"Received latitude: {float_lat}, longitude: {float_lng}")

    if not is_valid_location(float_lat, float_lng):
        logging.warning(f"Invalid location: lat={float_lat}, lng={float_lng}")
        raise InvalidUsage("Invalid location", 403)

    vpn_status = is_vpn(ip)

    try:
        update_attendance(class_name, student_name, student_roll, qr_code, ip, vpn_status, gps_status, float_lat, float_lng, time)
        return jsonify({"status": "success", "message": "Attendance recorded"}), 200
    except InvalidUsage as e:
        raise e
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")
        raise InvalidUsage("An unexpected error occurred", 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)