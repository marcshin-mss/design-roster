#!/bin/bash
# 디자인실 대시보드 — 봉인 + 커밋 + 푸시.
#   cd ~/Documents/design-roster && bash push.sh
set -e
cd "$(dirname "$0")"
find .git -name '*.lock' -delete 2>/dev/null || true   # 남아 있는 잠금 정리

SVC="design-roster-gate"

gh_bin() {
  if command -v gh >/dev/null 2>&1; then echo "$(command -v gh)"; return; fi
  if [ -x .tools/gh ]; then echo "$PWD/.tools/gh"; return; fi
  echo ""
}

# ── 1. GitHub 도구 ────────────────────────────────────────────
GH="$(gh_bin)"
if [ -z "$GH" ]; then
  echo "▸ GitHub 도구 내려받기 (설치 아님 · 이 폴더 안에만 둡니다)"
  case "$(uname -m)" in arm64) A=arm64 ;; *) A=amd64 ;; esac
  V="$(curl -fsSL https://api.github.com/repos/cli/cli/releases/latest \
       | sed -n 's/.*"tag_name": *"v\([^"]*\)".*/\1/p' | head -1)"
  [ -n "$V" ] || { echo "✗ 버전 확인 실패 — 인터넷 연결을 확인해 주세요."; exit 1; }
  mkdir -p .tools && cd .tools
  curl -fsSL -o gh.zip "https://github.com/cli/cli/releases/download/v${V}/gh_${V}_macOS_${A}.zip"
  unzip -oq gh.zip
  B="$(find . -type f -name gh -perm -u+x | head -1)"
  cp "$B" ./gh && chmod +x ./gh
  xattr -dr com.apple.quarantine ./gh 2>/dev/null || true
  rm -rf gh.zip "gh_${V}_macOS_${A}" 2>/dev/null || true
  cd ..
  GH="$PWD/.tools/gh"
fi

# ── 2. GitHub 로그인 ──────────────────────────────────────────
if ! "$GH" auth status 2>&1 | grep -q "workflow"; then
  echo "▸ GitHub 로그인 — 브라우저가 열리면 코드를 붙여넣고 Authorize 해주세요"
  "$GH" auth login --hostname github.com --git-protocol https --web --scopes workflow
fi
"$GH" auth setup-git >/dev/null 2>&1 || true

# ── 3. 봉인 — 비밀번호는 키체인에서 꺼낸다 ─────────────────────
if ls *.json 2>/dev/null | grep -vx data.json | grep -vqx sync.json; then
  PASS="$(security find-generic-password -a "$USER" -s "$SVC" -w 2>/dev/null || true)"
  if [ -z "$PASS" ]; then
    echo
    echo "  ┌────────────────────────────────────────────────┐"
    echo "  │  GATE_PASS 를 이번 한 번만 물어봅니다.         │"
    echo "  │  Mac 키체인에 저장해서 다음부터는 안 묻습니다. │"
    echo "  └────────────────────────────────────────────────┘"
    read -s -p "  GATE_PASS: " PASS; echo
    read -s -p "  한 번 더  : " P2;   echo
    [ -n "$PASS" ] || { echo "✗ 비어 있습니다."; exit 1; }
    [ "$PASS" = "$P2" ] || { echo "✗ 두 값이 다릅니다."; exit 1; }
    unset P2
    security add-generic-password -a "$USER" -s "$SVC" -w "$PASS" -U \
      && echo "  ✓ 키체인에 저장했습니다 (다음부터 안 물어봅니다)"
  fi
  echo "▸ 봉인"
  GATE_PASS="$PASS" python3 seal.py
  unset PASS
fi

# ── 4. 커밋 · 푸시 ────────────────────────────────────────────
echo "▸ 푸시"
git add -A
if git diff --staged --quiet; then
  echo "  올릴 변경이 없습니다."
else
  git -c user.name="Marc Shin" -c user.email="marc.shin@musinsa.com" \
      commit -q -m "대시보드 갱신"
  git remote get-url origin >/dev/null 2>&1 || \
    git remote add origin https://github.com/marcshin-mss/design-roster.git
  git pull --rebase --autostash -q origin main 2>/dev/null || true
  git push -u origin main
fi

echo
echo "✓ 끝났습니다. 1~2분 뒤 자동으로 배포됩니다."
echo "  https://marcshin-mss.github.io/design-roster/"
echo "  진행 상황: https://github.com/marcshin-mss/design-roster/actions"
