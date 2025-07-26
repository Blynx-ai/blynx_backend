from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from contextlib import asynccontextmanager

# Import our modules
from db import db
from auth import auth_service, UserRegister, UserLogin, UserResponse
from business import router as business_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await db.connect()
    yield
    # Shutdown
    await db.disconnect()

app = FastAPI(
    title="Blynx AI Backend",
    description="AI-powered backend service for Blynx",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure this properly for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(business_router)

@app.get("/")
async def root():
    """Root endpoint"""
    return {"message": "Welcome to Blynx AI Backend", "status": "running"}

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "blynx-ai-backend"}

@app.get("/api/v1/hello")
async def hello():
    """Sample API endpoint"""
    return {"message": "Hello from Blynx AI!", "version": "1.0.0"}

# Authentication endpoints
@app.post("/auth/register", response_model=UserResponse)
async def register(user_data: UserRegister):
    """Register a new user"""
    return await auth_service.register_user(user_data)

@app.post("/auth/login")
async def login(login_data: UserLogin):
    """Login user"""
    return await auth_service.login_user(login_data)

@app.get("/auth/me", response_model=UserResponse)
async def get_current_user_info(current_user: UserResponse = Depends(auth_service.get_current_user)):
    """Get current user information"""
    return current_user

@app.get("/api/v1/protected")
async def protected_route(current_user: UserResponse = Depends(auth_service.get_current_user)):
    """Example protected route"""
    return {
        "message": f"Hello {current_user.username}! This is a protected route.",
        "user_id": current_user.id,
        "email": current_user.email
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)