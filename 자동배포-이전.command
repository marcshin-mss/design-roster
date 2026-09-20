#!/bin/bash
# 자동배포를 보호되지 않는 위치(~/design-roster)로 이전 — 한 번만 실행.
# 이후 백그라운드 에이전트가 ~/design-roster 에서 파일 변경 시 알아서 봉인·푸시(승인·클릭 불필요).
set -e
SRC="$HOME/Documents/design-roster"
DST="$HOME/design-roster"
LABEL="com.marcshin.design-roster-deploy"
LA="$HOME/Library/LaunchAgents"; PLIST="$LA/$LABEL.plist"

echo "▸ 1/4  기존 에이전트 정리"
launchctl unload "$PLIST" 2>/dev/null || true

echo "▸ 2/4  리포 복사 → $DST"
mkdir -p "$DST"
if command -v rsync >/dev/null 2>&1; then rsync -a "$SRC"/ "$DST"/ ; else cp -R "$SRC"/. "$DST"/ ; fi
chmod +x "$DST"/deploy-agent.sh "$DST"/push.sh 2>/dev/null || true
rm -f "$DST"/.deploy-request 2>/dev/null || true

echo "▸ 3/4  LaunchAgent 설치 (새 위치)"
mkdir -p "$LA"
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>$DST/deploy-agent.sh</string></array>
  <key>WatchPaths</key><array><string>$DST/.deploy-request</string></array>
  <key>StartInterval</key><integer>180</integer>
  <key>RunAtLoad</key><false/>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string></dict>
  <key>StandardOutPath</key><string>$DST/deploy-agent.log</string>
  <key>StandardErrorPath</key><string>$DST/deploy-agent.log</string>
</dict></plist>
PL
launchctl load "$PLIST"

echo "▸ 4/4  자체 테스트 (트리거 → 배포)"
: > "$DST/.deploy-request"
sleep 6
echo "----- deploy-agent.log (최근) -----"
tail -8 "$DST/deploy-agent.log" 2>/dev/null || echo "(로그 없음)"
echo
echo "✓ 이전 완료. 앞으로는 ~/design-roster 에서 자동 배포됩니다. 이 창은 닫으셔도 됩니다."
