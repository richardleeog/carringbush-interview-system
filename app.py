"""
Student Interaction Register — Carringbush Adult Education.
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

from models import db, Student, InterviewSession, DocumentRecord, generate_student_id
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

    # Total documents generated
    total_documents = DocumentRecord.query.count()

    # All document records for the documents table, most recent first
    all_documents = (
        DocumentRecord.query
        .order_by(DocumentRecord.created_at.desc())
        .limit(50)
        .all()
    )

    # Build student status summaries
    student_statuses = {}
    for s in recent_students:
        docs = DocumentRecord.query.filter_by(student_id=s.id).all()
        sess_count = len(s.sessions)
        doc_count = len(docs)
        if doc_count > 0:
            submitted = [d for d in docs if d.status == "submitted"]
            shared = [d for d in docs if d.status == "shared_with_student"]
            if submitted:
                status = "Submitted"
                status_class = "status-submitted"
            elif shared:
                status = "Shared"
                status_class = "status-shared"
            else:
                status = "Docs generated"
                status_class = "status-generated"
        elif sess_count > 0:
            status = "Interview done"
            status_class = "status-interview"
        else:
            status = "Registered"
            status_class = "status-registered"
        student_statuses[s.id] = {"status": status, "class": status_class, "doc_count": doc_count}

    return render_template(
        "dashboard.html",
        total_students=total_students,
        sessions_this_week=sessions_this_week,
        languages_supported=languages_supported,
        total_documents=total_documents,
        recent_students=recent_students,
        all_documents=all_documents,
        student_statuses=student_statuses,
        lang_map=Config.SUPPORTED_LANGUAGES,
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
                    # Build a professional HTML CV
                    contact_parts = []
                    if student.phone:
                        contact_parts.append(student.phone)
                    if student.email:
                        contact_parts.append(student.email)
                    location = ""
                    if student.suburb:
                        location = student.suburb + (f" {student.postcode}" if student.postcode else "")
                        contact_parts.append(location)

                    # Professional summary – expand with detail
                    add_info = sess.additional_info or ""
                    goals = ""
                    traits = ""
                    if add_info:
                        # Extract goals and personal traits from additional_info
                        parts = [p.strip() for p in add_info.replace(". ", ".|").split("|") if p.strip()]
                        for p in parts:
                            if "goal" in p.lower() or "aspir" in p.lower() or "become" in p.lower():
                                goals = p.rstrip(".")
                            else:
                                traits = p.rstrip(".")

                    summary_lines = []
                    summary_lines.append(
                        f"Dedicated and dependable professional with a strong background in "
                        f"the {job_prefs.get('industry', 'hospitality') if isinstance(job_prefs, dict) else 'hospitality'} industry."
                    )
                    if work_exp:
                        total_exp = work_exp[0].get("duration", "")
                        summary_lines.append(
                            f"Brings {total_exp} of hands-on experience as a {work_exp[0].get('title', 'professional')}"
                            + (f", complemented by {work_exp[-1].get('duration', '')} in a {work_exp[-1].get('title', '').lower()} role" if len(work_exp) > 1 else "")
                            + "."
                        )
                    summary_lines.append(
                        f"Fluent {lang_name} speaker with {student.english_level or 'developing'} English, "
                        f"currently enrolled in language studies to strengthen workplace communication."
                    )
                    if traits:
                        summary_lines.append(f"{traits}.")
                    if goals:
                        summary_lines.append(f"Career aspiration: {goals.lower().replace('goal:', '').replace('goal', '').strip()}.")
                    prof_summary = " ".join(summary_lines)

                    # Work experience role descriptions based on title
                    role_descriptions = {
                        "cook": [
                            "Prepared a wide range of dishes to a high standard, ensuring consistent quality and presentation",
                            "Managed food preparation schedules, ingredient ordering, and stock rotation",
                            "Maintained strict food safety and hygiene standards in accordance with local regulations",
                            "Collaborated with kitchen team to develop daily specials and seasonal menus",
                            "Trained junior kitchen staff on preparation techniques and workplace safety procedures",
                        ],
                        "waiter": [
                            "Provided attentive and friendly table service to guests in a fast-paced dining environment",
                            "Accurately took customer orders and communicated dietary requirements to kitchen staff",
                            "Handled point-of-sale transactions, cash handling, and end-of-shift reconciliation",
                            "Maintained a clean and welcoming dining area, setting tables and managing reservations",
                            "Built positive relationships with regular customers, contributing to repeat business",
                        ],
                        "kitchen hand": [
                            "Supported kitchen operations including food preparation, cleaning, and dishwashing",
                            "Ensured all work areas met hygiene and safety requirements at all times",
                            "Assisted chefs with ingredient preparation, portioning, and plating",
                            "Managed stock rotation and proper storage of perishable goods",
                        ],
                        "cleaner": [
                            "Maintained cleanliness across commercial and residential properties to a high standard",
                            "Operated cleaning equipment and handled chemical supplies safely",
                            "Followed detailed cleaning schedules and reported maintenance issues promptly",
                        ],
                    }

                    # Build work experience HTML
                    work_html = ""
                    if work_exp:
                        for job in work_exp:
                            t = job.get("title", "Role")
                            e = job.get("employer", "Employer")
                            d = job.get("duration", "")
                            # Find matching role descriptions
                            descs = []
                            for key, desc_list in role_descriptions.items():
                                if key in t.lower():
                                    descs = desc_list
                                    break
                            if not descs:
                                descs = [
                                    f"Performed duties as {t} to a reliable and professional standard",
                                    "Worked collaboratively within a team to meet daily operational targets",
                                    "Demonstrated punctuality, commitment, and a positive attitude",
                                ]
                            bullets = "".join(f"<li>{d_item}</li>" for d_item in descs)
                            work_html += f"""
                            <div style="margin-bottom: 14px;">
                                <div style="display: flex; justify-content: space-between; align-items: baseline;">
                                    <strong style="font-size: 14px; color: #1a1a1a;">{t}</strong>
                                    <span style="color: #555; font-size: 13px; font-style: italic;">{d}</span>
                                </div>
                                <div style="color: #333; font-size: 13px; margin-bottom: 4px;">{e}</div>
                                <ul style="margin: 4px 0 0 18px; padding: 0; color: #444; font-size: 13px; line-height: 1.6;">
                                    {bullets}
                                </ul>
                            </div>"""

                    # Skills — group into categories
                    skill_categories = {}
                    if skills and isinstance(skills, list):
                        for s in skills:
                            s_lower = str(s).lower()
                            if any(kw in s_lower for kw in ["cook", "food", "dish", "cuisine", "kitchen", "preparation"]):
                                skill_categories.setdefault("Culinary & Food Preparation", []).append(str(s))
                            elif any(kw in s_lower for kw in ["customer", "service", "team", "communication"]):
                                skill_categories.setdefault("Customer Service & Teamwork", []).append(str(s))
                            elif any(kw in s_lower for kw in ["clean", "hygiene", "safety"]):
                                skill_categories.setdefault("Workplace Health & Safety", []).append(str(s))
                            else:
                                skill_categories.setdefault("Professional Skills", []).append(str(s))
                    skills_html = ""
                    for cat, cat_skills in skill_categories.items():
                        pills = " &bull; ".join(cat_skills)
                        skills_html += f'<div style="margin-bottom: 6px;"><strong style="font-size: 13px;">{cat}:</strong> <span style="font-size: 13px; color: #444;">{pills}</span></div>'

                    # Education
                    edu_html = ""
                    if education:
                        for ed in education:
                            inst = ed.get("institution", "")
                            qual = ed.get("qualification", "")
                            yr = ed.get("year", "")
                            edu_html += f"""
                            <div style="margin-bottom: 8px;">
                                <div style="display: flex; justify-content: space-between; align-items: baseline;">
                                    <strong style="font-size: 13px;">{qual}</strong>
                                    <span style="font-size: 13px; color: #555; font-style: italic;">{yr}</span>
                                </div>
                                <div style="font-size: 13px; color: #333;">{inst}</div>
                            </div>"""

                    # Certificates
                    cert_html = ""
                    if certificates:
                        cert_items = "".join(f"<li>{c}</li>" for c in certificates)
                        cert_html = f'<ul style="margin: 4px 0 0 18px; padding: 0; font-size: 13px; color: #444;">{cert_items}</ul>'

                    # Availability
                    avail_items = []
                    if availability:
                        if availability.get("mornings"):
                            avail_items.append("Mornings")
                        if availability.get("afternoons"):
                            avail_items.append("Afternoons")
                        if availability.get("evenings"):
                            avail_items.append("Evenings")
                        if availability.get("weekends"):
                            avail_items.append("Weekends")
                    avail_text = ", ".join(avail_items) if avail_items else "Flexible"

                    cv_html = f"""<div style="font-family: 'Segoe UI', Arial, sans-serif; max-width: 700px; margin: 0 auto; color: #1a1a1a; line-height: 1.5;">
    <!-- Header -->
    <div style="text-align: center; border-bottom: 3px solid #1B4F72; padding-bottom: 16px; margin-bottom: 20px;">
        <h1 style="margin: 0 0 6px 0; font-size: 26px; color: #1B4F72; letter-spacing: 2px;">{name.upper()}</h1>
        <div style="font-size: 14px; color: #555;">{" &nbsp;|&nbsp; ".join(contact_parts)}</div>
    </div>

    <!-- Professional Summary -->
    <div style="margin-bottom: 20px;">
        <h2 style="font-size: 15px; color: #1B4F72; text-transform: uppercase; letter-spacing: 1px; border-bottom: 1px solid #ccc; padding-bottom: 4px; margin: 0 0 8px 0;">Professional Summary</h2>
        <p style="font-size: 13px; color: #333; margin: 0; text-align: justify;">{prof_summary}</p>
    </div>

    <!-- Work Experience -->
    {"" if not work_exp else f'''<div style="margin-bottom: 20px;">
        <h2 style="font-size: 15px; color: #1B4F72; text-transform: uppercase; letter-spacing: 1px; border-bottom: 1px solid #ccc; padding-bottom: 4px; margin: 0 0 10px 0;">Work Experience</h2>
        {work_html}
    </div>'''}

    <!-- Key Skills -->
    {"" if not skills_html else f'''<div style="margin-bottom: 20px;">
        <h2 style="font-size: 15px; color: #1B4F72; text-transform: uppercase; letter-spacing: 1px; border-bottom: 1px solid #ccc; padding-bottom: 4px; margin: 0 0 8px 0;">Key Skills</h2>
        {skills_html}
    </div>'''}

    <!-- Education & Training -->
    {"" if not education else f'''<div style="margin-bottom: 20px;">
        <h2 style="font-size: 15px; color: #1B4F72; text-transform: uppercase; letter-spacing: 1px; border-bottom: 1px solid #ccc; padding-bottom: 4px; margin: 0 0 8px 0;">Education &amp; Training</h2>
        {edu_html}
    </div>'''}

    <!-- Certificates & Licences -->
    {"" if not certificates else f'''<div style="margin-bottom: 20px;">
        <h2 style="font-size: 15px; color: #1B4F72; text-transform: uppercase; letter-spacing: 1px; border-bottom: 1px solid #ccc; padding-bottom: 4px; margin: 0 0 8px 0;">Certificates &amp; Licences</h2>
        {cert_html}
    </div>'''}

    <!-- Languages -->
    <div style="margin-bottom: 20px;">
        <h2 style="font-size: 15px; color: #1B4F72; text-transform: uppercase; letter-spacing: 1px; border-bottom: 1px solid #ccc; padding-bottom: 4px; margin: 0 0 8px 0;">Languages</h2>
        <div style="font-size: 13px; color: #444;">
            <div style="margin-bottom: 4px;"><strong>{lang_name}:</strong> Native speaker</div>
            <div><strong>English:</strong> {student.english_level or 'Basic'} &mdash; currently enrolled in English language programme</div>
        </div>
    </div>

    <!-- Availability & Transport -->
    <div style="margin-bottom: 20px;">
        <h2 style="font-size: 15px; color: #1B4F72; text-transform: uppercase; letter-spacing: 1px; border-bottom: 1px solid #ccc; padding-bottom: 4px; margin: 0 0 8px 0;">Availability &amp; Transport</h2>
        <div style="font-size: 13px; color: #444;">
            <div style="margin-bottom: 4px;"><strong>Available:</strong> {avail_text}</div>
            <div><strong>Transport:</strong> {sess.transport or 'Public transport'}</div>
        </div>
    </div>

    <!-- References -->
    <div style="margin-bottom: 10px;">
        <h2 style="font-size: 15px; color: #1B4F72; text-transform: uppercase; letter-spacing: 1px; border-bottom: 1px solid #ccc; padding-bottom: 4px; margin: 0 0 8px 0;">References</h2>
        <p style="font-size: 13px; color: #444; margin: 0;">Available upon request</p>
    </div>
</div>"""
                    generated["cv"] = cv_html

                elif doc_type == "cover_letter":
                    role = job_title or (job_prefs.get("roles", "").split(",")[0].strip() if isinstance(job_prefs, dict) and job_prefs.get("roles") else "an available position")
                    company = employer or "your organisation"
                    industry = job_prefs.get("industry", "") if isinstance(job_prefs, dict) else ""

                    # Build richer cover letter content
                    exp_para = ""
                    if work_exp:
                        first = work_exp[0]
                        exp_para = (
                            f"In my most recent role as a {first.get('title', 'professional')} at "
                            f"{first.get('employer', 'my previous employer')}, I gained {first.get('duration', 'significant')} "
                            f"of practical experience that has equipped me with a solid foundation in "
                            f"{industry.lower() or 'this field'}."
                        )
                        if len(work_exp) > 1:
                            second = work_exp[-1]
                            exp_para += (
                                f" I have also worked as a {second.get('title', '')} at {second.get('employer', '')}, "
                                f"where I further developed my customer service and teamwork skills."
                            )

                    skills_text = ", ".join(str(s) for s in skills[:5]) if skills else "a strong work ethic"
                    add_info = sess.additional_info or ""
                    goals_text = ""
                    if "goal" in add_info.lower() or "become" in add_info.lower():
                        goals_text = f"I am particularly motivated by my long-term aspiration to advance in the {industry.lower() or 'hospitality'} industry. "

                    avail_items = []
                    if availability:
                        if availability.get("mornings"): avail_items.append("mornings")
                        if availability.get("afternoons"): avail_items.append("afternoons")
                        if availability.get("evenings"): avail_items.append("evenings")
                        if availability.get("weekends"): avail_items.append("weekends")
                    avail_text = ", ".join(avail_items) if avail_items else "flexible hours"

                    cl_html = f"""<div style="font-family: 'Segoe UI', Arial, sans-serif; max-width: 650px; margin: 0 auto; color: #1a1a1a; line-height: 1.7; font-size: 14px;">
    <div style="margin-bottom: 24px;">
        <strong>{name}</strong><br>
        {(student.phone + "<br>") if student.phone else ""}
        {(student.email + "<br>") if student.email else ""}
        {(student.suburb or "") + (" " + student.postcode if student.postcode else "")}
    </div>

    <div style="margin-bottom: 20px;">{today_str}</div>

    <div style="margin-bottom: 20px;">
        <strong>Re: Application for {role}</strong>
    </div>

    <p>Dear Hiring Manager,</p>

    <p>I am writing to express my strong interest in the position of {role} at {company}. As a dedicated and reliable professional with hands-on experience in the {industry.lower() or 'hospitality'} sector, I am confident that I would make a valuable contribution to your team.</p>

    {"<p>" + exp_para + "</p>" if exp_para else ""}

    <p>Among my key strengths, I bring {skills_text}. I am a native {lang_name} speaker with {student.english_level or 'developing'} English language skills, and I am actively enrolled in an English language programme to continue improving my communication abilities.</p>

    <p>{goals_text}I am available to work {avail_text} and can travel by {sess.transport or 'public transport'}, giving me the flexibility to meet the scheduling needs of your business.</p>

    <p>I would welcome the opportunity to discuss how my skills and experience align with the needs of your team. Thank you for taking the time to consider my application. I look forward to hearing from you.</p>

    <p style="margin-top: 30px;">Yours sincerely,</p>
    <p><strong>{name}</strong></p>
</div>"""
                    generated["cover_letter"] = cl_html

                elif doc_type == "summary_internal":
                    work_rows = ""
                    if work_exp:
                        for job in work_exp:
                            work_rows += f'<tr><td style="padding: 4px 8px; font-size: 13px;">{job.get("title", "N/A")}</td><td style="padding: 4px 8px; font-size: 13px;">{job.get("employer", "N/A")}</td><td style="padding: 4px 8px; font-size: 13px;">{job.get("duration", "N/A")}</td></tr>'

                    edu_list = ""
                    if education:
                        items = "".join(f'<li>{ed.get("qualification", "N/A")} at {ed.get("institution", "N/A")} ({ed.get("year", "")})</li>' for ed in education)
                        edu_list = f'<ul style="margin: 4px 0 0 18px; padding: 0; font-size: 13px;">{items}</ul>'

                    skills_text = ", ".join(str(s) for s in skills) if skills else "Not recorded"
                    certs_text = ", ".join(str(c) for c in certificates) if certificates else "None recorded"

                    prefs_html = ""
                    if isinstance(job_prefs, dict):
                        for k, v in job_prefs.items():
                            prefs_html += f'<div style="font-size: 13px; margin-bottom: 2px;"><strong>{k.replace("_", " ").title()}:</strong> {v}</div>'

                    avail_parts = []
                    if availability:
                        avail_parts = [k.title() for k, v in availability.items() if v and k != "notes"]

                    transcript_html = ""
                    if sess.transcript_english:
                        transcript_html = f'''<div style="margin-bottom: 16px;">
                            <h3 style="font-size: 14px; color: #1B4F72; margin: 0 0 6px 0;">Transcript (English)</h3>
                            <div style="background: #f8f9fa; padding: 12px; border-radius: 4px; font-size: 12px; color: #444; white-space: pre-wrap; max-height: 300px; overflow-y: auto;">{sess.transcript_english}</div>
                        </div>'''

                    internal_html = f"""<div style="font-family: 'Segoe UI', Arial, sans-serif; max-width: 700px; margin: 0 auto; color: #1a1a1a; line-height: 1.5;">
    <div style="background: #1B4F72; color: white; padding: 14px 20px; border-radius: 6px 6px 0 0;">
        <h2 style="margin: 0; font-size: 18px;">Internal Meeting Summary</h2>
        <div style="font-size: 13px; opacity: 0.9; margin-top: 4px;">Confidential &mdash; For staff use only</div>
    </div>
    <div style="border: 1px solid #dee2e6; border-top: none; padding: 20px; border-radius: 0 0 6px 6px;">
        <table style="width: 100%; font-size: 13px; margin-bottom: 16px;">
            <tr><td style="padding: 3px 0; width: 140px;"><strong>Student:</strong></td><td>{name} (ID: {student.student_id})</td></tr>
            <tr><td style="padding: 3px 0;"><strong>Date:</strong></td><td>{today_str}</td></tr>
            <tr><td style="padding: 3px 0;"><strong>Session:</strong></td><td>#{sess.session_number}</td></tr>
            <tr><td style="padding: 3px 0;"><strong>Language:</strong></td><td>{lang_name}</td></tr>
            <tr><td style="padding: 3px 0;"><strong>English Level:</strong></td><td>{student.english_level or 'Not assessed'}</td></tr>
        </table>

        {"" if not work_exp else f'''<div style="margin-bottom: 16px;">
            <h3 style="font-size: 14px; color: #1B4F72; margin: 0 0 6px 0;">Work History</h3>
            <table style="width: 100%; border-collapse: collapse;">
                <tr style="background: #f0f0f0;"><th style="padding: 6px 8px; text-align: left; font-size: 13px;">Role</th><th style="padding: 6px 8px; text-align: left; font-size: 13px;">Employer</th><th style="padding: 6px 8px; text-align: left; font-size: 13px;">Duration</th></tr>
                {work_rows}
            </table>
        </div>'''}

        {"" if not education else f'''<div style="margin-bottom: 16px;">
            <h3 style="font-size: 14px; color: #1B4F72; margin: 0 0 6px 0;">Education</h3>
            {edu_list}
        </div>'''}

        <div style="margin-bottom: 16px;">
            <h3 style="font-size: 14px; color: #1B4F72; margin: 0 0 6px 0;">Skills</h3>
            <div style="font-size: 13px;">{skills_text}</div>
        </div>

        <div style="margin-bottom: 16px;">
            <h3 style="font-size: 14px; color: #1B4F72; margin: 0 0 6px 0;">Certificates</h3>
            <div style="font-size: 13px;">{certs_text}</div>
        </div>

        {"" if not prefs_html else f'''<div style="margin-bottom: 16px;">
            <h3 style="font-size: 14px; color: #1B4F72; margin: 0 0 6px 0;">Job Preferences</h3>
            {prefs_html}
        </div>'''}

        <div style="margin-bottom: 16px;">
            <h3 style="font-size: 14px; color: #1B4F72; margin: 0 0 6px 0;">Availability &amp; Transport</h3>
            <div style="font-size: 13px;">Available: {", ".join(avail_parts) if avail_parts else "Not specified"}</div>
            <div style="font-size: 13px;">Transport: {sess.transport or 'Not specified'}</div>
        </div>

        {"" if not sess.additional_info else f'''<div style="margin-bottom: 16px;">
            <h3 style="font-size: 14px; color: #1B4F72; margin: 0 0 6px 0;">Additional Notes</h3>
            <div style="font-size: 13px;">{sess.additional_info}</div>
        </div>'''}

        {transcript_html}

        <div style="font-size: 12px; color: #888; border-top: 1px solid #eee; padding-top: 8px;">Generated: {today_str}</div>
    </div>
</div>"""
                    generated["summary_internal"] = internal_html

                elif doc_type == "summary_student":
                    work_list = ""
                    if work_exp:
                        items = "".join(f'<li>{job.get("title", "")} at {job.get("employer", "")}</li>' for job in work_exp)
                        work_list = f'<ul style="margin: 4px 0 10px 18px; padding: 0; font-size: 14px;">{items}</ul>'

                    skills_text = ", ".join(str(s) for s in skills) if skills else ""
                    edu_list = ""
                    if education:
                        items = "".join(f'<li>{ed.get("qualification", "")} at {ed.get("institution", "")}</li>' for ed in education)
                        edu_list = f'<ul style="margin: 4px 0 10px 18px; padding: 0; font-size: 14px;">{items}</ul>'

                    next_steps = '<ul style="margin: 4px 0 10px 18px; padding: 0; font-size: 14px;">'
                    next_steps += "<li>We will prepare your CV for you</li>"
                    next_steps += "<li>We will help you search for suitable jobs</li>"
                    if job_prefs and isinstance(job_prefs, dict):
                        roles = job_prefs.get("roles", "")
                        if roles:
                            next_steps += f"<li>We will focus on roles such as: {roles}</li>"
                    next_steps += "<li>We will arrange a follow-up meeting to check your progress</li>"
                    next_steps += "</ul>"

                    student_html = f"""<div style="font-family: 'Segoe UI', Arial, sans-serif; max-width: 650px; margin: 0 auto; color: #1a1a1a; line-height: 1.6; font-size: 14px;">
    <div style="background: #27AE60; color: white; padding: 16px 20px; border-radius: 6px 6px 0 0;">
        <h2 style="margin: 0; font-size: 18px;">Your Meeting Summary</h2>
    </div>
    <div style="border: 1px solid #dee2e6; border-top: none; padding: 20px; border-radius: 0 0 6px 6px;">
        <p>Hello <strong>{student.first_name}</strong>!</p>

        <p>Thank you for meeting with us on <strong>{today_str}</strong>. Here is a summary of what we discussed during our conversation.</p>

        {"" if not work_exp else f'''<h3 style="font-size: 15px; color: #27AE60; margin: 16px 0 6px 0;">Your Work Experience</h3>
        {work_list}'''}

        {"" if not skills_text else f'''<h3 style="font-size: 15px; color: #27AE60; margin: 16px 0 6px 0;">Your Skills</h3>
        <p>{skills_text}</p>'''}

        {"" if not education else f'''<h3 style="font-size: 15px; color: #27AE60; margin: 16px 0 6px 0;">Your Education</h3>
        {edu_list}'''}

        <h3 style="font-size: 15px; color: #27AE60; margin: 16px 0 6px 0;">What We Will Do Next</h3>
        {next_steps}

        <div style="background: #f0faf4; border-left: 4px solid #27AE60; padding: 12px 16px; margin-top: 16px; border-radius: 0 4px 4px 0;">
            <strong>Need help?</strong> If you have any questions, please do not hesitate to contact us. We are here to help you!
        </div>

        <div style="font-size: 12px; color: #888; border-top: 1px solid #eee; padding-top: 8px; margin-top: 16px;">Generated: {today_str}</div>
    </div>
</div>"""
                    generated["summary_student"] = student_html

                elif doc_type == "action_items":
                    staff_items = [
                        "Finalise CV and have student review it",
                        "Search for suitable job openings",
                    ]
                    if job_prefs and isinstance(job_prefs, dict):
                        roles = job_prefs.get("roles", "")
                        if roles:
                            staff_items.append(f"Focus job search on: {roles}")
                    staff_items.append("Prepare tailored cover letter template")
                    staff_items.append("Schedule follow-up meeting within 2 weeks")
                    if certificates:
                        staff_items.append("Verify certificates and arrange copies")

                    student_items = [
                        "Review your CV draft when we send it to you",
                        "Gather any missing documents or references",
                    ]
                    if not certificates:
                        student_items.append("Look into relevant certificates or training (e.g., Food Safety)")
                    student_items.append("Continue English language studies")
                    student_items.append("Let us know if your availability or contact details change")

                    staff_checks = "".join(f'<div style="margin-bottom: 6px; font-size: 14px;"><input type="checkbox" style="margin-right: 8px;" disabled> {item}</div>' for item in staff_items)
                    student_checks = "".join(f'<div style="margin-bottom: 6px; font-size: 14px;"><input type="checkbox" style="margin-right: 8px;" disabled> {item}</div>' for item in student_items)

                    action_html = f"""<div style="font-family: 'Segoe UI', Arial, sans-serif; max-width: 650px; margin: 0 auto; color: #1a1a1a; line-height: 1.5;">
    <div style="background: #E67E22; color: white; padding: 14px 20px; border-radius: 6px 6px 0 0;">
        <h2 style="margin: 0; font-size: 18px;">Action Items</h2>
        <div style="font-size: 13px; opacity: 0.9; margin-top: 4px;">{name} &mdash; {today_str}</div>
    </div>
    <div style="border: 1px solid #dee2e6; border-top: none; padding: 20px; border-radius: 0 0 6px 6px;">
        <h3 style="font-size: 15px; color: #E67E22; margin: 0 0 10px 0;">For Staff</h3>
        {staff_checks}

        <h3 style="font-size: 15px; color: #E67E22; margin: 20px 0 10px 0;">For Student</h3>
        {student_checks}

        <div style="font-size: 12px; color: #888; border-top: 1px solid #eee; padding-top: 8px; margin-top: 16px;">Generated: {today_str}</div>
    </div>
</div>"""
                    generated["action_items"] = action_html

            except Exception as doc_err:
                generated[doc_type] = f"Error generating document: {doc_err}"

        # Record which docs were generated
        sess.documents_generated = json.dumps(list(generated.keys()))

        # Create DocumentRecord entries for tracking
        for doc_type_key in generated:
            if doc_type_key.startswith("Error"):
                continue
            # Avoid duplicates if regenerating
            existing = DocumentRecord.query.filter_by(
                student_id=student.id, session_id=sess.id, doc_type=doc_type_key
            ).first()
            if not existing:
                rec = DocumentRecord(
                    student_id=student.id,
                    session_id=sess.id,
                    doc_type=doc_type_key,
                    status="generated",
                )
                db.session.add(rec)

        db.session.commit()

        return jsonify({"success": True, "documents": generated})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# PDF download – converts HTML document content to a printable PDF
# ---------------------------------------------------------------------------

@app.route("/interview/<int:student_id>/download-pdf", methods=["POST"])
def download_pdf(student_id):
    """Convert generated HTML document content to a downloadable PDF."""
    try:
        from io import BytesIO
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.colors import HexColor
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
            HRFlowable, KeepTogether
        )

        data = request.get_json()
        doc_type = data.get("doc_type", "cv")
        student = Student.query.get_or_404(student_id)
        session_id = data.get("session_id")
        sess = InterviewSession.query.get(session_id) if session_id else None

        if not sess:
            return jsonify({"error": "Session not found"}), 404

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
        job_title = data.get("job_title", "")
        employer = data.get("employer", "")

        # Colour palette
        BLUE = HexColor("#1B4F72")
        LIGHT_BLUE = HexColor("#2E86C1")
        GREEN = HexColor("#27AE60")
        ORANGE = HexColor("#E67E22")
        GREY = HexColor("#555555")
        DARK = HexColor("#1a1a1a")

        # Custom styles
        styles = getSampleStyleSheet()
        styles.add(ParagraphStyle(
            "DocName", parent=styles["Title"], fontSize=20,
            textColor=BLUE, alignment=1, spaceAfter=4, spaceBefore=0
        ))
        styles.add(ParagraphStyle(
            "ContactLine", parent=styles["Normal"], fontSize=10,
            textColor=GREY, alignment=1, spaceAfter=8
        ))
        styles.add(ParagraphStyle(
            "SectionHead", parent=styles["Heading2"], fontSize=12,
            textColor=BLUE, spaceBefore=14, spaceAfter=6,
            borderWidth=0, leading=16
        ))
        styles.add(ParagraphStyle(
            "BodyText2", parent=styles["Normal"], fontSize=10,
            textColor=DARK, leading=14, spaceAfter=4
        ))
        styles.add(ParagraphStyle(
            "JobTitle", parent=styles["Normal"], fontSize=11,
            textColor=DARK, leading=14, fontName="Helvetica-Bold"
        ))
        styles.add(ParagraphStyle(
            "JobMeta", parent=styles["Normal"], fontSize=10,
            textColor=GREY, leading=12, spaceAfter=2
        ))
        styles.add(ParagraphStyle(
            "Bullet", parent=styles["Normal"], fontSize=10,
            textColor=DARK, leading=13, leftIndent=16,
            bulletIndent=6, spaceAfter=2
        ))
        styles.add(ParagraphStyle(
            "SmallGrey", parent=styles["Normal"], fontSize=8,
            textColor=GREY, spaceBefore=16
        ))

        buf = BytesIO()
        doc = SimpleDocTemplate(
            buf, pagesize=A4,
            leftMargin=22 * mm, rightMargin=22 * mm,
            topMargin=20 * mm, bottomMargin=20 * mm
        )
        story = []

        # Role descriptions for CV
        role_descriptions = {
            "cook": [
                "Prepared a wide range of dishes to a high standard, ensuring consistent quality and presentation",
                "Managed food preparation schedules, ingredient ordering, and stock rotation",
                "Maintained strict food safety and hygiene standards in accordance with local regulations",
                "Collaborated with kitchen team to develop daily specials and seasonal menus",
                "Trained junior kitchen staff on preparation techniques and workplace safety procedures",
            ],
            "waiter": [
                "Provided attentive and friendly table service to guests in a fast-paced dining environment",
                "Accurately took customer orders and communicated dietary requirements to kitchen staff",
                "Handled point-of-sale transactions, cash handling, and end-of-shift reconciliation",
                "Maintained a clean and welcoming dining area, setting tables and managing reservations",
                "Built positive relationships with regular customers, contributing to repeat business",
            ],
            "kitchen hand": [
                "Supported kitchen operations including food preparation, cleaning, and dishwashing",
                "Ensured all work areas met hygiene and safety requirements at all times",
                "Assisted chefs with ingredient preparation, portioning, and plating",
                "Managed stock rotation and proper storage of perishable goods",
            ],
            "cleaner": [
                "Maintained cleanliness across commercial and residential properties to a high standard",
                "Operated cleaning equipment and handled chemical supplies safely",
                "Followed detailed cleaning schedules and reported maintenance issues promptly",
            ],
        }

        if doc_type == "cv":
            # Header
            story.append(Paragraph(name.upper(), styles["DocName"]))
            contact_parts = []
            if student.phone:
                contact_parts.append(student.phone)
            if student.email:
                contact_parts.append(student.email)
            location = ""
            if student.suburb:
                location = student.suburb + (f" {student.postcode}" if student.postcode else "")
                contact_parts.append(location)
            if contact_parts:
                story.append(Paragraph(" &bull; ".join(contact_parts), styles["ContactLine"]))
            story.append(HRFlowable(width="100%", thickness=2, color=BLUE, spaceAfter=10))

            # Professional Summary
            add_info = sess.additional_info or ""
            goals = ""
            traits = ""
            if add_info:
                parts = [p.strip() for p in add_info.replace(". ", ".|").split("|") if p.strip()]
                for p in parts:
                    if any(kw in p.lower() for kw in ["goal", "aspir", "become"]):
                        goals = p.rstrip(".")
                    else:
                        traits = p.rstrip(".")

            industry = job_prefs.get("industry", "hospitality") if isinstance(job_prefs, dict) else "hospitality"
            summary_parts = [
                f"Dedicated and dependable professional with a strong background in the {industry} industry."
            ]
            if work_exp:
                summary_parts.append(
                    f"Brings {work_exp[0].get('duration', '')} of hands-on experience as a "
                    f"{work_exp[0].get('title', 'professional')}"
                    + (f", complemented by {work_exp[-1].get('duration', '')} in a "
                       f"{work_exp[-1].get('title', '').lower()} role" if len(work_exp) > 1 else "")
                    + "."
                )
            summary_parts.append(
                f"Fluent {lang_name} speaker with {student.english_level or 'developing'} English, "
                f"currently enrolled in language studies to strengthen workplace communication."
            )
            if traits:
                summary_parts.append(f"{traits}.")
            if goals:
                summary_parts.append(f"Career aspiration: {goals.lower().replace('goal:', '').replace('goal', '').strip()}.")

            story.append(Paragraph("PROFESSIONAL SUMMARY", styles["SectionHead"]))
            story.append(HRFlowable(width="100%", thickness=0.5, color=HexColor("#cccccc"), spaceAfter=6))
            story.append(Paragraph(" ".join(summary_parts), styles["BodyText2"]))

            # Work Experience
            if work_exp:
                story.append(Paragraph("WORK EXPERIENCE", styles["SectionHead"]))
                story.append(HRFlowable(width="100%", thickness=0.5, color=HexColor("#cccccc"), spaceAfter=6))
                for job in work_exp:
                    t = job.get("title", "Role")
                    e = job.get("employer", "Employer")
                    d = job.get("duration", "")
                    story.append(Paragraph(f"{t}", styles["JobTitle"]))
                    story.append(Paragraph(f"{e} &mdash; {d}", styles["JobMeta"]))
                    descs = []
                    for key, desc_list in role_descriptions.items():
                        if key in t.lower():
                            descs = desc_list
                            break
                    if not descs:
                        descs = [
                            f"Performed duties as {t} to a reliable and professional standard",
                            "Worked collaboratively within a team to meet daily operational targets",
                            "Demonstrated punctuality, commitment, and a positive attitude",
                        ]
                    for desc in descs:
                        story.append(Paragraph(f"&bull; {desc}", styles["Bullet"]))
                    story.append(Spacer(1, 6))

            # Key Skills
            if skills:
                story.append(Paragraph("KEY SKILLS", styles["SectionHead"]))
                story.append(HRFlowable(width="100%", thickness=0.5, color=HexColor("#cccccc"), spaceAfter=6))
                skill_categories = {}
                for s in skills:
                    s_lower = str(s).lower()
                    if any(kw in s_lower for kw in ["cook", "food", "dish", "cuisine", "kitchen", "preparation"]):
                        skill_categories.setdefault("Culinary & Food Preparation", []).append(str(s))
                    elif any(kw in s_lower for kw in ["customer", "service", "team", "communication"]):
                        skill_categories.setdefault("Customer Service & Teamwork", []).append(str(s))
                    elif any(kw in s_lower for kw in ["clean", "hygiene", "safety"]):
                        skill_categories.setdefault("Workplace Health & Safety", []).append(str(s))
                    else:
                        skill_categories.setdefault("Professional Skills", []).append(str(s))
                for cat, cat_skills in skill_categories.items():
                    story.append(Paragraph(
                        f"<b>{cat}:</b> {' &bull; '.join(cat_skills)}", styles["BodyText2"]
                    ))

            # Education
            if education:
                story.append(Paragraph("EDUCATION &amp; TRAINING", styles["SectionHead"]))
                story.append(HRFlowable(width="100%", thickness=0.5, color=HexColor("#cccccc"), spaceAfter=6))
                for ed in education:
                    story.append(Paragraph(
                        f"<b>{ed.get('qualification', '')}</b> &mdash; {ed.get('institution', '')} ({ed.get('year', '')})",
                        styles["BodyText2"]
                    ))

            # Certificates
            if certificates:
                story.append(Paragraph("CERTIFICATES &amp; LICENCES", styles["SectionHead"]))
                story.append(HRFlowable(width="100%", thickness=0.5, color=HexColor("#cccccc"), spaceAfter=6))
                for cert in certificates:
                    story.append(Paragraph(f"&bull; {cert}", styles["Bullet"]))

            # Languages
            story.append(Paragraph("LANGUAGES", styles["SectionHead"]))
            story.append(HRFlowable(width="100%", thickness=0.5, color=HexColor("#cccccc"), spaceAfter=6))
            story.append(Paragraph(f"<b>{lang_name}:</b> Native speaker", styles["BodyText2"]))
            story.append(Paragraph(
                f"<b>English:</b> {student.english_level or 'Basic'} &mdash; currently enrolled in English language programme",
                styles["BodyText2"]
            ))

            # Availability
            avail_items = []
            if availability:
                if availability.get("mornings"): avail_items.append("Mornings")
                if availability.get("afternoons"): avail_items.append("Afternoons")
                if availability.get("evenings"): avail_items.append("Evenings")
                if availability.get("weekends"): avail_items.append("Weekends")
            story.append(Paragraph("AVAILABILITY &amp; TRANSPORT", styles["SectionHead"]))
            story.append(HRFlowable(width="100%", thickness=0.5, color=HexColor("#cccccc"), spaceAfter=6))
            story.append(Paragraph(
                f"<b>Available:</b> {', '.join(avail_items) if avail_items else 'Flexible'}",
                styles["BodyText2"]
            ))
            story.append(Paragraph(
                f"<b>Transport:</b> {sess.transport or 'Public transport'}",
                styles["BodyText2"]
            ))

            # References
            story.append(Paragraph("REFERENCES", styles["SectionHead"]))
            story.append(HRFlowable(width="100%", thickness=0.5, color=HexColor("#cccccc"), spaceAfter=6))
            story.append(Paragraph("Available upon request", styles["BodyText2"]))

        elif doc_type == "cover_letter":
            role = job_title or (job_prefs.get("roles", "").split(",")[0].strip() if isinstance(job_prefs, dict) and job_prefs.get("roles") else "an available position")
            company = employer or "your organisation"
            industry = job_prefs.get("industry", "") if isinstance(job_prefs, dict) else ""

            # Sender details
            story.append(Paragraph(f"<b>{name}</b>", styles["BodyText2"]))
            if student.phone:
                story.append(Paragraph(student.phone, styles["BodyText2"]))
            if student.email:
                story.append(Paragraph(student.email, styles["BodyText2"]))
            loc = (student.suburb or "") + (" " + student.postcode if student.postcode else "")
            if loc.strip():
                story.append(Paragraph(loc.strip(), styles["BodyText2"]))
            story.append(Spacer(1, 14))
            story.append(Paragraph(today_str, styles["BodyText2"]))
            story.append(Spacer(1, 14))
            story.append(Paragraph(f"<b>Re: Application for {role}</b>", styles["BodyText2"]))
            story.append(Spacer(1, 10))
            story.append(Paragraph("Dear Hiring Manager,", styles["BodyText2"]))
            story.append(Spacer(1, 8))

            story.append(Paragraph(
                f"I am writing to express my strong interest in the position of {role} at {company}. "
                f"As a dedicated and reliable professional with hands-on experience in the "
                f"{industry.lower() or 'hospitality'} sector, I am confident that I would make "
                f"a valuable contribution to your team.",
                styles["BodyText2"]
            ))
            story.append(Spacer(1, 6))

            if work_exp:
                first = work_exp[0]
                exp_text = (
                    f"In my most recent role as a {first.get('title', 'professional')} at "
                    f"{first.get('employer', 'my previous employer')}, I gained "
                    f"{first.get('duration', 'significant')} of practical experience."
                )
                if len(work_exp) > 1:
                    second = work_exp[-1]
                    exp_text += (
                        f" I have also worked as a {second.get('title', '')} at "
                        f"{second.get('employer', '')}, where I further developed my "
                        f"customer service and teamwork skills."
                    )
                story.append(Paragraph(exp_text, styles["BodyText2"]))
                story.append(Spacer(1, 6))

            skills_text = ", ".join(str(s) for s in skills[:5]) if skills else "a strong work ethic"
            story.append(Paragraph(
                f"Among my key strengths, I bring {skills_text}. I am a native {lang_name} "
                f"speaker with {student.english_level or 'developing'} English language skills, "
                f"and I am actively enrolled in an English language programme.",
                styles["BodyText2"]
            ))
            story.append(Spacer(1, 6))

            avail_items = []
            if availability:
                if availability.get("mornings"): avail_items.append("mornings")
                if availability.get("afternoons"): avail_items.append("afternoons")
                if availability.get("evenings"): avail_items.append("evenings")
                if availability.get("weekends"): avail_items.append("weekends")
            avail_text = ", ".join(avail_items) if avail_items else "flexible hours"
            story.append(Paragraph(
                f"I am available to work {avail_text} and can travel by "
                f"{sess.transport or 'public transport'}.",
                styles["BodyText2"]
            ))
            story.append(Spacer(1, 6))
            story.append(Paragraph(
                "I would welcome the opportunity to discuss how my skills and experience "
                "align with the needs of your team. Thank you for taking the time to consider "
                "my application. I look forward to hearing from you.",
                styles["BodyText2"]
            ))
            story.append(Spacer(1, 20))
            story.append(Paragraph("Yours sincerely,", styles["BodyText2"]))
            story.append(Spacer(1, 10))
            story.append(Paragraph(f"<b>{name}</b>", styles["BodyText2"]))

        elif doc_type == "summary_internal":
            story.append(Paragraph("Internal Meeting Summary", styles["DocName"]))
            story.append(Paragraph("Confidential &mdash; For staff use only", styles["ContactLine"]))
            story.append(HRFlowable(width="100%", thickness=2, color=BLUE, spaceAfter=10))

            info_data = [
                ["Student:", f"{name} (ID: {student.student_id})"],
                ["Date:", today_str],
                ["Session:", f"#{sess.session_number}"],
                ["Language:", lang_name],
                ["English Level:", student.english_level or "Not assessed"],
            ]
            t = Table(info_data, colWidths=[90, 350])
            t.setStyle(TableStyle([
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]))
            story.append(t)
            story.append(Spacer(1, 10))

            if work_exp:
                story.append(Paragraph("Work History", styles["SectionHead"]))
                story.append(HRFlowable(width="100%", thickness=0.5, color=HexColor("#cccccc"), spaceAfter=6))
                for job in work_exp:
                    story.append(Paragraph(
                        f"&bull; {job.get('title', 'N/A')} at {job.get('employer', 'N/A')} ({job.get('duration', 'N/A')})",
                        styles["Bullet"]
                    ))

            if education:
                story.append(Paragraph("Education", styles["SectionHead"]))
                story.append(HRFlowable(width="100%", thickness=0.5, color=HexColor("#cccccc"), spaceAfter=6))
                for ed in education:
                    story.append(Paragraph(
                        f"&bull; {ed.get('qualification', 'N/A')} at {ed.get('institution', 'N/A')} ({ed.get('year', '')})",
                        styles["Bullet"]
                    ))

            story.append(Paragraph("Skills", styles["SectionHead"]))
            story.append(HRFlowable(width="100%", thickness=0.5, color=HexColor("#cccccc"), spaceAfter=6))
            story.append(Paragraph(", ".join(str(s) for s in skills) if skills else "Not recorded", styles["BodyText2"]))

            if certificates:
                story.append(Paragraph("Certificates", styles["SectionHead"]))
                story.append(HRFlowable(width="100%", thickness=0.5, color=HexColor("#cccccc"), spaceAfter=6))
                story.append(Paragraph(", ".join(str(c) for c in certificates), styles["BodyText2"]))

            if sess.additional_info:
                story.append(Paragraph("Additional Notes", styles["SectionHead"]))
                story.append(HRFlowable(width="100%", thickness=0.5, color=HexColor("#cccccc"), spaceAfter=6))
                story.append(Paragraph(sess.additional_info, styles["BodyText2"]))

            story.append(Paragraph(f"Generated: {today_str}", styles["SmallGrey"]))

        elif doc_type == "summary_student":
            story.append(Paragraph("Your Meeting Summary", styles["DocName"]))
            story.append(HRFlowable(width="100%", thickness=2, color=GREEN, spaceAfter=10))
            story.append(Paragraph(f"Hello <b>{student.first_name}</b>!", styles["BodyText2"]))
            story.append(Spacer(1, 6))
            story.append(Paragraph(
                f"Thank you for meeting with us on <b>{today_str}</b>. "
                "Here is a summary of what we discussed.",
                styles["BodyText2"]
            ))

            if work_exp:
                story.append(Paragraph("Your Work Experience", styles["SectionHead"]))
                for job in work_exp:
                    story.append(Paragraph(
                        f"&bull; {job.get('title', '')} at {job.get('employer', '')}",
                        styles["Bullet"]
                    ))

            if skills:
                story.append(Paragraph("Your Skills", styles["SectionHead"]))
                story.append(Paragraph(", ".join(str(s) for s in skills), styles["BodyText2"]))

            if education:
                story.append(Paragraph("Your Education", styles["SectionHead"]))
                for ed in education:
                    story.append(Paragraph(
                        f"&bull; {ed.get('qualification', '')} at {ed.get('institution', '')}",
                        styles["Bullet"]
                    ))

            story.append(Paragraph("What We Will Do Next", styles["SectionHead"]))
            next_items = [
                "We will prepare your CV for you",
                "We will help you search for suitable jobs",
                "We will arrange a follow-up meeting",
            ]
            if job_prefs and isinstance(job_prefs, dict) and job_prefs.get("roles"):
                next_items.append(f"We will focus on roles such as: {job_prefs['roles']}")
            for item in next_items:
                story.append(Paragraph(f"&bull; {item}", styles["Bullet"]))

            story.append(Spacer(1, 10))
            story.append(Paragraph(
                "<b>Need help?</b> If you have any questions, please do not hesitate to contact us. "
                "We are here to help you!",
                styles["BodyText2"]
            ))
            story.append(Paragraph(f"Generated: {today_str}", styles["SmallGrey"]))

        elif doc_type == "action_items":
            story.append(Paragraph("Action Items", styles["DocName"]))
            story.append(Paragraph(f"{name} &mdash; {today_str}", styles["ContactLine"]))
            story.append(HRFlowable(width="100%", thickness=2, color=ORANGE, spaceAfter=10))

            story.append(Paragraph("FOR STAFF", styles["SectionHead"]))
            staff_items = [
                "Finalise CV and have student review it",
                "Search for suitable job openings",
            ]
            if job_prefs and isinstance(job_prefs, dict) and job_prefs.get("roles"):
                staff_items.append(f"Focus job search on: {job_prefs['roles']}")
            staff_items += ["Prepare tailored cover letter template", "Schedule follow-up meeting within 2 weeks"]
            for item in staff_items:
                story.append(Paragraph(f"&#9744; {item}", styles["Bullet"]))

            story.append(Spacer(1, 10))
            story.append(Paragraph("FOR STUDENT", styles["SectionHead"]))
            student_items = [
                "Review your CV draft when we send it to you",
                "Gather any missing documents or references",
            ]
            if not certificates:
                student_items.append("Look into relevant certificates or training (e.g., Food Safety)")
            student_items += ["Continue English language studies", "Let us know if your availability changes"]
            for item in student_items:
                story.append(Paragraph(f"&#9744; {item}", styles["Bullet"]))

            story.append(Paragraph(f"Generated: {today_str}", styles["SmallGrey"]))

        # Build PDF
        doc.build(story)
        buf.seek(0)

        doc_names = {
            "cv": "Curriculum_Vitae",
            "cover_letter": "Cover_Letter",
            "summary_internal": "Internal_Summary",
            "summary_student": "Student_Summary",
            "action_items": "Action_Items",
        }
        filename = f"{doc_names.get(doc_type, doc_type)}_{student.student_id}.pdf"

        return send_file(
            buf, mimetype="application/pdf",
            as_attachment=True, download_name=filename
        )

    except ImportError:
        return jsonify({"error": "PDF generation requires reportlab. Install with: pip install reportlab"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Document tracking & status updates
# ---------------------------------------------------------------------------

@app.route("/api/documents/<int:doc_id>/status", methods=["POST"])
def update_document_status(doc_id):
    """Update the status of a tracked document."""
    try:
        rec = DocumentRecord.query.get_or_404(doc_id)
        data = request.get_json()
        new_status = data.get("status")
        valid = list(DocumentRecord.STATUS_LABELS.keys())
        if new_status not in valid:
            return jsonify({"error": f"Invalid status. Must be one of: {valid}"}), 400

        rec.status = new_status
        if new_status == "shared_with_student":
            rec.shared_date = date.today()
        elif new_status == "submitted":
            rec.submitted_date = date.today()
            rec.submitted_to = data.get("submitted_to", "")
        if data.get("notes"):
            rec.notes = data["notes"]

        db.session.commit()
        return jsonify({"success": True, "document": rec.to_dict()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/documents", methods=["GET"])
def api_list_documents():
    """List all document records, optionally filtered by student."""
    student_id = request.args.get("student_id", type=int)
    query = DocumentRecord.query
    if student_id:
        query = query.filter_by(student_id=student_id)
    docs = query.order_by(DocumentRecord.created_at.desc()).limit(50).all()
    return jsonify({"documents": [d.to_dict() for d in docs]})


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

    # Build language lookup (both codes and full names) for searching
    lang_matches = []
    q_lower = q.lower()
    for code, name in Config.SUPPORTED_LANGUAGES.items():
        if q_lower in name.lower() or q_lower in code.lower():
            lang_matches.append(code)

    filters = [
        Student.first_name.ilike(f"%{q}%"),
        Student.surname.ilike(f"%{q}%"),
        Student.student_id.ilike(f"%{q}%"),
        Student.preferred_language.ilike(f"%{q}%"),
    ]
    # Also match by language name → code
    for code in lang_matches:
        filters.append(Student.preferred_language == code)

    students = Student.query.filter(db.or_(*filters)).limit(10).all()

    results = []
    for s in students:
        lang = Config.SUPPORTED_LANGUAGES.get(s.preferred_language, s.preferred_language)
        doc_count = DocumentRecord.query.filter_by(student_id=s.id).count()
        session_count = len(s.sessions)
        # Determine status
        if doc_count > 0:
            latest_doc = DocumentRecord.query.filter_by(student_id=s.id).order_by(
                DocumentRecord.updated_at.desc()).first()
            status = latest_doc.status_label if latest_doc else "Generated"
        elif session_count > 0:
            status = "Interview done"
        else:
            status = "Registered"
        results.append({
            "id": s.id, "student_id": s.student_id,
            "name": s.display_name, "language": lang,
            "status": status, "doc_count": doc_count,
        })

    return jsonify({"results": results})


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
