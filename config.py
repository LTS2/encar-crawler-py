"""
엔카 크롤링 설정 파일
"""

import os

from dotenv import load_dotenv

load_dotenv()

# 크롤링 설정
ENCAR_URL = "https://www.encar.com/pr/pr_index.do"
HEADLESS = False  # 디버깅을 위해 False로 설정, 실제 운영시 True
TIMEOUT = 30000  # 30초
RETRY_COUNT = 3
WAIT_BETWEEN_ACTIONS = 1500  # 밀리초

# 데이터베이스 설정
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", 3306))
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "encar_prices")

# 로깅 설정
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = "encar_crawler.log"
