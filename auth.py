import os
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from fastapi import HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from passlib.context import CryptContext
import jwt
from pydantic import BaseModel, EmailStr
from dotenv import load_dotenv
from db import db

# Load environment variables
load_dotenv()

# Security configurations
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_ACCESS_TOKEN_EXPIRE_DAYS = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_DAYS", 300))

# Pydantic models
class UserRegister(BaseModel):
    username: str
    email: EmailStr
    password: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    is_active: bool
    created_at: datetime

class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    expires_in: int
    user: UserResponse

class AuthService:
    @staticmethod
    def hash_password(password: str) -> str:
        """Hash a password"""
        return pwd_context.hash(password)
    
    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """Verify a password"""
        return pwd_context.verify(plain_password, hashed_password)
    
    @staticmethod
    def create_access_token(data: Dict[str, Any]) -> str:
        """Create JWT access token"""
        to_encode = data.copy()
        expire = datetime.utcnow() + timedelta(days=JWT_ACCESS_TOKEN_EXPIRE_DAYS)
        to_encode.update({"exp": expire})
        
        encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
        return encoded_jwt
    
    @staticmethod
    def hash_token(token: str) -> str:
        """Hash token for storage"""
        return hashlib.sha256(token.encode()).hexdigest()
    
    @staticmethod
    async def register_user(user_data: UserRegister) -> UserResponse:
        """Register a new user"""
        async with db.get_connection() as conn:
            # Check if user already exists
            existing_user = await conn.fetchrow(
                "SELECT id FROM users WHERE email = $1 OR username = $2",
                user_data.email, user_data.username
            )
            
            if existing_user:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="User with this email or username already exists"
                )
            
            # Hash password
            hashed_password = AuthService.hash_password(user_data.password)
            
            # Insert user
            user_row = await conn.fetchrow(
                """
                INSERT INTO users (username, email, password_hash)
                VALUES ($1, $2, $3)
                RETURNING id, username, email, is_active, created_at
                """,
                user_data.username, user_data.email, hashed_password
            )
            
            return UserResponse(**dict(user_row))
    
    @staticmethod
    async def login_user(login_data: UserLogin) -> TokenResponse:
        """Login user and return token"""
        async with db.get_connection() as conn:
            # Get user
            user_row = await conn.fetchrow(
                "SELECT * FROM users WHERE email = $1 AND is_active = TRUE",
                login_data.email
            )
            
            if not user_row:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid credentials"
                )
            
            # Verify password
            if not AuthService.verify_password(login_data.password, user_row['password_hash']):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid credentials"
                )
            
            # Create token
            token_data = {
                "sub": str(user_row['id']),
                "email": user_row['email'],
                "username": user_row['username']
            }
            access_token = AuthService.create_access_token(token_data)
            
            # Store token hash in database for persistence
            token_hash = AuthService.hash_token(access_token)
            expires_at = datetime.utcnow() + timedelta(days=JWT_ACCESS_TOKEN_EXPIRE_DAYS)
            
            await conn.execute(
                """
                INSERT INTO user_tokens (user_id, token_hash, expires_at)
                VALUES ($1, $2, $3)
                """,
                user_row['id'], token_hash, expires_at
            )
            
            user_response = UserResponse(**{
                'id': user_row['id'],
                'username': user_row['username'],
                'email': user_row['email'],
                'is_active': user_row['is_active'],
                'created_at': user_row['created_at']
            })
            
            return TokenResponse(
                access_token=access_token,
                token_type="bearer",
                expires_in=JWT_ACCESS_TOKEN_EXPIRE_DAYS * 24 * 3600,  # Convert to seconds
                user=user_response
            )
    
    @staticmethod
    async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> UserResponse:
        """Get current user from token"""
        token = credentials.credentials
        
        try:
            # Decode JWT token
            payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
            user_id = int(payload.get("sub"))
            
            if user_id is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token"
                )
            
        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired"
            )
        except jwt.JWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token"
            )
        
        async with db.get_connection() as conn:
            # Check if token exists in database and is active
            token_hash = AuthService.hash_token(token)
            token_row = await conn.fetchrow(
                """
                SELECT ut.* FROM user_tokens ut
                WHERE ut.token_hash = $1 AND ut.is_active = TRUE AND ut.expires_at > NOW()
                """,
                token_hash
            )
            
            if not token_row:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token is invalid or expired"
                )
            
            # Get user
            user_row = await conn.fetchrow(
                "SELECT * FROM users WHERE id = $1 AND is_active = TRUE",
                user_id
            )
            
            if not user_row:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User not found"
                )
            
            return UserResponse(**{
                'id': user_row['id'],
                'username': user_row['username'],
                'email': user_row['email'],
                'is_active': user_row['is_active'],
                'created_at': user_row['created_at']
            })

# Create auth service instance
auth_service = AuthService()