#!/bin/bash
# 디자인실 대시보드 — 봉인 + 커밋 + 푸시를 한 번에.
#   cd ~/Documents/design-roster && bash setup.sh
set -e
cd "$(dirname "$0")"

echo "▸ 1/5  준비"
rm -f _new_taxonomy.json _new_basis.json 2>/dev/null || true
find .git -name '*.lock' -delete 2>/dev/null || true
rm -rf .git/_stale 2>/dev/null || true
python3 -c "import cryptography" 2>/dev/null || pip3 install --quiet cryptography

echo "▸ 2/5  봉인 — GitHub Secrets 의 GATE_PASS 와 똑같은 값을 넣으세요"
python3 seal.py

for f in taxonomy basis slack one; do
  [ -f "$f.enc" ] || { echo "✗ $f.enc 가 없습니다. 중단합니다."; exit 1; }
done
if ls *.json 2>/dev/null | grep -vx data.json; then
  echo "✗ 위 평문 파일이 남아 있습니다. 중단합니다."; exit 1
fi
echo "  ✓ 평문 없음 · .enc 4개 확인"

echo "▸ 3/5  히스토리 정리"
git checkout --orphan _clean -q
git add -A
git -c user.name="Marc Shin" -c user.email="marc.shin@musinsa.com" \
    commit -q -m "디자인실 워크로드 대시보드"
git branch -D main 2>/dev/null || true
git branch -D master 2>/dev/null || true
git branch -m main

echo "▸ 4/5  푸시 — GitHub 로그인 창이 뜨면 승인해 주세요"
git remote get-url origin >/dev/null 2>&1 || \
  git remote add origin https://github.com/marcshin-mss/design-roster.git
git push -f -u origin main

echo "▸ 5/5  완료"
git log --oneline | head -1
echo
echo "다음은 브라우저에서:"
echo "  ① Settings → General → Danger Zone → Change visibility → Public"
echo "  ② Settings → Pages → Source → GitHub Actions"
echo "  ③ Actions → 대시보드 갱신 → Run workflow"
echo "  ④ https://marcshin-mss.github.io/design-roster/"
