import asyncio
import logging
from datetime import datetime
from instagram_agent import instagram_agent
from x_agent import x_agent
from linkedin_agent import linkedin_agent
from db import db
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

async def get_db_connection():
    """Get database connection"""
    return await asyncpg.connect(
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT", 5432)),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        ssl=os.getenv("DB_SSL_MODE", "require")
    )

def scrape_instagram_basic(business_id: int, url: str, job_id: str):
    """Basic Instagram scraping task"""
    return asyncio.run(_scrape_basic(business_id, url, job_id, instagram_agent))

def scrape_instagram_selenium(business_id: int, url: str, job_id: str):
    """Instagram scraping with screenshots task"""
    return asyncio.run(_scrape_selenium(business_id, url, job_id, instagram_agent))

def scrape_x_basic(business_id: int, url: str, job_id: str):
    """Basic X scraping task"""
    return asyncio.run(_scrape_basic(business_id, url, job_id, x_agent))

def scrape_x_selenium(business_id: int, url: str, job_id: str):
    """X scraping with screenshots task"""
    return asyncio.run(_scrape_selenium(business_id, url, job_id, x_agent))

def scrape_linkedin_basic(business_id: int, url: str, job_id: str):
    """Basic LinkedIn scraping task"""
    return asyncio.run(_scrape_basic(business_id, url, job_id, linkedin_agent))

def scrape_linkedin_selenium(business_id: int, url: str, job_id: str):
    """LinkedIn scraping with screenshots task"""
    return asyncio.run(_scrape_selenium(business_id, url, job_id, linkedin_agent))

async def _scrape_basic(business_id: int, url: str, job_id: str, agent):
    """Common basic scraping logic"""
    conn = None
    try:
        logger.info(f"Starting basic scraping for {agent.platform_name}: {url}")
        
        # Update job status to running
        conn = await get_db_connection()
        await conn.execute(
            "UPDATE scraping_jobs SET status = 'running', updated_at = $1 WHERE job_id = $2",
            datetime.utcnow(), job_id
        )
        
        # Perform scraping
        result = agent.scrape_basic(url)
        
        # Save result to database
        scrape_id = await agent.save_scrape_result(business_id, url, result)
        
        # Update job status
        if result.get('success'):
            await conn.execute(
                """
                UPDATE scraping_jobs 
                SET status = 'completed', result = $1, updated_at = $2 
                WHERE job_id = $3
                """,
                f'{{"scrape_id": {scrape_id}, "method": "basic"}}',
                datetime.utcnow(),
                job_id
            )
            logger.info(f"Basic scraping completed for {agent.platform_name}: {url}")
        else:
            await conn.execute(
                """
                UPDATE scraping_jobs 
                SET status = 'failed', error_message = $1, updated_at = $2 
                WHERE job_id = $3
                """,
                result.get('error', 'Unknown error'),
                datetime.utcnow(),
                job_id
            )
            logger.error(f"Basic scraping failed for {agent.platform_name}: {url} - {result.get('error')}")
        
        return result
        
    except Exception as e:
        logger.error(f"Error in basic scraping task: {str(e)}")
        if conn:
            await conn.execute(
                """
                UPDATE scraping_jobs 
                SET status = 'failed', error_message = $1, updated_at = $2 
                WHERE job_id = $3
                """,
                str(e),
                datetime.utcnow(),
                job_id
            )
        raise
    finally:
        if conn:
            await conn.close()

async def _scrape_selenium(business_id: int, url: str, job_id: str, agent):
    """Common selenium scraping logic"""
    conn = None
    try:
        logger.info(f"Starting selenium scraping for {agent.platform_name}: {url}")
        
        # Update job status to running
        conn = await get_db_connection()
        await conn.execute(
            "UPDATE scraping_jobs SET status = 'running', updated_at = $1 WHERE job_id = $2",
            datetime.utcnow(), job_id
        )
        
        # Perform scraping
        result = agent.scrape_with_selenium(url)
        
        # Save result to database
        scrape_id = await agent.save_scrape_result(business_id, url, result)
        
        # Update job status
        if result.get('success'):
            await conn.execute(
                """
                UPDATE scraping_jobs 
                SET status = 'completed', result = $1, updated_at = $2 
                WHERE job_id = $3
                """,
                f'{{"scrape_id": {scrape_id}, "method": "selenium", "screenshots_count": {len(result.get("screenshots", []))}}}',
                datetime.utcnow(),
                job_id
            )
            logger.info(f"Selenium scraping completed for {agent.platform_name}: {url}")
        else:
            await conn.execute(
                """
                UPDATE scraping_jobs 
                SET status = 'failed', error_message = $1, updated_at = $2 
                WHERE job_id = $3
                """,
                result.get('error', 'Unknown error'),
                datetime.utcnow(),
                job_id
            )
            logger.error(f"Selenium scraping failed for {agent.platform_name}: {url} - {result.get('error')}")
        
        return result
        
    except Exception as e:
        logger.error(f"Error in selenium scraping task: {str(e)}")
        if conn:
            await conn.execute(
                """
                UPDATE scraping_jobs 
                SET status = 'failed', error_message = $1, updated_at = $2 
                WHERE job_id = $3
                """,
                str(e),
                datetime.utcnow(),
                job_id
            )
        raise
    finally:
        if conn:
            await conn.close()