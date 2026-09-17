#!/bin/bash
#
# 클라우드 세션 시작 시 프로젝트를 바로 쓸 수 있는 상태로 만든다.
#
#   1. 개발 의존성(pytest) 설치
#   2. 공식 카드 데이터(cards.cdb, 스크립트 상수) 내려받기
#   3. Lua 파싱 캐시 예열 (12,000여 개 스크립트 파싱을 미리 끝내둔다)
#   4. 한국어 카드 데이터 소스 도달 가능 여부 점검
#
# 모든 단계는 멱등이며, 실패해도 세션을 막지 않는다.
# 데이터를 못 받아도 검색 기능 일부는 동작하고, 무엇이 막혔는지 로그로 알린다.

set -uo pipefail

# 클라우드 세션에서만 실행한다 (로컬에서는 즉시 종료).
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
cd "$PROJECT_DIR" || exit 0

PY="$(command -v python3 || command -v python)"
if [ -z "$PY" ]; then
  echo "[session-start] python 을 찾지 못했습니다. 건너뜁니다."
  exit 0
fi

echo "[session-start] 프로젝트: $PROJECT_DIR"

# --- 1. 개발 의존성 -------------------------------------------------------
if ! "$PY" -m pytest --version >/dev/null 2>&1; then
  echo "[session-start] pytest 설치 중..."
  "$PY" -m pip install -q -r requirements-dev.txt 2>&1 | tail -3 \
    || echo "[session-start] 경고: pytest 설치 실패 (테스트 실행 불가)"
else
  echo "[session-start] pytest 이미 설치됨"
fi

# --- 2. 공식 카드 데이터 --------------------------------------------------
# 이미 있는 파일은 건너뛴다. 갱신하려면 --force 로 직접 실행.
echo "[session-start] 공식 카드 데이터 확인 중..."
"$PY" -m scripts.fetch_official_db 2>&1 | sed 's/^/[session-start]   /' \
  || echo "[session-start] 경고: 공식 데이터를 받지 못했습니다 (네트워크 정책 확인 필요)"

# 카드 DB 경로를 세션 환경 변수로 고정한다 (경로 추정에 의존하지 않기 위해).
if [ -f "$PROJECT_DIR/data/cards.cdb" ] && [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo "export YGO_CARDS_CDB=\"$PROJECT_DIR/data/cards.cdb\"" >> "$CLAUDE_ENV_FILE"
fi

# --- 3. Lua 파싱 캐시 예열 ------------------------------------------------
# 예열해 두면 첫 검색이 약 7초에서 약 1초로 줄어든다.
if [ -f "$PROJECT_DIR/data/cards.cdb" ]; then
  echo "[session-start] Lua 파싱 캐시 예열 중 (12,000여 개 스크립트)..."
  "$PY" - <<'PYEOF' 2>&1 | sed 's/^/[session-start]   /'
import sys, time
sys.path.insert(0, ".")
try:
    from core.card_repository import CardRepository
    started = time.time()
    repo = CardRepository.build()
    stats = repo.stats()
    print(
        f"카드 {stats['canonical']:,}장 준비 완료 "
        f"(스크립트 {stats['with_script']:,}장, {time.time() - started:.1f}초)"
    )
except Exception as exc:  # 예열 실패는 치명적이지 않다
    print(f"캐시 예열 건너뜀: {exc}")
PYEOF
else
  echo "[session-start] cards.cdb 없음 — 캐시 예열 건너뜀"
fi

# --- 4. 한국어 데이터 소스 점검 -------------------------------------------
# 이 환경의 네트워크 정책이 공식 한국어 DB 를 허용하는지 미리 확인한다.
# 작업 중에 막힌 것을 발견하는 대신, 시작 시점에 분명히 알리기 위함이다.
KO_DIR="${YGO_KO_DIR:-$PROJECT_DIR/data/ko}"
if compgen -G "$KO_DIR/*.cdb" >/dev/null 2>&1 \
  || compgen -G "$KO_DIR/*.json" >/dev/null 2>&1 \
  || compgen -G "$KO_DIR/*.csv" >/dev/null 2>&1; then
  echo "[session-start] 한국어 카드 데이터 있음: $KO_DIR"
else
  KO_HOST="https://www.db.yugioh-card.com/yugiohdb/?request_locale=ko"
  KO_CODE="$(curl -s -o /dev/null -w '%{http_code}' -m 20 "$KO_HOST" 2>/dev/null)"
  if [ "$KO_CODE" = "200" ]; then
    echo "[session-start] 공식 한국어 DB 접근 가능 (HTTP 200) — 데이터 수집 진행 가능"
  else
    echo "[session-start] 공식 한국어 DB 접근 불가 (응답: ${KO_CODE:-없음})"
    echo "[session-start]   환경의 Network access 를 Custom 으로 바꾸고"
    echo "[session-start]   *.yugioh-card.com 을 허용 목록에 추가하세요."
    echo "[session-start]   (카드명은 영어로 표시되지만 한국어 검색은 정상 동작합니다)"
  fi
fi

echo "[session-start] 준비 완료"
exit 0
