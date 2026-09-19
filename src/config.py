"""프로젝트 공통 설정 로더.

secrets/ 아래의 자격증명(.env, 서비스 계정 키)을 로드하고,
프로젝트 루트 기준 경로 상수를 제공한다.
어느 위치에서 스크립트를 실행하더라도 동작하도록 프로젝트 루트를
이 파일 위치 기준으로 계산한다.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# src/config.py -> 프로젝트 루트는 한 단계 위
ROOT = Path(__file__).resolve().parent.parent

SECRETS_DIR = ROOT / "secrets"
DATA_DIR = ROOT / "data"

# Google 서비스 계정 키 경로
GOOGLE_SERVICE_ACCOUNT_PATH = SECRETS_DIR / "google-service-account.json"

# Firebase(Firestore) 서비스 계정 키 경로 - 월간 리포트 저장용
FIREBASE_SERVICE_ACCOUNT_PATH = SECRETS_DIR / "firebase-service-account.json"

# .env 파일 로드 (없어도 조용히 넘어감)
load_dotenv(SECRETS_DIR / "naver-api.env")
load_dotenv(SECRETS_DIR / "telegram.env")

# 대상 스프레드시트
SPREADSHEET_ID = "1YOk8QfK3f4bQKT6jhAiXb09Yes6aUgTyobkfrmadg-o"
SHEET_TRANSACTIONS = "📊주식내역"
SHEET_HOLDINGS = "📈주식현황상세"

GOOGLE_SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

# 네이버 검색 API 자격증명
NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")

# 텔레그램 봇 자격증명
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# 산출물 경로
PORTFOLIO_SNAPSHOT_PATH = DATA_DIR / "portfolio_snapshot.json"
NEWS_SNAPSHOT_PATH = DATA_DIR / "news_snapshot.json"


def ensure_data_dir() -> None:
    """data/ 디렉터리가 없으면 생성한다."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
