#!/bin/bash

# Deployment Script for Database-Backed Chat Application
# Migrates from cookie-based to database-backed storage

set -e

echo "=========================================="
echo "Database-Backed Chat - Deployment"
echo "=========================================="
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Check if we're in the right directory
if [ ! -f "genaiStudio_app.py" ]; then
    echo -e "${RED}Error: genaiStudio_app.py not found${NC}"
    echo "Please run this script from your application directory"
    exit 1
fi

echo -e "${BLUE}This script will:${NC}"
echo "1. Backup your current files"
echo "2. Install required dependencies"
echo "3. Deploy database-backed version"
echo "4. Initialize the database"
echo "5. Update frontend for conversation persistence"
echo ""
read -p "Continue? (y/n) " -n 1 -r
echo ""

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Deployment cancelled"
    exit 0
fi

# Create backup
BACKUP_DIR="backup_db_migration_$(date +%Y%m%d_%H%M%S)"
echo -e "${YELLOW}Creating backup: ${BACKUP_DIR}${NC}"
mkdir -p "$BACKUP_DIR"
cp genaiStudio_app.py "$BACKUP_DIR/"
[ -f "templates/index.html" ] && cp templates/index.html "$BACKUP_DIR/"
echo -e "${GREEN}✓ Backup completed${NC}"
echo ""

# Check for requirements.txt
if [ ! -f "requirements.txt" ]; then
    echo -e "${YELLOW}Creating requirements.txt...${NC}"
    cat > requirements.txt << 'EOF'
Flask==3.0.0
Flask-CORS==4.0.0
Flask-Limiter==3.5.0
Flask-SQLAlchemy==3.1.1
SQLAlchemy==2.0.23
requests==2.31.0
PyYAML==6.0.1
PyPDF2==3.0.1
pandas==2.1.4
openpyxl==3.1.2
gunicorn==21.2.0
EOF
fi

# Install dependencies
echo -e "${YELLOW}Installing dependencies...${NC}"
pip install -r requirements.txt
echo -e "${GREEN}✓ Dependencies installed${NC}"
echo ""

# Deploy application
if [ -f "genaiStudio_app_database.py" ]; then
    echo -e "${YELLOW}Deploying database-backed application...${NC}"
    cp genaiStudio_app.py "$BACKUP_DIR/genaiStudio_app.original.py"
    cp genaiStudio_app_database.py genaiStudio_app.py
    echo -e "${GREEN}✓ Application deployed${NC}"
else
    echo -e "${RED}Error: genaiStudio_app_database.py not found${NC}"
    exit 1
fi

# Initialize database
echo ""
echo -e "${YELLOW}Initializing database...${NC}"
export FLASK_APP=genaiStudio_app.py
flask init-db
echo -e "${GREEN}✓ Database initialized${NC}"
echo ""

# Database info
echo -e "${BLUE}Database Information:${NC}"
if [ -f "conversations.db" ]; then
    echo -e "  Database file: ${GREEN}conversations.db${NC}"
    echo -e "  Type: SQLite"
    echo -e "  Status: Created successfully"
else
    echo -e "  ${YELLOW}Warning: Database file not found. It will be created on first run.${NC}"
fi
echo ""

# Update frontend (if javascript update file exists)
if [ -f "javascript_database_updates.js" ]; then
    echo -e "${YELLOW}Frontend update file available: javascript_database_updates.js${NC}"
    echo "  You need to manually integrate these changes into templates/index.html"
    echo "  See DATABASE_GUIDE.md for instructions"
else
    echo -e "${YELLOW}Note: Frontend may need updates for full functionality${NC}"
fi
echo ""

echo -e "${GREEN}=========================================="
echo "Deployment Completed Successfully!"
echo "==========================================${NC}"
echo ""
echo -e "${BLUE}Next Steps:${NC}"
echo ""
echo "1. ${YELLOW}Test the database:${NC}"
echo "   flask db-stats"
echo ""
echo "2. ${YELLOW}Restart your application:${NC}"
echo "   # For systemd:"
echo "   sudo systemctl restart your-service-name"
echo ""
echo "   # For Gunicorn:"
echo "   pkill gunicorn"
echo "   gunicorn -c gunicorn_config.py genaiStudio_app:application"
echo ""
echo "3. ${YELLOW}Test the application:${NC}"
echo "   - Open in browser"
echo "   - Send a message"
echo "   - Close browser"
echo "   - Reopen and verify conversation persists"
echo ""
echo "4. ${YELLOW}Monitor the database:${NC}"
echo "   sqlite3 conversations.db \"SELECT COUNT(*) FROM conversations;\""
echo ""
echo "5. ${YELLOW}View logs:${NC}"
echo "   tail -f logs/assistant.log"
echo ""
echo -e "${BLUE}New Features:${NC}"
echo "  ✅ Persistent conversations across sessions"
echo "  ✅ No cookie size limits"
echo "  ✅ Conversation history API"
echo "  ✅ Export conversations"
echo "  ✅ Auto-cleanup of old conversations"
echo ""
echo -e "${BLUE}API Endpoints:${NC}"
echo "  GET  /conversations              - List all conversations"
echo "  GET  /conversations/<id>         - Get specific conversation"
echo "  POST /chat                       - Send message (includes conversation_id)"
echo "  DELETE /conversations/<id>       - Delete conversation"
echo "  GET  /conversations/<id>/export  - Export conversation"
echo "  GET  /stats                      - Usage statistics"
echo ""
echo -e "${BLUE}Database Management:${NC}"
echo "  flask init-db      - Initialize database"
echo "  flask db-stats     - View statistics"
echo "  flask cleanup-db   - Cleanup old conversations"
echo ""
echo -e "${GREEN}Backup location: ${BACKUP_DIR}${NC}"
echo ""
echo -e "${BLUE}Documentation:${NC}"
echo "  - DATABASE_GUIDE.md       - Complete guide"
echo "  - javascript_database_updates.js - Frontend changes"
echo ""
echo "If you encounter issues, restore from backup:"
echo "  ${YELLOW}cp ${BACKUP_DIR}/* .${NC}"
echo ""
echo -e "${GREEN}Enjoy your new database-backed chat application!${NC}"
