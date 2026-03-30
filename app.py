"""
Multilingual Interview and Document Preparation System.
A Flask web application that helps non-English-speaking job seekers
create professional CVs through recorded, translated interviews.
"""

import os
import json
import tempfile
from datetime import datetime, date, timezone

from flask import (Flask, render_template, request, jsonify, redirect,
                   url_for, flash, send_from_directory, send_file)
from werkzeug.utils import secure_filename

from models import db, Student, InterviewSession, generate_student_id
from services.transcription import TranscriptionService
from services.translation import TranslationService
from services.document_gen import DocumentGenerator
from services.file_manager import FileManager
from config import Config


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.config.from_object(Config)

db.init_app(app)

# Service singletons (initialised in main block)
transcription_service = None
translation_service = None
document_generator = None
file_manager = None


def init_services():
    """Initialise all service instances."""
    global transcription_service, translation_service, document_generator, file_manager
    transcription_service = TranscriptionService(app.config)
    translation_service = TranslationService(app.config)
    document_generator = DocumentGenerator(app.config)
    file_manager = FileManager(app.config)


def _student_dict(student):
    """Convert a Student ORM object to a dict for services."""
    return {
        "id": student.student_id,
        "surname": student.surname,
        "first_name": student.first_name,
        "email": student.email,
        "phone": student.phone,
        "location": f"{student.suburb or ''} {student.postcode or ''}".strip(),
        "preferred_language": student.preferred_language,
        "english_level": student.english_level,
    }


def _session_dict(sess):
    """Convert an InterviewSession ORM object to a dict for services."""
    return {
        "id": sess.id,
        "date": sess.date.isoformat() if sess.date else datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "session_number": sess.session_number,
    }


# ---------------------------------------------------------------------------
# Template helpers
# ---------------------------------------------------------------------------

@app.context_processor
def inject_globals():
    """Make common data available to all templates."""
    return {
        "SUPPORTED_LANGUAGES": Config.SUPPORTED_LANGUAGES,
        "ENGLISH_LEVELS": Config.ENGLISH_LEVELS,
        "ORG_NAME": Config.ORG_NAME,
    }


@app.template_filter("lang_name")
def lang_name_filter(code):
    """Convert a language code to its display name."""
    return Config.SUPPORTED_LANGUAGES.get(code, code)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@app.route("/")
def dashboard():
    total_students = Student.query.count()
    today = date.today()
    from sqlalchemy import func
    sessions_this_week = InterviewSession.query.filter(
        InterviewSession.date >= today.replace(day=max(1, today.day - today.weekday()))
    ).count()
    languages_supported = len(Config.SUPPORTED_LANGUAGES)
    recent_students = Student.query.order_by(Student.updated_at.desc()).limit(10).all()

    return render_template(
        "dashboard.html",
        total_students=total_students,
        sessions_this_week=sessions_this_week,
        languages_supported=languages_supported,
        recent_students=recent_students,
    )


# ---------------------------------------------------------------------------
# Students
# ---------------------------------------------------------------------------

@app.route("/students")
def students_list():
    q = request.args.get("q", "").strip()
    page = request.args.get("page", 1, type=int)
    query = Student.query

    if q:
        query = query.filter(
            db.or_(
                Student.first_name.ilike(f"%{q}%"),
                Student.surname.ilike(f"%{q}%"),
                Student.student_id.ilike(f"%{q}%"),
                Student.preferred_language.ilike(f"%{q}%"),
            )
        )

    students = query.order_by(Student.created_at.desc()).paginate(
        page=page, per_page=20, error_out=False
    )
    return render_template("students.html", students=students, search_query=q)


@app.route("/students/new", methods=["GET"])
def student_new_form():
    return render_template("student_new.html")


@app.route("/students/new", methods=["POST"])
def student_new_create():
    try:
        sid = generate_student_id()
        student = Student(
            student_id=sid,
            first_name=request.form.get("first_name", "").strip(),
            surname=request.form.get("surname", "").strip(),
            date_of_birth=request.form.get("dob", "").strip() or None,
            suburb=request.form.get("suburb", "").strip(),
            postcode=request.form.get("postcode", "").strip(),
            phone=request.form.get("phone", "").strip(),
            email=request.form.get("email", "").strip(),
            preferred_language=request.form.get("preferred_language", "en"),
            other_languages=request.form.get("other_languages", "").strip(),
            english_level=request.form.get("english_level", ""),
        )

        if not student.first_name or not student.surname:
            flash("Please enter the student's first name and surname.", "error")
            return redirect(url_for("student_new_form"))

        db.session.add(student)
        db.session.commit()

        # Create folder on disk
        file_manager.create_student_folder(_student_dict(student))

        flash(f"Student {student.display_name} registered (ID: {sid}).", "success")
        return redirect(url_for("student_profile", student_id=student.id))

    except Exception as e:
        db.session.rollback()
        flash(f"Error: {e}", "error")
        return redirect(url_for("student_new_form"))


@app.route("/students/<int:student_id>")
def student_profile(student_id):
    student = Student.query.get_or_404(student_id)
    sessions = (InterviewSession.query
                .filter_by(student_id=student.id)
                .order_by(InterviewSession.date.desc())
                .all())

    student_files = file_manager.get_student_files(_student_dict(student))

    return render_template(
        "student_profile.html",
        student=student,
        sessions=sessions,
        student_files=student_files,
    )


# ---------------------------------------------------------------------------
# Interview
# ---------------------------------------------------------------------------

@app.route("/interview/<int:student_id>")
def interview(student_id):
    student = Student.query.get_or_404(student_id)
    return render_template("interview.html", student=student)


@app.route("/interview/<int:student_id>/start", methods=["POST"])
def interview_start(student_id):
    try:
        student = Student.query.get_or_404(student_id)
        last = (InterviewSession.query
                .filter_by(student_id=student.id)
                .order_by(InterviewSession.session_number.desc())
                .first())
        next_num = (last.session_number + 1) if last else 1

        sess = InterviewSession(
            student_id=student.id,
            session_number=next_num,
            date=date.today(),
            status="in_progress",
        )
        db.session.add(sess)
        db.session.commit()

        # Create session folder
        file_manager.create_session_folder(
            _student_dict(student), _session_dict(sess)
        )

        return jsonify({"success": True, "session_id": sess.id,
                        "session_number": next_num})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/interview/<int:student_id>/upload-audio", methods=["POST"])
def upload_audio(student_id):
    try:
        student = Student.query.get_or_404(student_id)
        if "audio" not in request.files:
            return jsonify({"success": False, "error": "No audio file"}), 400

        audio = request.files["audio"]
        session_id = request.form.get("session_id", type=int)
        sess = InterviewSession.query.get(session_id) if session_id else None
        if not sess:
            return jsonify({"success": False, "error": "Session not found"}), 404

        # Save to a temp file then move to session folder
        ext = "webm"
        sd = _student_dict(student)
        ssd = _session_dict(sess)
        student_dir = file_manager._get_student_dir(sd)
        session_folder = file_manager._get_session_folder_name(ssd)
        session_path = os.path.join(student_dir, session_folder)
        os.makedirs(session_path, exist_ok=True)

        filename = f"audio_{datetime.now().strftime('%H%M%S')}.{ext}"
        filepath = os.path.join(session_path, filename)
        audio.save(filepath)

        return jsonify({"success": True, "filename": filename,
                        "filepath": filepath})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/interview/<int:student_id>/transcribe", methods=["POST"])
def transcribe_audio(student_id):
    try:
        student = Student.query.get_or_404(student_id)
        data = request.get_json()
        filepath = data.get("filepath", "")

        if not filepath or not os.path.exists(filepath):
            return jsonify({"success": False, "error": "Audio file not found"}), 400

        result = transcription_service.transcribe(
            filepath, language=student.preferred_language
        )
        return jsonify({"success": True, "transcript": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/interview/<int:student_id>/translate", methods=["POST"])
def translate_text(student_id):
    try:
        data = request.get_json()
        text = data.get("text", "")
        source = data.get("source_language", "")
        target = data.get("target_language", "en")

        if not text:
            return jsonify({"success": False, "error": "No text provided"}), 400

        translated = translation_service.translate(text, source, target)
        return jsonify({"success": True, "translated_text": translated})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/interview/<int:student_id>/save-transcript", methods=["POST"])
def save_transcript(student_id):
    try:
        student = Student.query.get_or_404(student_id)
        data = request.get_json()
        session_id = data.get("session_id")
        transcript_entries = data.get("transcript", [])
        # Gather structured data from front end
        work_experience = data.get("work_experience")
        education = data.get("education")
        skills = data.get("skills")
        job_preferences = data.get("job_preferences")
        certificates = data.get("certificates")
        availability = data.get("availability")
        transport = data.get("transport")
        additional_info = data.get("additional_info")

        sess = InterviewSession.query.get(session_id)
        if not sess:
            return jsonify({"success": False, "error": "Session not found"}), 404

        # Build full transcript text
        english_parts = []
        original_parts = []
        for entry in transcript_entries:
            english_parts.append(entry.get("english", ""))
            original_parts.append(entry.get("original", entry.get("english", "")))

        sess.transcript_english = "\n".join(english_parts)
        sess.transcript_original = "\n".join(original_parts)
        sess.work_experience = json.dumps(work_experience) if work_experience else None
        sess.education = json.dumps(education) if education else None
        sess.skills = json.dumps(skills) if skills else None
        sess.job_preferences = json.dumps(job_preferences) if job_preferences else None
        sess.certificates = json.dumps(certificates) if certificates else None
        sess.availability = json.dumps(availability) if availability else None
        sess.transport = transport
        sess.additional_info = additional_info
        sess.status = "completed"

        db.session.commit()

        # Save transcript files
        sd = _student_dict(student)
        ssd = _session_dict(sess)
        file_manager.save_transcript(sd, ssd, sess.transcript_english, "en")
        if student.preferred_language != "en":
            file_manager.save_transcript(
                sd, ssd, sess.transcript_original, student.preferred_language
            )

        return jsonify({"success": True, "session_id": sess.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# Document generation
# ---------------------------------------------------------------------------

@app.route("/interview/<int:student_id>/generate-documents")
def generate_documents_page(student_id):
    student = Student.query.get_or_404(student_id)
    latest = (InterviewSession.query
              .filter_by(student_id=student.id)
              .order_by(InterviewSession.created_at.desc())
              .first())
    if not latest:
        flash("No interview session found for this student.", "error")
        return redirect(url_for("student_profile", student_id=student.id))

    return render_template("documents.html", student=student, session=latest)


@app.route("/interview/<int:student_id>/generate", methods=["POST"])
def generate_documents(student_id):
    try:
        student = Student.query.get_or_404(student_id)
        data = request.get_json()
        session_id = data.get("session_id")
        doc_types = data.get("documents", [])
        job_title = data.get("job_title", "")
        employer = data.get("employer", "")

        sess = InterviewSession.query.get(session_id)
        if not sess:
            return jsonify({"success": False, "error": "Session not found"}), 404

        # Parse stored JSON fields
        work_exp = json.loads(sess.work_experience) if sess.work_experience else []
        education = json.loads(sess.education) if sess.education else []
        skills = json.loads(sess.skills) if sess.skills else []
        job_prefs = json.loads(sess.job_preferences) if sess.job_preferences else {}
        certificates = json.loads(sess.certificates) if sess.certificates else []
        availability = json.loads(sess.availability) if sess.availability else {}

        name = f"{student.first_name} {student.surname}"
        lang_name = Config.SUPPORTED_LANGUAGES.get(
            student.preferred_language, student.preferred_language
        )
        today_str = date.today().strftime("%d %B %Y")

        generated = {}

        for doc_type in doc_types:
            try:
                if doc_type == "cv":
                    lines = [
                        f"{'=' * 50}",
                        f"CURRICULUM VITAE",
                        f"{'=' * 50}",
                        "",
                        f"{name.upper()}",
                        "",
                    ]
                    contact = []
                    if student.phone:
                        contact.append(f"Phone: {student.phone}")
                    if student.email:
                        contact.append(f"Email: {student.email}")
                    if student.suburb:
                        contact.append(
                            f"Location: {student.suburb}"
                            + (f" {student.postcode}" if student.postcode else "")
                        )
                    lines.extend(contact)
                    lines.append("")

                    lines.append("PROFESSIONAL SUMMARY")
                    lines.append("-" * 30)
                    lines.append(
                        f"Motivated and reliable worker seeking employment in "
                        f"Melbourne. Speaks {lang_name} and English. "
                        + (sess.additional_info or "Eager to contribute to a team environment.")
                    )
                    lines.append("")

                    if work_exp:
                        lines.append("WORK EXPERIENCE")
                        lines.append("-" * 30)
                        for job in work_exp:
                            t = job.get("title", "Role")
                            e = job.get("employer", "Employer")
                            d = job.get("duration", "")
                            lines.append(f"  {t}  |  {e}  |  {d}")
                        lines.append("")

                    if skills:
                        lines.append("KEY SKILLS")
                        lines.append("-" * 30)
                        if isinstance(skills, list):
                            lines.append("  " + "  |  ".join(str(s) for s in skills))
                        lines.append("")

                    if education:
                        lines.append("EDUCATION & TRAINING")
                        lines.append("-" * 30)
                        for ed in education:
                            inst = ed.get("institution", "")
                            qual = ed.get("qualification", "")
                            yr = ed.get("year", "")
                            lines.append(f"  {qual}  |  {inst}  |  {yr}")
                        lines.append("")

                    if certificates:
                        lines.append("CERTIFICATES")
                        lines.append("-" * 30)
                        for cert in certificates:
                            lines.append(f"  - {cert}")
                        lines.append("")

                    lines.append("LANGUAGES")
                    lines.append("-" * 30)
                    lines.append(f"  {lang_name}: Native speaker")
                    lines.append(f"  English: {student.english_level or 'Basic'}")
                    lines.append("")

                    if sess.transport:
                        lines.append("TRANSPORT")
                        lines.append("-" * 30)
                        lines.append(f"  {sess.transport}")
                        lines.append("")

                    lines.append("REFERENCES")
                    lines.append("-" * 30)
                    lines.append("  Available upon request")
                    lines.append("")
                    lines.append(f"Generated: {today_str}")

                    generated["cv"] = "\n".join(lines)

                elif doc_type == "cover_letter":
                    role = job_title or "an available position"
                    company = employer or "your organisation"
                    skills_text = ", ".join(str(s) for s in skills[:5]) if skills else "a strong work ethic"

                    lines = [
                        f"{name}",
                        f"{student.phone or ''}",
                        f"{student.email or ''}",
                        f"{student.suburb or ''} {student.postcode or ''}".strip(),
                        "",
                        today_str,
                        "",
                        f"Re: Application for {role}",
                        "",
                        f"Dear Hiring Manager,",
                        "",
                        f"I am writing to express my interest in {role} at {company}. "
                        f"I am a motivated and reliable worker with experience in "
                        f"{work_exp[0].get('title', 'various roles') if work_exp else 'various roles'}.",
                        "",
                        f"I bring {skills_text} to any role. "
                        + (f"Most recently, I worked as {work_exp[0].get('title', '')} "
                           f"at {work_exp[0].get('employer', '')} for {work_exp[0].get('duration', '')}. "
                           if work_exp else "")
                        + f"I am a native {lang_name} speaker with "
                        f"{student.english_level or 'basic'} English.",
                        "",
                        f"I am available to work "
                        + (", ".join(
                            k for k, v in availability.items()
                            if v and k not in ("notes",)
                        ) if availability else "flexible hours")
                        + f" and travel by {sess.transport or 'public transport'}.",
                        "",
                        f"I would welcome the opportunity to discuss how I can contribute "
                        f"to your team. Thank you for considering my application.",
                        "",
                        f"Yours sincerely,",
                        f"{name}",
                    ]
                    generated["cover_letter"] = "\n".join(lines)

                elif doc_type == "summary_internal":
                    lines = [
                        f"{'=' * 50}",
                        f"INTERNAL MEETING SUMMARY",
                        f"{'=' * 50}",
                        "",
                        f"Student: {name} (ID: {student.student_id})",
                        f"Date: {today_str}",
                        f"Session: #{sess.session_number}",
                        f"Preferred Language: {lang_name}",
                        f"English Level: {student.english_level or 'Not assessed'}",
                        "",
                        "BACKGROUND",
                        "-" * 30,
                    ]
                    if work_exp:
                        lines.append("Work history:")
                        for job in work_exp:
                            lines.append(
                                f"  - {job.get('title', 'N/A')} at "
                                f"{job.get('employer', 'N/A')} ({job.get('duration', 'N/A')})"
                            )
                    if education:
                        lines.append("Education:")
                        for ed in education:
                            lines.append(
                                f"  - {ed.get('qualification', 'N/A')} at "
                                f"{ed.get('institution', 'N/A')}"
                            )
                    if skills:
                        lines.append(f"Skills: {', '.join(str(s) for s in skills)}")
                    if certificates:
                        lines.append(f"Certificates: {', '.join(str(c) for c in certificates)}")
                    lines.append("")

                    lines.append("JOB PREFERENCES")
                    lines.append("-" * 30)
                    if isinstance(job_prefs, dict):
                        for k, v in job_prefs.items():
                            lines.append(f"  {k}: {v}")
                    lines.append("")

                    lines.append("AVAILABILITY & TRANSPORT")
                    lines.append("-" * 30)
                    if availability:
                        avail_parts = [k for k, v in availability.items() if v]
                        lines.append(f"  Available: {', '.join(avail_parts)}")
                    lines.append(f"  Transport: {sess.transport or 'Not specified'}")
                    lines.append("")

                    if sess.additional_info:
                        lines.append("ADDITIONAL NOTES")
                        lines.append("-" * 30)
                        lines.append(f"  {sess.additional_info}")
                        lines.append("")

                    if sess.transcript_english:
                        lines.append("TRANSCRIPT (English)")
                        lines.append("-" * 30)
                        lines.append(sess.transcript_english)
                        lines.append("")

                    lines.append(f"Generated: {today_str}")
                    generated["summary_internal"] = "\n".join(lines)

                elif doc_type == "summary_student":
                    lines = [
                        f"{'=' * 50}",
                        f"YOUR MEETING SUMMARY",
                        f"{'=' * 50}",
                        "",
                        f"Hello {student.first_name}!",
                        "",
                        f"Thank you for meeting with us on {today_str}. "
                        f"Here is a summary of what we discussed.",
                        "",
                        "WHAT WE TALKED ABOUT",
                        "-" * 30,
                    ]
                    if work_exp:
                        lines.append("Your work experience:")
                        for job in work_exp:
                            lines.append(
                                f"  - {job.get('title', '')} at {job.get('employer', '')}"
                            )
                    if skills:
                        lines.append(f"Your skills: {', '.join(str(s) for s in skills)}")
                    if education:
                        lines.append("Your education:")
                        for ed in education:
                            lines.append(
                                f"  - {ed.get('qualification', '')} at {ed.get('institution', '')}"
                            )
                    lines.append("")

                    lines.append("WHAT WE WILL DO NEXT")
                    lines.append("-" * 30)
                    lines.append("  - We will prepare your CV")
                    lines.append("  - We will help you look for suitable jobs")
                    if job_prefs:
                        roles = job_prefs.get("roles", "")
                        if roles:
                            lines.append(f"  - We will focus on: {roles}")
                    lines.append("")
                    lines.append(
                        "If you have any questions, please contact us. "
                        "We are here to help!"
                    )
                    lines.append("")
                    lines.append(f"Generated: {today_str}")
                    generated["summary_student"] = "\n".join(lines)

                elif doc_type == "action_items":
                    lines = [
                        f"{'=' * 50}",
                        f"ACTION ITEMS",
                        f"{'=' * 50}",
                        "",
                        f"Student: {name}",
                        f"Date: {today_str}",
                        "",
                        "FOR STAFF",
                        "-" * 30,
                        "  [ ] Finalise CV and have student review",
                        "  [ ] Search for suitable job openings",
                    ]
                    if job_prefs:
                        roles = job_prefs.get("roles", "")
                        if roles:
                            lines.append(f"      (Focus areas: {roles})")
                    lines.append("  [ ] Prepare cover letter template")
                    lines.append("  [ ] Schedule follow-up meeting")
                    lines.append("")
                    lines.append("FOR STUDENT")
                    lines.append("-" * 30)
                    lines.append("  [ ] Review CV draft")
                    lines.append("  [ ] Gather any missing documents or references")
                    if not certificates:
                        lines.append("  [ ] Look into relevant certificates or training")
                    lines.append("  [ ] Continue English language studies")
                    lines.append("")
                    lines.append(f"Generated: {today_str}")
                    generated["action_items"] = "\n".join(lines)

            except Exception as doc_err:
                generated[doc_type] = f"Error generating document: {doc_err}"

        # Record which docs were generated
        sess.documents_generated = json.dumps(list(generated.keys()))
        db.session.commit()

        return jsonify({"success": True, "documents": generated})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# File serving
# ---------------------------------------------------------------------------

@app.route("/files/<path:filepath>")
def serve_file(filepath):
    """Serve files from the student_files directory."""
    full = os.path.join(app.config["STUDENT_FILES_DIR"], filepath)
    if not os.path.isfile(full):
        return "File not found", 404
    directory = os.path.dirname(full)
    filename = os.path.basename(full)
    return send_from_directory(directory, filename, as_attachment=True)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@app.route("/api/students/search")
def api_search_students():
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify({"results": []})

    students = Student.query.filter(
        db.or_(
            Student.first_name.ilike(f"%{q}%"),
            Student.surname.ilike(f"%{q}%"),
            Student.student_id.ilike(f"%{q}%"),
        )
    ).limit(10).all()

    return jsonify({
        "results": [
            {"id": s.id, "student_id": s.student_id,
             "name": s.display_name,
             "language": Config.SUPPORTED_LANGUAGES.get(s.preferred_language, s.preferred_language)}
            for s in students
        ]
    })


@app.route("/api/translate", methods=["POST"])
def api_translate():
    try:
        data = request.get_json()
        text = data.get("text", "")
        source = data.get("source_language", "")
        target = data.get("target_language", "en")
        if not text:
            return jsonify({"success": False, "error": "No text"}), 400
        translated = translation_service.translate(text, source, target)
        return jsonify({"success": True, "translated_text": translated})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(404)
def not_found(error):
    return render_template("404.html"), 404


@app.errorhandler(500)
def server_error(error):
    db.session.rollback()
    return render_template("500.html"), 500


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

# Initialise on import (for gunicorn) and for direct execution
with app.app_context():
    db.create_all()
    init_services()
    os.makedirs(app.config["STUDENT_FILES_DIR"], exist_ok=True)


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
