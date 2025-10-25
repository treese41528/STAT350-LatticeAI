# Production Deployment Checklist

## ✅ Completed (Ready for Production)

- [x] **Bug Fixes**
  - Fixed "No message provided" error
  - Fixed API endpoint (/api/chat/completions)
  - Fixed file upload handling

- [x] **Code Quality**
  - Removed test files
  - Removed redundant documentation
  - Cleaned up debug console.log statements
  - Organized project structure

- [x] **Database**
  - SQLite database configured
  - Conversation persistence working
  - Auto-cleanup of old conversations (90 days)

- [x] **Security**
  - Rate limiting enabled (30/min, 500/hour)
  - File upload validation
  - Session management
  - Secure filename handling

- [x] **Features**
  - Chat working with AI responses
  - File uploads (PDF, CSV, XLSX, TXT, etc.)
  - Conversation history
  - LaTeX rendering
  - Markdown support

## ⚠️ Before Deploying to Production

### 1. Add Static Assets (Optional)
```bash
# If you want logos, add these files to static/:
- static/lattice_ai_icon.png
- static/purdue-genai-studio-logo.png

# Or remove references from templates/index.html
```

### 2. Use Production Server
```bash
# Don't use Flask development server in production!
# Use Gunicorn instead:
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 --timeout 120 genaiStudio_app_database:application
```

### 3. Set Environment Variables
```bash
export GENAI_API_KEY="your-actual-api-key"
export FLASK_ENV="production"
```

### 4. Optional: Create config.yaml
If you want to customize settings, create `config.yaml` with your overrides.

### 5. Database Backup Strategy
```bash
# Setup automated backups
crontab -e

# Add daily backup at 2 AM:
0 2 * * * cd /path/to/app && cp instance/conversations.db backups/conversations-$(date +\%Y\%m\%d).db
```

### 6. Logging Configuration
Current setup logs to `logs/assistant.log` with rotation. This is production-ready.

## Deployment Steps

### For GitHub Deployment:

```bash
# 1. Review changes
git status

# 2. Commit
git add .
git commit -m "Production-ready version with bug fixes and cleanup"

# 3. Push to GitHub
git push origin main

# 4. On production server:
git pull origin main
pip install -r requirements.txt
python3 -c "from genaiStudio_app_database import app, db; app.app_context().push(); db.create_all()"
gunicorn -w 4 -b 0.0.0.0:5000 --timeout 120 genaiStudio_app_database:application
```

### For systemd Service:

Create `/etc/systemd/system/genai-studio.service`:

```ini
[Unit]
Description=GenAI Studio STAT 350 Chat Application
After=network.target

[Service]
Type=simple
User=your-username
WorkingDirectory=/path/to/GenAIStudio API
Environment="GENAI_API_KEY=your-api-key"
ExecStart=/usr/bin/gunicorn -w 4 -b 0.0.0.0:5000 --timeout 120 genaiStudio_app_database:application
Restart=always

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo systemctl daemon-reload
sudo systemctl enable genai-studio
sudo systemctl start genai-studio
sudo systemctl status genai-studio
```

## Testing After Deployment

```bash
# 1. Check health
curl http://localhost:5000/health

# 2. Check stats
curl http://localhost:5000/stats

# 3. Test chat (requires API key)
curl -X POST http://localhost:5000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Test", "conversation_id": null}'

# 4. Monitor logs
tail -f logs/assistant.log
```

## Known Minor Issues (Non-Critical)

- Missing logo files in static/ (returns 404, but app works fine)
- Backend has verbose logging (good for debugging, can reduce if needed)

## Performance Recommendations

- **For < 50 users**: Current SQLite setup is fine
- **For 50-500 users**: Consider PostgreSQL
- **For > 500 users**: Add Redis for caching, use PostgreSQL

## YES - This is Production Ready!

The application is fully functional and production-ready. The "issues" above are minor enhancements, not blockers.

**You can replace your old GitHub version now.**

Just make sure to:
1. Set your `GENAI_API_KEY` environment variable
2. Use Gunicorn (not Flask dev server)
3. Initialize the database
4. Optionally add static logo files (or ignore the 404s)
