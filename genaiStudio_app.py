#!/usr/bin/env python3
"""
Purdue GenAI Studio Flask Application - Configurable Course AI Assistant
Production-ready chat interface with file upload support
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

import requests
from flask import (
    Flask, render_template, request, Response, 
    stream_with_context, jsonify, send_from_directory,
    session, abort
)
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.utils import secure_filename
from werkzeug.exceptions import RequestEntityTooLarge
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

# PyPDF2 for PDF processing (optional, install with pip install pypdf2)
try:
    from PyPDF2 import PdfReader
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False

# pandas for CSV/Excel processing (optional, install with pip install pandas openpyxl)
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
        # Default configuration if no file exists
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
                'stream_timeout': 120,
                'max_tokens': 2000
            },
            'ui': {
                'logo_file': 'lattice_ai_icon.png',
                'ai_provider': 'Lattice AI',
                'footer_text': None  # Will be auto-generated if None
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
                'streaming_buffer_size': 5,
                'health_check_interval': 300
            }
        }

# Load configuration
config = load_config()

# Configure app
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', os.urandom(24).hex())
app.config['MAX_CONTENT_LENGTH'] = config['file_upload']['max_size_mb'] * 1024 * 1024
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=config['security']['session']['timeout_minutes'])

# Create necessary directories
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs('templates', exist_ok=True)
os.makedirs('static', exist_ok=True)
os.makedirs(os.path.dirname(config['logging']['file']), exist_ok=True)

# Configure logging
log_level = getattr(logging, config['logging']['level'])
logging.basicConfig(level=log_level)

# File handler with rotation
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

# API configuration from environment
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
            content += f"Shape: {df.shape}\n"
            content += f"Columns: {', '.join(df.columns)}\n\n"
            content += df.head(10).to_string()
        
        # Excel files
        elif file_ext == '.xlsx' and PANDAS_SUPPORT:
            df = pd.read_excel(filepath)
            content += f"Shape: {df.shape}\n"
            content += f"Columns: {', '.join(df.columns)}\n\n"
            content += df.head(10).to_string()
        
        # JSON files
        elif file_ext == '.json':
            with open(filepath, 'r') as f:
                data = json.load(f)
                content += json.dumps(data, indent=2)[:2000]  # Limit size
        
        else:
            content += f"[Binary file - cannot display content]"
            
    except Exception as e:
        logger.error(f"Error processing file {filename}: {e}")
        content += f"[Error reading file: {str(e)}]"
    
    return content

def health_check():
    """Check if the GenAI Studio service is healthy"""
    try:
        response = session_requests.get(
            f"{config['genai']['base_url']}/health",
            timeout=5
        )
        return response.status_code == 200
    except:
        return False

def stream_chat_completion(messages):
    """Stream chat completion from GenAI Studio API"""
    url = f"{config['genai']['base_url']}/api/chat/completions"
    
    # Add source instruction if configured for this model
    model = config['genai']['model']
    model_settings = config.get('model_settings', {})
    model_config = model_settings.get(model, model_settings.get('default', {}))
    
    if model_config.get('add_source_instruction') and messages:
        last_msg = messages[-1]
        if last_msg.get('role') == 'user':
            original_content = last_msg.get('content', '')
            if 'source:' not in original_content.lower():
                instruction = model_config.get('source_instruction', '')
                messages[-1] = {
                    'role': 'user',
                    'content': original_content + instruction
                }
    
    payload = {
        "model": model,
        "messages": messages,
        "temperature": config['genai']['temperature'],
        "max_tokens": config['genai']['max_tokens'],
        "stream": True
    }
    
    try:
        response = session_requests.post(
            url,
            headers=get_headers(),
            json=payload,
            stream=True,
            timeout=config['genai']['stream_timeout']
        )
        
        if response.status_code != 200:
            error_msg = f'API Error: {response.status_code}'
            logger.error(error_msg)
            yield f"data: {json.dumps({'error': error_msg})}\n\n"
            return
        
        # Set a deadline for the entire streaming operation
        start_time = time.time()
        max_stream_duration = 300  # 5 minutes max
        
        for line in response.iter_lines(decode_unicode=True):
            # Check if we've exceeded max duration
            if time.time() - start_time > max_stream_duration:
                logger.warning("Stream duration exceeded maximum time")
                yield f"data: {json.dumps({'error': 'Response time exceeded maximum duration'})}\n\n"
                break
                
            if line:
                if line.startswith("data:"):
                    data = line[5:].strip()
                    if data == "[DONE]":
                        yield "data: [DONE]\n\n"
                        break
                    try:
                        # Parse and re-emit the data
                        chunk = json.loads(data)
                        yield f"data: {json.dumps(chunk)}\n\n"
                    except json.JSONDecodeError:
                        continue
                        
    except requests.Timeout:
        logger.error(f"Request timeout after {config['genai']['stream_timeout']} seconds")
        yield f"data: {json.dumps({'error': 'The AI model is taking longer than expected. Please try again with a shorter question or wait a moment and retry.'})}\n\n"
    except requests.RequestException as e:
        logger.error(f"Request exception: {type(e).__name__}: {str(e)}")
        yield f"data: {json.dumps({'error': str(e)})}\n\n"
    except Exception as e:
        logger.error(f"Unexpected error: {type(e).__name__}: {str(e)}")
        yield f"data: {json.dumps({'error': f'Unexpected error: {str(e)}'})}\n\n"

def build_footer_text():
    """Build footer text dynamically from course information"""
    # Check if footer_text is explicitly set in config
    if config.get('ui', {}).get('footer_text'):
        return config['ui']['footer_text']
    
    # Build dynamic footer
    parts = ['Purdue University']
    
    # Add department if available
    if config.get('course', {}).get('department'):
        parts.append(config['course']['department'])
    
    # Add course name if available
    if config.get('course', {}).get('name'):
        parts.append(config['course']['name'])

    
    return ' • '.join(parts)

@app.route('/')
def index():
    """Render the main chat interface"""
    health = health_check()
    # Pass configuration to template
    template_config = {
        'COURSE_NAME': config['course']['name'],
        'ASSISTANT_NAME': config['assistant']['name'],
        'ASSISTANT_TITLE': config['assistant']['title'],
        'WELCOME_MESSAGE': config['assistant']['welcome_message'],
        'INPUT_PLACEHOLDER': config['assistant']['input_placeholder'],
        'LOGO_FILE': config['ui']['logo_file'],
        'AI_PROVIDER': config['ui']['ai_provider'],
        'FOOTER_TEXT': build_footer_text()  # Use dynamic footer
    }
    return render_template('index.html', health_status=health, config=template_config)

@app.route('/chat', methods=['POST'])
@require_api_key
def chat():
    """Handle streaming chat requests with file upload support"""
    # Initialize messages from session if available
    if 'messages' not in session:
        session['messages'] = []
    
    # Handle multipart form data (with files)
    if request.content_type and 'multipart/form-data' in request.content_type:
        # Get messages from form data
        messages_json = request.form.get('messages')
        if messages_json:
            try:
                messages = json.loads(messages_json)
            except:
                messages = session['messages']
        else:
            messages = session['messages']
        
        # Process uploaded files
        file_contents = []
        if 'files' in request.files:
            files = request.files.getlist('files')
            for file in files:
                if file and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    # Create unique filename
                    unique_filename = f"{int(time.time())}_{hashlib.md5(filename.encode()).hexdigest()[:8]}_{filename}"
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
                    
                    try:
                        file.save(filepath)
                        # Process file content
                        content = process_file(filepath, filename)
                        file_contents.append(content)
                        
                        # Clean up file after processing
                        os.remove(filepath)
                    except Exception as e:
                        logger.error(f"Error handling file {filename}: {e}")
        
        # Add file contents to the last user message
        if file_contents and messages:
            last_message = messages[-1]
            if last_message['role'] == 'user':
                file_context = "\n\n--- Attached Files ---\n" + "\n\n".join(file_contents)
                last_message['content'] += file_context
    else:
        # Regular JSON request
        data = request.json
        messages = data.get('messages', session['messages'])
    
    if not messages:
        return jsonify({"error": "No messages provided"}), 400
    
    # Limit conversation memory
    max_messages = config['advanced']['memory_per_conversation']
    if len(messages) > max_messages:
        # Keep system message if exists, then most recent messages
        if messages[0].get('role') == 'system':
            messages = [messages[0]] + messages[-(max_messages-1):]
        else:
            messages = messages[-max_messages:]
    
    # Update session
    session['messages'] = messages
    session.permanent = True
    
    # Make a copy to avoid modifying original
    messages_copy = messages.copy()
    
    def generate():
        try:
            buffer_size = config['advanced']['streaming_buffer_size']
            buffer = []
            
            for chunk in stream_chat_completion(messages_copy):
                buffer.append(chunk)
                if len(buffer) >= buffer_size:
                    for item in buffer:
                        yield item
                    buffer = []
            
            # Yield remaining items
            for item in buffer:
                yield item
                
        except Exception as e:
            logger.error(f"Error in generate(): {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
    
    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive'
        }
    )

@app.route('/clear-session', methods=['POST'])
def clear_session():
    """Clear the conversation session"""
    session.clear()
    return jsonify({"success": True})

@app.route('/export-conversation', methods=['GET'])
def export_conversation():
    """Export current conversation as JSON"""
    messages = session.get('messages', [])
    return jsonify({
        "course": config['course']['name'],
        "timestamp": datetime.now().isoformat(),
        "messages": messages
    })

@app.route('/static/<path:filename>')
def serve_static(filename):
    """Serve static files"""
    return send_from_directory('static', filename)

@app.route('/health')
def app_health():
    """Check application and API health"""
    api_health = health_check()
    return jsonify({
        "app": "healthy",
        "api": "healthy" if api_health else "unhealthy",
        "model": config['genai']['model'],
        "course": config['course']['name'],
        "features": config['features'],
        "file_upload_enabled": config['file_upload']['enabled'],
        "pdf_support": PDF_SUPPORT,
        "excel_support": PANDAS_SUPPORT
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
        }
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

@app.before_request
def before_request():
    """Set session permanent"""
    session.permanent = True

if __name__ == '__main__':
    # Check API key
    if not API_KEY:
        logger.warning("⚠️  No API key found. Set GENAI_API_KEY environment variable.")
    else:
        logger.info("✅ API key is configured")
    
    # Log configuration
    logger.info(f"📚 Course: {config['course']['name']}")
    logger.info(f"🤖 Model: {config['genai']['model']}")
    logger.info(f"📎 File upload: {'Enabled' if config['file_upload']['enabled'] else 'Disabled'}")
    
    # Check for optional dependencies
    if config['file_upload']['enabled']:
        if not PDF_SUPPORT:
            logger.warning("⚠️  PyPDF2 not installed. PDF support disabled. Install with: pip install pypdf2")
        if not PANDAS_SUPPORT:
            logger.warning("⚠️  pandas not installed. CSV/Excel support disabled. Install with: pip install pandas openpyxl")
    
    # Run the app
    debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    port = int(os.environ.get('PORT', 5000))
    
    if debug_mode:
        app.run(host='0.0.0.0', port=port, debug=True)
    else:
        # Production mode - use a proper WSGI server in production
        logger.info("🚀 Running in production mode")
        logger.info("💡 For production deployment, use a WSGI server like Gunicorn:")
        logger.info("   gunicorn -w 4 -b 0.0.0.0:5000 app:app")
        app.run(host='0.0.0.0', port=port, debug=False)