import os
from google import genai
from google.genai import types
from typing import Dict, Any, Optional
import json
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

class GeminiClient:
    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not found in environment variables")
        
        # Initialize the client - it will automatically pick up GEMINI_API_KEY from environment
        self.client = genai.Client()
        
    async def generate_content(self, prompt: str, system_instruction: Optional[str] = None, disable_thinking: bool = False) -> str:
        """Generate content using Gemini model"""
        try:
            if system_instruction:
                full_prompt = f"System: {system_instruction}\n\nUser: {prompt}"
            else:
                full_prompt = prompt
            
            # Configure generation settings
            config = types.GenerateContentConfig()
            if disable_thinking:
                config.thinking_config = types.ThinkingConfig(thinking_budget=0)
                
            response = self.client.models.generate_content(
                model="gemini-2.5-flash",
                contents=full_prompt,
                config=config
            )
            
            return response.text
        except Exception as e:
            logger.error(f"Error generating content with Gemini: {e}")
            raise
    
    async def generate_json_content(self, prompt: str, system_instruction: Optional[str] = None, disable_thinking: bool = False) -> Dict[str, Any]:
        """Generate JSON content using Gemini model"""
        try:
            json_instruction = "Please respond with valid JSON format only. Do not include any explanation or markdown formatting."
            if system_instruction:
                full_instruction = f"{system_instruction}\n\n{json_instruction}"
            else:
                full_instruction = json_instruction
                
            response_text = await self.generate_content(prompt, full_instruction, disable_thinking)
            
            # Clean the response to ensure it's valid JSON
            response_text = response_text.strip()
            if response_text.startswith("```json"):
                response_text = response_text[7:]
            if response_text.endswith("```"):
                response_text = response_text[:-3]
            response_text = response_text.strip()
            
            return json.loads(response_text)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            logger.error(f"Response text: {response_text}")
            # Return a fallback structure
            return {"error": "Failed to parse JSON response", "raw_response": response_text}
        except Exception as e:
            logger.error(f"Error generating JSON content: {e}")
            raise
    
    async def generate_content_with_config(self, prompt: str, config: types.GenerateContentConfig, system_instruction: Optional[str] = None) -> str:
        """Generate content with custom configuration"""
        try:
            if system_instruction:
                full_prompt = f"System: {system_instruction}\n\nUser: {prompt}"
            else:
                full_prompt = prompt
                
            response = self.client.models.generate_content(
                model="gemini-2.5-flash",
                contents=full_prompt,
                config=config
            )
            
            return response.text
        except Exception as e:
            logger.error(f"Error generating content with custom config: {e}")
            raise

# Global Gemini client instance
gemini_client = GeminiClient()