# Student Interaction Register

A Flask-based web application designed to help non-English-speaking job seekers in Melbourne create professional CVs through recorded interviews in their preferred language.

## Project Structure

```
carringbush/
├── app.py                          # Main Flask application
├── config.py                       # Configuration settings
├── models.py                       # Database models
├── requirements.txt                # Python dependencies
├── templates/                      # HTML templates
│   ├── base.html                  # Base template with navigation
│   ├── dashboard.html             # Main dashboard view
│   ├── students.html              # Students list and search
│   ├── student_new.html           # New student registration form
│   ├── student_profile.html       # Individual student profile
│   ├── interview.html             # Interview recording page
│   ├── documents.html             # Document generation page
│   ├── 404.html                   # 404 error page
│   └── 500.html                   # 500 error page
├── static/
│   └── css/
│       └── style.css              # Complete stylesheet
└── services/                       # Business logic services
    ├── transcription.py           # Audio transcription
    ├── translation.py             # Text translation
    ├── document_gen.py            # Document generation
    └── file_manager.py            # File handling

```

## Features

### Dashboard (`GET /`)
- Overview of system statistics
- Quick search for students
- List of recent students
- Quick access to new student registration

### Student Management
- **List** (`GET /students`): Browse all students with search and filtering
- **Create** (`POST /students/new`): Register new students with multilingual support
- **Profile** (`GET /students/<id>`): View student details and session history

### Interview Recording (`GET /interview/<id>`)
- Audio recording with MediaRecorder API
- Real-time transcription display
- Side-by-side original language and English translation
- Interview guide with suggested questions
- Session start/stop controls

### Interview API Endpoints
- `POST /interview/<id>/start` — Start new session
- `POST /interview/<id>/upload-audio` — Upload audio chunks
- `POST /interview/<id>/transcribe` — Transcribe audio
- `POST /interview/<id>/translate` — Translate text
- `POST /interview/<id>/save-transcript` — Save completed transcript

### Document Generation
- Generate multiple document types:
  - **CV**: Professional curriculum vitae
  - **Cover Letter**: Customisable with job title/employer
  - **Internal Summary**: Notes for staff
  - **Student Summary**: Summary for the student
  - **Action Items**: Follow-up tasks
- Print all documents
- Download individual documents

### Search & Discovery
- `GET /api/students/search` — API endpoint for student search
- Real-time search results
- Filter by name, ID, or language

## Technical Stack

- **Backend**: Flask (Python web framework)
- **Database**: SQLAlchemy ORM with SQLite
- **Frontend**: HTML, CSS (vanilla), JavaScript
- **Audio**: MediaRecorder API (browser native)
- **Transcription**: Integration with external service
- **Translation**: Integration with external service

## Colour Scheme

- **Primary Dark**: #1B4F72 (dark blue) — Headers, primary accents
- **Primary Mid**: #2E86C1 (medium blue) — Buttons, links
- **Primary Light**: #D6EAF8 (light blue) — Accents, highlights
- **Accent Warm**: #FEF9E7 (cream) — Backgrounds
- **Accent Success**: #27AE60 (green) — Success states
- **Accent Danger**: #E74C3C (red) — Danger/recording states

## Font

System fonts stack (cross-platform support):
- Apple San Francisco (-apple-system)
- Segoe UI (Windows)
- Roboto (Android)
- Fallback to sans-serif

## Design Features

### Responsive Layout
- Mobile-friendly (480px and up)
- Tablet optimised (768px)
- Desktop layouts (1024px+)
- Print-friendly styles

### Accessibility
- Large, clear buttons (staff may not be tech-savvy)
- High contrast text
- Clear form labels
- Semantic HTML structure

### User Experience
- Auto-dismissing flash messages
- Recording indicator (pulsing dot)
- Real-time transcript display
- Interview guide sidebar
- Clear call-to-action buttons

## Configuration

Edit `config.py` to customise:
- Supported languages
- English proficiency levels
- Interview guide topics
- File upload settings
- Database connection

## Running the Application

```bash
# Install dependencies
pip install -r requirements.txt

# Run development server
python app.py

# Access in browser
http://localhost:5000
```

## Database Setup

Initialised automatically on first run:
```python
with app.app_context():
    db.create_all()
```

## File Structure

- Student files organised by ID: `/student_files/<student_id>/`
- Audio chunks: `/<student_id>/sessions/<session_id>/audio/`
- Transcripts: `/<student_id>/sessions/<session_id>/transcript.json`
- Generated documents: `/<student_id>/documents/`

## Browser Support

- Chrome/Edge 60+
- Firefox 55+
- Safari 12+
- Requires microphone permission for recording

## Notes for MacBook Deployment

- Audio recording uses system microphone
- Ensure permissions granted: System Preferences → Security & Privacy → Microphone
- Uses native audio codec (audio/webm)
- Compatible with macOS 10.12+

## Future Enhancements

- Email integration for document delivery
- PDF export for documents
- Video recording option
- Multi-language interview guide
- Advanced document formatting options
- Batch student import
- Session analytics
- Mobile app version
