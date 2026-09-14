#!/bin/bash
# 자동배포 에이전트 설치 — 딱 한 번만 더블클릭하면 됩니다.
# 이후로는 파일이 바뀌면 맥이 알아서 봉인·푸시합니다. (클릭 불필요, 키체인 창 없음)
cd "$(dirname "$0")"
LABEL="com.marcshin.design-roster-deploy"
LA="$HOME/Library/LaunchAgents"
PLIST="$LA/$LABEL.plist"
FOLDER="$PWD"

echo "▸ 1/2  LaunchAgent 설치"
chmod +x deploy-agent.sh 2>/dev/null
mkdir -p "$LA"
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>$FOLDER/deploy-agent.sh</string></array>
  <key>WatchPaths</key>
  <array><string>$FOLDER/.deploy-request</string></array>
  <key>StartInterval</key><integer>300</integer>
  <key>RunAtLoad</key><false/>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string></dict>
  <key>StandardOutPath</key><string>$FOLDER/deploy-agent.log</string>
  <key>StandardErrorPath</key><string>$FOLDER/deploy-agent.log</string>
</dict></plist>
PL

echo "▸ 2/2  로드"
launchctl unload "$PLIST" 2>/dev/null || true
if launchctl load "$PLIST"; then
  echo "  ✓ 설치 완료"
  echo
  echo "─────────────────────────────────────────────"
  echo "이제 끝났습니다. 앞으로는 클릭할 필요가 없습니다."
  echo "파일이 바뀌면 맥이 몇 초 안에 알아서 배포합니다."
  echo "(GATE_PASS 는 이미 키체인에 있어 추가 입력 없음. 문제 시 deploy-agent.log 확인)"
else
  echo "  ✗ 로드 실패 — deploy-agent.log 및 콘솔을 확인하세요."
fi
echo
echo "이 창은 닫으셔도 됩니다."
