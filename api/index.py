import os
import base64
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

import sqlite3
import json
import secrets
import hashlib
import requests
from contextlib import contextmanager
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Body, Header, Form, UploadFile, File
try:
    from fastapi.responses import FileResponse, HTMLResponse, Response
except ImportError:
    from starlette.responses import FileResponse, HTMLResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import google.generativeai as genai
import uvicorn

# Constants
IS_VERCEL = os.environ.get("VERCEL") == "1"
DB_FILE = "/tmp/complaints.db" if IS_VERCEL else "complaints.db"
KEY_FILE = "AIzaSyDex-h1iHO5tgZMSHyfV2OP3h5jF2z.txt"
UPLOAD_DIR = "/tmp/uploads" if IS_VERCEL else "public/uploads"

# Ensure directories exist
os.makedirs(UPLOAD_DIR, exist_ok=True)

# 1. Initialize API Keys
api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GEMINI_KEY")
if not api_key and os.path.exists(KEY_FILE):
    try:
        with open(KEY_FILE, "r") as f:
            api_key = f.read().strip()
    except Exception as e:
        print(f"Error reading API key file: {e}")

if api_key:
    try:
        genai.configure(api_key=api_key)
        print("Gemini API configured successfully.")
    except Exception as e:
        print(f"Failed to configure Gemini API: {e}")
else:
    print("Warning: No Gemini API key found. Server will run in Fallback Mode.")

def get_gemini_model():
    if not api_key:
        return None
    for model_name in ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-flash"]:
        try:
            return genai.GenerativeModel(model_name)
        except Exception:
            continue
    return genai.GenerativeModel("gemini-1.5-flash")

# 2. Database Manager
@contextmanager
def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.commit()
        conn.close()

def init_db():
    with get_db() as conn:
        # Create users table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        # Create sessions table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        ''')
        # Create complaints base table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS complaints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                raw_text TEXT NOT NULL,
                location TEXT NOT NULL,
                waste_type TEXT NOT NULL,
                severity TEXT NOT NULL,
                urgency_reason TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'Pending'
            )
        ''')
        
        # Migrations: Alter complaints if columns are missing
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(complaints)")
        columns = [row['name'] for row in cursor.fetchall()]
        
        if 'user_id' not in columns:
            conn.execute("ALTER TABLE complaints ADD COLUMN user_id INTEGER REFERENCES users(id) DEFAULT NULL")
        if 'latitude' not in columns:
            conn.execute("ALTER TABLE complaints ADD COLUMN latitude REAL DEFAULT NULL")
        if 'longitude' not in columns:
            conn.execute("ALTER TABLE complaints ADD COLUMN longitude REAL DEFAULT NULL")
        if 'image_path' not in columns:
            conn.execute("ALTER TABLE complaints ADD COLUMN image_path TEXT DEFAULT NULL")
        if 'image_tags' not in columns:
            conn.execute("ALTER TABLE complaints ADD COLUMN image_tags TEXT DEFAULT NULL")
            
    print("SQLite Database initialized and migrated.")

# 3. Hashing Helpers
def hash_password(password: str, salt: str = None) -> tuple[str, str]:
    if not salt:
        salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100000
    )
    return key.hex(), salt

# 4. Auth Verification Dependency
async def get_current_user(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized. Session token required.")
    token = authorization.split(" ")[1]
    
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT users.id, users.username 
            FROM sessions 
            JOIN users ON sessions.user_id = users.id 
            WHERE sessions.token = ?
        ''', (token,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="Invalid or expired session.")
        return dict(row)

# 5. Pydantic Schemas
class UserRegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=30)
    password: str = Field(..., min_length=4)

class UserLoginRequest(BaseModel):
    username: str = Field(...)
    password: str = Field(...)

class ComplaintAnalysis(BaseModel):
    is_valid_civic_issue: bool = Field(
        description="MUST be True if the text is a real, meaningful civic or waste grievance. MUST be False if the text is gibberish, spam, test text, keyboard smashing, or completely out of scope."
    )
    rejection_reason: Optional[str] = Field(
        default=None,
        description="If is_valid_civic_issue is False, explain briefly why it is classified as invalid or fake."
    )
    location: str = Field(description="The specific location, street, landmark, neighborhood, or city mentioned in the complaint. If none is found, return 'Unknown'")
    waste_type: str = Field(description="The type of waste. MUST be one of: Wet, Dry, Mixed.")
    severity_level: str = Field(description="The severity level of the waste issue. MUST be one of: Low, Medium, Critical.")
    urgency_reason: str = Field(description="A brief explanation of why this severity level was assigned and what the core issue is.")

# 6. Anti-Fraud & Anti-Spam Validation Rules
def is_gibberish_or_spam(text: str) -> tuple[bool, str]:
    cleaned = text.strip()
    if len(cleaned) < 8:
        return True, "Complaint description is too short (minimum 8 characters required)."
        
    text_lower = cleaned.lower()
    
    # Common keyboard smash / test spam patterns
    spam_patterns = [
        "asdf", "qwerty", "zxcv", "12345", "test test", "blah blah", 
        "aaaaa", "bbbbb", "ccccc", "ddddd", "eeeee", "ffffff", "11111", "22222"
    ]
    for pattern in spam_patterns:
        if pattern in text_lower:
            return True, f"Submission contains repetitive spam pattern ('{pattern}')."
            
    # Unnatural character repetition
    char_counts = {}
    for char in text_lower:
        if char.isalpha():
            char_counts[char] = char_counts.get(char, 0) + 1
    total_alpha = sum(char_counts.values())
    if total_alpha > 5:
        max_char_ratio = max(char_counts.values()) / total_alpha
        if max_char_ratio > 0.45:
            return True, "Unnatural character repetition detected."

    # Single excessively long non-word
    words = cleaned.split()
    if len(words) == 1 and len(words[0]) > 18:
        return True, "Single excessively long unrecognized string submitted without spaces."

    return False, ""

def run_fallback_analysis(text: str) -> dict:
    text_lower = text.lower()
    location = "Unknown"
    words = text.split()
    for i, word in enumerate(words):
        if word.lower() in ["in", "at", "near", "on", "street", "road", "block"] and i + 1 < len(words):
            candidate = []
            for j in range(i+1, min(i+4, len(words))):
                candidate.append(words[j].strip(",.!?\"()"))
            location = " ".join(candidate)
            break
            
    wet_keywords = ["food", "wet", "organic", "smell", "vegetable", "fruit", "kitchen", "decay", "rotten", "garbage", "trash"]
    dry_keywords = ["plastic", "paper", "cardboard", "dry", "bottle", "can", "metal", "glass", "wood", "box"]
    
    has_wet = any(kw in text_lower for kw in wet_keywords)
    has_dry = any(kw in text_lower for kw in dry_keywords)
    
    if has_wet and has_dry:
        waste_type = "Mixed"
    elif has_wet:
        waste_type = "Wet"
    elif has_dry:
        waste_type = "Dry"
    else:
        waste_type = "Mixed"
        
    critical_keywords = ["terrible", "horrible", "stink", "smelly", "emergency", "danger", "hazard", "overflowing", "week", "disease", "toxic", "leak", "blocked", "flooded", "school", "hospital"]
    medium_keywords = ["skip", "pile", "day", "dirty", "litter", "truck", "missed", "smell"]
    
    if any(kw in text_lower for kw in critical_keywords):
        severity = "Critical"
    elif any(kw in text_lower for kw in medium_keywords):
        severity = "Medium"
    else:
        severity = "Low"
        
    urgency_reason = "Analyzed via local rules (Gemini API was bypassed or unavailable)."
    if severity == "Critical":
        urgency_reason = "Identified as high hazard due to environmental or sanitary risk factors."
        
    return {
        "location": location,
        "waste_type": waste_type,
        "severity_level": severity,
        "urgency_reason": urgency_reason
    }

# 7. Image Classification (Hugging Face API + Gemini Vision Fallback)
def analyze_image_gemini(image_bytes: bytes, mime_type: str = "image/jpeg") -> Optional[str]:
    if not api_key:
        return None
    try:
        model = get_gemini_model()
        if not model:
            return None
        prompt = (
            "Analyze this waste or civic grievance photo. Identify 2 to 3 key visible objects, waste materials, "
            "or situation elements with estimated percentage scores (e.g. 'Garbage Dump (94%), Plastic Litter (85%), Waste Bin (76%)'). "
            "Return ONLY the concise comma-separated tags string."
        )
        image_part = {
            "mime_type": mime_type,
            "data": image_bytes
        }
        response = model.generate_content([prompt, image_part])
        if response and response.text:
            cleaned = response.text.strip().replace("\n", " ")
            if len(cleaned) > 4 and len(cleaned) < 200:
                return cleaned
    except Exception as e:
        print(f"Gemini Vision API exception: {e}")
    return None

def analyze_image_hf(image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
    hf_token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_TOKEN")
    headers = {}
    if hf_token:
        headers["Authorization"] = f"Bearer {hf_token}"
    
    models = ["google/vit-base-patch16-224", "microsoft/resnet-50"]
    for model_id in models:
        urls = [
            f"https://api-inference.huggingface.co/models/{model_id}",
            f"https://router.huggingface.co/hf-inference/v1/models/{model_id}"
        ]
        for api_url in urls:
            try:
                response = requests.post(api_url, headers=headers, data=image_bytes, timeout=8)
                if response.status_code == 200:
                    predictions = response.json()
                    if isinstance(predictions, list) and len(predictions) > 0:
                        tags = []
                        for pred in predictions[:3]:
                            if isinstance(pred, dict):
                                score = pred.get("score", 0) * 100
                                label = pred.get("label", "unknown").split(",")[-1].strip()
                                if score > 5:
                                    tags.append(f"{label} ({score:.0f}%)")
                        if tags:
                            return ", ".join(tags)
            except Exception as e:
                print(f"Hugging Face API call error for {model_id}: {e}")
                continue

    # Fallback to Gemini Vision API if Hugging Face API times out or fails
    gemini_tags = analyze_image_gemini(image_bytes, mime_type)
    if gemini_tags:
        return gemini_tags

    return "Waste Photo Uploaded (Visual Record Saved)"


# 8. FastAPI Setup
app = FastAPI(title="SmartCivic AI Portal", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def startup_event():
    init_db()

# --- Auth Endpoints ---

@app.post("/api/auth/register")
async def register(payload: UserRegisterRequest):
    username = payload.username.strip()
    password = payload.password
    
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail="Username is already taken.")
            
        password_hash, salt = hash_password(password)
        try:
            cursor.execute('''
                INSERT INTO users (username, password_hash, salt)
                VALUES (?, ?, ?)
            ''', (username, password_hash, salt))
            return {"status": "success", "message": "Registration successful. Please log in."}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Database write error: {str(e)}")

@app.post("/api/auth/login")
async def login(payload: UserLoginRequest):
    username = payload.username.strip()
    password = payload.password
    
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=400, detail="Invalid username or password.")
            
        user = dict(row)
        chk_hash, _ = hash_password(password, user["salt"])
        if chk_hash != user["password_hash"]:
            raise HTTPException(status_code=400, detail="Invalid username or password.")
            
        # Generate session token
        token = secrets.token_hex(32)
        cursor.execute("INSERT INTO sessions (token, user_id) VALUES (?, ?)", (token, user["id"]))
        
        return {
            "status": "success",
            "token": token,
            "user": {
                "id": user["id"],
                "username": user["username"]
            }
        }

@app.post("/api/auth/logout")
async def logout(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = authorization.split(" ")[1]
    
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sessions WHERE token = ?", (token,))
        return {"status": "success", "message": "Logged out successfully."}

@app.get("/api/auth/me")
async def get_me(authorization: Optional[str] = Header(None)):
    current_user = await get_current_user(authorization)
    return current_user

# --- Complaints Endpoints ---

@app.get("/api/complaints/me")
async def get_my_complaints(authorization: Optional[str] = Header(None)):
    current_user = await get_current_user(authorization)
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT complaints.*, users.username as citizen_name
                FROM complaints 
                LEFT JOIN users ON complaints.user_id = users.id
                WHERE complaints.user_id = ?
                ORDER BY created_at DESC
            ''', (current_user["id"],))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database query error: {str(e)}")

@app.post("/api/complaints")
async def create_complaint(
    text: str = Form(...),
    latitude: Optional[float] = Form(None),
    longitude: Optional[float] = Form(None),
    file: Optional[UploadFile] = File(None),
    authorization: Optional[str] = Header(None)
):
    # Verify Authentication
    current_user = await get_current_user(authorization)
    cleaned_text = text.strip()

    # 1. Anti-Duplicate Protection: Check if user submitted identical text recently
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id FROM complaints 
            WHERE user_id = ? AND raw_text = ? AND status = 'Pending'
        ''', (current_user["id"], cleaned_text))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail="Duplicate complaint detected! You have already registered this issue recently.")

    # 2. Heuristic Anti-Spam & Character Entropy Check
    is_spam, spam_reason = is_gibberish_or_spam(cleaned_text)
    if is_spam:
        raise HTTPException(status_code=400, detail=f"Fake/Invalid Complaint Blocked: {spam_reason}")

    analysis = None
    extraction_method = "AI"
    image_path = None
    image_tags = None

    # Handle Image Upload & HF Analysis
    if file:
        try:
            # Generate unique file path & read contents
            file_ext = os.path.splitext(file.filename)[1].lower()
            if file_ext not in [".jpg", ".jpeg", ".png", ".webp"]:
                raise HTTPException(status_code=400, detail="Invalid image type. Upload JPG, PNG or WEBP.")
                
            contents = await file.read()
            mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
            mime_type = mime_map.get(file_ext, "image/jpeg")

            # Save to disk (for local dev)
            unique_filename = f"{secrets.token_hex(8)}{file_ext}"
            full_path = os.path.join(UPLOAD_DIR, unique_filename)
            with open(full_path, "wb") as f:
                f.write(contents)
                
            # Base64 Data URL for persistent rendering on serverless platforms (Vercel)
            base64_str = base64.b64encode(contents).decode("utf-8")
            image_path = f"data:{mime_type};base64,{base64_str}"
                
            # Classify with Hugging Face Inference API + Gemini Vision Fallback
            image_tags = analyze_image_hf(contents, mime_type)
            
        except HTTPException as he:
            raise he
        except Exception as e:
            print(f"Error handling file upload: {e}")
            image_tags = "Upload processed"

    # Analyze grievance text (Gemini API with heuristics fallback)
    if api_key:
        try:
            model = get_gemini_model()
            prompt = f"Analyze the following civic waste complaint and extract the details in structured format:\n\n{text}"
            
            response = model.generate_content(
                prompt,
                generation_config=genai.GenerationConfig(
                    response_mime_type="application/json",
                    response_schema=ComplaintAnalysis,
                    temperature=0.1
                )
            )
            
            result = json.loads(response.text)
            
            # Check if Gemini flagged this complaint as fake or non-civic
            if not result.get("is_valid_civic_issue", True):
                rejection = result.get("rejection_reason", "The input text does not represent a valid civic or waste management issue.")
                raise HTTPException(status_code=400, detail=f"AI Anti-Fraud Guard: {rejection}")

            location = result.get("location", "Unknown")
            
            waste_type = result.get("waste_type", "Mixed")
            if waste_type not in ["Wet", "Dry", "Mixed"]:
                waste_type = "Mixed"
                
            severity = result.get("severity_level", "Medium")
            if severity not in ["Low", "Medium", "Critical"]:
                severity = "Medium"
                
            urgency_reason = result.get("urgency_reason", "Extracted by Gemini AI.")
            
            analysis = {
                "location": location,
                "waste_type": waste_type,
                "severity_level": severity,
                "urgency_reason": urgency_reason
            }
            
        except Exception as e:
            print(f"Gemini API Error, falling back to heuristics: {e}")
            analysis = run_fallback_analysis(text)
            extraction_method = "Fallback Rules"
    else:
        analysis = run_fallback_analysis(text)
        extraction_method = "Fallback Rules"

    # Save to SQLite
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO complaints (raw_text, location, waste_type, severity, urgency_reason, status, user_id, latitude, longitude, image_path, image_tags)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                text,
                analysis["location"],
                analysis["waste_type"],
                analysis["severity_level"],
                analysis["urgency_reason"],
                "Pending",
                current_user["id"],
                latitude,
                longitude,
                image_path,
                image_tags
            ))
            new_id = cursor.lastrowid
            
            # Fetch and return the newly created row with username
            cursor.execute('''
                SELECT complaints.*, users.username as citizen_name
                FROM complaints 
                LEFT JOIN users ON complaints.user_id = users.id
                WHERE complaints.id = ?
            ''', (new_id,))
            
            complaint_data = dict(cursor.fetchone())
            complaint_data["extraction_method"] = extraction_method
            return complaint_data
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database insert error: {str(e)}")

@app.get("/api/complaints")
async def get_complaints():
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            # Sort critical complaints first, then medium, then low, chronologically newest first
            cursor.execute('''
                SELECT complaints.*, users.username as citizen_name
                FROM complaints 
                LEFT JOIN users ON complaints.user_id = users.id
                ORDER BY 
                    CASE severity 
                        WHEN 'Critical' THEN 1 
                        WHEN 'Medium' THEN 2 
                        WHEN 'Low' THEN 3 
                        ELSE 4 
                    END ASC, 
                    created_at DESC
            ''')
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database query error: {str(e)}")

@app.patch("/api/complaints/{complaint_id}")
async def toggle_complaint_status(complaint_id: int, status: str = Body(..., embed=True)):
    if status not in ["Pending", "Resolved"]:
        raise HTTPException(status_code=400, detail="Invalid status. Must be 'Pending' or 'Resolved'.")
        
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM complaints WHERE id = ?", (complaint_id,))
            if not cursor.fetchone():
                raise HTTPException(status_code=404, detail="Complaint not found")
                
            cursor.execute("UPDATE complaints SET status = ? WHERE id = ?", (status, complaint_id))
            
            cursor.execute('''
                SELECT complaints.*, users.username as citizen_name
                FROM complaints 
                LEFT JOIN users ON complaints.user_id = users.id
                WHERE complaints.id = ?
            ''', (complaint_id,))
            return dict(cursor.fetchone())
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database update error: {str(e)}")

@app.delete("/api/complaints/{complaint_id}")
async def delete_complaint(complaint_id: int):
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM complaints WHERE id = ?", (complaint_id,))
            if not cursor.fetchone():
                raise HTTPException(status_code=404, detail="Complaint not found")
                
            cursor.execute("DELETE FROM complaints WHERE id = ?", (complaint_id,))
            return {"status": "success", "message": f"Complaint {complaint_id} deleted."}
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database delete error: {str(e)}")

# Serve uploaded files from UPLOAD_DIR
@app.get("/uploads/{filename}")
async def get_uploaded_file(filename: str):
    file_path = os.path.join(UPLOAD_DIR, filename)
    if os.path.exists(file_path):
        return FileResponse(file_path)
    raise HTTPException(status_code=404, detail="File not found")

# Serve frontend files
try:
    from api.static_content import read_static_file
except ImportError:
    try:
        from static_content import read_static_file
    except ImportError:
        def read_static_file(filename: str):
            return None

@app.get("/", response_class=HTMLResponse)
@app.get("/index.html", response_class=HTMLResponse)
async def serve_root_index():
    content = read_static_file("index.html")
    if content:
        return HTMLResponse(content=content)
    raise HTTPException(status_code=404, detail="index.html not found")

@app.get("/style.css")
async def serve_root_css():
    content = read_static_file("style.css")
    if content:
        return Response(content=content, media_type="text/css")
    raise HTTPException(status_code=404, detail="style.css not found")

@app.get("/app.js")
async def serve_root_js():
    content = read_static_file("app.js")
    if content:
        return Response(content=content, media_type="application/javascript")
    raise HTTPException(status_code=404, detail="app.js not found")

# Additional static mounting fallback
candidate_public_dirs = [
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "public"),
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "public"),
    os.path.join(os.getcwd(), "public"),
    os.path.abspath("public"),
    "/var/task/api/public",
    "/var/task/public"
]

public_dir = None
for candidate in candidate_public_dirs:
    if os.path.exists(candidate):
        public_dir = candidate
        break

try:
    from fastapi.staticfiles import StaticFiles
    if public_dir:
        app.mount("/static", StaticFiles(directory=public_dir, html=True), name="static_public")
except Exception:
    pass

if __name__ == "__main__":
    import sys
    parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    uvicorn.run("api.index:app", host="127.0.0.1", port=8000, reload=True)
