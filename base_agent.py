import asyncio
import base64
import json
import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, List, Optional, Any
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
from bs4 import BeautifulSoup
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

class BaseSocialMediaAgent(ABC):
    def __init__(self):
        self.platform_name = self.get_platform_name()
    
    @abstractmethod
    def get_platform_name(self) -> str:
        """Return the platform name"""
        pass
    
    @abstractmethod
    def extract_profile_data(self, soup: BeautifulSoup, driver=None) -> Dict[str, Any]:
        """Extract profile data specific to the platform"""
        pass
    
    @abstractmethod
    def extract_posts_data(self, soup: BeautifulSoup, driver=None) -> List[Dict[str, Any]]:
        """Extract posts data specific to the platform"""
        pass
    
    def get_chrome_options(self) -> Options:
        """Get Chrome options for headless browsing"""
        options = Options()
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--disable-extensions')
        options.add_argument('--disable-plugins')
        options.add_argument('--disable-images')
        options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36')
        return options
    
    async def get_db_connection(self):
        """Get database connection"""
        return await asyncpg.connect(
            host=os.getenv("DB_HOST"),
            port=int(os.getenv("DB_PORT", 5432)),
            database=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            ssl=os.getenv("DB_SSL_MODE", "require")
        )
    
    def scrape_basic(self, url: str) -> Dict[str, Any]:
        """Basic scraping using requests and BeautifulSoup"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            profile_data = self.extract_profile_data(soup)
            posts_data = self.extract_posts_data(soup)
            
            return {
                'success': True,
                'profile_data': profile_data,
                'posts_data': posts_data,
                'method': 'basic',
                'timestamp': datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Basic scraping failed for {url}: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'method': 'basic',
                'timestamp': datetime.utcnow().isoformat()
            }
    
    def scrape_with_selenium(self, url: str) -> Dict[str, Any]:
        """Advanced scraping using Selenium with screenshots"""
        driver = None
        try:
            options = self.get_chrome_options()
            driver = webdriver.Chrome(options=options)
            
            driver.get(url)
            time.sleep(5)  # Wait for page to load
            
            # Scroll and take screenshots
            screenshots = []
            for i in range(10):
                # Take screenshot
                screenshot = driver.get_screenshot_as_base64()
                screenshots.append({
                    'order': i + 1,
                    'base64': screenshot,
                    'url': driver.current_url
                })
                
                # Scroll down
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(2)
            
            # Get page source for data extraction
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            
            profile_data = self.extract_profile_data(soup, driver)
            posts_data = self.extract_posts_data(soup, driver)
            
            return {
                'success': True,
                'profile_data': profile_data,
                'posts_data': posts_data,
                'screenshots': screenshots,
                'method': 'selenium',
                'timestamp': datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Selenium scraping failed for {url}: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'method': 'selenium',
                'timestamp': datetime.utcnow().isoformat()
            }
        finally:
            if driver:
                driver.quit()
    
    async def save_scrape_result(self, business_id: int, url: str, result: Dict[str, Any]) -> int:
        """Save scrape result to database"""
        conn = await self.get_db_connection()
        try:
            # Insert scrape record
            scrape_id = await conn.fetchval(
                """
                INSERT INTO social_media_scrapes 
                (business_id, platform, url, profile_data, post_data, scraping_method, status, error_message)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING id
                """,
                business_id,
                self.platform_name,
                url,
                json.dumps(result.get('profile_data', {})),
                json.dumps(result.get('posts_data', [])),
                result.get('method', 'unknown'),
                'completed' if result.get('success') else 'failed',
                result.get('error')
            )
            
            # Save screenshots if available
            if result.get('screenshots'):
                for screenshot in result['screenshots']:
                    await conn.execute(
                        """
                        INSERT INTO social_media_screenshots 
                        (scrape_id, screenshot_order, screenshot_base64, screenshot_url)
                        VALUES ($1, $2, $3, $4)
                        """,
                        scrape_id,
                        screenshot['order'],
                        screenshot['base64'],
                        screenshot['url']
                    )
            
            return scrape_id
            
        finally:
            await conn.close()