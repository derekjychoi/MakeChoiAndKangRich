"""텔레그램으로 메시지를 발송한다.

CLI:     python src/send_telegram.py "메시지"
         python src/send_telegram.py --dry-run "메시지"   # 실제 발송 없이 분할만 확인
모듈:    from send_telegram import send_message, escape_html
         send_message(f"<b>{escape_html(name)}</b>")

- 4096자(UTF-16 code unit 기준) 제한을 넘으면 여러 메시지로 자동 분할 발송
- parse_mode=HTML 사용. HTML 모드에서도 `&`,`<`,`>`는 반드시 이스케이프해야 하므로,
  종목명/뉴스 등 **외부·사용자 유래 데이터**를 메시지에 넣을 때는 반드시 escape_html()을
  거쳐야 한다. `<b>`,`<i>` 등 서식 태그는 조립 코드가 직접 넣고, 그 안의 데이터만 escape한다.
"""
from __future__ import annotations

import argparse
import re
import sys

import requests

import config

TELEGRAM_MAX_LEN = 4096
# 여유를 두고 분할 (UTF-16 code unit 기준, 태그가 경계에서 잘리는 것을 방어)
CHUNK_LEN = 4000
TIMEOUT_SEC = 15

# 예외 문자열 등에 섞여 나오는 봇 토큰(`bot<id>:<secret>`)을 로그에서 가리기 위한 패턴
_TOKEN_RE = re.compile(r"bot\d+:[\w-]+")


def escape_html(text: str) -> str:
    """HTML parse_mode 본문에 안전하게 넣기 위해 특수문자를 이스케이프한다.

    `&`,`<`,`>` 만 변환한다. 순서 중요: `&`를 먼저 치환해야 이중 이스케이프가 안 된다.
    서식 태그(`<b>` 등)가 아닌, 외부/사용자 데이터 문자열에만 적용할 것.
    """
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _mask_token(text: object) -> str:
    """로그 문자열에서 텔레그램 봇 토큰을 마스킹한다 (URL 유출 방지)."""
    return _TOKEN_RE.sub("bot***REDACTED***", str(text))


def _utf16_len(text: str) -> int:
    """텔레그램 길이 제한 기준인 UTF-16 code unit 개수를 센다.

    BMP 밖 이모지(📈 등)는 2 code unit으로 계산된다.
    """
    return len(text.encode("utf-16-le")) // 2


def _hard_split(text: str, limit: int) -> list:
    """공백조차 없는 초장문을 문자 경계에서 자르되, HTML 태그(`<...>`) 내부에서는
    자르지 않는다. 실전에서는 거의 도달하지 않는 극단적 방어 경로."""
    chunks: list[str] = []
    current = ""
    current_len = 0
    in_tag = False
    for ch in text:
        ch_len = _utf16_len(ch)
        # 태그 밖이고, 이 문자를 더하면 limit을 넘으면 여기서 끊는다.
        if not in_tag and current and current_len + ch_len > limit:
            chunks.append(current)
            current = ""
            current_len = 0
        current += ch
        current_len += ch_len
        if ch == "<":
            in_tag = True
        elif ch == ">":
            in_tag = False
    if current:
        chunks.append(current)
    return chunks


def _split_recursive(text: str, limit: int) -> list:
    """길이 초과 시 문단(\\n\\n) → 줄(\\n) → 단어(공백) → 문자 순으로 분할한다."""
    if _utf16_len(text) <= limit:
        return [text]
    for sep in ("\n\n", "\n", " "):
        if sep in text:
            return _pack_by_sep(text, sep, limit)
    # 구분자가 전혀 없는 초장문 (극단 케이스): 태그를 피해 문자 단위로 강제 분할
    return _hard_split(text, limit)


def _pack_by_sep(text: str, sep: str, limit: int) -> list:
    """text를 sep로 나눈 뒤 limit 이하로 다시 뭉친다. 조각 하나가 limit을 넘으면
    더 잘게(더 세밀한 구분자로) 재귀 분할한다."""
    chunks: list[str] = []
    current = ""
    for part in text.split(sep):
        candidate = part if not current else current + sep + part
        if _utf16_len(candidate) <= limit:
            current = candidate
            continue
        # candidate가 limit 초과 → 지금까지 모은 current를 확정
        if current:
            chunks.append(current)
            current = ""
        if _utf16_len(part) <= limit:
            current = part
        else:
            # 조각 하나가 limit 초과 → 더 세밀한 구분자로 재귀
            sub = _split_recursive(part, limit)
            chunks.extend(sub[:-1])
            current = sub[-1]
    if current:
        chunks.append(current)
    return chunks


def split_message(text: str, limit: int = CHUNK_LEN) -> list:
    """텔레그램 길이 제한(UTF-16 기준)을 넘지 않게, 문단/줄/단어 경계를 우선해 분할한다.

    - 단어 중간이나 HTML 태그 중간에서 잘리지 않도록 방어한다.
    - 길이 판단은 len()이 아니라 UTF-16 code unit 기준(_utf16_len).
    """
    return _split_recursive(text, limit)


def send_message(text: str, parse_mode: str = "HTML") -> None:
    """텔레그램으로 텍스트를 발송한다 (필요 시 자동 분할).

    주의: text 안의 데이터 문자열은 호출 측에서 escape_html()로 이스케이프해야 한다.
    """
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        raise RuntimeError("텔레그램 자격증명이 없습니다 (secrets/telegram.env 확인)")

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    for chunk in split_message(text):
        payload = {
            "chat_id": config.TELEGRAM_CHAT_ID,
            "text": chunk,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        resp = requests.post(url, data=payload, timeout=TIMEOUT_SEC)
        resp.raise_for_status()


def main() -> None:
    parser = argparse.ArgumentParser(description="텔레그램 메시지 발송")
    parser.add_argument("message", help="발송할 메시지 텍스트")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="실제 발송 없이 분할 결과만 출력",
    )
    parser.add_argument(
        "--parse-mode", default="HTML", help="parse_mode (기본 HTML)"
    )
    parser.add_argument(
        "--raw-html",
        action="store_true",
        help="message 인자를 이미 조립된 HTML로 간주하고 이스케이프하지 않음 (기본은 자동 이스케이프)",
    )
    args = parser.parse_args()

    # CLI로 넘어오는 메시지는 사람이 작성한 순수 텍스트로 간주해 기본적으로 자동 이스케이프한다.
    # (라이브러리로 import해서 send_message()를 직접 호출하는 경우는 호출자가 escape_html()을
    #  선택적으로 적용하는 기존 정책을 그대로 따른다 — CLI만 안전한 기본값으로 바꾼 것.)
    text = args.message if args.raw_html else escape_html(args.message)

    if args.dry_run:
        chunks = split_message(text)
        print(f"[dry-run] {len(chunks)}개 메시지로 분할됨")
        for i, c in enumerate(chunks, 1):
            print(f"  chunk {i}: {_utf16_len(c)} code unit")
        return

    send_message(text, parse_mode=args.parse_mode)
    print("발송 완료")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        # 예외 문자열에 URL(bot<TOKEN>/sendMessage)이 담길 수 있어 마스킹 후 출력
        print(f"발송 실패: {_mask_token(exc)}", file=sys.stderr)
        sys.exit(1)
