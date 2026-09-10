#!/bin/bash
# 디자인실 대시보드 — GitHub 인증 + 푸시. 설치도 sudo 도 필요 없다.
#   cd ~/Documents/design-roster && bash push.sh
set -e
cd "$(dirname "$0")"

GH=""
if command -v gh >/dev/null 2>&1; then
  GH="$(command -v gh)"
elif [ -x .tools/gh ]; then
  GH="$PWD/.tools/gh"
else
  echo "▸ 1/3  GitHub 도구 내려받기 (설치 아님 · 이 폴더 안에만 둡니다)"
  case "$(uname -m)" in arm64) A=arm64 ;; *) A=amd64 ;; esac
  V="$(curl -fsSL https://api.github.com/repos/cli/cli/releases/latest \
       | sed -n 's/.*"tag_name": *"v\([^"]*\)".*/\1/p' | head -1)"
  [ -n "$V" ] || { echo "✗ 버전 확인 실패 — 인터넷 연결을 확인해 주세요."; exit 1; }
  echo "  gh v$V ($A) 내려받는 중…"
  mkdir -p .tools && cd .tools
  curl -fsSL -o gh.zip "https://github.com/cli/cli/releases/download/v${V}/gh_${V}_macOS_${A}.zip"
  unzip -oq gh.zip
  B="$(find . -type f -name gh -perm -u+x | head -1)"
  [ -n "$B" ] || { echo "✗ 압축 안에서 gh 를 못 찾았습니다."; exit 1; }
  cp "$B" ./gh && chmod +x ./gh
  xattr -dr com.apple.quarantine ./gh 2>/dev/null || true
  rm -rf gh.zip "gh_${V}_macOS_${A}" 2>/dev/null || true
  cd ..
  GH="$PWD/.tools/gh"
fi
echo "  ✓ 준비됨"

echo "▸ 2/3  GitHub 로그인"
if "$GH" auth status 2>&1 | grep -q "workflow"; then
  echo "  ✓ 이미 로그인되어 있습니다"
else
  echo
  echo "  ┌─────────────────────────────────────────────┐"
  echo "  │  잠시 뒤 8자리 코드가 나옵니다.             │"
  echo "  │  엔터 → 브라우저 열림 → 코드 붙여넣기       │"
  echo "  │  → 초록색 Authorize 버튼 클릭               │"
  echo "  └─────────────────────────────────────────────┘"
  echo
  "$GH" auth login --hostname github.com --git-protocol https --web --scopes workflow
fi
"$GH" auth setup-git

echo "▸ 3/3  푸시"
if ls *.json 2>/dev/null | grep -vx data.json | grep -vqx sync.json; then
  echo "  기준값이 갱신되어 다시 봉인합니다 — GATE_PASS 를 넣어 주세요"
  python3 seal.py
fi
git add -A
git diff --staged --quiet || \
  git -c user.name="Marc Shin" -c user.email="marc.shin@musinsa.com" \
      commit -q -m "설정 보완"
git remote get-url origin >/dev/null 2>&1 || \
  git remote add origin https://github.com/marcshin-mss/design-roster.git
git push -f -u origin main

echo
echo "✓ 올라갔습니다. 이제 브라우저에서 순서대로:"
echo "  ① Settings → General → 맨 아래 → Change visibility → Public"
echo "  ② Settings → Pages → Source → GitHub Actions"
echo "  ③ Actions → 왼쪽 「대시보드 갱신」 → Run workflow"
