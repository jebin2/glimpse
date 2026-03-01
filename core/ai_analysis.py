import json
import time
from dataclasses import dataclass
from typing import List
from google import genai
from google.genai import types
import os
from custom_logger import logger_config

@dataclass
class KeyPoint:
    id: int
    label: str
    excerpt: str
    script_anchor: str
    position_hint: str

@dataclass
class NarrationPlan:
    full_script: str
    key_points: List[KeyPoint]

class AIAnalyzer:
    def __init__(self):
        # We assume GEMINI_API_KEY is available in the environment
        self.api_key = os.environ.get("GEMINI_API_KEY", "").split(",")[0]
        # In test mode we don't strictly require an API key if the cache exists
        is_test = os.environ.get("TEST", "").lower() == "true"
        if not self.api_key and not is_test:
            raise ValueError("GEMINI_API_KEY environment variable is not set.")
        
        if self.api_key:
            self.client = genai.Client(api_key=self.api_key)
        self.model = "gemini-3-flash-preview" # Using the preview model requested
        
    def _parse_plan_data(self, data: dict) -> NarrationPlan:
        script = data.get("narration_script", "")
        points_data = data.get("key_points", [])
        
        if not (5 <= len(points_data) <= 7):
            raise ValueError(f"Expected 5-7 key points, got {len(points_data)}")
            
        key_points = []
        for idx, kp in enumerate(points_data):
            anchor = kp.get("script_anchor", "")
            if anchor not in script:
                raise ValueError(f"script_anchor '{anchor}' not found in narration_script")
            
            key_points.append(KeyPoint(
                id=kp.get("id", idx + 1),
                label=kp.get("label", ""),
                excerpt=kp.get("excerpt", ""),
                script_anchor=anchor,
                position_hint=kp.get("position_hint", "middle")
            ))
            
        return NarrationPlan(full_script=script, key_points=key_points)
        
    def extract_plan(self, article_text: str) -> NarrationPlan:
        """
        Pass 2: Uses Gemini to extract a narration script and key points.
        Returns a NarrationPlan object.
        """
        is_test = os.environ.get("TEST", "").lower() == "true"
        test_file = "test_data/ai_response.json"
        
        if is_test and os.path.exists(test_file):
            logger_config.info(f"[2/5] TEST MODE: Loading Gemini response from {test_file}")
            with open(test_file, "r") as f:
                data = json.load(f)
            return self._parse_plan_data(data)
            
        logger_config.info(f"[2/5] Extracting key points with {self.model}...")
        
        prompt_path = os.path.join(os.path.dirname(__file__), "..", "prompts", "script_writer.txt")
        with open(prompt_path, "r") as f:
            prompt_template = f.read()
            
        prompt = prompt_template.format(article_text=article_text)
        
        contents = [
            types.Content(
                role="user",
                parts=[
                    types.Part.from_text(text=prompt),
                ],
            ),
        ]
        
        # We request high thinking for better parsing, but we also require JSON format response
        generate_content_config = types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.2,
        )

        attempts = 2
        for attempt in range(attempts):
            try:
                # Use generate_content (non-stream) to retrieve the JSON
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=contents,
                    config=generate_content_config,
                )
                
                text_response = response.text
                
                # Strip any accidental markdown fences before json.loads
                text_response = text_response.replace('```json', '').replace('```', '').strip()
                data = json.loads(text_response)
                
                if is_test:
                    os.makedirs("test_data", exist_ok=True)
                    with open(test_file, "w") as f:
                        json.dump(data, f, indent=2)
                
                return self._parse_plan_data(data)
                
            except Exception as e:
                logger_config.warning(f"Gemini API error on attempt {attempt+1}: {e}")
                if attempt == attempts - 1:
                    logger_config.error("Failed to extract valid plan from Gemini after multiple attempts.")
                    exit(2)
                time.sleep(2)
