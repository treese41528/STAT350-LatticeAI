#!/usr/bin/env python3
"""
Purdue GenAI Studio Flask Application - Database-Backed Version
Uses SQLite/PostgreSQL to store conversations persistently
No session cookie storage - conversations persist across sessions
"""

import os
import json
import time
import yaml
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta
import hashlib
import mimetypes
from pathlib import Path
from functools import wraps
import uuid

import requests
from flask import (
    Flask, render_template, request, jsonify, send_from_directory,
    session, abort
)
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import desc, func
from werkzeug.utils import secure_filename
from werkzeug.exceptions import RequestEntityTooLarge
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

# PyPDF2 for PDF processing (optional)
try:
    from PyPDF2 import PdfReader
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False

# pandas for CSV/Excel processing (optional)
try:
    import pandas as pd
    PANDAS_SUPPORT = True
except ImportError:
    PANDAS_SUPPORT = False

# Initialize Flask app
app = Flask(__name__)

# Load configuration
def load_config():
    """Load configuration from YAML file"""
    config_path = os.environ.get('CONFIG_FILE', 'config.yaml')
    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            return yaml.safe_load(f)
    else:
        # Default configuration
        return {
            'course': {
                'name': 'STAT 350',
                'department': 'Department of Statistics',
                'college': 'College of Science'
            },
            'assistant': {
                'name': 'Course Assistant',
                'title': 'Course Assistant',
                'welcome_message': 'How can I help you today?',
                'input_placeholder': 'Ask a question...'
            },
            'genai': {
                'base_url': 'https://genai.rcac.purdue.edu',
                'model': 'gpt-stat350',
                'temperature': 0.7,
                'timeout': 60,
                'max_tokens': 2000
            },
            'ui': {
                'logo_file': 'lattice_ai_icon.png',
                'ai_provider': 'Lattice AI',
                'footer_text': None
            },
            'file_upload': {
                'enabled': True,
                'max_size_mb': 10,
                'allowed_extensions': ['.txt', '.pdf', '.csv', '.xlsx', '.json', '.py', '.md']
            },
            'features': {
                'latex_rendering': True,
                'markdown_support': True,
                'code_highlighting': True,
                'file_analysis': True,
                'source_citations': True
            },
            'security': {
                'rate_limit': {
                    'enabled': True,
                    'requests_per_minute': 30,
                    'requests_per_hour': 500
                },
                'cors': {
                    'enabled': True,
                    'allowed_origins': ['*']
                },
                'session': {
                    'timeout_minutes': 120
                }
            },
            'logging': {
                'level': 'INFO',
                'file': 'logs/assistant.log',
                'max_size_mb': 100,
                'backup_count': 5
            },
            'advanced': {
                'memory_per_conversation': 50,
                'health_check_interval': 300
            },
            'database': {
                'type': 'sqlite',  # 'sqlite' or 'postgresql'
                'sqlite_path': 'conversations.db',
                'postgresql_uri': None,  # e.g., 'postgresql://user:pass@localhost/dbname'
                'conversation_retention_days': 90  # Delete old conversations after X days
            }
        }

# Load configuration
config = load_config()

# Configure app
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', os.urandom(24).hex())
app.config['MAX_CONTENT_LENGTH'] = config['file_upload']['max_size_mb'] * 1024 * 1024
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=config['security']['session']['timeout_minutes'])

# Database configuration
db_config = config.get('database', {})
if db_config.get('type') == 'postgresql' and db_config.get('postgresql_uri'):
    app.config['SQLALCHEMY_DATABASE_URI'] = db_config['postgresql_uri']
else:
    # Default to SQLite
    db_path = db_config.get('sqlite_path', 'conversations.db')
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize SQLAlchemy
db = SQLAlchemy(app)

# Database Models
class Conversation(db.Model):
    """Represents a conversation session"""
    __tablename__ = 'conversations'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.String(100))  # Optional: for user tracking
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    title = db.Column(db.String(200))  # Optional: conversation title
    
    # Relationships
    messages = db.relationship('Message', backref='conversation', lazy='dynamic', 
                              cascade='all, delete-orphan', order_by='Message.created_at')
    
    def to_dict(self, include_messages=False):
        result = {
            'id': self.id,
            'user_id': self.user_id,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'title': self.title,
            'message_count': self.messages.count()
        }
        if include_messages:
            result['messages'] = [msg.to_dict() for msg in self.messages.order_by(Message.created_at)]
        return result

class Message(db.Model):
    """Represents a single message in a conversation"""
    __tablename__ = 'messages'
    
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.String(36), db.ForeignKey('conversations.id'), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # 'user', 'assistant', 'system'
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    model = db.Column(db.String(100))  # Which model generated the response
    tokens_used = db.Column(db.Integer)  # Optional: track token usage
    
    def to_dict(self):
        return {
            'id': self.id,
            'role': self.role,
            'content': self.content,
            'created_at': self.created_at.isoformat(),
            'model': self.model,
            'tokens_used': self.tokens_used
        }

# Create database tables
with app.app_context():
    db.create_all()

# Create necessary directories
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs('templates', exist_ok=True)
os.makedirs('static', exist_ok=True)
os.makedirs(os.path.dirname(config['logging']['file']), exist_ok=True)

# Configure logging
log_level = getattr(logging, config['logging']['level'])
logging.basicConfig(level=log_level)

file_handler = RotatingFileHandler(
    config['logging']['file'],
    maxBytes=config['logging']['max_size_mb'] * 1024 * 1024,
    backupCount=config['logging']['backup_count']
)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
))
app.logger.addHandler(file_handler)
logger = app.logger

# Configure CORS
if config['security']['cors']['enabled']:
    CORS(app, origins=config['security']['cors']['allowed_origins'])

# Configure rate limiting
limiter = None
if config['security']['rate_limit']['enabled']:
    limiter = Limiter(
        app=app,
        key_func=get_remote_address,
        default_limits=[
            f"{config['security']['rate_limit']['requests_per_minute']} per minute",
            f"{config['security']['rate_limit']['requests_per_hour']} per hour"
        ]
    )

# Create session for API requests with retry
session_requests = requests.Session()
retry_strategy = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
)
adapter = HTTPAdapter(max_retries=retry_strategy)
session_requests.mount("http://", adapter)
session_requests.mount("https://", adapter)

# API configuration
API_KEY = os.environ.get("GENAI_API_KEY", "")

def get_headers(json_content=True):
    """Generate request headers"""
    headers = {}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    else:
        logger.warning("No API key configured! Set GENAI_API_KEY environment variable.")
    if json_content:
        headers["Content-Type"] = "application/json"
    return headers

def require_api_key(f):
    """Decorator to require API key"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not API_KEY:
            return jsonify({"error": "API key not configured"}), 503
        return f(*args, **kwargs)
    return decorated_function

def get_or_create_conversation(conversation_id=None, user_id=None):
    """Get existing conversation or create new one"""
    if conversation_id:
        conversation = Conversation.query.get(conversation_id)
        if conversation:
            return conversation
    
    # Create new conversation
    conversation = Conversation(user_id=user_id)
    db.session.add(conversation)
    db.session.commit()
    logger.info(f"Created new conversation: {conversation.id}")
    return conversation

def cleanup_old_conversations():
    """Delete conversations older than retention period"""
    retention_days = config.get('database', {}).get('conversation_retention_days', 90)
    cutoff_date = datetime.utcnow() - timedelta(days=retention_days)
    
    old_conversations = Conversation.query.filter(Conversation.updated_at < cutoff_date).all()
    for conv in old_conversations:
        db.session.delete(conv)
    
    if old_conversations:
        db.session.commit()
        logger.info(f"Cleaned up {len(old_conversations)} old conversations")

def allowed_file(filename):
    """Check if file extension is allowed"""
    return any(filename.lower().endswith(ext) for ext in config['file_upload']['allowed_extensions'])

def process_file(filepath, filename):
    """Process uploaded file and extract text content"""
    content = f"File: {filename}\n"
    
    try:
        file_ext = Path(filename).suffix.lower()
        
        # Text files
        if file_ext in ['.txt', '.md', '.py', '.cpp', '.java', '.r']:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                content += f.read()
        
        # PDF files
        elif file_ext == '.pdf' and PDF_SUPPORT:
            reader = PdfReader(filepath)
            text = []
            for page in reader.pages:
                text.append(page.extract_text())
            content += '\n'.join(text)
        
        # CSV files
        elif file_ext == '.csv' and PANDAS_SUPPORT:
            df = pd.read_csv(filepath)
            content += f"\nShape: {df.shape[0]} rows, {df.shape[1]} columns\n"
            content += f"\nColumns: {', '.join(df.columns)}\n"
            content += f"\nFirst few rows:\n{df.head(10).to_string()}\n"
            content += f"\nSummary statistics:\n{df.describe().to_string()}"
        
        # Excel files
        elif file_ext in ['.xlsx', '.xls'] and PANDAS_SUPPORT:
            df = pd.read_excel(filepath)
            content += f"\nShape: {df.shape[0]} rows, {df.shape[1]} columns\n"
            content += f"\nColumns: {', '.join(df.columns)}\n"
            content += f"\nFirst few rows:\n{df.head(10).to_string()}\n"
            content += f"\nSummary statistics:\n{df.describe().to_string()}"
        
        # JSON files
        elif file_ext == '.json':
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                content += json.dumps(data, indent=2)
        
        else:
            content += f"[Unsupported file type: {file_ext}]"
    
    except Exception as e:
        logger.error(f"Error processing file {filename}: {e}")
        content += f"\n[Error processing file: {str(e)}]"
    
    return content

def get_chat_completion(messages):
    """Get completion from GenAI API"""
    url = f"{config['genai']['base_url']}/api/chat/completions"
    
    payload = {
        "model": config['genai']['model'],
        "messages": messages,
        "temperature": config['genai']['temperature'],
        "max_tokens": config['genai']['max_tokens']
    }
    
    try:
        response = session_requests.post(
            url,
            headers=get_headers(),
            json=payload,
            timeout=config['genai']['timeout']
        )
        response.raise_for_status()
        return response.json()
    
    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP error from GenAI API: {e}")
        error_detail = "Service unavailable"
        try:
            error_detail = e.response.json().get('error', {}).get('message', str(e))
        except:
            pass
        return {"error": f"API error: {error_detail}"}
    
    except requests.exceptions.Timeout:
        logger.error("Timeout connecting to GenAI API")
        return {"error": "Request timeout. Please try again."}
    
    except requests.exceptions.RequestException as e:
        logger.error(f"Error connecting to GenAI API: {e}")
        return {"error": f"Connection error: {str(e)}"}
    
    except Exception as e:
        logger.error(f"Unexpected error in get_chat_completion: {e}")
        return {"error": f"Unexpected error: {str(e)}"}

def health_check():
    """Check if GenAI API is accessible"""
    try:
        url = f"{config['genai']['base_url']}/api/models"
        response = session_requests.get(
            url,
            headers=get_headers(),
            timeout=5
        )
        return response.status_code == 200
    except:
        return False

def build_footer_text():
    """Build dynamic footer text from configuration"""
    if config['ui'].get('footer_text'):
        return config['ui']['footer_text']
    
    parts = ['Purdue University']
    
    if config.get('course', {}).get('department'):
        parts.append(config['course']['department'])
    
    if config.get('course', {}).get('name'):
        parts.append(config['course']['name'])
    
    return ' • '.join(parts)

@app.route('/')
def index():
    """Render the main chat interface"""
    health = health_check()
    template_config = {
        'COURSE_NAME': config['course']['name'],
        'ASSISTANT_NAME': config['assistant']['name'],
        'ASSISTANT_TITLE': config['assistant']['title'],
        'WELCOME_MESSAGE': config['assistant']['welcome_message'],
        'INPUT_PLACEHOLDER': config['assistant']['input_placeholder'],
        'LOGO_FILE': config['ui']['logo_file'],
        'AI_PROVIDER': config['ui']['ai_provider'],
        'FOOTER_TEXT': build_footer_text()
    }
    return render_template('index.html', health_status=health, config=template_config)

@app.route('/chat', methods=['POST'])
@require_api_key
def chat():
    """Handle chat requests with database storage"""
    try:
        # Get conversation ID from request
        conversation_id = None
        user_message_content = None

        # Debug logging
        logger.info(f"Chat request received - Content-Type: {request.content_type}")
        logger.info(f"Request method: {request.method}")

        # Handle multipart form data (with files)
        if request.content_type and 'multipart/form-data' in request.content_type:
            conversation_id = request.form.get('conversation_id')
            user_message_content = request.form.get('message')
            logger.info(f"Multipart request - conversation_id: {conversation_id}, message length: {len(user_message_content) if user_message_content else 0}")

            # Process uploaded files
            file_contents = []
            if 'files' in request.files:
                files = request.files.getlist('files')
                logger.info(f"Processing {len(files)} uploaded file(s)")
                for file in files:
                    if file and allowed_file(file.filename):
                        filename = secure_filename(file.filename)
                        unique_filename = f"{int(time.time())}_{hashlib.md5(filename.encode()).hexdigest()[:8]}_{filename}"
                        filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)

                        try:
                            file.save(filepath)
                            logger.info(f"Processing file: {filename}")
                            content = process_file(filepath, filename)
                            logger.info(f"Extracted {len(content)} characters from {filename}")

                            # Truncate if too long (API may have limits)
                            MAX_FILE_CONTENT = 50000  # characters
                            if len(content) > MAX_FILE_CONTENT:
                                logger.warning(f"File content too long ({len(content)} chars), truncating to {MAX_FILE_CONTENT}")
                                content = content[:MAX_FILE_CONTENT] + f"\n\n[Content truncated - file was too long. Showing first {MAX_FILE_CONTENT} characters]"

                            file_contents.append(content)
                            os.remove(filepath)
                        except Exception as e:
                            logger.error(f"Error handling file {filename}: {e}")
                            file_contents.append(f"File: {filename}\n[Error processing file: {str(e)}]")

            # Add file contents to message
            if file_contents:
                file_context = "\n\n--- Attached Files ---\n" + "\n\n".join(file_contents)
                user_message_content += file_context
                logger.info(f"Total message length with files: {len(user_message_content)} characters")
        else:
            # Regular JSON request
            logger.info(f"Attempting to parse JSON request")
            logger.info(f"Request data: {request.data}")
            logger.info(f"Request headers: {dict(request.headers)}")

            # Try multiple ways to get the data
            data = None
            try:
                data = request.get_json(force=True, silent=False)
            except Exception as e:
                logger.error(f"Error parsing JSON with get_json: {e}")
                # Fallback to request.json
                try:
                    data = request.json
                except Exception as e2:
                    logger.error(f"Error with request.json: {e2}")

            if not data:
                logger.error("No JSON data in request")
                return jsonify({"error": "No data provided. Please ensure you're sending valid JSON."}), 400

            logger.info(f"Parsed JSON data: {data}")
            conversation_id = data.get('conversation_id')
            user_message_content = data.get('message')
            logger.info(f"JSON request - conversation_id: {conversation_id}, message: {user_message_content}")

        if not user_message_content or (isinstance(user_message_content, str) and len(user_message_content.strip()) == 0):
            logger.error(f"No message content - user_message_content: '{user_message_content}'")
            return jsonify({"error": "No message provided"}), 400
        
        # Get or create conversation
        user_id = session.get('user_id') or request.remote_addr
        conversation = get_or_create_conversation(conversation_id, user_id)
        
        # Save user message to database
        user_message = Message(
            conversation_id=conversation.id,
            role='user',
            content=user_message_content
        )
        db.session.add(user_message)
        db.session.commit()
        
        # Get recent messages for context (limit to max_messages)
        max_messages = config['advanced']['memory_per_conversation']
        recent_messages = Message.query.filter_by(conversation_id=conversation.id)\
            .order_by(desc(Message.created_at))\
            .limit(max_messages)\
            .all()
        recent_messages.reverse()  # Oldest first
        
        # Build messages array for API
        messages = [{"role": msg.role, "content": msg.content} for msg in recent_messages]
        
        # Get completion from API
        logger.info(f"Sending {len(messages)} messages to API, total chars in last message: {len(messages[-1]['content']) if messages else 0}")
        result = get_chat_completion(messages)

        if "error" in result:
            error_msg = result['error']
            # Check if error might be due to file content
            if len(user_message_content) > 10000:
                error_msg += " (Note: Message is very long - may be due to file attachment. Try with a smaller file or just text.)"
            return jsonify({"error": error_msg}), 500
        
        # Extract assistant's response
        assistant_content = result['choices'][0]['message']['content']
        model_used = result.get('model', config['genai']['model'])
        tokens_used = result.get('usage', {}).get('total_tokens')
        
        # Save assistant message to database
        assistant_message = Message(
            conversation_id=conversation.id,
            role='assistant',
            content=assistant_content,
            model=model_used,
            tokens_used=tokens_used
        )
        db.session.add(assistant_message)
        
        # Update conversation timestamp
        conversation.updated_at = datetime.utcnow()
        
        # Auto-generate title from first message if not set
        if not conversation.title and conversation.messages.count() == 2:
            conversation.title = user_message_content[:100]
        
        db.session.commit()
        
        return jsonify({
            "content": assistant_content,
            "conversation_id": conversation.id,
            "model": model_used,
            "usage": result.get('usage', {}),
            "message_count": conversation.messages.count()
        })
        
    except Exception as e:
        logger.error(f"Error in chat endpoint: {e}")
        db.session.rollback()
        return jsonify({"error": f"Server error: {str(e)}"}), 500

@app.route('/conversations', methods=['GET'])
def list_conversations():
    """List all conversations for the current user"""
    user_id = session.get('user_id') or request.remote_addr
    limit = request.args.get('limit', 20, type=int)
    offset = request.args.get('offset', 0, type=int)
    
    conversations = Conversation.query.filter_by(user_id=user_id)\
        .order_by(desc(Conversation.updated_at))\
        .limit(limit)\
        .offset(offset)\
        .all()
    
    return jsonify({
        "conversations": [conv.to_dict() for conv in conversations],
        "total": Conversation.query.filter_by(user_id=user_id).count()
    })

@app.route('/conversations/<conversation_id>', methods=['GET'])
def get_conversation(conversation_id):
    """Get a specific conversation with all messages"""
    conversation = Conversation.query.get_or_404(conversation_id)
    return jsonify(conversation.to_dict(include_messages=True))

@app.route('/conversations/<conversation_id>', methods=['DELETE'])
def delete_conversation(conversation_id):
    """Delete a conversation"""
    conversation = Conversation.query.get_or_404(conversation_id)
    db.session.delete(conversation)
    db.session.commit()
    return jsonify({"success": True, "message": "Conversation deleted"})

@app.route('/conversations/<conversation_id>/export', methods=['GET'])
def export_conversation(conversation_id):
    """Export a conversation as JSON"""
    conversation = Conversation.query.get_or_404(conversation_id)
    
    return jsonify({
        "course": config['course']['name'],
        "conversation_id": conversation.id,
        "created_at": conversation.created_at.isoformat(),
        "title": conversation.title,
        "messages": [msg.to_dict() for msg in conversation.messages.order_by(Message.created_at)]
    })

@app.route('/clear-session', methods=['POST'])
def clear_session():
    """Clear the user session"""
    session.clear()
    return jsonify({"success": True})

@app.route('/static/<path:filename>')
def serve_static(filename):
    """Serve static files"""
    return send_from_directory('static', filename)

@app.route('/health')
def app_health():
    """Check application and API health"""
    api_health = health_check()
    
    # Database health check
    try:
        db.session.execute('SELECT 1')
        db_health = True
    except:
        db_health = False
    
    return jsonify({
        "app": "healthy",
        "api": "healthy" if api_health else "unhealthy",
        "database": "healthy" if db_health else "unhealthy",
        "model": config['genai']['model'],
        "course": config['course']['name'],
        "features": config['features'],
        "file_upload_enabled": config['file_upload']['enabled'],
        "pdf_support": PDF_SUPPORT,
        "excel_support": PANDAS_SUPPORT,
        "total_conversations": Conversation.query.count(),
        "total_messages": Message.query.count()
    })

@app.route('/config-info')
def config_info():
    """Get public configuration information"""
    return jsonify({
        "course": config['course'],
        "assistant": config['assistant'],
        "ui": config['ui'],
        "features": config['features'],
        "file_upload": {
            "enabled": config['file_upload']['enabled'],
            "max_size_mb": config['file_upload']['max_size_mb'],
            "allowed_extensions": config['file_upload']['allowed_extensions']
        },
        "database": {
            "type": config.get('database', {}).get('type', 'sqlite')
        }
    })

@app.route('/stats')
def stats():
    """Get usage statistics"""
    user_id = session.get('user_id') or request.remote_addr
    
    user_conversations = Conversation.query.filter_by(user_id=user_id).count()
    user_messages = db.session.query(func.count(Message.id))\
        .join(Conversation)\
        .filter(Conversation.user_id == user_id)\
        .scalar()
    
    return jsonify({
        "user_conversations": user_conversations,
        "user_messages": user_messages,
        "total_conversations": Conversation.query.count(),
        "total_messages": Message.query.count()
    })

@app.errorhandler(413)
@app.errorhandler(RequestEntityTooLarge)
def handle_file_too_large(e):
    """Handle file too large error"""
    return jsonify({
        "error": f"File too large. Maximum size is {config['file_upload']['max_size_mb']}MB"
    }), 413

@app.errorhandler(429)
def handle_rate_limit(e):
    """Handle rate limit error"""
    return jsonify({
        "error": "Rate limit exceeded. Please wait a moment and try again."
    }), 429

@app.errorhandler(500)
def handle_internal_error(e):
    """Handle internal server errors"""
    logger.error(f"Internal server error: {e}")
    return jsonify({
        "error": "Internal server error. Please try again later."
    }), 500

@app.errorhandler(404)
def handle_not_found(e):
    """Handle 404 errors"""
    return jsonify({
        "error": "Resource not found"
    }), 404

@app.before_request
def before_request():
    """Set session permanent and cleanup old conversations"""
    session.permanent = True
    
    # Cleanup old conversations periodically (1% chance per request)
    import random
    if random.random() < 0.01:
        try:
            cleanup_old_conversations()
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

# CLI commands for database management
@app.cli.command()
def init_db():
    """Initialize the database"""
    db.create_all()
    print("Database initialized successfully!")

@app.cli.command()
def cleanup_db():
    """Cleanup old conversations"""
    cleanup_old_conversations()
    print("Database cleanup completed!")

@app.cli.command()
def db_stats():
    """Show database statistics"""
    print(f"Total conversations: {Conversation.query.count()}")
    print(f"Total messages: {Message.query.count()}")
    print(f"Database type: {config.get('database', {}).get('type', 'sqlite')}")
    print(f"Database URI: {app.config['SQLALCHEMY_DATABASE_URI']}")

# For Gunicorn
application = app

if __name__ == '__main__':
    # Check API key
    if not API_KEY:
        logger.warning("⚠️  No API key found. Set GENAI_API_KEY environment variable.")
    else:
        logger.info("✅ API key is configured")
    
    # Log configuration
    logger.info(f"📚 Course: {config['course']['name']}")
    logger.info(f"🤖 Model: {config['genai']['model']}")
    logger.info(f"💾 Database: {config.get('database', {}).get('type', 'sqlite')}")
    logger.info(f"📎 File upload: {'Enabled' if config['file_upload']['enabled'] else 'Disabled'}")
    
    print("⚠️  Running with Flask development server. Use Gunicorn for production!")
    print("💡 To run with Gunicorn:")
    print("   gunicorn -w 4 -b 0.0.0.0:5000 --timeout 120 app:application")
    
    debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=debug_mode)
