import re
import json
from typing import Dict, List, Any
from bs4 import BeautifulSoup
from base_agent import BaseSocialMediaAgent

class LinkedInAgent(BaseSocialMediaAgent):
    def get_platform_name(self) -> str:
        return "linkedin"
    
    def extract_profile_data(self, soup: BeautifulSoup, driver=None) -> Dict[str, Any]:
        """Extract LinkedIn profile data"""
        profile_data = {
            'name': None,
            'headline': None,
            'location': None,
            'about': None,
            'connections_count': None,
            'followers_count': None,
            'profile_pic_url': None,
            'banner_url': None,
            'current_company': None,
            'education': [],
            'experience': [],
            'skills': [],
            'languages': []
        }
        
        try:
            # Extract from JSON-LD
            script_tags = soup.find_all('script', type='application/ld+json')
            for script in script_tags:
                try:
                    data = json.loads(script.string)
                    if '@type' in data and 'Person' in data.get('@type', ''):
                        profile_data['name'] = data.get('name')
                        profile_data['headline'] = data.get('description')
                        if 'worksFor' in data:
                            profile_data['current_company'] = data['worksFor'].get('name')
                        break
                except:
                    continue
            
            # Extract from meta tags
            title_meta = soup.find('meta', property='og:title')
            if title_meta and not profile_data['name']:
                title_text = title_meta.get('content', '')
                if ' | ' in title_text:
                    profile_data['name'] = title_text.split(' | ')[0]
            
            desc_meta = soup.find('meta', property='og:description')
            if desc_meta and not profile_data['headline']:
                profile_data['headline'] = desc_meta.get('content', '')
            
            image_meta = soup.find('meta', property='og:image')
            if image_meta:
                profile_data['profile_pic_url'] = image_meta.get('content', '')
            
            # Look for specific LinkedIn elements
            name_elements = soup.find_all(['h1', 'span'], class_=re.compile(r'.*name.*|.*headline.*', re.I))
            for element in name_elements:
                text = element.get_text().strip()
                if text and len(text) > 2 and not profile_data['name']:
                    profile_data['name'] = text
                    break
            
            # Extract location
            location_elements = soup.find_all(['span', 'div'], class_=re.compile(r'.*location.*|.*geo.*', re.I))
            for element in location_elements:
                text = element.get_text().strip()
                if text and len(text) > 2:
                    profile_data['location'] = text
                    break
            
            # Extract connections count
            connection_elements = soup.find_all(text=re.compile(r'.*connection.*', re.I))
            for text in connection_elements:
                connections = self._extract_number(text)
                if connections:
                    profile_data['connections_count'] = connections
                    break
            
            # Extract experience sections
            experience_sections = soup.find_all(['section', 'div'], class_=re.compile(r'.*experience.*|.*work.*', re.I))
            for section in experience_sections[:5]:  # Limit to 5 experiences
                exp_items = section.find_all(['div', 'li'], class_=re.compile(r'.*job.*|.*position.*', re.I))
                for item in exp_items:
                    exp_data = {
                        'title': None,
                        'company': None,
                        'duration': None,
                        'description': None
                    }
                    
                    # Extract job title
                    title_elements = item.find_all(['h3', 'h4', 'span'], class_=re.compile(r'.*title.*|.*role.*', re.I))
                    for title_el in title_elements:
                        text = title_el.get_text().strip()
                        if text and len(text) > 2:
                            exp_data['title'] = text
                            break
                    
                    # Extract company
                    company_elements = item.find_all(['span', 'div'], class_=re.compile(r'.*company.*|.*org.*', re.I))
                    for company_el in company_elements:
                        text = company_el.get_text().strip()
                        if text and len(text) > 2:
                            exp_data['company'] = text
                            break
                    
                    if exp_data['title'] or exp_data['company']:
                        profile_data['experience'].append(exp_data)
            
            # Extract education
            education_sections = soup.find_all(['section', 'div'], class_=re.compile(r'.*education.*|.*school.*', re.I))
            for section in education_sections[:3]:  # Limit to 3 education entries
                edu_items = section.find_all(['div', 'li'])
                for item in edu_items:
                    edu_data = {
                        'school': None,
                        'degree': None,
                        'field': None,
                        'duration': None
                    }
                    
                    # Extract school name
                    school_elements = item.find_all(['h3', 'h4', 'span'], class_=re.compile(r'.*school.*|.*university.*', re.I))
                    for school_el in school_elements:
                        text = school_el.get_text().strip()
                        if text and len(text) > 2:
                            edu_data['school'] = text
                            break
                    
                    if edu_data['school']:
                        profile_data['education'].append(edu_data)
            
        except Exception as e:
            print(f"Error extracting LinkedIn profile data: {e}")
        
        return profile_data
    
    def extract_posts_data(self, soup: BeautifulSoup, driver=None) -> List[Dict[str, Any]]:
        """Extract LinkedIn posts data"""
        posts = []
        
        try:
            # Look for post containers
            post_elements = soup.find_all(['article', 'div'], class_=re.compile(r'.*post.*|.*update.*|.*activity.*', re.I))
            
            for i, post_element in enumerate(post_elements[:15]):  # Limit to 15 posts
                post_data = {
                    'post_id': f"linkedin_post_{i}",
                    'text': None,
                    'likes_count': None,
                    'comments_count': None,
                    'shares_count': None,
                    'image_urls': [],
                    'video_urls': [],
                    'author': None,
                    'timestamp': None,
                    'post_type': None
                }
                
                # Extract post text
                text_elements = post_element.find_all(['span', 'div', 'p'], class_=re.compile(r'.*text.*|.*content.*|.*message.*', re.I))
                for text_el in text_elements:
                    text = text_el.get_text().strip()
                    if text and len(text) > 10:
                        post_data['text'] = text
                        break
                
                # Extract author
                author_elements = post_element.find_all(['span', 'a'], class_=re.compile(r'.*author.*|.*name.*', re.I))
                for author_el in author_elements:
                    text = author_el.get_text().strip()
                    if text and len(text) > 2:
                        post_data['author'] = text
                        break
                
                # Extract media URLs
                img_tags = post_element.find_all('img')
                for img in img_tags:
                    src = img.get('src')
                    if src and ('linkedin.com' in src or 'licdn.com' in src):
                        post_data['image_urls'].append(src)
                
                video_tags = post_element.find_all(['video', 'source'])
                for video in video_tags:
                    src = video.get('src')
                    if src:
                        post_data['video_urls'].append(src)
                
                # Extract engagement metrics
                engagement_elements = post_element.find_all(['span', 'div'], class_=re.compile(r'.*reaction.*|.*like.*|.*comment.*|.*share.*', re.I))
                for element in engagement_elements:
                    text = element.get_text().strip()
                    
                    if 'like' in text.lower() or 'reaction' in text.lower():
                        post_data['likes_count'] = self._extract_number(text)
                    elif 'comment' in text.lower():
                        post_data['comments_count'] = self._extract_number(text)
                    elif 'share' in text.lower() or 'repost' in text.lower():
                        post_data['shares_count'] = self._extract_number(text)
                
                # Determine post type
                if post_data['image_urls']:
                    post_data['post_type'] = 'image'
                elif post_data['video_urls']:
                    post_data['post_type'] = 'video'
                else:
                    post_data['post_type'] = 'text'
                
                posts.append(post_data)
                
        except Exception as e:
            print(f"Error extracting LinkedIn posts: {e}")
        
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

# LinkedIn agent instance
linkedin_agent = LinkedInAgent()