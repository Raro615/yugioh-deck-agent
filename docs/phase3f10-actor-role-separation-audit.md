# Phase 3-F-10 — `TimingEvent.actor` / `EventContext.actor` 역할 분리 감사

## 1. Phase · Base · 실제 HEAD

| 항목 | 값 |
| --- | --- |
| Phase | 3-F-10 — Actor Role Separation Audit |
| 모드 | **AUDIT-ONLY** (production diff 0) |
| **실제 HEAD (측정)** | `c5a0ba8 Phase 3-F-9 보고서: commit SHA · push 결과 기록` |
| Base (3-F-9) | `7481c20` (작업) · `c5a0ba8` (보고서) — **둘 다 실제로 존재한다** |
| 3-F-9 최종 판정 | **C. ACTOR_EVENT_DEPENDENT** |
| branch | `claude/pensive-goodall-te1egy` |
| baseline 테스트 | 4,276 passed / 4 skipped |
| 새 테스트 | `tests/test_actor_role_separation_audit.py` — **23건** |

`git log` 로 HEAD 를 확인했고 작업 트리는 깨끗했다. 프롬프트의 Base SHA 둘은
이번에는 **모두 정확했다** (3-F-9 에서는 하나가 존재하지 않는 오타였다).

---

## 2. `TimingEvent.actor` 정의

### 한 문장 계약 (§3)

> **그 변화(delta) 가 직접 가리키는 플레이어.** delta 의 사람 칸에서
> **파생**되고, 어느 칸을 읽는지는 사건군이 정한다.

### 근거 (`test_01`)

`from_delta` 가 delta 의 칸을 읽어 정한다. **부르는 쪽이 끼어들 자리가
없다** — 그 메서드는 `delta` 하나만 받고, 본문에 `actor=actor` 가 없다.

| 성질 | 측정 |
| --- | --- |
| 출처 | **파생** — `delta.player` 또는 `delta.to_player` |
| delta 와의 일치 | **언제나 일치한다** (같은 delta → 같은 actor) |
| 뜻 | **사건군마다 다르다** (3-F-9 가 측정) |
| 타입 | `int | None`, 기본 `None`, 0/1 만 허용 |

---

## 3. `EventContext.actor` 정의

### 한 문장 계약 (§3)

> **그 변화 묶음을 일으킨 행위의 주체로 "부르는 쪽이 선언한" 값.**
> `read(result)` 에 `actor` 를 주면 그것, 안 주면 `result.action.actor`,
> 그것도 없으면 `None`.

### 근거 (`test_02` · `test_19`)

| 성질 | 측정 |
| --- | --- |
| 출처 | **선언** — 세 단계 (넘긴 값 → `result.action.actor` → `None`) |
| 자동 충전 | **`.action` 을 가진 결과에서만** — `ActionExecution` 하나뿐이다 |
| delta 와의 일치 | **아무도 검증하지 않는다** — 모순된 값도 받아들인다 |
| 뜻 | 행위자 — **의도상**. `__str__` 가 `None` 을 **"규칙"** 으로 읽는 것이 그 증거다 |

`.action` 을 갖는 결과를 셌다:

| 결과 타입 | `.action` | 그래서 |
| --- | :---: | --- |
| `ActionExecution` | **있다** | 자동으로 행위자가 찬다 |
| `EffectResult` | 없다 | **기본 `None`** |
| `ProgressionResult` | 없다 | **기본 `None`** |

---

## 4. 각각의 생성 경로

### A. Action → ActionExecution → Delta → `TimingEvent.actor`

| 값 | 생성 위치 | source | 타입 | 의미 | consumer |
| --- | --- | --- | --- | --- | --- |
| `TimingEvent.actor` | `engine/trigger.py` `TimingEvent.from_delta` | `delta.player` (소환·드로우·라이프) 또는 `delta.to_player` (이동) | `int | None` | **그 변화의 당사자** | `ObservedEvent.actor` 하나 |

### B. Action → `EventContext.actor` → `ObservedEvent.context.actor`

| 값 | 생성 위치 | source | 타입 | 의미 | consumer |
| --- | --- | --- | --- | --- | --- |
| `EventContext.actor` | `engine/event_pipeline.py` `EventContext.of` ← `EventReader.read` | 부르는 쪽 인수 → `result.action.actor` → `None` | `int | None` | **행위의 주체 (선언)** | `ObservedEvent.context` 를 읽는 쪽 |

### 🔴 두 성격이 **반대**다

| | `TimingEvent.actor` | `EventContext.actor` |
| --- | --- | --- |
| 어떻게 생기는가 | **파생** (delta 가 정한다) | **선언** (부르는 쪽이 정한다) |
| 뜻이 일관되는가 | **아니다** (사건군마다) | **그렇다** (늘 행위자를 뜻한다) |
| 언제나 채워지는가 | 이름 붙은 5개 사건군에서 | **action 경로에서만** 자동 |
| 틀릴 수 있는가 | **아니다** (delta 와 늘 맞는다) | **그렇다** (검증이 없다) |

하나는 **정확하지만 뜻이 흔들리고**, 하나는 **뜻이 분명하지만 보장되지
않는다.**

---

## 5. 사건별 비교표 (§4)

"같은 값" 과 "같은 뜻" 을 가른다 (`test_10`).

| Event | `TimingEvent.actor` | `EventContext.actor` | 동일/다름 | 각각의 의미 |
| --- | --- | --- | --- | --- |
| `MonsterSummoned` (행위) | 소환자 | 소환자 | **값 같음 · 계약 다름** | 당사자 / 행위자 — 이 경우 같은 사람 |
| `CardDrawn` (효과로) | 뽑은 사람 | **`None`** | **DIFFERENT** | 당사자 / 선언 안 됨 |
| `LifeChanged` (전투) | **맞은 쪽** | **공격자** | **DIFFERENT** | 당사자 / 행위자 |
| `ZoneMoved` | 도착지 주인 | (행위 경로 없음 → 선언 의존) | **DIFFERENT** | 소유자 / 선언 의존 |
| `CardDestroyed` (= `ZoneMoved(DESTROY)`) | 카드 주인 | 선언 의존 | DIFFERENT | 위와 같다 |
| `CardAddedToHand` (= `RETURN_TO_HAND`) | 카드 주인 | 선언 의존 | DIFFERENT | 위와 같다 |
| `CardDiscarded` (= `DISCARD`) | 카드 주인 | 선언 의존 | DIFFERENT | 위와 같다 |
| `CardBanished` (= `BANISH`) | 카드 주인 | 선언 의존 | DIFFERENT | 위와 같다 |
| `CardReturned` (= `RETURN_TO_DECK`) | 카드 주인 | 선언 의존 | DIFFERENT | 위와 같다 |
| `PhaseChanged` (턴 변화 포함) | **`None`** | **`None`** | 같음 (둘 다 없음) | 규칙이 한 일 |
| `BattleDestruction` | **`None`** (`UNIMPLEMENTED`) | 공격자 | **DIFFERENT** | 사건 이름 없음 / 행위자 |

**`MonsterSummoned` 을 뺀 모든 줄이 DIFFERENT 다.** 그리고 그 한 줄조차
"값이 같을 뿐" 이다 — 선언을 바꾸면 갈라진다 (`test_10` 이 실제로
`actor=THEIRS` 를 넘겨 갈라지는 것을 보였다).

### 다섯 "사건" 은 한 규칙이다 (`test_08`)

`CardDestroyed`·`CardAddedToHand`·`CardDiscarded`·`CardBanished`·
`CardReturned` 는 전부 `ZoneMoved` 의 다른 `OperationKind` 이므로
`timing.actor` 규칙이 **하나**다 (3-F-9 재확인).

---

## 6. Battle 반례 (§6)

실제 듀얼에서 P1 이 P0 을 직접 공격했다 (`test_06`).

| 값 | 결과 |
| --- | --- |
| `action.actor` | **P1** |
| `EventContext.actor` | **P1** ← 행동한 쪽 |
| `TimingEvent.actor` | **P0** ← LP 가 변한 쪽 |
| 피해 대상 | P0 |
| 공격 대상 | (직접 공격 — 몬스터 없음) |

### "상대가 나를 공격했다" 를 판단하려면 어느 값이 필요한가

**`EventContext.actor` 다.** 측정으로 양쪽을 돌려 보았다.

```
context.actor 로 판정  →  OPPONENT   (맞다)
timing.actor 로 판정   →  SELF       (틀리다)
```

반대 방향도 확인했다 — 내가 상대를 공격하면 `timing.actor` 가 `OPPONENT`,
`context.actor` 가 `SELF` 를 준다. **두 경우 모두 `timing` 쪽이 뒤집힌다.**

### 현재 `EVENT_RELATION` 은 어느 값을 읽는가

**어느 쪽도 읽지 않는다.** `_event_relation` 의 본문에 `actor` 가 한 번도
나오지 않는다 (3-F-7 · 3-F-8 이 측정, 여기서 재확인). 이번 Phase 에서
수정하지 않았다.

---

## 7. LifeChanged (§7)

두 개념을 갈랐다.

| 개념 | 뜻 | 현재 어디에 있는가 |
| --- | --- | --- |
| **affected player** | LP 가 실제로 변한 플레이어 | **`TimingEvent.actor`** (= `delta.player`) |
| **cause player** | LP 변화를 발생시킨 플레이어 | **전투에서만** `EventContext.actor` |

### 🔴 효과로 LP 가 바뀌면 **둘 중 어느 것도 원인을 주지 않는다** (`test_11`)

실제 카드(욕망의 항아리)를 해결해 확인했다 — `EffectResult` 에 `.action` 이
없으므로 `context.actor` 가 **기본 `None`** 이다.

```
효과 해결 → deltas = [CardDrawn, CardDrawn]
  timing.actor  = 0   (뽑은 사람 — 당사자)
  context.actor = None  ← 선언되지 않았다
```

`LifeChanged` 자신의 필드는 `player`·`before`·`after` **셋뿐**이고 원인 칸이
없다. **새 field 를 추가하지 않았다.**

### 🟡 그런데 원인이 아주 없는 것은 아니다 — **세 번째 자리** (`test_12`)

효과 해결은 `EffectEvent` 로 기록되고 그 `actor` 가 효과의 컨트롤러다.
`timing_events` 가 그것을 **`EFFECT_RESOLVED` 라는 별개 사건**의 `actor` 로
내놓는다.

```
EffectEvent(actor=0) → timing_events(...) =
    [card_drawn(actor=0), card_drawn(actor=0), effect_resolved(actor=0)]
                                               ^^^^^^^^^^^^^^^^^^^^^^^ 행위자
```

즉 행위자는 **delta 가 만든 사건과 같은 사건이 아니라 형제 사건**에 있다.
`CostPaymentEvent` 도 같은 모양의 `actor` 칸을 갖는다.

> **"actor" 가 담기는 자리가 셋이다** — delta 파생(당사자) · 문맥
> 선언(행위자) · 저널 기록(효과의 행위자, 형제 사건).

---

## 8. ZoneMoved (§8)

다섯 개념 가운데 **넷은 읽을 수 있다** (`test_13`).

| 개념 | 어디에 있는가 |
| --- | --- |
| source player | ○ `delta.source_player` |
| destination player | ○ `delta.destination_player` — **그리고 이것이 `timing.actor` 다** |
| card (무엇이) | ○ `event.instance` |
| operation (무슨 의미로) | ○ `event.operation` |
| **actual action player** | **없다** — `context.actor` 가 채워질 때만 생긴다 |

### "상대가 내 필드로 카드를 옮겼다" vs "카드가 상대 필드로 이동했다"

**delta 만으로는 구분되지 않는다** (`test_07`). 두 경우의 delta 가 같고,
`timing.actor` 는 둘 다 도착지 주인을 준다.

측정 사례 — 내 필드의 카드를 상대 필드로:

```
delta.source_player      = 0 (나)
delta.destination_player = 1 (상대)
timing.actor             = 1 (상대)     ← 움직인 쪽은 나인데
```

지금 이 사건을 만드는 **행위 경로가 없다** (`ZoneMoved` 를 내놓는
`PlayerAction` 이 없다), 그래서 `context.actor` 는 전적으로 선언에 달려 있다.

---

## 9. 실제 consumer 목록 (§9)

| Consumer | 읽는 actor | 기대 의미 | 실제 의미 | 안전성 |
| --- | --- | --- | --- | --- |
| `TimingEvent.from_delta` | (생성) | — | delta 당사자 | — |
| `TimingEvent.from_journal_event` | `event.actor` | 행위자 | **행위자** | 안전 |
| `EventContext.of` ← `EventReader.read` | 인수 / `action.actor` | 행위자 | 행위자 **또는 `None`** | 조건부 |
| `EventReader.read_deltas` | 인수 | 행위자 | **검증 없음** | 위험 (선언 책임) |
| `ObservedEvent.actor` | `timing.actor` | ? | **당사자** | 🔴 **이름이 위험하다** |
| `ObservedEvent.context.actor` | `context.actor` | 행위자 | 행위자/`None` | 안전 |
| `_event_relation` | **읽지 않는다** | — | — | 지금은 없음 |
| `TriggerRegistry` · `trigger.py` 나머지 | **읽지 않는다** | — | — | 없음 |
| `activation.py` · `activation_timing.py` | **읽지 않는다** | — | — | 없음 |
| `timing.py` · `trigger_order.py` · `trigger_chain.py` (dormant) | **읽지 않는다** | — | — | 없음 |
| `duel.py` · `legal_actions` | **읽지 않는다** | — | — | 없음 |
| `agent/` | **읽지 않는다** | — | — | 없음 |

### 🟢 production 에서 **아무도 읽지 않는다** (`test_18`)

9개 루트의 모든 `.py` 를 읽어 확인했다. `engine/event_pipeline.py` 와
`engine/trigger.py` **밖에서** 사건의 `actor` 를 읽는 자리가 **하나도 없다**
(다른 파일의 `ObservedEvent` 언급은 전부 **docstring** 이다). 그리고
`event_pipeline` 자체가 여전히 **production importer 0** 이다.

- **`TimingEvent.actor` 를 `EventRelation` 에 넘기는가** → 아니다
- **`EventContext.actor` 를 `EventRelation` 에 넘기는가** → 아니다
- **둘을 혼동하는 코드가 있는가** → **지금은 없다**
- **dormant code 도 같은 문제가 있는가** → dormant 쪽도 읽지 않는다

### 🔴 검증되지 않는다 (`test_19`)

소환한 사람이 P0 인데 `actor=THEIRS` 로 선언해도 **거절되지 않는다.**
`EventContext.__post_init__` 은 범위(0/1/None)만 보고 delta 를 보지 않으며,
`read_deltas` 도 delta 와 비교하지 않는다. 즉 `context.actor` 의 정확성은
**부르는 쪽의 책임**이고, 그 책임이 **어디에도 적혀 있지 않다.**

---

## 10. EventRelation 과의 관계 (§10)

3-F-8 의 결론(최소 입력)을 **뒤집지 않는다.** 질문은 하나다 — 그 최소
입력의 player relation 을 **어느 actor 로 만드는가.**

### 답: **`EventContext.actor`** (`test_14`)

여덟 사례를 실제로 돌렸다.

| # | 사례 | `timing.actor` 로 판정 | `context.actor` 로 판정 |
| --- | --- | --- | --- |
| 1 | 내가 소환 | SELF ○ | SELF ○ |
| 2 | 상대가 소환 | OPPONENT ○ | OPPONENT ○ |
| 3 | 내가 드로우 (효과) | SELF ○ | **UNKNOWN** |
| 4 | 상대가 드로우 (효과) | OPPONENT ○ | **UNKNOWN** |
| 5 | **상대가 나에게 데미지** | 🔴 **SELF ✗** | **OPPONENT ○** |
| 6 | **내가 상대에게 데미지** | 🔴 **OPPONENT ✗** | **SELF ○** |
| 7 | 상대가 내 카드를 이동 | 선언 의존 | 선언 의존 |
| 8 | 내 카드가 상대 필드로 | 🔴 OPPONENT (뜻이 다르다) | 선언 의존 |

`context.actor` 는 **틀리지 않는다.** 대신 **모를 때가 있다**(3·4) —
그리고 그것이 옳다 (`test_15`): 모르는 것을 `UNKNOWN` 으로 적는 쪽이
잘못된 `SELF` 보다 낫다. 이 프로젝트가 모든 자리에서 지켜 온 규칙이다.

`None` 을 "상대가 아니다" 로 접지 않는다는 3-F-8 의 설계 요구도 그대로
유지된다 (`test_16`).

---

## 11. actor naming risk (§11)

§11 의 세 갈래 가운데 **B** 다.

| 갈래 | 해당하는가 |
| --- | --- |
| A. 이름은 같지만 의미가 명확히 구분된다 → 문서화만 필요 | **아니다** — 의미가 구분되어 있지 **않다** |
| **B. 이름 때문에 consumer 가 잘못 해석할 가능성이 높다** → semantic naming risk | **그렇다** |
| C. 실제로 잘못된 actor 를 읽는 production consumer 가 존재한다 → structural risk | **아니다** — 읽는 자리가 없다 (§9) |

### 🔴 왜 B 인가 — 두 가지가 겹친다

**① 두 docstring 이 똑같은 것을 약속한다** (`test_03`).

```
TimingEvent.actor   : "이 사건을 일으킨 플레이어. 알 수 없으면 None."
EventContext.actor  : "이 변화를 일으킨 행위의 주체. 규칙이 스스로 한 일이면 None."
```

둘 다 **"일으킨"** 이다. 그런데 하나는 당사자이고 하나는 행위자다. 어느
설명도 "당사자" 나 "대상" 이라는 말을 쓰지 않는다. **설명만 읽은 consumer 는
둘을 바꿔 써도 된다고 믿게 된다.**

그리고 `TimingEvent.actor` 의 설명은 **불명확한 것이 아니라 사실과 다르다** —
3-F-9 가 `LifeChanged`·`ZoneMoved` 에서 그것이 행위자가 아님을 측정했다.

**② 짧은 이름이 덜 안전한 값을 가리킨다** (`test_17`).

`ObservedEvent.actor` 는 **`timing` 쪽**을 돌려준다. 그래서
`event.actor` 라고 쓰면 **당사자**가 오고, 행위자를 받으려면
`event.context.actor` 라고 **더 길게** 써야 한다. 자연스러운 쪽이 위험한
쪽이다.

**이번 Phase 에서 이름을 바꾸지 않았다.**

---

## 12. 새 field 필요성 검토 (§12)

후보 다섯을 기존 구조와 맞춰 봤다 (`test_22`). **새 field 를 만들지
않았다.**

| 후보 | 정말 필요한가 | 근거 |
| --- | --- | --- |
| `cause_player` | **필요하지 않다** | 전투는 `EventContext.actor` 가 준다. 효과는 `EffectEvent.actor` 가 준다 (형제 사건). **빠진 것은 칸이 아니라 배선**이다 |
| `affected_player` | **필요하지 않다** | `TimingEvent.actor` 가 **이미 그것이다** — 이름만 그렇게 읽히지 않는다 |
| `destination_player` | **필요하지 않다** | `ZoneMoved` 에 **이미 있다** |
| `source_player` | **필요하지 않다** | `ZoneMoved` 에 **이미 있다** |
| `controller` | **필요하지 않다** | 후보 쪽 값이고 3-F-8 이 이미 최소 입력으로 확정했다 |

### 결론: **필요하지 않다**

다섯 후보 가운데 **하나도 새로 만들 필요가 없다.** 필요한 것은 칸이 아니라
둘(또는 셋)의 **역할을 적어 두고 어느 것을 읽을지 정하는 일**이다.

단 하나 유보 — **효과 경로에서 `context.actor` 를 채우는 배선**이 없다.
그것은 새 field 가 아니라 **호출 규약**의 문제이고, 다음 Phase 의 일이다.

---

## 13. hidden-info (§13)

`test_20` — 두 actor 모두 `None`·0·1 뿐이고, 상대의 패·덱은 그대로 가려져
있다 (`concealed=True` · `cards == ()`). 뒷면 카드 신원도 쓰지 않았다.
**관측 경계를 변경하지 않았다.**

---

## 14. state_hash / RNG / AI 영향 (§14)

| 확인 | 결과 |
| --- | --- |
| `state_hash` | **불변** (`test_21` — 세 번 반복) |
| `canonical_state` | 변경 없음 |
| RNG | **불변** |
| clone 동작 | 변경 없음 |
| Search ranking | **digest 동일** `30fa3597…` (6판 611결정) |
| Evaluation / AI | 변경 없음 |

---

## 15. 테스트 결과

### 새 테스트 — `tests/test_actor_role_separation_audit.py` 23건

| # | 이름 | §16 항목 |
| --- | --- | --- |
| 01 | the timing actor is derived from the delta | 1 |
| 02 | the context actor is declared by the caller | 2 |
| 03 | 🔴 **both docstrings promise the same thing** | — (§11) |
| 04 | a summon makes the two actors agree | 3 |
| 05 | 🔴 an effect draw leaves the context actor empty | 4 |
| 06 | 🔴 **a battle makes the two actors disagree** | 5 · 13 |
| 07 | a card moved to the opponent field has no action at all | 6 · 17 |
| 08 | destroy banish discard and return share the timing rule | 7~11 |
| 09 | phase changed has neither actor | 12 |
| 10 | the two actors can agree by value but differ by meaning | 3 |
| 11 | 🔴 neither actor is the cause of a life change by effect | 16 |
| 12 | 🟡 **the effect agent lives on a sibling event** | 16 |
| 13 | source and destination are both readable but the agent is not | 17 |
| 14 | **the relation needs the context actor not the timing actor** | 14 · 15 |
| 15 | the relation is unknown when the context actor is absent | 14 · 15 |
| 16 | an absent actor must not be read as opponent | 14 · 15 |
| 17 | 🔴 the observed event exposes the timing actor under the bare name | — (§11) |
| 18 | 🟢 **no production consumer reads either actor** | 18 |
| 19 | 🔴 nothing checks the declared actor against the delta | 18 |
| 20 | reading both actors touches no hidden information | 19 |
| 21 | the state and the rng do not move | 20 · 21 |
| 22 | no new field was added | — (§12) |
| 23 | this phase changed nothing | 22 |

```
$ python3 -m pytest tests/test_actor_role_separation_audit.py -p no:randomly -q
23 passed in 9.98s
```

### 고의 위반 검증 — 6건, 전부 잡았다

| # | 위반 | 잡은 테스트 |
| --- | --- | --- |
| 1 | `ObservedEvent.actor` 가 context 쪽을 돌려준다 | `test_15` · `test_17` · `test_19` + 4건 |
| 2 | `EventContext` 가 선언된 actor 를 delta 와 검증한다 | `test_19` · `test_20` · `test_21` + 3건 |
| 3 | 두 docstring 을 서로 다르게 고친다 | `test_03` |
| 4 | `LifeChanged` 에 `cause_player` 를 더한다 | `test_11` · `test_22` |
| 5 | `EventContext` 에 여섯째 칸을 더한다 | `test_22` |
| 6 | `duel.py` 가 `context.actor` 를 읽는다 | `test_18` |

3번이 **한 테스트만** 잡았다는 것이 이 Phase 의 요점을 보여 준다 —
docstring 을 고치는 것이 **유일하게 필요한 변경**이고, 그것을 하면
`test_03` 이 "지금은 같다" 를 더 이상 주장하지 않게 된다. (그 테스트는
현재 상태를 고정한 것이므로, 문서를 고치는 Phase 에서 함께 갱신해야 한다 —
그 사실을 다음 Phase 후보에 적었다.)

주입 파일 4개(`trigger.py` · `event_pipeline.py` · `effect/delta.py` ·
`duel.py`)는 전부 백업에서 복원하고 md5 로 확인했다 (모두 `OK`).

### 🟡 측정 하나가 처음 틀렸다 — production 이 아니라 테스트를 고쳤다

`test_06` 에서 "LP 가 줄었다" 를 확인하려고 `before` 를 읽었는데, 그 값을
**전투를 적용한 뒤에** 읽고 있었다 (`battle_by` 가 내부에서 이미 실행한다).
그래서 `6100 < 6100` 으로 실패했다.

헬퍼가 **적용 전에** 맞는 쪽 LP 를 읽어 함께 돌려주도록 고쳤고, 그 이유를
헬퍼 주석에 적어 두었다. production 은 고치지 않았다.

### 전체 회귀

```
$ python3 -m pytest tests/test_actor_role_separation_audit.py -p no:randomly -q
23 passed in 9.98s

$ python3 -m pytest -p no:randomly -q
4299 passed, 4 skipped in 372.21s (0:06:12)
```

| | 통과 | skip |
| --- | --- | --- |
| Phase 3-F-9 직후 (baseline) | 4,276 | 4 |
| Phase 3-F-10 (이번) | **4,299** | 4 |
| 차이 | **+23** | 0 |

**+23 이 이번에 더한 시험 수와 정확히 같다.** skip 4건은 baseline 과 동일한
기존 skip 이다.

### 기존 테스트 처리

**수정 0건 · 삭제 0건 · skip 추가 0건 · assertion 약화 0건.**
production diff 가 0 이므로 기존 계약이 깨질 자리가 없었다.

기존 `tests/engine/test_event_pipeline.py` 가 소환에서 두 actor 가 같다고
단정하는 자리가 있는데(`event.actor == MINE` · `event.context.actor == MINE`),
**그것은 맞는 단정이다** — 소환에서는 둘이 같은 사람이다. 그 테스트는
"언제나 같다" 를 주장하지 않으므로 고칠 이유가 없다.

---

## 16. production diff

```
$ git diff --stat -- engine agent app core analysis rules rulings sources scripts
(출력 없음)
```

**0.** 추가한 것은 테스트 하나와 이 보고서뿐이다.

---

## 17. 최종 판정

### **B. ACTOR_ROLES_NEED_DOCUMENTATION**

> 실제 동작은 안전하지만 semantic contract 가 불명확하다.

판정 기준("각 actor 가 무엇을 의미하는지 명확하고, 그 의미에 맞는 consumer 가
올바른 값을 사용하고 있는가")에 둘로 답한다.

| 질문 | 답 |
| --- | --- |
| 각 actor 의 의미가 **명확한가** | 🔴 **아니다** — 두 docstring 이 똑같이 "일으킨" 이라고 적혀 있고, `TimingEvent.actor` 쪽은 **사실과 다르다** |
| 그 의미에 맞는 consumer 가 **올바른 값을 쓰는가** | 🟢 **지금은 그렇다** — production 에서 **아무도 읽지 않는다** |

### 왜 A 가 아닌가

A 는 "의미가 서로 다르지만 **현재 구조에서 명확히 구분 가능하다**" 다.
구분은 **가능하지만**(두 값이 모두 노출되어 있다) **명확하지 않다** —
문서가 둘을 구분하지 않고, 짧은 이름(`event.actor`)이 덜 안전한 값을
가리킨다. A 로 적으면 "지금 그대로 두어도 된다" 로 읽히는데, `test_03` 이
고정한 사실은 그 반대다.

### 왜 C 가 아닌가

C 는 "실제 production consumer 가 잘못된 actor 를 읽고 있다" 다.
9개 루트를 전부 읽어 확인한 결과 **그런 consumer 가 없다** (`test_18`) —
`event_pipeline` 은 production importer 0 이고, `duel.py` 도 dormant 계층도
읽지 않는다. 그러므로 **지금 고쳐야 할 코드가 없다.** C 로 적으면 있지도
않은 오용을 수리하러 가게 된다.

### 왜 D 가 아닌가

D 는 "두 actor 만으로 필요한 관계를 표현할 수 없다" 다. **표현할 수 있다** —
`context.actor` 가 전투에서 행위자를 정확히 주고(`test_06`), 효과에서는
`EffectEvent.actor` 가 그 값을 들고 있다(`test_12`). 빠진 것은 **칸이 아니라
배선**이고, 후보 다섯 가운데 새로 만들 것이 하나도 없다(`test_22`).
D 로 적으면 필요 없는 field 를 더하는 쪽으로 가게 된다.

### 왜 E 가 아닌가

예상보다 큰 구조 문제는 없었다. 오히려 **이미 있는 것이 더 많았다** —
행위자는 두 곳(`EventContext.actor` · `EffectEvent.actor`)에 있고,
`ZoneMoved` 의 네 개념도 다 읽을 수 있다.

### 🟡 B 가 "사소하다" 는 뜻이 아니다

이 B 는 주석을 다듬는 일이 아니다. 고쳐야 할 것이 셋이다.

1. **거짓 문장을 고치는 일** — `TimingEvent.actor` 의 "일으킨" 은 사실과
   다르다.
2. **어느 값을 읽을지 정하는 일** — §10 이 `context.actor` 를 가리켰고,
   그 결정이 적히지 않으면 다음 Phase 가 자연스러운 이름(`event.actor`)을
   집어 **뒤집힌 판정**을 만든다.
3. **선언의 책임을 적는 일** — `context.actor` 는 검증되지 않으므로
   (`test_19`) 누가 무엇을 보장해야 하는지가 계약에 있어야 한다.

---

## 18. 다음 Phase 후보 (1개)

**Phase 3-F-11 — 두 actor 의 semantic contract 를 문서로 고정 (최소 변경,
production 주석만)**

이 Phase 가 측정한 계약 두 문장을 **코드에 적는 것**만 한다. 동작을 바꾸지
않으므로 freeze 와 충돌하지 않지만, **production 파일을 건드리는 첫
변경**이므로 범위를 좁게 가져가야 한다.

그 Phase 가 답해야 할 것:

1. 두 docstring 을 어떻게 적을 것인가 — "당사자" / "행위자" 라는 말을
   쓰는 것이 이 저장소의 다른 어휘(`owner`·`controller`·`actor`,
   ADR §22)와 충돌하지 않는지 먼저 확인한다.
2. `ObservedEvent.actor` 를 그대로 둘 것인가 — 짧은 이름이 당사자를
   가리키는 것이 측정된 위험이다(`test_17`). 이름을 바꾸면 기존 테스트
   몇 곳이 걸리는지 센다 (`tests/engine/test_event_pipeline.py` 가 쓴다).
3. `context.actor` 의 **선언 책임**을 어디에 적을 것인가 —
   `EventReader.read` 의 docstring 이 "부르는 쪽이 보장한다" 를 말해야
   한다. 효과 경로에서 비는 것도 함께 적는다.
4. 이 Phase 의 `test_03` 은 **"지금 두 설명이 같다"** 를 고정한 것이므로,
   문서를 고치면 **그 테스트도 함께 갱신해야 한다.** 그때 "왜 기존 테스트가
   낡은 가정을 갖게 되었는지" 를 보고서에 적는다 — 테스트를 고쳐 통과시키는
   것이 아니라, **고친 사실을 측정으로 다시 고정**하는 쪽으로.

**이 Phase 는 그 작업을 하지 않았다. 다음 Phase 는 임의로 진행하지 않는다.**
