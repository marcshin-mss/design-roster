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


def adf_text(node):
    """Jira 설명(ADF JSON) → 평문. 티켓·에픽 내용을 사이징 근거로 쓰기 위해 추출."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(adf_text(x) for x in node)
    if isinstance(node, dict):
        t = node.get("type")
        if t == "text":
            return node.get("text", "")
        if t == "hardBreak":
            return "\n"
        inner = adf_text(node.get("content"))
        if t in ("paragraph", "heading", "listItem", "blockquote",
                 "bulletList", "orderedList", "codeBlock", "tableRow"):
            return inner + "\n"
        return inner
    return ""


def _compact(s):
    return re.sub(r"\s", "", s or "")


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


SYNC_URL = "https://design-roster-sync.marc-shin.workers.dev/"


def fetch_overrides():
    """워커 공유 기준(담당자가 조정한 sz 오버라이드)을 가져와 복호화한다.
    실패하면 {} — 스냅샷은 base 사이즈만으로도 남는다."""
    if not GATE:
        return {}
    try:
        req = urllib.request.Request(
            SYNC_URL, headers={"User-Agent": "Mozilla/5.0 design-roster-snap"})
        raw = urllib.request.urlopen(req, timeout=30).read().decode()
        box = json.loads(raw)
        if not box or not box.get("ct"):
            return {}
        d = json.loads(decrypt(box, GATE))
        sz = d.get("sz")
        return sz if isinstance(sz, dict) else {}
    except Exception as e:
        print("오버라이드 가져오기 실패(무시):", e)
        return {}


HOLIDAY_ICAL = ("https://calendar.google.com/calendar/ical/"
                "ko.south_korea%23holiday%40group.v.calendar.google.com/public/basic.ics")
# 공휴일 아님(제외): description 이 '공휴일' 이어도 빼는 것 + description 없을 때 블록리스트
HOL_BLOCK = {"제헌절", "국군의날", "크리스마스 이브", "섣달 그믐날", "정월대보름",
             "한식", "초복", "중복", "말복", "석가탄신일 전야"}


def _ical_fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "design-roster-leave"})
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")


def _ical_events(txt):
    """VEVENT 목록 → [{summary, desc, start(date), end(date)}]. all-day(VALUE=DATE)만."""
    txt = txt.replace("\r\n", "\n").replace("\r", "\n")
    unfolded = []
    for ln in txt.split("\n"):
        if ln[:1] in (" ", "\t") and unfolded:
            unfolded[-1] += ln[1:]
        else:
            unfolded.append(ln)
    evs, cur = [], None
    for ln in unfolded:
        if ln == "BEGIN:VEVENT":
            cur = {}
        elif ln == "END:VEVENT":
            if cur is not None:
                evs.append(cur)
            cur = None
        elif cur is not None and ":" in ln:
            k, v = ln.split(":", 1)
            key = k.split(";")[0].upper()
            if key == "SUMMARY":
                cur["summary"] = v.strip()
            elif key == "DESCRIPTION":
                cur["desc"] = v.strip()
            elif key == "DTSTART" and "DATE" in k.upper() and "T" not in v:
                cur["start"] = v.strip()[:8]
            elif key == "DTEND" and "DATE" in k.upper() and "T" not in v:
                cur["end"] = v.strip()[:8]
    return evs


def _wkid(d):
    iso = d.isocalendar()
    return "%04d-W%02d" % (iso[0], iso[1])


def _weekdays(s8, e8):
    """YYYYMMDD start(포함)~end(제외) 사이 평일 date 목록."""
    try:
        s = datetime.date(int(s8[:4]), int(s8[4:6]), int(s8[6:8]))
        e = datetime.date(int(e8[:4]), int(e8[4:6]), int(e8[6:8])) if e8 else s + datetime.timedelta(days=1)
    except Exception:
        return []
    out, cur = [], s
    while cur < e and (cur - s).days < 60:
        if cur.weekday() < 5:
            out.append(cur)
        cur += datetime.timedelta(days=1)
    return out


def compute_leave(names):
    """휴가·공휴일을 iCal에서 계산 → {asof, hol:{주:일수}, vac:{이름:{주:일수}}}.
    PXD_LEAVE_ICAL(휴가 캘린더 비공개 iCal) 있으면 매 빌드 자동 갱신,
    없으면 봉인된 leave.enc 로 폴백."""
    vac_url = os.environ.get("PXD_LEAVE_ICAL", "").strip()
    if not vac_url:
        return load_sealed("leave") or {}
    today = (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).date()
    lo = today - datetime.timedelta(weeks=2)
    hi = today + datetime.timedelta(weeks=20)

    def in_range(d):
        return lo <= d <= hi

    hol, hold = {}, set()
    try:
        for e in _ical_events(_ical_fetch(HOLIDAY_ICAL)):
            summ = e.get("summary", "")
            desc = e.get("desc", "")
            is_hol = ("공휴일" in desc) if desc else (summ not in HOL_BLOCK)
            if not is_hol or summ in HOL_BLOCK or summ == "제헌절":
                continue
            for d in _weekdays(e.get("start", ""), e.get("end", "")):
                if in_range(d):
                    hol[_wkid(d)] = hol.get(_wkid(d), 0) + 1
                if today - datetime.timedelta(weeks=27) <= d <= hi:   # 주간 기록 기준일(금→직전 영업일) 라벨용, 지난 26주까지
                    hold.add(d.isoformat())
    except Exception as ex:
        print("공휴일 iCal 실패(폴백 시도):", ex)
        hol = ((load_sealed("leave") or {}).get("hol")) or {}

    vac = {}
    try:
        for e in _ical_events(_ical_fetch(vac_url)):
            summ = e.get("summary", "")
            if "]" not in summ:
                continue
            nm = summ.split("]", 1)[1].strip()
            if nm not in names:
                continue
            frac = 0.25 if "반반차" in summ else (0.5 if "반차" in summ else 1.0)
            # 건강검진(반일 공가)+반차 = 하루 전체 부재 (예: "[건강검진 + 오후반차] 이름"), Marc 2026-10-08
            if "건강검진" in summ and frac < 1.0:
                frac = min(1.0, frac + 0.5)
            for d in _weekdays(e.get("start", ""), e.get("end", "")):
                if in_range(d):
                    vac.setdefault(nm, {})
                    vac[nm][_wkid(d)] = round(vac[nm].get(_wkid(d), 0) + frac, 2)
    except Exception as ex:
        print("휴가 iCal 실패:", ex)
        return load_sealed("leave") or {}

    print("휴가·공휴일 iCal 반영: 공휴일주 %d, 휴가인원 %d" % (len(hol), len(vac)))
    return {"asof": today.strftime("%Y-%m-%d"), "src": "ical", "hol": hol, "hold": sorted(hold), "vac": vac}


SLACK_TOKEN = os.environ.get("SLACK_TOKEN", "")
SL_CH    = "C09AAQF25QT"           # #one-제품디자인실 (비공개)
SL_CHAIR = "U02AN7XEDE3"           # 의장(조만호) 'one' 계정
SL_HEAD  = {"신행철"}               # 로스터 밖이지만 보고자로 인정
SL_OK_W  = ("좋", "승인", "진행", "오케", "ok", "굿", "고고", "go", "확인했", "됐", "합시다", "하시죠", "👍")
SL_NO_W  = ("보류", "다시", "재검토", "별로", "아닌", "아니", "고민", "수정", "바꿔", "빼", "왜", "?")
SL_OK_R  = {"+1", "thumbsup", "ok", "ok_hand", "white_check_mark", "heavy_check_mark", "100", "clap", "승인", "good"}


def _slack(method, **params):
    """슬랙 Web API GET 한 번(429 면 Retry-After 만큼 쉬고 재시도)."""
    import time as _t
    url = "https://slack.com/api/" + method + "?" + urllib.parse.urlencode(params)
    for attempt in range(5):
        req = urllib.request.Request(url, headers={"Authorization": "Bearer " + SLACK_TOKEN})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                _t.sleep(int(e.headers.get("Retry-After", "5")) + 1)
                continue
            raise
        if not d.get("ok"):
            if d.get("error") == "ratelimited":
                _t.sleep(5)
                continue
            raise RuntimeError(f"slack {method}: {d.get('error')}")
        return d
    raise RuntimeError(f"slack {method}: 재시도 초과")


def slack_reports(people, ft_rows):
    """#one-제품디자인실 에서 디자인 리더가 의장을 멘션해 올린 컨펌 요청과 의장 반응을 읽는다.
    행 = [date, who, kind, out, ap, title, jirakeys, confidence, jirasummaries]
    토큰이 없거나 실패하면 None(→ 봉인 스냅샷 사용). 읽기 전용."""
    if not SLACK_TOKEN:
        print("  SLACK_TOKEN 없음 — 슬랙 보고는 스냅샷 사용")
        return None
    import difflib
    try:
        oldest = datetime.datetime.strptime(CUT, "%Y-%m-%d").replace(
            tzinfo=datetime.timezone(datetime.timedelta(hours=9))).timestamp()
        msgs, cur = [], None
        while True:
            kw = {"channel": SL_CH, "oldest": "%.6f" % oldest, "limit": 200}
            if cur:
                kw["cursor"] = cur
            d = _slack("conversations.history", **kw)
            msgs += d.get("messages", [])
            cur = (d.get("response_metadata") or {}).get("next_cursor")
            if not cur:
                break
        names = {}

        def name_of(uid):
            if uid not in names:
                try:
                    u = _slack("users.info", user=uid).get("user") or {}
                    pr = u.get("profile") or {}
                    raw = pr.get("display_name") or pr.get("real_name") or u.get("real_name") or ""
                    names[uid] = re.split(r"[/(\s]", raw.strip())[0] if raw.strip() else ""
                except Exception:
                    names[uid] = ""
            return names[uid]

        ftsum = {r[0]: r[7] for r in (ft_rows or [])}
        snap = {(r[0], r[5]): r for r in (load_sealed("slack") or []) if len(r) >= 9}
        KST = datetime.timezone(datetime.timedelta(hours=9))
        rows = []
        for m in msgs:
            if m.get("subtype") or m.get("user") == SL_CHAIR:
                continue
            if m.get("thread_ts") and m.get("thread_ts") != m.get("ts"):
                continue
            txt = m.get("text") or ""
            if "<@" + SL_CHAIR not in txt:
                continue
            who = name_of(m.get("user") or "")
            if who not in people and who not in SL_HEAD:
                continue
            dt = datetime.datetime.fromtimestamp(float(m["ts"]), KST).strftime("%Y-%m-%d")
            mb = re.search(r"\*([^*\n]{2,120})\*", txt)
            title = (mb.group(1) if mb else re.sub(r"<[^>]+>", "", txt).strip().split("\n")[0])[:80].strip()
            # 의장 반응: 스레드 댓글 → 리액션 순으로 본다
            said = []
            if m.get("reply_count"):
                rp = _slack("conversations.replies", channel=SL_CH, ts=m["ts"], limit=200).get("messages", [])
                said = [r.get("text") or "" for r in rp[1:] if r.get("user") == SL_CHAIR]
                txt += "\n" + "\n".join(r.get("text") or "" for r in rp[1:])
            reacted = any(SL_CHAIR in (rx.get("users") or []) and rx.get("name", "").split("::")[0] in SL_OK_R
                          for rx in (m.get("reactions") or []))
            if said:
                last = said[-1].lower()
                ok = any(w in last for w in SL_OK_W)
                no = any(w in last for w in SL_NO_W)
                out = "승인" if ok and not no else "보류"
            elif reacted:
                out = "승인"
            else:
                out = "무응답"
            keys = sorted(set(re.findall(r"\b((?:FT|PD)-\d+)\b", txt)), key=lambda k: (k[:2], int(k.split("-")[1])))
            cf = "high" if keys else "-"
            if not keys and title:
                def _sim(a, b):
                    b = re.sub(r"\[[^\]]*\]\s*", "", b).strip()
                    if not b:
                        return 0
                    if a in b or b in a:
                        return 0.9
                    return difflib.SequenceMatcher(None, a, b).ratio()
                best = sorted(((_sim(title, sm), k) for k, sm in ftsum.items() if sm), reverse=True)[:1]
                if best and best[0][0] >= 0.6:
                    keys, cf = [best[0][1]], "medium"
            old = snap.get((dt, title))
            if old and not keys and old[6]:          # 사람이 판독해 둔 매칭이 있으면 유지
                keys, cf = list(old[6]), old[7]
            js = " | ".join(ftsum.get(k, "") for k in keys if ftsum.get(k))
            if not js and old and keys == list(old[6] or []):
                js = old[8]
            rows.append([dt, who, "컨펌요청", out, "조만호" if out != "무응답" else "", title, keys, cf, js])
        rows.sort(key=lambda r: (r[0], r[5]))
        print(f"슬랙 의장 보고 {len(rows)}건 (승인 {sum(r[3] == '승인' for r in rows)} · "
              f"보류 {sum(r[3] == '보류' for r in rows)} · 무응답 {sum(r[3] == '무응답' for r in rows)})")
        return rows if rows else None
    except Exception as e:
        print(f"  슬랙 조회 실패({e}) — 스냅샷 사용")
        return None


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
    # 퇴사·이동 인원 — taxonomy(봉인) 를 다시 풀지 않고 빌드 시점에 로스터에서 뺀다 (Marc 2026-09-29)
    LEFT = {"김정탁"}
    for _t in teams:
        _t["members"] = [m for m in _t["members"] if m.get("name") not in LEFT]
    # 신규 입사자 자동 편입 (Marc 2026-09-30) — 로스터(taxonomy)에 없는 사람이 PXD 디자인 티켓이 도는 프로젝트에서
    #   디자인 티켓을 받으면, Jira 표시명의 소속(예: 'Biz-P Commerce Design')으로 조직을 찾아 멤버로 넣는다.
    #   → 로스터·리소스·조직도(HC 자리)에 자동 반영. 다른 조직(Core-P 등)·29CM Customer Engagement 는 소속이 달라 제외.
    _join_first = {}      # 신규 입사자 첫 티켓 생성일 (인원 변동 기록용)
    try:
        _known = {m.get("account") for t in teams for m in t["members"] if m.get("account")}
        _IN0 = "(" + ",".join('"%s"' % a for a in _known) + ")"
        _pj = sorted({F(n, "project", "key") for n in jql(f'assignee in {_IN0} AND created >= -90d', ["project"], cap=1500)
                      if F(n, "project", "key")})
        _added = {}
        if _pj:
            _cand = jql(f'project in ({",".join(_pj)}) AND issuetype in ({TYPES}) AND created >= -60d '
                        f'AND assignee is not EMPTY AND assignee not in {_IN0}', ["assignee", "created"], cap=1500)
            for n in _cand:
                a = F(n, "assignee") or {}
                acc, disp = a.get("accountId"), a.get("displayName") or ""
                _cr = (F(n, "created") or "")[:10]
                if acc and _cr and (acc not in _join_first or _cr < _join_first[acc]):
                    _join_first[acc] = _cr
                if not acc or acc in _known or acc in _added:
                    continue
                org = org_of(disp)
                if not org or "Customer" in org:
                    continue
                tm = next((t for t in teams if org == t["name"] or org.endswith(" " + t["name"])), None)
                nm = disp.split("/")[0].strip()
                if tm is None or not nm or nm in LEFT:
                    continue
                _added[acc] = (tm, nm)
        for acc, (tm, nm) in _added.items():
            tm["members"].append({"name": nm, "account": acc, "role": "", "lead": False, "auto": True})
            print(f"신규 입사자 자동 편입: {nm} → {tm['name']}")
    except Exception as _e:
        print("신규 입사자 탐지 건너뜀:", _e)
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
           "created", "resolutiondate", "labels", "project", "updated", "description", "priority", "duedate"]

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

    def desc_of(key):
        n = meta.get(key)
        return adf_text(F(n, "description")).strip() if n else ""

    def evidence_of(rows):
        """과제 사이징 근거 내용을 찾는다. 실무 티켓 본문이 비어 있으면
        상위 에픽·이니셔티브를 타고 올라가 내용 있는 조상을 쓴다.
        반환: (본문텍스트, 근거키, 근거유형)."""
        own = "\n".join(desc_of(r[0]) for r in rows).strip()
        if len(_compact(own)) >= 30:
            k0 = rows[0][0] if rows else None
            ty0 = F(meta.get(k0) or {}, "issuetype", "name") or "티켓"
            return own, k0, ty0
        for r in rows:
            for a in chain(r[0]):
                n = meta.get(a)
                if not n:
                    continue
                dtx = desc_of(a)
                if len(_compact(dtx)) >= 30:
                    return dtx, a, (F(n, "issuetype", "name") or "상위")
        return own, (rows[0][0] if rows else None), "티켓"

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
    # 과제 병합 (Marc 승인 2026-09-28) — 소과제·분산 티켓을 대표 과제로 묶는다.
    #   각 키(티켓/에픽)를 대표 과제명으로 재매핑. 기존 과제의 앵커까지 전부 흡수해 split 없이 합친다.
    MERGE_ANCHORS = {
        'PEL-3012': '[Phase 2] mds-playbook — 파일럿 준비',
        'PEL-3015': '[Phase 2] mds-playbook — 파일럿 준비',
        'PEL-4606': '[Phase 2] mds-playbook — 파일럿 준비',
        'PEL-3211': '[Phase 2] mds-playbook — 파일럿 준비',
        'PEL-3014': '[Phase 2] mds-playbook — 파일럿 준비',
        'PEL-3016': '[Phase 2] mds-playbook — 파일럿 준비',
        'GPRD-12135': '글로벌 상품 쿠폰 도입',
        'GPRD-12314': '글로벌 상품 쿠폰 도입',
        'GPRD-12136': '글로벌 상품 쿠폰 도입',
        'GPRD-12137': '글로벌 상품 쿠폰 도입',
        'GPRD-12138': '글로벌 상품 쿠폰 도입',
        'GPRD-12179': '글로벌 상품 쿠폰 도입',
        'TM-2799': '글로벌 상품 쿠폰 도입',
        'PD-9023': '[앱테크] 무신사 대국민 행운권',
        'PD-10025': '[앱테크] 무신사 대국민 행운권',
        'PD-9070': '[앱테크] 무신사 대국민 행운권',
        'PD-9380': '[앱테크] 무신사 대국민 행운권',
        'PD-9024': '[앱테크] 무신사 대국민 행운권',
        'PD-9025': '[앱테크] 무신사 대국민 행운권',
        'AP-177': '[앱테크] 무신사 대국민 행운권',
        'PD-9155': '[무진장] 26 겨울 캠페인·홈 개편',
        'PD-9218': '[무진장] 26 겨울 캠페인·홈 개편',
        'PD-9220': '[무진장] 26 겨울 캠페인·홈 개편',
        'PD-9221': '[무진장] 26 겨울 캠페인·홈 개편',
        'PD-9223': '[무진장] 26 겨울 캠페인·홈 개편',
        'PD-9224': '[무진장] 26 겨울 캠페인·홈 개편',
        'PD-9219': '[무진장] 26 겨울 캠페인·홈 개편',
        'PD-9222': '[무진장] 26 겨울 캠페인·홈 개편',
        'PD-9464': '[무진장] 26 겨울 캠페인·홈 개편',
        'TM-4273': '[무진장] 26 겨울 캠페인·홈 개편',
        'PD-10040': '[무진장] 26 겨울 캠페인·홈 개편',
        'PD-10042': '[무진장] 26 겨울 캠페인·홈 개편',
        'PD-10127': '[무진장] 26 겨울 캠페인·홈 개편',
        'PD-10128': '[무진장] 26 겨울 캠페인·홈 개편',
        'PD-10129': '[무진장] 26 겨울 캠페인·홈 개편',
        'PD-10130': '[무진장] 26 겨울 캠페인·홈 개편',
        'PD-10131': '[무진장] 26 겨울 캠페인·홈 개편',
        'PD-10132': '[무진장] 26 겨울 캠페인·홈 개편',
        'PD-10133': '[무진장] 26 겨울 캠페인·홈 개편',
        'PD-9061': '[유즈드] 판매·정산 운영 개선',
        'PD-9207': '[유즈드] 판매·정산 운영 개선',
        'PD-9209': '[유즈드] 판매·정산 운영 개선',
        # 'TM-518'(인게이지먼트 팀 이니셔티브)는 병합에서 뺌 — KTLO·앱테크 에픽까지 유즈드로 묶여서 (Marc 2026-10-06)
        'PD-8865': '[유즈드] 판매·정산 운영 개선',
        'TM-3111': '[유즈드] 판매·정산 운영 개선',
        'PD-8133': '[유즈드] 판매·정산 운영 개선',
        'PD-8659': '[유즈드] 판매·정산 운영 개선',
        'PD-10020': '[유즈드] 판매·정산 운영 개선',
        'PD-8282': '[오프라인] 매장 연동',
        'PD-9140': '[오프라인] 매장 연동',
        'TM-2809': '[오프라인] 매장 연동',
        'PD-9204': '[스냅/후기/콘텐츠] 댓글 시스템 통합',
        'PD-8816': '[스냅/후기/콘텐츠] 댓글 시스템 통합',
        'TM-2254': '[스냅/후기/콘텐츠] 댓글 시스템 통합',
        'PD-10093': '[스냅/후기/콘텐츠] 댓글 시스템 통합',
        'M29CMPROD-1730': '[이구위크] 구매챌린지 온사이트 상시 진입점',
        'M29CMPROD-1741': '[이구위크] 구매챌린지 온사이트 상시 진입점',
        'M29CMPROD-1653': '[브랜드광고] 광고판 운영 (무신사·29CM)',
        'M29CMPROD-1639': '[브랜드광고] 광고판 운영 (무신사·29CM)',
        'PD-9373': '[브랜드광고] 광고판 운영 (무신사·29CM)',
        # 'MSS-194'(MSS 2026 KTLO)는 병합에서 뺌 — VOC·리서치·KTLO 에픽까지 광고판으로 묶여서 (Marc 2026-10-06)
        'PD-10018': '[탐색] 카테고리 메뉴 개선 (블루닷·이미지 4열)',
        'PD-10160': '[탐색] 카테고리 메뉴 개선 (블루닷·이미지 4열)',
        'PD-10101': '[탐색] AI 태그 노출·태깅 자동화 대응',
        'PD-10103': '[탐색] AI 태그 노출·태깅 자동화 대응',
        'PD-9444': '[AI 해설] 발매판·랭킹판 디자인',
        'TM-4263': '[AI 해설] 발매판·랭킹판 디자인',
        'PD-9445': '[AI 해설] 발매판·랭킹판 디자인',
        'TM-4262': '[AI 해설] 발매판·랭킹판 디자인',
    }
    MERGE_DOMAIN = {
        '[Phase 2] mds-playbook — 파일럿 준비': '공통UX',
        '글로벌 상품 쿠폰 도입': '글로벌',
        '[앱테크] 무신사 대국민 행운권': '앱테크·혜택',
        '[무진장] 26 겨울 캠페인·홈 개편': '무진장/이구위크',
        '[유즈드] 판매·정산 운영 개선': '유즈드',
        '[오프라인] 매장 연동': '커머스·주문결제',
        '[스냅/후기/콘텐츠] 댓글 시스템 통합': '마이·커뮤니티',
        '[이구위크] 구매챌린지 온사이트 상시 진입점': '무진장/이구위크',
        '[브랜드광고] 광고판 운영 (무신사·29CM)': '브랜드광고·캠페인',
        '[탐색] 카테고리 메뉴 개선 (블루닷·이미지 4열)': '탐색·검색',
        '[탐색] AI 태그 노출·태깅 자동화 대응': '탐색·검색',
        '[AI 해설] 발매판·랭킹판 디자인': 'AI 제품',
    }
    for _mk, _mn in MERGE_ANCHORS.items():
        anchor[_mk] = _mn
        if _mn not in tax["tasks"]:
            tax["tasks"][_mn] = {"domain": MERGE_DOMAIN.get(_mn, "기타 서비스"), "badges": [],
                                 "initiative": None, "platform": "무신사", "bucket": False, "anchors": []}
        elif _mn in MERGE_DOMAIN:
            tax["tasks"][_mn]["domain"] = MERGE_DOMAIN[_mn]
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

    # ── 도메인 수기 오버라이드 (Marc 지정, 2026-09-28) ──
    #   내용 기준으로 특정 과제를 지정 도메인에 강제 배치. taxonomy/guess 보다 우선.
    #   부분일치(소문자) — 접두어([PD]·[공통]·[Admin] 등)가 붙어도 잡힌다.
    DOMAIN_OVERRIDE_SUB = [
        ("optimal user", "탐색·검색"),
        ("옵티멀", "탐색·검색"),
        ("카테고리 메뉴 블루닷", "탐색·검색"),
        ("상품 리스트 정보 영역 개선", "탐색·검색"),
        ("브랜드탭 상품더보기", "탐색·검색"),
        ("ai 태깅 자동화 확대", "탐색·검색"),
        ("발견탭 관심사", "탐색·검색"),
        ("이미지 4열", "탐색·검색"),
        ("구매챌린지", "무진장/이구위크"),
    ]

    def domain_override(name):
        low = (name or "").lower()
        for sub, dom in DOMAIN_OVERRIDE_SUB:
            if sub in low:
                return dom
        return None

    # FT(FastTrack) 판정 — 디자인 발의(design-driven)에 국한하지 않는다.
    #   실무 티켓/조상이 FT 프로젝트이거나 fast-track 계열 라벨·요약 마커를 가지면 FT 성격으로 본다.
    FT_LABELS = {"fasttrack", "fast-track-away", "fast-track-home", "pel-fast-track",
                 "design-driven", "ux-ft", "ux-ft-backlog"}
    FT_MARK = re.compile(r"\[FT[-\s]|FT\s*팔로업|SNAP\s*FT|design-driven", re.I)

    def is_ft(rows):
        for r in rows:
            key = r[0]; summ = r[1] or ""; proj = str(r[4] or "")
            if proj == "FT" or str(key).startswith("FT-"):
                return True
            for a in [key] + chain(key):
                if str(a).startswith("FT-"):
                    return True
                nn = meta.get(a)
                if nn and any(str(l).lower() in FT_LABELS
                              for l in (F(nn, "labels", default=[]) or [])):
                    return True
            if FT_MARK.search(summ):
                return True
        return False

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
        if st == "예정" and (F(n, "status", "name") or "") != "SUGGESTED":
            continue   # 팀별 과제의 '예정'은 SUGGESTED 상태만 (Backlog·할일 등 제외)
        tname = next((anchor[c] for c in [key] + chain(key) if c in anchor), None)
        if not tname:
            # 새 과제의 단위는 가장 가까운 에픽(없으면 이니셔티브) — 과제 묶음 기준 (Marc 2026-10-06)
            root = next((c for c in chain(key) if F(meta.get(c, {}), "issuetype", "name") == "Epic"), None) or \
                next((c for c in chain(key) if F(meta.get(c, {}), "issuetype", "name") == "Initiative"), None)
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

    # ── 4.5 에픽 단위 분리 (서정명 제보 · Marc 2026-10-06) ──────────────
    #   한 과제에 서로 다른 에픽(QA 에픽 제외)의 티켓이 섞이면 에픽마다 별도 과제로 나눈다.
    #   예) 'AI 패션 코디네이터 도입' = PD-8805(이정수) + PD-10001(유정선) → 에픽별 2과제.
    #   에픽 없이 이니셔티브 바로 아래 붙은 티켓은 원래 과제에 남는다.
    #   예외: MERGE_ANCHORS 로 Marc 가 명시 승인한 병합 과제는 그대로 둔다(나누려면 거기서 빼야 함).
    MERGE_NAMES = set(MERGE_ANCHORS.values())

    def near_epic(k):
        return next((c for c in chain(k) if F(meta.get(c, {}), "issuetype", "name") == "Epic"), None)

    _tk_ep = {}
    for _w, _tasks in per.items():
        for _tn, _rows in _tasks.items():
            if _tn in MERGE_NAMES or _tn == BUCKET or _tn.startswith(BUCKET + " · "):
                continue
            for _r in _rows:
                _ep = near_epic(_r[0])
                if _ep and not is_qa(F(meta.get(_ep, {}), "summary") or ""):
                    _tk_ep.setdefault(_tn, set()).add(_ep)
    SPLIT = {}
    for _tn, _eps in _tk_ep.items():
        if len(_eps) < 2:
            continue
        _base = tax["tasks"].get(_tn, {})
        for _ep in _eps:
            _nm = clean_name(F(meta.get(_ep, {}), "summary") or _ep)
            if _nm == _tn:
                continue
            SPLIT[(_tn, _ep)] = _nm
            if _nm not in tax["tasks"]:
                tax["tasks"][_nm] = {"domain": _base.get("domain", "기타 서비스"),
                                     "badges": [b for b in _base.get("badges", []) if b not in ("신규", "오너")],
                                     "initiative": _ep, "platform": _base.get("platform", "무신사"),
                                     "bucket": False, "anchors": [_ep], "split_from": _tn}
                fresh.append(_nm)
            anchor[_ep] = _nm
    for _w, _tasks in per.items():
        for _tn in list(_tasks.keys()):
            _keep = []
            for _r in _tasks[_tn]:
                _nn = SPLIT.get((_tn, near_epic(_r[0])))
                if _nn:
                    _tasks.setdefault(_nn, []).append(_r)
                else:
                    _keep.append(_r)
            if _keep:
                _tasks[_tn] = _keep
            else:
                del _tasks[_tn]
    for _w, _rows in done.items():
        for _r in _rows:
            if len(_r) > 5 and _r[5]:
                _nn = SPLIT.get((_r[5], near_epic(_r[0])))
                if _nn:
                    _r[5] = _nn
    print("에픽 단위 분리: %d과제 → %d에픽" % (len({k[0] for k in SPLIT}), len(SPLIT)))

    # ── 4.6 공유 에픽은 담당자별로 (Marc 2026-10-06) ──
    #   같은 에픽(또는 에픽 없이 같은 이니셔티브 직속)을 여러 명이 맡는 과제는 사람별로 따로 본다 —
    #   한 사람 과제를 열면 그 사람 티켓만, 사이즈도 사람별(디자인QA 버킷과 같은 방식). 병합 과제는 제외.
    PERWHO = set()
    _grp = {}
    for _w, _tasks in per.items():
        for _tn, _rows in _tasks.items():
            if _tn in MERGE_NAMES or _tn == BUCKET or _tn.startswith(BUCKET + " · "):
                continue
            for _r in _rows:
                _grp.setdefault((_tn, near_epic(_r[0])), set()).add(_w)
    for (_tn, _ep), _ws in _grp.items():
        if len(_ws) >= 2:
            PERWHO.add(_tn)
    print("담당자별 과제: %d건" % len(PERWHO))

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
        if st == "예정" and (F(n, "status", "name") or "") != "SUGGESTED":
            continue   # 오너 에픽도 '예정'은 SUGGESTED 상태만
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
    # 무진장 도메인 표기 변경 → 무진장/이구위크 (이구위크 구매챌린지 온사이트 과제 포함, Marc 지정 2026-09-28)
    for th in tax["themes"]:
        if th.get("k") == "무진장":
            th["k"] = "무진장/이구위크"
    if not any(th.get("k") == "무진장/이구위크" for th in tax["themes"]):
        tax["themes"].append({"k": "무진장/이구위크"})

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
         "asof": (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).strftime("%Y-%m-%d %H:%M"),
         "perwho": sorted(PERWHO)}
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
                # FT(FastTrack) — 티켓/조상의 FT 프로젝트·fast-track 라벨·마커로 판정.
                #   과거 수기 FT 태그는 버리고 티켓 기준으로 다시 매긴다(모든 데이터 일관).
                if "FT" in badges:
                    badges.remove("FT")
                if is_ft(rows):
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
                # 수기 오버라이드 (내용 기준 재배치) — taxonomy/guess 보다 우선
                _ov = domain_override(tname)
                if _ov:
                    dom = _ov
                # QA '기타 서비스' 버킷 → 유즈드 (버킷명도 유즈드로, Marc 지정)
                disp = tname
                if tname == BUCKET + " · 기타 서비스":
                    dom = "유즈드"
                    disp = BUCKET + " · 유즈드"
                # 무진장 도메인 표기 통합 → 무진장/이구위크
                if dom == "무진장":
                    dom = "무진장/이구위크"
                # 사이징 근거 내용 — 실무 티켓 본문이 비면 상위 에픽·이니셔티브에서 끌어온다
                ev_tx, ev_k, ev_ty = evidence_of(rows)
                x = {"t": disp, "th": dom, "b": badges,
                     "init": d.get("initiative"), "pf": pf,
                     "tk": [[r[0], r[1], r[2], None] for r in rows],
                     "it": [r[1] for r in rows]}
                if ev_k and _compact(ev_tx):
                    x["ev"] = {"k": ev_k, "ty": ev_ty, "tx": ev_tx[:1200]}
                x["n"] = len(x["tk"])
                x["a"] = sum(1 for r in x["tk"] if r[2] == "진행 중")
                _crs = [day(F(meta.get(r[0]) or {}, "created")) for r in rows]
                _crs = [c for c in _crs if c]
                x["q"] = quarter_of(min(_crs)) if _crs else ""
                x["c0"] = min(_crs) if _crs else ""          # 과제 시작일(첫 티켓 생성) — 주간 사이즈 그래프 x축 시작
                if d.get("bucket") or tname == BUCKET:
                    x["bkt"] = 1
                if d.get("own"):
                    x["own"] = 1
                tasks.append(x)
            # 정렬 티어: 일반(0) → 디자인QA 버킷(1) → FT(2). (화면 app.json 이 사이즈 큰 순으로 재정렬)
            tasks.sort(key=lambda z: (1 if z.get("bkt") else (2 if "FT" in (z.get("b") or []) else 0),
                                      -z["a"], -z["n"], z["t"]))
            tm["members"].append({
                "name": who, "role": m.get("role", ""), "lead": bool(m.get("lead")), "auto": bool(m.get("auto")),
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

    # ── 6.5 지표 탭 보조 데이터 (Marc 2026-10-08 지표 개편) ─────────────────
    #   tkm   : 과제에 붙은 티켓별 [최종 업데이트일, 마감일] — 정체·마감 경보용
    #   flow  : 최근 14주 주별 티켓 인입(생성)·완료 건수 (철회/Dropped 제외) — 조직·팀
    #   orphan: 디자이너 담당 '진행 중' 에픽인데 아래 디자인 티켓이 없는 건 — 데이터 누락 경보
    #   ※ CI 로그는 공개 — 건수만 출력한다.
    try:
        _tkm = {}
        for _t in D["teams"]:
            for _m in _t["members"]:
                for _x in _m["tasks"]:
                    for _r in _x["tk"]:
                        _n = meta.get(_r[0])
                        if _n:
                            _tkm[_r[0]] = [day(F(_n, "updated")) or "", day(F(_n, "duedate")) or ""]
        D["tkm"] = _tkm
        print("티켓 메타: %d건" % len(_tkm))
    except Exception as _e:
        print("티켓 메타 건너뜀:", type(_e).__name__)
    try:
        _nowk = (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).date()
        _mon0 = _nowk - datetime.timedelta(days=_nowk.weekday())
        _wks = [(_mon0 - datetime.timedelta(weeks=i)).isoformat() for i in range(13, -1, -1)]
        _wix = {w: i for i, w in enumerate(_wks)}

        def _wkof(ds):
            try:
                _d = datetime.date.fromisoformat(ds[:10])
            except Exception:
                return None
            return (_d - datetime.timedelta(days=_d.weekday())).isoformat()
        _fl = {"w": _wks, "org": {"in": [0] * 14, "out": [0] * 14}, "team": {}}
        for _t in teams:
            _fl["team"][_t["key"]] = {"in": [0] * 14, "out": [0] * 14}
        for _n in issues:
            _who = (F(_n, "assignee", "displayName") or "").split("/")[0].strip()
            if _who not in people:
                continue
            if (F(_n, "status", "name") or "") in DROP_ST:
                continue
            _tk = people[_who][0]["key"]
            _i = _wix.get(_wkof(day(F(_n, "created")) or ""))
            if _i is not None:
                _fl["org"]["in"][_i] += 1
                _fl["team"][_tk]["in"][_i] += 1
            if state_of(_n) == "완료":
                _j = _wix.get(_wkof(day(F(_n, "resolutiondate")) or ""))
                if _j is not None:
                    _fl["org"]["out"][_j] += 1
                    _fl["team"][_tk]["out"][_j] += 1
        D["flow"] = _fl
        print("주간 흐름: %d주" % len(_wks))
    except Exception as _e:
        print("주간 흐름 건너뜀:", type(_e).__name__)
    try:
        _eps = jql(f'issuetype = Epic AND assignee in {IN} AND statusCategory = "In Progress" '
                   f'AND created >= "{LEAD}" ORDER BY key ASC',
                   ["summary", "assignee", "updated", "status", "created"], cap=400)
        _alive = set()
        for _n in issues:
            if state_of(_n) in ("진행 중", "예정"):
                _alive.update(chain(_n["key"]))
        _intask = {_r[0] for _t in D["teams"] for _m in _t["members"] for _x in _m["tasks"] for _r in _x["tk"]}
        _orph = []
        for _n in _eps:
            _k = _n["key"]
            if _k in _alive or _k in _intask:
                continue
            _who = (F(_n, "assignee", "displayName") or "").split("/")[0].strip()
            if _who not in people:
                continue
            _orph.append([_k, F(_n, "summary") or "", _who, day(F(_n, "updated")) or "", day(F(_n, "created")) or ""])
        D["orphan"] = _orph
        print("티켓 없는 진행 에픽: %d건" % len(_orph))
    except Exception as _e:
        print("에픽 점검 건너뜀:", type(_e).__name__)

    # ── 7. FT 흐름 · ONE 보드 — 같은 과제 집합 (Marc 2026-10-02) ──────────────
    #   대상: FT 프로젝트 이니셔티브(7/1 이후 생성) 중
    #     · 담당자가 디자인 조직(org 가 'Design' 으로 끝남)이거나
    #     · design-driven 라벨이 있거나
    #     · one밀도감_* 라벨이 있는 건
    #   PD 의 one밀도감 건은 FT 로 진행될 때 FT 로 넘어오므로 따로 넣지 않는다.
    #   단위는 이니셔티브(하위 에픽·티켓은 행으로 세지 않음).
    #   상태 6단계: 백로그 · 디자인 중 · 디자인 완료 · 개발 중 · 론치 완료 · 중단
    #   FT 탭 버킷: todo=백로그 / wip=디자인 중·디자인 완료·개발 중 / done=론치 완료 / drop=중단
    ftn = jql("project = FT ORDER BY key ASC", FLD, cap=1500)
    tmof = {m["name"]: t["name"] for t in teams for m in t["members"]}

    def _is_des(n, f):
        return org_of(F(n, f, "displayName") or "").endswith("Design")

    LAUNCH_ST = {"론치완료", "배포완료", "완료", "개발완료", "Done"}

    def _stage(n):
        st = str(F(n, "status", "name") or "")
        cat = str(F(n, "status", "statusCategory", "key") or "")
        if st in DROP_ST or any(w in st for w in ("철회", "반려", "취소", "Drop")):
            return "중단"
        if st in LAUNCH_ST or cat == "done":
            return "론치 완료"
        if st in ("Backlog", "SUGGESTED", "할일", "To Do") or cat == "new":
            return "백로그"
        if st.replace(" ", "") == "디자인완료":
            return "디자인 완료"
        if any(w in st for w in ("개발", "QA", "배포", "론치", "Launch", "Release", "검수")):
            return "개발 중"
        return "디자인 중"

    STG2B = {"백로그": "todo", "론치 완료": "done", "중단": "drop"}

    ft, one = [], []
    for n in ftn:
        ty = str(F(n, "issuetype", "name") or "")
        if "Initiative" not in ty and "이니셔티브" not in ty:
            continue
        cr = day(F(n, "created"))
        if not cr or cr < CUT:
            continue
        labs = [str(l) for l in (F(n, "labels", default=[]) or [])]
        dd = "design-driven" in labs
        dens = any(l.startswith("one밀도감") for l in labs)
        if not (_is_des(n, "assignee") or dd or dens):
            continue
        asg = (F(n, "assignee", "displayName") or "").split("/")[0].strip()
        rep = (F(n, "reporter", "displayName") or "").split("/")[0].strip()
        who = asg if (asg and (asg in people or _is_des(n, "assignee"))) else \
              (rep if (rep in people or _is_des(n, "reporter")) else asg)
        stg = _stage(n)
        st = F(n, "status", "name") or ""
        ft.append([n["key"], cr, day(F(n, "resolutiondate")), STG2B.get(stg, "wip"), st,
                   who or "", tmof.get(who, "미배정" if not who else "그 외"), F(n, "summary") or "",
                   day(F(n, "updated"))])
        one.append([n["key"], stg, ty, who or "-", F(n, "summary") or "",
                    ("d" if dd else "") + ("o" if dens else "")])
    ft.sort(key=lambda r: (r[1], r[0]))
    one.sort(key=lambda r: r[0])
    if len(one) < 20:
        print(f"  FT·ONE 결과가 비정상적으로 적음({len(one)}건) — 스냅샷 사용")
        D["ft"] = ft
        D["one"] = load_sealed("one") or []
    else:
        D["ft"] = ft
        D["one"] = one
    D["nodN"] = len(D["one"])
    _sc = {}
    for r in one:
        _sc[r[1]] = _sc.get(r[1], 0) + 1
    print(f"FT·ONE {len(one)}건 {_sc}")

    # ── 7.2 슬랙 의장 보고(#one-제품디자인실) — 봇 토큰이 있으면 자동 갱신 ──
    D["sl"] = slack_reports(people, ft) or load_sealed("slack") or []

    # ── 7.5 예정 디자인 수요 (runway 분기 플래닝 스냅샷) ──
    #   runway 내부 데이터(디자인 디펜던시 팀 지정)는 Jira에 없어 스냅샷으로 봉인해 둔다(runway.enc).
    #   Biz-P 디자인 4팀이 메인/디펜던시로 붙은 이니셔티브만 남긴다(타 조직 디자인팀 제외).
    _rw = load_sealed("runway") or {}
    BIZ_DESIGN = {"Commerce Design", "Discovery Design", "Core UX Design", "Engagement Design"}
    _rwr = []
    for r in (_rw.get("rows") or []):
        keep = [t for t in (r.get("t") or []) if t.replace("*", "").strip() in BIZ_DESIGN]
        if not keep:
            continue
        r = dict(r); r["t"] = [t.replace("*", "").strip() for t in keep]
        _rwr.append(r)
    D["rwq"] = {"asof": _rw.get("asof", ""), "rows": _rwr}
    print(f"runway 예정 디자인 수요 {len(_rwr)}건")

    # ── 7.6 분기 라벨(4Q / 3Q순연) + 과제 규모(우선순위) (Marc 2026-09-29) ──
    #   규모 = 상위 이니셔티브의 Jira 우선순위 필드(Big-Rock·P0·P1·P2·Emergency, 라이브).
    #          Jira 에 값이 없을 때만 runway 스냅샷의 pri 로 보완. 철회/반려/취소된 이니셔티브는 건너뛴다.
    #   분기 = 4Q 에 새로 생긴 과제, 또는 runway 계획이 4Q 에만 잡힌 과제 → '4Q'
    #          3Q(이전)에 생겨 runway 3Q 계획에 걸려 있거나 계획 없이 이어오는 과제 → '3Q순연'
    #   버킷(디자인QA)·오너 에픽은 제외.
    _rwk = {row.get("k"): row for row in (_rw.get("rows") or []) if row.get("k")}
    PRI_OK = ("Big-Rock", "P0", "P1", "P2", "Emergency")
    _need = sorted({x.get("init") for t in D["teams"] for m in t["members"] for x in m.get("tasks", [])
                    if x.get("init") and x.get("init") not in meta})
    for i in range(0, len(_need), 45):
        try:
            for n in jql("key in (%s)" % ",".join(_need[i:i + 45]), FLD):
                meta[n["key"]] = n
        except Exception as e:
            print("이니셔티브 우선순위 조회 실패(무시):", e)

    def _cands(x):
        cands = []
        if x.get("init"):
            cands.append(x["init"]); cands += chain(x["init"])
        for r in (x.get("tk") or []):
            cands.append(r[0]); cands += chain(r[0])
        seen, out = set(), []
        for c in cands:
            if c not in seen:
                seen.add(c); out.append(c)
        return out

    def _dead(n):
        st = str(F(n, "status", "name") or "")
        return any(w in st for w in ("철회", "반려", "취소"))

    def _is_init(n):
        ty = str(F(n, "issuetype", "name") or "")
        return "Initiative" in ty or "이니셔티브" in ty

    def _pri_of(x):
        live = [meta[c] for c in _cands(x) if c in meta and not _dead(meta[c])]
        for pick in (lambda n: _is_init(n), lambda n: True):
            for n in live:
                v = F(n, "priority", "name")
                if pick(n) and v in PRI_OK:
                    return v, n["key"], "jira"
        for c in _cands(x):
            row = _rwk.get(c)
            if row and row.get("pri") in PRI_OK:
                return row["pri"], c, "runway"
        return None, None, None

    def _q_label(x):
        rq = set()
        for c in _cands(x):
            row = _rwk.get(c)
            if row:
                rq |= {p.strip() for p in str(row.get("q") or "").split(",") if p.strip()}
        cq = x.get("q") or ""                       # 생성 분기 "26 3Q"
        if cq and cq >= "26 4Q":
            return "4Q"
        if "2026-Q4" in rq and not any(q < "2026-Q4" for q in rq):
            return "4Q"
        return "3Q순연"

    _cnt = {}
    for t in D["teams"]:
        for m in t["members"]:
            for x in m.get("tasks", []):
                x["b"] = [b for b in x["b"] if b not in ("4Q빅락", "3Q순연", "4Q")]
                x.pop("pri", None)
                if x.get("bkt") or x.get("own"):
                    continue
                ql = _q_label(x)
                x["b"].append(ql)
                pv, pk, src = _pri_of(x)
                if pv:
                    x["pri"] = [pv, pk, src]
                _cnt[(ql, pv)] = _cnt.get((ql, pv), 0) + 1
    print("분기·규모 라벨", {"%s/%s" % k: v for k, v in sorted(_cnt.items(), key=str)})

    # ── 7.6b 과제별 분기(qs) — 도메인·성격 탭의 분기 필터용 (Marc 2026-09-28) ──
    #   qs = 생성 분기 ∪ 빌드 시점 현재 분기(지금 진행·예정 중이므로) ∪ runway 계획 분기.
    #   → 현재 분기 탭 = 지금 도는 과제 전부, 다음 분기(예: 26 4Q, 27 1Q)는 runway 계획이 있으면 자동으로 생긴다.
    def _nq(s):
        mm = re.match(r"\s*(\d{4})-Q(\d)", s or "")
        return ("%s %sQ" % (mm.group(1)[2:], mm.group(2))) if mm else None

    _now = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
    _curq = "%02d %dQ" % (_now.year % 100, (_now.month - 1) // 3 + 1)

    def _rw_rows(x):
        cands = []
        if x.get("init"):
            cands.append(x["init"]); cands += chain(x["init"])
        for r in (x.get("tk") or []):
            cands.append(r[0]); cands += chain(r[0])
        return [_rwk[c] for c in cands if c in _rwk]

    def _qsort(q):
        a, b = q.split()
        return (int(a), int(b[0]))

    for t in D["teams"]:
        for m in t["members"]:
            for x in m.get("tasks", []):
                qs = {_curq}
                rq = set()          # runway 계획 분기(성격 탭의 분기별 계획/인입 판정용)
                if x.get("q"):
                    qs.add(x["q"])
                for row in _rw_rows(x):
                    for part in str(row.get("q") or "").split(","):
                        nq = _nq(part)
                        if nq:
                            qs.add(nq); rq.add(nq)
                x["qs"] = sorted(qs, key=_qsort)
                x["rq"] = sorted(rq, key=_qsort)
    print(f"분기 필터 기준 현재 분기 {_curq}")

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
    # ── 사이즈 수기 판단 (에픽·이니셔티브 내용 기반, Marc 요청 2026-09-28) ──
    #   빈 티켓이라 '조정 권장(M)'으로 뜨던 과제를, 상위 에픽/이니셔티브 내용을 읽고
    #   디자인 작업량 기준으로 확정한 값. 여기 값은 팀장 직접조정(워커 공유)보다는 낮은 우선순위
    #   (대시보드 szOf 는 워커 오버라이드 u.s 가 있으면 그걸 우선). basis 기본값을 확정으로 바꿔 '조정 권장' 해제.
    _band_h = (basis.get("size_bands") or {"XS": 2, "S": 5, "M": 10, "L": 18, "XL": 30})
    SIZE_JUDGED = {
        "[PD][PDP] 이미지별 모델/착용정보 노출": "S",
        # 병합 대표 과제(2026-09-28) — 구성 소과제 규모·에픽 내용 기준 확정 (M 리셋 방지)
        "[무진장] 26 겨울 캠페인·홈 개편": "XL",
        "[유즈드] 판매·정산 운영 개선": "L",
        "글로벌 상품 쿠폰 도입": "L",
        "[Phase 2] mds-playbook — 파일럿 준비": "L",
        "[앱테크] 무신사 대국민 행운권": "M",
        "[오프라인] 매장 연동": "M",
        "[스냅/후기/콘텐츠] 댓글 시스템 통합": "M",
        "[이구위크] 구매챌린지 온사이트 상시 진입점": "M",
        "[탐색] AI 태그 노출·태깅 자동화 대응": "M",
        "[AI 해설] 발매판·랭킹판 디자인": "M",
        "[브랜드광고] 광고판 운영 (무신사·29CM)": "S",
        "[탐색] 카테고리 메뉴 개선 (블루닷·이미지 4열)": "S",
    }
    _judged = {k.strip(): v for k, v in SIZE_JUDGED.items()}
    for tname, ent in basis["tasks"].items():
        band = _judged.get((tname or "").strip())
        if band:
            ent["size"] = band
            ent["hours"] = _band_h.get(band, ent.get("hours", 9))
            ent["provisional"] = False
            ent["judged"] = "epic"   # 근거: 상위 에픽/이니셔티브 내용
    # 비프로젝트(회의·Slack·보고·TT 준비 등) = 주 6h, 전역 단일값. 각 인원 부하에 더해 '점유'로 계산한다.
    basis["nonproject_hours"] = 6
    basis["nonproject_by_team"] = {}
    # 휴가·공휴일(주별 가용 차감) — PXD_LEAVE_ICAL(휴가 캘린더 비공개 iCal) 있으면 매 빌드 자동 갱신,
    # 없으면 봉인된 leave.enc 로 폴백. 공휴일은 공개 iCal 에서 항상 계산.
    basis["_leave"] = compute_leave(set(people))

    # ── 인원 변동 자동 감지 (Marc 2026-09-30) → basis._rev {id: event} ──
    #   입사 추정: 로스터에 자동 편입된 신규 입사자(첫 디자인 티켓 생성일)
    #   퇴사 추정: 멤버의 Jira 계정이 비활성(active=false)
    #   전배 추정: 멤버의 Jira 표시명 소속이 지난 빌드와 달라짐(basis._orgsnap 과 비교)
    #   날짜는 처음 감지한 날(입사는 첫 티켓일). 화면에서 확정·수정·메모한다.
    try:
        rev = basis.setdefault("_rev", {})
        snap = basis.setdefault("_orgsnap", {})
        today_s = (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).strftime("%Y-%m-%d")
        seen = {}
        for n in issues + epics:
            a = F(n, "assignee") or {}
            if a.get("accountId"):
                seen[a["accountId"]] = a
        tname_of = {m.get("account"): (t["name"], m) for t in teams for m in t["members"] if m.get("account")}
        for acc, (tnm, m) in tname_of.items():
            nm = m["name"]
            if m.get("auto"):
                k = "auto-join-" + acc
                if k not in rev:
                    rev[k] = {"d": _join_first.get(acc, today_s), "t": "입사", "who": nm, "to": tnm,
                              "note": "로스터에 없던 사람이 디자인 티켓을 받아 자동 감지(첫 티켓일 기준)", "src": "auto"}
            a = seen.get(acc)
            if not a:
                continue
            if a.get("active") is False:
                k = "auto-left-" + acc
                if k not in rev:
                    rev[k] = {"d": today_s, "t": "퇴사", "who": nm, "from": tnm,
                              "note": "Jira 계정 비활성 감지(감지일 기준)", "src": "auto"}
            org = org_of(a.get("displayName") or "")
            if org:
                prev = snap.get(acc)
                if prev and prev != org:
                    k = "auto-move-%s-%s" % (acc, org)
                    if k not in rev:
                        rev[k] = {"d": today_s, "t": "전배", "who": nm, "from": prev, "to": org,
                                  "note": "Jira 소속 변경 감지(감지일 기준)", "src": "auto"}
                snap[acc] = org
        print("인원 변동 자동 기록 %d건" % len(rev))
    except Exception as _e:
        print("인원 변동 감지 건너뜀:", _e)
    # 팀별 속도 추세 히스토리는 basis 안에 함께 저장(별도 파일 불필요 → 워크플로 수정 불필요)
    if _HIST_SNAP:
        h = basis.setdefault("_hist", {"days": []})
        h["days"] = [d for d in h.get("days", []) if d.get("date") != _HIST_SNAP["date"]]
        h["days"].append(_HIST_SNAP)
        h["days"] = h["days"][-120:]
        print("history 스냅샷: %s (%d일치, basis 내장)" % (_HIST_SNAP["date"], len(h["days"])))

    # ── 주간 기록 기준일 (Marc 2026-10-02): 금요일 기준, 금요일이 휴일이면 그 전 영업일 기준.
    #    → 영업일(평일·공휴일 아님)에 돈 빌드만 이번 주 값을 덮어쓴다. 주말·공휴일 빌드는 건드리지 않는다.
    #    그 주에 아직 기록이 하나도 없을 때만(한 주 전체가 휴일 등) 예외로 남긴다.
    _now_k = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
    _hold = set((basis.get("_leave") or {}).get("hold") or [])
    _BIZ = _now_k.weekday() < 5 and _now_k.date().isoformat() not in _hold
    if not _BIZ:
        print("주간 기록: 오늘(%s)은 주말·공휴일 — 이번 주 기록은 직전 영업일 값 유지" % _now_k.date())

    # ── 8.5 주간 사이즈 스냅샷 (매주 금 20시 KST — 담당자 조정값의 '최종'을 1건 기록) ──
    #   SNAP_WEEK=1 (워크플로가 금 20시 KST 실행에만 세팅) 일 때만 남긴다.
    #   실효 사이즈 = 워커 공유 오버라이드(sz) 우선, 없으면 basis.tasks 기본값.
    #   basis._sizehist = {weeks:[{w,d}...최근26], wk:{<키>:{"2026-W39":"L"}}}
    #   <키>: 과제명 (담당자별로 나뉘는 디자인QA 는 "과제명\u0001담당자" 키도 함께).
    if True:   # 매 빌드마다 이번 주 값을 덮어쓴다 → 그 주 마지막 빌드 값이 최종 (2026-10-02: 금 20시 크론 지연으로 주가 빠지던 문제)
        try:
            now_kst = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
            iso = now_kst.isocalendar()
            wk = "%04d-W%02d" % (iso[0], iso[1])
            sh = basis.setdefault("_sizehist", {"weeks": [], "wk": {}})
            weeks = sh.setdefault("weeks", [])
            wkmap = sh.setdefault("wk", {})
            done_w = {(w.get("w") if isinstance(w, dict) else w) for w in weeks}
            if _BIZ or wk not in done_w:
                SEP = "\u0001"
                ovr = fetch_overrides()
                eff = {}
                for tname, ent in (basis.get("tasks") or {}).items():
                    base = (ent or {}).get("size") or "M"
                    u = ovr.get(tname)
                    s = (u.get("s") if isinstance(u, dict) else None) or base
                    if s:
                        eff[tname] = s
                for k, u in ovr.items():
                    if SEP in k and isinstance(u, dict) and u.get("s"):
                        eff[k] = u["s"]
                weeks[:] = [w for w in weeks if (w.get("w") if isinstance(w, dict) else w) != wk] + \
                    [{"w": wk, "d": now_kst.strftime("%Y-%m-%d")}]
                for k, s in eff.items():
                    wkmap.setdefault(k, {})[wk] = s
                weeks[:] = weeks[-26:]
                keep = {(w.get("w") if isinstance(w, dict) else w) for w in weeks}
                for k in list(wkmap.keys()):
                    wkmap[k] = {w: v for w, v in wkmap[k].items() if w in keep}
                    if not wkmap[k]:
                        del wkmap[k]
                print("사이즈 스냅샷: %s (%d과제, 오버라이드 %d건)" % (wk, len(eff), len(ovr)))
        except Exception as _e:
            print("사이즈 스냅샷 건너뜀:", _e)

    # ── 8.6 주간 리소스(활용률) 스냅샷 (매주 금 20시 KST — 멤버별 부하·가용) ──
    #   대시보드 loadPass(now) 와 동일 산식으로 멤버별 이번 주 부하(md)와 가용(md)을 기록.
    #   basis._loadhist = {weeks:[{w,d}...최근26], mem:{"<이름>":{t:"<팀키>", w:{"2026-W39":[loadmd,capmd]}}}}
    #   조직·팀 추이는 멤버 합으로 유도(대시보드), 개인 추이는 이번 주부터 누적.
    if True:   # 매 빌드마다 이번 주 값을 덮어쓴다 → 그 주 마지막 빌드 값이 최종 (2026-10-02: 금 20시 크론 지연으로 주가 빠지던 문제)
        try:
            now_kst = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
            iso = now_kst.isocalendar()
            wk = "%04d-W%02d" % (iso[0], iso[1])
            lh = basis.setdefault("_loadhist", {"weeks": [], "mem": {}})
            lweeks = lh.setdefault("weeks", [])
            lmem = lh.setdefault("mem", {})
            done_w = {(w.get("w") if isinstance(w, dict) else w) for w in lweeks}
            if _BIZ or wk not in done_w:
                SEP = "\u0001"
                ovr = fetch_overrides()
                bands = basis.get("size_bands") or {"XS": 2, "S": 5, "M": 10, "L": 18, "XL": 30}
                week_h = basis.get("week_hours", 40)
                np_def = basis.get("nonproject_hours", 8)
                NPT = basis.get("nonproject_by_team") or {}
                ftmul = basis.get("ft_multiplier", 1.5)

                def _npOf(k):
                    v = NPT.get(k)
                    return v if isinstance(v, (int, float)) else np_def

                def _availMd(k):
                    return max(0.25, (week_h - _npOf(k)) / 8.0)

                def _effHours(tname, who):
                    d0 = ((basis["tasks"].get(tname) or {}).get("size")) or "M"
                    d1 = (basis["tasks"].get(tname) or {}).get("hours", 9)
                    split = tname.startswith("디자인QA") or tname in PERWHO
                    u = ovr.get(tname + SEP + who) if (split and ovr.get(tname + SEP + who)) else ovr.get(tname)
                    if not isinstance(u, dict):
                        u = {}
                    if u.get("h") is not None:
                        return u["h"]
                    if u.get("s"):
                        return bands.get(u["s"], d1)
                    return d1

                lweeks[:] = [w for w in lweeks if (w.get("w") if isinstance(w, dict) else w) != wk] + \
                    [{"w": wk, "d": now_kst.strftime("%Y-%m-%d")}]
                for tm in D["teams"]:
                    k = tm["k"]
                    cap = round(_availMd(k), 2)
                    for m in tm["members"]:
                        who = m["name"]
                        nonft, ftv = 0.0, []
                        for x in m.get("tasks", []):
                            if x.get("own") or (x.get("a", 0) or 0) <= 0:
                                continue
                            v = _effHours(x["t"], who) / 8.0
                            if "FT" in (x.get("b") or []):
                                ftv.append(v)
                            else:
                                nonft += v
                        ftv.sort(reverse=True)
                        w = nonft + sum(v * (ftmul ** i) for i, v in enumerate(ftv))
                        lmem.setdefault(who, {"t": k, "lead": bool(m.get("lead")), "w": {}})
                        lmem[who]["t"] = k
                        lmem[who]["lead"] = bool(m.get("lead"))
                        # 점유 = 프로젝트 부하 + 비프로젝트(회의 등) / 정원 = 주 근로시간 − (공휴일+휴가)일
                        _lv = basis.get("_leave") or {}
                        _hd = (_lv.get("hol") or {}).get(wk, 0)
                        _vd = ((_lv.get("vac") or {}).get(who) or {}).get(wk, 0)
                        _capd = max(0.25, week_h / 8.0 - _hd - _vd)
                        # 휴가 주는 과제·회의도 출근일만큼만 진행 → 점유도 출근 비율로 줄인다 (앱 occOf 와 동일)
                        _pres = min(1.0, _capd / max(0.25, week_h / 8.0))
                        lmem[who]["w"][wk] = [round((w + _npOf(k) / 8.0) * _pres, 2), round(_capd, 2)]
                lweeks[:] = lweeks[-26:]
                keepw = {(w.get("w") if isinstance(w, dict) else w) for w in lweeks}
                for who in list(lmem.keys()):
                    lmem[who]["w"] = {w: v for w, v in lmem[who]["w"].items() if w in keepw}
                    if not lmem[who]["w"]:
                        del lmem[who]
                print("리소스 스냅샷: %s (%d명)" % (wk, len(lmem)))
        except Exception as _e:
            print("리소스 스냅샷 건너뜀:", _e)

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
        print("새 과제: %d건" % len(fresh))   # 이름은 공개 로그에 남기지 않는다


if __name__ == "__main__":
    main()
