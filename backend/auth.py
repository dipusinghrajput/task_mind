import hashlib
import secrets
from database import get_db

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    hashed = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"{salt}:{hashed}"

def verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt, hashed = stored_hash.split(":")
        return hashlib.sha256((salt + password).encode()).hexdigest() == hashed
    except Exception:
        return False

def register_user(email: str, password: str, name: str = "") -> dict:
    db = get_db()
    existing = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if existing:
        db.close()
        return {"error": "Email already registered"}
    
    pw_hash = hash_password(password)
    db.execute(
        "INSERT INTO users (email, password_hash, name) VALUES (?, ?, ?)",
        (email, pw_hash, name)
    )
    db.commit()
    user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    
    # Seed default categories
    default_cats = [
        ("Academics", "#6366f1"),
        ("Startup", "#f59e0b"),
        ("Personal", "#10b981"),
        ("Health", "#ef4444"),
    ]
    for cat_name, cat_color in default_cats:
        db.execute(
            "INSERT INTO categories (user_id, name, color) VALUES (?, ?, ?)",
            (user["id"], cat_name, cat_color)
        )
    db.commit()
    db.close()
    return {"id": user["id"], "email": email, "name": name}

def login_user(email: str, password: str) -> dict:
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    db.close()
    if not user:
        return {"error": "Invalid email or password"}
    if not verify_password(password, user["password_hash"]):
        return {"error": "Invalid email or password"}
    return {"id": user["id"], "email": user["email"], "name": user["name"],
            "wake_time": user["wake_time"], "sleep_time": user["sleep_time"]}
