#!/bin/bash
# 심사용 실행 파일 (macOS): 더블클릭하면 설치 → 대시보드(심사 모드) 실행 → 브라우저 열기.
# 내용은 scripts/launch.sh 에 있습니다.
exec bash "$(dirname "$0")/scripts/launch.sh" --review
