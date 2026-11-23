# 프로젝트 갈라테아 (Galatea)

갈라테아는 **유희왕 덱과 시작 패를 입력하면 가능한 전개를 탐색하고, 선택한 수순과 남은 자원을 한국어 리플레이로 비교할 수 있는** 에이전트다. 같은 패에서 갈림길이 여러 개 나왔을 때 어떤 카드를 비용으로 썼고 그 결과 필드·패·묘지에 무엇이 남는지를 나란히 놓고 보는 것이 중심이다.

## 같은 패, 갈라지는 두 전개 (실제 기록)

시작 패는 `잭나이츠 오르페골 기르수 · 하루 우라라 · 증식의 G · 무한포영 · 무덤의 지명자`다. 엔진이 실행한 두 전개는 **앞의 일곱 걸음이 같고 여덟째 걸음에서 갈린다.**

| | ⓐ 갈라테아 + 클리막스 세트 | ⓑ 갈라테아i 소생 → 롱기르수 |
| --- | --- | --- |
| 갈라지는 걸음 | 갈라테아 ②로 제외된 **오르페골 스켈레촌**을 덱으로 되돌리고 **오르페골 클리막스**를 세트 | 묘지의 **잭나이츠 오르페골 기르수**를 제외해 **오르페골 갈라테아i**를 소생 |
| 그 다음 | — (여기서 멈춘다) | 갈라테아 + 갈라테아i로 **오르페골 롱기르수** 링크 소환 |
| 최종 엑스트라 몬스터 존 | 오르페골 갈라테아 | **오르페골 롱기르수** |
| 최종 몬스터 존 | World Legacy Token | World Legacy Token |
| 세트 | **오르페골 클리막스**(뒷면) | 없음 |
| **기르수가 남는 곳** | **묘지** | **제외** |
| 묘지 | 하루 우라라 · 갈라테아i · **기르수** | 하루 우라라 · 갈라테아 · 갈라테아i |
| 제외 | 없음 (스켈레촌이 덱으로 돌아갔다) | 스켈레촌 · **기르수** |
| 최종 패 (4장) | 증식의 G · 무한포영 · 무덤의 지명자 · 성유물－『성관』 | 같다 |

두 전개 모두 여섯째 걸음에서 갈라테아i ②로 **성유물－『성관』**을 패에 넣었고(그 자리의 다른 후보는 오르페골 바벨 · 성유물－『성장』), 상대 자리에는 기르수가 만든 토큰 하나가 남는다.

🔴 **결과 번호는 실행마다 달라진다.** 위 전개는 카드명과 수순으로 알아본다. 두 기록 모두 **새 초기 상태에서 처음부터 다시 실행해 최종 상태 해시가 일치**한 것이다.

바로 열어 보는 리플레이 (내려받아 브라우저로 연다 · 카드 그림은 넣지 않았다):

* [ⓑ 소생 → 롱기르수 리플레이](https://github.com/Raro615/yugioh-deck-agent/blob/claude/pensive-goodall-te1egy/docs/viewer/orcust-galatea-i-revive-longirsu.html) — 장면 13개
* [ⓐ 갈라테아 + 클리막스 세트 리플레이](https://github.com/Raro615/yugioh-deck-agent/blob/claude/pensive-goodall-te1egy/docs/viewer/orcust-galatea-climax-set.html) — 장면 11개
* 수치와 판정 근거는 검증 기록의 [두 전개 비교 절](https://github.com/Raro615/yugioh-deck-agent/blob/2aaecb03012bbb62ca150fc91e485da870f8d756/docs/orcust-galatea-effect-extension.md#L2719-L2740)에 있다.

## 직접 확인하기

🔴 **기능은 개발 브랜치 [`claude/pensive-goodall-te1egy`](https://github.com/Raro615/yugioh-deck-agent/tree/claude/pensive-goodall-te1egy) 에 있다.** `main` 에는 Lua 카드 스크립트와 이 문서만 있으므로, 실행은 반드시 개발 브랜치를 받아서 한다.

```
git clone https://github.com/Raro615/yugioh-deck-agent.git
cd yugioh-deck-agent
git checkout claude/pensive-goodall-te1egy
```

설치와 공식 데이터 내려받기는 [개발 브랜치 README](https://github.com/Raro615/yugioh-deck-agent/blob/claude/pensive-goodall-te1egy/README.md)에 있다. Discord 봇에서는 이 순서로 쓴다.

1. `/combo` 의 `hand` 에 시작 패를 한국어 카드명으로 넣는다 — `잭나이츠 오르페골 기르수, 하루 우라라, 증식의 G, 무한포영, 무덤의 지명자`
2. `recipe` 에 [예제 덱 레시피](https://github.com/Raro615/yugioh-deck-agent/blob/claude/pensive-goodall-te1egy/docs/orcust-azamina-note.ydk) 본문을 붙여 넣고 `search` 를 `auto` 로 둔다. `line` 과 목표 카드는 비운다.
3. 추천된 최종 필드·패를 비교한다. 요약에는 추천 근거 한 줄이 함께 온다.
4. 다른 후보를 보려면 `/combo-pick` 에 방금 받은 **요청 ID**와 **결과 번호**를 넣는다. 첨부된 `combo-replay.html` 을 열면 그 후보의 장면을 하나씩 볼 수 있다.

## 현재 가능한 것

* **오르페골 자율 탐색** — 덱과 시작 패만 주면 정해진 시간·후보 수 안에서 전개를 찾는다. 고정 경로를 적어 주지 않아도 된다.
* **후보 재실행** — 고른 후보를 같은 시작 상태에서 처음부터 다시 실행하고, 끝난 판의 상태 해시가 탐색이 적어 둔 것과 같은지 확인한다. 어긋나면 기록을 내보내지 않는다.
* **장면별 선택지·비용·소재 표시** — 리플레이에서 장면을 누르면 ① 고른 행동과 그때 치른 비용·소재·대상 ② 같은 시점의 다른 선택지 ③ 실제로 움직인 카드와 그 장면 뒤의 패·필드가 펼쳐진다. ②는 **행동을 고르는 시점**과 **효과 해결 중 카드를 고르는 시점**을 따로 적고, 고를 수 없던 후보는 그 사유와 함께 보여 준다.
* 위의 모든 설명은 **엔진이 그 자리에서 기록한 값**이다. 탐색이 어떤 행동을 더 높게 평가했다는 기록은 없으므로, 화면도 「가능한 선택지 중 하나로 탐색했다」 고만 적는다.
* **최종 추천 근거** — 평가가 쓴 네 축(필드 구성 · 쥔 카드 · 일반 소환권 · 상대 자리)과 **그 축이 증명하지 않는 것**을 마지막 장면에 적는다. 🔴 이 칸은 `/combo` 가 처음 보내는 리플레이에만 붙는다 — `/combo-pick` 으로 다시 꺼낸 리플레이에는 장면별 선택 근거는 그대로 있고 이 칸이 비어 있다 (후속 작업).

### 아직 안 되는 것

* **성유물－『성관』** — 갈라테아i ②로 **패에 넣는 것**과 링크 마커가 가리키는 **빈 몬스터 존 판정**까지는 확인됐다. 패에서 **특수 소환하는 절차는 구현되지 않았다** — 그래서 후보에도 보류에도 오르지 않는다.
* **Duel Simulator 공유** — 지원되는 경로는 사이트 리플레이로 공유할 수 있다. 다만 기르수가 **양쪽 필드에 토큰을 만드는** 기준 전개는 상대 자리 토큰에 줄 시작 자리가 없어 그 조작이 계획에서 빠지고, 재현이 완료되지 않는다. 이 전개는 Discord 첨부로 본다.
* 지원하지 않는 효과나 판정은 **결과에 그대로 표시한다** — 조용히 넘기지 않는다.

## 앞으로의 방향

1. **오르페골 후속 전개를 넓힌다** — 성관의 패 특수 소환 절차, 바벨의 필드 발동처럼 실제 전개를 바꾸는 효과부터.
2. **사이트 리플레이 재현을 넓힌다** — 양쪽 필드의 토큰과 표시 형식까지 엔진 기록과 맞춘다.
3. **덱·패 입력을 간소화한다** — 검증한 덱을 이름으로 다시 고르고, 일부 패만 지정하는 방식까지.

장기 목표로는 EDOPro의 카드·스크립트·금제 갱신을 반영하고 EDOPro에서 상대와 듀얼하는 에이전트를 지향한다. 자체 언어 모델과 검색을 연결해 최신 덱 사례와 카드 재정에 근거한 한국어 설명도 제공하고자 한다.

## 더 읽을 것

* [개발 브랜치 README](https://github.com/Raro615/yugioh-deck-agent/blob/claude/pensive-goodall-te1egy/README.md) — 설치, 한국어 카드 검색 예시, 구조, 데이터 출처
* [오르페골 전개 구현·검증 기록](https://github.com/Raro615/yugioh-deck-agent/blob/claude/pensive-goodall-te1egy/docs/orcust-galatea-effect-extension.md) — 무엇을 어떤 근거로 구현했고 무엇을 못 했는지
* [규칙·엔진 설계](https://github.com/Raro615/yugioh-deck-agent/blob/claude/pensive-goodall-te1egy/docs/duel-engine-design.md)

카드 데이터는 [BabelCDB](https://github.com/ProjectIgnis/BabelCDB) 와 [CardScripts](https://github.com/ProjectIgnis/CardScripts) 에서 받고, 규칙 근거는 [공식 룰북](https://www.yugioh-card.com/en/rulebook)과 [공식 카드 데이터베이스](https://www.db.yugioh-card.com/yugiohdb/)를 읽는다.
