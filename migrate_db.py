"""
Database Migration Script
Adds missing columns and tables for OTP authentication and progressive redemption features.
Run this if the automatic migration in app.py fails.

Usage:
    python migrate_db.py
"""

import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Get database URL from environment or use default
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./poll_play.db")

# Normalize Postgres URL
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

print(f"[MIGRATE] Connecting to database: {DATABASE_URL.split('@')[-1] if '@' in DATABASE_URL else DATABASE_URL}")

# Create engine
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

def migrate():
    """Run database migrations"""
    db = SessionLocal()
    try:
        # Check if we're using PostgreSQL or SQLite
        is_postgres = 'postgresql' in str(engine.url)
        print(f"[MIGRATE] Database type: {'PostgreSQL' if is_postgres else 'SQLite'}")
        
        # Migration 1: Add successfulRedemptions column to users table
        print("\n[MIGRATE] Checking successfulRedemptions column...")
        try:
            if is_postgres:
                db.execute(text('SELECT "successfulRedemptions" FROM users LIMIT 1'))
            else:
                db.execute(text('SELECT successfulRedemptions FROM users LIMIT 1'))
            print("[MIGRATE] ✓ successfulRedemptions column already exists")
        except Exception as e:
            print(f"[MIGRATE] Column not found, adding it... ({e})")
            try:
                if is_postgres:
                    db.execute(text('ALTER TABLE users ADD COLUMN "successfulRedemptions" INTEGER DEFAULT 0'))
                else:
                    db.execute(text('ALTER TABLE users ADD COLUMN successfulRedemptions INTEGER DEFAULT 0'))
                db.commit()
                print("[MIGRATE] ✓ successfulRedemptions column added successfully")
            except Exception as e2:
                print(f"[MIGRATE] ✗ Failed to add column: {e2}")
                db.rollback()
        
        # Migration 2: Create otps table if it doesn't exist
        print("\n[MIGRATE] Checking otps table...")
        try:
            db.execute(text("SELECT * FROM otps LIMIT 1"))
            print("[MIGRATE] ✓ otps table already exists")
        except Exception as e:
            print(f"[MIGRATE] Table not found, creating it... ({e})")
            try:
                if is_postgres:
                    db.execute(text("""
                        CREATE TABLE otps (
                            id SERIAL PRIMARY KEY,
                            email VARCHAR,
                            otp_code VARCHAR,
                            created_at TIMESTAMP WITH TIME ZONE,
                            expires_at TIMESTAMP WITH TIME ZONE,
                            is_used BOOLEAN DEFAULT FALSE
                        )
                    """))
                else:
                    db.execute(text("""
                        CREATE TABLE otps (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            email VARCHAR,
                            otp_code VARCHAR,
                            created_at DATETIME,
                            expires_at DATETIME,
                            is_used BOOLEAN DEFAULT 0
                        )
                    """))
                db.commit()
                print("[MIGRATE] ✓ otps table created successfully")
            except Exception as e2:
                print(f"[MIGRATE] ✗ Failed to create table: {e2}")
                db.rollback()
        
        print("\n[MIGRATE] Migration completed!")
        
    except Exception as e:
        print(f"\n[MIGRATE] ✗ Migration failed: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    print("=" * 60)
    print("DATABASE MIGRATION SCRIPT")
    print("=" * 60)
    migrate()
    print("=" * 60)
