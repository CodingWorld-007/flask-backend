from flask import Flask, request, jsonify
from flask_cors import CORS
from psycopg2 import pool, errors
from psycopg2.extras import RealDictCursor
import logging

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
    data = request.get_json(force=True)

    required_fields = ["class_id", "student_id", "device_id", "gps_lat", "gps_long", "gps_status"]
    if not all(data.get(field) for field in required_fields):
        return jsonify({"error": "Missing required fields."}), 400

    conn = None
    cur = None

    try:
        conn = db_pool.getconn()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        insert_query = """
            INSERT INTO attendance (class_id, student_id, device_id, gps_lat, gps_long, gps_status)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING *;
        """
        cur.execute(insert_query, (
            data["class_id"],
            data["student_id"],
            data["device_id"],
            data["gps_lat"],
            data["gps_long"],
            data["gps_status"]
        ))
        conn.commit()
        result = cur.fetchone()

        return jsonify({
            "message": "Attendance recorded successfully.",
            "data": result
        }), 201

    except errors.UniqueViolation:
        if conn:
            conn.rollback()
        return jsonify({"error": "Attendance already marked for this class today."}), 409

    except Exception as e:
        if conn:
            conn.rollback()
        logging.exception("Unexpected error occurred while recording attendance.")
        return jsonify({"error": "Internal server error."}), 500

    finally:
        if cur:
            cur.close()
        if conn:
            db_pool.putconn(conn)

if __name__ == "__main__":
    app.run(debug=False, port=8080)
