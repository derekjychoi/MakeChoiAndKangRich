"""Google 서비스 계정으로 시트 접근을 검증하고 구조를 출력하는 1회성 점검 스크립트."""
import json
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build

ROOT = Path(__file__).resolve().parent.parent
SA_PATH = ROOT / "secrets" / "google-service-account.json"
SPREADSHEET_ID = "1YOk8QfK3f4bQKT6jhAiXb09Yes6aUgTyobkfrmadg-o"

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

creds = service_account.Credentials.from_service_account_file(str(SA_PATH), scopes=SCOPES)
service = build("sheets", "v4", credentials=creds)

meta = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
print("스프레드시트 제목:", meta["properties"]["title"])
print("\n시트 목록:")
for s in meta["sheets"]:
    props = s["properties"]
    print(f"  - gid={props['sheetId']} title={props['title']!r} rows={props['gridProperties'].get('rowCount')} cols={props['gridProperties'].get('columnCount')}")

target_gid = 421427572
target_title = None
for s in meta["sheets"]:
    if s["properties"]["sheetId"] == target_gid:
        target_title = s["properties"]["title"]

print(f"\n요청된 gid={target_gid} -> title={target_title!r}")

if target_title:
    values = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID, range=f"'{target_title}'!A1:Z15"
    ).execute().get("values", [])
    print(f"\n'{target_title}' 시트 상위 {len(values)}행 미리보기:")
    for row in values:
        print(row)
