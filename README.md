# SmartCivic AI Portal 🏛️♻️

An automated, AI-powered civic waste management and reporting dashboard. Citizens can submit geo-tagged complaints with descriptions and photo attachments, while municipal administrators can prioritize, view AI analysis reasons, filter, and manage resolutions.

## Features

- 👤 **Citizen Portal**: Register/login to report issues.
- 📍 **Geotagged Maps**: Pinpoint waste locations on interactive Leaflet maps.
- 🤖 **Gemini AI Analysis**: Automatically extracts location, categorizes waste types (Wet/Dry/Mixed), evaluates severity (Low/Medium/Critical), and provides an urgency reasoning explanation from description text.
- 🖼️ **Image Classification**: Categorizes uploaded photos using Hugging Face's Image Inference models (ViT/ResNet).
- 📊 **Admin Operations Dashboard**: Interactive grid to track, filter by severity/status, and resolve complaints.

## Tech Stack

- **Backend**: FastAPI (Python), SQLite database (with automatic serverless migration)
- **Frontend**: Vanilla CSS & JavaScript, HTML5 semantic layout, Leaflet maps
- **AI Integrations**: Gemini API (via `google-generativeai`), Hugging Face Inference API

---

## Local Development

1. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Add Gemini API Key**:
   Create a file `AIzaSyDex-h1iHO5tgZMSHyfV2OP3h5jF2z.txt` containing your API key, or set the `GEMINI_API_KEY` environment variable.

3. **Start backend**:
   ```bash
   python main.py
   ```

4. Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in your browser.

---

## Deployment to Vercel 🚀

The project is optimized for deployment as a Vercel Serverless application:
- `vercel.json` is configured to route API and upload endpoints to Python, serving the web assets instantly from Vercel's Edge CDN.
- Safe, environment-aware SQLite connection path resolves to `/tmp/complaints.db` dynamically in serverless environments.

### Steps to Deploy:

1. Import this repository into Vercel.
2. In the Vercel project **Settings > Environment Variables**, add:
   - `GEMINI_API_KEY` (Your Gemini API Key)
3. Deploy! Vercel will automatically install the requirements and build the function.
