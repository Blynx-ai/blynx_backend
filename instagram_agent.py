import re
import json
from typing import Dict, List, Any
from bs4 import BeautifulSoup
from base_agent import BaseSocialMediaAgent
import base64
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import time

class InstagramAgent(BaseSocialMediaAgent):
    def get_platform_name(self) -> str:
        return "instagram"
    
    def extract_profile_data(self, soup: BeautifulSoup, driver=None) -> Dict[str, Any]:
        """Extract Instagram profile data"""
        profile_data = {
            'username': None,
            'full_name': None,
            'biography': None,
            'followers_count': None,
            'following_count': None,
            'posts_count': None,
            'profile_pic_url': None,
            'is_verified': False,
            'is_private': False,
            'external_url': None
        }
        
        try:
            # Try to extract from JSON-LD or script tags
            script_tags = soup.find_all('script', type='application/ld+json')
            for script in script_tags:
                try:
                    data = json.loads(script.string)
                    if '@type' in data and 'Person' in data.get('@type', ''):
                        profile_data['full_name'] = data.get('name')
                        profile_data['biography'] = data.get('description')
                        break
                except:
                    continue
            
            # Extract from meta tags
            username_meta = soup.find('meta', property='al:ios:url')
            if username_meta:
                content = username_meta.get('content', '')
                username_match = re.search(r'instagram://user\?username=([^&]+)', content)
                if username_match:
                    profile_data['username'] = username_match.group(1)
            
            # Extract title for full name if not found
            if not profile_data['full_name']:
                title_tag = soup.find('title')
                if title_tag:
                    title_text = title_tag.get_text()
                    if ' (@' in title_text:
                        profile_data['full_name'] = title_text.split(' (@')[0]
            
            # Extract follower counts from various selectors
            stat_elements = soup.find_all('span', class_=re.compile(r'.*count.*', re.I))
            for element in stat_elements:
                text = element.get_text().strip()
                if 'follower' in text.lower():
                    profile_data['followers_count'] = self._extract_number(text)
                elif 'following' in text.lower():
                    profile_data['following_count'] = self._extract_number(text)
                elif 'post' in text.lower():
                    profile_data['posts_count'] = self._extract_number(text)
            
            # Extract profile picture
            img_tags = soup.find_all('img')
            for img in img_tags:
                if 'profile' in img.get('alt', '').lower() or 'avatar' in img.get('class', []):
                    profile_data['profile_pic_url'] = img.get('src')
                    break
            
            # Check if verified
            verified_elements = soup.find_all(['span', 'div'], class_=re.compile(r'.*verif.*', re.I))
            profile_data['is_verified'] = len(verified_elements) > 0
            
            # Check if private
            private_elements = soup.find_all(text=re.compile(r'.*private.*', re.I))
            profile_data['is_private'] = len(private_elements) > 0
            
        except Exception as e:
            print(f"Error extracting Instagram profile data: {e}")
        
        return profile_data
    
    def extract_posts_data(self, soup: BeautifulSoup, driver=None) -> List[Dict[str, Any]]:
        """Extract Instagram posts data"""
        posts = []
        
        try:
            # Look for post containers
            post_elements = soup.find_all(['article', 'div'], class_=re.compile(r'.*post.*', re.I))
            
            for i, post_element in enumerate(post_elements[:20]):  # Limit to 20 posts
                post_data = {
                    'post_id': f"post_{i}",
                    'caption': None,
                    'likes_count': None,
                    'comments_count': None,
                    'image_urls': [],
                    'video_urls': [],
                    'hashtags': [],
                    'mentions': [],
                    'timestamp': None
                }
                
                # Extract caption
                caption_elements = post_element.find_all(['span', 'div'], class_=re.compile(r'.*caption.*', re.I))
                for caption_el in caption_elements:
                    text = caption_el.get_text().strip()
                    if text and len(text) > 10:
                        post_data['caption'] = text
                        break
                
                # Extract media URLs
                img_tags = post_element.find_all('img')
                for img in img_tags:
                    src = img.get('src')
                    if src and 'instagram' in src:
                        post_data['image_urls'].append(src)
                
                video_tags = post_element.find_all(['video', 'source'])
                for video in video_tags:
                    src = video.get('src')
                    if src:
                        post_data['video_urls'].append(src)
                
                # Extract hashtags and mentions from caption
                if post_data['caption']:
                    hashtags = re.findall(r'#\w+', post_data['caption'])
                    mentions = re.findall(r'@\w+', post_data['caption'])
                    post_data['hashtags'] = hashtags
                    post_data['mentions'] = mentions
                
                # Extract engagement metrics
                like_elements = post_element.find_all(text=re.compile(r'.*like.*', re.I))
                for like_text in like_elements:
                    likes = self._extract_number(like_text)
                    if likes:
                        post_data['likes_count'] = likes
                        break
                
                comment_elements = post_element.find_all(text=re.compile(r'.*comment.*', re.I))
                for comment_text in comment_elements:
                    comments = self._extract_number(comment_text)
                    if comments:
                        post_data['comments_count'] = comments
                        break
                
                posts.append(post_data)
                
        except Exception as e:
            print(f"Error extracting Instagram posts: {e}")
        
        return posts
    
    def _extract_number(self, text: str) -> int:
        """Extract number from text (handles K, M suffixes)"""
        try:
            # Remove commas and spaces
            text = re.sub(r'[,\s]', '', text)
            
            # Find number with optional K/M suffix
            match = re.search(r'(\d+(?:\.\d+)?)\s*([KkMm]?)', text)
            if match:
                number = float(match.group(1))
                suffix = match.group(2).upper()
                
                if suffix == 'K':
                    return int(number * 1000)
                elif suffix == 'M':
                    return int(number * 1000000)
                else:
                    return int(number)
        except:
            pass
        
        return None
    
    def take_screenshots(self, url: str, num_screenshots: int = 10) -> list:
        """Take headless screenshots of the given URL and return as base64 strings."""
        screenshots_base64 = []
        options = Options()
        options.headless = True
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1200,800")
        driver = webdriver.Chrome(options=options)
        try:
            driver.get(url)
            time.sleep(3)  # Wait for page to load
            for i in range(num_screenshots):
                # Optionally scroll to get different screenshots
                driver.execute_script(f"window.scrollTo(0, {i * 400});")
                time.sleep(1)
                screenshot = driver.get_screenshot_as_png()
                screenshot_b64 = base64.b64encode(screenshot).decode('utf-8')
                screenshots_base64.append(screenshot_b64)
        finally:
            driver.quit()
        return screenshots_base64

# Instagram agent instance
instagram_agent = InstagramAgent()