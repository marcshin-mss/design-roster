# 디자인실 워크로드 대시보드

Biz-P Product Design 26명의 지라 과제를 읽어 **주간 리소스**를 보여줍니다.
GitHub Actions가 평일 07~19시 **30분마다** 지라를 다시 읽고 GitHub Pages로 배포합니다.

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

Settings → Pages → Source를 **GitHub Actions**로.

### 3. 최초 봉인 (한 번만)

평문 JSON을 `GATE_PASS`로 잠급니다. **로컬에서 한 번만** 돌리면 됩니다.

```
pip3 install cryptography
python3 seal.py          # GATE_PASS 를 입력 (화면에 안 보임)
git add -A && git commit -m "봉인" && git push
```

`taxonomy·basis·slack·one` 이 `.enc` 로 바뀌고 평문은 삭제됩니다.

### 4. 첫 빌드

Actions 탭 → **대시보드 갱신** → Run workflow.

## 파일

| 파일 | 무엇 | 누가 고치나 |
|---|---|---|
| `index.html` | 대시보드 전체 (비밀번호 게이트 포함) | 화면을 바꿀 때만 |
| `data.json` | 지라 조회 결과 + 기준값 **(암호화)** | **자동** — 손대지 마세요 |
| `basis.enc` | 사이즈·주간 투입·비프로젝트 시간 **(암호화)** | 사람 |
| `taxonomy.enc` | 과제 정의 — 도메인·배지·앵커·인원 **(암호화)** | 사람 |
| `slack.enc` | 의장님 보고·승인 **(암호화)** | 사람 |
| `one.enc` | ONE design-driven 보드 **(암호화)** | 사람 |
| `build.py` · `seal.py` | 빌드 / 최초 봉인 | — |

**리포가 Public이어도 내용은 안 보입니다.** 과제명·인원·의장님 보고까지 전부 `GATE_PASS`로 잠겨 있고,
평문으로 남는 건 코드(`build.py`·`index.html`·워크플로)뿐입니다. 평문 `*.json`은 `.gitignore`로 막혀 있습니다.

`basis.enc` 또는 `taxonomy.enc`를 커밋하면 **즉시 다시 빌드**됩니다.

## 가중치 조정이 모두에게 반영되는 흐름

1. 대시보드에서 과제를 눌러 **1인 주간 투입**을 조정 (이 시점엔 내 브라우저에만)
2. 상단 **「기준 공유」 → basis.enc 내용 복사** — 브라우저가 같은 비밀번호로 다시 잠가 줍니다
3. 이 리포의 `basis.enc`를 그 내용으로 교체하고 커밋 (github.com에서 바로 편집 가능)
4. Actions가 자동으로 다시 빌드 → **전원에게 적용**

짧은 코드만 주고받고 싶으면 「코드 복사」로 슬랙에 붙여넣고, 받는 쪽이 「받은 기준 적용」에 붙여넣으면 됩니다.

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
