from pathlib import Path

DB_PATH = Path("downloads.db")
OUTPUT_DIR = Path("output")
STAGING_DIR = Path("./staging2")
FINAL_DIR = Path("./digitized")
STATE_FILE = STAGING_DIR / "processing_state.json"
ROOT_OUTPUT_DIR = Path("output")

OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL = "qwen3.5:cloud"

OCR_DPI = 300
MAX_IMAGE_DIMENSION = 1024
TEXT_CHUNK_SIZE = 3000

MIN_DELAY = 2.5
MAX_DELAY = 9.5
TIMEOUT = 30
MAX_RETRIES = 3
DOWNLOAD_CHUNK_SIZE = 1024 * 32
TEMP_DIR = Path(".temp_downloads")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]
