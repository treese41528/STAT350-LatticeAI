# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Flask-based GenAI chat application (GenAI Studio) for educational use at Purdue University. It provides a web interface for students to interact with LLMs through the Purdue GenAI API. The application supports persistent conversation storage, file uploads (PDF, CSV, Excel), and multi-user isolation.

## Architecture

### Backend (Flask)
- **Main application**: `genaiStudio_app_database.py` - SQLAlchemy-backed version with persistent storage
- **Database**: SQLite (default) or PostgreSQL for storing conversations and messages
- **API Integration**: Connects to Purdue GenAI API (`genai.rcac.purdue.edu`) using bearer token authentication
- **Session management**: Flask sessions with SQLAlchemy for user isolation

### Frontend
- **Template**: `templates/index.html` - Single-page chat interface
- **JavaScript**: Embedded in HTML, handles chat UI, message rendering, and file uploads
- **Styling**: CSS in HTML with support for Markdown, LaTeX, and code highlighting

### Database Schema
- **Conversation table**: Stores conversation metadata (id, user_id, timestamps, title)
- **Message table**: Stores individual messages (conversation_id, role, content, timestamps)
- **Relationships**: One-to-many (Conversation → Messages) with cascade delete

### File Processing
- **pdf_processor.py**: Multi-library PDF text extraction (PyMuPDF → pdfplumber → PyPDF2 fallback)
- **Supported formats**: TXT, PDF, CSV, XLSX, JSON, Python, Markdown
- **Upload handling**: Temporary file processing with secure filenames and cleanup

## Common Development Commands

### Running the Application
```bash
# Development server
python3 genaiStudio_app_database.py

# Production server (recommended)
gunicorn -w 4 -b 0.0.0.0:5000 --timeout 120 genaiStudio_app_database:application
```

### Database Management
```bash
# Initialize database (creates tables)
flask --app genaiStudio_app_database init-db

# View database statistics
flask --app genaiStudio_app_database db-stats

# Cleanup old conversations
flask --app genaiStudio_app_database cleanup-db
```

### Testing
```bash
# Run standalone test app (no API key required)
python3 test_app_standalone.py

# Test API health
curl http://localhost:5000/health

# Test chat endpoint
curl -X POST http://localhost:5000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello", "conversation_id": null}'
```

### Installation
```bash
# Core dependencies
pip3 install -r requirements.txt

# Enhanced dependencies (includes all PDF libraries)
pip3 install -r requirements_enhanced.txt
```

## Configuration

Configuration is loaded from `config.yaml` or environment variables:

### Required Environment Variables
- `GENAI_API_KEY`: Bearer token for Purdue GenAI API (required for production)
- `SECRET_KEY`: Flask session secret (optional, auto-generated if not set)

### Optional Environment Variables
- `CONFIG_FILE`: Path to config YAML (default: `config.yaml`)
- `FLASK_DEBUG`: Enable debug mode (default: `False`)
- `PORT`: Server port (default: `5000`)

### Key Configuration Sections
- **genai**: API URL, model name, temperature, timeout, max_tokens
- **database**: Type (sqlite/postgresql), path, retention policy
- **file_upload**: Enabled, max size, allowed extensions
- **security**: Rate limiting, CORS, session timeout
- **features**: LaTeX rendering, Markdown, code highlighting

## API Endpoints

### Chat Operations
- `POST /chat` - Send message, supports JSON or multipart/form-data (for files)
- `GET /conversations` - List user conversations (paginated)
- `GET /conversations/<id>` - Get specific conversation with messages
- `DELETE /conversations/<id>` - Delete conversation
- `GET /conversations/<id>/export` - Export conversation as JSON

### Utility Endpoints
- `GET /` - Main chat interface
- `GET /health` - Application and API health check
- `GET /config-info` - Public configuration info
- `GET /stats` - Usage statistics
- `POST /clear-session` - Clear user session

## Key Implementation Details

### Conversation Flow
1. User sends message via `/chat` endpoint
2. Get or create conversation (by conversation_id or create new)
3. Save user message to database
4. Retrieve recent messages (up to `memory_per_conversation` limit)
5. Send to GenAI API
6. Save assistant response to database
7. Update conversation timestamp and return response

### User Isolation
- Each request gets a unique `user_id` (from session or IP address)
- Conversations are filtered by `user_id`
- Session-based persistence across browser sessions

### Error Handling
- Cookie overflow fixed by storing conversations in database (not sessions)
- JSON parse errors handled with proper error responses
- Rate limiting prevents abuse
- File size limits enforced
- Automatic retry logic for API requests

### Data Retention
- Old conversations auto-deleted after `conversation_retention_days` (default: 90 days)
- Cleanup runs probabilistically on 1% of requests
- Manual cleanup available via CLI command

## File Structure

### Core Application Files
- `genaiStudio_app_database.py` - Main database-backed Flask app
- `pdf_processor.py` - PDF text extraction utilities
- `user_id_upgrade.py` - User ID management and migration
- `test_app_standalone.py` - Standalone test app with mock responses

### Frontend Files
- `templates/index.html` - Main chat UI template
- `enhanced_formatContent.js` - JavaScript for image rendering
- `enhanced_image_styles.css` - Styles for image display
- `javascript_database_updates.js` - Frontend database integration code

### Documentation
- `README.md` - Project overview and quick start
- `FILE_INDEX.md` - Complete file inventory
- `COMPLETE_DATABASE_SETUP.md` - Step-by-step deployment guide
- `DATABASE_GUIDE.md` - Database implementation details
- `IMAGE_PDF_FIX_GUIDE.md` - Image and PDF handling
- `MULTI_USER_EXPLAINED.md` - Multi-user architecture details
- `COMPARISON_GUIDE.md` - Solution comparison

### Deployment Scripts
- `deploy_database.sh` - Automated database version deployment
- `quick_local_test.sh` - Local testing setup

## Known Issues and Solutions

### Cookie Overflow Error
**Problem**: Session cookies too large (>4KB) with long conversations
**Solution**: Conversations stored in database instead of session cookies

### JSON Parse Error
**Problem**: Server returning HTML instead of JSON on errors
**Solution**: Proper error handlers return JSON responses with correct content-type

### PDF Reading Failures
**Problem**: Some PDFs fail to extract text
**Solution**: Three-tier fallback: PyMuPDF → pdfplumber → PyPDF2

### Image Display Issues
**Problem**: LLM-generated image URLs not rendering
**Solution**: Enhanced formatContent.js detects and renders image URLs

### Streaming Disabled
**Note**: Streaming is intentionally disabled in this application for stability

## Development Workflow

### Adding New Features
1. Read relevant documentation (DATABASE_GUIDE.md, etc.)
2. Backup current files before modifications
3. Test changes with `test_app_standalone.py` first
4. Update database schema if needed (add migration logic)
5. Test with real API using development server
6. Update documentation if behavior changes

### Debugging
1. Check logs: `tail -f logs/assistant.log`
2. Verify API health: `curl http://localhost:5000/health`
3. Check database: `flask db-stats`
4. Test endpoints with curl
5. Use browser DevTools for frontend issues

### Deployment
1. Backup existing installation
2. Install dependencies: `pip3 install -r requirements_enhanced.txt`
3. Initialize database: `flask init-db`
4. Set environment variables (GENAI_API_KEY)
5. Test locally first
6. Deploy with Gunicorn (not Flask dev server)
7. Monitor logs for errors

## Security Considerations

- Rate limiting enabled by default (30 req/min, 500 req/hour)
- File upload size limits enforced
- Secure filename handling for uploads
- Session timeout after 120 minutes
- CORS configured for allowed origins
- No streaming to prevent response timeout issues
- User isolation via session-based user_ids
- Temporary files cleaned up after processing

## Dependencies

### Core
- Flask 3.0.0 + Flask-CORS, Flask-Limiter, Flask-SQLAlchemy
- SQLAlchemy 2.0.23
- requests 2.31.0 (with retry logic)
- PyYAML 6.0.1
- gunicorn 21.2.0

### File Processing
- PyMuPDF 1.23.8 (best PDF extraction)
- pdfplumber 0.10.3 (fallback)
- PyPDF2 3.0.1 (final fallback)
- pandas 2.1.4 + openpyxl 3.1.2 (CSV/Excel)

### Database
- SQLite (built-in, default)
- psycopg2-binary 2.9.9 (optional, for PostgreSQL)
