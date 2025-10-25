# GenAI Studio - STAT 350 Chat Application

![Chat Demo](./static/ChatDemo.png)

A Flask-based AI chat application for Purdue University's STAT 350 course, providing students with an intelligent assistant powered by the Purdue GenAI API with course-specific knowledge.

## Features

- ✅ **AI-Powered Chat** - Real-time responses from gpt-stat350 model with STAT 350 knowledge base
- ✅ **Persistent Conversations** - SQLite database storage with conversation history
- ✅ **File Upload Support** - Upload and analyze PDFs, CSV, Excel, text files
- ✅ **Multi-User Support** - Session-based user isolation
- ✅ **Rich Content** - LaTeX rendering, Markdown support, code highlighting
- ✅ **Conversation Management** - Create, view, delete, and export conversations

## Quick Start

### Prerequisites

- Python 3.8+
- Purdue GenAI API key

### Installation

```bash
# Install dependencies
pip install -r requirements.txt

# Set your API key
export GENAI_API_KEY="your-api-key-here"

# Initialize database
python3 -c "from genaiStudio_app_database import app, db; app.app_context().push(); db.create_all(); print('✅ Database initialized')"

# Run the application
python3 genaiStudio_app_database.py
```

The application will be available at **http://localhost:5000**

### Production Deployment

For production, use Gunicorn:

```bash
gunicorn -w 4 -b 0.0.0.0:5000 --timeout 120 genaiStudio_app_database:application
```

## Architecture

### Backend
- **Framework**: Flask 3.0 with SQLAlchemy
- **Database**: SQLite (default) or PostgreSQL
- **API**: Purdue GenAI API (genai.rcac.purdue.edu)
- **File Processing**: PyPDF2, pandas for PDF/Excel/CSV

### Frontend
- **Template**: Single-page HTML with embedded JavaScript
- **Styling**: CSS with Purdue branding colors
- **Libraries**: KaTeX for LaTeX rendering

### Database Schema

**Conversations Table**
- id (UUID), user_id, created_at, updated_at, title
- Stores conversation metadata

**Messages Table**
- id, conversation_id, role (user/assistant), content, created_at
- Stores individual chat messages

## Usage

### Sending Messages
1. Type your question in the input field
2. Press Enter or click Send
3. View AI response with citations from course materials

### Uploading Files
1. Click the attachment button
2. Select a file (PDF, TXT, CSV, XLSX, JSON, MD, PY)
3. Ask questions about the file content
4. Files are automatically processed and sent to the AI

### Managing Conversations
- Conversations persist across sessions
- Refresh the page to see conversation history
- Each conversation has a unique ID

## API Endpoints

### Chat
- `POST /chat` - Send message (JSON or multipart/form-data)
  - Body: `{conversation_id: null|uuid, message: string, files: optional}`
  - Returns: `{content: string, conversation_id: uuid}`

### Conversations
- `GET /conversations` - List all user conversations
- `GET /conversations/<id>` - Get specific conversation with messages
- `DELETE /conversations/<id>` - Delete conversation
- `GET /conversations/<id>/export` - Export as JSON

### Utility
- `GET /health` - Application health check
- `GET /stats` - Usage statistics
- `POST /clear-session` - Clear user session

## Configuration

The application uses default configuration with these key settings:

```python
genai:
  base_url: https://genai.rcac.purdue.edu
  model: gpt-stat350
  temperature: 0.7
  max_tokens: 2000

database:
  type: sqlite
  sqlite_path: conversations.db
  conversation_retention_days: 90

file_upload:
  enabled: true
  max_size_mb: 10
  allowed_extensions: [.txt, .pdf, .csv, .xlsx, .json, .py, .md]
```

To use a custom config, create `config.yaml` in the project root.

## Database Management

```bash
# Initialize database
flask --app genaiStudio_app_database init-db

# View statistics
flask --app genaiStudio_app_database db-stats

# Cleanup old conversations
flask --app genaiStudio_app_database cleanup-db
```

## Troubleshooting

### "No message provided" Error
- **Fixed**: Improved JSON parsing with defensive error handling
- Check browser console (F12) for detailed error messages

### API Connection Issues
- Verify `GENAI_API_KEY` environment variable is set
- Check API endpoint: `https://genai.rcac.purdue.edu/api/chat/completions`
- Ensure model `gpt-stat350` is accessible

### File Upload Errors
- Files are limited to 10MB
- Supported formats: TXT, PDF, CSV, XLSX, JSON, PY, MD
- Long files are automatically truncated to 50,000 characters

### Database Issues
- Delete `instance/conversations.db` and reinitialize to reset
- Check write permissions on `instance/` directory

## Development

### Project Structure
```
GenAIStudio API/
├── genaiStudio_app_database.py  # Main application
├── deploy_database.sh           # Deployment script
├── requirements.txt             # Dependencies
├── templates/
│   └── index.html              # Frontend template
├── static/                     # Static assets
├── instance/
│   └── conversations.db        # SQLite database
├── logs/
│   └── assistant.log           # Application logs
└── uploads/                    # Temporary file uploads
```

### Adding Features
1. Read the code in `genaiStudio_app_database.py`
2. Database models are defined using SQLAlchemy
3. Routes use Flask blueprints
4. Frontend is a single HTML file with embedded JS/CSS

### Logging
Application logs are stored in `logs/assistant.log`:
```bash
tail -f logs/assistant.log
```

## Security

- **Rate Limiting**: 30 requests/minute, 500 requests/hour per user
- **Session Management**: Secure session cookies with timeout
- **File Upload**: Secure filename handling, size limits, extension validation
- **User Isolation**: Session-based user IDs prevent data leakage
- **API Key**: Stored as environment variable, never in code

## Performance

- **Database**: SQLite for simplicity, PostgreSQL for production scale
- **Caching**: Python bytecode caching enabled
- **File Processing**: Files processed in memory, automatically cleaned up
- **Conversation Memory**: Last 50 messages per conversation sent to API

## Course Integration

This application is specifically configured for **STAT 350** with:
- Custom knowledge base containing all course materials
- Chapter-by-chapter content from course website
- R code examples and tutorials
- Worksheet solutions and explanations
- Exam preparation resources

## Support

- Check logs: `logs/assistant.log`
- Health check: `http://localhost:5000/health`
- Statistics: `http://localhost:5000/stats`

## License

Educational use for Purdue University STAT 350.

## Credits

- **Course**: STAT 350, Department of Statistics, Purdue University
- **AI Model**: GPT-STAT350 via Purdue GenAI API
- **Framework**: Flask, SQLAlchemy, KaTeX
