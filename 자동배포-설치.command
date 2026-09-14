#!/bin/bash
# 자동배포 에이전트 설치 — 딱 한 번만 더블클릭하면 됩니다.
# 이후로는 파일이 바뀌면 맥이 알아서 봉인·푸시합니다. (클릭 불필요)
cd "$(dirname "$0")"
SVC="design-roster-gate"
LABEL="com.marcshin.design-roster-deploy"
LA="$HOME/Library/LaunchAgents"
PLIST="$LA/$LABEL.plist"
FOLDER="$PWD"

echo "▸ 1/3  키체인 — 백그라운드에서 비밀번호를 다시 안 묻게 설정"
PASS="$(security find-generic-password -a "$USER" -s "$SVC" -w 2>/dev/null || true)"
if [ -n "$PASS" ]; then
  # -A: 백그라운드 에이전트가 프롬프트 없이 GATE_PASS 를 읽을 수 있게 한다
  security add-generic-password -a "$USER" -s "$SVC" -w "$PASS" -A -U 2>/dev/null \
    && echo "  ✓ 완료 (앞으로 안 묻습니다)"
  unset PASS
else
  echo "  ⚠ 키체인에 GATE_PASS 가 없습니다 — 업데이트.command 를 한 번 먼저 실행해 저장한 뒤 다시 설치하세요."
fi

echo "▸ 2/3  LaunchAgent 설치"
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

echo "▸ 3/3  로드"
launchctl unload "$PLIST" 2>/dev/null || true
if launchctl load "$PLIST"; then
  echo "  ✓ 설치 완료"
  echo
  echo "─────────────────────────────────────────────"
  echo "이제 끝났습니다. 앞으로는 클릭할 필요가 없습니다."
  echo "파일이 바뀌면 맥이 몇 초 안에 알아서 배포합니다."
  echo "(문제 생기면 deploy-agent.log 를 확인하세요)"
else
  echo "  ✗ 로드 실패 — deploy-agent.log 및 콘솔을 확인하세요."
fi
echo
echo "이 창은 닫으셔도 됩니다."
