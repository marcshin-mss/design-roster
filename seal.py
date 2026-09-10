#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""평문 JSON 을 한 번만 암호화한다. 비밀번호는 화면에 안 보이게 입력받고 어디에도 저장하지 않는다.

    python3 seal.py

taxonomy · basis · slack · one 을 .enc 로 바꾸고 평문 파일은 지운다.
GitHub Secrets 의 GATE_PASS 와 반드시 같은 값을 넣어야 한다.
"""
import os, sys, json, getpass, base64, hashlib

HERE = os.path.dirname(os.path.abspath(__file__))
NAMES = ["taxonomy", "basis", "slack", "one", "app"]

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:
    sys.exit("먼저 설치해 주세요:  pip3 install cryptography")


def seal(text, pw):
    salt, iv = os.urandom(16), os.urandom(12)
    key = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 250000, 32)
    ct = AESGCM(key).encrypt(iv, text.encode(), None)
    b = lambda x: base64.b64encode(x).decode()
    return {"enc": "AES-GCM", "kdf": "PBKDF2-SHA256", "iter": 250000,
            "salt": b(salt), "iv": b(iv), "ct": b(ct)}


pw = os.environ.get("GATE_PASS")          # push.sh 가 키체인에서 꺼내 넘겨준다
if pw:
    print("  (키체인에 저장된 GATE_PASS 사용)")
else:
    pw = getpass.getpass("GATE_PASS (GitHub Secrets 에 넣은 값): ")
    if not pw:
        sys.exit("비밀번호가 비어 있습니다.")
    if getpass.getpass("한 번 더: ") != pw:
        sys.exit("두 값이 다릅니다.")

done = []
for n in NAMES:
    src = os.path.join(HERE, n + ".json")
    if not os.path.exists(src):
        print(f"  건너뜀 — {n}.json 없음")
        continue
    body = json.dumps(json.load(open(src, encoding="utf-8")),
                      ensure_ascii=False, separators=(",", ":"))
    json.dump(seal(body, pw), open(os.path.join(HERE, n + ".enc"), "w"), indent=0)
    os.remove(src)
    done.append(n)
    print(f"  {n}.json → {n}.enc  (평문 삭제)")

print("\n완료:", ", ".join(done) if done else "없음")
print("이제 커밋하시면 됩니다. 평문은 리포에 남지 않습니다.")
