from datetime import datetime
from typing import Optional
from fastapi import HTTPException, Depends, status, APIRouter
from pydantic import BaseModel, HttpUrl
from auth import auth_service, UserResponse
from db import db

# Pydantic models
class BusinessCreate(BaseModel):
    name: str
    about_us: Optional[str] = None
    industry_type: Optional[str] = None
    customer_type: Optional[str] = None
    landing_page_url: Optional[str] = None
    instagram_url: Optional[str] = None
    linkedin_url: Optional[str] = None
    x_url: Optional[str] = None

class BusinessUpdate(BaseModel):
    name: Optional[str] = None
    about_us: Optional[str] = None
    industry_type: Optional[str] = None
    customer_type: Optional[str] = None
    landing_page_url: Optional[str] = None
    instagram_url: Optional[str] = None
    linkedin_url: Optional[str] = None
    x_url: Optional[str] = None

class BusinessResponse(BaseModel):
    id: int
    user_id: int
    name: str
    about_us: Optional[str]
    industry_type: Optional[str]
    customer_type: Optional[str]
    landing_page_url: Optional[str]
    instagram_url: Optional[str]
    linkedin_url: Optional[str]
    x_url: Optional[str]
    created_at: datetime
    updated_at: datetime

# Create router
router = APIRouter(prefix="/api/v1/business", tags=["business"])

class BusinessService:
    @staticmethod
    async def create_business(business_data: BusinessCreate, user_id: int) -> BusinessResponse:
        """Create a new business for the user"""
        async with db.get_connection() as conn:
            # Check if user already has a business
            existing_business = await conn.fetchrow(
                "SELECT id FROM businesses WHERE user_id = $1",
                user_id
            )
            
            if existing_business:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="User already has a business. Each user can have only one business."
                )
            
            # Insert business
            business_row = await conn.fetchrow(
                """
                INSERT INTO businesses (user_id, name, about_us, industry_type, customer_type, 
                                      landing_page_url, instagram_url, linkedin_url, x_url)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                RETURNING *
                """,
                user_id, business_data.name, business_data.about_us, 
                business_data.industry_type, business_data.customer_type,
                business_data.landing_page_url, business_data.instagram_url,
                business_data.linkedin_url, business_data.x_url
            )
            
            return BusinessResponse(**dict(business_row))
    
    @staticmethod
    async def get_business(user_id: int) -> BusinessResponse:
        """Get user's business"""
        async with db.get_connection() as conn:
            business_row = await conn.fetchrow(
                "SELECT * FROM businesses WHERE user_id = $1",
                user_id
            )
            
            if not business_row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Business not found"
                )
            
            return BusinessResponse(**dict(business_row))
    
    @staticmethod
    async def update_business(business_data: BusinessUpdate, user_id: int) -> BusinessResponse:
        """Update user's business"""
        async with db.get_connection() as conn:
            # Check if business exists
            existing_business = await conn.fetchrow(
                "SELECT id FROM businesses WHERE user_id = $1",
                user_id
            )
            
            if not existing_business:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Business not found"
                )
            
            # Build update query dynamically
            update_fields = []
            update_values = []
            param_count = 1
            
            for field, value in business_data.dict(exclude_unset=True).items():
                if value is not None:
                    update_fields.append(f"{field} = ${param_count}")
                    update_values.append(value)
                    param_count += 1
            
            if not update_fields:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="No fields to update"
                )
            
            # Add updated_at field
            update_fields.append(f"updated_at = ${param_count}")
            update_values.append(datetime.utcnow())
            param_count += 1
            
            # Add user_id for WHERE clause
            update_values.append(user_id)
            
            query = f"""
                UPDATE businesses 
                SET {', '.join(update_fields)}
                WHERE user_id = ${param_count}
                RETURNING *
            """
            
            business_row = await conn.fetchrow(query, *update_values)
            
            return BusinessResponse(**dict(business_row))
    
    @staticmethod
    async def delete_business(user_id: int) -> dict:
        """Delete user's business"""
        async with db.get_connection() as conn:
            # Check if business exists
            existing_business = await conn.fetchrow(
                "SELECT id FROM businesses WHERE user_id = $1",
                user_id
            )
            
            if not existing_business:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Business not found"
                )
            
            # Delete business
            await conn.execute(
                "DELETE FROM businesses WHERE user_id = $1",
                user_id
            )
            
            return {"message": "Business deleted successfully"}

# Create business service instance
business_service = BusinessService()

# Routes
@router.post("/", response_model=BusinessResponse)
async def create_business(
    business_data: BusinessCreate,
    current_user: UserResponse = Depends(auth_service.get_current_user)
):
    """Create a new business"""
    return await business_service.create_business(business_data, current_user.id)

@router.get("/", response_model=BusinessResponse)
async def get_business(
    current_user: UserResponse = Depends(auth_service.get_current_user)
):
    """Get current user's business"""
    return await business_service.get_business(current_user.id)

@router.put("/", response_model=BusinessResponse)
async def update_business(
    business_data: BusinessUpdate,
    current_user: UserResponse = Depends(auth_service.get_current_user)
):
    """Update current user's business"""
    return await business_service.update_business(business_data, current_user.id)

@router.delete("/")
async def delete_business(
    current_user: UserResponse = Depends(auth_service.get_current_user)
):
    """Delete current user's business"""
    return await business_service.delete_business(current_user.id)