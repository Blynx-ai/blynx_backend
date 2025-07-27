from datetime import datetime
from typing import Dict, List, Optional
from fastapi import HTTPException, Depends, status, APIRouter
from pydantic import BaseModel, HttpUrl
from auth import auth_service, UserResponse
from business import business_service
from queue_manager import queue_manager
from db import db
import scraping_tasks

# Pydantic models
class ScrapingRequest(BaseModel):
    platform: str  # instagram, x, linkedin
    url: str
    method: str  # basic, selenium

class ScrapingJobResponse(BaseModel):
    job_id: str
    platform: str
    url: str
    method: str
    status: str
    created_at: datetime

class ScrapingResultResponse(BaseModel):
    id: int
    platform: str
    url: str
    profile_data: Dict
    post_data: List[Dict]
    scraping_method: str
    status: str
    created_at: datetime
    screenshots_count: Optional[int] = 0

# Create router
router = APIRouter(prefix="/api/v1/scraping", tags=["scraping"])

class ScrapingService:
    PLATFORM_AGENTS = {
        'instagram': {
            'basic': scraping_tasks.scrape_instagram_basic,
            'selenium': scraping_tasks.scrape_instagram_selenium
        },
        'x': {
            'basic': scraping_tasks.scrape_x_basic,
            'selenium': scraping_tasks.scrape_x_selenium
        },
        'linkedin': {
            'basic': scraping_tasks.scrape_linkedin_basic,
            'selenium': scraping_tasks.scrape_linkedin_selenium
        }
    }
    
    @staticmethod
    async def start_scraping_job(request: ScrapingRequest, business_id: int) -> ScrapingJobResponse:
        """Start a scraping job"""
        # Validate platform and method
        if request.platform not in ScrapingService.PLATFORM_AGENTS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported platform: {request.platform}"
            )
        
        if request.method not in ScrapingService.PLATFORM_AGENTS[request.platform]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported method '{request.method}' for platform '{request.platform}'"
            )
        
        # Get the task function
        task_func = ScrapingService.PLATFORM_AGENTS[request.platform][request.method]
        
        # Enqueue the job
        try:
            job_id = queue_manager.enqueue_job(task_func, business_id, request.url, None)
            
            # Save job to database
            async with db.get_connection() as conn:
                await conn.execute(
                    """
                    INSERT INTO scraping_jobs (business_id, job_id, platform, url, job_type, status)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    business_id, job_id, request.platform, request.url, request.method, 'queued'
                )
                
                # Update the job_id in the task parameters
                queue_manager.enqueue_job(task_func, business_id, request.url, job_id)
            
            return ScrapingJobResponse(
                job_id=job_id,
                platform=request.platform,
                url=request.url,
                method=request.method,
                status='queued',
                created_at=datetime.utcnow()
            )
            
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to start scraping job: {str(e)}"
            )
    
    @staticmethod
    async def get_job_status(job_id: str, business_id: int) -> Dict:
        """Get job status"""
        async with db.get_connection() as conn:
            job_row = await conn.fetchrow(
                "SELECT * FROM scraping_jobs WHERE job_id = $1 AND business_id = $2",
                job_id, business_id
            )
            
            if not job_row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Job not found"
                )
            
            # Get RQ job status
            rq_status = queue_manager.get_job_status(job_id)
            
            return {
                'job_id': job_row['job_id'],
                'platform': job_row['platform'],
                'url': job_row['url'],
                'job_type': job_row['job_type'],
                'status': job_row['status'],
                'result': job_row['result'],
                'error_message': job_row['error_message'],
                'created_at': job_row['created_at'],
                'updated_at': job_row['updated_at'],
                'rq_status': rq_status
            }
    
    @staticmethod
    async def get_scraping_results(business_id: int, platform: Optional[str] = None) -> List[ScrapingResultResponse]:
        """Get scraping results for a business"""
        async with db.get_connection() as conn:
            if platform:
                query = """
                    SELECT s.*, 
                           (SELECT COUNT(*) FROM social_media_screenshots ss WHERE ss.scrape_id = s.id) as screenshots_count
                    FROM social_media_scrapes s 
                    WHERE s.business_id = $1 AND s.platform = $2
                    ORDER BY s.created_at DESC
                """
                rows = await conn.fetch(query, business_id, platform)
            else:
                query = """
                    SELECT s.*,
                           (SELECT COUNT(*) FROM social_media_screenshots ss WHERE ss.scrape_id = s.id) as screenshots_count
                    FROM social_media_scrapes s 
                    WHERE s.business_id = $1
                    ORDER BY s.created_at DESC
                """
                rows = await conn.fetch(query, business_id)
            
            results = []
            for row in rows:
                results.append(ScrapingResultResponse(
                    id=row['id'],
                    platform=row['platform'],
                    url=row['url'],
                    profile_data=row['profile_data'] or {},
                    post_data=row['post_data'] or [],
                    scraping_method=row['scraping_method'],
                    status=row['status'],
                    created_at=row['created_at'],
                    screenshots_count=row['screenshots_count']
                ))
            
            return results
    
    @staticmethod
    async def get_screenshots(scrape_id: int, business_id: int) -> List[Dict]:
        """Get screenshots for a scraping result"""
        async with db.get_connection() as conn:
            # Verify scrape belongs to business
            scrape_row = await conn.fetchrow(
                "SELECT id FROM social_media_scrapes WHERE id = $1 AND business_id = $2",
                scrape_id, business_id
            )
            
            if not scrape_row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Scrape result not found"
                )
            
            # Get screenshots
            screenshot_rows = await conn.fetch(
                """
                SELECT screenshot_order, screenshot_base64, screenshot_url, created_at
                FROM social_media_screenshots 
                WHERE scrape_id = $1
                ORDER BY screenshot_order
                """,
                scrape_id
            )
            
            return [dict(row) for row in screenshot_rows]

# Create scraping service instance
scraping_service = ScrapingService()

# Routes
@router.post("/start", response_model=ScrapingJobResponse)
async def start_scraping(
    request: ScrapingRequest,
    current_user: UserResponse = Depends(auth_service.get_current_user)
):
    """Start a social media scraping job"""
    # Get user's business
    business = await business_service.get_business(current_user.id)
    
    return await scraping_service.start_scraping_job(request, business.id)

@router.get("/jobs/{job_id}")
async def get_job_status(
    job_id: str,
    current_user: UserResponse = Depends(auth_service.get_current_user)
):
    """Get scraping job status"""
    business = await business_service.get_business(current_user.id)
    
    return await scraping_service.get_job_status(job_id, business.id)

@router.get("/results", response_model=List[ScrapingResultResponse])
async def get_scraping_results(
    platform: Optional[str] = None,
    current_user: UserResponse = Depends(auth_service.get_current_user)
):
    """Get scraping results"""
    business = await business_service.get_business(current_user.id)
    
    return await scraping_service.get_scraping_results(business.id, platform)

@router.get("/results/{scrape_id}/screenshots")
async def get_screenshots(
    scrape_id: int,
    current_user: UserResponse = Depends(auth_service.get_current_user)
):
    """Get screenshots for a scraping result"""
    business = await business_service.get_business(current_user.id)
    
    return await scraping_service.get_screenshots(scrape_id, business.id)