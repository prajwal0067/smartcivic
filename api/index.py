import os
import base64
import io
try:
    from PIL import Image
except ImportError:
    Image = None
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
EMBEDDED_KEY = "AIzaSyDex-h1iHO5tgZMSHyfV2OP3h5jF2zqj4Q"
key_candidates = [
    "AIzaSyDex-h1iHO5tgZMSHyfV2OP3h5jF2z.txt",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "AIzaSyDex-h1iHO5tgZMSHyfV2OP3h5jF2z.txt"),
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "AIzaSyDex-h1iHO5tgZMSHyfV2OP3h5jF2z.txt"),
    os.path.join(os.getcwd(), "AIzaSyDex-h1iHO5tgZMSHyfV2OP3h5jF2z.txt"),
    os.path.join(os.getcwd(), "api", "AIzaSyDex-h1iHO5tgZMSHyfV2OP3h5jF2z.txt"),
    "/var/task/api/AIzaSyDex-h1iHO5tgZMSHyfV2OP3h5jF2z.txt",
    "/var/task/AIzaSyDex-h1iHO5tgZMSHyfV2OP3h5jF2z.txt",
]

api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GEMINI_KEY")
if not api_key:
    for candidate in key_candidates:
        if os.path.exists(candidate):
            try:
                with open(candidate, "r") as f:
                    api_key = f.read().strip()
                if api_key:
                    break
            except Exception as e:
                print(f"Error reading API key from {candidate}: {e}")

if not api_key:
    api_key = EMBEDDED_KEY

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

# 6. Pure AI Photo Analysis & Verification (Gemini Vision / Hugging Face)
def analyze_photo_with_ai(image_bytes: bytes, mime_type: str = "image/jpeg") -> tuple[bool, str, str, str, str]:
    """
    Analyzes the uploaded photo purely using Gemini Vision API & HuggingFace Inference API.
    Returns: (is_real_waste, tags_description, visual_severity, visual_urgency_reason, rejection_reason)
    """
    if api_key:
        try:
            model = get_gemini_model()
            if model:
                prompt = (
                    "You are an AI Public Sanitation & Civic Inspector. Analyze this uploaded image carefully.\n"
                    "Evaluate two things:\n"
                    "1. Is this photo showing a real civic waste issue, garbage dump, litter, waste bin overflow, or public cleanliness hazard? "
                    "Set 'is_real_waste' to false if the photo is a selfie, a person's face/body, a pet, an indoor clean room, a graphic, or an unrelated object.\n"
                    "2. Assess the urgency/severity level of the waste visible in the photo ('Low', 'Medium', or 'Critical') and provide a brief urgency reason.\n\n"
                    "Output ONLY a valid raw JSON object with keys:\n"
                    "{\n"
                    '  "is_real_waste": boolean,\n'
                    '  "rejection_reason": "explanation if false, otherwise null",\n'
                    '  "detected_tags": "comma-separated 2-3 visible tags with scores, e.g. Garbage Dump (94%), Plastic Litter (85%)",\n'
                    '  "visual_severity": "Low" or "Medium" or "Critical",\n'
                    '  "visual_urgency_reason": "explanation of visual risk and urgency"\n'
                    "}"
                )
                
                image_input = None
                if Image:
                    try:
                        image_input = Image.open(io.BytesIO(image_bytes))
                    except Exception:
                        image_input = None
                if not image_input:
                    image_input = {"mime_type": mime_type, "data": image_bytes}

                response = model.generate_content(
                    [prompt, image_input],
                    generation_config={"response_mime_type": "application/json", "temperature": 0.1}
                )
                if response and response.text:
                    res = json.loads(response.text)
                    is_real = res.get("is_real_waste", True)
                    tags = res.get("detected_tags", "Waste Photo Analyzed via Gemini Vision")
                    severity = res.get("visual_severity", "Medium")
                    if severity not in ["Low", "Medium", "Critical"]:
                        severity = "Medium"
                    reason = res.get("rejection_reason", "AI Vision identified photo as non-waste or selfie.")
                    urgency_exp = res.get("visual_urgency_reason", "Urgency evaluated by Gemini Vision AI.")
                    return is_real, tags, severity, urgency_exp, reason
        except Exception as e:
    # If Gemini API key is missing, revoked, or fails
    return False, "Gemini Vision API Required", "Low", "", "Gemini API key is missing or revoked. Please provide a working Gemini API key to enable AI vision photo verification."


# 7. Pure AI Grievance Text Analysis (Gemini Text API)
def analyze_text_with_ai(text: str) -> dict:
    """
    Analyzes citizen grievance text purely using Gemini AI API.
    """
    cleaned = text.strip()
    if len(cleaned) < 4:
        raise HTTPException(status_code=400, detail="Complaint text is too short. Please describe the grievance clearly.")

    if api_key:
        try:
            model = get_gemini_model()
            if model:
                prompt = f"""You are an expert AI Civic Intelligence Engine for SmartCivic. Analyze this citizen complaint text:
"{cleaned}"

Output ONLY a valid raw JSON object with keys:
{{
  "is_valid_civic_issue": boolean (true if genuine civic/waste/sanitation grievance; false if gibberish, spam, test text, keyboard smash, or out-of-scope),
  "rejection_reason": "explanation if is_valid_civic_issue is false, otherwise null",
  "location": "extracted street/landmark/neighborhood/city or Unknown",
  "waste_type": "Wet" or "Dry" or "Mixed",
  "severity_level": "Low" or "Medium" or "Critical",
  "urgency_reason": "explanation of severity and priority"
}}"""
                response = model.generate_content(
                    prompt,
                    generation_config={"response_mime_type": "application/json", "temperature": 0.1}
                )
                if response and response.text:
                    res = json.loads(response.text)
                    if not res.get("is_valid_civic_issue", True):
                        reason = res.get("rejection_reason", "Text was identified as non-civic or invalid by AI.")
                        raise HTTPException(status_code=400, detail=f"AI Grievance Shield: {reason}")

                    loc = res.get("location", "Unknown")
                    w_type = res.get("waste_type", "Mixed")
                    if w_type not in ["Wet", "Dry", "Mixed"]:
                        w_type = "Mixed"
                    sev = res.get("severity_level", "Medium")
                    if sev not in ["Low", "Medium", "Critical"]:
                        sev = "Medium"
                    urg_exp = res.get("urgency_reason", "Evaluated by Gemini AI Engine.")

                    return {
                        "location": loc,
                        "waste_type": w_type,
                        "severity_level": sev,
                        "urgency_reason": urg_exp
                    }
        except HTTPException as he:
            raise he
        except Exception as e:
            print(f"Gemini Text API Exception: {e}")

    return {
        "location": "Unknown",
        "waste_type": "Mixed",
        "severity_level": "Medium",
        "urgency_reason": "Processed via AI Engine."
    }

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
        image_input = None
        if Image:
            try:
                image_input = Image.open(io.BytesIO(image_bytes))
            except Exception:
                image_input = None
        if not image_input:
            image_input = {"mime_type": mime_type, "data": image_bytes}

        response = model.generate_content([prompt, image_input])
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
        image_input = None
        if Image:
            try:
                image_input = Image.open(io.BytesIO(image_bytes))
            except Exception:
                image_input = None
        if not image_input:
            image_input = {"mime_type": mime_type, "data": image_bytes}

        response = model.generate_content([prompt, image_input])
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

    extraction_method = "Gemini AI Engine"
    image_path = None
    image_tags = None
    visual_sev = "Low"
    visual_urg = None

    # 2. Pure AI Photo Upload Verification & Visual Risk Assessment
    if file:
        try:
            file_ext = os.path.splitext(file.filename)[1].lower()
            if file_ext not in [".jpg", ".jpeg", ".png", ".webp"]:
                raise HTTPException(status_code=400, detail="Invalid image format. Please upload JPG, PNG or WEBP.")
                
            contents = await file.read()
            mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
            mime_type = mime_map.get(file_ext, "image/jpeg")

            # Data URL for persistent rendering
            base64_str = base64.b64encode(contents).decode("utf-8")
            image_path = f"data:{mime_type};base64,{base64_str}"
                
            # Pure AI Vision Analysis: Detect Fake/Real photo + Visual Urgency
            is_real, tags_out, vis_sev, vis_urg, img_rejection = analyze_photo_with_ai(contents, mime_type)
            if not is_real:
                raise HTTPException(status_code=400, detail=f"AI Photo Verification Failed: {img_rejection}")
            
            image_tags = tags_out
            visual_sev = vis_sev
            visual_urg = vis_urg
            
        except HTTPException as he:
            raise he
        except Exception as e:
            print(f"Error handling file upload: {e}")
            image_tags = "Photo Processed via AI"

    # 3. Pure AI Text Grievance & Urgency Analysis
    analysis = analyze_text_with_ai(cleaned_text)

    # 4. Dynamic Merging of Visual & Text AI Urgency
    if visual_sev == "Critical" or analysis["severity_level"] == "Critical":
        analysis["severity_level"] = "Critical"

    if visual_urg:
        analysis["urgency_reason"] = f"{analysis['urgency_reason']} [Visual AI: {visual_urg}]"

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
