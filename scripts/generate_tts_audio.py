import sys
import json
import logging
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Suppress PyTorch warnings in this subprocess
import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
os.environ["OMP_NUM_THREADS"] = "1"

from src.tts_generator import TTSGenerator

logging.basicConfig(level=logging.ERROR)

def main():
    if len(sys.argv) < 3:
        print("Usage: generate_tts_audio.py <output_path> <steps_json>", file=sys.stderr)
        sys.exit(1)

    output_path = Path(sys.argv[1])
    steps_json = sys.argv[2]
    
    try:
        text_steps = json.loads(steps_json)
    except Exception as e:
        print(f"Failed to parse steps JSON: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        # Initialize and run TTS in this clean process
        generator = TTSGenerator(use_coqui=True)
        timing_info = generator.generate_speech_file(text_steps, output_path, force_direct=True)
        
        # 1. Write timing info to a dedicated sidecar JSON file to bypass stdout clutter
        timing_file = output_path.parent / f"{output_path.name}.timing.json"
        timing_file.write_text(json.dumps(timing_info), encoding="utf-8")

        # 2. Print with sentinel token for reliable parsing
        print(f"\n__TIMING_START__{json.dumps(timing_info)}__TIMING_END__")
        sys.exit(0)
    except Exception as e:
        print(f"TTS Generation Subprocess Failed: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
