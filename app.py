from flask import Flask, request, jsonify
from flask_cors import CORS
from psycopg2 import pool, errors
from psycopg2.extras import RealDictCursor
import logging
from datetime import datetime  # Import datetime

# Initialize app and CORS
app = Flask(__name__)
CORS(app)

# Logging configuration
logging.basicConfig(level=logging.INFO)

# PostgreSQL connection pool setup
try:
    db_pool = pool.SimpleConnectionPool(
        minconn=1,
        maxconn=20,
        user="postgres",
        password="post",
        host="localhost",
        port="5432",
        database="smart_attendance_db"
    )
    if db_pool:
        logging.info("PostgreSQL connection pool created successfully.")
except Exception as e:
    logging.error(f"Failed to create connection pool: {e}")
    raise SystemExit("Cannot start server without database connection.")

@app.route("/api/attendance", methods=["POST"])
def mark_attendance():
    logging.info("Received attendance request")
    data = request.get_json(force=True)
    logging.info(f"Request data: {data}")

    # Ensure required fields are present, including attendance_id
    required_fields = ["class_id", "student_id", "device_id", "gps_lat", "gps_long", "gps_status"]
    if not all(data.get(field) for field in required_fields):
        return jsonify({"error": "Missing required fields."}), 400

    conn = None
    cur = None

    try:
        logging.info("Getting DB connection")
        conn = db_pool.getconn()
        logging.info("DB connection acquired")

        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get the current timestamp
        current_timestamp = datetime.utcnow()  # Get current UTC time

        insert_query = """
            INSERT INTO attendance (class_id, student_id, device_id, gps_lat, gps_long, gps_status, timestamp)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING attendance_id, *;  -- Adjusted to return attendance_id
        """
        logging.info("Executing insert query")
        cur.execute(insert_query, (
            data["class_id"],
            data["student_id"],
            data["device_id"],
            data["gps_lat"],
            data["gps_long"],
            data["gps_status"],
            current_timestamp  # Include the current timestamp
        ))
        conn.commit()
        result = cur.fetchone()
        logging.info(f"Insert successful: {result}")

        return jsonify({
            "message": "Attendance recorded successfully.",
            "data": result
        }), 201

    except Exception as e:
        logging.exception("Error in /api/attendance")
        if conn:
            conn.rollback()
        return jsonify({"error": "Internal server error."}), 500

    finally:
        if cur:
            cur.close()
        if conn:
            db_pool.putconn(conn)

if __name__ == "__main__":
    app.run(debug=False, port=8080)
