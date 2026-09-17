# Phase 2 Architecture Decision Records

**기준 커밋:** `7450109`
**상태:** 결정 완료 · 구현 전
**범위:** Action / Effect / Execution Authority 의 **계약**만 확정한다.
Phase 2 코드는 이 문서에서 작성하지 않는다.

---

## 0. 이 문서를 쓰기 전에 확인한 것

ADR 을 쓰기 전에 repository 를 직접 검사했다. **이미 결정되어 있는 것을 다시
결정하지 않기 위해서다.**

### 이미 존재하는 설계

`docs/duel-engine-design.md` 에 이번 주제의 상당 부분이 **이미 설계되어
있었다.** 아래 ADR 들은 그것을 뒤집는 것이 아니라 **확정 · 정정 · 보강**한다.

| 기존 절 | 이미 결정되어 있던 것 |
|---|---|
| §9 `Action / Legal Action` | "`Destroy` / `Banish` / `AddToHand` / `Discard` / `Send` 는 Action 이 아니라 효과의 결과다" |
| §10 `Legal Action 생성` | `LEGAL` / `PLAUSIBLE` / `ILLEGAL` 3등급, 기본은 `LEGAL` 만 반환 |
| §11 `Effect Resolution` | `EffectRef → EffectRegistry.lookup() → ExecutionPlan → StateDelta`, `TEXT_DERIVED` 실행 거부 |
| §12 `Chain` | `ChainLink` 가 `effect: EffectRef` 를 **참조**하는 구조 |
| §13 `State Transition` | `StateDelta` 만이 상태를 바꾼다 |
| §16 `AI 경계` | 읽기 전용 뷰 + `Action` 객체만 반환 |

즉 **ADR-001 · 002 · 003 · 004 · 007 · 008 의 방향은 이미 설계에 있었다.**
이번 작업의 실질은 (a) 그 결정을 ADR 로 못박고, (b) 코드를 실측해서 **설계가
틀렸거나 불충분한 지점을 찾아내는 것**이었다. 실제로 세 가지를 찾았다.

### 검사에서 발견한 실제 충돌 3건

#### 🔴 충돌 1 — `ActionKind` 라는 이름이 이미 정반대 의미로 쓰이고 있다

`analysis/effect_model.py:25` 에 `ActionKind` 가 **이미 있다.**

```python
class ActionKind(str, Enum):
    """효과가 실제로 하는 일. Lua 의 ``Duel.*`` 호출에서 유도한다."""
    SPECIAL_SUMMON = "special_summon"
    TO_HAND = "to_hand"
    TO_GRAVE = "to_grave"
    BANISH = "banish"
    DESTROY = "destroy"
    ...
```

이것은 **Effect semantics** 다. 그런데 `docs/duel-engine-design.md` §9 의
Action 모델은 `kind: ActionKind` 라고 적혀 있다. 같은 이름이 한쪽에서는
"플레이어의 의도", 다른 쪽에서는 "효과의 결과"를 뜻한다.

**이대로 Phase 2 를 시작하면 `from analysis.effect_model import ActionKind`
한 줄로 `DestroyAction` 이 생긴다.** ADR-001 이 이 문제를 처리한다.

그리고 이 충돌은 가설이 아니다. **멤버 하나에서 이미 실현되어 있다** —
아래 ADR-001 의 `normal_summon` 항목을 보라.

#### 🔴 충돌 2 — `ACTION_DESTINATION` 이 Destroy 와 Send 를 이미 합쳐 놓았다

`analysis/effect_model.py:52`:

```python
ACTION_DESTINATION = {
    ActionKind.TO_GRAVE: "GRAVE",
    ActionKind.DESTROY:  "GRAVE",   # ← 같은 값
    ActionKind.DISCARD:  "GRAVE",   # ← 같은 값
    ActionKind.RELEASE:  "GRAVE",   # ← 같은 값
    ...
}
```

`Destroy` · `Send to GY` · `Discard` · `Release` 가 전부 `"GRAVE"` 다.
콤보 탐색용 휴리스틱으로는 타당하지만 (네 경우 모두 결과적으로 묘지에
있게 되므로), **실행 의미로 쓰면 `Destroy ≠ Send to Graveyard` 가 무너진다.**
ADR-002 가 이 표의 사용 범위를 못박는다.

#### 🟠 충돌 3 — 설계 §11 의 실행 권위 표가 낡았다

설계 §11 은 이렇게 적혀 있다.

| 상태 | 설계 문서 | **실측 (`7450109`)** |
|---|---:|---:|
| `lua_verified` | 12,687 | **12,968** |
| `text_derived` | 1,440 | **806** |
| `no_effect` | (없음) | **746** |

`no_effect` 가 설계 문서에 아예 없다. 1,440 은 `no_effect` 가 도입되기
(커밋 `9bf690a`) 전의 숫자이고, 그때는 통상 몬스터 746장이 `text_derived` 에
섞여 있었다. 설계대로 `text_derived` 를 차단하면 **푸른 눈의 백룡이 듀얼에
나올 수 없었다.** 이 표를 이 문서에서 정정한다.

> 측정 명령 (`include_alternates=True`):
> ```python
> repo = CardRepository.build(db_path="data/cards.cdb", script_dir=".")
> Counter(c.provenance.analysis_status for c in repo.all_cards(include_alternates=True))
> ```
> 다른 일러스트를 제외하면 (`include_alternates=False`, 기본값)
> 12,687 / 756 / 684 · 총 14,127 이다. 설계 §11 의 12,687 은
> **`lua_verified` 만 우연히 일치**하고 나머지는 맞지 않는다.

### 충돌하지 않은 것

- Phase 1 `GameState` 는 이 구조를 **그대로 수용한다.** `chain` · `pending` ·
  `journal` 이 이미 자리표시로 있고 (`game_state.py:100-105`), `clone()` 과
  `state_hash()` 가 결정론적이다.
- `engine` 은 `analysis` 에서 **심볼 하나만** 가져온다
  (`use_registry.py:32` 의 `LimitScope`). `core` 는 `TYPE_CHECKING` 밖에서
  가져오지 않는다. 경계가 이미 깨끗하다.
- `rules/` 는 초급 룰북(Starter Deck Rulebook)이라 `Destroy` / `Send` 구분을
  **다루지 않는다.** ADR-002 의 근거를 룰북에서 끌어올 수 없다는 뜻이고,
  그래서 Lua 상수에서 끌어왔다. 없는 근거를 있다고 하지 않는다.
- `rulings/` 의 신뢰 경계는 이미 완성되어 있다
  (`tests/rulings/test_identity_trust_boundary.py`, 21개 테스트).

---

## ADR-001 — Action 과 Effect 의 책임 분리

### Context

현재 repository 에는 `Action` 이라는 이름이 **한 곳에만** 있고, 그것은
Phase 2 가 말하는 Action 이 아니다.

- `analysis.effect_model.ActionKind` — **효과가 하는 일** (DESTROY, BANISH, TO_GRAVE…)
- `analysis.effect_model.EffectAction` — 효과가 일으키는 처리 하나
- `engine/` 에는 Action 이 **없다** (Phase 1 은 상태만 다룬다)

설계 문서 §9 는 Phase 2 의 Action 을 `kind: ActionKind` 로 적어 두었는데,
그 이름이 이미 정반대 의미로 점유되어 있다.

### Decision

**1. Action 은 "선택 주체가 고르는 것"이다.**

Action 은 *플레이어 또는 게임 시스템이 무엇을 하려고 하는가* 를 표현한다.
AI 가 후보 목록에서 **고를 수 있는 것**만 Action 이다.

```
Action 인 것          Activate · NormalSummon · TributeSummon · Set
                      FlipSummon · ChangePosition · DeclareAttack
                      Draw(규칙 드로우) · Pass · EndPhase

Action 이 아닌 것     Destroy · Banish · Send · Return · Discard
                      AddToHand · ChangeControl · ChangeATK
```

**2. Effect 는 "효과 해결이 만들어내는 의미 있는 변화"다.**

Effect 는 AI 가 고르지 않는다. 카드 효과의 resolution 에서 발생한다.

**3. 이름 충돌을 코드로 막는다.**

Phase 2 는 `analysis.effect_model.ActionKind` 를 **import 하지 않는다.**
엔진의 Action 어휘는 `engine/` 안에 새로 만들고, 이름도 겹치지 않게 한다.

| 계층 | 타입 | 의미 |
|---|---|---|
| `analysis` | `ActionKind` (기존, 변경 없음) | 효과가 하는 일 = **Effect semantics** |
| `engine` | `PlayerActionKind` (Phase 2-A 신설) | 선택 주체가 고르는 행위 |
| `engine` | `EffectOperation` (Phase 2-C 신설) | 효과 해결이 만드는 변화 |

`analysis.ActionKind` 의 이름은 **바꾸지 않는다.** 이미 안정적으로 쓰이고
있고 (`effect_analyzer.py`, `text_effect_analyzer.py`, `__init__.py`,
관련 테스트), 이름을 바꾸면 이번 작업이 "설계 결정"에서 "리팩터링"으로
번진다. 대신 엔진 쪽 이름을 명시적으로 다르게 짓는다.

### Rationale

Action 과 Effect 를 합치면 **AI 가 규칙을 계산하게 된다.**

`DestroyAction` 이 존재하면 AI 는 "카드 B 를 파괴한다"를 직접 고를 수 있고,
그 순간 "파괴할 수 있는가" 를 판정하는 책임이 AI 로 넘어간다. 엔진이
강제해야 할 규칙이 AI 의 추론으로 대체되는 것이다.

#### 실측 근거 — 충돌은 이미 한 멤버에서 실현되어 있다

`analysis.ActionKind` 18개 멤버 중 17개는 플레이어가 고를 수 없는 것들이다
(`destroy`, `banish`, `to_grave`, `to_hand`, `discard` …). Action 어휘로
쓸 수 없다.

**그런데 `normal_summon` 하나가 겹친다.** 그리고 이것이 이 ADR 의 가장 좋은
증거다 — 같은 문자열이 두 가지를 뜻한다.

| | `analysis.ActionKind.NORMAL_SUMMON` | Phase 2 `PlayerActionKind.NORMAL_SUMMON` |
|---|---|---|
| 뜻 | 효과 해결 중 `Duel.Summon` 이 호출된다 | 플레이어가 이번 턴의 일반 소환권을 쓰기로 **고른다** |
| 유래 | `effect_analyzer.py:101` 의 `"Summon" → NORMAL_SUMMON` | 아직 없음 (Phase 2-A) |
| 실측 | **74개 효과** (교차하는 혼, 아르카나 리딩, 후완다리즈×토칸 …) | — |
| 소환권 | 소비할 수도, 안 할 수도 있다 | **반드시** 소비한다 |
| 선택 주체 | 없음 — 효과가 수행한다 | 플레이어 / AI |

이름이 같다고 합치면 **서로 다른 두 규칙이 하나가 된다.** "효과가 일반
소환을 수행했다"와 "플레이어가 일반 소환권을 썼다"는 다른 사건이고,
후자만 그 턴의 소환권을 소모한다.

> 이 문단의 초안에는 "18개 멤버 중 플레이어가 고르는 행위는 하나도 없다"고
> 적혀 있었다. `Contract E` 를 실행했더니 `normal_summon` 에서 실패했다.
> 실제 데이터가 더 강한 근거를 준 경우다.

### Alternatives considered

| 대안 | 기각 이유 |
|---|---|
| `analysis.ActionKind` 를 `EffectOperationKind` 로 개명 | 이번 작업 범위를 벗어나는 리팩터링. 4개 모듈 + 테스트가 걸린다. 개명해도 Phase 2 가 그것을 Action 으로 쓰는 것을 막지 못한다 |
| Action 을 "엔진이 실행하는 모든 상태 전이"로 넓게 정의 | `Destroy` 가 Action 이 되고, AI 후보 목록에 섞인다. 정확히 피하려는 것 |
| 하나의 `Operation` 계층으로 통합 | 선택 가능성(choosable)과 실행 결과가 한 타입이 되어, 후보 생성기가 무엇을 걸러야 할지 타입으로 알 수 없다 |

### Consequences

- Phase 2-A 는 `engine/` 에 **새 Action 어휘**를 만든다. 기존 것을 재사용하지 않는다.
- 후보 생성기는 `PlayerActionKind` 만 나열한다. `EffectOperation` 은 나열 대상이 아니다.
- `Contract E` 가 이 분리를 감시한다.

> **구현 결과 (Phase 2-A).** `engine/action.py` 의 `PlayerActionKind` 10개 중
> `DESTROY` / `BANISH` / `SEND` / `DISCARD` / `RELEASE` 는 없다.
> `Contract E` 는 처음에 문자열 검색이었는데, `engine/action.py` 의 설명글이
> 두 어휘의 차이를 **설명하려고** `analysis.ActionKind` 를 언급하는 바람에
> 오탐이 났다. 지금은 AST 로 **실제 사용**만 본다 — 설명은 막을 것이 아니라
> 있어야 할 것이기 때문이다.

### Future implications

`Activate` Action 이 `EffectRef` 를 들고 있고, 그 효과의 해결이
`EffectOperation` 을 낳는다. 이 방향은 단방향이다 — `EffectOperation` 에서
`Action` 이 만들어지는 경로는 없다.

---

## ADR-002 — Destroy / Banish / Send / Return 의 의미론적 위치

### Context

Phase 1 의 존 primitive 는 이렇다.

```python
move_card(card, source, destination, *, index=None, position=None)
```

**이유(reason)를 받지 않는다.** 순수하게 기계적인 이동이다.

한편 `engine/vocabulary.py` 는 `REASON_*` 를 이미 노출하고 있다
(`vocabulary.reasons`). 실측값:

```
REASON_DESTROY = 0x1        REASON_EFFECT  = 0x40
REASON_RELEASE = 0x2        REASON_COST    = 0x80
REASON_BATTLE  = 0x20       REASON_RETURN  = 0x20000
```

**비트마스크다.** 효과에 의한 파괴는 `REASON_DESTROY | REASON_EFFECT` = `0x41`
이고, 전투에 의한 파괴는 `REASON_DESTROY | REASON_BATTLE` = `0x21` 이다.

### Decision

**1. 네 가지 모두 Effect semantics 다. Action 이 아니다.**

```
Destroy → EffectOperation + REASON_DESTROY
Banish  → EffectOperation + REASON_EFFECT (목적지 REMOVED)
Send    → EffectOperation + REASON_EFFECT (목적지 GRAVE, DESTROY 없음)
Return  → EffectOperation + REASON_RETURN
```

**2. 저수준 이동과 고수준 의미를 두 계층으로 나눈다.**

| 계층 | 위치 | 하는 일 |
|---|---|---|
| Low-level | `engine.state.zones.move_card` (Phase 1, **변경 없음**) | 존 사이 이동. 이유를 모른다 |
| High-level | `EffectOperation` (Phase 2-C) | "왜 움직였는가"를 `REASON_*` 로 들고 있다 |

`move_card` 를 고치지 않는다. Phase 1 에서 잘 동작하고 있고, 이유를
붙이는 것은 그 위 계층의 일이다.

**3. `Destroy` 와 `Send to GY` 를 구분하는 것은 목적지가 아니라 reason 이다.**

둘 다 묘지로 간다. **목적지로는 절대 구분할 수 없다.** 구분은
`REASON_DESTROY` 비트가 서 있는가 하나뿐이다.

**4. `ACTION_DESTINATION` 은 실행 의미로 쓰지 않는다.**

`analysis/effect_model.py:52` 의 이 표는 `DESTROY` · `TO_GRAVE` ·
`DISCARD` · `RELEASE` 를 전부 `"GRAVE"` 로 매핑한다. 이것은 **분석 ·
콤보 탐색용 휴리스틱**이고, 그 목적에는 정확하다. 그러나 Phase 2 의
`EffectOperation` 은 이 표를 참조하지 않는다.

### Rationale

게임 규칙상 `Destroy` 와 `Send to GY` 는 **다른 사건**이다.

- "파괴되었을 때" 트리거는 `Send` 로는 발동하지 않는다
- 파괴 내성("효과로 파괴되지 않는다")은 `Send` 를 막지 못한다
- 파괴 대체 효과(스타더스트 드래곤 류)는 `Send` 에 개입하지 않는다

이 셋이 전부 `REASON_DESTROY` 비트 하나에 달려 있다.

실측 근거: 설계 §7 의 조건 술어 집계에서 `event_reason` 술어가 **928건**
쓰인다. 즉 928개의 효과가 "무슨 이유로 일어났는가"를 실제로 물어본다.
reason 을 버리면 이 928건을 평가할 수 없다.

**룰북 근거는 없다.** `data/rules/structured/sd-rulebook-en-v10.json` 을
검색했으나 초급 룰북이라 `Destroy` / `Send` 구분을 다루지 않는다
(`"Monster Cards sent here when destroyed"` 한 줄뿐). 없는 근거를 지어내지
않고, Lua 상수를 근거로 삼는다.

### Alternatives considered

| 대안 | 기각 이유 |
|---|---|
| `move_card` 에 `reason` 파라미터 추가 | Phase 1 이 규칙 어휘를 갖게 된다. 그리고 reason 은 이동 하나가 아니라 **사건 전체**의 속성이다 (파괴되었지만 이동하지 않는 경우도 있다) |
| `DestroyOperation` / `SendOperation` 을 별도 클래스로 | 조합 폭발. `REASON_DESTROY \| REASON_BATTLE \| REASON_EFFECT` 조합이 클래스 수로 나타난다 |
| 목적지로 구분 | **불가능하다.** 둘 다 GRAVE 다 |
| `ACTION_DESTINATION` 을 고쳐서 구분 | 그 표의 목적(콤보 탐색)에는 지금이 맞다. 분석용 표를 실행용으로 개조하면 두 용도 모두 나빠진다 |

### Consequences

- `EffectOperation` 은 `reason: int` (REASON_* 비트마스크) 를 **필수로** 갖는다.
- 파괴 내성 · 대체 효과는 Phase 8 에서 이 비트를 보고 개입한다.
- `Contract F` 가 `ACTION_DESTINATION` 의 붕괴를 테스트로 박제한다 — 그 표를
  실행에 쓰면 안 되는 이유가 테스트로 남는다.

### Future implications

`GameEvent.reason` (설계 §7) 과 같은 비트마스크를 쓴다. Effect 가 만든
operation 의 reason 이 그대로 event 의 reason 이 되어야 트리거가 맞는다.

---

## ADR-003 — Effect Execution Authority

### Context

`core/provenance.py:57` 의 `AnalysisStatus` 가 이미 세 상태를 구분한다.
실측 분포 (`7450109`, `include_alternates=True`, 총 14,520장):

| 상태 | 카드 수 | EffectRef 수 | EffectRef 를 하나라도 가진 카드 |
|---|---:|---:|---:|
| `lua_verified` | 12,968 | 35,385 | **12,773** |
| `text_derived` | 806 | **0** | **0** |
| `no_effect` | 746 | **0** | **0** |

**결정적인 발견:** `text_derived` 와 `no_effect` 카드는 `EffectRef` 를
**하나도 만들 수 없다.** `engine/ids.py:123` 이 그 이유다.

```python
def effect_refs(card: "Card") -> list[EffectRef]:
    if card.script is None:
        return []
    return [EffectRef(card.id, i) for i in range(len(card.script.effects))]
```

`EffectRef` 는 **Lua 스크립트에서만 나온다.**

### Decision

실행 권위를 다음과 같이 확정한다.

| `AnalysisStatus` | Duel Engine 실행 | 다른 용도 |
|---|---|---|
| `LUA_VERIFIED` | **조건부 허용** (ADR-006 참조) | 전부 허용 |
| `TEXT_DERIVED` | **금지** | 검색 · 분석 · 설명 · 후보 생성 허용 |
| `NO_EFFECT` | 해당 없음 — **실행할 효과가 존재하지 않는다** | 카드 자체는 정상적으로 듀얼에 나온다 |
| `UNAVAILABLE` | **금지** | 분석 근거가 없다는 뜻이지 효과가 없다는 뜻이 아니다 |

**`NO_EFFECT` 는 차단이 아니다.** 푸른 눈의 백룡은 듀얼에 나오고, 소환되고,
공격한다. 단지 *발동할 효과*가 없을 뿐이다. `TEXT_DERIVED` 차단과 **전혀
다른 처리**이며, 이 둘을 합치면 통상 몬스터 746장이 듀얼에서 사라진다
(커밋 `9bf690a` 이전에 실제로 그럴 뻔했다).

### Rationale

**이 결정은 정책이자 동시에 구조다.**

정책만이었다면 "잊어버리면 뚫린다". 그러나 실측상 `TEXT_DERIVED` 카드는
`EffectRef` 를 **만들 수 없으므로**, 실행 identity 공간에 이름조차 없다.
`EffectRegistry` 의 키가 `EffectRef` 인 한 (ADR-005), `TEXT_DERIVED` 효과는
**등록될 수도, 조회될 수도 없다.**

즉 Contract A 는 런타임 `if` 문이 아니라 **타입 공간의 성질**로 성립한다.
방어선이 두 겹이다.

1. 구조적 — `EffectRef` 가 만들어지지 않는다
2. 정책적 — 엔진 진입점에서 `AnalysisStatus` 를 확인한다

### Alternatives considered

| 대안 | 기각 이유 |
|---|---|
| `TEXT_DERIVED` 도 실행 허용 | ADR-004 가 상세히 다룬다 |
| `TEXT_DERIVED` 데이터를 폐기 | 806장의 분석 정보를 버린다. 검색 · 시너지 분석 · Lua 작성 보조에 모두 유용하다 |
| `NO_EFFECT` 도 `TEXT_DERIVED` 와 같이 차단 | 통상 몬스터 746장이 듀얼에서 사라진다. **이미 한 번 겪은 버그다** |
| `UNAVAILABLE` 을 `NO_EFFECT` 로 취급 | "분석 못 했다" 와 "효과가 없다" 는 정반대다 |

### Consequences

- 엔진 진입점 한 곳에서 `AnalysisStatus` 를 확인한다. 하위 계층은 확인하지 않아도 된다.
- 806장이 듀얼 시뮬레이션에서 제외된다. **이것은 의도한 손실이다.**
- `Contract A` · `Contract B` 가 감시한다.

### Future implications

`TEXT_DERIVED` 는 줄어들 수 있다 — 새 카드의 Lua 가 나오면 자동으로
`LUA_VERIFIED` 가 된다 (`card_repository.py:237`). 이것은 ADR-009 가 말하는
"승격"이 아니라 **소스가 바뀐 것**이다.

---

## ADR-004 — TEXT_DERIVED 실행 금지

### Context

`analysis/text_effect_analyzer.py` 는 공식 카드 텍스트에서 효과 구조를
유도한다. 그 결과는 `AnalysisStatus.TEXT_DERIVED` 로 표시된다.

```
Official Card Text → Parser/Analyzer → Structured Effect
```

### Decision

**`TEXT_DERIVED` 는 어떤 경우에도 authoritative execution source 가 되지
않는다.** 테스트 통과 · 사람의 검토 · AI 의 확신 — 그 무엇도 이 금지를
해제하지 않는다. 해제는 오직 **실제 실행 가능한 구현이 존재할 때** 뿐이고,
그것은 더 이상 `TEXT_DERIVED` 가 아니다 (ADR-009).

### Rationale

**공식 텍스트 ≠ 실행 가능한 구현.**

텍스트에서 다음을 완전하게 판별할 수 없다.

| 판별 대상 | 왜 텍스트로 부족한가 |
|---|---|
| activation condition | "~한 경우" 와 "~했을 때" 가 다른 타이밍인데 번역·표기에 따라 흐려진다 |
| targeting | "대상으로 하고" 가 빠진 대상 미지정 효과와 구분이 어렵다 |
| timing | `SetHintTiming` 에 해당하는 정보가 텍스트에 없다 |
| cost | "그리고" 앞뒤가 비용인지 효과인지 텍스트만으로는 갈린다 |
| resolution order | 동시 처리 / 순차 처리가 텍스트에 드러나지 않는다 |
| simultaneous event | 동시에 발생한 사건의 처리 순서 |
| replacement | 대체 효과인지 일반 효과인지 |
| once-per-turn scope | "1턴에 1번" 이 카드 단위인지 카드명 단위인지 텍스트로 구분 안 되는 경우가 있다 |

마지막 항목이 특히 구체적이다. Phase 1 에서 `LimitScope` 를 세 개로 나눈
이유가 정확히 이것이고 (`PER_CARD` / `PER_CARD_NAME` / `PER_EFFECT`),
그 구분은 Lua 의 `SetCountLimit` 인자에서 나온다. **텍스트에는 그 인자가
없다.**

**위험의 형태:** `TEXT_DERIVED` 를 실행하면 파서의 추론 오류가 곧바로
`GameState` mutation 이 된다. 그리고 그 mutation 은 `state_hash` 에 들어가고,
journal 에 기록되고, replay 에서 재현된다. **틀린 것이 결정론적으로
재현된다.** 틀렸다는 사실은 어디에도 남지 않는다.

이것이 프로젝트 전체를 관통하는 원칙의 한 사례다.

```
UNVERIFIED         ≠ WRONG
SOURCE_UNAVAILABLE ≠ RULING_NOT_FOUND
NO_LUA             ≠ NO_EFFECT
KOREAN_TRANSLATION ≠ OFFICIAL_RULING
TEXT_DERIVED       ≠ LUA_VERIFIED     ← 이번 ADR
```

### Alternatives considered

| 대안 | 기각 이유 |
|---|---|
| 신뢰도 점수를 붙여 임계값 이상은 실행 | 임계값은 `UNKNOWN` 을 `true` 로 바꾸는 장치다. 프로젝트 원칙에 정면으로 어긋난다 |
| 사람이 검토한 것만 실행 | 검토 기록을 저장할 곳이 없고, 검토가 곧 구현이 아니다. 검토했다고 실행 semantics 가 생기지 않는다 |
| `TEXT_DERIVED` 를 "경고와 함께 실행" | 경고는 로그로 가고 `state_hash` 는 오염된다. 경고받은 상태와 정상 상태가 해시로 구분되지 않는다 |

### Consequences

- `TEXT_DERIVED` 카드가 든 덱은 **듀얼 시뮬레이션이 불가능**하다고 명시적으로
  거부된다. 조용히 그 카드만 빼고 진행하지 않는다.
- AI 는 `TEXT_DERIVED` 정보를 **읽을 수 있지만** 그것으로 상태를 바꿀 수 없다 (ADR-007).

### Future implications

이 금지는 영구적이다. `TEXT_DERIVED` 가 실행 가능해지는 경로는 "금지를
푸는 것"이 아니라 "구현을 작성하는 것"이다.

---

## ADR-005 — EffectRef 를 실행 identity 로 사용한다

### Context

`analysis.EffectAnalysis.index` 는 **`str`** 이고 Lua 변수명(`"e1"`, `"e2"`)을
담는다. 이것이 한 카드 안에서 중복된다.

실측 (`7450109`):

```
효과 블록을 가진 카드            12,773
EffectSpec.index 가 중복되는 카드  4,884
중복 때문에 가려지는 효과 블록      6,925
```

`(card_id, index)` 를 키로 쓰면 **6,925개의 효과가 사라진다.**

`engine/ids.py` 의 `EffectRef` 는 이 문제를 해결하려고 만들어졌다.

```python
@dataclass(frozen=True, slots=True, order=True)
class EffectRef:
    card_id: int
    ordinal: int     # 원문 순서. 중복되지 않는다
```

### Decision

**`EffectRef(card_id, ordinal)` 이 Phase 2 이후 유일한 실행 identity 다.**

```
Card Definition → card_id → EffectRef(card_id, ordinal) → EffectImplementation → Execution
```

`EffectSpec.index` / `EffectAnalysis.index` 를 실행 키로 **사용하지 않는다.**
분석 결과를 사람이 읽을 때의 라벨로만 남긴다.

이미 Phase 1 에서 `UseRegistry` 의 `PER_EFFECT` 키가 `EffectRef` 를 쓰고
있으므로 (`use_registry.py:81`), 이 결정은 기존 코드와 일관된다.

### Rationale

`ordinal` 은 `enumerate(card.script.effects)` 의 인덱스다. 따라서:

- **중복 불가능** — 리스트 인덱스이므로 구조적으로 유일하다
- **결정론적** — 같은 스크립트를 같은 파서로 읽으면 같은 순서다
- **정수 튜플** — `state_hash` 에 넣어도 파이썬 `hash()` 에 의존하지 않는다

취약점 하나를 명시한다. **스크립트가 바뀌면 `ordinal` 이 밀린다.** 카드
스크립트에 효과 블록이 중간 삽입되면 그 뒤의 `ordinal` 이 전부 1씩 밀리고,
저장된 `EffectRef` 가 다른 효과를 가리키게 된다. Phase 2-D 에서
`EffectRegistry` 항목에 **스크립트 해시를 함께 저장**해서, 스크립트가 바뀌면
등록이 무효화되도록 한다. 이번 단계에서는 구현하지 않고 기록만 한다.

### Alternatives considered

| 대안 | 기각 이유 |
|---|---|
| `EffectSpec.index` (`"e1"`) | **4,884장에서 중복.** 6,925개 효과가 사라진다 |
| 효과 본문의 내용 해시 | 스크립트 포매팅 변경에도 키가 바뀐다. 그리고 사람이 읽을 수 없다 |
| 전역 일련번호 | 카드와 무관한 번호라 디버깅이 불가능하고, 카드가 추가될 때마다 재배번된다 |
| `(card_id, effect_code)` | `effect_code` 가 `None` 인 효과가 많고, 한 카드에서 중복된다 |

### Consequences

- `EffectRegistry` 의 키가 `EffectRef` 로 고정된다.
- `TEXT_DERIVED` 는 `EffectRef` 를 만들 수 없으므로 **등록 자체가 불가능**하다 (ADR-003 의 구조적 방어선).
- `Contract G` 가 index 중복을 테스트로 박제한다.

### Future implications

`ChainLink.effect: EffectRef` (설계 §12) 와 `UseRegistry` 의 `PER_EFFECT` 키가
같은 타입이므로, "이 체인 링크의 효과가 이번 턴에 이미 쓰였는가"가 키 변환
없이 조회된다.

---

## ADR-006 — Effect Implementation Lookup

### Context

**`LUA_VERIFIED` 는 "실행 가능"을 뜻하지 않는다.** 실측이 이를 증명한다.

```
lua_verified 카드                          12,968
그중 EffectRef 를 하나라도 가진 카드        12,773
그중 EffectRef 가 0개인 카드                  195   ← 문제
```

195장을 조사했다. 예: 오버로드 퓨전 (`3659803`)

```lua
function s.initial_effect(c)
	local e1=Fusion.CreateSummonEff(c,s.ffilter,...)   -- 공유 라이브러리가 효과를 만든다
	c:RegisterEffect(e1)
end
```

효과가 `Fusion.CreateSummonEff` 라는 **공유 라이브러리 팩토리** 안에서
만들어진다. 파서는 카드 스크립트에서 효과 블록을 찾지 못한다. 카드는
`LUA_VERIFIED` 인데 **주소를 매길 수 있는 효과가 하나도 없다.**

여기에 더해, `EffectRef` 가 있어도 그 효과의 **구현**이 registry 에 없을 수
있다. Phase 2-E 는 소수의 카드부터 시작한다.

### Decision

**실행 가능성은 저장하지 않고 조회 시점에 유도한다.**

```
CardExecutionAvailability   (Phase 2-D 신설, engine/ 안)
 ├ EXECUTABLE          EffectRef 가 있고 registry 에 구현이 있다
 ├ NO_IMPLEMENTATION   EffectRef 는 있으나 구현이 없다  (LUA_VERIFIED 대부분)
 ├ NOT_ADDRESSABLE     LUA_VERIFIED 이나 EffectRef 가 0개다  (195장)
 ├ TEXT_DERIVED        분석 전용. 실행 금지            (806장)
 └ NO_EFFECT           발동할 효과가 없다 — 정상 상태   (746장)
```

**`core/provenance.py` 의 `AnalysisStatus` 에 값을 추가하지 않는다.**
`CardProvenance` 는 "이 데이터가 어디서 왔는가"를 기록하는 곳이고,
"지금 이 엔진 빌드가 실행할 수 있는가" 는 **엔진의 질문**이다. 같은 카드
데이터를 쓰는 두 엔진 빌드가 서로 다른 답을 내야 하므로, 카드 데이터에
저장하면 반드시 어긋난다.

lookup 계약:

```
EffectRegistry.lookup(EffectRef) -> EffectImplementation | None
```

- 키는 `EffectRef`. 다른 타입은 받지 않는다.
- 없으면 `None` 을 돌려주고, 호출자는 **실행을 거부한다.** 빈 구현으로
  대체하거나 아무것도 안 하고 성공 처리하지 않는다.
- `TEXT_DERIVED` 효과는 애초에 `EffectRef` 가 없으므로 등록도 조회도 불가능하다.

### Rationale

`LUA_VERIFIED` 를 실행 게이트로 쓰면 **195장에서 즉시 깨진다.** 그 카드들은
"스크립트가 있다"는 사실은 참인데 "실행할 효과를 지목할 수 있다"는 거짓이다.
두 명제가 다르다는 것이 실측으로 확인되었다.

저장하지 않는 이유: 실행 가능성은 **registry 의 내용에 따라 달라진다.**
Phase 2-E 에서 카드 5장을 구현하면 5장만 `EXECUTABLE` 이고, Phase 7 에서
500장이 되면 500장이 된다. 카드 데이터는 그동안 한 글자도 바뀌지 않는다.
이것을 `CardProvenance` 에 저장하면 **데이터와 코드가 반드시 어긋난다.**

### Alternatives considered

| 대안 | 기각 이유 |
|---|---|
| `AnalysisStatus` 에 `EXECUTABLE` 추가 | 출처(provenance)와 실행 가능성은 다른 축이다. 그리고 registry 내용에 따라 변하는 값을 카드 데이터에 저장하면 즉시 낡는다 |
| `LUA_VERIFIED` 를 그대로 실행 게이트로 | **195장에서 깨진다.** 실측으로 확인됨 |
| 195장의 파서를 고쳐 `Fusion.*` 팩토리를 해석 | 유효한 개선이지만 이번 범위가 아니고, 고쳐도 "구현 없음" 문제는 남는다 |
| 구현 없는 효과를 no-op 으로 실행 | **가장 위험하다.** 아무 일도 안 일어난 것이 정상 해결로 기록되고 `state_hash` 에 들어간다 |

### Consequences

- Phase 2-D 가 `engine/` 안에 availability 를 유도하는 함수 하나를 만든다. 데이터 모델 변경 없음.
- 195장은 구현 대상 후보에서 **명시적으로** 제외되고, 파서 개선 대상으로 기록된다.
- `Contract C` 가 "LUA_VERIFIED 면 실행 가능" 이라는 잘못된 전제를 막는다.

### Future implications

`Fusion.*` / `Synchro.*` 같은 공유 라이브러리 팩토리를 파서가 해석하게 되면
195장이 줄어든다. 그것은 `analysis/` 개선이고 ADR 을 바꾸지 않는다.

---

## ADR-007 — AI / Engine 실행 경계

### Context

설계 §16 이 이미 경계를 정해 두었다.

```
GameState(읽기 전용 뷰) → LegalActions → AI → Action → Engine → GameState'
```

현재 코드는 이 경계를 **이미 지키고 있다.** 실측:

```
engine/ 이 analysis/ 에서 가져오는 심볼:  LimitScope 단 하나 (use_registry.py:32)
engine/ 이 core/ 에서 가져오는 심볼:      모듈 수준에서는 없음 (TYPE_CHECKING 뿐)
```

### Decision

**AI 는 `Action` 객체만 돌려준다. 상태를 만들지도, 바꾸지도 않는다.**

```
AI
 ↓  (읽기 전용 GameStateView + 분석 데이터 — TEXT_DERIVED 포함 가능)
Action Candidate
 ↓
Engine Validation          ← 여기부터 AI 가 개입할 수 없다
 ↓
Condition (3-값)
 ↓
Effect
 ↓
Execution Authority Check  ← ADR-003 / ADR-006
 ↓
State Change
 ↓
GameState
```

금지되는 것:

```python
state.player(0).hand.append(card)       # 금지
state.player(0).change_life(-1000)      # 금지
move_card(card, hand, grave)            # 금지
state.uses.mark_effect_used(...)        # 금지
```

**AI 가 `TEXT_DERIVED` 를 읽는 것은 허용한다.** "이 카드는 아마 이런 효과일
것이다" 라고 추론하고, 그 추론으로 Action 후보의 **우선순위를 매기는 것**까지
허용한다. 금지되는 것은 그 추론이 `GameState` mutation 이 되는 것뿐이다.

### Rationale

AI 의 추론과 엔진의 권위를 분리하면, **AI 가 틀려도 상태가 오염되지 않는다.**
AI 가 `TEXT_DERIVED` 정보로 잘못된 Action 을 고르면 엔진이 `ILLEGAL` 로
거부한다. 거부는 기록되고, 상태는 그대로다.

반대로 AI 가 상태를 직접 바꿀 수 있으면, AI 의 추론 오류와 엔진의 규칙
위반이 구분되지 않는다. `state_hash` 가 오염된 뒤에는 어느 쪽이 틀렸는지
알 수 없다.

현재 코드가 이미 이 경계를 지키고 있다는 것이 중요하다. **지켜야 할 것이
아니라 유지해야 할 것이다.**

### Alternatives considered

| 대안 | 기각 이유 |
|---|---|
| AI 에 `GameState` 를 그대로 넘긴다 | `move()` · `change_life()` 가 노출된다. 실수 한 줄로 경계가 사라진다 |
| AI 가 `StateDelta` 를 만들어 제출 | Delta 를 만들려면 규칙을 알아야 한다. 규칙 계산이 AI 로 넘어간다 |
| AI 에게 `TEXT_DERIVED` 를 숨긴다 | 806장에 대해 AI 가 아무 말도 못 하게 된다. 읽기는 안전하다 — 쓰기만 막으면 된다 |

### Consequences

- Phase 2-A 는 `GameStateView` (읽기 전용 래퍼) 를 함께 만든다.
- `engine` → `analysis` 의존은 `LimitScope` 하나로 유지한다. 늘어나면 경계가 흐려진 신호다.
- `Contract H` 가 이 의존을 감시한다.

### Future implications

RL / MCTS 는 `clone()` 과 `state_hash()` 의 결정론에 의존한다. Phase 1 에서
이미 보장되어 있다.

---

## ADR-008 — StateDelta 도입 시점

### Context

설계 §13 은 `StateDelta` 를 이미 규정한다. 그러나 Phase 1 의 `GameState` 는
**직접 변경 방식**이다.

```python
def move(self, instance, zone, *, to_player=None, index=None, position=None):
    ...
    return move_card(card, source, destination, index=index, position=position)
```

`draw()` · `change_life()` · `set_result()` 도 마찬가지다.

### Decision

**`StateDelta` 를 지금 도입하지 않는다. Phase 2-E 에서 도입한다.**

단, 그때 도입할 수 있도록 Phase 2-A ~ 2-D 에서 다음을 지킨다.

1. Phase 1 의 직접 변경 메서드(`move` · `draw` · `change_life`)는 **그대로
   둔다.** 테스트와 셋업이 쓴다.
2. **Effect 해결 경로에서는 그 메서드를 직접 부르지 않는다.** Effect 는
   `EffectOperation` 목록을 만들고, 그것을 적용하는 곳이 한 군데여야 한다.
3. 그 "한 군데"가 Phase 2-E 에서 `StateDelta.apply()` 가 된다.

### Rationale

**지금 도입하면 과잉 추상화다.** 근거:

- 현재 상태 변경 지점은 `move` · `draw` · `change_life` · `set_result` 4개뿐이다.
- Delta 를 적용받을 **소비자가 아직 없다.** `journal` 은 빈 리스트이고
  (`game_state.py:105`), `EventJournal` 은 Phase 2 에서 만들어진다.
- Delta 의 가치는 (a) replay, (b) 되돌리기, (c) 이벤트 유도 인데, **셋 다
  Phase 2-E 이후에 필요해진다.**

**나중에 도입해도 되는 이유:** Phase 1 이 이미 `state_hash()` 를 결정론적으로
제공한다. replay 검증에 필요한 `(state_hash, action, state_hash')` 중 양 끝이
이미 있다. 가운데의 `delta` 만 나중에 채우면 된다.

**반대로 지금 도입하면 잃는 것:** 모든 테스트가 delta 를 거쳐야 하고, Phase 1
의 136개 테스트가 다시 쓰여야 한다. 아직 그 delta 가 무엇을 담아야 하는지
모르는 채로.

### Alternatives considered

| 대안 | 기각 이유 |
|---|---|
| 지금 `StateDelta` 프레임워크를 만든다 | 소비자가 없다. `EffectOperation` 이 무엇을 담을지 확정되지 않은 상태에서 delta 스키마를 정하면 두 번 고친다 |
| 영구히 직접 변경 방식 | replay 와 되돌리기가 불가능해진다. MCTS 가 `clone()` 만으로 버틸 수 있는지는 미지수 |
| Phase 2-A 부터 도입 | Action 어휘를 정하는 단계에서 상태 적용 방식까지 정하면 두 결정이 얽힌다 |

### Consequences

- Phase 2-A ~ 2-D 는 Phase 1 의 변경 메서드를 그대로 쓴다.
- Phase 2-E 에서 Effect 실행 경로만 delta 로 바꾼다. 테스트 셋업은 안 바꾼다.
- `GameState.move()` 등은 **영구히 남는다.** delta 의 구현 수단이 되기 때문이다.

### Future implications

`EventJournal` 이 `(state_hash, action, delta, state_hash')` 를 기록하면
결정론적 replay 가 성립한다. 난수는 Phase 1 의 `seed` 가 이미 journal 에
넣을 수 있는 형태다 (`GameState.seed`).

---

## ADR-009 — TEXT_DERIVED → LUA_VERIFIED 승격 (개념만)

> 이 ADR 은 §9 의 요구에 따라 **개념만** 정의한다. 구현하지 않는다.

### Context

806장의 `TEXT_DERIVED` 카드를 영구히 버리지 않으려면 승격 경로가 필요하다.

### Decision

**자동 승격 시스템을 만들지 않는다.** 그리고 "테스트를 통과했다"는 승격
근거가 **되지 않는다.**

승격은 두 종류로 나뉘고, 이름을 구분한다.

| 종류 | 무슨 일이 일어났는가 | 현재 지원 여부 |
|---|---|---|
| **소스 갱신** | 그 카드의 공식 Lua 스크립트가 배포되었다 | **이미 자동** (`card_repository.py:237`) |
| **구현 작성** | 사람이 그 카드의 실행 semantics 를 작성했다 | 미지원 |

"구현 작성" 경로는 `AnalysisStatus` 를 바꾸지 **않는다.** 그 카드의 분석은
여전히 텍스트에서 나왔기 때문이다. 대신 `EffectRegistry` 에 항목이 생기고,
`CardExecutionAvailability` (ADR-006) 가 `EXECUTABLE` 이 된다.

### Rationale

`AnalysisStatus` 는 **출처**를 뜻한다. 사람이 구현을 작성했다고 해서 그
분석이 Lua 에서 나온 것이 되지는 않는다. 상태를 덮어쓰면 "이 구조화 정보가
어디서 왔는가" 라는 질문에 영원히 답할 수 없게 된다.

"verified" 의 정의를 명시한다.

> **verified 란, 실행 semantics 가 공식 스크립트에서 유도되었거나, 사람이
> 작성한 구현이 공식 텍스트 · 공식 재정과 교차 검증되고 결정론적 테스트로
> 고정되었음을 뜻한다. 테스트 통과만으로는 verified 가 아니다 — 테스트는
> 구현이 스스로를 확인한 것일 뿐, 외부 근거와 대조한 것이 아니다.**

### Consequences

- `TEXT_DERIVED` 카드는 구현이 생겨도 `TEXT_DERIVED` 로 남는다. 그것이 정확하다.
- 실행 가능 여부는 `AnalysisStatus` 가 아니라 registry 가 답한다 (ADR-006).

---

## Phase 2 구현 순서

실제 코드를 확인한 뒤 제안 순서를 **두 군데 조정**했다.

| 단계 | 내용 | 조정 |
|---|---|---|
| **2-A** ✅ | `PlayerActionKind` · `PlayerAction` · `ActionTarget` · 검증 인터페이스 · `GameStateView` | `GameStateView` 를 여기로 **앞당김** — ADR-007 의 경계를 Action 이 생기는 순간부터 지키기 위해. **구현 완료**, `docs/phase2a-player-action.md` |
| **2-B** | Condition 표현 (평가 아님) | 원안대로 |
| **2-C** | `EffectOperation` 모델 + `REASON_*` | 원안대로 |
| **2-D** | `EffectRegistry` + `CardExecutionAvailability` | 원안대로 |
| **2-E** | 소수 카드의 실제 실행 + `StateDelta` 도입 | `StateDelta` 를 여기로 **명시** (ADR-008) |
| **2-F** | Chain | 원안대로 |
| **2-G** | Summon / activation legality | 원안대로 |

기존 설계 §17 로드맵의 Phase 번호와는 다음과 같이 대응한다. 설계 §17 의
Phase 3.5 (`SetHintTiming` 수집) 는 **2-F 이전에 반드시 끝나야 한다** —
퀵 효과의 발동 시점을 판단할 수 없으면 체인이 성립하지 않는다.

---

## Chain 과 Effect 의 관계

**`Effect = Chain Link` 가 아니다.** 명시적으로 기록한다.

| 개념 | 정체 | 개수 관계 |
|---|---|---|
| `Effect` | 카드가 가진 **정의**. `EffectRef` 로 지목된다 | 듀얼 내내 고정. 35,385개가 데이터에 있다 |
| `ChainLink` | 그 효과가 **이번에 발동된 사건**. 시점 스냅숏을 갖는다 | 듀얼 중 생성·소멸. 같은 Effect 가 여러 링크를 만들 수 있다 |

증거는 Phase 1 에 이미 있다. `UseRegistry` 의 `PER_EFFECT` 키가 **횟수
카운터**인 이유가 바로 이것이다 — 하나의 `EffectRef` 가 한 턴에 여러 번
발동될 수 있어서 (`SetCountLimit(2..4, ...)` 를 쓰는 효과 53건),
"발동되었다/아니다" 로는 표현되지 않았다.

설계 §12 의 `ChainLink.effect: EffectRef` 는 **참조**다. 소유가 아니다.
이 방향을 뒤집으면 (Effect 가 chain 상태를 들고 있으면) 카드 정의가
가변이 되고, Phase 1 의 `test_definition_immutability.py` 가 깨진다.

---

## 유지해야 하는 구분 10가지

Phase 2 구현 중 이 중 하나라도 무너지면 설계가 틀어진 것이다.

| # | 구분 | 지키는 장치 |
|---|---|---|
| 1 | `UNVERIFIED identity` ≠ `VERIFIED identity` | `CardIdentity.trusted` 는 `VERIFIED` 만 참 (`card_identity.py:128`) |
| 2 | `TEXT_DERIVED` ≠ `LUA_VERIFIED` | `AnalysisStatus` + `EffectRef` 부재 (ADR-003) |
| 3 | 공식 텍스트 ≠ 실행 가능한 구현 | ADR-004 |
| 4 | `Action` ≠ `Effect` | 타입 분리 + 이름 분리 (ADR-001) |
| 5 | `Effect` ≠ `Chain Link` | `ChainLink.effect` 는 참조 |
| 6 | `Destroy` ≠ `Send to Graveyard` | `REASON_DESTROY` 비트 (ADR-002) |
| 7 | `Owner` ≠ `Controller` | `CardInstance.owner` / `.controller` (Phase 1) |
| 8 | `Card Definition` ≠ `Card Instance` | `definition` 프로퍼티 + 불변성 테스트 (Phase 1) |
| 9 | 저수준 존 이동 ≠ 고수준 게임 의미 | `move_card` 에 reason 없음 (ADR-002) |
| 10 | AI 추론 ≠ authoritative mutation | `GameStateView` + registry (ADR-007) |

---

## 남은 설계 문제

Phase 2 를 **시작할 수는 있으나**, 진행 중 답이 필요한 것들이다.

| # | 문제 | 언제까지 | 막는 단계 |
|---|---|---|---|
| 1 | `EffectRef.ordinal` 이 스크립트 변경에 밀린다 | Phase 2-D | 2-D (registry 에 스크립트 해시 저장) |
| 2 | `LUA_VERIFIED` 195장이 `EffectRef` 를 못 만든다 | 미정 | 없음 (제외하고 진행 가능) |
| 3 | `SetHintTiming` 미수집 | Phase 2-F 이전 | **2-F (Chain)** |
| 4 | `TEXT_DERIVED` 덱을 어떻게 거부할 것인가 — 덱 단위인가 카드 단위인가 | Phase 2-D | 2-E |
| 5 | `EffectOperation` 이 "이동하지 않는 파괴"(필드 밖 파괴 등)를 어떻게 표현할 것인가 | Phase 2-C | 2-C |

1 · 3 · 5 는 해당 단계 안에서 풀 수 있다. **4 는 사용자 결정이 필요하다** —
아래 참조.

### 사용자 결정이 필요한 것

> **`TEXT_DERIVED` 카드가 든 덱을 어느 단위로 거부하는가?**
>
> - (a) 덱 단위 — 한 장이라도 있으면 그 덱은 시뮬레이션 불가
> - (b) 카드 단위 — 그 카드만 "발동 불가"로 두고 듀얼은 진행
>
> (a) 는 안전하지만 실용성이 떨어진다 (806장이 널리 퍼져 있다).
> (b) 는 실용적이지만 **시뮬레이션 결과가 실제와 다르다는 것을 숨긴다.**
> ADR-004 의 정신은 (a) 에 가깝고, 설계 §11 도 (a) 로 읽힌다.
> Phase 2-E 전까지 답이 필요하다.

---

## 테스트 계약

`tests/engine/test_phase2_contracts.py` 에 8개 계약을 구현했다. **Phase 2
코드가 없는 지금도 전부 실행되고 통과한다** — 기존 데이터와 코드에 대한
불변식이기 때문이다.

| 계약 | 내용 | 지금 무엇을 검사하는가 |
|---|---|---|
| A | `TEXT_DERIVED` 는 실행될 수 없다 | 806장 전부 `EffectRef` 0개 — 실행 identity 공간에 이름이 없다 |
| B | `NO_EFFECT` 는 발동할 효과가 없다 | 746장 전부 `EffectRef` 0개. `TEXT_DERIVED` 와 **다른** 상태임을 확인 |
| C | `LUA_VERIFIED` 만으로는 실행 가능하지 않다 | `EffectRef` 0개인 `LUA_VERIFIED` 카드가 195장 **존재한다** |
| D | `UNVERIFIED` identity 로 공식 재정을 얻을 수 없다 | `trusted` 는 `VERIFIED` 만 참 |
| E | `Action` 과 `Effect` 는 다른 개념이다 | 두 어휘의 이름 겹침이 `normal_summon` 하나뿐임을 고정. `engine` 코드가 `analysis.ActionKind` 를 **사용**하지 않음 (AST 검사) |
| F | `Destroy` 와 `Send` 는 자동으로 같지 않다 | `ACTION_DESTINATION` 이 실제로 둘을 합침을 박제. `REASON_DESTROY` 는 독립 비트 |
| G | `EffectRef(card_id, ordinal)` 이 효과 identity 다 | `EffectSpec.index` 가 4,884장에서 중복 |
| H | AI 는 분석 데이터로 상태를 바꿀 수 없다 | `engine` → `analysis` 의존이 `LimitScope` 하나뿐 |

Contract D 의 네트워크 수준 검증은 `tests/rulings/test_identity_trust_boundary.py`
(21개) 가 이미 하고 있다. **중복 구현하지 않고** API 수준 불변식만 확인한다.
