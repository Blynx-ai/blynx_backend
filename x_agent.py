import re
import json
from typing import Dict, List, Any
from bs4 import BeautifulSoup
from base_agent import BaseSocialMediaAgent

class XAgent(BaseSocialMediaAgent):
    def get_platform_name(self) -> str:
        return "x"
    
    def extract_profile_data(self, soup: BeautifulSoup, driver=None) -> Dict[str, Any]:
        """Extract X (Twitter) profile data"""
        profile_data = {
            'username': None,
            'display_name': None,
            'biography': None,
            'followers_count': None,
            'following_count': None,
            'tweets_count': None,
            'profile_pic_url': None,
            'banner_url': None,
            'is_verified': False,
            'is_protected': False,
            'location': None,
            'website': None,
            'joined_date': None
        }
        
        try:
            # Extract from meta tags
            username_meta = soup.find('meta', property='og:url')
            if username_meta:
                url = username_meta.get('content', '')
                username_match = re.search(r'x\.com/([^/]+)', url)
                if username_match:
                    profile_data['username'] = username_match.group(1)
            
            # Extract display name from title or og:title
            title_meta = soup.find('meta', property='og:title')
            if title_meta:
                profile_data['display_name'] = title_meta.get('content', '').split(' (@')[0]
            
            # Extract description
            desc_meta = soup.find('meta', property='og:description')
            if desc_meta:
                profile_data['biography'] = desc_meta.get('content', '')
            
            # Extract profile image
            image_meta = soup.find('meta', property='og:image')
            if image_meta:
                profile_data['profile_pic_url'] = image_meta.get('content', '')
            
            # Look for stat elements
            stat_elements = soup.find_all(['span', 'div'], attrs={'data-testid': re.compile(r'.*stat.*', re.I)})
            for element in stat_elements:
                text = element.get_text().strip()
                parent_text = element.parent.get_text().strip() if element.parent else ''
                
                if 'follower' in parent_text.lower():
                    profile_data['followers_count'] = self._extract_number(text)
                elif 'following' in parent_text.lower():
                    profile_data['following_count'] = self._extract_number(text)
                elif 'tweet' in parent_text.lower() or 'post' in parent_text.lower():
                    profile_data['tweets_count'] = self._extract_number(text)
            
            # Check for verification badge
            verified_elements = soup.find_all(['svg', 'span'], attrs={'aria-label': re.compile(r'.*verif.*', re.I)})
            profile_data['is_verified'] = len(verified_elements) > 0
            
            # Check if protected
            protected_elements = soup.find_all(text=re.compile(r'.*protected.*|.*private.*', re.I))
            profile_data['is_protected'] = len(protected_elements) > 0
            
        except Exception as e:
            print(f"Error extracting X profile data: {e}")
        
        return profile_data
    
    def extract_posts_data(self, soup: BeautifulSoup, driver=None) -> List[Dict[str, Any]]:
        """Extract X (Twitter) posts data"""
        posts = []
        
        try:
            # Look for tweet/post containers
            post_elements = soup.find_all(['article', 'div'], attrs={'data-testid': re.compile(r'.*tweet.*|.*post.*', re.I)})
            
            for i, post_element in enumerate(post_elements[:20]):  # Limit to 20 posts
                post_data = {
                    'post_id': f"tweet_{i}",
                    'text': None,
                    'retweets_count': None,
                    'likes_count': None,
                    'replies_count': None,
                    'quotes_count': None,
                    'image_urls': [],
                    'video_urls': [],
                    'hashtags': [],
                    'mentions': [],
                    'urls': [],
                    'timestamp': None,
                    'is_retweet': False,
                    'is_reply': False
                }
                
                # Extract tweet text
                text_elements = post_element.find_all(['span', 'div'], attrs={'data-testid': 'tweetText'})
                if not text_elements:
                    text_elements = post_element.find_all(['span', 'div'], class_=re.compile(r'.*tweet.*text.*', re.I))
                
                for text_el in text_elements:
                    text = text_el.get_text().strip()
                    if text and len(text) > 5:
                        post_data['text'] = text
                        break
                
                # Extract media URLs
                img_tags = post_element.find_all('img')
                for img in img_tags:
                    src = img.get('src')
                    if src and ('pbs.twimg.com' in src or 'x.com' in src):
                        post_data['image_urls'].append(src)
                
                video_tags = post_element.find_all(['video', 'source'])
                for video in video_tags:
                    src = video.get('src')
                    if src:
                        post_data['video_urls'].append(src)
                
                # Extract engagement metrics
                engagement_elements = post_element.find_all(['span', 'div'], attrs={'data-testid': re.compile(r'.*like.*|.*retweet.*|.*reply.*', re.I)})
                for element in engagement_elements:
                    text = element.get_text().strip()
                    test_id = element.get('data-testid', '').lower()
                    
                    if 'like' in test_id:
                        post_data['likes_count'] = self._extract_number(text)
                    elif 'retweet' in test_id:
                        post_data['retweets_count'] = self._extract_number(text)
                    elif 'reply' in test_id:
                        post_data['replies_count'] = self._extract_number(text)
                
                # Extract hashtags, mentions, and URLs from text
                if post_data['text']:
                    hashtags = re.findall(r'#\w+', post_data['text'])
                    mentions = re.findall(r'@\w+', post_data['text'])
                    urls = re.findall(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', post_data['text'])
                    
                    post_data['hashtags'] = hashtags
                    post_data['mentions'] = mentions
                    post_data['urls'] = urls
                
                # Check if retweet or reply
                rt_elements = post_element.find_all(text=re.compile(r'.*retweeted.*', re.I))
                post_data['is_retweet'] = len(rt_elements) > 0
                
                reply_elements = post_element.find_all(text=re.compile(r'.*replying to.*', re.I))
                post_data['is_reply'] = len(reply_elements) > 0
                
                posts.append(post_data)
                
        except Exception as e:
            print(f"Error extracting X posts: {e}")
        
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

# X agent instance
x_agent = XAgent()