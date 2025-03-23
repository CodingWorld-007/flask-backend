import os
from flask import Flask, request, jsonify
import git

app = Flask(__name__)

# GitHub Repo Details
GITHUB_REPO_URL = "https://github.com/CodingWorld-007/attendance-system.git"

GITHUB_PAT = os.getenv("GITHUB_PAT")  # ✅ Store PAT securely in Render Env Variables
LOCAL_REPO_PATH = "/tmp/attendance-system"

# Clone Repo (if not exists)
if not os.path.exists(LOCAL_REPO_PATH):
    git.Repo.clone_from(GITHUB_REPO_URL, LOCAL_REPO_PATH)

@app.route('/submit_attendance', methods=['POST'])
def submit_attendance():
    data = request.json
    student_id = data.get('student_id')
    timestamp = data.get('timestamp')

    file_path = os.path.join(LOCAL_REPO_PATH, "data", "attendance.txt")

    # Append attendance data
    os.makedirs(os.path.dirname(file_path), exist_ok=True)  # ✅ Ensure "data" folder exists
    with open(file_path, "a") as f:
        f.write(f"{student_id},{timestamp}\n")

    # Commit and Push to GitHub Securely
    repo = git.Repo(LOCAL_REPO_PATH)
    repo.git.add(file_path)
    repo.index.commit(f"Added attendance for {student_id}")
    origin = repo.remote(name='origin')
    origin.set_url(f"https://{GITHUB_PAT}@github.com/CodingWorld-007/attendance-system.git")
    origin.push()

    return jsonify({"status": "Attendance recorded"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
