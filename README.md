# STAT 350 AI Assistant - Purdue GenAI Studio

A streamlined chat interface for STAT 350 students using Purdue's GenAI Studio platform with the specialized gpt-stat350 model.

![STAT 350 Assistant](https://img.shields.io/badge/STAT%20350-AI%20Assistant-CFB991?style=for-the-badge&logo=data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==)

## Features

- 🚀 **Real-time Streaming**: Smooth streaming responses from the STAT 350 model
- 🎨 **Purdue-Themed UI**: Clean interface with official Purdue colors
- 📚 **STAT 350 Focused**: Specialized assistant for probability and statistics
- 📱 **Responsive Design**: Works on desktop and mobile devices
- 🔒 **Secure**: API key authentication

## Prerequisites

- Python 3.8+
- Purdue GenAI Studio API key
- Access to Purdue GenAI Studio (https://genai.rcac.purdue.edu)

## Quick Start

### 1. **Clone and Setup**

```bash
# Clone the repository
git clone <repository-url>
cd stat350-assistant

# Create virtual environment
python -m venv venv

# Activate virtual environment
# On Windows:
venv\Scripts\activate
# On macOS/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. **Configure API Key**

Create a `.env` file:
```bash
cp .env.example .env
```

Edit `.env` and add your GenAI Studio API key:
```
GENAI_API_KEY=your-api-key-here
```

### 3. **Setup Logo Image**

**Option A: Use the official logo**
```bash
mkdir -p static
# Save the Purdue GenAI Studio logo image to:
# static/purdue-genai-studio-logo.png
```

**Option B: Create a placeholder**
```bash
pip install Pillow  # If not already installed
python create_placeholder_logo.py
```

**Option C: Use text instead** (see IMAGE_SETUP.md)

### 4. **Run the Application**

```bash
python app.py
```

Open http://localhost:5000 in your browser

## Project Structure

```
stat350-assistant/
├── app.py              # Flask application
├── templates/
│   └── index.html      # Chat interface
├── static/
│   └── purdue-genai-studio-logo.png  # Purdue GenAI Studio logo
├── requirements.txt    # Python dependencies
├── .env.example        # Environment template
├── .env               # Your API key (git-ignored)
└── README.md          # This file
```

## Configuration

The application uses these environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `GENAI_API_KEY` | Your GenAI Studio API key | Required |
| `GENAI_BASE_URL` | GenAI Studio base URL | `https://genai.rcac.purdue.edu` |
| `GENAI_TIMEOUT` | Request timeout in seconds | `30` |

The model is fixed to `gpt-stat350` for STAT 350 course content.

## Usage

1. **Ask Questions**: Type your STAT 350 questions in the input field
2. **Send**: Press Enter or click the Send button
3. **View Responses**: The AI assistant will stream responses in real-time

### Example Questions

- "Explain the Central Limit Theorem"
- "What is the difference between discrete and continuous probability distributions?"
- "How do I calculate the expected value of a random variable?"
- "Explain hypothesis testing with an example"

## Deployment

### Development Mode

```bash
python app.py
```

### Production Mode with Gunicorn

```bash
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

### Docker Deployment

Create a `Dockerfile`:
```dockerfile
FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000

CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "app:app"]
```

Build and run:
```bash
docker build -t stat350-assistant .
docker run -p 5000:5000 --env-file .env stat350-assistant
```

## API Endpoints

- `GET /` - Main chat interface
- `POST /chat` - Send chat messages (streaming)
- `GET /health` - Health check endpoint

## Troubleshooting

### API Key Issues
- Ensure your API key is correctly set in the `.env` file
- Verify you have access to the gpt-stat350 model

### Connection Issues
- Check if you can access https://genai.rcac.purdue.edu
- Ensure you're on Purdue network or using VPN if required

### No Response
- Check the browser console for errors
- Verify the API health status indicator in the header

## Security Notes

- Never commit your `.env` file with API keys
- Use environment variables for all sensitive data
- Consider adding authentication for public deployments

## Support

For issues related to:
- **This application**: Open an issue on GitHub
- **GenAI Studio**: Contact Purdue RCAC support
- **STAT 350 Content**: Contact your course instructor

---

Built for STAT 350 at Purdue University | Boiler Up! 🚂