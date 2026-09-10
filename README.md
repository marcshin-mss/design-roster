# 디자인실 워크로드 대시보드

Biz-P Product Design 26명의 지라 과제를 읽어 **주간 리소스**를 보여줍니다.
GitHub Actions가 평일 07~22시 **30분마다** 지라를 다시 읽고 GitHub Pages로 배포합니다.
대시보드의 **「지금 다시 읽기」** 를 누르면 기다리지 않고 바로 다시 읽습니다.

**주소** https://marcshin-mss.github.io/design-roster/ (열람 비밀번호 = `GATE_PASS`)

## 구성

```
지라 ──(30분마다 · 또는 「지금 다시 읽기」)──▶ Actions ──▶ data.json (암호화) ──▶ Pages

브라우저 ──(사이즈 조정)──▶ Cloudflare Worker + KV (암호화) ◀──(10초마다 확인)──▶ 모든 브라우저

「지금 다시 읽기」 : 브라우저 ──▶ Worker ──(저장된 토큰)──▶ GitHub Actions 재빌드
```

- **티켓 데이터**는 서버에서 자동 갱신됩니다. 보는 사람은 아무것도 안 해도 됩니다.
  브라우저 새로고침만으로는 안 바뀝니다 — 서버가 지라를 다시 읽어야 바뀝니다.
- **사이즈 조정**은 브라우저에서 하고, 암호화해서 Cloudflare에 올라갑니다.
  다른 사람 화면은 **10초 안에** 따라옵니다.

## 파일

| 파일 | 무엇 | 누가 고치나 |
|---|---|---|
| `index.html` | 게이트 + 부트스트랩만. 화면 본체는 여기 없습니다 | 거의 안 고침 |
| `app.enc` | 대시보드 화면·로직 전체 **(암호화)** | 화면을 바꿀 때 |
| `data.json` | 지라 조회 결과 + 기준값 **(암호화)** | **자동** — 손대지 마세요 |
| `basis.enc` | 사이즈·주간 투입·비프로젝트 시간 **(암호화)** | 사람 |
| `taxonomy.enc` | 과제 정의 — 도메인·배지·앵커·인원·짧은 이름 **(암호화)** | 사람 |
| `slack.enc` | 의장님 보고·승인 **(암호화)** | 사람 |
| `one.enc` | ONE design-driven 보드 **(암호화)** | 사람 |
| `sync.json` | 공유 기준 저장소 주소 (비밀 아님) | 주소가 바뀔 때 |
| `worker.js` | Cloudflare Worker 원본 | 저장소 규칙을 바꿀 때 |
| `build.py` · `seal.py` | 빌드 / 봉인 | — |

**리포가 Public이어도 내용은 안 보입니다.** 과제명·인원·의장님 보고는 물론
**화면 코드(`app.enc`)까지** `GATE_PASS`로 잠겨 있습니다. 평문으로 남는 건
`build.py`·워크플로·게이트 껍데기뿐이고, 평문 `*.json`은 `.gitignore`로 막혀 있습니다.

`basis.enc` 또는 `taxonomy.enc`를 커밋하면 **즉시 다시 빌드**됩니다.

## 사이즈 조정이 모두에게 반영되는 흐름

대시보드에서 과제를 눌러 **1인 주간 투입**을 바꾸면 끝입니다.
값은 `GATE_PASS`로 암호화돼 Cloudflare Workers KV에 저장되고,
열려 있는 모든 화면이 10초 안에 받아 다시 계산합니다.

우상단 표시로 상태를 볼 수 있습니다.

| 표시 | 뜻 |
|---|---|
| **공유 기준** | 정상. 모두가 같은 값을 봅니다 |
| **저장 실패** | 저장소에 못 올렸습니다. 변경이 내 브라우저에만 남습니다 |
| **이 브라우저만** | `sync.json` 이 없거나 저장소에 못 붙었습니다 |

저장소에는 **암호화된 덩어리만** 올라갑니다 — Cloudflare도 내용을 읽지 못합니다.
쓰기는 `GATE_PASS` 를 아는 사람만 되고(`x-gate` = 비밀번호의 SHA-256),
직전 값 하나는 `basis:prev` 로 백업됩니다.

## 처음 한 번 설정

### 1. 리포 시크릿 (Settings → Secrets and variables → Actions)

| 이름 | 값 |
|---|---|
| `JIRA_BASE` | `https://musinsa-oneteam.atlassian.net` |
| `JIRA_EMAIL` | API 토큰을 발급한 계정 메일 |
| `JIRA_TOKEN` | Atlassian API 토큰 |
| `GATE_PASS` | 대시보드 열람 비밀번호 (팀에 공유할 값) |

Atlassian 토큰은 https://id.atlassian.com/manage-profile/security/api-tokens 에서 발급합니다.
**조회 전용으로만 쓰입니다** — 이 리포의 어떤 코드도 지라에 쓰지 않습니다.

### 2. Pages 켜기

Settings → Pages → Source를 **GitHub Actions**로. (리포는 Public이어야 합니다)

### 3. 공유 기준 저장소 (Cloudflare · 무료)

1. Workers KV → 네임스페이스 `roster` 생성
2. Workers & Pages → Create → Hello World → 이름 `design-roster-sync` → Deploy
3. Bindings → KV namespace → 변수명 `ROSTER`, 네임스페이스 `roster`
4. Edit code → `worker.js` 내용 붙여넣기 → Deploy
5. Settings → Variables and Secrets → **Secret** 두 개

   | 이름 | 값 |
   |---|---|
   | `GATE_HASH` | `GATE_PASS` 의 SHA-256 — `bash gatehash.sh` 로 만듭니다 |
   | `GH_TOKEN` | GitHub fine-grained PAT · 이 리포에 **Actions: Read and write** |

   `GH_TOKEN` 이 없으면 「지금 다시 읽기」만 비활성이고 나머지는 정상 동작합니다.
6. Worker 주소를 `sync.json` 에 적습니다

무료 한도는 읽기 10만/일 · 쓰기 1,000/일 · 저장 1GB 입니다. 미사용으로 멈추지 않습니다.

### 4. 봉인 후 배포

평문 JSON을 `GATE_PASS`로 잠그고 올립니다.

```
bash push.sh              # 봉인 → 커밋 → 푸시를 한 번에
```

`taxonomy·basis·slack·one·app` 이 `.enc` 로 바뀌고 평문은 삭제됩니다.
그다음 Actions 탭 → **대시보드 갱신** → Run workflow.

## 「지금 다시 읽기」

대시보드 상단 **「갱신」 → 「지금 다시 읽기」**. 누르면 Worker가 저장된 `GH_TOKEN` 으로
`refresh.yml` 워크플로를 깨우고, 브라우저는 8초마다 `data.json` 이 바뀌었는지 보다가
새 데이터가 올라오면 화면을 자동으로 바꿉니다. 보통 1~2분.

- 토큰은 Cloudflare 안에만 있고 페이지에는 나오지 않습니다
- 비밀번호 해시(`x-gate`)로 잠겨 있어 아무나 못 누릅니다
- 90초 쿨다운 — 여러 명이 눌러도 한 번만 돕니다

**「화면만 새로고침」** 은 지라를 읽지 않고 서버에 있는 데이터만 다시 가져옵니다.

## 화면을 고치려면

`app.json` 은 `{ "html": …, "src": … }` 두 덩어리입니다.
`html` 은 `<div id="shell">` 자리에 들어갈 마크업, `src` 는 그 뒤 실행되는 스크립트입니다.
고친 뒤 `bash push.sh` 로 다시 봉인해 올리면 됩니다.

## 판정 기준

구버전 디자인실 대시보드와 맞췄습니다.

- 이슈 타입 **Design · Task · 작업**만. 부작업 제외
- **생성일 2026-07-01 이후**가 모든 버킷의 공통 조건
- 완료는 **생성일과 완료일이 모두** 7/1 이후
- 담당자는 **계정(accountId)**으로 거릅니다 — 지라에 한글 동명이인이 많습니다
- 팀장 4명은 실무 티켓 대신 **본인이 담당자인 에픽**만, 리소스에는 0
- **CBP** 배지 = 상위 에픽의 발의 조직이 Core-P거나 지라 라벨에 `CBP`
- 정원 = 주 40h(법정 근로, 휴게 제외) − 비프로젝트 8h = **32h(4md)/인**
- 부하 = 진행 중 티켓이 있는 과제의 사이즈 시간 합. FT는 2건째부터 1.5배
