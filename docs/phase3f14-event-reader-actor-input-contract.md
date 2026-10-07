# Phase 3-F-14 — `EventReader.read()` actor 입력 계약 강제

## 1. Phase · Base · 실제 HEAD

| 항목 | 값 |
| --- | --- |
| Phase | 3-F-14 — actor 입력 계약 **구현** (감사가 아니다) |
| 모드 | **production 변경** — `engine/event_pipeline.py` **한 파일** |
| **실제 HEAD (측정)** | `86fc6f5 Phase 3-F-13: document EventReader actor input boundary audit` |
| Base (3-F-13) | `2eef3f9` (작업) · `86fc6f5` (보고서) — **둘 다 실존** (`git cat-file -t`) |
| 3-F-13 최종 판정 | **C. READ_ACTOR_CALLER_MUST_DECLARE** |
| branch | `claude/pensive-goodall-te1egy` |
| baseline 테스트 | 4,362 passed / 4 skipped |
| 신규 테스트 | `tests/test_event_reader_actor_input_contract.py` — **22건** |

### 🟡 먼저: 이 Phase 의 범위가 3-F-13 이 "최소" 라고 적은 것보다 크다

3-F-13 §16 은 최소 변경을 **보초값 도입 + docstring** 으로 잡고, `actor` 필수화는
"36 자리를 바꾸므로 별도 결정" 이라고 적었다. 이번 지시(§4 1 — `read(result)` 는
**실패**해야 한다)는 **그 필수화를 포함**한다. 그래서 실제 작업량이 1파일이 아니라
**9파일**이 되었다.

지시가 명확하므로 **전부 수행했다.** 다만 기록은 정직하게 남긴다 — 이 Phase 는
3-F-13 이 "사용자 승인이 먼저다" 라고 적어 둔 그 승인을 받은 Phase 다.

---

## 2. 기존 → 변경된 signature

### 기존 (3-F-13 까지)

```python
def read(self, result, actor: int | None = None) -> tuple[ObservedEvent, ...]:
    deltas = getattr(result, "deltas", None)
    if deltas is None:
        raise TypeError(f"변화(deltas)를 들고 있는 결과가 필요합니다: …")
    if actor is None:                                              # ← 자동 파생
        actor = getattr(getattr(result, "action", None), "actor", None)
    return self.read_deltas(deltas, actor=actor)

def read_deltas(self, deltas, actor: int | None = None) -> …
def observe(self, result, actor: int | None = None) -> …
def collect(self, result, actor: int | None = None) -> …
```

### 변경 뒤

```python
class _ActorOmitted:
    """``actor`` 를 **넘기지 않았다**는 표시. ``None`` 과 **다른 것**이다."""
    __slots__ = ()
    def __repr__(self) -> str: return "<actor 를 넘기지 않음>"

_ACTOR_OMITTED = _ActorOmitted()        # 하나만 만든다 — ``is`` 로만 비교한다


def read(self, result, actor: "int | None | _ActorOmitted" = _ACTOR_OMITTED) -> …:
    deltas = getattr(result, "deltas", None)
    if deltas is None:
        raise TypeError(f"변화(deltas)를 들고 있는 결과가 필요합니다: …")
    return self.read_deltas(deltas, actor=actor)        # 자동 파생이 **없다**

def read_deltas(self, deltas, actor: "int | None | _ActorOmitted" = _ACTOR_OMITTED) -> …:
    if actor is _ACTOR_OMITTED:
        raise TypeError(
            "actor 를 말해야 합니다. 이 변화를 **누가** 일으켰는지는 부르는 "
            "쪽만 압니다 — 결과나 delta 에서 알아낼 수 없습니다. 행위자가 "
            "있으면 actor=0 또는 actor=1 로, 규칙이 스스로 한 일(페이즈 "
            "전환 등)이면 actor=None 이라고 **적어서** 넘기세요. 생략은 "
            "'행위자가 없다'는 뜻이 아니라 '말하지 않았다'는 뜻입니다."
        )
    base = EventContext.of(self._view, actor=actor)
    …

def observe(self, result, actor: "int | None | _ActorOmitted" = _ACTOR_OMITTED) -> …
def collect(self, result, actor: "int | None | _ActorOmitted" = _ACTOR_OMITTED) -> …
```

### 설계 결정 넷

| 결정 | 이유 |
| --- | --- |
| **보초값 하나**를 모듈 수준에 둔다 | 매번 ``_ActorOmitted()`` 를 만들면 `is` 비교가 **조용히** 깨진다 (고의 위반 5번이 그것을 보여준다) |
| **네 입구 전부** 같은 기본값 | 하나만 `None` 으로 남으면 그리로 들어온 `None` 이 "선언된 None" 으로 보여 **계약의 구멍**이 된다 (고의 위반 4번) |
| 판정은 **`read_deltas` 한 곳** | 같은 규칙을 두 벌 두면 갈린다 — `_timing_for` 가 Phase 2-AJ 에서 실제로 갈려 실제 카드가 한쪽만 죽은 뒤 적어 둔 태도를 그대로 따랐다 |
| `deltas` 검사를 **먼저** | 순서가 뒤집히면 "결과가 틀렸다" 가 "actor 를 안 말했다" 로 보고되어 부르는 쪽이 엉뚱한 곳을 고친다 (고의 위반 6번) |

**`collect_events` 는 `actor` 를 받지 않는다** — 이미 읽어 둔 사건을 받으므로 그때는
actor 가 이미 정해져 있다. 계약을 다시 물을 자리가 아니다.

---

## 3. omitted vs explicit None 계약

| 부르는 모양 | 분류 | 결과 |
| --- | --- | --- |
| `read(r, actor=0)` · `read(r, actor=1)` | **A. ACTOR_DECLARED** | 그 값이 `EventContext.actor` 에 들어간다 |
| `read(r, actor=None)` | **B. INTENTIONAL_NONE** | `EventContext.actor is None` |
| `read(r)` | **C. ACTOR_OMITTED** | 🔴 **`TypeError`** |

**`ACTOR_OMITTED ≠ INTENTIONAL_NONE`.** 이것이 §11 이 말한 핵심 성공 조건이고,
`test_04` 가 한 테스트 안에서 세 모양이 **서로 다른 결과**를 내는 것을 고정한다.

### 에러 semantics (§8)

- **`TypeError`** 를 쓴다. 새 `ValidationCode` 를 만들지 **않았다.**
- `UNKNOWN` 으로도 처리하지 **않았다** — `UNKNOWN` 은 "알 수 없음" 이고 이것은
  **"필수 입력 누락"** 이다.
- 이 모듈의 **기존 관례**다: `EventReader(GameState)` → `TypeError`,
  `read(deltas 없는 결과)` → `TypeError`, `read_deltas(StateDelta 아닌 것)` →
  `TypeError`. 규칙 판정 실패에는 `EventPipelineError` 를 쓰는데, 입력 계약 위반은
  규칙 판정이 아니다. 모듈 전체의 `raise TypeError` 가 **6자리**이고 그중 하나가
  이 Phase 가 더한 것이다 (`test_18`).
- 에러 메시지가 **무엇을 해야 하는지** 말한다 — 계약을 강제하는 에러가 고치는
  방법을 주지 않으면 부르는 쪽이 아무 값이나 넣어 통과시키려 한다 (`test_01`).

---

## 4. 사건별 actor 계약 (§5)

사건의 **이름**으로 정하지 않고 3-F-13 이 측정한 semantic source 를 따랐다.

| Event | 실제 표현 | delta 가 행위자를 담나 | 선언 출처 |
| --- | --- | --- | --- |
| `MonsterSummoned` | 클래스 | 🟢 **담는다** (`player` ≠ `owner`) | `action.actor` |
| `CardDrawn` | 클래스 | 🔴 아니다 — **남을 뽑게 할 수 있다** | 호출자 (`controller`) |
| `LifeChanged` | 클래스 | 🔴 아니다 — 사람 칸이 **당한 쪽** | 호출자 |
| `ZoneMoved` | 클래스 | 🔴 아니다 — 두 칸이 **모두 주인** | 호출자 |
| `PhaseChanged` | 클래스 | — (칸은 있는데 계약이 `None`) | **`actor=None`** |
| `CardDestroyed` | `ZoneMoved(destroy)` | 🔴 **가해자 칸이 없다** | 호출자 |
| `CardAddedToHand` | `ZoneMoved(return_to_hand)` | 🔴 아니다 | 호출자 |
| `CardDiscarded` | `ZoneMoved(discard)` | 🔴 아니다 | 호출자 |
| `CardBanished` | `ZoneMoved(banish)` | 🔴 아니다 | 호출자 |
| `CardReturned` | `ZoneMoved(return_to_deck)` | 🔴 아니다 | 호출자 |

🔴 **그래서 자동 추론은 계약이 될 수 없다.** `MonsterSummoned` 은 행위자를 담고
나머지는 담지 않는데, `read()` 에는 둘을 가릴 근거가 없다. 같은 규칙으로 읽으면
**어떤 사건에서는 행위자를, 어떤 사건에서는 당한 쪽을** 집는다 (`test_11` ·
`test_12` · `test_13` · `test_14`).

### 실제 카드로 확인한 둘

**강욕의 보은 `5915629`** — P0 이 발동하면 **P1 이 2장 드로우한다.** delta 의
`player` · `from_player` · `to_player` 가 **전부 1** 이다. 행위자 0 은 delta 어디에도
없다 → **선언 말고는 출처가 없다** (`test_12`).

**자비의 비 `66719324`** — 한 실행이 **귀속자가 다른 delta 둘**(P0·P1)을 내고
행위자는 **하나**다. 그래서 선언은 **묶음마다 한 번**이고, `EventContext.at(index)`
가 같은 값을 옮겨 적는 설계가 맞다 (`test_14`).

---

## 5. 결과별 actor 계약 (§9)

**실제 call graph 와 객체로 확인했다** — 추측하지 않았다.

| Result | actor 필수 | `actor=None` 허용 | 생략 허용 | 이유 |
| --- | --- | --- | --- | --- |
| `ActionExecution` | **YES** | **YES** | **NO** | `action.actor` 가 있지만 `read()` 는 **보지 않는다.** 행위의 정의상 파생이 안전하긴 하나, 그러면 다른 여섯과 계약이 갈린다 |
| `ActivationResult` | **YES** | **YES** | **NO** | 같다. 비용 없는 발동은 delta 가 0개인데 **입력 계약이 먼저**다 (`test_16`) |
| `EffectEvent` | **YES** | **YES** | **NO** | `actor`(= `controller`) 를 들고 있지만 **지배자이고 행위자가 아니다.** 쓰면 개념을 바꿔 쓰는 것이다 (3-F-13 §5) |
| `CostPaymentEvent` | **YES** | **YES** | **NO** | 같다 (`payer`) |
| `EffectResult` | **YES** | **YES** | **NO** | actor 칸이 **없다.** 상류의 `ResolutionContext.controller` 를 **호출자가** 옮겨 적는다 |
| `CostPaymentResult` | **YES** | **YES** | **NO** | 같다 (`PaymentContext.payer`) |
| `ProgressionResult` | **YES** | **YES** (**이것이 정상**) | **NO** | 세 층 어디에도 사람 칸이 없다. `actor=None` 이 **의미상 올바른** 유일한 경우다 |

### 🟡 "`actor=None` 을 모든 결과에 허용하지 않는다" 를 검토한 결과

§4 가 "실제 코드상 `actor=None` 이 허용되면 안 되는 결과 타입이 있다면 별도 계약을
명시한다" 고 했다. **검토 결과 그런 타입을 만들지 않았다.** 까닭 둘:

1. **거짓 선언은 이미 막지 않는다.** `read(execution, actor=MINE)` 로 공격자를
   거짓말해도 통과한다 (3-F-11 이 "넘기는 쪽의 책임" 으로 고정한 계약이고 `test_09`
   가 그대로 유지한다). `actor=None` 만 특별히 막으면 **거짓의 한 종류만** 막는
   것이고, 일관성이 없다.
2. **막을 근거가 코드에 없다.** "`ActionExecution` 에는 `None` 이 틀렸다" 를
   주장하려면 `read()` 가 `action` 을 봐야 하는데, §7 이 그것을 금지한다. 보지 않고
   막을 수는 없다.

→ **`None` 의 사실 여부는 선언한 쪽의 책임**으로 남긴다. 이 Phase 가 막은 것은
**"말하지 않는 것"** 하나다. 더 막으려면 §7 을 풀어야 하므로 임의로 하지 않는다.

---

## 6. 호출자 전수 조사와 수정 (§5)

### 조사 — AST 로 셌다 (정규식 아님)

| | 3-F-13 측정 | 3-F-14 수정 뒤 |
| --- | --- | --- |
| production 호출 | 1 (모듈 자기 자신) | 1 — `observe` 가 `actor=actor` 로 **그대로 넘긴다** |
| 테스트 호출 | 72 (+ 3-F-13 파일 2 = 74) | 더 늘었다 (신규 파일 포함) |
| **actor 생략** | **38** | 🟢 **0** |
| `actor=None` 명시 | 1 | 여럿 (페이즈 전환 등) |

`test_04`(3-F-13 파일)가 이것을 고정한다 — **"계약을 지키지 않은 생략이 0곳"**.

> 🔴 **측정에 함정이 둘 있었고 둘 다 걸렸다.**
>
> ① `with pytest.raises(TypeError): reader.read(...)` 는 **거부를 시험하는 자리**라서
> 반드시 생략해야 한다. 그것을 위반으로 세면 "생략이 거부된다" 를 시험할 방법 자체가
> 없어진다 → AST 로 `with` 블록의 줄 범위를 구해 `<거부 시험>` 으로 따로 센다.
>
> ② `read(result, **kwargs)` 같은 **전달 헬퍼**는 actor 를 정하는 자리가 아니다 →
> `**` 언패킹이 있으면 `<전달>` 로 센다.
>
> 그리고 ①을 구현하면서 3-F-12 의 `test_13` 이 거부를 `lambda` 로 묶고 있어
> `with` 블록 **밖**으로 나가 있었다 — `lambda` 를 걷어내고 블록 안에서 직접
> 부르도록 고쳤다.

### 수정 — 사건 이름으로 정하지 않고 semantic source 로 정했다

| 자리 | 판단 | 선언 |
| --- | --- | --- |
| `tests/engine/test_event_pipeline.py` 소환 경로 19곳 | `summon_execution` 이 `normal_summon(MINE, …)` 이다 | `actor=MINE` |
| 같은 파일 페이즈 전이 2곳 | **규칙이 하는 일** | `actor=None` |
| 같은 파일 `_UnknownChange` 1곳 | synthetic 변화 — **어떤 행위자도 주장하지 않는다** | `actor=None` |
| 같은 파일 `read(object())` 1곳 | `deltas` 계약을 시험하는 자리 | `actor=MINE` 을 **넘긴다** (넘기지 않으면 어느 계약 위반인지 모호해진다) |
| 4개 감사 파일의 전투·소환 경로 | 행위가 있다 | `actor=execution.action.actor` / `action.actor` |
| 감사 파일의 효과 해결 · journal | 행위를 들고 있지 않다 | 그 테스트가 재던 질문에 맞춰 `actor=None` 또는 `actor=MINE` |
| 3-F-10 `both_actors` 헬퍼 | `actor=None` 을 "안 넘김" 표시로 쓰고 있었다 | 자기 `_UNSET` 을 들게 고쳤다 |

🔴 **`actor=0` 을 일괄 삽입하지 않았다** (§10 금지). 자리마다 무엇이 행위자인지
판단했고, 행위자가 없는 자리는 `None` 을, 행위가 있는 자리는 **그 행위의 actor** 를
적었다.

> 🟡 **헬퍼가 결함을 복제하고 있었다.** 3-F-10 의 `both_actors(…, actor=None)` 은
> `None` 을 "안 넘겼다" 는 표시로 썼다 — `read` 의 기본값이 `None` 이라 통했기
> 때문이다. 그것이 바로 3-F-12 가 찾은 결함과 **같은 모양**이고, 헬퍼 안에서 한 번
> 더 일어나고 있었다. 보초값을 따로 들게 고쳤다.

---

## 7. Battle 사례 (§6)

P1 이 P0 을 공격한다. LP 8000 → **6100**.

```python
read(execution)                  # 🔴 TypeError
read(execution, actor=1)         # ✅ 이것이어야 한다
```

| 항목 | 값 |
| --- | --- |
| delta | `LifeChanged(player=0)` **하나뿐** |
| `TimingEvent.actor` | **0** (귀속 — 맞은 쪽, delta 에서 파생) |
| `EventContext.actor` | **1** (행위 — 공격한 쪽, **선언**) |

그리고 §6 이 금지한 두 구현을 하지 않았다 — `context.actor = timing.actor` 도,
`context.actor = delta.player` 도 없다. `test_09` 가 그것을 **거짓 선언으로**
확인한다: `actor=0` 으로 거짓말하면 그대로 0 이 들어간다. delta 로 덮어쓰면
"부르는 쪽이 책임진다" 가 거짓말이 되기 때문이다 (`test_10`).

---

## 8. production 변경 내역

```
$ git diff --stat -- engine agent app core analysis rules rulings sources scripts
 engine/event_pipeline.py | 107 +++++++++++++++++++++++++++++++-----------
 1 file changed, 89 insertions(+), 18 deletions(-)
```

**한 파일**이다. 417 → 429 (3-F-11) → **500** 줄.

| 바꾼 것 | 바꾸지 않은 것 |
| --- | --- |
| `_ActorOmitted` · `_ACTOR_OMITTED` 추가 (비공개 — `__all__` 에 없다) | `EventContext` 구조 (칸 다섯 그대로) |
| 네 입구의 `actor` 기본값 | `TimingEvent.actor` · `ObservedEvent.actor` |
| `read` 의 자동 파생 **삭제** | `EventContext.of` signature |
| `read_deltas` 의 거부 추가 | `engine/trigger.py` (귀속자 계약) |
| `read` · `read_deltas` · `observe` · `collect` · `EventContext.actor` docstring | `EVENT_RELATION` · `TriggerRegistry` · trigger pipeline |

**§9 의 금지 항목 전부 미실행**: `cause_player` · `affected_player` ·
`action_player` · `source_player` · `actor_player` · `ActorKind` · `ActorSource` ·
`EventActor` · 새 Player API — **하나도 없다** (`test_19` · `test_20`).

### 🟢 dormant 는 그대로다

`engine.event_pipeline` 의 production importer 는 **여전히 0개**다. 바뀐 것은
**아무도 부르지 않는 입구의 입력 계약**이므로, Engine V1 의 실행 경로는 한 줄도
달라지지 않았다.

---

## 9. 테스트

### 신규 `tests/test_event_reader_actor_input_contract.py` — 22건

| # | 무엇을 고정하나 | §10 항목 |
| --- | --- | --- |
| 01 | 생략 → 거부. 에러가 **무엇을 해야 하는지** 말한다 | 1 |
| 02 | `actor=None` → 성공, 행위자 없음 (페이즈 전환) | 2 · 6 |
| 03 | `actor=0` · `actor=1` → 그대로 들어온다 (parametrize) | 3 · 4 |
| 04 | 🟢 **세 모양이 세 가지 다른 결과** — 이 Phase 의 성공 조건 | 14 |
| 05 | 네 입구가 **같은 보초값 하나**를 쓴다 · 비공개다 | 11 |
| 06 | 판정이 **한 곳**에만 있다 | — |
| 07 | `EventPipeline.observe`/`collect` 도 거부한다 | — |
| 08 | 🔴 **여섯 자동 추론이 전부 없다** | 11 |
| 09 | 선언을 delta 로 **덮어쓰지 않는다** (거짓 선언이 통과한다) | 11 · 12 |
| 10 | **Battle** — 생략 거부 + 두 뜻 보존 | 5 · 13 |
| 11 | `MonsterSummoned` — delta 가 담아도 선언은 따로 | 7 |
| 12 | 🔴 **강욕의 보은** — 선언이 유일한 출처 | 8 |
| 13 | `ZoneMoved` 5개 — 가해자 칸 없음 + 도착지 주인 | 10 |
| 14 | 🔴 **자비의 비** — 귀속자 둘, 행위자 하나 | 9 |
| 15 | **일곱 result 전부** 생략을 거부한다 | — |
| 16 | `ActivationResult` — delta 0개여도 입력 계약이 먼저 | — |
| 17 | `deltas` 계약이 actor 계약보다 **먼저** 검사된다 | — |
| 18 | 새 `ValidationCode` 없음 · `UNKNOWN` 아님 | — |
| 19 | production 변경이 한 파일 · dormant 유지 · 금지 항목 없음 | — |
| 20 | `EventContext`·`TimingEvent`·`ObservedEvent` 구조 불변 | — |
| 21 | `state_hash` · RNG · hidden-information 불변 | — |

**"`None` 이면 실패" 테스트를 만들지 않았다.** `test_02`·`test_13`(일부)·`test_15`
는 `None` 을 **기대**하고, 각 `None` 이 `INTENTIONAL_NONE` 인지 거부 대상인지를
테스트 이름과 주석에 적었다.

### 고의 위반 검증 — 8건, 전부 잡혔다

| # | 위반 | 잡은 테스트 수 |
| --- | --- | --- |
| 1 | 기본값을 `None` 으로 되돌린다 (**계약 제거**) | **14건** |
| 2 | `action.actor` 자동 파생을 되살린다 (§7 위반) | **13건** |
| 3 | `delta.player` 자동 파생 (§3 · §6 위반) | 5건 |
| 4 | `observe`/`collect` **만** 기본값 `None` (계약의 구멍) | 2건 — `test_05` · `test_07` |
| 5 | 보초값을 **매번 새로** 만든다 (`is` 가 조용히 깨진다) | **14건** |
| 6 | actor 검사를 `deltas` 검사보다 **먼저** 한다 (§8 순서) | 4건 |
| 7 | 새 `ValidationCode`/`EventPipelineError` 로 처리 (§8 위반) | **14건** |
| 8 | `EventContext` 에 `actor_source` 칸을 더한다 (§9 위반) | 2건 — `test_14` · `test_20` |

4번과 8번이 중요하다 — **구멍 하나, 칸 하나**를 정확히 집는다. 5번은 "같아 보이지만
조용히 깨지는" 변경이고, 그것이 14건을 깨뜨린다는 것이 보초값을 하나로 둔 까닭이다.

주입 파일 1개(`engine/event_pipeline.py`)는 매번 백업에서 복원하고 md5 로 확인했다
(8회 전부 `OK`).

### 전체 회귀

| 실행 | 결과 |
| --- | --- |
| 1회차 (production 만 바꾼 직후) | `48 failed, 4314 passed, 4 skipped` |
| **2회차 (최종)** | **`4384 passed, 4 skipped in 443.38s`** |

`4,362` (3-F-13) `+ 22` (신규) `= 4,384`. 실패 0 · skip 그대로 4건.

**1회차의 48 실패가 이 Phase 의 작업량 그 자체다.** 계약을 바꾸면 그 계약에
의존하던 테스트가 깨지는 것이 정상이고, 48건을 **자리마다 판단해서** 고쳤다 —
호출에 선언을 더한 것과, 낡은 계약을 pin 하고 있던 것 두 종류다 (아래 표).

`-p no:randomly` 로 돌렸다.

### 기존 테스트 처리 — §10 · §13 의 금지를 전부 지켰다

**삭제 0건 · skip 추가 0건 · assertion 약화 0건 · 무의미한 `actor=0` 일괄 삽입 0건.**

수정은 **7개 파일**이고 두 종류다.

#### (가) 호출 자리에 선언을 더한 것 — 의미 변화 없음

| 파일 | 수정 |
| --- | --- |
| `tests/engine/test_event_pipeline.py` | 23곳 (소환 19 · 페이즈 2 · synthetic 1 · 거부 1) |
| `tests/test_timing_event_actor_semantic_audit.py` | 3곳 |
| `tests/test_actor_role_separation_audit.py` | 헬퍼 1 + 2곳 |
| `tests/test_actor_semantic_contract.py` | 헬퍼 1 |

#### (나) **낡은 계약을 pin 하고 있던 것** — 이유를 각 테스트의 `.. note::` 와 아래에 적었다

| 테스트 | 무엇을 pin 하고 있었나 | 어떻게 고쳤나 |
| --- | --- | --- |
| 3-F-12 `test_12` | 🔴 "`actor=None` 이 생략과 **같은 값**" | 세 모양이 **다르다**로. 단정 5 → **9** |
| 3-F-12 `test_13` | 🔴 "`read` 는 못 하고 `read_deltas` 만 할 수 있다" (**비대칭**) | **대칭**으로 |
| 3-F-12 `test_03` | 겹 `getattr` 이 **있다** (`count == 3`) | **없다** (`count == 1`) |
| 3-F-12 `test_07` | journal actor 를 안 봐서 조용히 `None` | 안 보는 것은 그대로, 다만 **거부로 드러난다** |
| 3-F-12 `test_08` | `read` 설명이 **셋만** 예로 든다 | **일곱**을 전부 적는다 |
| 3-F-12 `test_09`·`test_11`·`test_16`·`test_17` | 생략 시의 값 | 거부 + 선언 |
| 3-F-12 `test_22` | `git diff HEAD` 가 비었다 | **자기 commit** `3a10656` 을 본다 (아래 참조) |
| 3-F-13 `test_01` | 기본값이 **`None`** | 기본값이 **보초값**, 넷이 **같은 것** |
| 3-F-13 `test_04` | 🔴 "**절반이 선언하지 않는다**" (36/72) | **"생략이 0곳"** — 고정 대상이 뒤집혔다 |
| 3-F-13 `test_07` | 생략 → `action.actor` 가 들어온다 | 생략 → **거부** |
| 3-F-13 `test_08` | 🔴 "구별되지 않는다" | **구별된다** |
| 3-F-13 `test_18` | 🔴 `OMITTED_INPUT` 이 **존재한다** | 그 분류가 **사라졌다** |
| 3-F-13 `test_19` | `CostPaymentResult` 가 설명에 **없다** | 이제 있다. 🟡 다만 분류는 `UNKNOWN` 그대로 |
| 3-F-13 `test_22` | `read` 본문 전문 + `git diff HEAD` | **자기 commit** `2eef3f9` 을 본다 |
| 3-F-11 `test_02` | `None` 의 까닭이 **둘** | **하나** + `TypeError` |
| 3-F-11 `test_09` | 선언 안 하면 `None` | 선언 안 하면 **거부**. 이름도 바꿨다 |
| 3-F-10 `test_02` | 세 단계 fallback (`action` 이 본문에 있다) | 두 단계 + fallback **부재** |
| 3-F-10 `test_03` | 설명이 `EffectResult` 를 예로 든다 | 까닭이 하나라고 적혀 있다 |
| 3-F-9 `test_13` | `read` 본문에 `action` 이 있다 | **없다** |
| dormant `test_02`·`test_25` | `event_pipeline.py` 429줄 | **500줄** + 왜 늘었는지 |

#### 🔴 `test_22` 두 개를 고친 방법이 특히 중요하다

3-F-12·3-F-13 의 `test_22` 는 `git diff HEAD -- engine …` 이 비어 있는지를 봤다.
그것은 **"지금 작업 나무가 깨끗한가"** 이지 **"그 Phase 가 무엇을 바꿨나"** 가
아니다. 뒤의 Phase 가 production 을 바꾸는 순간 — 이번에 그렇게 되었다 — 그
단정은 **남의 변경 때문에** 깨진다. **재려던 것과 잰 것이 달랐다.**

그래서 **각 Phase 의 작업 commit 자체**를 보도록 고쳤다
(`git show --stat 3a10656` · `2eef3f9`). 그 목록은 영원히 바뀌지 않으므로 뒤의
어떤 Phase 에도 흔들리지 않는다. 같은 자리에서 `read` 본문 전문을 고정하던 것도
빼고, §9 금지 항목 확인으로 바꿨다 — 그것은 **어느 Phase 에서도 참이어야 하는 것**
이다.

이것은 3-F-11 이 줄 번호 snapshot 에서 배운 것과 같은 교훈의 반복이다. **뒤의
Phase 때문에 깨지는 단정은 잘못된 것을 재고 있다.**

---

## 10. state_hash / RNG / Search / AI 영향 (§13)

| 항목 | 결과 | 근거 |
| --- | --- | --- |
| `state_hash` | **불변** | 선언해 읽든, "없다" 고 읽든, **거부당해도** `state_hash()` 가 동일 (`test_21`) |
| RNG | **불변** | `repr(state.rng)` 동일 · 같은 seed 두 번 → 같은 `state_hash` |
| hidden-information | **불변** | `EventReader(GameState)` 는 여전히 `TypeError`. 상대 패·덱은 `concealed` |
| Search ranking | **불변** | digest `30fa3597…402c4175` (6 duel · 611 decision) — 기존 3개 파일이 고정하고 전체 회귀에서 통과 |
| AI behavior | **불변** | `agent/` 는 `event_pipeline` 을 import 하지 않는다 (importer 0) · `action.actor` 만 읽는다 |
| Engine V1 freeze | **유지** | dormant 모듈의 입구만 바뀌었다 — 실행 경로 0 |
| §12 금지 | **전부 미실행** | `EVENT_RELATION` ✗ · `TriggerRegistry` ✗ · `EventBus` ✗ · pipeline 활성화 ✗ |

---

## 11. 최종 판정

### **A. ACTOR_INPUT_CONTRACT_ENFORCED**

**생략과 explicit None 이 구분되고, caller declaration 계약이 실제 API 에 안전하게
반영되었다.**

근거 넷.

1. **세 모양이 세 결과를 낸다** — 생략은 `TypeError`, `actor=None` 은 `None`,
   값은 그 값. `test_04` 가 한 테스트 안에서 확인한다.
2. **입구 넷이 전부 막혀 있다** — `read` · `read_deltas` · `observe` · `collect` 가
   같은 보초값 하나를 쓴다. 하나만 열려 있어도 계약이 새는데, 고의 위반 4번이 그
   구멍을 정확히 집는다.
3. **자동 추론이 하나도 남지 않았다** — 여섯 경로를 코드와 실측으로 확인했고,
   되살리는 주입 둘(2·3)이 각각 13건·5건을 깨뜨린다.
4. **생략 호출이 0곳이다** — 38곳을 자리마다 판단해서 고쳤고, 새 생략이 들어오면
   `test_04`(3-F-13)가 걸린다. 계약이 **문서가 아니라 측정으로** 지켜진다.

### 왜 B(PARTIAL)가 아닌가

B 는 "구조적으로 남은 예외가 있음" 이다. 입력 경계에서는 **예외가 없다** — 일곱
result 전부 같은 계약이고 (`test_15`), delta 수가 0이어도 입력을 먼저 본다
(`test_16`).

🟡 **다만 경계 **밖**에 문 하나가 남아 있다는 것을 적어 둔다.**
`EventContext.of(view)` 는 여전히 `actor=None` 기본값을 갖는다. 이 Phase 가 §3 의
"`EventContext` 구조 변경 금지" 를 지켜 손대지 않았다. 그 문으로 들어가려면
`ObservedEvent` 를 직접 조립해야 하고 — 즉 **`EventReader` 를 우회해야** 하고 —
production 과 테스트에 그런 자리는 **하나도 없다**. 입력 경계(`read` 계열)의 계약은
완전하므로 A 로 판정하되, 이 문을 B 의 근거로 삼지 않은 이유를 여기 남긴다.

### 왜 C(BLOCKED)가 아닌가

막히지 않았다. 변경은 **한 파일 89줄**이고, `EventContext` 구조도 `ValidationCode` 도
건드리지 않았다.

### 왜 D(NOT_NEEDED)가 아닌가

필요했다. 3-F-12 가 측정한 `OMITTED_INPUT` 은 **실재했고** (강욕의 보은:
행위자가 P0 으로 존재하는데 조용히 `None` 이 되었다), 3-F-13 이 호출자 36/72 가
생략한다는 것을 셌다. 지금은 그 분류가 **사라졌다** (`test_18`).

### 🟡 고치지 **않은** 것 — 정직하게 남긴다

1. **journal 의 actor 를 여전히 쓰지 않는다.** `EffectEvent.actor` 가 객체에
   있는데 `read()` 는 보지 않는다. 3-F-12 가 `MISSING_ACTOR` 로 분류한 그
   자리이고, §7 이 `controller` 자동 추론을 금지하므로 이 Phase 에서 고칠 수 없다.
   **고친 것은 "말하지 않아도 통과하는 것" 이고, "무엇을 말해야 하는지" 가 아니다.**
2. **거짓 선언은 막지 않는다.** `actor=0` 으로 공격자를 거짓말해도 통과한다.
   3-F-11 의 "넘기는 쪽의 책임" 계약이 그대로다.
3. **`CostPaymentResult` 의 분류는 `UNKNOWN` 그대로다.** 설명에 이름은 올랐지만
   무엇을 선언해야 하는지는 코드가 말해 주지 않는다.

---

## 12. 다음 Phase 후보 (1개)

### `EffectResult` · journal 사건의 actor 를 **누가 어떻게 옮겨 적는가** 설계 감사

이번 Phase 로 "말하지 않으면 거부된다" 가 되었다. 남은 질문은 **그 반대쪽**이다.

> 행위를 들고 있지 않은 결과(`EffectResult` · `CostPaymentResult` · journal 사건
> 둘)에서, 호출자는 **무엇을 선언해야 하는가?** 그리고 그 값을 어디서 가져오는 것이
> 옳은가?

조사할 것:

1. `ResolutionContext.controller` · `PaymentContext.payer` 를 "행위의 주체" 로 쓰는
   **범위 조건** — 컨트롤 이동이 없는 동안만 참인가? 참이 아니게 되는 조건은
   무엇인가?
2. `EffectEvent.actor` 가 객체에 있는데 호출자가 **옮겨 적어야** 하는 것이 옳은
   설계인가, 아니면 그 result 가 actor 를 밝히는 계약을 가져야 하는가? (3-F-13 의
   설계 A 를 **타입을 좁혀** 다시 검토하는 것이다 — 전면 파생이 아니라
   "자기 actor 를 가진 result 만".)
3. 그 둘을 정하면 `CostPaymentResult` 의 `UNKNOWN` 분류가 해소되는가?

**새 field 를 만들지 않는 범위에서 가능한지**부터 본다. 가능하지 않다면 그 사실을
근거와 함께 보고하고, 금지를 풀 것인지는 사용자가 정한다.

**시작하지 않는다.** 다음 Phase 는 임의로 진행하지 않는다.

---

## 13. Commit · Push 기록

| 항목 | 값 |
| --- | --- |
| 작업 commit | **`c016992`** `Phase 3-F-14: enforce EventReader actor input contract` |
| production | `engine/event_pipeline.py` **하나** (+89 / −18) |
| 테스트 | 신규 1 · 수정 7 |
| push | `86fc6f5..c016992` → `origin/claude/pensive-goodall-te1egy` **성공** |
| 보고서 commit | 이 문서 — `Phase 3-F-14: document EventReader actor input contract` |

작업 직전 HEAD 는 `86fc6f5` (3-F-13 보고서) 였고, push 결과가 그 SHA 에서 이어진
것으로 확인된다.

> 🟡 **이 Phase 는 3-F 계열에서 production 코드를 바꾼 두 번째 Phase 다** (첫
> 번째는 3-F-11 이고 그것은 docstring 뿐이었다). 그래서 앞 Phase 들처럼 "작업
> commit 이 테스트 파일 하나" 라는 증거는 쓸 수 없고, 대신 **production diff 가
> 한 파일인 것**과 **dormant importer 가 0인 것**이 범위의 증거다.
