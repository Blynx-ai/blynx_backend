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
            
            # Create index for better performance
            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_user_tokens_hash ON user_tokens(token_hash)
            ''')
            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_user_tokens_user_id ON user_tokens(user_id)
            ''')
            
            logger.info("Database tables created/verified successfully")

# Database instance
db = Database()