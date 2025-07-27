import os
import asyncpg
from asyncpg import Pool
from contextlib import asynccontextmanager
from typing import Optional
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Database:
    _pool: Optional[Pool] = None
    
    @classmethod
    async def connect(cls):
        """Create database connection pool"""
        if cls._pool is None:
            try:
                cls._pool = await asyncpg.create_pool(
                    host=os.getenv("DB_HOST"),
                    port=int(os.getenv("DB_PORT", 5432)),
                    database=os.getenv("DB_NAME"),
                    user=os.getenv("DB_USER"),
                    password=os.getenv("DB_PASSWORD"),
                    ssl=os.getenv("DB_SSL_MODE", "require"),
                    min_size=1,
                    max_size=10,
                    command_timeout=60,
                )
                logger.info("Database connection pool created successfully")
                
                # Create tables if they don't exist
                await cls.create_tables()
                
            except Exception as e:
                logger.error(f"Failed to create database connection pool: {e}")
                raise
    
    @classmethod
    async def disconnect(cls):
        """Close database connection pool"""
        if cls._pool:
            await cls._pool.close()
            cls._pool = None
            logger.info("Database connection pool closed")
    
    @classmethod
    @asynccontextmanager
    async def get_connection(cls):
        """Get database connection from pool"""
        if cls._pool is None:
            await cls.connect()
        
        async with cls._pool.acquire() as connection:
            yield connection
    
    @classmethod
    async def create_tables(cls):
        """Create necessary tables"""
        async with cls.get_connection() as conn:
            # Create users table
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    email VARCHAR(255) UNIQUE NOT NULL,
                    username VARCHAR(100) UNIQUE NOT NULL,
                    password_hash VARCHAR(255) NOT NULL,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Create user_tokens table for persistent token storage
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS user_tokens (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    token_hash VARCHAR(255) NOT NULL,
                    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    is_active BOOLEAN DEFAULT TRUE
                )
            ''')
            
            # Create businesses table
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS businesses (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER UNIQUE REFERENCES users(id) ON DELETE CASCADE,
                    name VARCHAR(255) NOT NULL,
                    about_us TEXT,
                    industry_type VARCHAR(100),
                    customer_type VARCHAR(100),
                    landing_page_url VARCHAR(500),
                    instagram_url VARCHAR(500),
                    linkedin_url VARCHAR(500),
                    x_url VARCHAR(500),
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Create agent_flows table (updated with more tracking)
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS agent_flows (
                    id SERIAL PRIMARY KEY,
                    flow_id VARCHAR(255) UNIQUE NOT NULL,
                    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    business_id INTEGER REFERENCES businesses(id) ON DELETE CASCADE,
                    source_urls JSONB NOT NULL,
                    status VARCHAR(50) DEFAULT 'pending',
                    result JSONB,
                    error_message TEXT,
                    total_sources INTEGER DEFAULT 0,
                    completed_sources INTEGER DEFAULT 0,
                    failed_sources INTEGER DEFAULT 0,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Create social_media_scrapes table (updated with flow_id)
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS social_media_scrapes (
                    id SERIAL PRIMARY KEY,
                    flow_id VARCHAR(255) REFERENCES agent_flows(flow_id) ON DELETE CASCADE,
                    business_id INTEGER REFERENCES businesses(id) ON DELETE CASCADE,
                    platform VARCHAR(50) NOT NULL,
                    url VARCHAR(500) NOT NULL,
                    profile_data JSONB,
                    post_data JSONB,
                    scraping_method VARCHAR(50) NOT NULL,
                    status VARCHAR(50) DEFAULT 'pending',
                    error_message TEXT,
                    retry_count INTEGER DEFAULT 0,
                    screenshots_taken BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Create social_media_screenshots table (updated)
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS social_media_screenshots (
                    id SERIAL PRIMARY KEY,
                    scrape_id INTEGER REFERENCES social_media_scrapes(id) ON DELETE CASCADE,
                    flow_id VARCHAR(255) REFERENCES agent_flows(flow_id) ON DELETE CASCADE,
                    screenshot_order INTEGER NOT NULL,
                    screenshot_base64 TEXT NOT NULL,
                    screenshot_url TEXT,
                    scroll_position INTEGER DEFAULT 0,
                    viewport_info JSONB,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Create news_research table (NEW)
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS news_research (
                    id SERIAL PRIMARY KEY,
                    flow_id VARCHAR(255) REFERENCES agent_flows(flow_id) ON DELETE CASCADE,
                    business_id INTEGER REFERENCES businesses(id) ON DELETE CASCADE,
                    company_name VARCHAR(255) NOT NULL,
                    search_query VARCHAR(500) NOT NULL,
                    news_articles JSONB,
                    sentiment_analysis JSONB,
                    key_insights JSONB,
                    status VARCHAR(50) DEFAULT 'pending',
                    error_message TEXT,
                    total_articles INTEGER DEFAULT 0,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Create scraping_jobs table (updated with flow_id)
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS scraping_jobs (
                    id SERIAL PRIMARY KEY,
                    flow_id VARCHAR(255) REFERENCES agent_flows(flow_id) ON DELETE CASCADE,
                    business_id INTEGER REFERENCES businesses(id) ON DELETE CASCADE,
                    job_id VARCHAR(255) UNIQUE NOT NULL,
                    platform VARCHAR(50) NOT NULL,
                    url VARCHAR(500) NOT NULL,
                    job_type VARCHAR(50) NOT NULL,
                    status VARCHAR(50) DEFAULT 'queued',
                    result JSONB,
                    error_message TEXT,
                    retry_count INTEGER DEFAULT 0,
                    fallback_used BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Create flow_logs table (NEW - for detailed flow logging)
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS flow_logs (
                    id SERIAL PRIMARY KEY,
                    flow_id VARCHAR(255) REFERENCES agent_flows(flow_id) ON DELETE CASCADE,
                    agent_type VARCHAR(100) NOT NULL,
                    log_level VARCHAR(20) DEFAULT 'INFO',
                    message TEXT NOT NULL,
                    metadata JSONB,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Create indexes for better performance
            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_user_tokens_hash ON user_tokens(token_hash)
            ''')
            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_user_tokens_user_id ON user_tokens(user_id)
            ''')
            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_businesses_user_id ON businesses(user_id)
            ''')
            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_agent_flows_user_id ON agent_flows(user_id)
            ''')
            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_agent_flows_flow_id ON agent_flows(flow_id)
            ''')
            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_social_scrapes_flow_id ON social_media_scrapes(flow_id)
            ''')
            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_social_scrapes_business_id ON social_media_scrapes(business_id)
            ''')
            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_social_scrapes_platform ON social_media_scrapes(platform)
            ''')
            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_screenshots_flow_id ON social_media_screenshots(flow_id)
            ''')
            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_news_research_flow_id ON news_research(flow_id)
            ''')
            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_scraping_jobs_flow_id ON scraping_jobs(flow_id)
            ''')
            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_scraping_jobs_business_id ON scraping_jobs(business_id)
            ''')
            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_scraping_jobs_job_id ON scraping_jobs(job_id)
            ''')
            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_flow_logs_flow_id ON flow_logs(flow_id)
            ''')
            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_flow_logs_agent_type ON flow_logs(agent_type)
            ''')
            
            logger.info("Database tables created/verified successfully")

# Database instance
db = Database()