"""
Database models for the Student Interaction Register.
Uses SQLite via Flask-SQLAlchemy.
"""
from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Student(db.Model):
    """A student record."""
    __tablename__ = "students"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.String(20), unique=True, nullable=False)  # e.g., "2026001"
    first_name = db.Column(db.String(100), nullable=False)
    surname = db.Column(db.String(100), nullable=False)
    date_of_birth = db.Column(db.String(20), nullable=True)
    suburb = db.Column(db.String(100), nullable=True)
    postcode = db.Column(db.String(10), nullable=True)
    phone = db.Column(db.String(30), nullable=True)
    email = db.Column(db.String(200), nullable=True)
    preferred_language = db.Column(db.String(10), nullable=False, default="en")
    other_languages = db.Column(db.Text, nullable=True)  # comma-separated
    english_level = db.Column(db.String(30), nullable=True)  # basic/conversational/comfortable/fluent
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    sessions = db.relationship("InterviewSession", backref="student", lazy=True,
                               order_by="InterviewSession.created_at.desc()")

    @property
    def folder_name(self):
        """Generate the standard folder name: SURNAME_FirstName_ID"""
        surname = self.surname.upper().replace(" ", "_")
        first = self.first_name.replace(" ", "_")
        return f"{surname}_{first}_{self.student_id}"

    @property
    def display_name(self):
        return f"{self.first_name} {self.surname}"

    @property
    def session_count(self):
        return len(self.sessions)

    def to_dict(self):
        return {
            "id": self.id,
            "student_id": self.student_id,
            "first_name": self.first_name,
            "surname": self.surname,
            "display_name": self.display_name,
            "date_of_birth": self.date_of_birth,
            "suburb": self.suburb,
            "postcode": self.postcode,
            "phone": self.phone,
            "email": self.email,
            "preferred_language": self.preferred_language,
            "other_languages": self.other_languages,
            "english_level": self.english_level,
            "notes": self.notes,
            "folder_name": self.folder_name,
            "session_count": self.session_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class InterviewSession(db.Model):
    """A single interview session with a student."""
    __tablename__ = "interview_sessions"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    session_number = db.Column(db.Integer, nullable=False)
    date = db.Column(db.Date, default=lambda: datetime.now(timezone.utc).date())
    duration_minutes = db.Column(db.Integer, nullable=True)
    interviewer_name = db.Column(db.String(100), nullable=True)
    transcript_original = db.Column(db.Text, nullable=True)  # in student's language
    transcript_english = db.Column(db.Text, nullable=True)
    summary_internal = db.Column(db.Text, nullable=True)  # detailed, for staff
    summary_student = db.Column(db.Text, nullable=True)  # friendly, for student
    action_items = db.Column(db.Text, nullable=True)  # JSON list
    documents_generated = db.Column(db.Text, nullable=True)  # JSON list of filenames
    status = db.Column(db.String(20), default="in_progress")  # in_progress, completed
    sensitive_notes = db.Column(db.Text, nullable=True)  # flagged sensitive content
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Work experience, education, skills gathered during interview
    work_experience = db.Column(db.Text, nullable=True)  # JSON
    education = db.Column(db.Text, nullable=True)  # JSON
    skills = db.Column(db.Text, nullable=True)  # JSON
    job_preferences = db.Column(db.Text, nullable=True)  # JSON
    certificates = db.Column(db.Text, nullable=True)  # JSON list
    availability = db.Column(db.Text, nullable=True)  # JSON
    transport = db.Column(db.String(200), nullable=True)
    additional_info = db.Column(db.Text, nullable=True)

    @property
    def folder_name(self):
        """Generate session folder name: YYYY-MM-DD_Session_NN"""
        date_str = self.date.strftime("%Y-%m-%d") if self.date else "unknown"
        return f"{date_str}_Session_{self.session_number:02d}"

    def to_dict(self):
        return {
            "id": self.id,
            "session_number": self.session_number,
            "date": self.date.isoformat() if self.date else None,
            "duration_minutes": self.duration_minutes,
            "interviewer_name": self.interviewer_name,
            "status": self.status,
            "folder_name": self.folder_name,
            "has_transcript": bool(self.transcript_english),
            "documents_generated": self.documents_generated,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class DocumentRecord(db.Model):
    """Tracks individual generated documents and their lifecycle status."""
    __tablename__ = "document_records"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    session_id = db.Column(db.Integer, db.ForeignKey("interview_sessions.id"), nullable=False)
    doc_type = db.Column(db.String(50), nullable=False)  # cv, cover_letter, summary_internal, etc.
    status = db.Column(db.String(30), default="generated")
    # Statuses: generated, reviewed, shared_with_student, submitted, archived
    shared_date = db.Column(db.Date, nullable=True)
    submitted_date = db.Column(db.Date, nullable=True)
    submitted_to = db.Column(db.String(200), nullable=True)  # employer name
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    student = db.relationship("Student", backref=db.backref("documents", lazy=True,
                              order_by="DocumentRecord.created_at.desc()"))
    session = db.relationship("InterviewSession", backref=db.backref("document_records", lazy=True))

    DOC_TYPE_NAMES = {
        "cv": "Curriculum Vitae",
        "cover_letter": "Cover Letter",
        "summary_internal": "Internal Summary",
        "summary_student": "Student Summary",
        "action_items": "Action Items",
    }

    STATUS_LABELS = {
        "generated": "Generated",
        "reviewed": "Reviewed",
        "shared_with_student": "Shared with Student",
        "submitted": "Submitted to Employer",
        "archived": "Archived",
    }

    @property
    def doc_type_name(self):
        return self.DOC_TYPE_NAMES.get(self.doc_type, self.doc_type)

    @property
    def status_label(self):
        return self.STATUS_LABELS.get(self.status, self.status)

    def to_dict(self):
        return {
            "id": self.id,
            "student_id": self.student_id,
            "session_id": self.session_id,
            "doc_type": self.doc_type,
            "doc_type_name": self.doc_type_name,
            "status": self.status,
            "status_label": self.status_label,
            "shared_date": self.shared_date.isoformat() if self.shared_date else None,
            "submitted_date": self.submitted_date.isoformat() if self.submitted_date else None,
            "submitted_to": self.submitted_to,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


def generate_student_id():
    """Generate the next sequential student ID like 2026001, 2026002..."""
    year = datetime.now().year
    prefix = str(year)
    last = Student.query.filter(
        Student.student_id.like(f"{prefix}%")
    ).order_by(Student.student_id.desc()).first()

    if last:
        last_num = int(last.student_id[4:])
        return f"{prefix}{last_num + 1:03d}"
    return f"{prefix}001"
