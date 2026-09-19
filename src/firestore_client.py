"""Firestore Admin SDK 클라이언트 - 프로세스당 한 번만 초기화한다."""
from __future__ import annotations

import firebase_admin
from firebase_admin import credentials, firestore

from config import FIREBASE_SERVICE_ACCOUNT_PATH

_initialized = False


def get_db():
    global _initialized
    if not _initialized:
        cred = credentials.Certificate(str(FIREBASE_SERVICE_ACCOUNT_PATH))
        firebase_admin.initialize_app(cred)
        _initialized = True
    return firestore.client()
