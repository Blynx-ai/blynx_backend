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
from db import db

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
    
    async def scrape_with_fallback(self, url: str, flow_id: str = None, max_retries: int = 2) -> Dict[str, Any]:
        """
        Scrape with automatic fallback to headless browser + screenshots if basic scraping fails
        """
        retry_count = 0
        last_error = None
        
        while retry_count <= max_retries:
            try:
                if retry_count == 0:
                    # First attempt: Basic scraping
                    await self._log_scraping_event(flow_id, "INFO", f"Attempting basic scraping for {url}")
                    result = self.scrape_basic(url)
                    
                    if result.get('success') and self._is_valid_result(result):
                        await self._log_scraping_event(flow_id, "INFO", f"Basic scraping successful for {url}")
                        return result
                    else:
                        raise Exception("Basic scraping failed or returned invalid data")
                        
                else:
                    # Fallback: Selenium with screenshots
                    await self._log_scraping_event(flow_id, "INFO", f"Fallback attempt {retry_count}: Using headless browser with screenshots for {url}")
                    result = self.scrape_with_selenium_enhanced(url)
                    
                    if result.get('success'):
                        await self._log_scraping_event(flow_id, "INFO", f"Headless browser scraping successful for {url}")
                        result['fallback_used'] = True
                        result['retry_count'] = retry_count
                        return result
                    else:
                        raise Exception("Headless browser scraping failed")
                        
            except Exception as e:
                last_error = e
                retry_count += 1
                await self._log_scraping_event(flow_id, "WARNING", f"Attempt {retry_count} failed for {url}: {str(e)}")
                
                if retry_count <= max_retries:
                    await asyncio.sleep(2 ** retry_count)  # Exponential backoff
        
        # All attempts failed
        await self._log_scraping_event(flow_id, "ERROR", f"All scraping attempts failed for {url}")
        return {
            'success': False,
            'error': str(last_error),
            'retry_count': retry_count - 1,
            'timestamp': datetime.utcnow().isoformat()
        }
    
    def _is_valid_result(self, result: Dict[str, Any]) -> bool:
        """Check if scraping result contains meaningful data"""
        if not result.get('success'):
            return False
            
        profile_data = result.get('profile_data', {})
        posts_data = result.get('posts_data', [])
        
        # Check if we have at least some profile data or posts
        has_profile_data = any(v for v in profile_data.values() if v)
        has_posts_data = len(posts_data) > 0
        
        return has_profile_data or has_posts_data
    
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
    
    def scrape_with_selenium_enhanced(self, url: str, num_screenshots: int = 15) -> Dict[str, Any]:
        """Enhanced Selenium scraping with better screenshot handling"""
        driver = None
        try:
            options = self.get_chrome_options()
            driver = webdriver.Chrome(options=options)
            
            driver.get(url)
            time.sleep(5)  # Wait for page to load
            
            # Get page dimensions
            page_height = driver.execute_script("return document.body.scrollHeight")
            viewport_height = driver.execute_script("return window.innerHeight")
            
            # Take screenshots with intelligent scrolling
            screenshots = []
            scroll_positions = self._calculate_scroll_positions(page_height, viewport_height, num_screenshots)
            
            for i, position in enumerate(scroll_positions):
                try:
                    # Scroll to position
                    driver.execute_script(f"window.scrollTo(0, {position});")
                    time.sleep(2)  # Wait for content to load
                    
                    # Take screenshot
                    screenshot = driver.get_screenshot_as_base64()
                    screenshots.append({
                        'order': i + 1,
                        'base64': screenshot,
                        'url': driver.current_url,
                        'scroll_position': position,
                        'viewport_info': {
                            'width': driver.execute_script("return window.innerWidth"),
                            'height': driver.execute_script("return window.innerHeight"),
                            'page_height': page_height
                        }
                    })
                    
                except Exception as e:
                    logger.warning(f"Error taking screenshot {i+1}: {e}")
                    continue
            
            # Get page source for data extraction
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            
            profile_data = self.extract_profile_data(soup, driver)
            posts_data = self.extract_posts_data(soup, driver)
            
            return {
                'success': True,
                'profile_data': profile_data,
                'posts_data': posts_data,
                'screenshots': screenshots,
                'method': 'selenium_enhanced',
                'page_info': {
                    'page_height': page_height,
                    'viewport_height': viewport_height,
                    'total_screenshots': len(screenshots)
                },
                'timestamp': datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Enhanced Selenium scraping failed for {url}: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'method': 'selenium_enhanced',
                'timestamp': datetime.utcnow().isoformat()
            }
        finally:
            if driver:
                driver.quit()
    
    def _calculate_scroll_positions(self, page_height: int, viewport_height: int, num_screenshots: int) -> List[int]:
        """Calculate optimal scroll positions for screenshots"""
        if page_height <= viewport_height:
            return [0]  # Page fits in one viewport
        
        positions = []
        max_scroll = page_height - viewport_height
        
        if num_screenshots == 1:
            positions = [0]
        elif num_screenshots == 2:
            positions = [0, max_scroll]
        else:
            # Distribute positions evenly
            step = max_scroll / (num_screenshots - 1)
            positions = [int(i * step) for i in range(num_screenshots)]
            positions[-1] = max_scroll  # Ensure last position is exactly at bottom
        
        return positions
    
    async def save_scrape_result_enhanced(self, business_id: int, url: str, result: Dict[str, Any], flow_id: str = None) -> int:
        """Enhanced save scrape result with flow_id tracking"""
        async with db.get_connection() as conn:
            try:
                # Insert scrape record
                scrape_id = await conn.fetchval(
                    """
                    INSERT INTO social_media_scrapes 
                    (flow_id, business_id, platform, url, profile_data, post_data, scraping_method, 
                     status, error_message, retry_count, screenshots_taken)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                    RETURNING id
                    """,
                    flow_id,
                    business_id,
                    self.platform_name,
                    url,
                    json.dumps(result.get('profile_data', {})),
                    json.dumps(result.get('posts_data', [])),
                    result.get('method', 'unknown'),
                    'completed' if result.get('success') else 'failed',
                    result.get('error'),
                    result.get('retry_count', 0),
                    bool(result.get('screenshots'))
                )
                
                # Save screenshots if available
                if result.get('screenshots'):
                    for screenshot in result['screenshots']:
                        await conn.execute(
                            """
                            INSERT INTO social_media_screenshots 
                            (scrape_id, flow_id, screenshot_order, screenshot_base64, screenshot_url, 
                             scroll_position, viewport_info)
                            VALUES ($1, $2, $3, $4, $5, $6, $7)
                            """,
                            scrape_id,
                            flow_id,
                            screenshot['order'],
                            screenshot['base64'],
                            screenshot['url'],
                            screenshot.get('scroll_position', 0),
                            json.dumps(screenshot.get('viewport_info', {}))
                        )
                
                return scrape_id
                
            except Exception as e:
                logger.error(f"Error saving scrape result: {e}")
                raise
    
    async def _log_scraping_event(self, flow_id: str, level: str, message: str):
        """Log scraping events to flow logs"""
        if not flow_id:
            return
            
        try:
            async with db.get_connection() as conn:
                await conn.execute(
                    """
                    INSERT INTO flow_logs (flow_id, agent_type, log_level, message)
                    VALUES ($1, $2, $3, $4)
                    """,
                    flow_id, f"{self.platform_name.upper()}_SCRAPER", level, message
                )
        except Exception as e:
            logger.error(f"Error logging scraping event: {e}")
    
    # Keep the original methods for backward compatibility
    def scrape_with_selenium(self, url: str) -> Dict[str, Any]:
        """Original selenium method for backward compatibility"""
        return self.scrape_with_selenium_enhanced(url, 10)
    
    async def save_scrape_result(self, business_id: int, url: str, result: Dict[str, Any]) -> int:
        """Original save method for backward compatibility"""
        return await self.save_scrape_result_enhanced(business_id, url, result)