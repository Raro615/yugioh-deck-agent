# Phase 3-F-13 — `EventReader.read()` actor 입력 경계 / Semantic Responsibility 감사

## 1. Phase · Base · 실제 HEAD

| 항목 | 값 |
| --- | --- |
| Phase | 3-F-13 — `read()` actor 입력 경계 · semantic responsibility |
| 모드 | **AUDIT-ONLY** — production diff **0** (§10 조건 3 이 깨진다, §12 참조) |
| **실제 HEAD (측정)** | `b3f2c0e Phase 3-F-12: document actor provenance audit` |
| Base (3-F-12) | `3a10656` (작업) · `b3f2c0e` (보고서) — **둘 다 실존** (`git cat-file -t`) |
| 3-F-12 최종 판정 | **C. ACTOR_PROVENANCE_GAP** |
| branch | `claude/pensive-goodall-te1egy` |
| baseline 테스트 | 4,339 passed / 4 skipped |
| 신규 테스트 | `tests/test_event_reader_actor_input_boundary.py` — **23건** |

> ⚠️ **글자가 두 벌이다.** §2 의 설계 이름과 §14 의 판정 글자가 어긋난다.
> §14 의 **B** (`READ_ACTOR_SHOULD_DERIVE_FROM_RESULT`) 가 §2 의 **설계 A**
> (result 가 준다) 이고, §14 의 **C** (`READ_ACTOR_CALLER_MUST_DECLARE`) 가
> §2 의 **설계 B** (호출자가 준다) 다. 이 문서는 설계를 §2 의 이름으로,
> 판정만 §14 의 글자로 적는다.

---

## 2. 현재 `read()` signature (§1 A · B)

```python
EventReader.read       (self, result, actor: int | None = None) -> tuple[ObservedEvent, ...]
EventReader.read_deltas(self, deltas, actor: int | None = None) -> tuple[ObservedEvent, ...]
EventPipeline.observe  (self, result, actor: int | None = None) -> tuple[ObservedEvent, ...]
EventPipeline.collect  (self, result, actor: int | None = None) -> tuple[EventObservation, ...]
EventPipeline.collect_events(self, events)                      # ← actor 를 받지 않는다
```

actor 를 받는 자리는 **넷**이고 **기본값이 전부 `None`** 이다.
`collect_events` 는 **받지 않는다** — 이미 읽어 둔 사건을 받으므로 그때는 actor
가 이미 정해져 있다. 즉 **입력 경계가 한 군데로 좁혀져 있다** (`test_01`).

### 본문 (§1 C)

```python
deltas = getattr(result, 'deltas', None)
if deltas is None:
    raise TypeError(f'변화(deltas)를 들고 있는 결과가 필요합니다: {type(result).__name__}')
if actor is None:
    actor = getattr(getattr(result, 'action', None), 'actor', None)
return self.read_deltas(deltas, actor=actor)
```

actor 가 가는 곳은 **`EventContext.of` 하나**다. delta 와 비교되지 않고,
검증되지 않고, `_timing_for` 에는 아예 전달되지 않는다 (`test_02`).

**즉 현재 API 는 설계 A 와 설계 B 의 혼합이다** — 설계 A(파생)가 기본이고
설계 B(선언)가 그것을 덮어쓴다.

---

## 3. 호출 graph (§1 D · E)

```
[production]
EventPipeline.observe(result, actor=…)
    └─ self._reader.read(result, actor=actor)      ← 유일한 production 호출
                                                     (같은 모듈 안이다)
외부 production 호출자:  0개
```

| 묻는 것 | 답 |
| --- | --- |
| 외부 production 호출자 | **0개** (`test_03`) |
| 테스트 호출 | **72곳** (이 감사 파일 제외) |
| 그중 **actor 를 생략** | **36곳** |
| 그중 **actor 를 선언** | **36곳** |
| `actor=None` 을 **명시**한 곳 | **1곳** — 3-F-12 가 "생략과 구별되지 않는다" 를 보이려고 쓴 자리 |

🔴 **절반이 선언하지 않는다.** 지금 API 는 "선언하지 않아도 되는 것" 으로
**실제로 쓰이고 있다** (`test_04`). 이 숫자가 §10 조건 3 을 깨뜨린다 (§12).

> 호출 자리를 **AST 로** 셌다. 3-F-8 에서 정규식이 자기 소스를 세어 숫자가 둘
> 늘었고, 이 Phase 에서도 **이 감사 파일 자신을 세지 않도록** 따로 뺐다 —
> 측정 도구가 증거에 섞이면 "기존 호출자가 어떻게 쓰고 있나" 의 답이 오염된다.

---

## 4. `read()` 는 actor 를 추론할 재료가 없다 (§1 F · G)

| 묻는 것 | 답 |
| --- | --- |
| `EventReader` 가 들고 있는 것 | `__slots__ == ("_view",)` — **`GameStateView` 하나** |
| 코드에 실행기가 있는가 | **없다** — `ActionExecutor` · `TurnProgressor` · `EffectExecutor` · `Chain` · `PriorityState` · `Duel` 전부 **코드에 0회** |
| import 하는 것 | 값 타입(`StateDelta` · `TimingEvent` …) 과 `GameStateView` 뿐 |
| 관측이 actor 를 드러내는가 | `engine/game_state_view.py` 에 `actor` 라는 말이 **0회** |

→ **§1 G 의 답은 "아니다".** `read()` 가 추론해야 하는 구조가 아니다. 추론하려면
모듈이 **일부러 거부하고 있는** 의존(실행기)을 들여와야 하고, 그러면 모듈
설명이 적어 둔 금지 — "이 파일이 실행기를 알면 실행기가 사건을 만들어야 한다는
뜻이 된다" — 를 깨게 된다 (`test_05`).

> 🔴 **여기서 내가 또 당했다.** 처음에는 `"ActionExecutor" not in source` 로
> 쟀는데, 모듈 설명에 "실행기(`ActionExecutor` · `TurnProgressor`)는 이 파일을
> **모른다**" 라는 문장이 있어서 걸렸다. 설명이 그 이름을 **부정하려고** 적고
> 있는데 존재로 센 것이다. 3-F-7 이 같은 실수를 하고 교훈까지 적어 두었는데
> 반복했다. 문자열 리터럴을 지운 AST(`code_only`)와 import 목록으로 다시 쟀다.

---

## 5. 사건별 actor 책임 (§4)

§4 가 지목한 10개 사건 중 **다섯은 클래스가 아니다** — 전부 `ZoneMoved` 이고
`OperationKind` 로만 갈린다 (3-F-9 가 센 그대로이고, 이번에도 전수로 다시 쟀다).

| Event | 실제 표현 | `TimingEvent.actor` | `EventContext.actor` | actor source | `read()`가 알 수 있나 | 책임자 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 `MonsterSummoned` | 클래스 | `delta.player` = **소환한 사람** | 행위자 | delta **또는** action | 🟢 **delta 가 담는다** (`player` ≠ `owner`) | 파생 가능 |
| 2 `CardDrawn` | 클래스 | `delta.player` = **뽑은 사람** | 행위자 | action / 호출자 | 🔴 **아니다** — 남을 뽑게 할 수 있다 | **호출자** |
| 3 `LifeChanged` | 클래스 | `delta.player` = **LP 가 바뀐 쪽** | 행위자 | action / 호출자 | 🔴 **아니다** | **호출자** |
| 4 `ZoneMoved` | 클래스 | `delta.destination_player` = **도착지 주인** | 행위자 | action / 호출자 | 🔴 **아니다** | **호출자** |
| 5 `PhaseChanged` | 클래스 | **`None`** (계약) | **`None`** | — | 🟢 없는 것이 맞다 | **아무도** |
| 6 `CardDestroyed` | **`ZoneMoved(destroy)`** | 도착지 주인 = **주인** | 행위자 | 호출자 | 🔴 **아니다** — 가해자 칸이 없다 | **호출자** |
| 7 `CardAddedToHand` | **`ZoneMoved(return_to_hand)`** | 주인 | 행위자 | 호출자 | 🔴 아니다 | **호출자** |
| 8 `CardDiscarded` | **`ZoneMoved(discard)`** | 주인 | 행위자 | 호출자 | 🔴 아니다 | **호출자** |
| 9 `CardBanished` | **`ZoneMoved(banish)`** | 주인 | 행위자 | 호출자 | 🔴 아니다 | **호출자** |
| 10 `CardReturned` | **`ZoneMoved(return_to_deck)`** | 주인 | 행위자 | 호출자 | 🔴 아니다 | **호출자** |

### 🔴 핵심: delta 가 행위자를 담을 때도 있고 안 담을 때도 있다

- `MonsterSummoned` 은 `player`(소환한 사람) 와 `owner`(카드 주인) 를 **둘 다**
  들고 있고, `from_delta` 는 `player` 를 고른다. 남의 묘지에서 내가 특수
  소환하면 `player=0 · owner=1` 로 **갈린다** (`test_12`).
- 그런데 `CardDrawn` · `LifeChanged` 는 사람 칸이 **하나뿐**이고 그것은
  **귀속자**다. `ZoneMoved` 는 둘이지만 **둘 다 주인**이다.

→ **같은 규칙으로 읽으면 어떤 사건에서는 행위자를, 어떤 사건에서는 피해자를
집는다.** `read()` 에는 둘을 가릴 근거가 없다. **그래서 "delta 에서 파생" 은
계약이 될 수 없다** — §3 이 금지한 `context.actor = delta.player` 가 왜
금지인지의 구조적 이유다.

### 6 ~ 10 — 가해자를 담는 칸이 없다

다섯 사건 모두 출발지·도착지 주인이 **같은 사람**이다 (내 몬스터가 내 묘지로
간다). `ZoneMoved` 의 사람 칸은 둘뿐이고 **둘 다 카드 주인**이다. "상대가 내
카드를 파괴했다" 를 **delta 만 보고는 알 수 없다** (`test_11`).

> 🟡 그 다섯 사건만으로는 귀속자가 `destination_player` 인지 `source_player`
> 인지 **가려지지 않는다** (둘이 같으니까). 실제로 이 Phase 의 고의 위반 7번
> (`actor=delta.source_player` 로 바꾸기) 이 처음에 `test_11` 에 **걸리지
> 않았다.** 그래서 컨트롤이 넘어가는 이동(`source_player=0 ·
> destination_player=1`)을 같은 테스트에 더해 **도착지 주인**임을 고정했다.

---

## 6. 🔴 결정적 실제 카드 둘

### 강욕의 보은 `5915629` — 행위자가 delta 어디에도 없다

P0 이 발동하면 **P1 이 2장 드로우한다.**

| 항목 | 값 |
| --- | --- |
| result | `EffectResult` — **`action` 을 들고 있지 않다** |
| delta | `CardDrawn` × 2, **모든 사람 칸이 `1`** (`player` · `from_player` · `to_player`) |
| `timing.actor` | `1` — 귀속자. **맞는 값이다** |
| `context.actor` (선언 없음) | **`None`** |
| `context.actor` (`actor=0` 선언) | `0` |
| `EffectEvent.actor` | `0` — journal 은 알고 있었다. `read()` 가 **보지 않는다** (3-F-12) |

→ **설계 A 로는 이 사건의 행위자를 영원히 알 수 없다.** 행위자 `0` 을 아는 곳은
셋뿐이다: `ResolutionContext.controller` · `EffectEvent.actor` · **호출자**
(`test_09`).

### 자비의 비 `66719324` — 두 actor 의 **개수**가 다르다

P0 이 발동하면 **양쪽이 1000 회복한다.**

| 항목 | 값 |
| --- | --- |
| delta | `LifeChanged(player=0)` · `LifeChanged(player=1)` |
| `timing.actor` | `0` 과 `1` — **delta 마다 하나** |
| `context.actor` | `0` **하나** — 두 사건이 **같은 값을 공유** |
| `context.sequence` | `0` · `1` |

→ 두 actor 는 값만 다른 것이 아니라 **cardinality 가 다르다.**

| | `TimingEvent.actor` | `EventContext.actor` |
| --- | --- | --- |
| 단위 | **delta 마다** | **묶음(invocation)마다** |
| 성격 | 파생 | 선언 |

그래서 `EventContext.at(index)` 가 같은 actor 를 옮겨 적는 설계가 **맞다.**
사건마다 다른 행위자를 넣을 자리는 **있어서는 안 된다** — 한 번의 행위가 여러
사람의 상태를 바꾸는 것이 정상이기 때문이다 (`test_10`).

---

## 7. 결과 타입별 경계 (§5)

| result | ① action? | ② action.actor? | ③ event actor 필요? | ④ 어디서 얻나 | ⑤ 없어도 정상? | ⑥ `read()` 책임? | ⑦ 호출자 책임? |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `ActionExecution` | ○ | ○ **필수 int** | ○ | `action.actor` | ✗ | 🟢 **파생 안전** (행위의 정의) | ○ (덮어쓸 수 있다) |
| `ActivationResult` | ○ | ○ **필수 int** | ○ | `action.actor` | ✗ | 🟢 **파생 안전** | ○ |
| `EffectEvent` | ✗ | — | ○ | `actor` (= `controller`) | ✗ | 🟡 **개념이 다르다** | **○** |
| `CostPaymentEvent` | ✗ | — | ○ | `actor` (= `payer`) | ✗ | 🟡 **개념이 다르다** | **○** |
| `EffectResult` | ✗ | — | ○ | **아무 데도 없다** | ✗ | ✗ **불가** | **○ 유일** |
| `CostPaymentResult` | ✗ | — | ○ | **아무 데도 없다** | ✗ | ✗ **불가** | **○ 유일** |
| `ProgressionResult` | ✗ | — | **✗** | — | **○ 의도됨** | ✗ | ✗ |

### 설계 A 의 최대 사정거리 = **4/7**, 안전한 것은 **2/7**

- `action` 을 들고 있는 **둘**은 파생이 **정의상 안전**하다 — `PlayerAction` 은
  "누가 하는 행위인가" 가 **정의**이고, `actor` 는 필수 `int` 로 0/1 검증을
  거친다. 행위의 actor 를 행위에서 읽는 것은 추론이 아니다.
- journal **둘**은 **공짜가 아니다.** `EffectEvent.actor = context.controller`,
  `CostPaymentEvent.actor = context.payer`. 두 문맥에 `actor` 칸이 **없고**
  `controller`/`payer` 만 있다 — **개념이 다르다는 구조적 증거**다. 지금은 값이
  같지만(컨트롤 이동이 없다) 뜻이 다르고, 사용자의 기준 — **추측해서 구조화하지
  않는다** — 에 따라 이것을 파생 근거로 세지 않는다 (`test_16`).
- 나머지 **셋**은 actor 가 **객체에 없다.** `ProgressionResult` 는 없는 것이
  맞고, 둘은 호출자만 답할 수 있다 (`test_15`).

---

## 8. `None` 경계를 세 가지로 가른다 (§6)

| 분류 | 사례 | 측정 | 코드에 구별되나 |
| --- | --- | --- | --- |
| **A. INTENTIONAL_NONE** | 페이즈 전환 | `timing.actor is None` **그리고** `context.actor is None` | 🔴 **아니다** |
| **B. OMITTED_INPUT** | 강욕의 보은을 선언 없이 읽기 | `context.actor is None` — **그런데 행위자는 P0 으로 존재한다** | 🔴 **아니다** |
| **C. UNKNOWN** | `CostPaymentResult` | actor 칸도 없고 `read()` 설명에 **예시로도 없다** | 🔴 **아니다** |

### 🔴 B 를 A 로 처리하는 것이 지금의 기본 동작이다

§6 이 "B 를 A 로 처리하면 안 된다" 고 못박았다. 그런데 측정 결과 **세 `None`
이 완전히 같은 값**이고, `EventContext` 에는 `actor_source` · `provenance` ·
`note` 칸이 **하나도 없다** (`test_17` · `test_18` · `test_19`).

### 🔴 PhaseChanged 의 `None` 은 데이터 부재가 아니다

`PhaseChanged` 는 `from_player` · `to_player` 를 **들고 있다.** 그런데
`from_delta` 가 actor 를 **일부러 넣지 않는다.** 즉 `INTENTIONAL_NONE` 은
**계약이 정한 것**이고, 바로 그래서 "없는 것" 과 "안 넣은 것" 이 코드에서 같은
모양이 된다 (`test_13`).

> 3-F-12 는 `ProgressionResult`·`TransitionPlan`·`PhaseTransition` **결과 쪽**에
> 사람 칸이 없다고 적었다. 그것은 맞다. 이번에 **delta 쪽**에는 있다는 것을
> 더 쟀다 — 모순이 아니라 층이 다르다.

### "구조적 문제인가 API 설계 선택인가" (§6 의 질문)

**설계 선택이지만 표현력이 부족한 선택이다.** `if actor is None:` 하나가
"안 넘겼다" 와 "`None` 을 넘겼다" 를 합쳐 버린다. 보초값(sentinel) 하나로 가를
수 있고 — 고의 위반 2번이 실제로 그렇게 해 보았다 — 지금 그 자리가 비어 있다.
구조를 바꿀 필요는 없다 (`test_08`).

---

## 9. Battle 사례 (§7)

P1 이 P0 을 공격한다. LP 8000 → **6100**.

| 항목 | 값 |
| --- | --- |
| delta | `LifeChanged(player=0)` **하나뿐** |
| delta 의 모든 사람 칸 | `{0}` — **맞은 쪽만** |
| `action.actor` | `1` |
| `timing.actor` | `0` (귀속) |
| `context.actor` | `1` (행위) |

### §7 의 두 질문에 답한다

**"`read()` 가 스스로 P1 을 읽어야 하는가?"**
읽어도 **틀리지 않는다** — `action.actor` 는 행위의 정의다. 다만 그것은
**`action` 을 들고 있는 결과에서만** 가능하고, 7개 중 **둘**뿐이다.

**"호출자가 P1 을 책임져야 하는가?"**
나머지 **다섯**에서는 호출자밖에 답할 수 없다. 강욕의 보은이 그 증거다 —
행위자가 delta 에도, 결과에도 없다.

→ **책임은 호출자에게 있고, 파생은 편의다.** 편의가 책임을 대신할 수 없는
이유는 사정거리가 2/7 이기 때문이다 (`test_14`).

---

## 10. 세 설계 비교 (§2)

| 기준 | 설계 A — result 가 준다 | 설계 B — 호출자가 준다 | 설계 C — 문맥이 정한다 |
| --- | --- | --- | --- |
| semantic 책임이 명확한가 | 🟡 **타입마다 다르다** — action 이면 정의, journal 이면 개념 치환, 나머지는 답 없음 | 🟢 **한 곳** — 호출자 | 🔴 문맥을 **만든 쪽**으로 미뤄진다 (결국 호출자인데 한 겹 늘었다) |
| 잘못 읽을 가능성 | 🔴 **있다** — delta 가 행위자를 담을 때와 안 담을 때를 가릴 근거가 없다 | 🟡 **있다** (거짓 선언 가능) — 그러나 **책임자가 명시된다** | 🔴 있다 + turn·phase 까지 틀릴 수 있다 |
| 기존 구조와 충돌 | 🟡 journal 의 `controller`/`payer` 를 행위자로 바꿔 쓰게 된다 | 🟢 **충돌 없다** — 지금 이미 선언이 파생을 이긴다 | 🔴 `EventContext.of` 가 turn·phase 를 **관측에서** 읽는 보장을 버린다 |
| hidden information | 🟢 없음 (결과는 실행 산물) | 🟢 없음 | 🟡 호출자가 관측과 다른 문맥을 넣을 수 있다 |
| `EventContext.actor` 계약과 일치 | 🟡 **부분** — "부르는 쪽이 선언한다" 와 어긋난다 | 🟢 **그 계약 자체다** | 🟡 선언이지만 한 겹 우회 |
| Battle · LifeChanged · ZoneMoved | 🔴 **ZoneMoved · LifeChanged 에서 깨진다** (가해자 칸 없음) | 🟢 전부 가능 | 🟢 가능 |
| EffectResult · ProgressionResult | 🔴 **EffectResult 불가** (actor 가 없다) | 🟢 가능 (`ProgressionResult` 는 "없음" 을 선언) | 🟢 가능 |
| EVENT_RELATION 이 읽을 때 안전한가 | 🔴 **위험** — 피해자를 행위자로 집을 수 있다 | 🟢 **안전** (선언이 없으면 모름) | 🟡 문맥 불일치 위험이 새로 생긴다 |
| API 가 불필요하게 복잡해지나 | 🟢 간단 | 🟢 **지금과 같다** (매개변수 그대로) | 🔴 **새 매개변수**이고 `read` 는 지금 `context` 를 받지 않는다 |

### 설계 C 를 코드 근거로 배제한다

`EventContext.of` 는 `view.turn_number` · `view.turn_player` · `view.phase` 를
**관측에서 읽는다.** 그래서 지금은 문맥의 turn·phase 가 **언제나** 관측과
같다 — 실측으로 확인했다. 호출자가 문맥을 만들어 넘기면 그 셋이 관측과
**갈릴 수 있고 아무도 맞춰 보지 않는다.** 설계 C 는 **없던 불일치를 새로
만드는** 선택이다 (`test_20`).

---

## 11. semantic responsibility 판단 (§8)

### "actor 를 가장 확실하게 알고 있는 위치는 어디인가?"

```
engine/duel.py:617,630,649,987,997   PlayerAction(actor=seat)        ← 여기서 확정된다
    │                                 seat 는 Duel 이 정한다
    ▼
Duel._apply_board                    executed = self._executor.execute(state, action, …)
    │                                 **deltas 와 action.actor 가 같은 지역 scope 에 있다**
    ▼
DuelStep(action, accepted, code, reason, result)   ← deltas 를 버린다 (3-F-12)
```

효과 경로는 다르다.

```
ResolutionContext(controller=…)      ← 효과를 해결하라고 **부른 쪽**이 정한다
    ▼
EffectExecutor.execute               → EffectResult  (actor 없음)
                                     → EffectEvent(actor=context.controller)
```

→ **actor 를 가장 확실하게 아는 위치는 "실행을 지시한 쪽"** 이다. 판 경로에서는
`Duel` (seat 를 안다), 효과 경로에서는 `ResolutionContext` 를 만든 쪽이다.
**둘 다 `read()` 의 호출자가 될 자리**다.

### "그 위치에서 EventReader 까지 전달하는 것이 architecture 상 올바른가?"

**올바르다.** 근거 넷:

1. `read()` 는 관측만 들고 있고 실행기를 **일부러 모른다** (§4). 전달받지
   않으면 알 길이 없고, 알게 만들면 모듈 경계가 무너진다.
2. 행위자는 **invocation 의 속성**이다 — 자비의 비가 증명한다 (delta 둘,
   행위자 하나). invocation 을 아는 것은 그것을 일으킨 쪽뿐이다.
3. `action.actor` 파생은 **2/7** 만 덮는다. 나머지에서 호출자가 필요하다면,
   계약을 둘로 쪼개는 것보다 **하나로 두는 것**이 책임이 명확하다.
4. 지금 코드가 이미 그렇게 동작한다 — **선언이 파생을 이긴다.** 계약을 글로
   적는 일만 남았다.

> **가장 쉽게 구현되는 위치를 고르지 않았다.** 가장 쉬운 것은 설계 A 의 확장
> (journal 의 `actor` 도 읽기) 이고, 그것은 2/7 → 4/7 로 사정거리를 늘린다.
> 고르지 않은 이유는 그 둘이 **지배자 · 지불자**이고 행위자가 아니기 때문이다.

---

## 12. production diff 와 §10 의 여섯 조건

```
$ git diff --stat HEAD -- engine agent app core analysis rules rulings sources scripts
(출력 없음)
```

**0 이다.** §10 은 여섯 조건을 **모두** 만족할 때만 최소 변경을 허용한다.

| # | 조건 | 판정 |
| --- | --- | --- |
| 1 | 현재 API 계약이 실제 semantic 오류를 만들 수 있음 | **○** — B 를 A 로 처리한다 (§8) |
| 2 | 올바른 계약이 기존 architecture 에서 명확히 도출됨 | **○** — 설계 B (§11) |
| 3 | 변경 범위가 `read()` 경계에 한정됨 | 🔴 **✗** |
| 4 | Engine V1 freeze 를 깨지 않음 | ○ |
| 5 | state_hash/RNG/Search/AI 에 영향 없음 | ○ |
| 6 | 기존 테스트 의미를 약화하지 않음 | ○ (강화된다) |

### 조건 3 이 깨지는 이유

"호출자가 반드시 선언해야 한다" 를 **실제로 구현하면** actor 에 기본값을 둘 수
없고, 그러면 **생략하고 있는 36 자리**가 전부 바뀐다 (§3). 그것은 `read()`
경계가 아니라 **호출자 쪽 변경**이고, §14 가 금지한 "즉시 대규모 리팩터링" 이다.

그래서 **계약만 확정하고 고치지 않는다.** 최소 변경 범위는 §14 에 적는다.

### 🟡 다음 Phase 가 고치면 깨질 내 테스트를 미리 적어 둔다

3-F-12 의 `test_12_read_cannot_express_an_explicit_none` 은 **현재의 결함을
pin 한다** (`read(execution, actor=None) → 1`). 보초값이 들어오면 그 테스트는
**반드시 깨진다.**

이것은 3-F-8 의 `test_15` 가 거짓 docstring 의 존재를 pin 했다가 3-F-11 에서
깨진 것과 **똑같은 모양**이다. 그때 배운 대로, 다음 Phase 는 그 테스트를
삭제하지 말고 **고쳐진 계약을 pin 하는 쪽으로 방향만 바꾸면** 된다. 미리 적어
두는 이유는, 그때 그것이 **회귀가 아니라 예정된 일**임을 알 수 있게 하려는
것이다.

---

## 13. 테스트

### 신규 `tests/test_event_reader_actor_input_boundary.py` — 23건

| # | 무엇을 고정하나 | §11 항목 |
| --- | --- | --- |
| 01 | actor 입력 경계는 **4개 메서드**, 기본값 전부 `None`, `collect_events` 는 제외 | §1 A·B |
| 02 | actor 는 `EventContext.of` 로만 간다 — delta 와 비교되지 않는다 | §1 C |
| 03 | 외부 production 호출자 **0개** | §1 D |
| 04 | 🔴 테스트 호출 72곳 중 **36곳이 생략** | §1 E |
| 05 | `read()` 는 추론할 재료가 없다 (관측 하나, 실행기 0) | §1 F·G |
| 06 | **명시 전달** — 선언이 파생을 이긴다 | 1 |
| 07 | **생략** — `action.actor` 가 들어온다 | 2 |
| 08 | 🔴 **`actor=None`** 은 생략과 구별되지 않는다 | 3 |
| 09 | 🔴 **강욕의 보은** — 행위자가 delta 어디에도 없다 | 4·5 |
| 10 | 🔴 **자비의 비** — 두 actor 의 cardinality 가 다르다 | 7 |
| 11 | `ZoneMoved` 5개 사건 — 가해자 칸 없음 + **도착지 주인**임을 고정 | 8 |
| 12 | 그런데 `MonsterSummoned` 은 행위자를 담는다 → 파생은 계약이 못 된다 | 4 |
| 13 | 🔴 `PhaseChanged` 는 사람 칸이 있는데 `actor=None` | 9 |
| 14 | **Battle** — 행위자가 `action` 에만 있다 | 6 |
| 15 | 7개 result 를 **책임**으로 가른다 (파생 최대 4/7, 안전 2/7) | §5 |
| 16 | 🟡 journal actor 는 `controller`·`payer` — 공짜가 아니다 | §5 |
| 17 | `INTENTIONAL_NONE` — `None` 을 **기대**한다 | §6 A |
| 18 | 🔴 `OMITTED_INPUT` — 두 `None` 이 구별되지 않는다 | §6 B |
| 19 | `UNKNOWN` — `CostPaymentResult` 는 설명에 없다 | §6 C |
| 20 | 설계 C 는 **없던 불일치를 만든다** | §2 |
| 21 | 3-F-11 계약 · dormant 경계 유지 | §12 |
| 22 | production diff 0 + `read` 본문 고정 + 금지 항목 | §10 |
| 23 | `state_hash` · RNG · hidden-information 불변 | §13 |

**"`None` 이면 실패" 테스트를 만들지 않았다.** `test_17` 은 `None` 을
**기대**하고, `test_18` 은 `None` 이 **같은 값이라는 사실**을 고정하며,
`test_19` 는 분류 근거가 **없다는 것**을 고정한다.

### 고의 위반 검증 — 7건, 전부 잡혔다

| # | 위반 | 잡은 테스트 |
| --- | --- | --- |
| 1 | `read()` 가 actor 를 **delta 에서 파생**한다 (§3 금지) | 3건 — 09·18·22 |
| 2 | 보초값으로 생략을 구분한다 (**다음 Phase 의 변경**) | 4건 — 01·03·08·22 |
| 3 | `read` 가 `context` 를 받는다 (**설계 C**) | 3건 — 01·20·22 |
| 4 | `PhaseChanged` 에 actor 를 넣는다 | 3건 — 13·17·22 |
| 5 | `EffectEvent.actor` 를 상수로 바꾼다 | 2건 — 16·22 |
| 6 | `MonsterSummoned` 의 `owner` 칸을 없앤다 | 2건 — 12·22 |
| 7 | `from_delta` 가 `ZoneMoved` 의 **출발지** 주인을 쓴다 | 3건 — 11·13·22 |

주입 2 가 중요하다 — **다음 Phase 가 할 변경이 지금 테스트에 걸린다.** 즉 이
감사는 "현재 계약" 을 pin 했고, 계약이 바뀌면 **알게 된다.**

> 🔴 주입 7 은 **처음에 `test_11` 에 걸리지 않았다.** 다섯 사건이 모두
> 출발지=도착지라서 두 칸을 가릴 수 없었기 때문이다. 그래서 컨트롤이 넘어가는
> 이동을 더해 `test_11` 을 **강화**했다. 주입이 테스트의 사각을 찾아낸 것이다.
>
> 🔴 주입 1 은 **`test_03` 의 줄 번호 고정**을 깨뜨렸다 (호출 자리가 2줄
> 밀렸다). 3-F-11 에서 줄 번호 snapshot 5건이 깨진 것과 같은 함정을 또 만든
> 것이어서, 줄 번호를 빼고 **파일·호출·인자**만 고정하도록 고쳤다.

주입 파일 4개(`event_pipeline.py` · `trigger.py` · `effect/executor.py` ·
`effect/delta.py`)는 전부 백업에서 복원하고 md5 로 확인했다 (4개 모두 `OK`).

### 전체 회귀

```
4362 passed, 4 skipped in 406.50s (0:06:46)
```

`4,339` (3-F-12) `+ 23` (신규) `= 4,362`. **첫 실행에서 실패 0** 이고 skip 은
그대로 4건이다. production diff 가 0 이므로 기존 테스트가 움직일 이유가 없었고,
실제로 움직이지 않았다.

`-p no:randomly` 로 돌렸다.

### 기존 테스트 처리

**삭제 0건 · skip 추가 0건 · assertion 약화 0건 · 수정 0건.**

---

## 14. state_hash / RNG / Search / AI 영향 (§13)

| 항목 | 결과 | 근거 |
| --- | --- | --- |
| `state_hash` | **불변** | 선언해 읽든 생략하든, 실제 카드 둘을 해결한 뒤 읽든 `state_hash()` 동일 (`test_23`) |
| RNG | **불변** | 같은 seed 두 번 → 같은 `state_hash` |
| hidden-information | **불변** | `EventReader(GameState)` 는 `TypeError` |
| Search ranking | **불변** | digest `30fa3597…402c4175` (6 duel · 611 decision) — 기존 3개 파일이 고정하고 있고 전체 회귀에서 통과한다. **네 번째 사본을 만들지 않았다** |
| AI behavior | **불변** | production diff 0 · `agent/` 는 `action.actor` 만 읽는다 (3-F-12 §13) |
| Engine V1 freeze | **유지** | production diff 0 |
| §12 금지 | **전부 미실행** | `EVENT_RELATION` 연결 ✗ · `TriggerRegistry` 연결 ✗ · pipeline 활성화 ✗ (`test_21`) |
| §9 금지 field/enum | **전부 없음** | `cause_player` · `affected_player` · `action_player` · `actor_player` · `ActorKind` · `ActorSource` · `EventActor` (`test_22`) |

---

## 15. 최종 판정

### **C. READ_ACTOR_CALLER_MUST_DECLARE**

**행위자의 semantic 의미를 호출자만 알고 있으므로, 호출자가 명시적으로 actor 를
제공해야 한다.**

근거 넷, 전부 실측이다.

1. **사정거리** — 설계 A 는 **2/7** 만 안전하게 덮는다. `EffectResult` ·
   `CostPaymentResult` 에는 actor 가 **객체에 없고**, journal 둘의 actor 는
   **지배자 · 지불자**라는 다른 개념이다. 호출자는 **7/7** 을 답할 수 있다.
2. **강욕의 보은** — 실제 카드에서 **행위자가 delta 에도 결과에도 없다.**
   P0 이 발동해 P1 이 드로우하면, 데이터가 가리키는 사람은 전부 P1 이다.
3. **delta 가 일관되지 않는다** — `MonsterSummoned` 은 행위자를 담고
   (`player` ≠ `owner`), `ZoneMoved`·`LifeChanged`·`CardDrawn` 은 담지 않는다.
   `read()` 에는 **둘을 가릴 근거가 없다.**
4. **`read()` 는 추론할 재료가 없다** — 관측 하나뿐이고 실행기를 일부러 모른다.
   추론하게 만들려면 모듈이 거부하고 있는 의존을 들여와야 한다.

그리고 **자비의 비**가 성격을 못박는다 — 행위자는 **invocation 의 속성**이고,
invocation 을 아는 것은 그것을 일으킨 쪽뿐이다.

### 왜 A 가 아닌가

A 는 "입력 책임이 명확하고 **`None` 경계도 설명 가능**" 을 요구한다. 책임은
명확해졌지만(이 Phase 가 확정했다) **`None` 경계가 설명되지 않는다** —
`INTENTIONAL_NONE` · `OMITTED_INPUT` · `UNKNOWN` 셋이 **같은 값**이고 코드에
구별이 **없다**. §6 이 금지한 "B 를 A 로 처리" 가 기본 동작이다.

### 왜 B 가 아닌가

B 는 "authoritative result/action 에 이미 있으므로 `read()` 가 파생하는 것이 더
올바르다" 다. **2/7 에서만 참이다.** 나머지에서 파생은 불가능하거나 개념
치환이고, delta 파생은 §3 이 명시적으로 금지한 것이다. 지금의 파생
(`action.actor`) 은 **편의로 남겨 두는 것이 맞지만, 계약은 아니다.**

### 왜 D 가 아닌가

D 는 "A/B/C 중 하나를 확정할 수 없다" 다. **확정했다** — 7개 result 의 책임,
10개 사건의 actor source, 세 설계의 9개 기준, 호출자 36/72 까지 전부 숫자로
적었다. 설계 C 는 코드 근거로 **배제**했다.

### 왜 E 가 아닌가

E 는 입력 경계 때문에 이후 architecture 를 안전하게 설계할 수 **없다**는 것이다.
설계할 수 있다. 필요한 것은 **보초값 하나와 docstring 한 단락**이고, 모듈 경계도
Engine V1 freeze 도 건드리지 않는다. 고의 위반 2번이 그 변경이 실제로 작다는
것을 보여주었다 — 걸린 테스트가 4건이고 전부 **의도된 신호**였다.

### 🟡 다만 "계약을 확정했다" 가 "지금 고장났다" 는 뜻은 아니다

외부 production 호출자가 **0개**다. 지금 틀린 actor 가 production 판단을
오염시키고 있지 않다. §14 대로 **즉시 리팩터링하지 않고** 계약 · 최소 변경 범위 ·
다음 Phase 후보만 적는다.

---

## 16. 최소 변경 범위 (확정만, 실행하지 않음)

계약 C 를 구현하는 데 필요한 **최소**는 셋이다.

| # | 무엇 | 범위 | 비용 |
| --- | --- | --- | --- |
| 1 | 생략을 구분하는 **보초값** — `actor=_OMITTED` | `engine/event_pipeline.py` **1파일** | 호출자 변경 **0** (생략 동작이 같다) |
| 2 | `actor=None` 을 **"주체 없음" 선언**으로 읽는다 | 같은 파일 | 🔴 3-F-12 `test_12` 를 **고쳐야 한다** (§12) |
| 3 | `read()` docstring 에 **7개 result 와 세 `None`** 을 적는다 | 같은 파일 | 0 |

**하지 않을 것**: `actor` 를 필수 인자로 만들기. 그것이 계약 C 의 완전한 형태
이지만 **36 자리**를 바꾸므로 §10 조건 3 과 §14 를 모두 깬다. 필수화는 보초값이
자리를 잡은 뒤에 **따로** 판단할 일이다.

---

## 17. 다음 Phase 후보 (1개)

### `read()` actor 입력에 보초값을 도입해 세 `None` 을 가른다 — **최소 production 변경**

이번 Phase 가 **계약을 확정했으므로**, 다음은 감사가 아니라 **구현**이다.
범위는 §16 의 1 · 3 (2 는 함께 따라온다).

반드시 함께 처리할 것:

1. 3-F-12 `test_12_read_cannot_express_an_explicit_none` 을 **삭제하지 말고**
   고쳐진 계약을 pin 하는 쪽으로 바꾼다. **왜 기존 테스트가 결함을 pin 하고
   있었는지**를 보고서에 적는다 (3-F-11 이 `test_15` 에 한 것과 같다).
2. 이 Phase 의 `test_01` · `test_03` · `test_08` 도 **의도적으로 깨진다** —
   고의 위반 2번이 미리 보여주었다. 같은 방식으로 고친다.
3. `read_deltas` 와 `read` 의 **표현력 차이가 사라지는지** 확인한다. 보초값이
   들어오면 `read` 도 "주체 없음" 을 말할 수 있게 되므로, 두 메서드의 계약
   차이를 docstring 에 적을지 **없앨지** 결정해야 한다.
4. `actor` 를 **필수로 만들지는 않는다** — 그 결정은 별개이고, 36 자리의 변경이
   필요하므로 사용자 승인이 먼저다.

**시작하지 않는다.** 다음 Phase 는 임의로 진행하지 않는다.

---

## 18. Commit · Push 기록

| 항목 | 값 |
| --- | --- |
| 작업 commit | **`2eef3f9`** `Phase 3-F-13: audit EventReader actor input boundary` |
| 포함 파일 | `tests/test_event_reader_actor_input_boundary.py` **하나뿐** — production 0 |
| push | `b3f2c0e..2eef3f9` → `origin/claude/pensive-goodall-te1egy` **성공** |
| 보고서 commit | 이 문서 — `Phase 3-F-13: document EventReader actor input boundary audit` |

작업 직전 HEAD 는 `b3f2c0e` (3-F-12 보고서) 였고, push 결과가 그 SHA 에서
이어진 것으로 확인된다. 작업 commit 이 **테스트 파일 하나만** 담고 있는 것이
AUDIT-ONLY 의 직접 증거다.
