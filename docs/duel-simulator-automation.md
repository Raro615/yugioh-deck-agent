# 외부 Duel Simulator 실연동 (Phase 6-AX)

이 저장소의 엔진 실행 기록 한 건을 **실제 사이트에서 조작하고, 사이트 자체
녹화 기능으로 리플레이를 만들어 공유**한 작업의 기록.

| | |
| --- | --- |
| 대상 | <https://duel-simulator.miyauchidp.dev/> |
| 실제로 만든 공유 리플레이 | **<https://duel-simulator.miyauchidp.dev/replay/hR6gbCRd>** |
| 제목 | `オルフェゴール ロンギルス展開 (galatea engine / 自作プレースホルダー画像)` |
| 경로 | `orcust-skeleton-longirsu` · 패 `69811710,703897,2930675,12989604,61654098` |
| 코드 | `deck/site_plan.py` · `deck/site_session.py` · `scripts/duel_simulator_driver.js` · `scripts/duel_simulator_share.py` · `app/site_share.py` |

🔴 **자체 뷰어와 별개다.** `docs/replay-viewer.md` 의 갈라테아 리플레이
화면은 그대로 남아 있고, 이 문서는 **외부 사이트에 올린 것**만 적는다.
자체 HTML 을 외부 연동 완료로 대체하지 않는다.

---

## 1. 사이트가 지금 제공하는 입력 경로 (2026-11 실측)

| 입력 | 지금 있는가 | 이 세션에서 쓸 수 있는가 |
| --- | --- | --- |
| 遊戯王ニューロン 덱 이미지 업로드 | ✅ | ⚠ 공식 내보내기 파일이 없다 |
| PC판 마스터듀얼 화면 캡처 | ✅ | ❌ 게임 클라이언트가 없다 |
| **샘플 덱** | ❌ **없어졌다** | — |
| Deck Image Replacer (신규) | ✅ | ❌ 먼저 덱 이미지를 요구한다 |
| 카드 이름으로 덱에 추가 | ❌ 없다 | — |
| 공개 API · 가져오기 형식 | 공개 문서에서 확인하지 못했다 | — |

🔴 **6-AS 시점과 달라진 점**: 홈 화면의 「Use Sample Deck」 이 사라졌다
(매뉴얼에는 아직 설명이 남아 있다). 그래서 덱 이미지 없이는 판에 카드를
올릴 방법이 **전혀 없다**.

한 가지 중요한 발견: 카드 식별은 틀렸을 때 **카드명 검색으로 고칠 수
있다**. 다만 가이드라인 4절이 "카드의 식별 결과에 따라 盤面의 카드 이미지를
다른 이미지로 바꾸지 않는다" 고 적는다 — **그림은 올린 이미지에서 잘라낸
것이 그대로 남는다.**

### 카드 그림을 모아 덱 이미지를 만들지 않은 이유

6-AW 에서 받아 둔 카드 그림(`data/cache/card_images/`, 출처 YGOPRODeck)으로
덱 이미지를 합성하는 길을 검토했고, **하지 않기로 했다.**

> 5. 禁止事項（抜粋） … **利用する権限のない画像を読み込み、共有URLや
> リプレイとして公開する行為**
> — 이용 가이드라인

> 4. … 利用者が読み込むデッキ画像は、**公式アプリから出力されたデッキ画像、
> またはPC版マスターデュエルの画面の取り込みを想定しています。**
> — 이용 가이드라인

> 第7条 … 利用者は、UGCの作成・アップロード・共有について**第三者の権利を
> 侵害しないこと、必要な許諾を得ていること**を表明し …
> — 이용규약

카드 그림의 권리는 코나미에 있고, 이 저장소는 그것을 외부 서비스에 올려
**공개**할 권한이 없다. 공유는 덱 이미지를 운영 서버에 저장·공개하므로
(가이드라인 7절), 합성 덱 이미지를 올리는 것은 위 5절이 이름을 붙여 금지한
바로 그 행위다.

---

## 2. 대신 쓴 것 — **자체 제작 자리표시 덱 시트**

`deck/site_plan.render_deck_sheet_html` 이 만드는, **카드 그림이 하나도 없는**
덱 시트다. 각 칸에는 카드 **이름과 패스코드만** 글자로 찍힌다.

* 🔴 **공식 앱의 내보내기 이미지가 아니고**, 그렇게 부르지 않는다. 시트의
  아래 줄에 `自作プレースホルダー画像（公式アプリの出力ではありません／
  カード画像は含みません）` 이라고 적혀 있다.
* 🔴 다른 카드의 그림을 그 카드인 것처럼 쓰지 않았다 — **그림 자체가 없다.**
* 권리 문제가 없다: 이 저장소가 만든 글자 이미지다.

격자 치수는 사이트의 해석기가 카드를 제대로 잘라내도록 맞췄다 (폭 1169 ·
한 줄 10장 · 카드 116×169 · 타이틀 82px · 헤더 띠 44px). 이 숫자는 공개
리플레이 페이지에 표시된 덱 이미지의 **격자 간격을 재서** 얻었다 (이미지
자체는 쓰지 않았다).

### 입력 결과 확인 — "들어갔다" 로 끝내지 않았다

| 확인 항목 | 결과 |
| --- | --- |
| 자동 검출 | ❌ 틀린다 (`Main Deck: 7 cards (1 rows)`) → **수동 매수 보정** 사용 |
| 메인 장수 | ✅ `Deck (40)` |
| 엑스트라 장수 | ✅ `Extra Deck (6)` |
| 메인/엑스트라 구분 | ✅ 엑스트라 6장이 엑스트라 칸으로 들어갔다 |
| 잘림 | ✅ 잘라낸 카드가 114×167 (비율 0.683 = 카드 비율) |
| 카드 식별 | ❌ **전부 미식별** (`Unrecognized`) — 그림이 없으니 당연하다. 카드 이름은 시트에 찍혀 있어 판에서 읽을 수 있다 |

---

## 3. 조작 계획 — 엔진 기록에서 나온다

`deck/site_plan.build_site_plan(record)` 가 실행 기록을 사이트 조작 목록으로
바꾼다. 🔴 **정식 입력은 실행 기록이고**, 사람이 읽으라고 쓴 설명문
(`reason` · `resolution_choices`) 을 해석해서 조작을 정하지 않는다.

| 기록 | 조작 | 근거(`basis`) |
| --- | --- | --- |
| `monster_summoned` | 끌어 놓기 (칸 번호대로) | `engine:event#N.monster_summoned` |
| `zone_moved` · `card_drawn` | 끌어 놓기 (존으로) | `engine:event#N.zone_moved` |
| 걸음 `activate_effect` | 우클릭 → Activate Effect | `engine:step#N.kind` + `event#M.source` |
| 걸음의 `targets` | 우클릭 → Target | `engine:step#N.targets` |
| `special_summon_limited` · `zone_shuffled` | **조작 없음** | `plan["unsupported"]` 에 적는다 |

* **개체를 자리로 묶는다.** 시작 패 5장이 `main-0`…`main-4`, 나머지 덱이
  `main-5` 이후, 엑스트라가 `extra-0` 이후다. 그래서 같은 이름의 카드가
  여러 장이어도 섞이지 않고, 사이트의 「왼쪽 위 5장을 패로」 가 기록의 시작
  패와 정확히 같다.
* **공유 엑스트라 몬스터 존**: 엔진의 좌석 0 `EMZONE` → 사이트의
  `Extra Monster Zone1`, 좌석 1 → `Extra Monster Zone2`. 같은 물리적 자리를
  양쪽에 중복 생성하지 않는다.
* 🔴 **엔진 행동 6 · 엔진 사건 8 · 사이트 조작 16** 은 서로 다른 수다.
  계획의 `counts` 가 셋을 따로 센다.

이번 경로에서 **사이트에 대응 조작이 없는 사건** (조용히 빠뜨리지 않고
실행 전에 찍는다):

```
사건 #1 의 zone_shuffled: 덱 섞기 — 사이트의 덱은 순서를 따로 다루지 않습니다
사건 #3 의 special_summon_limited: 특수 소환 제한 등록 — 사이트에 그 표현이 없습니다
사건 #3 의 zone_shuffled: …
사건 #6 의 special_summon_limited: …
```

---

## 4. 사이트 조작 — 실측

`scripts/duel_simulator_driver.js` 가 **사람이 쓰는 UI 그대로** 조작한다
(끌어 놓기 · 우클릭 메뉴 · 버튼). 내부 엔드포인트를 부르지 않고 번들을
뜯어보지 않는다. 조작마다 화면의 History 줄을 읽어 **도착지**를 확인하고,
어긋나면 **그 자리에서 멈춘다** (확인 없이 다시 시도해 두 번 움직이는 일을
만들지 않는다).

좌표 의존 범위: 존은 `data-droppable` 요소의 **화면 좌표**로 찾는다
(사이트가 존 이름을 DOM 에 적지 않는다). 카드는 좌표가 아니라
`data-card-id`(`main-11-…` 처럼 이동해도 바뀌지 않는 식별자) 로 찾는다.
그래서 레이아웃이 바뀌면 존 찾기가 먼저 깨지고, 그때는 History 확인이
실패해 멈춘다.

### 시작 상태 (기록 시작 직전)

```
Hand 5 · Deck 35 · Extra Deck 6 · Grave 0 · Banish 0 · Free 0
```

사이트 쪽에 표현할 수 없는 것: **상대 정보는 아무것도 넣지 않았다** (상대
덱·패·필드). 엔진 기록의 좌석 1 은 덱 40장뿐이고 이번 전개와 무관하므로,
없는 상대 정보를 검증된 것처럼 다루지 않는다. 특수 소환 제한도 사이트에
표현이 없다 (§3 의 `unsupported`).

### 16개 조작 — 전부 화면으로 확인

| # | 조작 | 카드 | 화면(History) |
| --- | --- | --- | --- |
| 1 | move | main-0 기르수 | `Hand → Monster Zone1` |
| 2 | activate | main-0 | `Activate Effect · Monster Zone1` |
| 3 | move | main-24 디베르 | `Deck → Grave` |
| 4 | activate | main-24 | `Activate Effect · Grave` |
| 5 | move | main-24 | `Grave → Banish1` |
| 6 | move | main-11 스켈레촌 | `Deck → Monster Zone2` |
| 7 | move | main-0 | `Monster Zone1 → Grave` |
| 8 | move | main-11 | `Monster Zone2 → Grave` |
| 9 | move | extra-1 갈라테아 | `Extra Deck → Extra Monster Zone1` |
| 10 | activate | main-11 | `Activate Effect · Grave` |
| 11 | target | main-0 | `Target · Grave` |
| 12 | move | main-11 | `Grave → Banish2` |
| 13 | move | main-0 | `Grave → Monster Zone1` |
| 14 | move | extra-1 | `Extra Monster Zone1 → Grave` |
| 15 | move | main-0 | `Monster Zone1 → Grave` |
| 16 | move | extra-4 롱기르수 | `Extra Deck → Extra Monster Zone1` |

### 최종 상태 — 엔진 기록과 대조

| 존 | 엔진 기록 | 사이트 화면 |
| --- | --- | --- |
| Extra Monster Zone1 | `#84` 오르페골 롱기르수 | ✅ `extra-4` |
| Grave | `#81` 갈라테아 · `#75` 기르수 | ✅ `extra-1` · `main-0` (2장) |
| Banish | `#19` 디베르 · `#6` 스켈레촌 | ✅ `main-24` · `main-11` (2장) |
| Hand | 4장 | ✅ 4 |
| Deck | 33장 | ✅ 33 |
| Extra Deck | 4장 | ✅ 4 |

🔴 **사이트에서 움직였다는 것과 공식 규칙상 적법하다는 것은 다른 사실이다.**
이 사이트는 수동 재현 도구이고 규칙 판정기가 아니다. 적법성을 판정한 것은
이 저장소의 엔진이고, 사이트는 그 결과를 **보여 줄 뿐**이다.

---

## 5. 공유 리플레이 — 실제로 만들었다

<https://duel-simulator.miyauchidp.dev/replay/hR6gbCRd>

새 페이지에서 열어 재생을 확인한 결과 (실측):

| 확인 | 결과 |
| --- | --- |
| 페이지 제목 | `オルフェゴール ロンギルス展開 (galatea engine / 自作プレースホルダー画像)` |
| 수순 수 | **16** (계획의 16개 조작과 같다) |
| 시작 장면 `0 / 16` | Hand 5 · Deck 35 · Extra 6 · Grave 0 · Banish 0 |
| 중간 장면 `8 / 16` | Grave 2 · Banish 1 · Hand 4 · Deck 33 |
| 마지막 장면 `16 / 16` | Grave 2 · Banish 2 · Hand 4 · Extra 4 · Deck 33 |
| 최종 카드 자리 | 롱기르수 = EM존 / 갈라테아·기르수 = 묘지 / 디베르·스켈레촌 = 제외 |

수순 목록도 계획과 글자까지 같았다 (`#1 Hand → Monster Zone1` …
`#16 Extra Deck → Extra Monster Zone1`).

🔴 **공유는 되돌릴 수 없다.** 공유 URL 은 접근 제어가 없는 미수록 형식이고
(규약 8조), 이용자가 스스로 지우는 기능이 없다 (가이드라인 7절). 그래서
`--share` 는 기본으로 꺼져 있고, 켜면 경고를 찍고, **조작기가 최종 상태
확인에 성공했을 때만** 공유한다.

---

## 6. 다시 실행하는 법

```bash
# 계획과 덱 시트만 (브라우저를 열지 않는다)
python3 -m scripts.duel_simulator_share --line orcust-skeleton-longirsu --plan-only

# 사이트에서 실제로 조작하고 확인까지 (공유하지 않는다)
python3 -m scripts.duel_simulator_share --line orcust-skeleton-longirsu

# 🔴 공유 URL 까지 — 되돌릴 수 없는 공개다
python3 -m scripts.duel_simulator_share --line orcust-skeleton-longirsu \
    --share --title "…"

# 이미 있는 기록으로
python3 -m scripts.duel_simulator_share --json combo-replay.json
```

| | |
| --- | --- |
| 필요한 환경 | 이 컨테이너의 Chromium + Node Playwright (추가 설치 없음) |
| 바깥 통신 | `duel-simulator.miyauchidp.dev` 하나 |
| 입력 | 고정 경로 이름 또는 `engine-replay/*` JSON |
| 출력 | `<작업디렉터리>/plan.json` · `deck-sheet.png` · `shot-*.png` · `video/` · `result.json` (+ `--share` 면 `share_url`) |
| 걸리는 시간 | 실측 1~2분 |
| 실패했을 때 | `result.json` 의 `stopped_at` · `stopped_reason` 에 **어느 조작에서 무엇이 달랐는지** 남는다. 기록을 끝내지 않고 공유도 하지 않는다 |

🔴 산출물은 `docs/viewer/local/` 아래라 **커밋되지 않는다**.

---

## 7. 디스코드 연결

`/share-replay` 슬래시 명령 (`app/discord_bot.py` · `app/site_share.py`).

```
/share-replay hand:<패> recipe:<레시피> [line:<경로>] [title:<제목>]
```

* **봇의 응답 처리를 막지 않는다**: `defer()` 로 먼저 응답을 열고, 브라우저
  조작은 `asyncio.to_thread` 로 보낸다 (`/combo` 와 같은 구조).
* **동시 요청이 브라우저 상태를 섞지 않는다**: 한 칸짜리 자물쇠로 한 번에
  하나만 돌고, 돌고 있으면 기다리지 않고 「바쁘다」 로 답한다.
* **URL 이 실제로 만들어졌을 때만** 성공 링크를 적는다.
* 실패하면 짧은 이유와 함께 `combo-replay.html` 로 계속 재생할 수 있다고
  적는다.
* **외부 공유가 일어나는 조작임을 입구에서 먼저 알린다** (대기 중에 보이게
  첫 메시지로 보낸다).

🔴 **디스코드 실제 전송은 확인하지 않았다.** 봇 토큰이 없는 자리라 응답
생성 함수와 명령 등록만 시험으로 확인했고, 그것을 디스코드 실사용 확인이라고
부르지 않는다.

---

## 8. 남은 것

| 항목 | 상태 |
| --- | --- |
| 사이트 단독 성공 | ✅ 조작 16/16 · 최종 상태 일치 · 공유 URL 생성·재생 확인 |
| 재실행 가능한 자동 조작 | ✅ `scripts/duel_simulator_share.py` |
| 디스코드 연결 | ⚠ 구현했으나 **실제 전송 미확인** (토큰 없음) |
| 카드 식별(이름·효과 표시) | ❌ 미식별 — 그림이 없어서다. 이름은 시트에 찍혀 판에서 읽을 수 있다 |
| 상대 필드 | ❌ 넣지 않았다 — 기록에 이번 전개와 관련된 상대 정보가 없다 |
| 체인 번호·해결 구간 편집 | ❌ 이번 범위 밖 |

### 공식 Neuron 내보내기 이미지가 필요한 경우

**실제 카드 그림이 있는 판**으로 만들려면 아래 한 장이 필요하다.

* 필요한 파일: 遊戯王ニューロン(공식 앱)의 「デッキ画像を保存」 으로 내보낸
  **이 레시피 그대로의 덱 이미지 1장** (PNG/JPG).
* 왜 필요한가: 사이트는 **올린 덱 이미지에서 잘라낸 그림만** 판에 올린다.
  카드 검색으로 카드를 추가할 수 없고, 식별을 고쳐도 그림은 바뀌지 않는다
  (가이드라인 4절). 그리고 이 저장소가 가진 카드 그림은 외부에 올려 공개할
  권한이 없다 (§1).
* 받으면 바뀌는 것: `scripts/duel_simulator_share.py` 에 그 파일을 덱
  시트 대신 넣는 한 줄만 추가하면 된다. 조작·확인·공유 경로는 **지금 그대로**
  쓴다 (이미 끝까지 돌았다).
* 덱 순서 주의: 사이트의 「왼쪽 위 5장」 이 시작 패가 되도록, 내보낼 때
  `69811710 · 703897 · 2930675 · 12989604 · 61654098` 이 맨 앞 5장이어야
  한다. 아니면 계획의 `setup` 이 가리키는 자리를 바꿔야 한다.

운영자에게는 연락하지 않았다.
