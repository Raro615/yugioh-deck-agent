# Phase 3-F-9 — `TimingEvent.actor` 의미 계약 감사

## 1. Phase · Base · 실제 HEAD

| 항목 | 값 |
| --- | --- |
| Phase | 3-F-9 — TimingEvent.actor Semantic Contract Audit |
| 모드 | **AUDIT-ONLY** (production diff 0) |
| **실제 HEAD (측정)** | `96db694 Phase 3-F-8 보고서: commit SHA · push 결과 기록` |
| Base (3-F-8) | `d684133` (작업) · `96db694` (보고서) |
| 3-F-8 최종 판정 | **A. MINIMAL_RELATION_INPUTS_SUFFICIENT** |
| branch | `claude/pensive-goodall-te1egy` |
| baseline 테스트 | 4,254 passed / 4 skipped |
| 새 테스트 | `tests/test_timing_event_actor_semantic_audit.py` — **22건** |

### 🟡 프롬프트의 Base SHA 를 확인했고 둘이 어긋났다

프롬프트는 Base 를 `9bce29c / d684133 / 96db694` 로 적었다. 실제로 확인한
결과:

| 적힌 SHA | 확인 결과 |
| --- | --- |
| `9bce29c` | **존재하지 않는다** (`git cat-file`: `Not a valid object name`). `9bec29c` 의 오타로 보인다 |
| `9bec29c` | 존재하지만 **Phase 3-F-7** 의 보고서 commit 이다 |
| `d684133` | ○ Phase 3-F-8 작업 commit |
| `96db694` | ○ Phase 3-F-8 보고서 commit |

**3-F-8 의 commit 은 `d684133` · `96db694` 둘이다.** HEAD 가 `96db694` 이고
작업 트리가 깨끗한 것을 확인한 뒤 시작했다.

---

## 2. TimingEvent 정의

| 항목 | 실제 값 | 출처 | 의미 |
| --- | --- | --- | --- |
| 필드 | `point` · `delta` · `effect_ref` · `actor` · `note` (5개) | `engine/trigger.py:219` | 사건 하나 |
| `actor` 타입 | `int | None` | 같음 | 플레이어 번호 |
| Optional | **그렇다** — 기본값 `None` | 같음 | "알 수 없으면 `None`" (docstring) |
| 허용값 | `0` · `1` · `None` | `__post_init__` | `2` 를 넣으면 `TriggerError` |
| `canonical_state` 포함 | **포함된다** | `canonical_state()` | 재현에 쓰인다 |
| `to_dict` 포함 | 값이 있으면 포함, **`None` 이면 빠진다** | `to_dict()` | 적지 않은 것을 `0` 으로 적지 않는다 |
| `state_hash` 영향 | **없다** | `GameState` 밖이다 | 사건은 판의 모양이 아니다 |

docstring 은 이렇게 적어 두었다.

> `actor`: **이 사건을 일으킨 플레이어.** 알 수 없으면 `None`.

**이 문장이 실제와 맞는지가 이 Phase 의 질문이다.**

---

## 3. actor 생성 경로

경로는 **셋**뿐이다 (`test_02`).

| # | 경로 | `actor` 에 들어가는 것 |
| --- | --- | --- |
| 1 | `TimingEvent.from_delta(delta)` | delta 의 **사람 칸** — 그런데 **칸이 두 종류다** |
| 2 | `TimingEvent.from_journal_event(event)` | `event.actor` — 효과를 발동한 사람 (**행위자**) |
| 3 | `TimingEvent.unimplemented(note)` | 기본 **`None`** |

### 🔴 1번이 **두 가지 다른 칸**에서 가져온다

`from_delta` 의 코드에 두 문장이 함께 있다.

```
actor=delta.player        ← MonsterSummoned · CardDrawn · LifeChanged
actor=delta.to_player     ← ZoneMoved
```

그리고 `PhaseChanged` 는 **일부러 적지 않는다** — "페이즈 전이는 규칙이 하는
일이고, 누가 그것을 선언했는가는 우선권 계층의 질문이다" (코드 주석).

---

## 4. 사건별 actor 의미 — 전수 조사

### 🔴 먼저: 흔히 드는 사건 이름 **여섯은 클래스가 아니다** (`test_03`)

`engine` 전체를 import 해서 `StateDelta` 하위 클래스를 셌다. 구상 클래스는
**열둘**이고, 추상이 둘(`CardMovement` · `_SpellMovement`)이다.

| 이름 | 클래스로 존재하는가 |
| --- | --- |
| `MonsterSummoned` · `CardDrawn` · `LifeChanged` · `ZoneMoved` · `PhaseChanged` | **있다** |
| `CardDestroyed` · `CardAddedToHand` · `CardDiscarded` · `CardBanished` · `CardReturned` | **없다** — 전부 `ZoneMoved` 의 다른 `OperationKind` |
| `TurnChanged` | **없다** — `PhaseChanged` 가 `from_turn`/`to_turn` 을 들고 있다 |
| `ZoneShuffled` · `BattleDestruction` · `CardSet` · `SpellPlaced` · `SpellRevealed` · `SpellRetired` · `SpellRestored` | **있다** (프롬프트 목록에 없던 것) |

**그래서 actor 규칙은 13가지가 아니라 6가지다** — `ZoneMoved` 한 규칙이
파괴·추방·버리기·되돌리기·패로를 다 덮는다 (`test_08`).

### 전수 표

| Event | actor source | actor 의 실제 의미 | 행위자? | 대상? | 소유자? | 의미 없음? |
| --- | --- | --- | :---: | :---: | :---: | :---: |
| `MonsterSummoned` | `delta.player` | 소환한 사람 | **○** | | | |
| `CardDrawn` | `delta.player` | 뽑은 사람 | **○** | | | |
| `LifeChanged` | `delta.player` | LP 가 **바뀐** 사람 | | **○** | | |
| `ZoneMoved` (파괴·추방·버리기·되돌리기 포함) | `delta.to_player` | **도착지 주인** | | | **○** | |
| `PhaseChanged` | (적지 않는다) | — | | | | **○** |
| `ZoneShuffled` | (옮길 이름 없음) | — | | | | **○** |
| `BattleDestruction` | (옮길 이름 없음) | — | | | | **○** |
| `CardSet` | (옮길 이름 없음) | — | | | | **○** |
| `SpellPlaced` | (옮길 이름 없음) | — | | | | **○** |
| `SpellRevealed` | (옮길 이름 없음) | — | | | | **○** |
| `SpellRetired` | (옮길 이름 없음) | — | | | | **○** |
| `SpellRestored` | (옮길 이름 없음) | — | | | | **○** |

### 열둘 중 **다섯**만 시점 이름을 받는다 (`test_11`)

이름 없는 일곱은 `UNIMPLEMENTED` 가 되고 `actor` 가 **전부 `None`** 이다.
그중 여섯은 `player`·`owner`·`source_player` 를 **갖고 있는데도** 버려진다.

---

## 5. MonsterSummoned — **안전하다** (`test_04`)

`actor = delta.player` = 소환한 사람. **행위자가 맞다.**

`owner` 와 `player` 가 다를 수 있는 경우(상대 묘지에서 내가 소생)에도
`actor` 는 **소환한 쪽**을 고른다 — `changed_side` 가 참이 되는 그 경우에도
의미가 흔들리지 않는다.

---

## 6. CardDrawn — **안전하다** (`test_05`)

`actor = delta.player` = 뽑은 사람. **행위자가 맞다.**

그리고 "덱에서 카드가 이동했다" 와 **같은 개념으로 취급되지 않는다**:
`ZoneMoved(movement=DRAW, …)` 를 만들면 `ValueError` 로 **거절된다** —
"한 사실을 두 모양으로 적으면 세는 쪽이 두 번 센다" (코드). 별개 시점
`CARD_DRAWN` 이 따로 있다.

---

## 7. LifeChanged — 🔴 **당한 쪽이다** (`test_06`)

`actor = delta.player` = **LP 가 바뀐 사람**.

| 구분 | 현재 구조 |
| --- | --- |
| "LP 를 감소시킨 **원인**" | **어디에도 없다** |
| "LP 가 **변경된** 플레이어" | `player` — 그리고 그것이 `actor` 가 된다 |

`LifeChanged` 의 필드는 `player` · `before` · `after` **셋뿐**이고, 원인을
담을 칸이 없다. 회복도 같은 모양이다 — 방향만 다르고 `actor` 는 늘
당사자다.

---

## 8. ZoneMoved — 🔴 **도착지 주인이다** (`test_07` · `test_16`)

`actor = delta.to_player` = **도착지의 주인**.

§6 이 구분을 요구한 다섯 가운데 사건이 들고 있는 것은 넷이고, **"이동을
발생시킨 플레이어" 가 그 넷에 없다.**

| 구분해야 할 것 | 사건이 들고 있는가 |
| --- | --- |
| 이동을 발생시킨 플레이어 | **없다** |
| 카드 controller / owner | 간접적으로만 (`source_player`/`destination_player`) |
| source zone owner | ○ `source_player` |
| destination zone owner | ○ `destination_player` ← **이것이 `actor` 다** |

### 반례 측정

내 필드의 카드를 **상대 필드로** 넘기면:

```
delta.source_player = 0 (나)      delta.destination_player = 1 (상대)
event.actor         = 1 (상대)
```

"**내가** 내 카드를 상대에게 넘겼다" 인데 `actor` 가 **상대**다. 관계로
읽으면 OPPONENT 가 된다.

### "상대가 카드를 이동시켰다" vs "카드가 상대 필드로 이동했다"

**구분할 수 없다.** 다만 이것은 **정보 부재가 아니다** — 사건이
`from_zone`·`to_zone`·`source_player`·`destination_player` 를 다 들고 있고,
**어느 칸을 `actor` 로 골랐는가**의 문제다.

§6 이 물은 "구분할 수 없다면 어떤 `ValidationCode` 가 맞는가" 에 대해:
정보가 **있는데** 다른 칸을 보고 있는 상태이므로 `INFORMATION_UNAVAILABLE`
(정보가 없다)도 `RULE_NOT_IMPLEMENTED`(규칙이 없다)도 **정확하지 않다.**
지금 필요한 것은 판정 코드가 아니라 **의미를 정하는 일**이다. 새
`ValidationCode` 를 만들지 않았다.

---

## 9. CardDestroyed — 🔴 **클래스가 없고, 두 경로가 갈린다** (`test_09` · `test_15`)

§7 이 요구한 네 경우를 측정했다.

| | 경우 | 현재 표현 | 누가 파괴했는가 | 무엇이 파괴되었는가 | 누구의 카드였는가 |
| --- | --- | --- | --- | --- | --- |
| A | 내 카드가 **내 효과**로 파괴 | `ZoneMoved(DESTROY)` | **알 수 없다** | ○ `card` | ○ `destination_player` |
| B | 내 카드가 **상대 효과**로 파괴 | `ZoneMoved(DESTROY)` — **A 와 완전히 같다** | **알 수 없다** | ○ | ○ |
| C | **전투**로 내 카드가 파괴 | `BattleDestruction` → **`UNIMPLEMENTED`** | 알 수 없다 | ○ `card` | ○ `owner` (사건으로 옮길 때 **버려진다**) |
| D | 행위자를 알 수 없는 파괴 | 위와 구분되지 않는다 | — | — | — |

### A 와 B 가 **정규 표현까지 같다**

측정했다: 같은 카드가 같은 자리로 가면 `canonical_state()` 가 동일하고
`actor` 도 동일하다. **"destroyed card controller" 가 "destroyer actor" 의
자리를 쓰고 있고, 사실인 것은 앞의 것뿐이다.**

### C 는 **사건 이름조차 없다**

`BattleDestruction` 은 `CardMovement` 인데 `ZoneMoved` 가 아니어서
`from_delta` 가 옮기지 못한다 → `UNIMPLEMENTED` · `actor=None`. 전투 파괴는
지금 **트리거가 볼 수 없는 사건**이다.

---

## 10. 기타 사건

| 사건 | 측정 |
| --- | --- |
| `PhaseChanged` | `actor=None` — **의도된 공백**이다 (주석에 이유가 적혀 있다). 턴 변화도 이 안에 있다 |
| `ZoneShuffled` | `UNIMPLEMENTED` — STRUCTURAL-74 가 그렇게 결정해 두었다 |
| `CardSet` · `SpellPlaced` · `SpellRevealed` · `SpellRetired` · `SpellRestored` | 전부 `UNIMPLEMENTED` · `actor=None`. 다섯 다 `player`·`owner`·`source_player` 를 **갖고 있는데도** 사건으로 옮길 때 버려진다 (`test_10`) |

---

## 11. 🔴 가장 강한 반례 — 실제 듀얼의 직접 공격 (`test_12`)

실제 `Duel` 에서 P1 이 P0 을 직접 공격했다.

```
action.actor              = 1      (공격 선언자)
P0 의 LP                  8000 → 6100
남은 delta                 LifeChanged(player=0, before=8000, after=6100)
그 사건의 point            life_changed
그 사건의 actor            **0**        ← 맞은 쪽
```

**공격한 P1 은 어떤 delta 에도 남지 않는다.** 측정으로 확인했다 —
`action.actor` 가 `rule_uses` 에는 기록되지만(공격권) **delta 에는 들어가지
않는다**.

> 그래서 상위 계층이 `event.actor` 를 `PlayerRef` 로 읽으면,
> **"상대가 나를 공격했다" 가 "내가 했다"(SELF) 로 읽힌다.** 유희왕에서
> 가장 흔한 사건에서 관계가 **뒤집힌다.**

### 🟡 그런데 행위자는 **버려지지 않았다** (`test_13`)

`EventReader.read` 가 `actor` 를 넘기지 않으면
**`result.action.actor` 에서 가져와** `EventContext.actor` 에 싣는다.
같은 사건에서:

| 읽는 곳 | 값 | 뜻 |
| --- | --- | --- |
| `ObservedEvent.actor` (= `timing.actor`) | **0** | 맞은 쪽 |
| `ObservedEvent.context.actor` (= `action.actor`) | **1** | **공격자** |

**두 `actor` 가 서로 다른 답을 들고 나란히 있다.** 행위자는 사건 객체의
형제 칸에 **이미 있다** — `TimingEvent` 쪽이 아닌 `EventContext` 쪽이다.

이것이 이 Phase 의 두 번째 발견이고, 다음 Phase 의 질문을 훨씬 좁힌다.

---

## 12. 실제 consumer (§12)

| Consumer | actor 사용 | 해석 | event type 구분 | 위험 |
| --- | --- | --- | --- | --- |
| `TimingEvent.from_journal_event` | `actor=event.actor` | 효과를 발동한 사람 (**행위자**) | — | 낮다 |
| `ObservedEvent.actor` | `return self.timing.actor` | **그대로 옮긴다** | **없다** | **높다** — 섞인 뜻이 그대로 흐른다 |
| `EventContext.of` | `actor=actor` (= `action.actor`) | **행위자** | **없다** | 낮다 (뜻이 일관된다) |
| `EventContext.canonical_state`/`to_dict` | 직렬화 | 값만 | 없다 | 낮다 |
| `engine/trigger.py` `_event_relation` | **읽지 않는다** | — | — | 지금은 없다 |
| `engine/duel.py` (live) | **읽지 않는다** | — | — | **지금 당장 틀린 판정은 나오지 않는다** |
| `engine/timing.py` · `trigger_order.py` · `trigger_chain.py` (dormant) | `event.actor` **읽지 않는다** (3-F-7 측정) | — | — | 없다 |

측정으로 확인한 것 (`test_19`):

- `ObservedEvent.actor` 의 본문은 정확히 `return self.timing.actor` 다 —
  `point` 도 `isinstance` 도 **없다.** 사건 종류를 보고 뜻을 고르지 않는다.
- `EventContext.of` 도 `point` 를 보지 않는다.
- **`duel.py` 에 `event.actor`/`timing.actor` 가 하나도 없다** — 그래서
  지금 production 에서 틀린 관계 판정이 나오고 있지는 않다. dormant 라는
  이유로 빼지 않고 함께 셌고, dormant 쪽도 읽지 않는다.

> **지금은 아무도 읽지 않는다. 그래서 이것은 "현재 버그" 가 아니라 "다음
> Phase 가 읽기 시작하면 터지는 함정" 이다.**

---

## 13. SELF / OPPONENT 안전성 (§9)

| 사건군 | `event.actor` 를 `PlayerRef` 로 읽어도 안전한가 | 왜 |
| --- | --- | --- |
| `MonsterSummoned` | **안전** | 행위자다 |
| `CardDrawn` | **안전** | 행위자다 |
| `LifeChanged` | 🔴 **위험** | **당한 쪽**이다 — "상대가 나에게 피해를 줬다" 가 SELF 로 읽힌다 |
| `ZoneMoved` | 🔴 **위험** | **도착지 주인**이다 — "내가 상대에게 넘겼다" 가 OPPONENT 로 읽힌다 |
| `PhaseChanged` | 해당 없음 | `None` |
| 이름 없는 일곱 | 해당 없음 | `None` |

**열둘 중 둘만 안전하고, 둘은 위험하며, 여덟은 값이 없다** (`test_18`).

### `actor is None` 을 "상대가 아니다" 로 읽지 않는다 (`test_17`)

`None != 0` 과 `None != 1` 이 **둘 다 참**이므로, 단순 `!=` 비교는 "모른다"
를 "상대" 로 바꾼다. 안전한 모양은 **존재를 먼저 묻는 것**이다 — 3-F-8 이
설계 요구로 고정한 것을 여기서 네 사건군에 대해 재확인했다.

---

## 14. 잘못된 관계 판정 시나리오 (§13)

| # | 시나리오 | 현재 `actor` 만으로 SELF/OPPONENT 를 정확히 판단할 수 있는가 |
| --- | --- | --- |
| 1 | "상대가 나를 공격해서 LP 가 감소했다" | 🔴 **아니다.** `actor` = 나(맞은 쪽) → **SELF 로 읽힌다** (`test_12`) |
| 2 | "상대가 카드를 드로우했다" | **그렇다.** `actor` = 상대 (`test_14`) |
| 3 | "상대가 내 카드를 파괴했다" | 🔴 **아니다.** 내 효과로 파괴한 것과 **구분되지 않는다**. 파괴자를 적을 칸이 없다 (`test_15`) |
| 4 | "상대 필드로 카드가 이동했다" | 🔴 **판단은 되지만 뜻이 다르다.** `actor` = 상대이지만 움직인 쪽은 나일 수 있다 (`test_16`) |

### 왜 불가능한지 — 둘로 갈린다

| 원인 | 해당 시나리오 | 성격 |
| --- | --- | --- |
| **데이터에 아예 없다** | 3 (파괴자) · 1 (피해를 입힌 쪽, delta 기준) | 사건·delta 어디에도 칸이 없다 |
| **있는데 다른 칸을 보고 있다** | 4 (`source_player` 가 있다) · 1 (`EventContext.actor` 에 공격자가 있다) | **선택의 문제** |

이 구분이 중요하다. 전자는 데이터 모델 변경이 필요하고, **후자는 어느 칸을
읽을지 정하는 일**이다.

---

## 15. hidden-info (§14)

`test_20` — 행위자와 당사자는 **둘 다 공개 정보**다. 모든 사건의 `actor` 와
`context.actor` 가 `None`·0·1 뿐이고, 상대의 패·덱은 그대로 가려져 있다
(`concealed=True` · `cards == ()`). 뒷면 카드 신원도 쓰지 않았다.
**관측 경계를 변경하지 않았다.**

---

## 16. state_hash / RNG (§15)

| 확인 | 결과 |
| --- | --- |
| 사건을 읽는 일이 `state_hash` 를 바꾸는가 | **아니다** (`test_21` — 세 번 반복해 확인) |
| RNG 를 소비하는가 | **아니다** |
| `canonical_state` | 변경 없음 |
| clone 동작 | 변경 없음 |
| Search ranking | **digest 동일** — `30fa3597…` (6판 611결정) |
| Evaluation / AI | 변경 없음 |

`TimingEvent.actor` 는 `canonical_state` 에 들어가지만 그것은 **사건의**
정규 표현이고 `GameState.state_hash()` 와 무관하다.

---

## 17. 테스트 결과

### 새 테스트 — `tests/test_timing_event_actor_semantic_audit.py` 22건

| # | 이름 | §17 항목 |
| --- | --- | --- |
| 01 | the actor field definition | 1 |
| 02 | every actor creation path | 1 |
| 03 | **the real delta vocabulary is twelve classes not thirteen names** | 7~10 |
| 04 | monster summoned actor is the agent | 2 |
| 05 | card drawn actor is the agent | 3 |
| 06 | 🔴 life changed actor is the victim not the cause | 4 · 16 |
| 07 | 🔴 zone moved actor is the destination owner | 5 · 14 |
| 08 | destroy discard banish and return share one actor rule | 6~10 |
| 09 | 🔴 battle destruction has no point and no actor | 6 · 15 |
| 10 | set and spell movements are nameless too | 7~10 |
| 11 | only five of twelve deltas get a name | 7~10 |
| 12 | 🔴 **a real direct attack records the victim not the attacker** | 16 |
| 13 | 🟡 **two actors disagree on the same event** | 17 |
| 14 | an opponent draw is safe to read as a relation | 11 · 12 |
| 15 | 🔴 an opponent destroying my card is not distinguishable | 15 |
| 16 | 🔴 a card moving to the opponent field reads as the opponent acting | 14 |
| 17 | an absent actor is not an opponent | 13 |
| 18 | self and opponent safety per event family | 11 · 12 |
| 19 | the actor consumers do not branch on event type | 17 |
| 20 | reading the actor touches no hidden information | 18 |
| 21 | the state and the rng do not move | 19 · 20 |
| 22 | this phase changed nothing | 21 |

```
$ python3 -m pytest tests/test_timing_event_actor_semantic_audit.py -p no:randomly -q
22 passed in 9.25s
```

### 고의 위반 검증 — 6건, 전부 잡았다

| # | 위반 | 잡은 테스트 |
| --- | --- | --- |
| 1 | `ZoneMoved` 의 actor 를 `source_player` 로 바꾼다 | `test_02` · `test_07` · `test_16` |
| 2 | `LifeChanged` 에 `cause_player` 칸을 더한다 | `test_06` · `test_22` |
| 3 | `ObservedEvent.actor` 가 context 쪽을 우선한다 | `test_13` · `test_19` |
| 4 | `from_delta` 가 `BattleDestruction` 에 이름을 준다 | `test_11` · `test_17` · `test_18` + 1건 |
| 5 | 전투가 `LifeChanged` 에 **공격자**를 적는다 | `test_12` · `test_13` |
| 6 | `duel.py` 가 `event.actor` 를 읽는다 | `test_19` |

주입 파일 5개(`trigger.py` · `effect/delta.py` · `event_pipeline.py` ·
`battle.py` · `duel.py`)는 전부 백업에서 복원하고 md5 로 확인했다 (모두
`OK`).

### 🟡 측정 과정에서 내가 한 번 빠뜨렸다

처음 `StateDelta` 하위 클래스를 셀 때 `engine.battle` 과
`engine.spell_activation` 을 import 하지 않은 상태였고, 그래서
`BattleDestruction` · `CardSet` · `Spell*` **일곱 개가 빠진 채 "6개" 로**
셌다. `pkgutil.walk_packages` 로 `engine` 전체를 import 한 뒤 다시 세어
**열둘**을 얻었다.

그 교훈을 테스트에 적어 두었다 (`every_concrete_delta` 의 docstring) —
**하위 클래스를 세려면 먼저 전부 import 해야 한다.** 일부만 import 한
상태로 세면 조용히 적게 나온다.

### 전체 회귀

```
$ python3 -m pytest tests/test_timing_event_actor_semantic_audit.py -p no:randomly -q
22 passed in 9.25s

$ python3 -m pytest -p no:randomly -q
4276 passed, 4 skipped in 371.72s (0:06:11)
```

| | 통과 | skip |
| --- | --- | --- |
| Phase 3-F-8 직후 (baseline) | 4,254 | 4 |
| Phase 3-F-9 (이번) | **4,276** | 4 |
| 차이 | **+22** | 0 |

**+22 가 이번에 더한 시험 수와 정확히 같다.** skip 4건은 baseline 과 동일한
기존 skip 이다.

### 기존 테스트 처리

**수정 0건 · 삭제 0건 · skip 추가 0건 · assertion 약화 0건.**
production diff 가 0 이므로 기존 계약이 깨질 자리가 없었다.

---

## 18. production diff

```
$ git diff --stat -- engine agent app core analysis rules rulings sources scripts
(출력 없음)
```

**0.** 추가한 것은 테스트 하나와 이 보고서뿐이다.

### §10 의 세 설계 — 감사만 (결론을 먼저 내리지 않았다)

| | 설계 | 측정이 말하는 것 |
| --- | --- | --- |
| A | 현재 `actor` 하나 유지 | **안 된다.** 뜻이 사건군마다 다르고 상위 판정이 뒤집힌다 (§13) |
| B | `actor` 의 semantic 을 event type 별로 **엄격히 정의** | 가능하다 — 그런데 "정의" 만으로는 `LifeChanged` 의 **원인**과 파괴자가 생기지 않는다. 읽는 쪽이 사건군마다 분기해야 하고, 지금 읽는 자리들은 분기하지 않는다 (§12) |
| C | 별도 field 추가 (`cause_player` 등) | **일부에만 필요하다.** `ZoneMoved` 는 `source_player` 가 이미 있고 `EventContext.actor` 에 행위자가 이미 있다 — **없는 것은 파괴자와 데미지 원인뿐**이다 |

**새 field 를 더하자는 결론을 내리지 않았다.** 측정 결과 필요한 것이
사건군마다 다르고, 특히 `EventContext.actor` 가 이미 행위자를 들고 있다는
사실(§11)이 C 의 범위를 크게 줄인다. 그 정리가 다음 Phase 의 일이다.

---

## 19. 최종 판정

### **C. ACTOR_EVENT_DEPENDENT**

> `actor` 가 사건 종류에 따라 다른 semantic 을 가지며 현재 상위 관계 판정에
> 위험이 있다.

§11 이 요구한 세 갈래 가운데 **세 번째**다.

| 갈래 | 해당하는가 |
| --- | --- |
| 1. 이름은 애매하지만 의미는 일관됨 → 문서화 문제 | **아니다** — 의미가 실제로 다르다 (§4 표) |
| 2. 사건별로 다르지만 각 사건에서 명확한 규칙이 있음 → semantic contract 문제 | **부분적으로만** — 규칙은 있지만 **docstring 이 그 규칙과 다르게 약속한다** |
| 3. 같은 field 가 사건마다 다른 의미로 쓰여 **상위 판정이 잘못될 수 있다** → structural risk | **그렇다** — `test_12` 가 실제 듀얼에서 관계가 뒤집히는 것을 보였다 |

판정 기준("향후 `EVENT_RELATION` 이 `actor` 를 안전하게 `PlayerRef` 로
해석할 수 있는가")에 대한 답: **열둘 중 둘만 안전하다.**

### 왜 A 가 아닌가

`MonsterSummoned` · `CardDrawn` 만 보면 일관돼 보인다. 그러나
`LifeChanged`(당한 쪽)와 `ZoneMoved`(도착지 주인)에서 **뜻이 뒤집히고**,
그것이 전투라는 가장 흔한 경로에서 일어난다.

### 왜 B 가 아닌가

B 는 "실제 동작은 일관되지만 문서/명명이 불명확하다" 다. 동작이 **일관되지
않다** — 두 칸(`delta.player`·`delta.to_player`)에서 가져오고, 그 둘이 서로
다른 개념이다. 이름만 고쳐도 `test_12` 의 뒤집힘은 남는다.

### 왜 D 가 아닌가

D 는 "actor 하나만으로는 중요한 관계를 표현할 수 없다" 다. 그것도 사실이지만
(파괴자·데미지 원인), **더 정확한 진단은 "하나로 여러 뜻을 나른다"** 다.
D 로 적으면 "칸을 더하면 된다" 로 읽히는데, 측정은 **행위자가 이미
`EventContext.actor` 에 있다**는 것을 보였다 (§11). 부족함보다 **혼재**가
먼저 풀려야 한다.

### 왜 E 가 아닌가

예상보다 큰 구조 문제는 아니다. 원인이 `from_delta` 의 두 문장으로
특정되고, 각 delta 가 어떤 사람 칸을 갖는지에서 직접 따라온다. 그리고
**지금 이 값을 읽는 production consumer 가 하나도 없어서**(§12) 현재
동작하는 코드에는 영향이 없다 — 터지기 전에 찾은 함정이다.

---

## 20. 다음 Phase 후보 (1개)

**Phase 3-F-10 — 행위자를 어느 칸에서 읽을 것인가: `TimingEvent.actor` 와
`EventContext.actor` 의 역할 분리 감사**

§11 의 발견 하나만 본다. **행위자는 이미 `EventContext.actor` 에 있고**,
`TimingEvent.actor` 는 delta 의 당사자를 들고 있다. 두 칸이 같은 이름으로
다른 것을 가리키는 것이 혼란의 뿌리이므로, **칸을 더하기 전에 둘의 역할을
가르는 것**이 먼저다.

그 Phase 가 답해야 할 것:

1. `EventContext.actor` 가 **언제나** 채워지는가 — `EventReader.read` 가
   `result.action` 이 없는 결과(효과 해결 · 규칙 진행)에서는 `None` 을 넣을
   수 있다. 그 범위를 센다.
2. 둘의 이름을 가르면(예: 사건 쪽을 "당사자" 로 읽기) **기존 읽는 자리
   몇 곳이 영향받는가.** 지금 `timing.actor` 를 읽는 곳은
   `ObservedEvent.actor` 하나다 — 그 하나의 뜻을 어느 쪽으로 정할지가 핵심이다.
3. 그렇게 갈라도 **여전히 없는 것**이 무엇인가 — 파괴자와 데미지 원인.
   그 둘이 `EventContext.actor` 로 덮이는지(전투는 `action.actor` 가 공격자
   이므로 덮일 가능성이 있다) 측정한다.
4. `BattleDestruction` 등 이름 없는 일곱을 `UNIMPLEMENTED` 로 두는 결정이
   이 문제와 **독립인가.** 이름을 주는 것과 행위자를 정하는 것을 섞지 않는다.

**이 Phase 는 그 작업을 하지 않았다. 다음 Phase 는 임의로 진행하지 않는다.**
