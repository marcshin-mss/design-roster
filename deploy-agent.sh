#!/bin/bash
# 자동배포 핸들러 — LaunchAgent 가 .deploy-request 변경을 감지하면 실행한다.
# .deploy-request 가 있을 때만 push.sh 를 돌리고, 없으면 조용히 끝낸다(루프 방지).
cd "$(dirname "$0")" || exit 0
[ -f .deploy-request ] || exit 0
rm -f .deploy-request 2>/dev/null
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
{
  echo "──────────────────────────────────────────"
  echo "▶ 자동배포 시작 $(date '+%Y-%m-%d %H:%M:%S')"
  bash push.sh
  echo "■ 자동배포 종료 $(date '+%Y-%m-%d %H:%M:%S')"
} >> deploy-agent.log 2>&1
