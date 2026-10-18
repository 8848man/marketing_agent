#!/bin/bash
# Shared launcher for start.command / start-review.command (macOS, Linux).
# Readable on purpose: it only creates .venv in this folder, installs requirements.txt,
# and starts the local dashboard. It reads no file outside this folder.
set -euo pipefail
MODE="${1:-}"
cd "$(dirname "$0")/.."
echo "== 운명원 YouTube 댓글 대시보드 ${MODE:+(심사 모드)} =="

PY=""
for cand in python3.13 python3.12 python3.11 python3; do
  if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' 2>/dev/null; then
    PY="$cand"; break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.11 이상이 필요합니다. https://www.python.org/downloads/ 에서 설치한 뒤 이 파일을 다시 실행하세요."
  echo "(Homebrew 사용 시: brew install python@3.12)"
  read -r -p "Enter 키를 누르면 창을 닫습니다." _ || true
  exit 1
fi
if [ ! -d "/Applications/Google Chrome.app" ] && [ ! -d "$HOME/Applications/Google Chrome.app" ] && ! command -v google-chrome >/dev/null 2>&1; then
  echo "주의: Google Chrome을 찾지 못했습니다. 댓글 게시에는 Chrome이 필요합니다(https://www.google.com/chrome/)."
fi

if [ ! -x .venv/bin/python ]; then
  echo "1/3 가상환경을 만드는 중 (.venv)…"
  "$PY" -m venv .venv
fi
STAMP=".venv/.requirements-$(cksum requirements.txt pyproject.toml | cksum | cut -d' ' -f1)"
if [ ! -f "$STAMP" ]; then
  echo "2/3 필요한 패키지를 설치하는 중 (처음 한 번, 1~3분)…"
  .venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt
  rm -f .venv/.requirements-* && touch "$STAMP"
fi
echo "3/3 대시보드를 시작합니다. 잠시 뒤 브라우저가 열립니다. 끝내려면 이 창에서 Ctrl+C."
export PYTHONUNBUFFERED=1
exec .venv/bin/python -m marketing_agent dashboard --port 8770 --port-tries 10 $MODE
