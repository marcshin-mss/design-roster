#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""디자인실 워크로드 대시보드 — 지라에서 읽어 data.json 을 만든다.

  JIRA_BASE   https://musinsa-oneteam.atlassian.net
  JIRA_EMAIL  API 토큰을 발급한 계정 메일
  JIRA_TOKEN  Atlassian API 토큰
  GATE_PASS   대시보드 열람 비밀번호(주면 data.json 을 암호화한다)

전부 읽기 전용 조회다. 지라에 아무것도 쓰지 않는다.
"""
import os, re, sys, json, base64, hashlib, datetime, urllib.request, urllib.parse, urllib.error

BASE  = os.environ.get("JIRA_BASE", "https://musinsa-oneteam.atlassian.net").rstrip("/")
EMAIL = os.environ.get("JIRA_EMAIL", "")
TOKEN = os.environ.get("JIRA_TOKEN", "")
GATE  = os.environ.get("GATE_PASS", "")
CUT   = "2026-07-01"            # 하반기 시작 — 이 이전에 '이미 끝난' 것만 뺀다
LEAD  = "2026-04-01"            # 7/1 이전 생성이라도 이 이후 생성 + 진행 중이면 포함(직전 분기부터)
HERE  = os.path.dirname(os.path.abspath(__file__))

TYPES   = '"Design","Task","작업"'
DONE_ST = {"론치완료", "완료", "개발완료", "기획완료"}
DROP_ST = {"Dropped", "철회/반려/취소"}
TODO_ST = {"Backlog", "SUGGESTED", "할일"}


def jql(q, fields, cap=2000):
    """JQL 한 번. nextPageToken 으로 끝까지 넘긴다."""
    out, token = [], None
    while True:
        body = {"jql": q, "maxResults": 100, "fields": fields}
        if token:
            body["nextPageToken"] = token
        req = urllib.request.Request(
            BASE + "/rest/api/3/search/jql",
            data=json.dumps(body).encode(),
            headers={
                "Authorization": "Basic " + base64.b64encode(f"{EMAIL}:{TOKEN}".encode()).decode(),
                "Content-Type": "application/json",
                "Accept": "application/json",
            })
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    d = json.load(r)
                break
            except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
                if attempt == 3:
                    raise
                import time as _t
                print(f"  지라 연결 실패({e}), {2**attempt}초 후 재시도")
                _t.sleep(2 ** attempt)
        out += d.get("issues", [])
        token = d.get("nextPageToken")
        if not token or d.get("isLast") or len(out) >= cap:
            return out


def F(n, *path, default=None):
    cur = n.get("fields", n)
    for p in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(p)
        if cur is None:
            return default
    return cur


def day(v):
    return v[:10] if v else None


def quarter_of(d):
    """'2026-09-01' → '26 3Q' (분기 = 생성일 기준). 날짜 없으면 ''."""
    if not d or len(d) < 7:
        return ""
    try:
        return "%s %dQ" % (d[2:4], (int(d[5:7]) - 1) // 3 + 1)
    except Exception:
        return ""


def org_of(display):
    """'최보경/Core-P Catalog bokyung.choi' → 'Core-P Catalog'"""
    if not display or "/" not in display:
        return ""
    return display.split("/", 1)[1].rsplit(" ", 1)[0]


def bucket_of(status):
    if status in DONE_ST:
        return "done"
    if status in DROP_ST:
        return "drop"
    if status in TODO_ST:
        return "todo"
    return "wip"


def state_of(n):
    """진행 중 / 예정 / 보류 / 완료 — 구버전 디자인실 대시보드와 같은 기준."""
    st  = F(n, "status", "name") or ""
    cat = F(n, "status", "statusCategory", "name") or ""
    if st.upper() == "HOLD":
        return "보류"
    if cat in ("완료", "Done"):
        return "완료"
    if cat in ("진행 중", "In Progress"):
        return "진행 중"
    return "예정"


def decrypt(box: dict, password: str) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    b = lambda x: base64.b64decode(x)
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), b(box["salt"]),
                              box.get("iter", 250000), 32)
    return AESGCM(key).decrypt(b(box["iv"]), b(box["ct"]), None).decode()


def load_sealed(name):
    """name.enc(암호화) 우선, 없으면 name.json(평문). 둘 다 없으면 None."""
    p = os.path.join(HERE, name + ".enc")
    if os.path.exists(p):
        if not GATE:
            sys.exit(f"{name}.enc 를 열려면 GATE_PASS 가 필요합니다.")
        return json.loads(decrypt(json.load(open(p, encoding="utf-8")), GATE))
    p = os.path.join(HERE, name + ".json")
    if os.path.exists(p):
        return json.load(open(p, encoding="utf-8"))
    return None


def save_sealed(name, obj):
    """GATE_PASS 가 있으면 name.enc 로 잠가 저장한다."""
    body = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    if GATE:
        json.dump(encrypt(body, GATE),
                  open(os.path.join(HERE, name + ".enc"), "w"), indent=0)
    else:
        open(os.path.join(HERE, name + ".json"), "w", encoding="utf-8").write(body)


def encrypt(payload: str, password: str) -> dict:
    """AES-256-GCM. 브라우저 WebCrypto 로 그대로 푼다."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt = os.urandom(16)
    iv   = os.urandom(12)
    key  = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 250000, 32)
    ct   = AESGCM(key).encrypt(iv, payload.encode(), None)
    b64  = lambda b: base64.b64encode(b).decode()
    return {"enc": "AES-GCM", "kdf": "PBKDF2-SHA256", "iter": 250000,
            "salt": b64(salt), "iv": b64(iv), "ct": b64(ct)}


def main():
    if not (EMAIL and TOKEN):
        sys.exit("JIRA_EMAIL / JIRA_TOKEN 이 없습니다.")
    tax = load_sealed("taxonomy")
    if not tax:
        sys.exit("taxonomy.enc 도 taxonomy.json 도 없습니다.")
    teams = tax["teams"]
    people = {m["name"]: (t, m) for t in teams for m in t["members"]}
    basisNow = load_sealed("basis") or {"tasks": {}}   # 완료 건 사이즈 태깅·히스토리용 조기 로드
    def _dnrow(d2):
        tn = d2[5] if len(d2) > 5 else None
        e = (basisNow.get("tasks") or {}).get(tn) if tn else None
        band = e.get("size") if e else None
        md = round((e.get("hours") or 0) / 8.0, 2) if e else None
        return [d2[0], d2[1], d2[2], (d2[3] if len(d2) > 3 else None),
                (d2[4] if len(d2) > 4 else None), band, md]
    accts  = [m["account"] for t in teams for m in t["members"] if m.get("account")]
    leads  = {m["name"]: m["account"] for t in teams for m in t["members"]
              if m.get("lead") and m.get("account")}
    IN = "(" + ",".join('"%s"' % a for a in accts) + ")"
    name_of = {m["account"]: m["name"] for t in teams for m in t["members"] if m.get("account")}

    FLD = ["summary", "status", "issuetype", "parent", "assignee", "reporter",
           "created", "resolutiondate", "labels", "project"]

    # ── 1. 실무 티켓 ────────────────────────────────────────────────
    # 7월 티켓 기준: 7/1 이후 생성분 전부 + 7/1 이전 생성이라도 (LEAD 이후 생성 & 진행 중, HOLD 제외)
    issues = jql(f'issuetype in ({TYPES}) AND assignee in {IN} '
                 f'AND (created >= "{CUT}" OR (created >= "{LEAD}" AND statusCategory = "In Progress" AND status != "HOLD")) '
                 f'AND (statusCategory != Done OR resolved >= "{CUT}") ORDER BY key ASC', FLD)
    print(f"티켓 {len(issues)}건")
    if len(issues) < 120:
        sys.exit(f"조회 결과가 비정상적으로 적습니다({len(issues)}건). data.json 을 덮어쓰지 않습니다.")

    # ── 2. 팀장 오너 에픽 ───────────────────────────────────────────
    epics = []
    if leads:
        LIN = "(" + ",".join('"%s"' % a for a in leads.values()) + ")"
        epics = jql(f'issuetype = Epic AND assignee in {LIN} AND created >= "{CUT}" '
                    f'AND (statusCategory != Done OR resolved >= "{CUT}") ORDER BY key ASC', FLD)
    print(f"팀장 에픽 {len(epics)}건")

    # ── 3. 조상 체인 (CBP 판정 · 과제 매칭용) ──────────────────────
    parent, meta = {}, {}
    for n in issues + epics:
        meta[n["key"]] = n
        p = F(n, "parent", "key")
        if p:
            parent[n["key"]] = p
    for _ in range(4):
        need = [p for p in set(parent.values()) if p not in meta]
        if not need:
            break
        for i in range(0, len(need), 45):
            for n in jql("key in (%s)" % ",".join(need[i:i + 45]), FLD):
                meta[n["key"]] = n
                p = F(n, "parent", "key")
                if p:
                    parent[n["key"]] = p

    def chain(k, d=5):
        out, c = [], parent.get(k)
        while c and d:
            out.append(c)
            c = parent.get(c)
            d -= 1
        return out

    def is_cbp(key):
        for a in [key] + chain(key):
            n = meta.get(a)
            if not n:
                continue
            if org_of(F(n, "reporter", "displayName") or "").startswith("Core-P"):
                return True
            if any(str(l).upper() == "CBP" for l in (F(n, "labels", default=[]) or [])):
                return True
        return False

    # ── 4. 과제에 붙이기 ───────────────────────────────────────────
    anchor = {}
    for tname, e in tax["tasks"].items():
        for a in e.get("anchors", []):
            anchor[a] = tname
        if e.get("initiative"):
            anchor.setdefault(e["initiative"], tname)
    BUCKET = "디자인QA"          # QA 요청만 담는 묶음 (담당자별로 크기를 따로 잡는다)
    M29 = {"M29CMPROD", "M29CEF"}

    def is_qa(summ):
        """디자인 QA 성격의 티켓인지 — 제목으로 판정한다."""
        u = summ.upper()
        if "디자인 QA" in summ or "디자인QA" in summ:
            return True
        return re.search(r"(^|[^A-Z])QA([^A-Z]|$)", u) is not None

    def clean_name(summ):
        """티켓 제목을 과제 이름으로 다듬는다 — 티켓 종류 표시만 떼어낸다."""
        t = summ.strip()
        for p in ("[Design] ", "[design] ", "[디자인] "):
            if t.startswith(p):
                t = t[len(p):].strip()
        return t or summ.strip()

    # 도메인 추론 — 기타 서비스로 떨어질 과제/QA 티켓을 제목·티켓 내용으로 실제 도메인에 배치한다.
    #  위에서부터 먼저 걸리는 규칙 하나로 도메인을 정한다(구체적 → 일반). 아무것도 안 걸리면 기타 서비스.
    DOMAIN_RULES = [
        (r"B2B", "기타 서비스"),
        (r"\[AI\]|트래커\s*자동화|워터마크|에이전트|AI\s*Native|AI네이티브|LLM", "AI 제품"),
        (r"유즈드|USED|중고", "유즈드"),
        (r"무진장", "무진장"),
        (r"글로벌\s*원앱|원앱|One-?App", "글로벌 원앱"),
        (r"해외|글로벌", "글로벌"),
        (r"검색|랭킹|브랜드숍|브랜드\s*인덱스|PLP|SRP|전시|딥링크|브릿지|추천판|전문관|디스커버리|필터", "탐색·검색"),
        (r"주문|클레임|장바구니|주문서|PDP|결제|배송|쿠폰|매입|스토어\s*출고|재고|오프라인|매장|무탠다드|29Connect|커머스|판매가", "커머스·주문결제"),
        (r"앱테크|엡테크|출석|래플|좋아요|최근본|알림|체험단|적립|케이뱅크|미션|이벤트딜", "앱테크·혜택"),
        (r"마이|FAQ|문의하기|1:1\s*문의|커뮤니티|스냅|후기|댓글|프로필|콘텐츠판|매거진", "마이·커뮤니티"),
        (r"광고|\bDA\b|캠페인|기획전|브랜딩|룩북|이메일|\bCBP\b", "브랜드광고·캠페인"),
        (r"VOC|리서치|서베이|설문|유저\s*테스트|사용성", "리서치·VOC"),
        (r"서체|폰트|컴포넌트|MDS|디자인\s*시스템|아이콘|디자인\s*가이드|인디케이터|헬스체크|밀도감", "공통UX"),
    ]
    _DOMAIN_RULES = [(re.compile(p, re.I), dom) for p, dom in DOMAIN_RULES]

    def guess_domain(title, ticket_titles):
        hay = (title or "") + " " + " ".join(ticket_titles or [])
        for rx, dom in _DOMAIN_RULES:
            if rx.search(hay):
                return dom
        return "기타 서비스"

    per = {}          # 담당자 → 과제명 → [티켓]
    hold, done = {}, {}
    fresh = []

    for n in issues:
        who = (F(n, "assignee", "displayName") or "").split("/")[0].strip()
        if who not in people:
            continue
        key, summ = n["key"], F(n, "summary") or ""
        st = state_of(n)
        if st == "보류":
            hold.setdefault(who, []).append([key, summ, F(n, "status", "name"), "", day(F(n, "created"))])
            continue
        if st == "완료":
            if day(F(n, "created")) >= CUT and (day(F(n, "resolutiondate")) or "") >= CUT:
                _tn = next((anchor[c] for c in [key] + chain(key) if c in anchor), None)
                done.setdefault(who, []).append([key, summ, "완료", day(F(n, "resolutiondate")), day(F(n, "created")), _tn])
            continue
        tname = next((anchor[c] for c in [key] + chain(key) if c in anchor), None)
        if not tname:
            root = next((c for c in reversed(chain(key))
                         if F(meta.get(c, {}), "issuetype", "name") in ("Initiative", "Epic")), None)
            if root and sum(1 for m2 in issues
                            if root in chain(m2["key"])
                            and (F(m2, "assignee", "displayName") or "").split("/")[0].strip() == who) >= 2:
                tname = (F(meta.get(root, {}), "summary") or summ).strip()
                if tname not in tax["tasks"]:
                    tax["tasks"][tname] = {"domain": "기타 서비스", "badges": ["신규"],
                                           "initiative": root, "platform": "무신사",
                                           "bucket": False, "anchors": []}
                    fresh.append(tname)
                anchor[root] = tname
            elif is_qa(summ):
                # QA 는 성격(QA)으로 두되, 도메인은 티켓 내용 기준으로 분산한다 → 도메인별 QA 버킷
                qdom = guess_domain(summ, [summ])
                tname = BUCKET + " · " + qdom
                if tname not in tax["tasks"]:
                    tax["tasks"][tname] = {"domain": qdom, "badges": ["QA"], "initiative": None,
                                           "platform": "무신사", "bucket": True, "anchors": []}
            else:
                # 기타 개선 건 — 티켓 하나를 과제 하나로 본다 (다른 과제와 같은 규칙 적용)
                tname = clean_name(summ)
                if tname not in tax["tasks"]:
                    tax["tasks"][tname] = {"domain": "기타 서비스", "badges": ["신규"],
                                           "initiative": None, "platform": "무신사",
                                           "bucket": False, "anchors": [key]}
                    fresh.append(tname)
        per.setdefault(who, {}).setdefault(tname, []).append([key, summ, st, None, F(n, "project", "key")])

    for w in done:
        done[w].sort(key=lambda r: r[3] or "", reverse=True)

    # ── 5. 팀장 오너 에픽 → 과제 ───────────────────────────────────
    for n in epics:
        who = (F(n, "assignee", "displayName") or "").split("/")[0].strip()
        if who not in people:
            continue
        key, summ = n["key"], F(n, "summary") or ""
        st = state_of(n)
        if st == "보류":
            hold.setdefault(who, []).append([key, summ, "HOLD", "", day(F(n, "created"))]); continue
        if st == "완료":
            done.setdefault(who, []).append([key, summ, "완료", day(F(n, "resolutiondate")), day(F(n, "created")), summ]); continue
        per.setdefault(who, {})[summ] = [[key, summ, st, None, F(n, "project", "key")]]
        tax["tasks"].setdefault(summ, {"domain": "기타 서비스", "badges": ["오너"], "initiative": None,
                                       "platform": "29CM" if F(n, "project", "key") in M29 else "무신사",
                                       "bucket": False, "anchors": [], "own": True})
        tax["tasks"][summ]["own"] = True
        if "오너" not in tax["tasks"][summ]["badges"]:
            tax["tasks"][summ]["badges"].append("오너")

    # ── 5.5 디자인QA 는 '성격(QA)' 고정 + 도메인은 티켓 내용 기준(버킷명에 이미 반영) ──
    #   과거 단일 "디자인QA" 버킷은 도메인별 "디자인QA · <도메인>" 버킷으로 분산한다.
    for tn, e in list(tax["tasks"].items()):
        if tn == BUCKET or tn.startswith(BUCKET + " · "):
            e["badges"] = ["QA"]
            e["bucket"] = True
    # FT·디자인QA(단일) 는 도메인 축 themes 에서 뺀다 (성격 축에만 남긴다)
    tax["themes"] = [th for th in tax["themes"] if th["k"] not in ("FT", "디자인QA")]

    # ── 6. D 조립 ──────────────────────────────────────────────────
    def dedupe(rows):
        ks = {r[0] for r in rows}
        kill = {a for r in rows for a in chain(r[0]) if a in ks}
        seen, out = set(), []
        for r in sorted(rows, key=lambda z: (z[2] != "진행 중", z[0])):
            if r[0] in kill or r[0] in seen:
                continue
            seen.add(r[0]); out.append(r)
        return out

    D = {"teams": [], "themes": tax["themes"], "sum": tax["summaries"], "short": tax.get("short", {}),
         "asof": (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).strftime("%Y-%m-%d %H:%M")}
    for t in teams:
        tm = {"k": t["key"], "name": t["name"], "lead": t["lead"],
              "n": len(t["members"]), "order": 0, "md": 0, "members": [], "over": 0, "hold": 0}
        for m in t["members"]:
            who = m["name"]
            tasks = []
            for tname, rows in (per.get(who) or {}).items():
                d = tax["tasks"].get(tname) or {"domain": "기타 서비스", "badges": ["신규"],
                                                "initiative": None, "platform": "무신사", "bucket": False}
                rows = dedupe(rows)
                if not rows:
                    continue
                badges = [b for b in d.get("badges", [])]
                if any(is_cbp(r[0]) for r in rows) and "CBP" not in badges:
                    badges.append("CBP")
                # PEL — 디자인 조직 자동화/툴링 이니셔티브: PEL 프로젝트 티켓이 붙은 과제 (티켓 생기면 자동 반영)
                if any(str(r[0]).startswith("PEL-") for r in rows) and "PEL" not in badges:
                    badges.append("PEL")
                # design-driven — 디자인 발의(FT)로 취급
                if "design-driven" in tname.lower() and "FT" not in badges:
                    badges.append("FT")
                pk = {r[4] for r in rows if r[4]}
                pf = d.get("platform", "무신사")
                if pk and pk <= M29:
                    pf = "29CM"
                elif pk & M29:
                    pf = "공통"
                dom = d.get("domain", "기타 서비스")
                # 기타 서비스로 떨어진 과제(오너 에픽·자동 신규건 등)는 내용으로 실제 도메인 추론
                is_bucket = d.get("bucket") or tname == BUCKET or tname.startswith(BUCKET + " · ")
                if dom == "기타 서비스" and not is_bucket:
                    dom = guess_domain(tname, [r[1] for r in rows])
                x = {"t": tname, "th": dom, "b": badges,
                     "init": d.get("initiative"), "pf": pf,
                     "tk": [[r[0], r[1], r[2], None] for r in rows],
                     "it": [r[1] for r in rows]}
                x["n"] = len(x["tk"])
                x["a"] = sum(1 for r in x["tk"] if r[2] == "진행 중")
                _crs = [day(F(meta.get(r[0]) or {}, "created")) for r in rows]
                _crs = [c for c in _crs if c]
                x["q"] = quarter_of(min(_crs)) if _crs else ""
                if d.get("bucket") or tname == BUCKET:
                    x["bkt"] = 1
                if d.get("own"):
                    x["own"] = 1
                tasks.append(x)
            tasks.sort(key=lambda z: (1 if z.get("bkt") else 0, -z["a"], -z["n"], z["t"]))
            tm["members"].append({
                "name": who, "role": m.get("role", ""), "lead": bool(m.get("lead")),
                "tasks": tasks, "n": sum(len(x["tk"]) for x in tasks),
                "hd": hold.get(who, []), "dn": [_dnrow(d2) for d2 in done.get(who, [])],
                "wk": 0, "over": 0, "md": 0})
        tm["members"].sort(key=lambda m2: (1 if m2["lead"] else 0, -m2["n"], m2["name"]))
        tm["hold"] = sum(len(m2["hd"]) for m2 in tm["members"])
        D["teams"].append(tm)

    D["taskN"] = sum(len(m["tasks"]) for t in D["teams"] for m in t["members"])
    D["tkN"]   = sum(len(x["tk"]) for t in D["teams"] for m in t["members"] for x in m["tasks"])
    D["actN"]  = sum(1 for t in D["teams"] for m in t["members"] for x in m["tasks"]
                     for k in x["tk"] if k[2] == "진행 중")
    D["rowN"]  = D["tkN"] - D["actN"]
    D["doneN"] = sum(len(m["dn"]) for t in D["teams"] for m in t["members"])
    D["holdN"] = sum(len(m["hd"]) for t in D["teams"] for m in t["members"])

    # ── 7. FT 흐름 ─────────────────────────────────────────────────
    ftn = jql("project = FT ORDER BY key ASC", FLD, cap=1200)
    kids = set(F(n, "parent", "key") for n in ftn if F(n, "parent", "key"))
    tmof = {m["name"]: t["name"] for t in teams for m in t["members"]}
    ft = []
    for n in ftn:
        if n["key"] in kids:
            continue
        who = (F(n, "assignee", "displayName") or "").split("/")[0].strip()
        labs = [str(l) for l in (F(n, "labels", default=[]) or [])]
        if who not in people and "design-driven" not in labs:
            continue
        cr = day(F(n, "created"))
        if not cr or cr < CUT:
            continue
        st = F(n, "status", "name") or ""
        ft.append([n["key"], cr, day(F(n, "resolutiondate")), bucket_of(st), st,
                   who if who in people else (who or ""),
                   tmof.get(who, "미배정" if not who else "그 외"), F(n, "summary") or ""])
    ft.sort(key=lambda r: (r[1], r[0]))
    D["ft"] = ft
    print(f"FT {len(ft)}건")

    # 슬랙(의장 보고)·ONE 보드는 사람이 판독한 내용이라 리포 파일에서 그대로 가져온다
    D["sl"]  = load_sealed("slack") or []
    D["one"] = load_sealed("one") or []
    D["nodN"] = len(D["one"])

    # ── 7.7 스냅샷 히스토리 (팀별 속도 추세용 — 날짜별 1건 upsert) ──
    try:
        def _med(a):
            a = sorted(v for v in a if v is not None and v >= 0)
            return None if not a else (a[len(a)//2] if len(a) % 2 else (a[len(a)//2-1]+a[len(a)//2])/2)
        _today = (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).strftime("%Y-%m-%d")
        snap = {}
        for tm in D["teams"]:
            mem = [m for m in tm["members"] if not m.get("lead")]
            leads = []
            doneN = 0
            for m in tm["members"]:
                for r in m.get("dn", []):
                    doneN += 1
                    rv = r[3] if len(r) > 3 else None
                    cv = r[4] if len(r) > 4 else None
                    if rv and cv:
                        try:
                            dd = (datetime.date.fromisoformat(rv) - datetime.date.fromisoformat(cv)).days
                            if dd >= 0:
                                leads.append(dd)
                        except Exception:
                            pass
            actMd = 0.0
            actN = 0
            for m in mem:
                for x in m.get("tasks", []):
                    if x.get("a", 0) > 0:
                        e = (basisNow.get("tasks") or {}).get(x["t"])
                        actMd += ((e.get("hours") if e else 9) or 9) / 8.0
                        actN += 1
            lm = _med(leads)
            avg = round(actMd/actN, 2) if actN else 0
            snap[tm["k"]] = {"n": len(mem), "doneN": doneN, "leadMed": lm,
                             "avgMd": avg, "loadMd": round(actMd, 1),
                             "spd": round(lm/avg, 2) if (lm is not None and avg > 0) else None}
        _HIST_SNAP = {"date": _today, "teams": snap}   # basis._hist 에 upsert (8단계)
    except Exception as _e:
        _HIST_SNAP = None
        print("history 스냅샷 건너뜀:", _e)

    # ── 8. 저장 ────────────────────────────────────────────────────
    save_sealed("taxonomy", tax)
    basis = load_sealed("basis") or {}
    basis.setdefault("tasks", {})
    for tname in tax["tasks"]:
        basis["tasks"].setdefault(tname, {"size": "M", "hours": 9, "provisional": True})
    # 팀별 속도 추세 히스토리는 basis 안에 함께 저장(별도 파일 불필요 → 워크플로 수정 불필요)
    if _HIST_SNAP:
        h = basis.setdefault("_hist", {"days": []})
        h["days"] = [d for d in h.get("days", []) if d.get("date") != _HIST_SNAP["date"]]
        h["days"].append(_HIST_SNAP)
        h["days"] = h["days"][-120:]
        print("history 스냅샷: %s (%d일치, basis 내장)" % (_HIST_SNAP["date"], len(h["days"])))
    save_sealed("basis", basis)

    D["basis"] = basis          # 페이지는 이 번들 하나만 받는다(팀 히스토리 basis._hist 포함)
    payload = json.dumps(D, ensure_ascii=False, separators=(",", ":"))
    out = os.path.join(HERE, "data.json")
    if GATE:
        json.dump(encrypt(payload, GATE), open(out, "w"), indent=0)
        print("data.json 암호화 저장")
    else:
        open(out, "w", encoding="utf-8").write(payload)
        print("data.json 평문 저장 (GATE_PASS 없음)")
    print(f"과제 {D['taskN']} 티켓 {D['tkN']} 진행중 {D['actN']} 예정 {D['rowN']} "
          f"보류 {D['holdN']} 완료 {D['doneN']}")
    if fresh:
        print("새 과제: " + ", ".join(fresh))


if __name__ == "__main__":
    main()
