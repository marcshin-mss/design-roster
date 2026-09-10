#!/bin/bash
# GATE_PASS 의 SHA-256 을 구합니다. 비밀번호는 화면·기록에 남지 않습니다.
#   cd ~/Documents/design-roster && bash gatehash.sh
read -s -p "GATE_PASS: " P; echo
[ -n "$P" ] || { echo "비어 있습니다."; exit 1; }
read -s -p "한 번 더: " P2; echo
[ "$P" = "$P2" ] || { echo "두 값이 다릅니다."; exit 1; }
H=$(printf '%s' "$P" | shasum -a 256 | awk '{print $1}')
unset P P2
echo
echo "GATE_HASH ↓  (Cloudflare 에 붙여넣으세요)"
echo "$H"
command -v pbcopy >/dev/null 2>&1 && printf '%s' "$H" | pbcopy && echo "(클립보드에도 복사했습니다)"
