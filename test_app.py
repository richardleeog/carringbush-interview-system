"""Integration tests for the Multilingual Interview System."""

import os
import sys
import json
import tempfile

# Use a temp directory for test database and files
test_dir = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(test_dir, 'test.db')}"

# Set config before importing app
sys.path.insert(0, os.path.dirname(__file__))

from config import Config
Config.STUDENT_FILES_DIR = os.path.join(test_dir, "students")
Config.SQLALCHEMY_DATABASE_URI = f"sqlite:///{os.path.join(test_dir, 'test.db')}"

from app import app, db, init_services, file_manager
from models import Student, InterviewSession, generate_student_id


def setup():
    """Set up fresh database for tests."""
    with app.app_context():
        db.drop_all()
        db.create_all()


def create_test_student():
    """Helper: create a test student in the DB."""
    with app.app_context():
        sid = generate_student_id()
        student = Student(
            student_id=sid,
            first_name="Maria",
            surname="Garcia",
            preferred_language="es",
            english_level="basic",
            suburb="Fitzroy",
            postcode="3065",
            phone="0400123456",
            email="maria@example.com",
        )
        db.session.add(student)
        db.session.commit()
        return student.id, student.student_id


def test_route(client, method, url, data=None, expected_status=200, label=""):
    """Test a route and print PASS/FAIL."""
    try:
        if method == "GET":
            resp = client.get(url)
        elif method == "POST":
            if isinstance(data, dict) and "json" in data:
                resp = client.post(url, json=data["json"])
            elif isinstance(data, dict):
                resp = client.post(url, data=data, follow_redirects=True)
            else:
                resp = client.post(url)

        if resp.status_code == expected_status:
            print(f"  PASS - {label} (status {resp.status_code})")
            return resp
        else:
            print(f"  FAIL - {label} (expected {expected_status}, got {resp.status_code})")
            if resp.status_code >= 400:
                print(f"         Response: {resp.data[:300].decode('utf-8', errors='replace')}")
            return resp
    except Exception as e:
        print(f"  FAIL - {label} ({type(e).__name__}: {e})")
        return None


def run_tests():
    print("\n" + "=" * 60)
    print("INTEGRATION TESTS - Multilingual Interview System")
    print("=" * 60)

    setup()
    app.config["TESTING"] = True
    client = app.test_client()

    # 1. Dashboard
    print("\n--- Page Routes ---")
    test_route(client, "GET", "/", label="Dashboard")

    # 2. Students list
    test_route(client, "GET", "/students", label="Students list")

    # 3. New student form
    test_route(client, "GET", "/students/new", label="New student form")

    # 4. Create student via POST
    resp = test_route(client, "POST", "/students/new", data={
        "first_name": "Thanh",
        "surname": "Nguyen",
        "preferred_language": "vi",
        "english_level": "basic",
        "suburb": "Richmond",
        "postcode": "3121",
        "phone": "0412345678",
        "email": "thanh@example.com",
    }, expected_status=200, label="Create student (POST)")

    # 5. Get the student we just created
    with app.app_context():
        student = Student.query.filter_by(surname="Nguyen").first()
        if student:
            student_db_id = student.id
            student_sid = student.student_id
            print(f"         Created student ID: {student_sid}")
        else:
            print("  FAIL - Student not found in DB after creation")
            return

    # 6. Student profile
    test_route(client, "GET", f"/students/{student_db_id}", label="Student profile")

    # 7. Interview page
    test_route(client, "GET", f"/interview/{student_db_id}", label="Interview page")

    # 8. Start interview session
    print("\n--- API Routes ---")
    resp = test_route(client, "POST", f"/interview/{student_db_id}/start",
                      data={"json": {}}, label="Start interview session")
    session_id = None
    if resp:
        data = json.loads(resp.data)
        if data.get("success"):
            session_id = data.get("session_id")
            print(f"         Session ID: {session_id}")

    # 9. Translation API
    resp = test_route(client, "POST", "/api/translate",
                      data={"json": {"text": "Hello", "source_language": "en", "target_language": "es"}},
                      label="Translation API")
    if resp:
        data = json.loads(resp.data)
        print(f"         Translation result: {data.get('translated_text', data.get('error', 'N/A'))[:50]}")

    # 10. Search API
    resp = test_route(client, "GET", "/api/students/search?q=Nguyen", label="Search API")
    if resp:
        data = json.loads(resp.data)
        print(f"         Search results: {len(data.get('results', []))} found")

    # 11. Save transcript
    if session_id:
        resp = test_route(client, "POST", f"/interview/{student_db_id}/save-transcript",
                          data={"json": {
                              "session_id": session_id,
                              "transcript": [
                                  {"english": "My name is Thanh.", "original": "Tên tôi là Thanh."},
                                  {"english": "I have experience in hospitality.", "original": "Tôi có kinh nghiệm về khách sạn."},
                              ],
                              "work_experience": [{"title": "Kitchen Hand", "employer": "Pho House", "duration": "2 years"}],
                              "skills": ["cooking", "cleaning", "customer service"],
                              "education": [{"institution": "TAFE Victoria", "qualification": "Certificate III"}],
                          }},
                          label="Save transcript")

    # 12. Generate documents page
    if session_id:
        test_route(client, "GET", f"/interview/{student_db_id}/generate-documents",
                   label="Generate documents page")

    # 13. Generate documents API
    if session_id:
        resp = test_route(client, "POST", f"/interview/{student_db_id}/generate",
                          data={"json": {
                              "session_id": session_id,
                              "documents": ["cv", "summary_internal"],
                              "job_title": "Kitchen Hand",
                              "employer": "Melbourne Restaurant",
                          }},
                          label="Generate documents (POST)")
        if resp:
            data = json.loads(resp.data)
            if data.get("success"):
                print(f"         Documents generated: {list(data.get('documents', {}).keys())}")
            else:
                print(f"         Error: {data.get('error', 'unknown')}")

    # 14. 404 page
    print("\n--- Error Handling ---")
    test_route(client, "GET", "/nonexistent-page", expected_status=404, label="404 page")

    # 15. Student profile with files
    print("\n--- Post-Interview ---")
    test_route(client, "GET", f"/students/{student_db_id}", label="Student profile (with session)")

    print("\n" + "=" * 60)
    print("Tests complete.")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    run_tests()
