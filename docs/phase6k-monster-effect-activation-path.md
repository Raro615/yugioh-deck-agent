# Phase 6-K — 몬스터 효과 발동 절차 및 체인 엔진 연결 (B3)

> **달성 수준: §12 수준 1 (발동 경로 확보). 수준 2 (실제 발동 및 해결) 미달성.**
>
> 막는 것이 **"규칙이 없다" 에서 "구현이 없다" 로 바뀌었다.** 그 둘은 다른
> 사실이고 (ADR-006), 이번 Phase 가 바꾼 것은 전자 하나다. 몬스터 효과가
> 실제로 해결된 사례는 **0건**이다.

- 브랜치 `claude/pensive-goodall-te1egy`
- commit `17eb60c` (production) · `910f6c3` (테스트) · `3eb470b` (테스트 보강) · 이 문서
- 시작 시점 HEAD `6eace6b`

---

## 1. §1 — 작업 시작 전 상태

| 확인 | 값 |
|---|---|
| 브랜치 | `claude/pensive-goodall-te1egy` |
| 작업 트리 | clean (`git status --short` 가 빈 출력) |
| HEAD | `6eace6b` "Phase 6-J 보고서: 실행 미달성을 미달성이라고 적는다" |

사용자의 기존 변경 사항은 없었다. 덮어쓴 것도 없다.

---

## 2. 요약 — 무엇이 바뀌었고 무엇이 그대로인가

### 바뀐 것

어니스트 ①(`EffectRef(37742478, 0)`)에 대한 `ActionValidator.validate` 의 답:

| | Phase 6-K 이전 | 이후 |
|---|---|---|
| `ActionValidator` | `UNKNOWN` / `monster-activation-timing (기동 · 유발 · 플립 · 유발즉시 분류가 없다)` | **`VALID`** |
| `ActivationTimingChecker` (체인 빔) | `VALID` | `VALID` (그대로) |
| `EffectActivator.can_activate` | — (앞에서 멈췄다) | `UNKNOWN` / `registered effect implementation` |
| `ActivationStatus` | `UNAUTHORIZED` | **`NOT_IMPLEMENTED`** |
| 체인 길이 | 0 | 0 |

### 그대로인 것

- **마법 · 함정 경로**: 욕망의 항아리가 후보로 나오고, 발동되고, 2장 뽑고,
  묘지로 간다 (§13-H).
- **스펠 스피드 계층**: 한 줄도 건드리지 않았다. 체인이 열려 있으면 몬스터
  효과는 여전히 `UNKNOWN` 이다 — 새 경로는 **체인 1 전용**이다 (§13-J).
- **후보 목록**: `legal_actions` 에 몬스터 효과가 하나도 나오지 않는다.
  `activatable_effects` 가 `executable` 만 돌려주고, 등재된 몬스터 효과는
  `executable=False` 다.
- **`PlayerAction` 계약**: 칸도 종류도 하나 늘지 않았다 (§9).
- **등록소를 주지 않은 호출**: `ActionValidator(view)` 는 Phase 6-K 이전과
  **글자 하나까지 같은 답**을 낸다 (§13-C).

---

## 3. §4-A — 발동 행위 모델 조사

### A-1. `ACTIVATE_EFFECT` 는 처음부터 효과를 지목하고 있었다

```python
_NEEDS_EFFECT_REF: frozenset[PlayerActionKind] = frozenset(
    {PlayerActionKind.ACTIVATE_EFFECT}
)
```

`PlayerAction.activate_effect(actor, source, effect_ref, *, targets=())` 는
`EffectRef(card_id, ordinal)` 을 **필수**로 받고, `validate_structure` 가
없으면 `EFFECT_REF_REQUIRED` 로 거절한다. 그리고 `ConditionContext` 에도
`effect_ref` 칸이 처음부터 있었다 (`engine/condition/context.py:58`).

**모자란 것은 지목 수단이 아니라, 그 지목을 읽는 코드였다.**
`_activate_effect` 는 `action.effect_ref` 를 **한 번도 보지 않았고**, 범위
판정 함수 `_activation_out_of_scope(view, context, instance)` 는 카드
`instance` 만 받았다.

이것이 6-H 와 같은 모양의 발견이다 — 6-H 에서는 Lua 조건 원문이 이미
기록되어 있었고 해석하는 코드가 없었다. 여기서는 효과 지목이 이미
전달되고 있었고 읽는 코드가 없었다.

### A-2. `ACTIVATE_CARD` 는 여전히 비어 있는 자리다

`engine/action.py` 가 이미 적어 둔 대로, Engine V1 에서 유효한 발동 행위는
`ACTIVATE_EFFECT` 하나다. 몬스터 효과도 "카드 X 의 효과 #N" 으로 모델링되
므로 같은 종류를 쓴다. **새 `PlayerActionKind` 를 만들지 않았다.**

### A-3. 발동 요청 · 발동 가능 판정 · 체인 등록 · 효과 해결 (§3-8)

| 단계 | 자리 | 이번 Phase |
|---|---|---|
| 발동 요청 | `PlayerAction(ACTIVATE_EFFECT)` | 변경 없음 |
| 발동 가능 판정 | `ActionValidator` → `ActivationTimingChecker` → `EffectActivator.can_activate` | **첫째 관문만** 변경 |
| 체인 등록 | `EffectActivator.activate` → `Chain.push` | 변경 없음 |
| 효과 해결 | `ChainResolver.resolve_top` → `EffectExecutor` | 변경 없음 |

---

## 4. §4-B — 발동 가능 판정: B3 의 정확한 자리

### B-1. 막던 한 줄

`engine/action_validation.py::_activation_out_of_scope`:

```python
if not definition.is_spell:
    if "TRAP" in set(definition.type_names):
        return (("함정이다", TRAP_TRIGGER_MISSING),)
    return (("통상 마법이 아니다", MONSTER_ACTIVATION_MISSING),)   # ← B3
```

**카드 종류 하나만 보고** 모든 몬스터 효과를 범위 밖으로 돌렸다. 그
결과가 `_NormalSpellActivation.evaluate` → `UNKNOWN` →
`verdict.permits_execution` 거짓 → `ActivationStatus.UNAUTHORIZED` 다.

### B-2. 🔴 적혀 있던 이유가 체인 1 에서는 **참이 아니었다**

`MONSTER_ACTIVATION_MISSING` 은 그 이유를 "기동 · 유발 · 플립 · 유발즉시
분류가 없어서 **스펠 스피드조차 정할 수 없다**" 로 적고 있었다. 그런데
`ActivationTimingChecker.check` 는:

```python
if not timing.chain_is_open:
    return self._passed("체인이 비어 있어 스펠 스피드 제약이 걸리지 않습니다.")
```

**체인이 비어 있으면 스펠 스피드를 묻지 않는다.** 실측으로 확인했다 —
어니스트를 앞면으로 몬스터 존에 놓고 체인을 비운 판에서 이 관문은 `VALID`
를 돌려준다. 즉 B3 가 적어 둔 이유는 **체인 2 이상에서만 성립**하고, 체인
1 의 기동 효과에는 적용되지 않았다.

이것이 이 Phase 의 출발점이다: 막는 **이유**와 막는 **범위**가 어긋나 있었다.

### B-3. 세 자리가 각각 막고 있었다 (실측)

| 자리 | 측정값 | 성격 |
|---|---|---|
| `ActionValidator` | `UNKNOWN` / `MONSTER_ACTIVATION_MISSING` | 규칙 계층 — **이번 Phase 가 고쳤다** |
| `Duel._activation_sources` | `()` — 몬스터 존을 보지 않는다 | 후보 생성 — 고쳤다 |
| `EFFECT_LIBRARY` | 몬스터 정의 **0건** | 등재 — 하나 더했다 (`executable=False`) |

세 번째가 §12 수준 2 를 막는다.

### B-4. 왜 관측이 아니라 **등록소**로 받는가

발동 분류는 **효과 하나**에 붙는데 `CardDefinitionView` 는 **카드 하나**를
싣는다. 그 입도 불일치를 Phase 3-F-26 이 이미 측정해 두었다 — 몬스터
856장(10.4%) 이 스펠 스피드 1 계열 블록과 2 계열 블록을 **둘 다** 가지고,
`QUICK_O` 보유 1,338장 중 847장(63.3%) 이 그렇다. **그런 카드에는 카드
단위의 답이 존재하지 않는다.**

그래서 관측에 칸을 더하지 않았다. `ActivationTiming.set_this_turn` 과 같은
방식으로 — 관측에 없는 사실은 그것을 들고 있는 쪽이 넘긴다 — 검증기가
`definitions=` 로 **불변 정의 등록소**를 받는다. 기본값은 `None` 이고,
그때는 Phase 6-K 이전의 답 그대로다.

---

## 5. §4-C — 체인 연결 경로 조사

### C-1. 체인 경로는 이미 완성되어 있었다

`EffectActivator._check_shape` 가 **비용을 치르기 전에** `chain.push` 로
시험해 보고 (`Chain` 은 불변이므로 그 사본은 버려진다), `activate` 가
비용 → `ChainLink` → `Chain.push` 를 한다. 몬스터 효과를 위해 바꿀 것이
하나도 없었다.

### C-2. 🔴 그런데 **배치**가 몬스터를 터뜨릴 수 있었다

`Duel._apply_activation` 의 ③단계는 `NormalSpellPlacement.place` 를 부르고,
그 함수는 카드가 패에 없으면 `SpellActivationError` 를 던진다. 몬스터는
패에 없다. 그리고 그 자리는 **비용과 체인 링크가 이미 지나간 뒤**이므로
되돌릴 방법이 없다 (ADR-008 이 일반 rollback 을 미뤄 두었다).

그래서 `engine/spell_activation.py` 에 `PLACEMENT_SOURCE_ZONES` 를 두고
(패 · 마법 & 함정 존 — RULE-SPELLTRAP-002 · 012 가 적은 두 자리),
`_place_activated` 가 **부르기 전에** 묻는다. 카드 종류를 보지 않고
**자리**를 본다 — 어느 자리에 배치가 있는가는 배치 계층이 적어 둔다.

### C-3. 체인 링크를 무조건 만들고 나중에 실패시키지 않았다 (§9)

`_check_shape` 의 시험 push 는 **불변 `Chain` 의 사본**이고 `self.chain` 에
반영되지 않는다. 그리고 세 관문이 전부 `VALID` 를 낸 뒤에만 비용이
치러진다. 어니스트는 셋째 관문에서 멈추므로 **체인 길이가 0 그대로**다
(§13-L2 가 실측).

### C-4. 실측 — 시험용 권한으로 배치 경로까지 확인했다

`_apply_activation` 의 `if placed is not None` 관문은 실제 데이터로는 닿지
않는다 (어니스트가 `executable=False` 라 그 앞에서 멈춘다). 닿지 않는
관문은 고쳐도 아무 테스트가 깨지지 않으므로, 테스트 안에서만 사는 구현
등록소를 만들어 일부러 닿게 했다 (`test_l04`). 결과:

- 체인 링크 **1개** 생성
- `pending_spells` **빈 채로 유지** (치울 것이 없다)
- 어니스트는 몬스터 존에 **그대로**, 마법 & 함정 존에 아무것도 들어가지 않음
- 체인을 풀어도 묘지로 가지 않음

🔴 **production 에는 아무 권한도 더하지 않았다** (§8 금지). 그 등록소는
테스트 함수 안의 객체이고, `EFFECT_LIBRARY` 도 `implementation_registry`
도 건드리지 않는다. 그리고 그 정의의 `operations` 는 비어 있으므로
**어니스트의 효과가 해결된 것이 아니다** — 확인한 것은 배치 경로 하나다.

### C-5. 🔴 측정 중 발견 — 후보 생성과 발동 허가가 다른 목록을 읽는다

`Duel.legal_actions` 는 `engine.spell_activation.activatable_effects` 를
부르고 그 함수는 `EFFECT_LIBRARY` 를 **모듈 수준에서** 읽는다. 주입된
발동기의 `lookup` 을 보지 않는다. 그래서 `Duel._activator` 를 바꿔도
`apply` 는 "허가된 행위가 아닙니다" 로 거절한다.

**Phase 6-K 가 만든 것이 아니라 원래 그런 것**이고, B3 의 범위가 아니므로
고치지 않았다. `test_l04` 가 그 사실을 단언으로 적어 둔다.

---

## 6. §4-D — 유발 효과와의 관계 (§10)

### D-1. 기동 효과는 트리거 계층의 일이 **아니다**

| | 기동 효과 | 유발 효과 |
|---|---|---|
| 시점을 정하는 것 | **플레이어의 선언** | **사건** |
| 공식 근거 | RULE-EFFECT-002 (`"your Main Phase"`) | RULE-EFFECT-004 (`"specific times"`) |
| 엔진의 입구 | `PlayerAction(ACTIVATE_EFFECT)` | `TimingEvent` → `TriggerCollector` |
| Lua | `SetCode` **없음** | `SetCode(EVENT_*)` |

실측: 어니스트 ① 의 `EffectSpec.code` 는 `None` 이다. 코퍼스 전체에서
`IGNITION` 블록은 사건 코드를 갖지 않는다.

그래서 이번 Phase 는 **트리거 계층을 한 줄도 건드리지 않았다.** 6-I 가
만든 `compiled_triggers` 로 어니스트를 훑으면 등록된 트리거가 **0건**이다
(`test_trigger_duel_integration::test_03` 이 전수로 확인).

### D-2. 임의 효과의 발동 여부를 엔진이 정하지 않는다 (§10)

유발 · 유발 즉시 · 플립 분류는 **범위 밖**으로 남겼고, 각자 다른 이유를
들고 있다 (§7). 특히 유발 즉시는 **룰북이 발동 시점을 적지 않았다** —
구조화 데이터가 그 사실을 `not_stated: ["activation_timing"]` 으로 기록해
두었다. 확인되지 않은 시점을 "언제든 된다" 로 읽으면 스펠 스피드 2 가 아무
때나 끼어든다.

---

## 7. §5 — 효과 종류별 발동 정책

🔴 **카드 타입별 허용표로 구현하지 않았다** (§5 금지). 축은 **효과**에
붙고, 카드 종류와 **둘 다** 봐야 통과한다
(`activation_is_monster_ignition`).

### 축의 근거 — 공식 룰북 넷

`data/rules/structured/sd-rulebook-en-v10.json` 의 `effect_types`:

| `ActivationKind` | 룰북의 분류 | `activation_timing` | 스펠 스피드 | 근거 | 이번 범위 |
|---|---|---|---|---|---|
| `IGNITION` | Ignition Effect | `"your Main Phase"` | 1 | RULE-EFFECT-002 | **범위 안** |
| `TRIGGER` | Trigger Effect | `"specific times…"` | 1 | RULE-EFFECT-004 | 범위 밖 — 사건이 시점을 정한다 |
| `FLIP` | Flip Effect | `"when a face-down card is flipped face-up"` | 1 | RULE-EFFECT-005 | 범위 밖 — 뒤집는 절차가 없다 |
| `QUICK` | Quick Effect | **`null` (`not_stated`)** | 2 | RULE-EFFECT-003 | 범위 밖 — **룰북이 적지 않았다** |

- **지속 효과는 축에 없다.** 룰북이 `has_activation: false` 라고 적는다
  (RULE-EFFECT-001) — 발동하지 않는 것에 "어떻게 발동하는가" 를 붙이면 그
  자체가 거짓이다.
- **마법 · 함정의 발동(`EFFECT_TYPE_ACTIVATE`) 도 축에 없다.** 카드 종류로
  이미 판정되고 있고, 같은 질문에 답하는 자리를 둘로 만들면 둘이 갈라진다.
- `engine` 은 `rules` 를 import 하지 않는다. **테스트가 대조한다**
  (`test_a01` · `test_a03`) — `engine/activation_timing.py` 가 스펠 스피드
  표에 대해 적어 둔 약속과 같은 자리다.

### 🔴 EDOPro 의 `_O` / `_F` 접미사를 축에 넣지 않았다

처음 구현은 여섯 멤버(`TRIGGER_O` · `TRIGGER_F` · `QUICK_O` · `QUICK_F` ·
`IGNITION` · `FLIP`)였고, 그 docstring 이 `_O` 를 *(임의)* · `_F` 를
*(강제)* 로 적었다. **기존 감사가 그것을 잡았다** —
`tests/test_effect_type_quick_audit.py::test_32` 가 "production 코드에서
접미사를 해석하는 자리가 **0곳**" 을 AST 로 고정하고 있었고, `test_29` 가
그 뜻풀이에 **공식 근거가 없음**을 이미 측정해 두었다.

그래서 **테스트를 고치지 않고 production 을 고쳤다.** 축을 룰북의 넷으로
줄였고, `SetType(EFFECT_TYPE_TRIGGER_O)` 도 `TRIGGER_F` 도 손으로 옮길 때
`TRIGGER` 하나가 되며 **엔진은 어느 쪽이었는지 모른다.** 강제 · 임의 축은
`engine/trigger.py` 의 `TriggerRequirement` 에 따로 있고 그쪽은
`TriggerSpec` 이 근거를 들고 온다 — 두 축을 섞지 않는다.

같은 감사(`test_settype_clone_contamination_audit::test_27`) 가
`engine/` 코드에 `effect_types` 라는 **이름**이 나타나는 것도 금지한다.
처음에는 `EngineVocabulary.effect_types` 라는 `ConstantGroup` 을 두었고
`test_37` 이 그것을 잡았다. 감사에 예외를 더하면 그 감사가 조용히
약해지므로 **이름을 바꿨고**, 축의 근거가 상수 파일이 아니라 룰북이므로
결국 그 묶음 자체를 **지웠다.**

### 분류별 거부 이유 (`MONSTER_ACTIVATION_MISSING_BY_KIND`)

```
TRIGGER  trigger-effect-activation (유발 효과는 사건이 시점을 정한다 —
         RULE-EFFECT-004, 트리거 계층의 일)
FLIP     flip-effect-activation (앞면으로 뒤집히는 사건이 시점이다 —
         RULE-EFFECT-005)
QUICK    quick-effect-activation (룰북이 발동 시점을 적지 않는다 —
         RULE-EFFECT-003 의 not_stated)
```

모듈 적재 시점의 `assert` 가 "분류 중 어느 쪽에도 적히지 않은 것이 없다" 를
지킨다 — 적지 않으면 그 분류는 조용히 범위 밖이 되고 왜 막혔는지 아무도
모른다.

---

## 8. §6 — 최소 효과 유형 선정

### 선정: **몬스터의 기동 효과**, 그중 어니스트 ①

§6 의 권고 순서(1 = 기동 효과)를 그대로 따랐다. 조사해 보니 유발 효과의
최소 경로가 더 안전하지도 단순하지도 않았다 — 유발 효과는 시점이 사건이고
(RULE-EFFECT-004) 트리거 계층이 아직 효과를 실행하지 않는다 (6-J).

### 코퍼스 측정 — 기동 효과 깔때기

분석된 효과 **26,352**건 중 분류별 등장 수:

| 분류 | 수 |
|---|---|
| `TRIGGER_O` | 6,002 |
| `ACTIVATE` | 4,293 |
| `IGNITION` | **4,106** |
| `TRIGGER_F` | 1,866 |
| `QUICK_O` | 1,854 |
| `FLIP` | 189 |
| `QUICK_F` | 15 |

기동 효과를 좁혀 가면:

| 단계 | 수 |
|---|---|
| 기동 효과 | 4,106 |
| └ 몬스터의 기동 효과 | 3,480 |
| &nbsp;&nbsp;└ 발동 위치가 `MZONE` 단독 | 2,209 |
| &nbsp;&nbsp;&nbsp;&nbsp;├ 1턴에 1번 제약 있음 | 1,841 |
| &nbsp;&nbsp;&nbsp;&nbsp;├ 비용 있음 | 203 |
| &nbsp;&nbsp;&nbsp;&nbsp;├ 발동 조건 있음 | 69 |
| &nbsp;&nbsp;&nbsp;&nbsp;├ 해결 동작 미해독 | 58 |
| &nbsp;&nbsp;&nbsp;&nbsp;├ 해결 동작 막힘 | 6 |
| &nbsp;&nbsp;&nbsp;&nbsp;└ **남은 후보** | **32** |

🔴 **32건 중 거의 전부가 "카운터 비용" 이다.** 왕립 마법도서관(마력 카운터
3개), 마법의 꼭두각시 인형(2개), 운마물 계열(포그 카운터), 도토리 다람쥐,
웜 일리단… 이들의 공식 텍스트는 "카운터를 N개 제거하고 발동할 수 있다" 로
적는데, `CostKind` 분석은 **그 제거를 비용으로 보지 않는다** (분석기가
`SetCountLimit`/`RemoveCounter` 를 비용 축으로 옮기지 않는다). 카운터 계층
자체가 이 엔진에 없으므로, 이들을 등재하면 **비용을 치르지 않고** 효과가
나간다.

> 이것이 이 Phase 의 가장 중요한 측정이다 — "비용 없음" 필터가 몬스터
> 기동 효과에서는 **믿을 수 없다.**

카운터 비용이 없는 것은 "이 카드를" 가리키는 넷뿐이었다 (어니스트 · 젬
코끼리 · 다크 어니스트 · 사신 이레이저). 거기서:

- **다크 어니스트** — "1턴에 1번" 이 붙는다. 효과마다 세는 자리가 없다.
- **사신 이레이저** — ② 로 자기를 파괴하면 ③("파괴되어 묘지로 보내졌을
  경우에 **발동한다**", 강제 유발)이 따라와야 한다. 그 계층이 없으므로
  등재하면 **규칙을 조용히 어긴다.**
- **젬 코끼리 · 어니스트** — 남는다. 공식 텍스트가 ①②로 갈려 블록 경계가
  분명한 쪽을 골랐다.

### 선정한 유형에 대한 §6 항목

| 항목 | 답 |
|---|---|
| 선행 상태 | 앞면 표시로 **메인 몬스터 존**에 있다. 자기 턴, 메인 페이즈 1 또는 2, 체인이 비어 있다 |
| 지원 시점 | 체인 1 의 발동만. 체인이 열려 있으면 스펠 스피드 관문이 `UNKNOWN` 으로 막는다 |
| 필요한 `PlayerAction` 데이터 | `kind=ACTIVATE_EFFECT` · `actor` · `source` · `effect_ref`. **대상 없음.** 계약 변경 **0건** |
| 검증 가능한 조건 | 컨트롤러 · 턴 플레이어 · 페이즈 · 자리 · 표시 형식 · 발동 분류 |
| 검증 **불가능**한 조건 | "1턴에 1번" (효과마다 세는 자리가 없다) · 뒷면 효과 무효 규칙 · `IsRelateToEffect` · 효과마다의 발동 위치(`SetRange`) |
| 기존 체인 경로 | 그대로 쓴다. `EffectActivator` → `Chain.push` 를 한 줄도 바꾸지 않았다 |
| 해결 지원 여부 | **아니다.** `operations` 가 비어 있다 — 이유는 §10 |

---

## 9. §7 — `ACTIVATE_EFFECT` 확장: **계약 변경이 필요하지 않았다**

§7 은 계약을 크게 바꿔야 하면 즉시 수정하지 말고 최소 변경안을 보고하라고
했다. 조사 결과 **바꿀 것이 없었다.**

| §7 의 조건 | 상태 |
|---|---|
| 어느 효과인지 지목 | 이미 `effect_ref` 필수 (`_NEEDS_EFFECT_REF`) |
| 발동하는 카드 | 이미 `source` 필수 (`_NEEDS_SOURCE`) |
| 대상 | 이미 `targets` (개수 제한 없음) |
| 새 `PlayerActionKind` | **만들지 않았다** |
| 새 칸 | **만들지 않았다** |
| 구조 검사 | 한 줄도 바꾸지 않았다 |

`PlayerAction` · `ActionTarget` · `ConditionContext` 의 dataclass 칸이
Phase 6-K 전후로 **동일**하다. 테스트가 그것을 센다
(`test_official_activation_player_action_contract::test_04` 가
`_NEEDS_EFFECT_REF` 를 못박는다).

---

## 10. §8 — 변경 내역 (production 7파일, +577 −40)

| 파일 | +/− | 무엇 |
|---|---|---|
| `engine/action_validation.py` | +308 −32 | 등록소 수용 · 분류별 이유 · 몬스터 분기 · 기동 효과 요구 둘 |
| `engine/effect/library.py` | +97 −1 | 어니스트 ① 등재 (`executable=False`) + `OPERATION_RULINGS` |
| `engine/vocabulary.py` | +66 −1 | `ActivationKind` 넷 (룰북 근거) |
| `engine/duel.py` | +54 −5 | 발동 출발지에 몬스터 존 · 배치 없는 발동 · 등록소 배선 |
| `engine/effect/definition.py` | +31 | `EffectDefinition.activation_kind` + 타입 검사 + 정규 표현 + 직렬화 |
| `engine/spell_activation.py` | +15 | `PLACEMENT_SOURCE_ZONES` |
| `engine/activation.py` | +6 −1 | `_verdict` 가 등록소를 넘긴다 |
| **합계** | **+577 −40** | production 7파일 |

### 왜 어니스트 ① 의 `operations` 가 비어 있는가

```lua
function s.operation1(e,tp,eg,ep,ev,re,r,rp)
	local c=e:GetHandler()
	if c:IsFaceup() and c:IsRelateToEffect(e) then
		Duel.SendtoHand(c,nil,REASON_EFFECT)
	end
end
```

돌려보낼 카드가 **발동한 그 카드 자신**이다. 그런데 `CardOperation` 은
대상을 `TargetRef` **이름**으로 가리키고, 그 이름에 "이 효과의 카드" 를 넣는
길이 없다:

- `TargetRequirement` 넷은 전부 **고르거나 · 무작위이거나 · 전부**다.
- `CandidateSource.exclude_source` 는 자신을 **빼는** 쪽만 있다.
- 후보 조건(`require`)으로도 쓸 수 없다 — `CandidateResolver` 가 후보마다
  문맥의 `source` 를 **그 후보로 바꿔** 판정하므로 (`engine/cost/resolver.py`)
  원래 발동한 카드가 거기서 사라진다.

`ResolutionContext.source` 에는 그 카드가 **이미 있다.** 모자란 것은 정의가
그것을 가리키는 **이름**이고, 그 이름을 더하는 것은 대상 축에 다섯 번째
모양을 더하는 일이다. §14 가 큰 구조 변경에 승인을 요구하므로 **여기서
멈추고 사실만 적었다** (§17).

🔴 그래도 **싣는다.** 빼 버리면 "몬스터 효과의 발동 분류를 적을 수 있게
되었다" 는 사실이 아무 데도 남지 않고, `activation_kind` 가 실제 데이터에서
한 번도 쓰이지 않는 칸이 된다. `_DARK_HOLE_ENTRY` 가 "하는 일을 적지 않은
채로" 실려 있는 것과 같은 자리다.

---

## 11. §11 · §13 — 테스트

### 새 파일 — `tests/engine/test_monster_effect_activation.py` (48개, 실측 `--collect-only`)

| 묶음 | 수 | 지키는 것 |
|---|---|---|
| A 어휘 축 | 4 | 룰북 넷과 1:1 · 지속 효과 제외 · `_O`/`_F` 제외 · 분류마다 자리가 있다 |
| B 운반칸 | 4 | 문자열 거부 · `None` 은 "적지 않았다" · 정규 표현에 들어간다 · 손으로 하나만 적혔다 |
| C 등록소 없음 | 4 | **Phase 6-K 이전과 같은 답** · 정의 없음 · 분류 미기재 · 통상 몬스터는 더 앞에서 막힌다 |
| D 기동 효과 | 3 | `VALID` · 술어가 둘 다 본다 · 마법 정의의 `IGNITION` 은 몬스터 경로로 안 간다 |
| E 분류별 이유 | 4 | 셋이 각자 다른 이유로 막힌다 |
| F 자리 · 표시 형식 | 3 | `GRAVE`/`EMZONE`/`HAND` 는 `UNKNOWN` · EMZ 제외가 선택이다 · 뒷면은 다른 이유 |
| G 규칙이 금지 | 5 | 상대 턴 `INVALID` · 배틀/엔드/스탠바이 `INVALID` · 메인 2 는 `VALID` |
| H 마법 경로 | 1 | 욕망의 항아리가 끝까지 간다 |
| I 배치 | 3 | 꽉 찬 존에서도 `VALID` · 배치 자리에 몬스터 존 없음 · `_place_activated` 가 `None` |
| J 스펠 스피드 | 1 | 체인이 열리면 여전히 막힌다 (체인 1 전용) |
| K 후보 | 2 | 몬스터 존이 출발지다 · 후보는 생기지 않는다 |
| L 막는 것이 구현 | 4 | 이유가 바뀌었다 · 체인 0 · `apply` 거절 · 시험용 권한으로 배치 경로 확인 |
| M 기르수 | 2 | 실제로 기동 효과다 · **억지로 실행시키지 않았다** |
| N 금지 사항 | 5 | 카드 ID 분기 0 · 종류만으로 허가 안 함 · 등록소는 선택 · 모양 검사 · 배선 3자리 |

### §11 기르수 (69811710)

측정: `e[2]` 가 **실제로** `EFFECT_TYPE_IGNITION` + `SetRange(LOCATION_MZONE)`
다 — 즉 이번 Phase 의 범위 **모양**이다. 그런데:

- 하는 일이 `special_summon` 이고 **토큰**이다 (6-J 의 B2 + 토큰 계층 없음)
- "1턴에 1번" 이 붙는다

🔴 **정의를 등록하지 않았다.** 그래서 분류를 읽을 길이 없고, Phase 6-K
이후에도 범위 밖이며 이유는 "효과의 발동 분류가 적혀 있지 않다" 다 — 그것이
참이다. 기르수 전용 예외 처리도 카드 ID 분기도 **없다**
(`test_n01` 이 production 코드의 정수 상수를 AST 로 훑어 기르수의 번호가
**0곳**임을 센다).

### 움직인 기존 감사 핀 — 서른넷

**기존 테스트를 지우지도 skip 을 더하지도 않았다.** threshold 를 완화한
자리도 없다. 움직인 핀은 두 종류다.

1. **"그 시점에 참이었던 수"** — `len(EFFECT_LIBRARY) == 16` (19자리),
   `EffectDefinition` 10칸 (8자리), 실행 불가 3건, `_ENTRY` 변수 16개,
   `OPERATION_RULINGS` 17장.
2. **사실이 바뀐 자리** — 각각 왜 바뀌었는지를 그 자리에 적었다.

사실이 바뀐 자리에서 단언을 **지우지 않고 갈랐다**:

| 테스트 | 전 | 후 |
|---|---|---|
| `test_12_every_registered_effect_belongs_to_a_spell_or_trap` | 몬스터 0장 | 몬스터 1장, **실행되는 쪽은 여전히 0장** |
| `test_a_the_engine_targets_activate_only_cards` | 등재 전부 `ACTIVATE` | **실행하는** 것은 전부 `ACTIVATE`, 아닌 것은 어니스트 하나 |
| `test_09_but_every_registered_trap_is_free_chain` | 등재 전체가 `EVENT_FREE_CHAIN` | **마법 · 함정 전체**가 그렇다 (몬스터는 코드가 없다) |
| `test_09_no_registered_effect_needs_a_trigger_event` | 코드 하나, 종류 하나 | 코드는 하나 아니면 없음, 종류에 **유발 계열 0** |
| 단일 블록 루프 4자리 | 전부 블록 1개 | 몬스터는 블록 3개이고 `code` 가 없다 |

세 자리는 **지문**이 바뀌었다 (`_activation_sources` 의 자리 목록이 상수로
옮겨졌다 · `_NormalSpellActivation` 호출에 인자가 늘었다 ·
`ActionValidator(self.view(seat))` 에 `definitions=` 가 붙었다). 지문이
지키던 사실(자기 자리만 본다 · 관문이 있다 · 관측을 넘긴다)은 그대로 두고
**더 적었다.**

### Mutation 테스트 — 21개, 생존 0

`engine/` 의 내 코드에 고의 결함을 하나씩 넣고 새 테스트 48개를 돌렸다.

| | 결과 |
|---|---|
| 분류를 읽지 않고 언제나 `IGNITION` | killed (4 failed) |
| 카드 종류를 보지 않는다 | killed |
| EMZ 를 범위에 넣는다 | killed (2 failed) |
| 뒷면 검사를 뺀다 | killed |
| 네 분류 전부를 범위에 넣는다 | killed (적재 시점 `assert`) |
| 기동 효과에 빈 칸을 요구한다 | killed |
| 턴 플레이어 요구를 뺀다 | killed |
| 분류별 이유를 하나로 묶는다 | killed (3 failed) |
| 배치 자리에 몬스터 존을 넣는다 | killed (3 failed) |
| 배치 없는 발동에도 `place` 를 부른다 | killed (2 failed) |
| 놓인 것이 없어도 `pending` 에 넣는다 | killed |
| 출발지에서 몬스터 존을 뺀다 | killed (2 failed) |
| 문자열 분류를 그대로 받는다 | killed |
| 분류를 정규 표현에서 뺀다 | killed |
| 등록소 모양 검사를 뺀다 | killed |
| 어니스트를 `executable=True` 로 | killed |
| **등록소 배선을 지운다 (3자리)** | **처음에는 생존 → 테스트를 보강했다** |

🔴 **생존 둘이 가르친 것**: `Duel` 과 `EffectActivator` 가 검증기에 등록소를
넘기는 자리를 지워도 48개가 전부 통과했다. 지우면 판정이 **더 좁아지기만**
하므로 어떤 거부도 일어나지 않고, 후보가 0건인 지금은 **동작으로도 보이지
않는다.** 조용히 좁아지는 것은 조용히 틀린 것이다. 그래서

- `test_l02` 가 `ActivationStatus` 까지 본다 (`UNAUTHORIZED` 와
  `NOT_IMPLEMENTED` 는 같은 `ValidationCode` 를 쓴다)
- `test_n05` 가 production 세 호출 자리를 AST 로 센다

를 더했고, 셋 다 killed 가 되었다. **생존 0.**

### 🔴 작업 중 사고 — `git checkout` 으로 커밋하지 않은 작업을 날렸다

첫 mutation 하네스가 되돌리기에 `git checkout -- <path>` 를 썼다. 그 시점에
production 변경이 **커밋되지 않은 상태**였으므로 다섯 파일
(`action_validation.py` · `duel.py` · `activation.py` ·
`spell_activation.py` · `effect/definition.py`) 의 작업이 전부 사라졌다.

전부 다시 적었고, `tests/engine` 3,128개가 다시 통과함을 확인한 뒤
**먼저 커밋**하고 mutation 을 다시 돌렸다. 두 번째 하네스는 원본을 메모리에
들고 있다가 그대로 되돌리고, 되돌린 내용이 원본과 같은지 `assert` 한다.

---

## 12. §12 — 완료 수준

### ✅ 수준 1 — 발동 경로 확보

- `ActionValidator` 가 몬스터의 기동 효과에 **`VALID`** 를 낸다
- 상대 턴 · 메인 페이즈 밖은 **`INVALID`** (규칙이 금지한다)
- 자리 · 표시 형식 · 다른 분류는 **`UNKNOWN`** (우리가 모른다)
- 체인 1 에서 타이밍 관문을 통과한다
- 배치 없는 발동이 배치 계층을 터뜨리지 않는다
- 막는 것이 **`registered effect implementation`** 하나로 좁혀졌다 (ADR-006)

### ❌ 수준 2 — 실제 발동 및 해결 **미달성**

- 체인 길이 **0**. 어니스트는 패로 돌아가지 않는다
- `legal_actions` 의 발동 후보 **0건**
- 해결된 몬스터 효과 **0건**
- 막는 것 하나: **정의가 "이 효과의 카드" 를 가리킬 이름이 없다**

> 🔴 전체 Phase 가 성공했다고 적지 않는다. **발동 경로 확보, 실제 효과
> 해결 미달성**이다.

---

## 13. §13 — 테스트 실행 결과

pytest 의 **실제 종료 코드**로 판정했다. `tail` · `grep` 등 출력 필터의
종료 코드로 판단하지 않았다.

| 묶음 | 결과 | 종료 코드 |
|---|---|---|
| 새 파일 단독 | 48 passed | — |
| `tests/engine` (복원 검증) | 3,128 passed | — |
| 어휘를 훑는 감사 6파일 + 새 파일 | 197 passed | **`REAL_EXIT_CODE=0`** |
| **이번 Phase 가 건드린 테스트 44파일 + `tests/engine` 전부** | **4,110 passed** | **`EXIT=0`** |
| 전체 (4분할 + `engine`/`agent`/`rules`/`rulings`) | §18 | — |

---

## 14. §14 — B3 집중 · 구조 변경

B3 **하나만** 다뤘다. 손대지 않은 것:

- 스펠 스피드 (`engine/activation_timing.py` 를 **읽기만** 했다)
- 트리거 계층 (`engine/trigger*.py` 전부)
- B2 (소환 판정) · B1 (소생 제한)
- `integration/` 전부
- 대상 축 (`TargetRequirement` · `CandidateSource`)
- 비용 · 카운터 계층
- `agent/` · `core/` · `sources/` · `analysis/` · `rules/`

**사용자 승인이 필요한 구조 변경**은 §17 에 적어 두고 진행하지 않았다.

---

## 15. §15 — 금지 사항 준수

| 금지 | 확인 |
|---|---|
| 카드 ID · 이름 하드코딩 분기 | `test_n01` — 어니스트의 번호는 `library.py` 의 **선언 한 곳**, 비교문 0곳. 기르수는 production 코드에 0곳 |
| 몬스터라는 이유만으로 허가 | `test_n02` · `test_d02` — 카드 종류와 효과 분류를 **둘 다** 본다 |
| 효과 종류와 카드 종류 혼동 | `test_d03` — 마법 정의의 `IGNITION` 은 몬스터 경로로 가지 않는다 |
| 유발 즉시를 발동 가능으로 처리 | `test_e01` — `QUICK` 은 `UNKNOWN`, 이유가 룰북의 `not_stated` 다 |
| 체인 링크를 무조건 만든 뒤 실패 | §5-C3 — 세 관문이 전부 통과한 뒤에만 비용이 치러진다 |
| 테스트용 권한을 production 에 | `test_l04` 의 등록소는 테스트 함수 안의 객체. `EFFECT_LIBRARY` 불변 |
| 기존 테스트 삭제 · skip 추가 · 단언 약화 | §11 — 서른넷을 **갈라서 더 적었다** |
| 기르수를 억지로 실행 | `test_m02` — 등재하지 않았고 범위 밖이다 |
| 공식 카드명 · 텍스트 번역 | 전부 `data/cards.cdb` 의 `desc` 원문 |
| 기존 commit rewrite · force push · 새 브랜치 | 없음 |
| 추측으로 구조화 | 네 분류 전부 룰북 행에 대응. `_O`/`_F` 는 근거가 없어 **넣지 않았다** |

---

## 16. §16 — 심층 분석

### 16-1. 왜 "분류가 없다" 가 **정확한 진단이 아니었는가**

B3 의 문장은 둘을 합치고 있었다.

1. "효과 분류를 적는 칸이 없다" — **참이었고**, 이번 Phase 가 고쳤다.
2. "그래서 스펠 스피드조차 정할 수 없다" — **체인 1 에서는 참이 아니었다.**

둘을 합쳐 놓은 동안, 고쳐야 할 것이 ①인지 ②인지 알 수 없었다. ②를 고치려면
스펠 스피드 계층을 효과 단위로 바꿔야 하고 그것은 큰 변경이다. ①만 고치면
되는 범위(체인 1 의 기동 효과)가 있다는 것이 이번 측정이다.

### 16-2. `None` 을 어느 분류로도 읽지 않는다

`activation_kind=None` 은 "분류가 없는 효과" 가 아니라 **"적지 않았다"** 다.
그래서 코퍼스의 3,480개 몬스터 기동 효과 중 등재된 하나를 뺀 전부가
Phase 6-K 이후에도 범위 밖이다. 일괄 변환을 하지 않았다는 것이 이 설계의
요점이고, 6-H 가 784건을 일괄 변환하지 않은 것과 같은 자리다.

### 16-3. 새 경로가 **체인 1 전용**인 것은 우연이 아니다

스펠 스피드 관문을 건드리지 않았으므로, 체인이 열린 판에서 몬스터는
`classify_spell_speed` 가 `None` 을 내고 관문이 `UNKNOWN` 으로 막는다.
즉 **기본값이 안전한 쪽**이다 — 기동 효과가 상대 턴에 끼어드는 일이
구조적으로 불가능하다.

### 16-4. 세 "모른다" 를 하나로 접은 것

`_declared_activation_kind` 는 셋을 `None` 으로 접는다 — 등록소를 받지
못했다 · 정의가 없다 · 분류를 적지 않았다. 구분해서 다르게 쓰는 자리가
아직 없고, **접은 결과가 더 넓어지지 않는다** (셋 다 범위 밖). 넓어지는
쪽으로 접었다면 그것은 거짓이 된다.

### 16-5. EMZ 를 넣지 않은 것이 **선택**이다

공식 스크립트는 기동 효과의 발동 위치를 `SetRange(LOCATION_MZONE)` 로
적는데, 그 상수가 엑스트라 몬스터 존을 포함하는지 이 저장소에서 확인된 바가
없다. `Zone` 은 둘을 **다른 존**으로 가른다. 확인되지 않은 대응을 선언하면
그것이 규칙처럼 굳으므로, `IGNITION_ACTIVATION_ZONES` 를 `{MZONE}` 로 두고
EMZ 의 기동 효과는 `IGNITION_LOCATION_MISSING` 으로 **이유를 남기며** 막는다.
출발지(`ACTIVATION_SOURCE_ZONES`)에는 EMZ 를 **넣었다** — 보지도 않으면
이유가 기록되지 않는다.

### 16-6. 발동 **위치**는 아직 효과 단위가 아니다

이번에 옮긴 것은 `SetType` 이고 `SetRange` 는 옮기지 않았다. 그래서 엔진은
"기동 효과는 앞면 메인 몬스터 존에서만" 이라고 판정하는데, 실제 규칙에는
묘지나 패에서 발동하는 기동 효과도 있다. 그것들은 `FALSE` 가 아니라
`UNKNOWN` 이고 이유가 `IGNITION_LOCATION_MISSING` 이다 — 없는 것을 "규칙이
금지한다" 로 적지 않는다.

### 16-7. 기존 감사가 설계를 두 번 고쳤다

- `test_32`/`test_29` → `_O`/`_F` 를 축에서 빼게 했다
- `test_37`/`test_27` → `effect_types` 라는 **이름**을 못 쓰게 했고, 결국
  `ConstantGroup` 자체를 지우게 했다

둘 다 **테스트를 고쳐 통과시키지 않고 production 을 고쳤다.** 감사에
예외를 더하면 그 감사가 조용히 약해진다 (6-I 가 `connectivity::test_04`
에서 배운 것과 같다).

### 16-8. 측정이 믿을 수 없었던 필터

§6 의 "비용 없음" 필터가 몬스터 기동 효과에서는 **카운터 비용을 놓친다.**
32건의 후보 중 거의 전부가 그 경우였다. 분석 계층이 `RemoveCounter` 를 비용
축으로 옮기지 않기 때문이고, 그 사실을 모르고 등재하면 **비용을 치르지 않고**
효과가 나간다. 다음 Phase 가 기동 효과를 넓힐 때 가장 먼저 봐야 할 자리다.

---

## 17. 🔴 다음 단계 — **사용자 승인이 필요한 구조 변경**

수준 2 를 달성하려면 아래 하나가 필요하다. §14 에 따라 **진행하지 않았다.**

### 제안 A — 정의가 "이 효과의 카드" 를 가리키는 이름 (최소 변경)

`ResolutionContext.source` 에 그 카드가 **이미 있다.** 모자란 것은 정의가
그것을 가리키는 이름이다.

- `TargetRequirement` 에 다섯 번째 값 (예: `SELF`) 또는
  `TargetSpec.self_reference()` 생성자
- `EffectExecutor._selection_for` 가 그 모양일 때 `context.source` 를
  그대로 선택으로 쓴다
- 영향: `engine/effect/target.py` · `engine/effect/executor.py` ·
  `engine/target_bridge.py` 와 그 세 곳을 고정한 테스트들

이것이 열리면 어니스트 ① · 젬 코끼리 ① 이 **실제로 해결된다**
(`to_hand` → `RETURN_TO_HAND` 는 6-J 가 이미 지원된다고 측정했다).

### 제안 B — 효과마다의 "1턴에 1번" (범위가 훨씬 넓다)

`count_limit` 을 효과 단위로 세는 자리를 만들면 §6 의 1,841건이 풀린다.
`GameState.rule_uses` 가 `(턴, 플레이어, instance_id, 행위)` 를 세고 있고
`UseRegistry` 가 이미 `EffectRef` 로 키를 잡을 수 있다.

### 제안 C — 카운터 계층

§16-8 이 측정한 32건의 후보 대부분이 여기 걸린다. 가장 크고 가장 위험하다 —
없는 채로 등재하면 비용을 치르지 않는다.

**권고 순서: A → B → C.** A 가 가장 작고, 열리는 것이 실제 효과 해결이다.

---

## 18. 전체 테스트 실행 결과

저장소 전체를 다섯 묶음으로 나눠 돌렸다 (`tests/*.py` 를 `split -n l/4` 로
넷으로 가르고 — `cat part00..03 | diff - all.txt` 로 누락 없음을 확인했다 —
거기에 `tests/engine` · `tests/agent` · `tests/rules` · `tests/rulings` 를
더한 다섯째 묶음).

| 묶음 | 결과 | 시간 |
|---|---|---|
| 1/4 (`tests/*.py`) | **678 passed** | 25:27 |
| 2/4 | **557 passed** | 15:25 |
| 3/4 | **576 passed** | 16:14 |
| 4/4 | **466 passed** | 10:27 |
| `engine` + `agent` + `rules` + `rulings` | **3,658 passed, 4 skipped** | 13:22 |
| **합계** | **5,935 passed · 4 skipped · 0 failed** | |

그 위에 **종료 코드를 직접 확인한** 두 번의 실행이 있다 (§13):

- 이번 Phase 가 건드린 테스트 44파일 + `tests/engine` 전부 →
  `4110 passed` · **`EXIT=0`**
- 어휘를 소스 텍스트로 훑는 감사 6파일 + 새 파일 →
  `197 passed` · **`REAL_EXIT_CODE=0`**

🔴 **출력 필터의 종료 코드로 판단하지 않았다** (§13). 위 두 줄은
`python3 -m pytest … ; echo $?` 로 pytest 자신의 종료 코드를 읽은 것이고,
분할 실행의 수는 pytest 가 스스로 적은 요약 줄이다.

### skip 4건

Phase 6-K 가 더한 것이 **아니다.** `tests/rulings` 의 기존 skip 이고
(공식 재정 수집 캐시가 없을 때), 6-J 보고서가 이미 같은 수를 적었다.
**skip 을 하나도 더하지 않았다.**

---

## 19. 🔴 다음 Phase

**다음 Phase 는 자동으로 시작하지 않는다.** §17 의 제안 A · B · C 는
구조 변경이고, §14 에 따라 사용자 승인을 기다린다.

