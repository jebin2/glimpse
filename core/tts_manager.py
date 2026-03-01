import os
import json
import time
import shutil
import re
import sys
from dataclasses import dataclass
from typing import List
from pydub import AudioSegment
from custom_logger import logger_config

from google import genai
from google.genai import types
import json_repair

from core.ai_analysis import NarrationPlan
from jebin_lib import HFTTSClient, HFSTTClient

@dataclass
class AudioSegmentInfo:
    segment_index: int
    type: str              # "bridge" or "key_point"
    key_point_id: int | None
    audio_path: str        
    duration_seconds: float
    text: str
    start_time: float      # Absolute start time in the full audio
    end_time: float        # Absolute end time in the full audio

class TTSManager:
    def __init__(self):
        self.tts_client = HFTTSClient()
        self.stt_client = HFSTTClient()
        self.api_key = os.environ.get("GEMINI_API_KEY", "").split(",")[0]
        if self.api_key:
            self.client = genai.Client(api_key=self.api_key)
        self.model = "gemini-3-flash-preview"

    def _fix_stt_spelling(self, stt_json_path: str, original_script: str):
        """
        Uses Gemini to force the STT output to match the original script exactly
        while preserving/interpolating timestamps.
        """
        logger_config.info("Forcing STT JSON to match original script via Gemini...")
        
        prompt_path = os.path.join(os.path.dirname(__file__), "..", "prompts", "STT_spelling_corrector.txt")
        if not os.path.exists(prompt_path):
            logger_config.warning(f"Spelling corrector prompt not found at {prompt_path}, skipping.")
            return

        with open(prompt_path, 'r') as file:
            system_prompt = file.read()

        try:
            with open(stt_json_path, 'r') as file:
                stt_json_str = file.read().strip()

            user_prompt = f"ORIGINAL SCRIPT:\n{original_script}\n\nRAW STT JSON:\n{stt_json_str}"

            response = self.client.models.generate_content(
                model=self.model,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    response_mime_type="application/json"
                ),
                contents=user_prompt
            )
            
            raw_response = response.text
            if not raw_response:
                logger_config.warning("Gemini spelling corrector failed (no response), skipping.")
                return

            # Clean up potential markdown formatting if Gemini ignored the prompt rule
            if "```json" in raw_response:
                raw_response = raw_response.split("```json")[1].split("```")[0].strip()
            elif "```" in raw_response:
                raw_response = raw_response.split("```")[1].split("```")[0].strip()

            result = json_repair.loads(raw_response)
            if isinstance(result, dict):
                with open(stt_json_path, 'w') as file:
                    json.dump(result, file, indent=2)
                logger_config.success("STT output successfully force-matched to original script.")
            
        except Exception as e:
            logger_config.error(f"Error in STT spelling correction: {e}")

    def generate_all(self, plan: NarrationPlan, tmpdir: str) -> tuple[str, List[AudioSegmentInfo]]:
        """
        Pass 3: Generate the full narration as one high-quality track, 
        then align it using STT + Gemini Correction for absolute precision.
        """
        logger_config.info(f"[3/5] Generating full high-quality TTS audio track...")
        
        is_test = os.environ.get("TEST", "").lower() == "true"
        if is_test:
            os.makedirs("test_data", exist_ok=True)
            
        full_audio_path = os.path.join(tmpdir, "narration_full.wav")
        test_audio_path = "test_data/narration_full.wav"
        stt_json_path = f"{full_audio_path}.json"
        test_stt_path = "test_data/narration_full.wav.json"

        # 1. Generate Voice Audio (Single Track)
        if is_test and os.path.exists(test_audio_path):
            logger_config.info(f"TEST MODE: Using cached full audio {test_audio_path}")
            shutil.copy2(test_audio_path, full_audio_path)
            if os.path.exists(test_stt_path):
                shutil.copy2(test_stt_path, stt_json_path)
        else:
            try:
                self.tts_client.generate_audio_segment(plan.full_script, full_audio_path)
            except Exception as e:
                logger_config.error(f"TTS API failed: {e}. Creating dummy audio fallback...")
                AudioSegment.silent(duration=30000).export(full_audio_path, format="wav")
            
            if is_test:
                shutil.copy2(full_audio_path, test_audio_path)

        # 2. Transcribe for Alignment
        if not os.path.exists(stt_json_path):
            logger_config.info("Running STT on full audio...")
            success = self.stt_client.transcribe(full_audio_path)
            if not success:
                logger_config.warning("STT transcription failed. Timings will be heavily estimated.")

        # 3. Force-match STT JSON to Original Script via Gemini
        # self._fix_stt_spelling(stt_json_path, plan.full_script)
        
        if is_test:
            shutil.copy2(stt_json_path, test_stt_path)

        # 4. Extract High-Precision Timestamps for Each Segment
        audio_segments = []
        if os.path.exists(stt_json_path):
            with open(stt_json_path, 'r') as f:
                stt_data = json.load(f)
            
            # Extract flat word list from perfected JSON
            words = []
            segments_obj = stt_data.get('segments', {})
            word_list = []
            if isinstance(segments_obj, dict):
                word_list = segments_obj.get('word', [])
            elif isinstance(segments_obj, list):
                for s in segments_obj:
                    # Some STT formats use 'words' key inside segments list
                    word_list.extend(s.get('words', s.get('word', [])))
            
            for w in word_list:
                text = w.get('word', w.get('text', '')).strip()
                if text:
                    words.append({
                        'text': text.lower(),
                        'start': float(w.get('start', 0.0)),
                        'end': float(w.get('end', 0.0))
                    })

            # Define Logic Segments
            logic_segments = []
            full_text = plan.full_script
            current_char_pos = 0
            for kp in plan.key_points:
                anchor_idx = full_text.find(kp.script_anchor, current_char_pos)
                if anchor_idx != -1:
                    bridge_text = full_text[current_char_pos:anchor_idx].strip()
                    if bridge_text: logic_segments.append({"type": "bridge", "text": bridge_text, "kp_id": None})
                    logic_segments.append({"type": "key_point", "text": kp.script_anchor, "kp_id": kp.id})
                    current_char_pos = anchor_idx + len(kp.script_anchor)
            outro = full_text[current_char_pos:].strip()
            if outro: logic_segments.append({"type": "bridge", "text": outro, "kp_id": None})

            # Map Logic Segments to Absolute Path in perfected words list
            current_word_idx = 0
            for i, lseg in enumerate(logic_segments):
                # Clean words for safer matching
                lseg_words = [re.sub(r'[^a-zA-Z0-9]', '', w).lower() for w in lseg['text'].split() if w.strip()]
                if not lseg_words: continue
                
                # Find start
                start_time = words[current_word_idx]['start'] if current_word_idx < len(words) else 0.0
                
                # Advance pointer by word count
                matched_count = 0
                while current_word_idx < len(words) and matched_count < len(lseg_words):
                    # We assume STT JSON is now PERFECTLY matched to script words
                    current_word_idx += 1
                    matched_count += 1
                
                end_time = words[current_word_idx-1]['end'] if current_word_idx > 0 else (start_time + 1.0)
                
                audio_segments.append(AudioSegmentInfo(
                    segment_index=i,
                    type=lseg["type"],
                    key_point_id=lseg["kp_id"],
                    audio_path=full_audio_path,
                    duration_seconds=end_time - start_time,
                    text=lseg["text"],
                    start_time=start_time,
                    end_time=end_time
                ))

        # Fallback if no STT
        if not audio_segments:
            logger_config.warning("No audio segments were matched. Check STT and Script anchor consistency.")
            # Create a single fallback segment covering 30s
            audio_segments.append(AudioSegmentInfo(
                segment_index=0, type="bridge", key_point_id=None,
                audio_path=full_audio_path, duration_seconds=30.0,
                text=plan.full_script[:100], start_time=0.0, end_time=30.0
            ))

        return full_audio_path, audio_segments
