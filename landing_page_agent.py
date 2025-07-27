import re
import json
import time
import base64
from typing import Dict, List, Any, Optional
from bs4 import BeautifulSoup
from base_agent import BaseSocialMediaAgent
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

class LandingPageAgent(BaseSocialMediaAgent):
    def get_platform_name(self) -> str:
        return "landing_page"
    
    def extract_profile_data(self, soup: BeautifulSoup, driver=None) -> Dict[str, Any]:
        """Extract landing page data"""
        page_data = {
            'title': None,
            'description': None,
            'keywords': None,
            'company_name': None,
            'logo_url': None,
            'favicon_url': None,
            'canonical_url': None,
            'og_data': {},
            'twitter_data': {},
            'contact_info': {
                'email': [],
                'phone': [],
                'address': []
            },
            'social_links': {
                'facebook': [],
                'twitter': [],
                'instagram': [],
                'linkedin': [],
                'youtube': []
            },
            'technologies': [],
            'navigation_menu': [],
            'footer_links': [],
            'cta_buttons': [],
            'forms': [],
            'content_sections': []
        }
        
        try:
            # Basic meta information
            title_tag = soup.find('title')
            if title_tag:
                page_data['title'] = title_tag.get_text().strip()
            
            # Meta description
            desc_meta = soup.find('meta', attrs={'name': 'description'})
            if desc_meta:
                page_data['description'] = desc_meta.get('content', '').strip()
            
            # Meta keywords
            keywords_meta = soup.find('meta', attrs={'name': 'keywords'})
            if keywords_meta:
                page_data['keywords'] = keywords_meta.get('content', '').strip()
            
            # Canonical URL
            canonical_link = soup.find('link', attrs={'rel': 'canonical'})
            if canonical_link:
                page_data['canonical_url'] = canonical_link.get('href', '')
            
            # Favicon
            favicon_link = soup.find('link', attrs={'rel': re.compile(r'.*icon.*', re.I)})
            if favicon_link:
                page_data['favicon_url'] = favicon_link.get('href', '')
            
            # Open Graph data
            og_tags = soup.find_all('meta', property=re.compile(r'^og:'))
            for tag in og_tags:
                prop = tag.get('property', '').replace('og:', '')
                content = tag.get('content', '')
                if prop and content:
                    page_data['og_data'][prop] = content
            
            # Twitter Card data
            twitter_tags = soup.find_all('meta', attrs={'name': re.compile(r'^twitter:')})
            for tag in twitter_tags:
                name = tag.get('name', '').replace('twitter:', '')
                content = tag.get('content', '')
                if name and content:
                    page_data['twitter_data'][name] = content
            
            # Extract company logo
            logo_selectors = [
                'img[alt*="logo" i]',
                'img[class*="logo" i]',
                'img[id*="logo" i]',
                '.logo img',
                '#logo img',
                'header img:first-of-type'
            ]
            for selector in logo_selectors:
                logo_img = soup.select_one(selector)
                if logo_img:
                    page_data['logo_url'] = logo_img.get('src', '')
                    break
            
            # Extract company name from various sources
            company_name_sources = [
                page_data['og_data'].get('site_name'),
                page_data['title'],
                soup.find('h1'),
                soup.select_one('.company-name, .brand-name, .site-title')
            ]
            for source in company_name_sources:
                if source:
                    if isinstance(source, str):
                        page_data['company_name'] = source.strip()
                        break
                    elif hasattr(source, 'get_text'):
                        page_data['company_name'] = source.get_text().strip()
                        break
            
            # Extract contact information
            page_data['contact_info'] = self._extract_contact_info(soup)
            
            # Extract social media links
            page_data['social_links'] = self._extract_social_links(soup)
            
            # Extract navigation menu
            page_data['navigation_menu'] = self._extract_navigation(soup)
            
            # Extract footer links
            page_data['footer_links'] = self._extract_footer_links(soup)
            
            # Extract CTA buttons
            page_data['cta_buttons'] = self._extract_cta_buttons(soup)
            
            # Extract forms
            page_data['forms'] = self._extract_forms(soup)
            
            # Extract content sections
            page_data['content_sections'] = self._extract_content_sections(soup)
            
            # Detect technologies
            page_data['technologies'] = self._detect_technologies(soup)
            
        except Exception as e:
            print(f"Error extracting landing page data: {e}")
        
        return page_data
    
    def extract_posts_data(self, soup: BeautifulSoup, driver=None) -> List[Dict[str, Any]]:
        """Extract blog posts or news articles from landing page"""
        posts = []
        
        try:
            # Look for blog/news sections
            post_selectors = [
                'article',
                '.blog-post',
                '.news-item',
                '.post',
                '.article',
                '[class*="blog"]',
                '[class*="news"]',
                '[class*="post"]'
            ]
            
            for selector in post_selectors:
                post_elements = soup.select(selector)
                for i, element in enumerate(post_elements[:10]):  # Limit to 10 posts
                    post_data = {
                        'id': i + 1,
                        'title': None,
                        'excerpt': None,
                        'content': None,
                        'author': None,
                        'date': None,
                        'category': None,
                        'tags': [],
                        'image_url': None,
                        'url': None
                    }
                    
                    # Extract title
                    title_elem = element.find(['h1', 'h2', 'h3', 'h4'])
                    if title_elem:
                        post_data['title'] = title_elem.get_text().strip()
                    
                    # Extract content/excerpt
                    content_elem = element.find(['p', 'div'])
                    if content_elem:
                        post_data['excerpt'] = content_elem.get_text().strip()[:200]
                    
                    # Extract image
                    img_elem = element.find('img')
                    if img_elem:
                        post_data['image_url'] = img_elem.get('src', '')
                    
                    # Extract link
                    link_elem = element.find('a')
                    if link_elem:
                        post_data['url'] = link_elem.get('href', '')
                    
                    posts.append(post_data)
                
                if posts:  # If we found posts, break
                    break
                    
        except Exception as e:
            print(f"Error extracting landing page posts: {e}")
        
        return posts
    
    def _extract_contact_info(self, soup: BeautifulSoup) -> Dict[str, List[str]]:
        """Extract contact information"""
        contact_info = {
            'email': [],
            'phone': [],
            'address': []
        }
        
        # Extract emails
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        emails = re.findall(email_pattern, soup.get_text())
        contact_info['email'] = list(set(emails))[:5]  # Limit to 5 unique emails
        
        # Extract phone numbers
        phone_pattern = r'(\+?\d{1,4}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}'
        phones = re.findall(phone_pattern, soup.get_text())
        contact_info['phone'] = list(set([''.join(phone) for phone in phones]))[:3]
        
        # Extract addresses (look for common address patterns)
        address_elements = soup.find_all(['div', 'span', 'p'], class_=re.compile(r'.*address.*', re.I))
        for elem in address_elements[:3]:
            text = elem.get_text().strip()
            if len(text) > 10 and len(text) < 200:
                contact_info['address'].append(text)
        
        return contact_info
    
    def _extract_social_links(self, soup: BeautifulSoup) -> Dict[str, List[str]]:
        """Extract social media links"""
        social_links = {
            'facebook': [],
            'twitter': [],
            'instagram': [],
            'linkedin': [],
            'youtube': []
        }
        
        # Find all links
        links = soup.find_all('a', href=True)
        
        for link in links:
            href = link.get('href', '').lower()
            
            if 'facebook.com' in href:
                social_links['facebook'].append(href)
            elif 'twitter.com' in href or 'x.com' in href:
                social_links['twitter'].append(href)
            elif 'instagram.com' in href:
                social_links['instagram'].append(href)
            elif 'linkedin.com' in href:
                social_links['linkedin'].append(href)
            elif 'youtube.com' in href:
                social_links['youtube'].append(href)
        
        # Remove duplicates and limit
        for platform in social_links:
            social_links[platform] = list(set(social_links[platform]))[:3]
        
        return social_links
    
    def _extract_navigation(self, soup: BeautifulSoup) -> List[Dict[str, str]]:
        """Extract navigation menu items"""
        nav_items = []
        
        # Look for navigation elements
        nav_selectors = ['nav', '.navigation', '.menu', '.navbar', '#menu', '#navigation']
        
        for selector in nav_selectors:
            nav_elem = soup.select_one(selector)
            if nav_elem:
                links = nav_elem.find_all('a')
                for link in links[:10]:  # Limit to 10 items
                    text = link.get_text().strip()
                    href = link.get('href', '')
                    if text and len(text) < 50:
                        nav_items.append({
                            'text': text,
                            'url': href
                        })
                break
        
        return nav_items
    
    def _extract_footer_links(self, soup: BeautifulSoup) -> List[Dict[str, str]]:
        """Extract footer links"""
        footer_links = []
        
        footer_elem = soup.find('footer')
        if footer_elem:
            links = footer_elem.find_all('a')
            for link in links[:15]:  # Limit to 15 items
                text = link.get_text().strip()
                href = link.get('href', '')
                if text and len(text) < 50:
                    footer_links.append({
                        'text': text,
                        'url': href
                    })
        
        return footer_links
    
    def _extract_cta_buttons(self, soup: BeautifulSoup) -> List[Dict[str, str]]:
        """Extract Call-to-Action buttons"""
        cta_buttons = []
        
        # Look for CTA elements
        cta_selectors = [
            'button',
            '.btn',
            '.button',
            '.cta',
            '[class*="cta"]',
            'a[class*="button"]'
        ]
        
        for selector in cta_selectors:
            elements = soup.select(selector)
            for elem in elements[:8]:  # Limit to 8 CTAs
                text = elem.get_text().strip()
                href = elem.get('href', '') if elem.name == 'a' else ''
                if text and len(text) < 100:
                    cta_buttons.append({
                        'text': text,
                        'url': href,
                        'type': elem.name
                    })
        
        return cta_buttons
    
    def _extract_forms(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """Extract forms from the page"""
        forms = []
        
        form_elements = soup.find_all('form')
        for i, form in enumerate(form_elements[:5]):  # Limit to 5 forms
            form_data = {
                'id': i + 1,
                'action': form.get('action', ''),
                'method': form.get('method', 'get'),
                'fields': []
            }
            
            # Extract form fields
            inputs = form.find_all(['input', 'textarea', 'select'])
            for input_elem in inputs:
                field = {
                    'type': input_elem.get('type', input_elem.name),
                    'name': input_elem.get('name', ''),
                    'placeholder': input_elem.get('placeholder', ''),
                    'required': input_elem.has_attr('required')
                }
                form_data['fields'].append(field)
            
            forms.append(form_data)
        
        return forms
    
    def _extract_content_sections(self, soup: BeautifulSoup) -> List[Dict[str, str]]:
        """Extract main content sections"""
        sections = []
        
        # Look for main content sections
        section_selectors = ['section', '.section', '.content-block', '.hero', '.about', '.services']
        
        for selector in section_selectors:
            elements = soup.select(selector)
            for i, elem in enumerate(elements[:8]):  # Limit to 8 sections
                title_elem = elem.find(['h1', 'h2', 'h3'])
                title = title_elem.get_text().strip() if title_elem else f"Section {i+1}"
                
                # Get text content (first 300 chars)
                content = elem.get_text().strip()[:300]
                
                if content and len(content) > 20:
                    sections.append({
                        'title': title,
                        'content': content
                    })
        
        return sections
    
    def _detect_technologies(self, soup: BeautifulSoup) -> List[str]:
        """Detect technologies used on the website"""
        technologies = []
        
        # Check script sources for common libraries/frameworks
        script_tags = soup.find_all('script', src=True)
        for script in script_tags:
            src = script.get('src', '').lower()
            
            if 'jquery' in src:
                technologies.append('jQuery')
            elif 'bootstrap' in src:
                technologies.append('Bootstrap')
            elif 'react' in src:
                technologies.append('React')
            elif 'vue' in src:
                technologies.append('Vue.js')
            elif 'angular' in src:
                technologies.append('Angular')
            elif 'gtag' in src or 'analytics' in src:
                technologies.append('Google Analytics')
        
        # Check meta tags for generators
        generator_meta = soup.find('meta', attrs={'name': 'generator'})
        if generator_meta:
            technologies.append(generator_meta.get('content', ''))
        
        return list(set(technologies))
    
    def take_screenshots(self, url: str, num_screenshots: int = 10) -> List[str]:
        """Take headless screenshots of the landing page and return as base64 strings."""
        screenshots_base64 = []
        options = Options()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        
        driver = webdriver.Chrome(options=options)
        
        try:
            driver.get(url)
            time.sleep(5)  # Wait for page to fully load
            
            # Get page height for scrolling
            page_height = driver.execute_script("return document.body.scrollHeight")
            viewport_height = driver.execute_script("return window.innerHeight")
            
            # Take screenshots at different scroll positions
            scroll_positions = []
            for i in range(num_screenshots):
                if i == 0:
                    scroll_positions.append(0)  # Top of page
                else:
                    position = (page_height / (num_screenshots - 1)) * i
                    scroll_positions.append(min(position, page_height - viewport_height))
            
            for i, position in enumerate(scroll_positions):
                try:
                    # Scroll to position
                    driver.execute_script(f"window.scrollTo(0, {position});")
                    time.sleep(2)  # Wait for scroll to complete
                    
                    # Take screenshot
                    screenshot = driver.get_screenshot_as_png()
                    screenshot_b64 = base64.b64encode(screenshot).decode('utf-8')
                    screenshots_base64.append(screenshot_b64)
                    
                except Exception as e:
                    print(f"Error taking screenshot {i+1}: {e}")
                    continue
                    
        except Exception as e:
            print(f"Error during screenshot process: {e}")
        finally:
            driver.quit()
        
        return screenshots_base64

# Landing page agent instance
landing_page_agent = LandingPageAgent()