#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""업무 현황 전용 팀 계산 (Marc 2026-11-12 「업무 현황에만 팀을 추가해서 똑같이」).

다른 조직 디자인팀(명단 = xteam.enc, 봉인)을 build.py 와 같은 규칙(티켓 → 과제 · Runway 계획 · 크기)으로
따로 계산해 xt.json 을 남긴다. 이어서 도는 build.py 가 그걸 D["xt"] 로 싣고 지운다.
본 빌드 숫자(리소스 · 조직도 · 성과)에는 섞이지 않는다.

- 지라는 읽기만 한다(담당자 자동 기록 같은 쓰기는 끔).
- 계산 중 파일은 임시 폴더에만 쓴다(리포 · 배포물에 평문이 남지 않게).
- xteam 이 없으면 아무것도 안 하고 끝난다.
"""
import os, sys, json, shutil, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build

def init_org(D):
    """과제(이니셔티브)를 맡은 PM 의 소속 — 리소스 관리 「조직별 투입」용 (Marc 11-12).
    지라 담당자 표시 이름 '이름/Core-P Partner Growth 아이디' 의 가운데 소속. 담당자가 없으면 Runway 라벨 core_p_<팀>."""
    import re
    keys = sorted({k for P in (D.get("pjq") or {}).values() for k in ((P or {}).get("init") or {})})
    out = {}
    for i in range(0, len(keys), 80):
        ch = keys[i:i + 80]
        try:
            rows = build.jql("key in (%s)" % ",".join(ch), ["assignee", "labels"], cap=200)
        except Exception as e:
            print("  과제 소속 조회 실패:", e); continue
        for n in rows:
            k = n.get("key"); nm = build.F(n, "fields", "assignee", "displayName") or ""
            m = re.match(r"^[^/]+/(.+?)\s+\S+$", nm)
            org = m.group(1).strip() if m else ""
            if not org:
                lb = [re.sub(r"^runway-\d{4}_q\d_플래닝-core_p_|-atl$", "", x) for x in (build.F(n, "fields", "labels") or []) if re.search(r"-core_p_(?!product_design)\w+-atl$", x)]
                if lb: org = "Core-P " + lb[0].replace("_", " ").title()
            if k and org: out[k] = org
    return out

def main():
    if not (build.EMAIL and build.TOKEN):
        print("업무 현황 전용 팀: 지라 계정 없음 — 건너뜀"); return
    xt = build.load_sealed("xteam")
    if not xt or not xt.get("teams"):
        print("업무 현황 전용 팀: xteam 없음 — 건너뜀"); return
    tax = build.load_sealed("taxonomy") or {}
    tmp = tempfile.mkdtemp(prefix="pxd-xt-")
    try:
        mini = {"teams": xt["teams"], "themes": tax.get("themes") or [], "summaries": {}, "short": {}, "tasks": {}}
        json.dump(mini, open(os.path.join(tmp, "taxonomy.json"), "w", encoding="utf-8"), ensure_ascii=False)
        build.HERE = tmp                       # 읽고 쓰는 파일은 전부 임시 폴더
        build.GATE = ""                        # 봉인 파일 · 썸네일 · Worker 스냅샷 쓰기 없음
        build.apply_assignments = lambda *a, **k: None   # 지라 쓰기 끔
        build._RW_DT.update(xt.get("rw") or {})
        build._RW_KEEP = {t["name"] for t in xt["teams"]}
        os.environ.pop("SLACK_TOKEN", None)
        build.main()
        D = json.load(open(os.path.join(tmp, "data.json"), encoding="utf-8"))
        names = {x["t"] for t in D["teams"] for m in t["members"] for x in m.get("tasks", [])} | \
                {r[5] for t in D["teams"] for m in t["members"] for r in m.get("dn", []) if len(r) > 5 and r[5]}
        bt = {k: v for k, v in ((D.get("basis") or {}).get("tasks") or {}).items() if k in names}
        iorg = init_org(D)
        out = {"teams": D["teams"], "pjq": D.get("pjq") or {}, "tkm": D.get("tkm") or {}, "acc": D.get("acc") or {}, "iorg": iorg,
               "perwho": D.get("perwho") or [], "orphan": D.get("orphan") or [],
               "rwq": (D.get("rwq") or {}).get("rows") or [], "bt": bt, "asof": D.get("asof", ""),
               "view": xt.get("view") or []}
        open(os.path.join(HERE, "xt.json"), "w", encoding="utf-8").write(
            json.dumps(out, ensure_ascii=False, separators=(",", ":")))
        print("업무 현황 전용 팀: %d팀 · 과제 %d" % (len(out["teams"]), D.get("taskN", 0)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

if __name__ == "__main__":
    try:
        main()
    except SystemExit as e:
        print("업무 현황 전용 팀 건너뜀:", e)
    except Exception as e:
        print("업무 현황 전용 팀 건너뜀:", type(e).__name__, e)
