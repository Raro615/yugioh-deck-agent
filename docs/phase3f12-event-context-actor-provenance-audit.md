# Phase 3-F-12 — `EventContext.actor` Provenance / None 경계 감사

## 1. Phase · Base · 실제 HEAD

| 항목 | 값 |
| --- | --- |
| Phase | 3-F-12 — `EventContext.actor` provenance · `None` 경계 감사 |
| 모드 | **AUDIT-ONLY** — production diff **0** |
| **실제 HEAD (측정)** | `6d2f5f4 Phase 3-F-11: document actor semantic contract` |
| Base (3-F-11) | `a6087bc` (작업) · `6d2f5f4` (보고서) — **둘 다 실제로 존재한다** (`git cat-file -t` 확인) |
| 3-F-11 최종 판정 | **A. ACTOR_SEMANTIC_CONTRACT_FIXED** |
| branch | `claude/pensive-goodall-te1egy` |
| baseline 테스트 | 4,315 passed / 4 skipped |
| 신규 테스트 | `tests/test_event_context_actor_provenance.py` — **24건** |

이 Phase 는 구조를 바꾸지 않는다. `EVENT_RELATION` 을 연결하지 않고,
trigger pipeline 을 켜지 않고, 새 field 를 만들지 않는다 (§10 · §11).

---

## 2. 요지 — 일곱 가지 측정

1. `EventContext` 를 만드는 production 자리는 **두 곳**이고 둘 다
   `engine/event_pipeline.py` 안이다. 값을 **받는** 자리는 `of` **하나**다.
2. `PlayerAction.actor` 는 **절대 `None` 이 되지 않는다** (필수 `int`,
   `__post_init__` 이 0/1 만 받는다). 그래서 **행위가 있는 경로에서는 actor 가
   비지 않는다** — `None` 경계는 전부 "행위가 없는" 쪽에서만 생긴다.
3. 🔴 delta 를 들고 있는 production result 는 **7개**다. 그중 `.action` 을 가진
   것은 **둘** — `ActionExecution` **과 `ActivationResult`**. 3-F-10 · 3-F-11 이
   "`ActionExecution` 하나뿐" 이라 적은 것은 **덜 센 것**이었다.
4. 🔴 `EffectEvent` · `CostPaymentEvent` 는 `actor` 를 **자기 칸에 직접 들고
   있는데** `read()` 가 그 칸을 **보지 않는다.** 정보가 객체에 있는데 떨어진다.
5. 🔴 `read()` 로는 **"주체가 없다" 를 선언할 수 없다.** `actor=None` 은 "안
   넘긴 것" 과 구별되지 않아 언제나 fallback 이 이긴다. `read_deltas` 는 표현할
   수 있다 — **두 메서드의 표현력이 다르고, 그 차이가 어디에도 적혀 있지 않다.**
6. 🔴 `context.actor is None` 에는 **까닭이 적히지 않는다.** `TimingEvent` 에는
   `note` 칸이 있는데 `EventContext` 에는 없다 — **비대칭**이다.
7. live 경로는 `DuelStep` 에서 끊긴다. 그런데 `read()` 가 필요한 입력 둘
   (`deltas` · `action.actor`) 이 **같은 함수의 지역변수로 동시에 존재한다.**

---

## 3. 🔴 먼저: 내가 앞 Phase 에서 덜 셌다

3-F-10 §12 와 3-F-11 §11 에 이렇게 적었다.

> `ActionExecution` 만 `.action` 을 가지고 있다. `EffectResult` ·
> `ProgressionResult` 는 없다.

**전수로 세면 틀렸다.** `engine` 전체를 `pkgutil.walk_packages` 로 import 한 뒤
`deltas` 칸을 가진 dataclass 를 모으면 **7개**가 나오고, `.action` 을 가진 것이
**둘**이다.

| result | `.action` | `.actor` | `read()` 의 actor |
| --- | --- | --- | --- |
| `engine.action_execution.ActionExecution` | ○ `PlayerAction` | ✗ | `action.actor` |
| `engine.activation.ActivationResult` | **○ `PlayerAction`** | ✗ | `action.actor` |
| `engine.effect.journal.EffectEvent` | ✗ | **○ 필수 `int`** | **`None`** 🔴 |
| `engine.effect.journal.CostPaymentEvent` | ✗ | **○ 필수 `int`** | **`None`** 🔴 |
| `engine.effect.resolution.EffectResult` | ✗ | ✗ | `None` |
| `engine.payment.CostPaymentResult` | ✗ | ✗ | `None` |
| `engine.turn_progression.ProgressionResult` | ✗ | ✗ | `None` |

두 집합(`.action` 있음 / `.actor` 있음)이 **겹치지 않는다** — 한 result 가 둘을
다 갖는 일은 없다 (`test_05`).

**왜 전에는 안 보였나.** 3-F-9 에서 똑같은 실수를 했다 —
`StateDelta.__subclasses__()` 만 보고 7개 delta 클래스를 놓쳤고, 그때 "전수를
세려면 `engine` 전체를 import 해야 한다" 를 교훈으로 적었다. 3-F-10 · 3-F-11 은
**그 교훈을 actor 쪽에 적용하지 않았다.** 이번에는 같은 도구를 썼다
(`every_delta_bearing_result`).

---

## 4. `EventContext` 생성 위치 (§2 A · B)

production 전체에서 `EventContext` 가 만들어지는 자리는 **둘**이다.

| # | 자리 | 코드 | actor 를 어떻게 하나 |
| --- | --- | --- | --- |
| 1 | `EventContext.of(view, actor=, sequence=)` | `return cls(...)` | **값을 받는다** — 유일한 입구 |
| 2 | `EventContext.at(sequence)` | `return EventContext(...)` | `self.actor` 를 **옮겨 적는다** |

- 이름으로 부르는 자리는 **1곳**이다: `construction_sites("EventContext") ==
  {"engine/event_pipeline.py": 1}`. `of` 는 `cls(...)` 라서 이름 검색에 안 잡힌다
  — 그래서 둘을 따로 확인했다 (`test_01`).
- `at` 은 순번만 바꾸므로 **한 변화 묶음의 모든 사건이 같은 actor 를 공유한다**
  (`test_02`). 사건별로 actor 가 달라질 수 없다.
- `read_deltas` 가 `EventContext.of(self._view, actor=actor)` 로 묶음의 기준을
  만들고, delta 마다 `base.at(index)` 를 붙인다.

**밖에서 문맥을 만드는 production 코드는 없다.**

---

## 5. actor source (§2 C) — 코드는 `result.action.actor` 라고 쓰지 않는다

`EventReader.read` 의 실제 본문 (docstring 제거, `ast.unparse`):

```python
deltas = getattr(result, 'deltas', None)
if deltas is None:
    raise TypeError(f'변화(deltas)를 들고 있는 결과가 필요합니다: {type(result).__name__}')
if actor is None:
    actor = getattr(getattr(result, 'action', None), 'actor', None)
return self.read_deltas(deltas, actor=actor)
```

🔴 **점 표기법이 코드에 없다.** 겹 `getattr` 이다. 그 결과:

- **타입을 보지 않는다** — `action` 이라는 이름의 아무 것이나 받는다.
- 없으면 **조용히 `None`** 이 된다. 예외도, 경고도, 기록도 없다.

production 전체에서 `result.action.actor` 라는 문자열이 나오는 곳은
`engine/event_pipeline.py` **한 파일**이고, 그 자리는 **산문**이다 — AST 로
문자열 리터럴이 차지하는 줄 집합을 구해 그 안에 들어 있음을 확인했다
(`test_03`). 즉 **설명은 점 표기법으로 적혀 있고 코드는 duck typing 이다.**

> 줄 번호를 고정하지 않았다. 3-F-11 에서 줄 번호 snapshot 이 docstring 한 줄
> 때문에 줄줄이 깨졌다. 이번에는 **성격**(산문인가 코드인가)을 고정했다.

### `action.actor` 는 `None` 이 될 수 없다 (§2 E)

```
actor: int            # 기본값 없음
if self.actor not in (0, 1): raise MalformedAction(...)
```

`None` · `2` · `-1` 전부 거부된다 (`test_04`). 그래서 **§2 E 의 답은 "아니다"**
이고, 이것이 §5 의 범위를 좁힌다 — `None` 경계는 **행위를 들고 있지 않은
결과**에서만 생긴다.

---

## 6. production call graph (§3)

```
PlayerAction(actor=seat)                       engine/duel.py 9곳
    │                                          actor 는 여기서 확정된다
    ▼  CONNECTED
ActionExecution(action=…, deltas=…)            engine/duel.py:805 _apply_board
ActivationResult(action=…, deltas=…)           engine/duel.py:903 발동 경로
    │                                          ← deltas 와 actor 가 **여기 함께 있다**
    ▼  🔴 MISSING — 지역변수로 버려진다
DuelStep(action, accepted, code, reason, result)
    │                                          result 는 DuelResult|None (승패)
    ▼  MISSING
EventReader.read(result, actor=None)           production importer **0**
    │
    ▼  DORMANT
EventContext.of(view, actor=…) → .at(i)
    │
    ▼  DORMANT
ObservedEvent.context.actor                    production consumer **0**
```

| 화살표 | 판정 | 근거 |
| --- | --- | --- |
| `PlayerAction` → `ActionExecution` / `ActivationResult` | **CONNECTED** | 둘 다 `action` 을 필수로 들고 있다 |
| 실행 결과 → `DuelStep` | 🔴 **MISSING** | `DuelStep` 에 `deltas` 칸이 없고 `result` 는 승패다 |
| `DuelStep` → `EventReader` | **MISSING** | `engine/duel.py` 에 `EventReader` · `EventContext` · `ObservedEvent` · `deltas` 가 **0회** |
| `EventReader` → `EventContext` | **CONNECTED** (모듈 안) | `read_deltas` 가 `of` 를 부른다 |
| `EventContext.actor` → consumer | **DORMANT** | production 에 `context.actor` 를 읽는 줄이 **0** |

### 🔴 한 대입 전에서 끊긴다

`Duel._apply_board` 안에서:

```python
executed = self._executor.execute(self.state, action, authorization=…)   # deltas 를 들고 있다
…
return DuelStep(action, True, ValidationCode.OK, executed.reason, result=self._check_end())
```

`executed.deltas` 와 `action.actor` 가 **같은 함수의 같은 시점에** 있다.
`read()` 가 필요한 입력이 전부 거기 있고, **보관되지 않는 것뿐이다**
(`test_19`). 3-F-5 가 "Duel 이 delta 를 버린다" 로 찾은 것과 같은 자리이고,
이번에 **actor 쪽에서도 같은 자리라는 것**을 확인했다.

---

## 7. actor provenance 분류 (§4)

| 분류 | 경로 | 근거 |
| --- | --- | --- |
| **A. ACTION_ACTOR** | `ActionExecution` · `ActivationResult` | `action.actor` 가 필수 `int` 이므로 **언제나** 실측 행위자가 들어온다 (`test_06`) |
| **B. DERIVED** | **없다** | `EventContext.actor` 는 계산되지 않는다. `TimingEvent.actor` 쪽만 파생이다 (3-F-10) |
| **C. EXPLICIT_NONE** | `ProgressionResult` | 결과 · `TransitionPlan` · `PhaseTransition` **어디에도 사람 칸이 없다** (`test_10` · `test_11`) |
| **🔴 D. MISSING** | `EffectEvent` · `CostPaymentEvent` | `actor` 가 **필수 `int` 로 객체에 있는데** `read()` 가 `.action` 만 본다 (`test_07`) |
| **E. UNKNOWN** | `EffectResult` · `CostPaymentResult` | actor 칸이 없다. 상류(`ResolutionContext.controller` · `PaymentContext.payer`)는 알고 있었다 — 결과가 들고 나오지 않는다 (`test_09`) |

### C 와 D 를 같은 것으로 취급하지 않는다

둘 다 `context.actor is None` 을 낸다. **값이 같다.** 그런데

- `ProgressionResult` 의 `None` 은 **구조상 없는 것**이다 — 채울 값이 없다.
- `EffectEvent` 의 `None` 은 **읽지 않은 것**이다 — 채울 값이 `event.actor` 에
  있다.

그리고 **받는 쪽에는 이 둘을 가를 정보가 하나도 없다** (§8 참조).

---

## 8. `None` 경계 전체 목록 (§5)

| # | 경로 | action? | `action.actor`? | 계약 성립? | `EVENT_RELATION` 이 읽으면 | 코드에 해석이 적혀 있나 | 분류 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `ProgressionResult` (페이즈 전환) | ✗ | — | **○** — 규칙이 한 일이다 | "주체 없음" 으로 읽어야 한다 | 🟡 `TimingEvent` 쪽만 (`PhaseChanged` → `actor=None`) | **INTENTIONALLY_NONE** |
| 2 | `EffectResult` (효과 해결) | ✗ | — | **△** — 부르는 쪽이 선언하면 성립 | **모름**으로 읽어야 한다. "주체 없음" 이 아니다 | 🟢 3-F-11 의 docstring 이 적었다 | **UNRESOLVED** (선언 필요) |
| 3 | `CostPaymentResult` (비용) | ✗ | — | **△** — 같다 | 같다 | 🔴 적혀 있지 않다 (docstring 이 이 타입을 예로 들지 않는다) | **UNRESOLVED** |
| 4 | `EffectEvent` (journal) | ✗ | — | **✗** | **틀리게 읽는다** — 주체가 있는데 없다고 본다 | 🔴 없다 | **MISSING_ACTOR** |
| 5 | `CostPaymentEvent` (journal) | ✗ | — | **✗** | 같다 | 🔴 없다 | **MISSING_ACTOR** |
| 6 | `read_deltas(deltas)` 직접 호출 | — | — | **○** — 선언 안 했으면 모름이 맞다 | 모름 | 🟡 간접적으로만 | **UNRESOLVED** |

### 🔴 `read()` 로는 EXPLICIT_NONE 을 선언할 수 없다

```python
read(execution)                 → context.actor = 1
read(execution, actor=None)     → context.actor = 1      # 같은 값, 같은 객체
```

`if actor is None:` 이 "안 넘겼다" 와 "None 을 넘겼다" 를 **구별하지 않는다.**
보초값(sentinel)도 `MISSING` 도 없다 (`test_12`). 그래서 **행위를 들고 있는
결과에 "이 사건에는 주체가 없다" 를 말할 방법이 `read()` 에 없다.**

### 🔴 `read_deltas` 는 할 수 있고, 그 차이가 적혀 있지 않다

```python
reader.read(execution)                          → [1]
reader.read_deltas(execution.deltas)            → [None]
reader.read_deltas(execution.deltas, actor=None)→ [None]
```

`read_deltas` 에는 result 가 없으므로 fallback 자체가 없다 — 본문에 `getattr`
도 `action` 도 **나오지 않는다.** 즉 "주체 없음" 을 표현하려면 **더 낮은 API 로
내려가야 하는데**, 두 docstring 어디에도 `read_deltas` 라는 말이 나오지 않는다
(`test_13`).

### 선언값은 검증되지 않는다 — 설계된 느슨함

```python
battle(attacker=P1) → action.actor = 1
read(execution, actor=0) → context.actor = 0      # 거짓말이 그대로 들어간다
```

3-F-11 의 docstring 이 "delta 와 맞춰 보지 않는다 · 사실인지는 넘기는 쪽의
책임" 이라고 적어 둔 그대로다. **결함이 아니다** — 다만 `actor` 가 틀릴 수
있다는 것을 못박았다 (`test_14`). 막는 것은 0/1 밖뿐이다.

### 🔴 `None` 의 까닭이 코드에 남지 않는다 (§5 6번)

```
EventContext = {turn_number, turn_player, phase, actor, sequence}
```

`note` · `provenance` · `actor_source` · `reason` 칸이 **하나도 없다.** 그래서
`context.actor is None` 을 받은 쪽은 셋을 구분할 수 없다 —
INTENTIONALLY_NONE · MISSING_ACTOR · 선언을 잊은 것.

**비대칭이다.** `TimingEvent` 에는 `note` 칸이 있어서 "옮길 이름이 없었다" 를
적을 수 있고, `is_observable` 이 그것을 읽는다. 문맥 쪽에는 그 자리가 없다
(`test_15`).

---

## 9. Battle 사례 재검증 (§7)

P1 이 P0 을 직접 공격한다. 실측:

| 항목 | 값 |
| --- | --- |
| `action.actor` | **1** |
| P0 LP | 8000 → **6100** |
| delta | `LifeChanged(player=0, before=8000, after=6100)` — **하나뿐** |
| point | `life_changed` |
| `timing.actor` | **0** — 귀속 (맞은 쪽) |
| `context.actor` | **1** — 행위 (공격한 쪽) |

### 값이 우연히 맞은 것이 아니다

두 값의 **출처가 서로 독립**이다.

```
context.actor ← execution.action.actor ← PlayerAction(actor=1)   (선언 경로)
timing.actor  ← delta.player                                      (파생 경로)
```

그래서 공격자를 뒤집으면 **둘이 함께 뒤집힌다** — 한쪽만 바뀌면 그것이 파생이
아니라 우연이었다는 증거가 된다. 실측:

| 공격자 | 피해자 LP | `timing.actor` | `context.actor` |
| --- | --- | --- | --- |
| P1 | P0: 8000 → 6100 | 0 | 1 |
| P0 | P1: 8000 → 6100 | 1 | 0 |

**둘 다 자기 계약을 지킨다** (`test_16`). §7 의 질문 — "현재 production 코드가
이 둘을 각각 올바른 의미로 보존하고 있는가?" — 의 답은 **행위가 있는 경로에서는
그렇다**.

---

## 10. 실제 실행 경로별 provenance (§6)

실제 카드(`11091375` 홍옥의 사령 · `55144522` 욕망의 항아리)로 돌려서 쟀다
(`test_17`).

| # | 경로 (§6 번호) | result | delta 수 | `TimingPoint` | `context.actor` | 분류 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 통상 소환 | `ActionExecution` | 1 | `monster_summoned` | **1** | A |
| 2 | 특수 소환 | `ActionExecution` | 1 | `monster_summoned` | **1** | A |
| 3 | 직접 공격 | `ActionExecution` | 1 | `life_changed` | **1** | A |
| 4 | 카드 드로우 | `EffectResult` (욕망의 항아리) | 2 | `card_drawn` | `None` | E |
| 5 | 라이프 변화 | 3번 **안에서** 일어난다 — 별도 result 가 없다 | — | `life_changed` | **1** | A |
| 6 | 존 이동 (마법·함정 세트) | `ActionExecution` | 1 | **`unimplemented`** | **1** | A |
| 7 | 마법·효과 발동 | `ActivationResult` | **0** (비용 없음) | — | **1** (delta 를 얹으면) | A |
| 8 | 효과 해결 | `EffectResult` | 2 | `card_drawn` | `None` | E |
| 9 | journal 기록 | `EffectEvent` | 2 | `card_drawn` | `None` 🔴 | **D** |
| 10 | 페이즈 전환 | `ProgressionResult` | 1 | `phase_changed` | `None` | C |

`test_17` 이 1·2·3·6·8·9·10 **일곱 경로**를 실제로 돌려서 쟀고, 7 은
`test_06` 이 따로 쟀다. 5 는 3 과 같은 실행이다 (전투의 유일한 delta 가
`LifeChanged` 다 — 3-F-9 의 측정과 같다).

- 1 ~ 3 · 5 ~ 7 — **행위가 있는 경로는 전부 실제 행위자를 준다.**
- 4 · 8 ~ 10 — **행위가 없는 경로는 전부 `None` 이고, 까닭이 서로 다르다.**
- 🟡 **6 이 흥미롭다.** 마법·함정 세트의 delta 는 옮길 이름이 없어서
  `TimingPoint.UNIMPLEMENTED` 인데, **`context.actor` 는 그대로 1 이다.** 두
  계약이 독립이라는 또 하나의 증거다 — 사건에 이름을 못 붙여도 **누가 했는지는
  남는다.** (`TimingEvent.actor` 는 이 경우 `ZoneMoved` 의 도착지 주인에서
  온다.)
- 7 의 주의점: 비용 없는 발동은 `deltas == ()` 라서 **사건이 0개**다. 그래도
  actor 경로는 `.action` 이다 — delta 하나를 얹어서(`dataclasses.replace`)
  확인했다. 판을 바꾸지 않는 측정이다.

---

## 11. `EffectResult` / `ProgressionResult` 사례 (§8)

### `EffectResult` — 칸이 없다. 상류는 알고 있었다

```
fields(EffectResult) = {status, code, reason, missing, applied, deltas, unchecked_rules}
```

`actor` 도 `action` 도 없다. 그런데 `EffectExecutor.execute` 는
`ResolutionContext(controller=…)` 를 받으므로 **누가 해결하는지 알고 있었다.**
결과가 그것을 들고 나오지 않는다.

- 선언이 없으면 `None`
- `read(result, actor=MINE)` 로 선언하면 들어간다

→ **경로가 막힌 것이 아니라 비어 있는 것**이다 (`test_09`).

### 🟡 그리고 journal 의 actor 는 **행위자가 아니라 지배자 · 지불자**다

```python
engine/effect/executor.py   self._journal.record(..., actor=context.controller, ...)
engine/payment.py           self._journal.record_payment(actor=context.payer, ...)
```

두 문맥에 `actor` 칸이 **없다** — `controller` 와 `payer` 뿐이다. Engine V1 에
컨트롤 이동이 없으므로 **지금은 값이 같다.** 그러나 **같은 뜻이 아니다.**

그래서 "journal 의 actor 를 그대로 `EventContext.actor` 로 쓰면 된다" 고
결론하지 않는다. **고치지 않고 `STRUCTURAL_RISK` 로 적는다** (`test_18`) — §8 이
요구한 그대로다.

### `ProgressionResult` — 구조상 사람이 없다

```
fields(ProgressionResult) = {status, plan, deltas}
fields(TransitionPlan)    = {verdict, transition, unresolved_rules}
fields(PhaseTransition)   = {kind, before, after}
```

세 층 **어디에도** `actor` · `action` · `player` · `turn_player` 가 없다
(`test_10`). 실제로 돌리면 `timing.actor` 도 `context.actor` 도 `None` 이고
point 는 `phase_changed` 다 (`test_11`). 3-F-9 가 `PhaseChanged` 의 `actor` 를
`None` 으로 측정한 것과 **같은 자리**다.

→ **INTENTIONALLY_NONE.** 다만 그 의도가 `EventContext` 쪽에는 적혀 있지 않다 —
`TimingEvent.actor` 의 표에만 "`PhaseChanged` → `None` — 규칙이 하는 일이다" 가
있다.

### `read()` 의 docstring 이 7개 중 3개만 예로 든다

```
"ActionExecution · ProgressionResult · EffectResult"
```

`ActivationResult` · `CostPaymentResult` · `EffectEvent` · `CostPaymentEvent` 가
빠져 있다 (`test_08`). 빠진 넷 중 **둘이 바로 `MISSING_ACTOR` 경로**다.

---

## 12. 실제 consumer 현황

| 묻는 것 | 답 | 근거 |
| --- | --- | --- |
| `engine.event_pipeline` 을 import 하는 production 파일 | **0개** | `test_20` |
| `context.actor` 를 읽는 production 줄 | **0줄** | `test_20` |
| `EventContext` 를 만드는 production 자리 (모듈 밖) | **0곳** | `test_01` |
| `engine/duel.py` 가 사건 파이프라인을 아는가 | **모른다** (`EventReader`·`EventContext`·`ObservedEvent`·`deltas` 전부 0회) | `test_19` |

`engine/summon.py` · `engine/__init__.py` · `engine/trigger.py` ·
`engine/execution.py` 에 `event_pipeline` 이라는 말이 나오지만 **전부 설명
속의 상호 참조**이고 import 가 아니다.

→ **지금 틀린 판정이 나오고 있지는 않다.** §8 의 공백은 **아직 아무도 밟지
않은** 자리다. 그래서 이번 Phase 가 고치지 않아도 오작동이 없다.

---

## 13. AI / Search 영향 (§9)

| 묻는 것 | 답 |
| --- | --- |
| `engine/game_state_view.py` 에 `actor` 라는 말 | **0회** |
| `agent/` 가 읽는 `.actor` | 전부 `action.actor` · `chosen.actor` — **자기가 고른 행위의** actor |
| `agent/` 에 `ObservedEvent`·`EventContext`·`TimingEvent`·`EventReader` | **0회** |

→ **`EventContext.actor` 는 AI 관측에 노출되지 않는다** (`test_21`).
`agent/simulation.py:252` 의 `self.duel.legal_actions(action.actor)` 와
`agent/runner.py:220` 의 `chosen.actor != seat` 는 **행위의 주인** 확인이고
사건의 actor 가 아니다.

§9 가 변경을 금지한 것들 — `GameStateView` · `Observation` · `LegalActions` ·
`Search` · `Evaluation` · `Policy` — **한 줄도 건드리지 않았다.**

---

## 14. state_hash / RNG / hidden-information 영향

| 항목 | 결과 | 근거 |
| --- | --- | --- |
| `state_hash` | **불변** | 선언해 읽든, 안 하고 읽든, journal 사건을 읽든 `state_hash()` 가 동일 (`test_23`) |
| RNG | **불변** | 같은 seed 두 번 → 같은 `state_hash` (`test_23`) |
| hidden-information 경계 | **불변** | `EventReader` 는 `GameStateView` 만 받고 `GameState` 를 **거부**한다. `__slots__ == {"_view"}` (`test_24`) |
| Search ranking | **불변** | 6 duel · **611 decision** digest `30fa3597…402c4175` — 기존 3개 파일(`test_actor_relation_boundary_audit` · `test_actor_role_separation_audit` · `test_actor_semantic_contract`)이 이미 고정하고 있고 전체 회귀에서 통과한다. **네 번째 사본을 만들지 않았다** (같은 6판을 또 돌리는 비용뿐이다) |
| Engine V1 freeze | **유지** | production diff 0 |

---

## 15. production diff

```
$ git diff --stat HEAD -- engine agent app core analysis rules rulings sources scripts
(출력 없음)
```

**0 이다** — §14 가 "특히 production diff 가 0이어야 정상" 이라고 한 그대로다
(`test_22`).

§10 · §11 의 금지 항목 전부 미실행:

- `EVENT_RELATION` production 연결 · `TriggerRegistry` 연결 · dormant pipeline
  활성화 · `EventBus` · 새 event graph · 새 Player API — **전부 없음**
- 새 field `cause_player` · `affected_player` · `action_player` ·
  `source_player` · `actor_player` — **전부 없음**
- `EventBus` 라는 말은 `engine/event_pipeline.py` 에 **1회** 나오고, 그것은
  "만들지 않는다" 는 설명이다 — 숫자를 고정해 두었다

### `test_22` 는 줄 수를 세지 않는다

3-F-11 에서 줄 수 snapshot 5건이 docstring 때문에 깨졌다. 그래서 이번에는
**이 감사가 의지한 코드 본문 자체**를 고정했다 — `EventReader.read` 의 본문
6줄이다. 누가 fallback 을 바꾸면 이 감사의 결론이 무효가 되므로, **그때 깨지는
것이 맞다.** 줄 번호가 밀려서 깨지는 일은 없다.

---

## 16. 테스트

### 신규 `tests/test_event_context_actor_provenance.py` — 24건

| # | 무엇을 고정하나 |
| --- | --- |
| 01 | `EventContext` 생성 자리는 두 곳, 둘 다 한 모듈 안 |
| 02 | actor 를 받는 자리는 `of` 하나 · `at` 은 옮겨 적기만 |
| 03 | 🔴 코드는 `result.action.actor` 라고 쓰지 않는다 (겹 `getattr`), 점 표기법은 **산문**뿐 |
| 04 | `action.actor` 는 `None` 이 될 수 없다 |
| 05 | 🔴 delta 를 들고 있는 result **7개** · `.action` 은 **2개** (앞 Phase 정정) |
| 06 | `.action` 이 있으면 actor 가 언제나 들어온다 (`ActivationResult` 포함) |
| 07 | 🔴 journal 사건은 actor 를 들고 있는데 `read()` 가 안 본다 |
| 08 | `read()` docstring 이 7개 중 3개만 예로 든다 |
| 09 | `EffectResult` 는 칸이 없다 · 상류는 알고 있었다 |
| 10 | `ProgressionResult` 3층 전부 사람 칸이 없다 |
| 11 | 페이즈 전환은 두 actor 가 다 `None` |
| 12 | 🔴 `read()` 로 EXPLICIT_NONE 을 선언할 수 없다 |
| 13 | `read_deltas` 는 할 수 있고, 그 차이가 적혀 있지 않다 |
| 14 | 선언값은 검증되지 않는다 (설계된 느슨함) |
| 15 | 🔴 `None` 의 까닭이 남지 않는다 — `TimingEvent.note` 와 비대칭 |
| 16 | Battle 반례 — 8000→6100 · 두 출처가 독립 · 뒤집으면 함께 뒤집힌다 |
| 17 | 10개 실행 경로 → result 타입 → actor 출처 |
| 18 | 🟡 journal actor 는 `controller` · `payer` 에서 온다 (`STRUCTURAL_RISK`) |
| 19 | 🔴 live 경로가 `DuelStep` 에서 끊긴다 — 입력 둘이 같은 함수에 있다 |
| 20 | production importer 0 · `context.actor` reader 0 |
| 21 | AI 관측에 사건 actor 가 노출되지 않는다 |
| 22 | production diff 0 + `read` 본문 고정 + 금지 항목 미실행 |
| 23 | `state_hash` · RNG 불변 |
| 24 | hidden-information 경계 불변 (`GameState` 거부) |

**"actor 가 `None` 이면 무조건 실패" 라는 테스트는 만들지 않았다** (§12). `None`
이 계약상 허용되는 경로(`test_10` · `test_11`)는 `None` 을 **기대**하고,
허용되지 않는 경로(`test_07`)만 결함으로 적는다.

### 고의 위반 검증 — 7건, 전부 잡혔다

| # | 위반 | 잡은 테스트 |
| --- | --- | --- |
| 1 | `read()` 의 `.action` fallback 을 **없앤다** | **8건** — 03·06·07·12·13·16·17·22 |
| 2 | `read()` 가 `result.actor` 도 보게 **"고친다"** | 4건 — 03·07·17·22 |
| 3 | `EventContext` 에 `cause_player` 를 더한다 | 2건 — 15·22 |
| 4 | `DuelStep` 이 `deltas` 를 보관한다 | 4건 — 05·08·19·22 |
| 5 | `PlayerAction.actor` 를 `None` 허용으로 바꾼다 | 2건 — 04·22 |
| 6 | `GameStateView` 가 `actor` 를 드러낸다 | 2건 — 21·22 |
| 7 | `EffectEvent.actor` 를 `None` 기본값으로 바꾼다 | 2건 — 07·22 |

주입 4 가 `test_05` · `test_08` 까지 깨뜨린 것은 **의도하지 않은 교차
확인**이었다 — `DuelStep` 에 `deltas` 를 더하면 **8번째** delta-bearing
dataclass 가 되기 때문이다. 전수 측정이 실제로 전수라는 증거다.

주입 2 가 의미 있다: **공백을 "고치는" 변경도 잡힌다.** 이 Phase 는 고치지
않기로 했고(§15), 몰래 고치면 걸린다.

주입 파일 5개(`event_pipeline.py` · `duel.py` · `action.py` ·
`game_state_view.py` · `effect/journal.py`)는 전부 백업에서 복원하고 md5 로
확인했다 (5개 모두 `OK`).

### 전체 회귀

```
4339 passed, 4 skipped in 385.44s (0:06:25)
```

`4,315` (3-F-11) `+ 24` (신규) `= 4,339`. **첫 실행에서 실패 0** 이고 skip 은
그대로 4건이다.

3-F-11 과 달리 **깨진 기존 테스트가 하나도 없다.** 그것이 AUDIT-ONLY 의 증거다 —
3-F-11 은 docstring 을 고쳐서 줄 수 snapshot 5건을 움직였지만, 이번에는
production 을 한 글자도 바꾸지 않았으므로 움직일 것이 없었다.

`-p no:randomly` 로 돌렸다.

### 기존 테스트 처리

**삭제 0건 · skip 추가 0건 · assertion 약화 0건 · 수정 0건.**

§13 이 "production behavior 가 변경되는 수정이 필요하다면 즉시 중단하고 보고"
를 요구했다 — **그런 수정은 필요하지 않았다.** 공백을 찾았지만 고치지 않았고
(§15), 그래서 중단 조건에 닿지 않았다.

---

## 17. 최종 판정

### **C. ACTOR_PROVENANCE_GAP**

**actor 가 존재해야 하는 경로에서 전달되지 않는 구조적 공백이 있다.**

근거 둘, 둘 다 실측이다.

1. 🔴 **`EffectEvent.actor` · `CostPaymentEvent.actor` 가 필수 `int` 로 객체에
   있는데 `read()` 가 그 칸을 보지 않는다.** 결과는 `context.actor is None` 이고,
   이것은 "주체가 없다" 가 아니라 **"주체가 있는데 안 읽었다"** 다. 받는 쪽은
   `ProgressionResult` 의 의도된 `None` 과 **구분할 수 없다.**
2. 🔴 **`read()` 로는 "주체 없음" 을 선언할 수 없다.** `actor=None` 이 생략과
   같아서, 행위를 들고 있는 결과에 EXPLICIT_NONE 을 말할 방법이 없다. 즉 §4 의
   C 와 D 를 **입력 경계에서부터** 가를 수 없다.

여기에 공백을 **고치기 어렵게 만드는** 사실 하나를 덧붙인다.

3. 🟡 journal 의 actor 는 `controller` · `payer` 에서 온다. Engine V1 에서는
   값이 같지만 **뜻이 다르다.** 그래서 "journal 의 actor 를 그대로 쓰면 된다"
   가 자명한 해법이 아니다 — `STRUCTURAL_RISK` 로만 적는다.

### 왜 A 가 아닌가

A 는 "semantic contract 에 맞게 생성/전달되고 있으며 **`None` 경계도 설명
가능**" 을 요구한다. 행위가 있는 경로(6개)는 전부 맞다 — Battle 반례까지 두
출처가 독립임을 확인했다. 그러나 **`None` 경계 6개 중 2개(journal)가 설명되지
않는다.** 설명되지 않는 것이 아니라 **틀렸다** — 주체가 있는데 없다고 나온다.

### 왜 B 가 아닌가

B 는 "`None` 경계가 **모두 의도된 것**으로 확인되었고 문서화가 필요하다" 다.
`ProgressionResult`(1) 과 선언-필요 경로(3) 는 B 에 해당한다. **journal 둘은
의도된 것이 아니다** — 값이 거기 있다. 문서를 더 쓰는 것으로 메워지지 않는다.

### 왜 D 가 아닌가

D 는 "현재 코드만으로 actor 의 생성 의미를 확정할 수 없다" 다. 확정했다 —
생성 자리 2곳, 입구 1곳, 7개 result 의 분류, 6개 `None` 경로를 전부 실측으로
적었다. **모르는 것이 아니라 빠진 것**이다.

### 왜 E 가 아닌가

E 는 Engine V1 구조 자체를 바꿔야 하는 문제다. 공백 2개는 **`read()` 한 메서드
안에서** 메울 수 있다 — `getattr(result, "actor", None)` 한 줄과, 생략을
구분하는 보초값 하나다. 주입 2 · 주입 3 이 그 변경이 실제로 작다는 것을
보여준다. `DuelStep` 쪽도 **대입 하나**다. 구조 변경이 아니다.

### 🟡 다만 "공백을 찾았다" 가 "지금 고장났다" 는 뜻은 아니다

production consumer 가 **0** 이다 (§12). 아무도 `context.actor` 를 읽지 않으므로
**지금 틀린 판정이 나오고 있지 않다.** 공백은 `EVENT_RELATION` 을 연결하는
순간부터 **틀린 답**이 되는 자리다. 그래서 §15 가 요구한 대로 **고치지 않고**
발견 · 증거 · 영향 평가 · 다음 Phase 후보까지만 적는다.

---

## 18. 다음 Phase 후보 (1개)

### `read()` 의 actor 입력 경계 설계 — EXPLICIT_NONE 과 MISSING 을 가른다

**감사할 것**, 고칠 것이 아니다. 묻는 것은 하나다.

> `read()` 가 actor 를 정하는 규칙을 **어떻게 계약해야** `INTENTIONALLY_NONE` ·
> `MISSING_ACTOR` · `선언하지 않음` 셋이 받는 쪽에서 구분되는가?

세 설계를 **비용이 아니라 semantic responsibility 로** 비교한다 (3-F-8 과 같은
태도).

| 설계 | 무엇을 바꾸나 | 누가 책임지나 |
| --- | --- | --- |
| A. result 가 자기 actor 를 밝힌다 | `read()` 가 `getattr(result, "actor", …)` 도 본다 | **result** — 7개 타입이 각자 답한다 |
| B. 부르는 쪽이 반드시 선언한다 | 생략을 구분하는 보초값 + 선언 없으면 거부 | **부르는 쪽** |
| C. 문맥이 까닭을 들고 다닌다 | `EventContext` 가 actor 의 출처를 함께 적는다 | **문맥** |

함께 결정해야 하는 것: journal 의 `controller`/`payer` 를 "행위의 주체" 로
읽어도 되는 **범위 조건**(컨트롤 이동이 없는 동안만?)과, `ProgressionResult` 의
의도된 `None` 을 `EventContext` 쪽에 적을 자리.

**C 를 고르면 새 field 가 된다** — 3-F-12 가 금지한 것이므로, 그 Phase 는
금지를 풀 것인지부터 사용자가 정해야 한다. 임의로 진행하지 않는다.

---

## Commit · Push 기록

| 항목 | 값 |
| --- | --- |
| 작업 commit | **`3a10656`** `Phase 3-F-12: audit EventContext actor provenance` |
| 포함 파일 | `tests/test_event_context_actor_provenance.py` **하나뿐** — production 0 |
| push | `6d2f5f4..3a10656` → `origin/claude/pensive-goodall-te1egy` **성공** |
| 보고서 commit | 이 문서 — `Phase 3-F-12: document actor provenance audit` |

작업 직전 HEAD 는 `6d2f5f4` (3-F-11 보고서) 였고, push 결과가 그 SHA 에서
이어진 것으로 확인된다. 작업 commit 이 **테스트 파일 하나만** 담고 있는 것이
AUDIT-ONLY 의 직접 증거다.
