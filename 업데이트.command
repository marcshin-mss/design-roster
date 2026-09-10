#!/bin/bash
# Finder 에서 더블클릭하면 대시보드를 봉인·푸시합니다. (터미널 입력 불필요)
cd "$(dirname "$0")"
bash push.sh
echo
echo "─────────────────────────────────"
echo "끝났습니다. 이 창은 닫으셔도 됩니다."
