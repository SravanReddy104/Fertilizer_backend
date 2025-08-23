import os
from typing import Optional
from pydantic_settings import BaseSettings
from pathlib import Path

class Settings(BaseSettings):
    # Supabase configuration
    supabase_url: str = os.getenv("SUPABASE_URL", "")
    supabase_key: str = os.getenv("SUPABASE_KEY", "")
    
    # Database configuration
    database_url: str = os.getenv("DATABASE_URL", "")
    
    # Security
    secret_key: str = os.getenv("SECRET_KEY", "your-secret-key-here")
    algorithm: str = os.getenv("ALGORITHM", "HS256")
    access_token_expire_minutes: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
    
    # API configuration
    api_v1_str: str = "/api/v1"
    project_name: str = "Fertilizer Shop Dashboard"
    
    class Config:
        # Ensure we load the backend/.env regardless of current working directory
        env_file = str(Path(__file__).resolve().parents[2] / ".env")

settings = Settings()
