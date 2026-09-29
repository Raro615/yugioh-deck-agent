# Phase 2-AJ — Real Card Semantics Audit & Next Execution Boundary

기준 커밋: `b20643d` (Phase 2-AI) · 2847 passed / 4 skipped
→ 이번 단계: **2871 passed / 4 skipped**

한 줄 결론: **BLOCKER 하나를 찾아 고쳤고(🔴), 공식 재정으로
STRUCTURAL-96 을 닫았으며, 다음 병목은 ADR-006(판정기 부재)로 확정했다.**

---

## 1. 이번 단계가 한 일의 크기

코드 변경은 **세 파일, 실질 20줄 남짓**이다. 나머지는 조사와 근거 기록이다.
§12 의 종료 기준으로는 **PASS B** — "다음 단계 진행을 막는 명확한
STRUCTURAL 문제를 발견했고, 최소 범위로 해결했다."

---

## 2. Repository Audit

### 확인한 실행 경로

```
PlayerAction
  → EffectActivator.activate        activation.py:389
  → Chain / ChainLink
  → ChainResolver.resolve_top       chain.py:557
  → EffectExecutor.execute          executor.py:420
       _plan   (state.project() 위에서)   executor.py:485
       _apply  (진짜 판)                  executor.py:1543
  → StateDelta
  → EventJournal                    effect/journal.py
  ├─→ EventReader.read_deltas       event_pipeline.py  (관측)
  └─→ timing_events                 trigger.py         (트리거)  ← 여기서 죽었다
  → TriggerCollector.collect        trigger.py:784
```

### 핵심 발견 — 변화를 사건으로 옮기는 자리가 **둘**이었다

둘 다 `StateDelta → TimingEvent` 를 하는데, **다르게 굴었다.**

| | 모르는 변화를 만나면 |
|---|---|
| `EventReader._timing_for` | `TimingEvent.unimplemented` 로 남긴다 |
| `trigger.timing_events` | **`TriggerError` 를 던진다** |

STRUCTURAL-74 는 이미 "셔플은 `UNIMPLEMENTED` 사건으로 남는다" 고 적어
두었다. 그 결정을 **한쪽만 지키고 있었다.**

---

## 3. 🔴 BLOCKER — 셔플이 든 실제 카드의 해결을 트리거로 넘기면 죽었다

Phase 2-AI 가 리로드를 등재하면서 `ZoneShuffled` (Phase 2-Z 에 생긴 델타)가
**실제 카드 경로에서 처음으로 생겼다.** 그전에는 synthetic 정의만
`ShuffleOperation` 을 썼고, 그 테스트들은 트리거 계층까지 가지 않았다.

재현:

```
TriggerError: 이 변화를 시점으로 옮길 수 없습니다: ZoneShuffled.
              지어내지 않고 TimingEvent.unimplemented 를 쓰세요.
```

효과 자체는 멀쩡히 해결된다 (`RESOLVED`, 7개 델타). 죽는 것은 **그 다음**
한 걸음이다. `StateDelta → EventJournal → 후속 Timing/Trigger` 라는
파이프라인의 마지막 마디가 끊겨 있었다.

### 분류 (§2)

**A — 기존 구조의 실제 BUG.** 새로운 설계 질문이 아니다. STRUCTURAL-74 가
답을 이미 적어 두었고, 코드 한 곳이 그것을 지키지 않았다.

### 고친 방법 — 판단을 한 군데로

```python
# engine/trigger.py
def timing_for(delta: StateDelta) -> TimingEvent:
    try:
        return TimingEvent.from_delta(delta)
    except TriggerError:
        return TimingEvent.unimplemented(...)

def timing_events(event):
    found = [timing_for(delta) for delta in event.deltas]   # 전부 자리를 지킨다
    found.append(TimingEvent.from_journal_event(event))
    return tuple(found)

# engine/event_pipeline.py
def _timing_for(self, delta):
    return timing_for(delta)        # try/except 한 벌을 지웠다
```

**지어내지 않는 태도는 그대로다.** `TimingEvent.from_delta` 는 여전히
모르는 변화에 예외를 던진다 — 너그러워진 것은 파이프라인이지 그 함수가
아니다.

### 왜 "덱을 섞었을 때" 시점을 만들지 않았는가

corpus 가 답한다.

- `data/constants/constant.lua` 에 `EVENT_*SHUFFLE` 이 **없다.**
- 그런 상수에 반응하는 카드 스크립트가 **0장.**

없는 사건에 이름을 붙이면 그 이름이 옳은지 아무도 확인하지 않는다.
STRUCTURAL-74 의 판단이 맞았고, 이번에 근거만 보탰다.

---

## 4. STRUCTURAL-96 — 공식 재정이 답했다 (**RESOLVED**)

### 정확한 문제

리로드의 드로우 매수가 무엇을 가리켜야 하는가.

| 출처 | 말하는 것 |
|---|---|
| `c22589918.lua` | `Duel.Draw(p,#g,…)` — `g` 는 패 전체 그룹 = **넣으려 한 수** |
| 공식 텍스트 (KO) | "덱에 넣은 매수만큼" = **실제로 들어간 수** |
| 공식 텍스트 (JA) | "デッキに加えた枚数分" = 같음 |

2-AI 는 "출처가 `official_lua` 이므로 스크립트를 따른다" 로 `ATTEMPTED_COUNT`
를 적고, 차이를 기록만 해 두었다.

### 실제 evidence — 공식 데이터베이스에서 받아 왔다

`https://www.db.yugioh-card.com/yugiohdb/` 에서 두 장만 받았다
(`--card-id 22589918 --card-id 77561728`, **`--all` 아님**).
`data/rulings/ocg/5849.json` · `5546.json`.

**OCG-QA-11919** (같은 "デッキに戻した数だけドロー" 계열, 時械神ガブリオン):

> 『その後、相手は自身のデッキに戻した数だけドローする』処理の際の、
> 『自身のデッキに戻した数』にその魔法・罠カード（＝「リロード」と
> 「強欲な瓶」）は**含まれません**。

덱에 **돌아가지 않은** 카드는 "되돌린 수" 에 들어가지 않는다.
→ 공식 semantics 는 **`AFFECTED_COUNT`**.

`#g` 는 이 카드에서 두 수가 언제나 같아서 통하는 **스크립트의 지름길**이다.

### 같은 페이지의 보충(補足)이 정의의 모양도 확인해 준다

> ■デッキが０枚の状況でも発動できます。
> ■処理時に、『自分の手札を全てデッキに加えてシャッフルする』処理を行います。
>   その後、『デッキに加えた枚数分のカードをドローする』処理を行います。
>   （これらの処理は同時に行われません。）

- 되돌리기 · 셔플 · 드로우는 **한 덩어리가 아니라 차례**다 →
  조작 셋 + `ResultRef` 하나라는 지금 모양이 맞다.
- "덱이 0장이어도 발동할 수 있다" → 2-AI 의
  `test_g_this_card_can_never_run_the_deck_out` 이 실행으로 발견한 사실을
  공식 자료가 확인해 준다.

### 어느 쪽이 authoritative 인가

| 층 | 권위 | 이번 판단 |
|---|---|---|
| 공식 카드 텍스트 · 재정 (`db.yugioh-card.com`) | **최상** | 따른다 |
| EDOPro 스크립트 (`c*.lua`) | 구현 | 모양은 따르되, 공식이 직접 답한 자리에서는 양보 |
| passcode ↔ cid 링크 | `unverified` | 수집 결과의 `authoritative` 가 **거짓**으로 남는다 |

마지막 줄을 뭉개지 않는다. 이름(`リロード`)과 텍스트가 맞는다는 것은
**내용으로** 확인했고, 그것은 링크 검증과 **다른 일**이다.

### 현재 architecture 에서 표현 가능한가 — **그렇다**

`ResultField` 가 이미 두 칸을 갖고 있다. 고친 것은 한 줄이다.

```python
DrawOperation(count=SelectionCount.from_result(
    ResultRef(0, ResultField.AFFECTED_COUNT)))   # 였던 것: ATTEMPTED_COUNT
```

**동작은 바뀌지 않는다.** 실행기가 두 수를 가르는 길은
`Partial.AS_MANY_AS_POSSIBLE` 하나뿐인데 (`_plan_card_operation` 의
`refused`), 그렇게 적힌 실제 카드가 아직 0장이다. 고친 이유는 동작이 아니라
**주장**이 틀렸기 때문이다 — 언젠가 갈릴 때 조용히 틀리지 않도록.

### 가장 중요한 부수 발견 — 계열이 한 칸을 공유하지 않는다

"되돌린 수만큼 드로우" 계열 **7장**. 스크립트는 전부 `Duel.Draw(p,#g,…)` 로
같은데, 공식 텍스트가 갈린다.

| 카드 | 공식 텍스트 | 의미하는 칸 |
|---|---|---|
| 리로드 22589918 | 덱에 넣은 매수만큼 | AFFECTED |
| 기억말소 52817046 | 덱에 넣은 매수만큼 | AFFECTED |
| 포톤 레오 38757297 | 덱에 넣은 매수만큼 | AFFECTED |
| 요술망치 85852291 | 덱에 넣은 매수만큼 | AFFECTED |
| 뇌조룡 83107873 | 덱으로 되돌린 수만큼 | AFFECTED |
| 마건총 19489718 | 덱으로 되돌린 수만큼 | AFFECTED |
| **교란작전 77561728** | **원래의 패의 수만큼** (元の手札の数だけ) | **ATTEMPTED** |

조작 종류(`RETURN_TO_DECK`)로 기본값을 정했다면 그 한 장이 **조용히
틀렸을 것이다.** 2-X 의 관문 · 2-AC 의 `Shortfall` · 2-AF 의 `Partial` 과
**같은 결론**: 카드가 적어 둔 것만 옮긴다.

---

## 5. 실제 Card Corpus Audit

### 조사한 범위

스크립트 12,702장 전수 + 공식 텍스트(cards.cdb) + 공식 재정 2장.

### 대표 구조와 현재 지원 상태

| # | 구조 | corpus | 표현 가능? | 실행 가능? | 막는 것 |
|---|---|---:|---|---|---|
| 1 | 단순 조작 (대상 없음) | 3,252 | ✔ | ✔ | — |
| 2 | 고른다 | 8,363 | ✔ | 일부 | 조작별 판정기 |
| 3 | 해당하는 것 전부 | 3,015 | ✔ (2-AI) | 1장 | **ADR-006** |
| 4 | 무작위 | 141 | ✔ (2-AB) | 2장 | — |
| 5 | 앞 결과 → 뒤 조작 | 408 | ✔ (2-AD) | **1장** | ADR-006 |
| 6 | 플레이어가 선언 | 148 | **부분** | 0장 | **STRUCTURAL-97** |
| 7 | 되돌리기 → 셔플 → 드로우 | 7 | ✔ | 1장 | — |

### 5번을 더 쪼개면

| 스크립트 모양 | 자리 수 | 엔진의 자리 |
|---|---:|---|
| 이동 호출의 반환값을 `0` 과 견준다 | **1,433** | `OperationGuard` + `NumericTest.any_at_all()` — **적을 수 있다** |
| `Duel.GetOperatedGroup()` | 311 | STRUCTURAL-87 — 옮기지 않기로 한 것 (암묵 참조라서) |
| 반환값을 변수로 받아 수로 쓴다 | 146 | `ResultRef(AFFECTED_COUNT)` — **적을 수 있다** |
| `FilterCount(IsLocation…) == #g` | 1 | `OperationResult.is_complete` — **적을 수 있다** |

**1,433곳을 막는 것은 조건 계층이 아니다.** 조건은 이미 적힌다. 막는 것은
그 앞의 조작(파괴 · 제외 …)이 판정기가 없어 실행되지 않는 것이다 —
ADR-006.

### 6번 — 새 STRUCTURAL

`Duel.Announce*` 199자리.

```
AnnounceNumber        60  ┐
AnnounceLevel         27  ├ 수        → NumberDomain 으로 적을 수 있다 (106)
AnnounceNumberRange   19  ┘
AnnounceCard          32  ┐
AnnounceAttribute     29  ├ 수가 아니다 → **적을 자리가 없다** (92)
AnnounceRace          20  │
AnnounceAnotherAttr…   7  │
AnnounceAnotherRace    4  ┘
AnnounceCoin           1    동전 — 별개
```

`NumberDomain.values: tuple[int, ...]` 이고 `DeclaredNumber.value: int` 다.
"카드명을 선언한다" · "속성을 선언한다" 를 담을 자리가 **없다.**
coverage 부족이 아니라 **담는 것이 다른 것**이다.

---

## 6. TODO 재분류

| | Status | Severity | Evidence | Fixed / Deferred | Next Phase |
|---|---|---|---|---|---|
| **71** 덱을 본 뒤 섞지 않는다 | STRUCTURAL | 🟠 | `ShuffleOperation` 은 생겼지만 "효과가 끝난 뒤 섞는다" 를 부르는 자리가 여전히 없다 | Deferred — 발동/해결 절차의 일이고 결과 계층이 아니다 | 실제 카드 coverage |
| **74** 셔플 시점 없음 | **부분 RESOLVED** | 🟡 | `EVENT_*SHUFFLE` 상수 0 · 반응 카드 0 | **Fixed**(죽던 것). 이름은 여전히 만들지 않음 — 그것이 맞는 상태다 | 없음 |
| **75** 패 셔플 442장 | NOT YET RELEVANT | 🟡 | `Duel.ShuffleHand` 를 쓰는 등재 카드 0 | Deferred — 규칙상 의미(정보가 바뀌는가) 미확인 | 관측 계층 |
| **76** 지속 효과 계층 없음 | STRUCTURAL | 🟠 | `ObservationGrant` 를 카드에서 읽는 자리 없음 | Deferred — Phase 8 | Phase 8 |
| **77** 아키타입 조건 없음 | STRUCTURAL | 🟠 | `IsSetCard` 4,601장 | Deferred | 조건 계층 확장 |
| **78** `INSPECT_FACE_DOWN` | NOT YET RELEVANT | 🟡 | EDOPro 에 상수 없음 | Deferred | 없음 |
| **83** 몬스터 종류 조건 | STRUCTURAL | 🟡 | 6859683 하나가 이것으로 막힌다 | Deferred | 조건 계층 확장 |
| **86** 라이프 증감이 고정 수뿐 | STRUCTURAL | 🟡 | 30922149 `dr*2000` | Deferred — `ResultRef.multiplier` 가 절반은 답한다 | 값 계층 |
| **87** `GetOperatedGroup` 311장 | STRUCTURAL | 🟡 | 이번 측정에서 **311 재확인** | Deferred — 표현력이 아니라 **암묵 참조**가 문제 (§9 위반) | 결과 계층 |
| **90** `SelectionCount` 이름이 좁다 | COSMETIC | 🟢 | 65곳 이름 변경 | Deferred | 언제든 |
| **93** 값끼리 못 견준다 | DETAIL | 🟡 | 자리가 **1 → 2** (59490397, 19489718) | Deferred — **둘 다** `OperationResult.is_complete` 로 답한다. 연산자를 늘릴 이유가 아직 없다 | 없음 |
| **95** 투영을 두 번 적용 | DETAIL | 🟢 | 효과당 조작 3개 | Deferred — 재지 않았고 문제도 아니다 | 없음 |
| **96** 텍스트 vs 스크립트 | **RESOLVED** | — | OCG-QA-11919 + 7장 계열 | **Fixed** — 공식 재정으로 닫았고, 갈리는 것이 계열이 아니라 **카드**라는 것까지 확인 | 없음 |
| **97** 선언이 수가 아닐 수 있다 | **신규 STRUCTURAL** | 🟠 | `Announce*` 199자리 중 **92**가 수가 아니다 | Deferred — 이번 목표가 아니다 | 선언 계층 확장 |

---

## 7. 코드 변경

| 파일 | 변경 | 왜 |
|---|---|---|
| `engine/trigger.py` | `timing_for()` 추가 · `timing_events()` 가 그것을 쓴다 | 🔴 셔플이 든 해결이 트리거 계층에서 죽었다 |
| `engine/event_pipeline.py` | `_timing_for` 가 `timing_for` 에 위임 | 같은 판단을 두 벌 두면 또 갈린다 |
| `engine/effect/library.py` | 리로드의 `ResultRef` 필드 `ATTEMPTED` → `AFFECTED` + 근거 기록 | STRUCTURAL-96 — 공식 재정이 답했다 |
| `data/rulings/ocg/5849.json` · `5546.json` | 공식 재정 2장 (신규) | 근거를 말이 아니라 **데이터로** 남긴다 |

기존 테스트 수정 **2건** (삭제 0건):

- `test_bulk_selection.py::test_e_the_draw_reads_the_attempted_count…`
  → `…_the_affected_count_because_the_ruling_says_so`.
  **잘못된 가정이 무엇이었는지**: "출처가 `official_lua` 면 스크립트가 최종
  권위다." 스크립트는 구현이고, 공식 데이터베이스가 직접 답한 자리에서는
  그쪽이 권위다.
- `test_identity_trust_boundary.py::test_existing_records_are_preserved…`
  장부 9 → 11, 그리고 **진짜 잘못된 가정 하나**: "`EXISTS` 면 Q&A 가
  있다." 교란작전은 Q&A 0건인데 보충은 있다 — `CardRulingSet` 은 둘을 따로
  들고 있고, 단언이 그 모델과 어긋나 있었다.

---

## 8. 테스트

- New tests: **24** (`tests/engine/test_real_card_semantics.py`)
- Passed: **2871** / Failed: 0 / Skipped: 4 / Total: 2875
- Regression: **0**

§11 이 요구한 최소 항목:

| 요구 | 시험 |
|---|---|
| ResultRef semantics | `test_c_the_two_counts_are_separate_questions` · `test_c_success_is_not_a_number` |
| 앞 조작 → 뒤 조작 | `test_c_the_dependency_really_carries_a_number_between_operations` |
| 실제 corpus 구조 | `test_d_*` (1,433 · 311 · 146 · 1 · 199 전부 다시 잰다) |
| UNKNOWN / PENDING 구분 | `test_c_not_yet_is_not_unknown_and_not_zero` |
| clone 독립 | `test_e_a_clone_does_not_share_the_outcome` |
| 결정론 | `test_e_the_same_seed_gives_the_same_resolution` |
| (추가) 정보 경계 §10 | `test_e_resolving_reveals_nothing_new_to_the_opponent` |

---

## 9. Architecture 판단

> "현재 Duel Engine 은 실제 카드 실행을 확대하기 전에 어떤 구조적 문제를
> 먼저 해결해야 하는가?"

**결과/조건/값 계층은 더 손댈 것이 없다.** §6 의 질문에 답하면:

- **Q1** — 그렇다. `ResultRef` + `OperationResult` 로 "앞 결과 → 뒤 조작"
  이 표현된다. 실제 카드에서 실제로 돈다 (리로드).
- **Q2** — 부족한 것은 **result field semantics 도, operation result model
  도, value/domain 도, execution context 도 아니었다.** 유일하게 부족했던
  것은 **card translation layer** 다: 어느 칸을 가리켜야 하는지 결정할
  근거(공식 재정)가 없었을 뿐이고, 받아 보니 기존 칸으로 그대로 적혔다.
- **Q3** — 이번에 찾은 BLOCKER 는 결과 계층이 아니라 **사건 계층의 버그**
  였고, 고쳤다.
- **Q4** — 나머지는 "아직 지원하지 않는 카드 유형" 이 맞다. 단 그 이유는
  표현력이 아니라 **판정기 부재**다.
- **Q5** — 아래.

> "추가적인 구조 수정 없이 실제 카드 coverage 단계로 진행할 수 있는가?"

**조건부로 그렇다.** 결과 계층은 준비됐다. 그러나 coverage 를 실제로
늘리려면 먼저 **ADR-006** 을 풀어야 한다.

등재된 16장 중 4장이 실행되지 않고, 그 넷 다 이유가 같다 —
`UnknownDestructionRuling` · `IsAbleToHand` · `IsAbleToRemove` 처럼
**"이 카드를 이렇게 해도 되는가" 를 답할 판정기가 등록되어 있지 않다.**
corpus 규모로는 `Destroy` 계열만 533장, 전체 bulk 1,156장이 여기 걸린다.

`ResultRef` 를 쓰는 408장도 **같은 벽**이다. 앞 조작이 파괴/제외라서
실행되지 않으면, 뒤의 수를 아무리 정확하게 적어도 돌지 않는다.

---

## 10. 다음 Phase 제안

```
NEXT PHASE:
  Operation Ruling Layer — 조작별 규칙 판정기 (ADR-006)

목표:
  "이 카드를 파괴/제외/패로/덱으로 할 수 있는가" 를 답하는 판정기를
  **손으로 등록하는 구조** 그대로 채운다. 지금은 등록된 것이 없어
  UnknownDestructionRuling 이 모든 파괴를 UNKNOWN 으로 답한다.
  자동 생성하지 않고, 공식 텍스트/스크립트가 실제로 말하는 것만 옮긴다.

이유:
  - 등재 16장 중 실행되지 않는 4장이 **전부** 이것 때문이다.
  - bulk 1,156장 · 결과 참조 408장 · 조건 1,433자리가 **같은 벽**에서 멈춘다.
  - 결과/조건/값/부분/선택/무작위 계층은 이번 감사에서 "표현 가능" 으로
    확인됐다. 다음 병목은 명백히 여기 하나다.
  - UNKNOWN 을 허가로 바꾸지 않는다는 규칙이 이미 서 있으므로, 판정기를
    채우는 일은 기존 경계를 넓히지 않고 **비어 있는 자리를 메우는** 일이다.

선행 조건:
  - 없음. 이번 Phase 에서 BLOCKER 0.
  - 다만 판정기의 근거는 공식 자료여야 한다. 이번에 확인한 대로
    `scripts/fetch_ocg_rulings.py --card-id …` 로 **카드 단위**로 받는다
    (`--all` 금지 그대로).
```

---

## 11. 이번에 하지 않은 것 (§3)

Duel Engine 재설계 · EffectExecutor 재작성 · 새 Graph Engine · 새 EventBus ·
새 Expression Language · 새 Promise/Future · 새 Rule Engine · 카드 이름별
hardcoded rule · architecture 우회 · 모든 카드 지원 시도 · AI decision logic ·
Discord/Web UI · 테스트 삭제/완화.

**새 카드를 한 장도 등재하지 않았다.** 이번 단계는 재는 단계였다.
`NumericTest` 에 연산자를 늘리지 않았고(STRUCTURAL-93 의 두 자리 모두
`is_complete` 로 답한다), `TimingPoint` 에 이름을 늘리지 않았으며,
`NumberDomain` 을 수 아닌 것까지 담도록 넓히지 않았다(STRUCTURAL-97 로
기록만 했다).

---

## 12. 최종

```
NEXT PHASE: POSSIBLE
BLOCKER: 0   (이번에 찾은 1건은 이번 단계에서 고쳤다)
```

**다음 Phase 는 시작하지 않았다.**
