# Phase 3-F-6 — TriggerSpec 선언 스키마 감사

## 1. Phase · Base · 실제 HEAD

| 항목 | 값 |
| --- | --- |
| Phase | 3-F-6 — TriggerSpec Declaration Schema Audit |
| 모드 | **AUDIT-ONLY** (production diff 0) |
| Base | Phase 3-F-5 (`3eccab9` 작업 · `2d4c466` 보고서) |
| 3-F-5 최종 판정 | **B. SPECIAL_SUMMON_EVENT_FOUNDATION_PARTIAL** |
| **실제 HEAD (측정)** | `2d4c466 Phase 3-F-5 보고서: commit SHA · push 결과 기록` |
| branch | `claude/pensive-goodall-te1egy` |
| baseline 테스트 | 4,196 passed / 4 skipped |
| 새 테스트 | `tests/test_trigger_spec_declaration_audit.py` — **19건** |

`git log` 로 HEAD 를 직접 확인했고 작업 트리는 깨끗했다. 3-F-5 보고서의 판정
줄도 읽어 **B** 임을 확인했다.

**이 Phase 는 선언 데이터만 본다** (§9). 3-F-5 가 측정한 실행 경로
(Operation → Mutation → Delta → Event → Timing → Trigger → Activation) 를
다시 재지 않았고, `TriggerSpec` 을 production 에 연결하지 않았다.

---

## 2. TriggerSpec 전체 field

필드는 **아홉 개**다 (`test_01`).

| # | field | 의미 | 타입 | 기본값 | 사건을 좁히는 축인가 |
| --- | --- | --- | --- | --- | --- |
| 1 | `effect_ref` | 어느 효과의 선언인가 (identity) | `EffectRef` | **필수** | 아니다 |
| 2 | `point` | **어떤 사건에 반응하는가** | `TimingPoint` | **필수** | **그렇다** |
| 3 | `requirement` | 강제인가 임의인가 | `TriggerRequirement` | `UNKNOWN` | 아니다 |
| 4 | `wording` | "…한 때" 인가 "…한 경우" 인가 | `TriggerWording` | `UNKNOWN` | 아니다 |
| 5 | `operations` | 어떤 **의미**의 이동인가 | `frozenset[OperationKind] \| None` | `None` | **그렇다** (`CARD_MOVED` 한정) |
| 6 | `from_zones` | 어디에서 | `frozenset[Zone] \| None` | `None` | **그렇다** (`CARD_MOVED` 한정) |
| 7 | `to_zones` | 어디로 | `frozenset[Zone] \| None` | `None` | **그렇다** (`CARD_MOVED` 한정) |
| 8 | `activates_from` | **반응하는 카드가** 어느 자리에서 발동하는가 | `frozenset[Zone] \| None` | `None` | 아니다 |
| 9 | `condition` | 그때 무엇이 참이어야 하는가 | `Condition \| None` | `None` | 아니다 (**상태**만) |

### 축이 넷뿐임을 어떻게 확인했는가

`TriggerSpec.matches` 의 **본문만** AST 로 떼어내 `self.<field>` 를 셌다
(문자열 창으로 보지 않았다). 비교하는 것은 정확히
`{point, operations, from_zones, to_zones}` 이고, 나머지 다섯은 **읽지
않는다.**

`activates_from` 은 사건의 축이 아니라 **반응하는 카드의 자리**다 —
`_activation_zone` 관문이 `card.zone in spec.activates_from` 으로 쓴다.
"누가 그 사건을 일으켰는가" 와 혼동하면 안 된다.

### 기본값의 뜻

`None` 은 **"전부 허용" 이 아니라 "선언하지 않았다"** 다. `activates_from` 이
그 규칙을 docstring 에 명시한다 — 적지 않은 것을 "어디서든 발동 가능" 으로
읽지 않고 자리 관문을 `UNKNOWN` 으로 둔다. `to_dict()` 도 선언하지 않은 축을
**적지 않는다** (`test_12`).

---

## 3. field별 생성 / 소비 위치

### 생성

| 자리 | 무엇 |
| --- | --- |
| `TriggerRegistry.register(spec)` | 유일한 등록 입구. **손으로만** — 카드 데이터에서 자동 생성하는 컴파일러는 없다 (STRUCTURAL-7 · -21) |
| `TriggerRegistry.__init__(specs)` | 위를 반복 호출 |

production 코드 어디에도 `TriggerSpec(...)` 를 만드는 자리가 **없다.**
만드는 것은 테스트뿐이다.

### 소비 — 전부 `engine/trigger.py` 안이다

| field | 읽는 자리 (`engine/trigger.py`) | 무엇을 하는가 |
| --- | --- | --- |
| `effect_ref` | `:848` · `:904` · `:940` · `:955` · `:1265` · `:1271` · `:1291` · `:1469` · `:1481` · `:1538` | 정의 찾기 · 후보 identity · 후보/선언 일치 확인 |
| `point` | `matches` · `:1373` (`_event_relation`) | 사건군 비교 |
| `requirement` | `:907` | 후보에 그대로 실어 보낸다 (판정하지 않는다) |
| `wording` | `:908` | 같음 |
| `operations` | `matches` · `:1367` | 이동 의미 비교 · **읽을 수 없으면** `UNKNOWN` (3-E-45) |
| `from_zones` | `matches` · `:1368` | 같음 |
| `to_zones` | `matches` · `:1369` | 같음 |
| `activates_from` | `:1410` · `:1427` · `:1439` | `_activation_zone` 관문 |
| `condition` | `:928` (`TriggerCollector._judge`) · `:1458` (`_trigger_condition`) | 조건 평가 **두 군데** |

### LIVE / DORMANT

**`TriggerSpec` 이라는 이름을 아는 production 모듈은 `engine/trigger.py`
하나뿐이다** (`test_11` — 9개 루트의 모든 `.py` 를 읽어 확인).

dormant 다섯 모듈 중 `trigger_chain.py` · `trigger_order.py` ·
`timing.py` · `event_pipeline.py` **넷조차 이 타입을 모른다.**

| | |
| --- | --- |
| LIVE 소비자 | **없음** |
| DORMANT 소비자 | `engine/trigger.py` 안의 `TriggerRegistry.watching` · `TriggerCollector` · `TriggerEligibilityJudge` |
| `duel.py` | `TriggerSpec` · `TriggerRegistry` · `TriggerCollector` · `TriggerEligibilityJudge` · `TriggerCandidate` **전부 없음** |
| `Duel` 의 칸 | `trigger` · `registry` 가 든 필드 **없음** |

> **"잘 설계되어 있다" 와 "duel 에서 작동한다" 는 다르다** (§13).
> 이 선언 타입은 자기 파일 밖으로 한 걸음도 나가지 않는다.

---

## 4. EVENT 표현 가능성

### **DIRECTLY REPRESENTABLE** — 그것이 `point` 다.

`point` 는 실제로 사건군을 가른다 (`test_02`): `MONSTER_SUMMONED` 선언은
`CARD_DRAWN` 사건을 잡지 않는다. 공허한 축이 아니다.

그런데 소환이 든 `TimingPoint` 는 **하나**뿐이다.

```
[point.value for point in TimingPoint if "summon" in point.value]
  == ["monster_summoned"]        # 전체 8개 중
```

그래서 이 축으로 말할 수 있는 것은 **"몬스터가 소환되었다"** 까지이고,
"**어떤** 소환" 은 말할 수 없다.

---

## 5. SUMMON_KIND 표현 가능성

### **NOT REPRESENTABLE** — 자물쇠가 셋이다 (`test_03`).

| # | 자물쇠 | 측정 |
| --- | --- | --- |
| ① | **칸이 없다** | 아홉 필드 중 이름에 `summon` 이 든 것이 0개 |
| ② | **기존 필터가 금지된다** | `MONSTER_SUMMONED` 에 `operations`/`from_zones`/`to_zones` 를 주면 `__post_init__` 이 `TriggerError` — "카드 이동이 아닌 사건입니다" |
| ③ | **사건에서 꺼낼 창구가 없다** | `hasattr(event, "summon")` 이 `False`, `event.operation` 이 `None` |

그런데 **사실은 분명히 있다**: `event.delta.summon is SummonKind.SPECIAL`.
정보가 없는 것이 아니라 **선언이 그것을 가리킬 말을 갖지 못했다.**

### 우회로 셋도 측정해서 막았다

| 우회 | 결과 |
| --- | --- |
| `CARD_MOVED` + `to_zones={MZONE}` 로 소환을 잡는다 | **아무것도 잡지 못한다** — 소환은 `CardMovement` 가 아니라 `from_delta` 가 `MONSTER_SUMMONED` 를 준다. (같은 선언이 실제 `ZoneMoved` 는 잡는다 — 공허한 확인이 아니다) |
| `MONSTER_SUMMONED` 에 필터 셋 | 선언 자체가 **거절**된다 |
| 소환 종류마다 `point` 를 따로 쓴다 | 소환이 든 `TimingPoint` 가 **하나**뿐이다 |

---

## 6. ACTOR 표현 가능성

### **NOT REPRESENTABLE** (`test_04`).

- 사건은 행위자를 **들고 있다**: `event.actor` 가 `0` / `1`.
- 선언에는 `actor` 도 `player` 도 **없다**.
- `matches` 본문에 `"actor"` 와 `"player"` 가 **한 번도 나오지 않는다**
  (AST 로 본문만 떼어내 확인).

그래서 하나의 선언이 내 소환과 상대 소환을 **같게** 본다.

---

## 7. SELF / OPPONENT 표현 가능성

### **NOT REPRESENTABLE**, 그리고 **그 이유가 필드 부재가 아니다** (`test_05` · `test_15`).

"상대가" 는 절대 번호가 아니라 **관계**다 — `event.actor` 와 **반응하는
효과의 컨트롤러**를 비교해야 한다.

### 관계 어휘는 이미 있다

`PlayerRef.CONTROLLER` / `OPPONENT` 가 카드 텍스트의 "자신" / "상대" 에
대응하고, 문맥을 받아 번호로 풀린다.

```
PlayerRef.OPPONENT.resolve(ConditionContext(player=0)) == 1
PlayerRef.OPPONENT.resolve(ConditionContext(player=1)) == 0
```

**그런데 그것은 조건 계층의 어휘이고, 조건 계층은 사건을 보지 못한다** (§9).

### 선언을 거르는 자리들이 후보를 모른다

```
TriggerSpec.matches(event)                 ← 사건만
TriggerRegistry.watching(event)            ← 사건만
TriggerCollector.collect(event)            ← 사건만
```

그리고 `collect` 본문의 순서가 측정된다 — `watching(event)` 가 **먼저**
돌고 그 뒤에 `_candidates_for` 가 후보를 만든다. 즉 선언이 걸러지는 시점에
컨트롤러는 **아직 존재하지 않는다.**

### 🔴 다섯 관문 중 사건과 후보를 함께 보는 것이 **없다**

이 Phase 의 중심 측정이다 (`test_15`).

| 관문 | event 를 받는가 | candidate 를 받는가 |
| --- | --- | --- |
| `_event_relation` | **예** | **아니오** |
| `_activation_zone` | 아니오 | 예 |
| `_trigger_condition` | 아니오 | 예 |
| `_execution_authority` | 아니오 | 아니오 |
| `_cost_feasibility` | 아니오 | 예 |

사건을 받는 관문은 **하나**이고, 그 하나가 후보를 받지 않는다. 둘 다 받는
관문은 **0개**다.

`judge(candidate, spec, event)` 는 둘 다 받지만 **관문의 답을 접기만**
한다 (`fold`) — 본문에 `"actor"` 가 없다.

### 🟡 딱 한 군데는 둘을 함께 들고 있다

`TriggerCollector._judge(spec, event, card, definition)` 는 `event` 와
`card.controller` 를 **둘 다** 갖는다. 그러나:

1. 그것은 관문이 아니라 후보를 **만드는** 자리이고, 거기서 거부하면 같은
   사실이 `EVENT_RELATION`(관문)과 `TriggerStatus`(후보) **두 어휘로 갈려**
   적힌다. 이 파일이 바로 그 위험을 Phase 3-E-26 주석으로 경고해 두었고,
   그 주석이 `_judge` 본문에 실제로 있다 (측정).
2. 그 자리에서도 `ConditionContext(...)` 에 사건을 **넣지 않는다** —
   `player` · `source` · `effect_ref` 셋만 넣는다.

> 즉 비교해야 할 두 값이 **서로 다른 계층**에 있고, 둘을 합법적으로 만나게
> 할 자리가 설계에 **없다.** 필드를 더해도 비교할 자리가 생기지 않는다.

---

## 8. NORMAL / SPECIAL 표현 가능성

### **NOT REPRESENTABLE** (`test_06`).

두 축(종류 · 행위자)을 교차시켜 사건 넷을 만들었다. 네 사건은 **서로 다른
사실**이다 — `canonical_state()` 가 네 가지로 갈린다.

| 사건 | `point` | `actor` | `delta.summon` | 선언 하나가 잡는가 |
| --- | --- | --- | --- | --- |
| 내 일반소환 | `monster_summoned` | 0 | `normal` | **잡는다** |
| 내 특수소환 | `monster_summoned` | 0 | `special` | **잡는다** |
| 상대 일반소환 | `monster_summoned` | 1 | `normal` | **잡는다** |
| 상대 특수소환 | `monster_summoned` | 1 | `special` | **잡는다** |

`point` 는 넷 다 같고, 선언이 볼 수 있는 축은 그것뿐이다.
`registry.watching` 도 넷 모두에 대해 **1** 을 돌려준다.

---

## 9. EVENT + CONDITION 표현 가능성

### **절반만 된다** (`test_07`).

실제 듀얼에서 조건만 바꿔 두 번 판정했다.

| `condition` | `TRIGGER_CONDITION` | `EVENT_RELATION` |
| --- | --- | --- |
| `MZONE >= 1` (참) | `VALID` / `OK` | `VALID` / `OK` |
| `MZONE >= 99` (거짓) | **`INVALID` / `CANDIDATE_NOT_ELIGIBLE`** | `VALID` / `OK` |

- **조건 절반 = REPRESENTABLE WITH EXISTING FIELDS.** 관문이 실제로
  뒤집힌다.
- **사건 절반 = NOT REPRESENTABLE.** 조건을 뒤집어도 `EVENT_RELATION` 은
  그대로다.

### 조건으로 사건을 묻는 우회가 **구조적으로** 막혀 있다

| 측정 | 결과 |
| --- | --- |
| `ConditionContext` 필드 | `player` · `source` · `effect_ref` · `targets` — **사건 없음** |
| `Condition.evaluate` 매개변수 | `view` · `context` — **사건 없음** |
| 사건 · 시점 · 행위자를 묻는 조건 클래스 | **0개** |
| 소환이 든 조건 클래스 | **정확히 둘** — 아래 |

소환이 든 조건 클래스 둘은 `_NormalSummonRightAvailable` 과
`_NormalSummonProcedure` 이고, **둘 다 "지금 일반 소환을 할 수 있는가" 를
묻는 상태 술어**다. 본문에 `SummonKind` · `MonsterSummoned` ·
`TimingEvent` · `delta` 가 하나도 없다 (AST 로 본문만 떼어내 확인).

### 🟡 판이 기억하는 소환 사실은 하나뿐이고, 그것이 쓸 수 없는 하나다

`GameStateView` 에 소환 관련 접근자는 `normal_summons_used` **하나**뿐이고,
`RuleActionKind` 는 `{normal_summon, attack, set_spell_trap}` — **특수 소환이
없다.**

그래서 "상대가 이번 턴에 일반 소환했다" 는 상태로 알 수 있고, **"상대가
특수 소환했다" 는 알 수 없다.** 특수 소환은 그 권리를 쓰지 않으므로 아무
숫자도 늘리지 않는다.

### 🔴 그리고 판 자체가 소환 종류를 잊는다

`test_16` — 같은 카드를 **일반 소환**한 결과와 **패에서 특수 소환**한
결과를 판에서 비교했다.

```
zone=MZONE · position=FACEUP_ATTACK · controller=0 · owner=0
previous=('HAND','FACEDOWN',0) · counters={} · status_flags=0
materials=[] · equipped_to=None · temporary_effects=0
```

**완전히 같다.** `CardInstance` 14필드 중 소환 종류를 적는 칸이 없고,
`PreviousState` 는 `location`/`position`/`controller` 셋뿐이며,
`engine/state/` 전체에서 "summon" 이 나오는 파일은 `rule_usage.py`
하나다 (일반 소환권).

> 그러므로 **어떤 상태 술어로도 소환 종류를 복원할 수 없다.** 조건 우회의
> 두 번째 자물쇠다.

---

## 10. §4 일곱 요구 — 최종 판정표

| | 요구 | 판정 | 근거 |
| --- | --- | --- | --- |
| A | "특수소환이 발생했다" | **NOT REPRESENTABLE** | 종류 축이 없다 (`test_03` · `test_06`) |
| B | "일반소환이 발생했다" | **NOT REPRESENTABLE** | 같음 — 같은 `point` 하나 |
| C | "내가 특수소환했다" | **NOT REPRESENTABLE** | 종류 + 관계 둘 다 없다 |
| D | "상대가 특수소환했다" | **NOT REPRESENTABLE** | 같음. 그리고 관계는 **계층 문제** (`test_15`) |
| E | "특수소환 종류가 특정 값이다" | **NOT REPRESENTABLE** | 칸 없음 · 필터 금지 · 창구 없음 |
| F | "특수소환한 플레이어가 특정 플레이어다" | **NOT REPRESENTABLE** | `actor` 칸 없음, `matches` 가 보지 않음 |
| G | "특수소환 사건 + 추가 조건" | **PARTIAL** — 조건은 `REPRESENTABLE WITH EXISTING FIELDS`, 사건은 `NOT REPRESENTABLE` | `test_07` |

**`UNKNOWN` 은 하나도 없다** — 일곱 모두 코드를 읽어 확정했다.

### "어떤 Event 인가" 는 되는데 왜 A 가 안 되는가

`point` 로 "몬스터가 소환되었다" 는 선언할 수 있다. A 는 그보다 **한 칸
좁은** 요구이고, 그 한 칸이 없다. 사건군 선택과 사건군 **안에서의** 선별을
구분해야 이 표가 읽힌다.

---

## 11. 증식의 G 요구사항 검사 (§6)

**구현하지 않았다.** 카드 이름도 패스코드도 쓰지 않고 **구조로만**
적었다 (`test_08`). 카드의 실제 `code` 증거는 3-F-5 §9 에 이미 측정되어
있다.

요구: "상대가 SPECIAL_SUMMON 을 **성공적으로** 수행한 사건에 반응"

| 축 (§2) | 그 값을 들고 있는 자리 | 지금 있는가 | **선언할 수 있는가** |
| --- | --- | --- | --- |
| EVENT | `TimingEvent.point` | **있다** | **예** |
| EVENT TYPE | `TimingPoint.MONSTER_SUMMONED` | **있다** | **예** |
| SUMMON KIND | `event.delta.summon` | **있다** | **아니오** |
| ACTOR | `event.actor` | **있다** | **아니오** |
| SELF vs OPPONENT | `event.actor` ↔ `candidate.controller` | 둘 다 있다 — **같은 자리에 없다** | **아니오** |
| TRIGGER CONDITION | `TriggerSpec.condition` (상태만) | **있다** | **예** |

**필요한 정보는 여섯 축 모두 엔진 안에 존재한다.** 선언할 수 없는 것이
셋이고, 그 셋이 정확히 이 요구를 다른 요구와 구별하는 축이다.

"**성공적으로**" 는 추가 요구가 아니다 — 실패한 특수 소환은 delta 가 없고
사건도 없다 (3-F-5 §8). 성공만 사건이 되는 것이 이미 보장되어 있다.

SOURCE 축("어떤 효과로 인해 발생했는가")은 이 요구에 필요하지 않으므로
표에 넣지 않았다. `MonsterSummoned` 는 그 정보를 들고 있지 않다 —
소환은 효과의 어휘를 쓰지 않기 때문이다 (3-F-5 §5).

---

## 12. 후와로스 요구사항 검사 (§7)

**구현하지 않았다.** 요구: "**특정 종류**의 특수소환 발생에 반응"
(`test_09`).

### 증G 와 같은 정보가 필요한가 — **아니다. 한 축 더 깊다.**

| | 증G | 후와로스 |
| --- | --- | --- |
| EVENT / EVENT TYPE | 필요 · 선언 가능 | 같음 |
| SUMMON KIND (일반/특수) | 필요 · **선언 불가** | 같음 |
| ACTOR · SELF/OPPONENT | 필요 · **선언 불가** | 같음 |
| **어떤 특수 소환법인가** | 필요하지 않다 | **필요하다** |

### 그 축은 선언의 문제가 아니라 **어휘의 문제**다

`SummonKind` 는 `{normal, special}` **둘**뿐이고, `fusion` · `synchro` ·
`xyz` · `link` · `ritual` · `pendulum` 이 **하나도 없다.**

그것은 결함이 아니라 적어 둔 결정이다 (STRUCTURAL-62): "어떤 카드가 특수
소환되었는가" 와 "어떤 방법으로" 는 다른 질문이고, 절차가 생길 때 각자
이름을 갖는다.

> 즉 후와로스는 `TriggerSpec` 에 칸을 더해도 표현되지 않는다 — **담을 값
> 자체가 없다.** 증G 보다 한 계층 더 깊은 요구다.

---

## 13. 드롤과의 차이 (§8)

**드롤 트리거를 설계하지 않았다.** 차이만 측정했다 (`test_10`).

드롤이 요구하는 사건군은 "카드가 손에 들어왔다" 이고 그것은
`CARD_MOVED` 다. **거기서는 기존 필터가 허용되고 실제로 걸러낸다.**

| 선언 | 사건 | 잡는가 |
| --- | --- | --- |
| `CARD_MOVED` + `operations={RETURN_TO_HAND}` + `to_zones={HAND}` | 상대 필드 → 상대 패 | **예** |
| 같은 선언 | 상대 필드 → 상대 묘지 | **아니오** (실제로 거른다) |
| 같은 선언 | 드로우 (`CARD_DRAWN`) | 아니오 (별개 시점) |
| `MONSTER_SUMMONED` + `operations={SPECIAL_SUMMON}` | — | **선언 자체가 거절** |

> **같은 선언 구조가 사건군에 따라 다르게 동작한다.** 이것이 이 Phase 의
> 가장 짧은 요약이다. 필터는 `CARD_MOVED` 전용으로 지어져 있고, 특수
> 소환은 `CARD_MOVED` 가 **아니도록 일부러 갈라 놓은** 사건이다
> (ADR-002 와 같은 이유).

### 다만 행위자 축은 **양쪽 다** 막혀 있다

드롤 쪽도 "**상대가** 손에 넣었다" 는 적을 수 없다. 측정으로 확인했다 —
같은 `to_hand` 선언이 **내** 카드가 패로 돌아간 사건도 잡는다.

**그러므로 `TriggerSpec` 이 모든 패트랩을 하나로 표현해야 한다고 가정하지
않는다.** 사건군 차이는 **종류 축**에만 있고, **행위자 축은 공통
문제**다 — 그쪽이 더 깊은 결함이다.

---

## 14. canonical_state / state_hash (§11)

| 측정 | 결과 |
| --- | --- |
| `TriggerSpec.canonical_state()` 길이 | **9** — 아홉 필드를 다 담는다 |
| 서로 다른 선언을 가르는가 | **그렇다** (`activates_from` 유무로 달라진다) |
| 잎 노드 타입 | `int` · `str` · `None` 만 — 객체 주소가 없다 (replay 안전) |
| `to_dict()` | 선언하지 않은 축을 **적지 않는다** (`None` 을 빈 값으로 바꾸지 않는다) |
| `Duel` 에 등록소 칸 | **없다** |
| 등록소를 만들면 `state_hash` 가 바뀌는가 | **아니다** |
| 사건을 읽고 후보를 모으면 `state_hash`/RNG 가 바뀌는가 | **아니다** (`test_13`) |

### 새 필드가 들어온다면 무엇이 영향을 받는가 (기록만)

1. **`canonical_state()` 길이가 9 → 10 이상**이 된다. 이 값으로 선언을
   정렬하므로 (`TriggerRegistry.watching` 이 `canonical_state` 순으로
   정렬한다) **같은 등록소의 선언 순서가 달라질 수 있다.**
2. **`to_dict()` 의 키가 늘어난다.** 직렬화된 선언을 읽는 쪽이 생기면
   호환 문제가 된다. 지금은 읽는 쪽이 없다.
3. **`state_hash` 는 영향이 없다.** 선언은 판의 모양이 아니고 `Duel` 이
   들고 있지도 않다.
4. **replay 는 영향이 없다** — 같은 이유. 다만 1번 때문에 **선언 순서에
   의존하는 기록**이 생긴 뒤라면 영향이 생긴다.

**이 Phase 는 이 네 가지 중 아무것도 바꾸지 않았다.**

---

## 15. ValidationCode 와의 관계 (§12)

네 가지를 같은 `UNKNOWN` 으로 뭉개지 않았다 (`test_14`).

| 사실 | 지금 어떻게 나타나는가 |
| --- | --- |
| **선언에 행위자 칸이 없다** | **어떤 `ValidationCode` 로도 표현되지 않는다** — 스키마의 사실이고 판정의 사실이 아니다 |
| 지금 행위자를 판단할 수 없다 | **해당 없음** — 사건은 `actor` 를 **들고 있다** |
| 지금 조건이 거짓이다 | `INVALID` / `CANDIDATE_NOT_ELIGIBLE` (측정됨 — §9 표) |
| 규칙이 미구현이다 | `UNKNOWN` / `RULE_NOT_IMPLEMENTED` |
| 정보를 읽을 수 없다 | `UNKNOWN` / `INFORMATION_UNAVAILABLE` (3-E-45) |

### 🔴 그래서 틀린 승인이 난다

선언이 행위자를 적지 못한다는 사실이 `UNKNOWN` 으로 **새지 않는다.**
`EVENT_RELATION` 은 `VALID` / `OK` 를 낸다 — 내 일반 소환에도.

3-F-5 가 그 결과를 측정했고, **이 Phase 는 그 원인이 스키마임을 말한다.**
3-E-45 가 만든 정직한 세 번째 답(`INFORMATION_UNAVAILABLE`)은 "**적었는데**
읽을 수 없다" 일 때만 난다. 적을 칸이 없으면 그 길에 닿지 못한다.

> **표현할 수 없는 것을 `UNKNOWN` 으로 적는 길이 없다.** 이것이
> `ValidationCode` 의 문제가 아니라 선언 스키마의 문제인 이유다.

---

## 16. Engine V1 freeze 영향 (§14)

**해제하지 않았다** (`test_17`).

| 모듈 | production importer |
| --- | --- |
| `engine/event_pipeline.py` | **0** |
| `engine/timing.py` | **0** |
| `engine/trigger.py` | `activation_timing.py` 가 **`TimingPoint` 하나만** import |

`engine/activation_timing.py` 에 `TriggerSpec` · `TriggerRegistry` ·
`TriggerCollector` · `TimingEvent` 가 **하나도 없다** — 어휘 하나만 새어
나간다 (3-F-5 §6 이 측정한 빈 소켓).

금지 항목 전부 미실행: `TriggerRegistry` duel 연결 없음 · trigger/
event_pipeline/timing production 연결 없음 · EventBus 없음 · graph 없음 ·
Candidate pipeline 없음 · Activation loop 없음 · `LegalActions` 변경 없음 ·
`SPECIAL_SUMMON` legal action 추가 없음.

### Evaluation / Search 분리 (§15)

- Evaluation · weight · Search ranking/depth/algorithm **변경 0**.
- 순위를 **실제로 돌려** 못박았다 (`test_18`): 6판 **611결정**, digest
  `30fa3597a24d4511d8c92ce9f9921412ffada7546675c4d7d5765381402c4175` —
  3-F-5 와 **같은 값**이다.
- `agent/` 다섯 모듈에 `engine.trigger` · `TriggerSpec` · `SummonKind` 가
  하나도 없다.

---

## 17. 테스트 결과

### 새 테스트 — `tests/test_trigger_spec_declaration_audit.py` 19건

| # | 이름 | §16 항목 |
| --- | --- | --- |
| 01 | the declaration has exactly nine fields and four event axes | 1 |
| 02 | the only event axis that reaches a summon is the point | 2 |
| 03 | summon kind is not declarable anywhere in the spec | 3 · 6 |
| 04 | the actor is on the event but not in the declaration | 4 |
| 05 | self versus opponent needs two layers at once | 5 |
| 06 | one declaration cannot separate the four cases | 5 · 6 |
| 07 | the condition field works but cannot see the event | 7 |
| 08 | the opponent special summon requirement splits into six axes | 8 |
| 09 | the second requirement needs the same axes plus more | 9 |
| 10 | the card moved family can be narrowed and the summon family cannot | 10 |
| 11 | the declaration type has exactly one production module | 11 |
| 12 | the declaration has a canonical state over all nine fields | 12 |
| 13 | the registry touches neither state hash nor rng | 13 · 14 |
| 14 | four different refusals stay four different things | — (§12) |
| 15 | **no gate sees the event and the candidate together** | 5 |
| 16 | **the board cannot remember which summon it was** | 7 |
| 17 | engine v1 stayed frozen | 11 |
| 18 | the search ranking is unchanged | 15 |
| 19 | this phase added no production field and no card name | — (§19) |

```
$ python3 -m pytest tests/test_trigger_spec_declaration_audit.py -p no:randomly -q
19 passed in 10.62s
```

### 고의 위반 검증 — 7건, 전부 잡았다

| # | 위반 | 잡은 테스트 |
| --- | --- | --- |
| 1 | `TriggerSpec` 에 `summons` 필드를 더한다 | `test_01` · `test_03` · `test_19` |
| 2 | `MONSTER_SUMMONED` 에 필터를 허용한다 | `test_03` · `test_10` |
| 3 | `actor` 필드를 더하고 `matches` 에서 비교한다 | `test_04` · `test_05` · `test_06` · `test_10` · `test_14` · `test_19` |
| 4 | `ConditionContext` 에 `event` 칸을 더한다 | `test_07` |
| 5 | `_event_relation` 에 `candidate` 를 넘긴다 | `test_15` |
| 6 | 소환 종류를 판에 기록한다 (`counters`) | `test_16` · `test_18` |
| 7 | 예시 카드 패스코드를 production 에 더한다 | `test_19` |

6번이 `test_18`(순위 digest)까지 깨뜨린 것이 뜻밖의 확인이었다 — 판의 모양을
바꾸면 탐색 순위가 함께 움직인다는 것을 그 테스트가 잡아낸다.

주입 파일 4개(`trigger.py` · `condition/context.py` · `summon.py` ·
`duel.py`)는 전부 백업에서 복원하고 md5 로 확인했다 (모두 `OK`).

### 🟡 내가 쓴 단정 둘이 처음에 틀렸다 — production 이 아니라 테스트를 고쳤다

1. **`test_19`** — "예시 패스코드가 production 어디에도 없다" 고 적었는데
   **거짓**이었다. `23434538` 이 `scripts/fetch_ocg_rulings.py` 의 **재정
   수집 표본 표**에 이미 있다 (commit `6e46fe8`, 트리거와 무관한 rulings
   작업). 금지된 것은 **더하는 것**이므로, 기존 자리를 정확히 못박아
   **새로 생기면 걸리게** 바꿨다. 그 파일에 `TriggerSpec` ·
   `TimingPoint` · `SummonKind` · `MONSTER_SUMMONED` 가 없음도 함께
   확인한다.
2. **`test_07`** — "소환이 든 조건 클래스가 없다" 고 적었는데 **둘 있었다**
   (`_NormalSummonRightAvailable` · `_NormalSummonProcedure`). 이름으로
   뭉갠 단정이었다. 둘을 **정확히 열거**하고, 본문이 상태만 읽는다는 것을
   AST 로 확인하는 쪽으로 바꿨다. 그 과정에서 §9 의 `normal_summons_used`
   발견이 나왔다 — **판이 기억하는 소환 사실이 하나 있고 그것이 쓸 수 없는
   하나**라는 것.

두 경우 모두 **production 을 고치지 않았다.**

### 전체 회귀

```
$ python3 -m pytest tests/test_trigger_spec_declaration_audit.py -p no:randomly -q
19 passed in 10.62s

$ python3 -m pytest -p no:randomly -q
4215 passed, 4 skipped in 408.24s (0:06:48)
```

| | 통과 | skip |
| --- | --- | --- |
| Phase 3-F-5 직후 (baseline) | 4,196 | 4 |
| Phase 3-F-6 (이번) | **4,215** | 4 |
| 차이 | **+19** | 0 |

**+19 가 이번에 더한 시험 수와 정확히 같다.** skip 4건은 baseline 과 동일한
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

§10 이 요구한 여섯 질문에 답한다 — **새 필드가 정말 필요한가.**

| 질문 | 답 |
| --- | --- |
| 1. 정말 `TriggerSpec` 에 필요한 정보인가 | **소환 종류는 그렇다.** 사건을 좁히는 축이고, 선언이 적지 않으면 아무도 적을 수 없다. **행위자는 아니다** — 아래 |
| 2. Event 가 이미 가지고 있는 정보인가 | **둘 다 그렇다** (`delta.summon` · `event.actor`). 선언이 그것을 **가리킬 말**이 없을 뿐이다 |
| 3. TriggerCondition 이 가져야 하는 정보인가 | **아니다.** 조건은 "그때 무엇이 참인가" 이고 사건을 보지 않는다. 사건을 넣으면 조건 스무 개의 서명이 다 바뀐다 |
| 4. EventRelation 이 해결해야 하는 문제인가 | **종류는 그렇다** — `_event_relation` 이 이미 사건을 받는다. **행위자는 거기서 풀 수 없다** — 그 관문이 후보를 받지 않는다 |
| 5. 다른 계층에서 해결해야 하는 문제인가 | **행위자는 그렇다.** `event.actor` ↔ `candidate.controller` 비교를 어느 계층에 둘지가 먼저 결정되어야 한다 |
| 6. 기존 개념으로 표현 가능한가 | **아니다.** 셋을 다 측정해서 막았다 — 필터(금지) · 조건(사건 못 봄) · 상태(판이 잊음) |

### 설계 제안까지만 (구현하지 않았다)

**두 축이 서로 다른 성격의 변경이다.**

| 축 | 필요한 변경 | 성격 |
| --- | --- | --- |
| **소환 종류** | `TriggerSpec` 에 `summons: frozenset[SummonKind] \| None` + `TimingEvent.summon` 접근자 + `matches` 비교 1줄 + `__post_init__` 의 금지 규칙 완화 | **순수 추가** — 기존 계층 경계를 건드리지 않는다 |
| **행위자 / 상대** | `event.actor` 와 `candidate.controller` 를 **한 자리에서** 볼 수 있게 하는 결정 | **계층 경계 변경** |

행위자 쪽에 있는 선택지 셋(각자 무엇을 깨뜨리는지도 기록):

1. `_event_relation` 에 `candidate` 를 넘긴다 → 관문의 서명이 바뀌고,
   `_event_relation` 이 "사건만 보는 관문" 이라는 성격을 잃는다.
2. `TriggerCollector._judge` 에서 비교한다 → 같은 사실이 `EVENT_RELATION`
   과 `TriggerStatus` **두 어휘**로 갈린다 (Phase 3-E-26 이 경고한 모양).
3. 새 관문을 하나 더 만든다 → 다섯 관문이 여섯이 되고, `EVENT_RELATION`
   과의 경계를 새로 정의해야 한다.

**어느 쪽도 이 Phase 에서 고르지 않는다.** 그것이 다음 Phase 의 질문이다.

### `__post_init__` 의 금지는 **왜** 그렇게 적혔는가 (읽은 결과)

"`{point} 시점에는 {name} 를 걸 수 없습니다. 카드 이동이 아닌 사건입니다."

그 금지가 지키려던 것은 **거짓 필터를 막는 것**이다. `MONSTER_SUMMONED`
사건에서 `event.operation` 은 언제나 `None` 이므로, `operations` 필터를
허용하면 그 선언은 **아무것도 잡지 못하는** 선언이 된다 — 조용히 틀린다.

그러므로 소환 종류 칸을 더할 때 **그 금지를 풀어서는 안 된다.**
`operations` 는 계속 금지하고, `summons` 는 `MONSTER_SUMMONED` **에서만**
허용하는 쪽이 그 결정을 지킨다. (고의 위반 2번이 금지를 푼 경우이고,
`test_03` · `test_10` 이 그것을 잡는다.)

---

## 19. 최종 판정

### **C. TRIGGER_SPEC_ARCHITECTURAL_GAP**

근거:

1. **일곱 요구 중 여섯이 `NOT REPRESENTABLE`, 하나가 `PARTIAL`** 이다
   (§10). 그러므로 A 가 아니다.
2. **그중 하나는 단순 field 추가로 해결된다** — 소환 종류. 거기까지만
   보면 B 다.
3. **그러나 핵심 요구("상대가")는 field 추가로 해결되지 않는다.**
   비교해야 할 두 값이 서로 다른 계층에 있고, **사건과 후보를 함께 보는
   관문이 하나도 없다** (`test_15`). 어느 계층에서 비교할지를 먼저
   결정해야 하며, 세 선택지가 각각 다른 것을 깨뜨린다 (§18).
4. **우회로 셋이 모두 계층 경계에서 막힌다.**
   - 기존 필터 → `CARD_MOVED` 전용으로 지어져 있고, 그 금지에는 지킬
     이유가 있다
   - `condition` → `ConditionContext` 와 `Condition.evaluate` 에 사건이
     **없다.** 넣으려면 조건 스무 개의 서명이 바뀐다
   - 상태 → **판이 소환 종류를 잊는다** (`test_16`)
5. 그리고 그 부재가 **`UNKNOWN` 으로 표현되지 못하고 `VALID/OK` 로
   새어 나간다** (§15) — 선언 스키마의 공백이 판정 어휘에 자리를 갖지
   못한다는 뜻이다.

### 왜 B 가 아닌가

B 는 "하나 이상의 정보가 선언 구조에 부족하다" 다. 그것은 사실이지만,
B 로 적으면 **"칸을 더하면 된다"** 로 읽힌다. 소환 종류는 그렇고 행위자는
아니다. 이 Phase 가 실제로 측정한 것은 **행위자 축이 선언만의 문제가
아니라는 것**이고, 그것을 B 로 적으면 다음 Phase 가 칸만 더하고 같은 조용한
오답을 production 에 들여놓게 된다.

### 왜 D 가 아닌가

예상 밖의 더 큰 구조 문제는 없었다. §7 의 "관문이 둘을 함께 보지 못한다" 는
**예상보다 깊은** 결함이지만, 그 원인이 기존 설계 결정의 직접적 대가로
설명된다 — 소환을 `CARD_MOVED` 에서 일부러 갈라 놓았고(ADR-002 와 같은
이유), 필터는 `CARD_MOVED` 전용으로 지어졌고, 조건은 상태 전용으로
지어졌다. 새로운 모순이 아니다.

---

## 20. 다음 Phase 후보 (1개)

**Phase 3-F-7 — "상대가" 를 어느 계층에서 비교할 것인가: 관문 경계 설계 감사**

§18 이 적은 선택지 **셋만** 본다. 소환 종류 칸은 그 결정이 난 **뒤에**
함께 더하는 것이 맞다 — 지금 칸만 더하면 종류는 좁혀지는데 행위자는
여전히 `VALID/OK` 로 새어, **반쯤 맞는 선언**이 생긴다.

그 Phase 가 답해야 할 것:

1. 세 선택지가 각각 **무엇을 깨뜨리는지** 측정한다 — 기존 테스트 몇 개가
   서명 변경에 걸리는지, `GateVerdict` 어휘가 어떻게 갈리는지.
2. "사건만 보는 관문" 이라는 `_event_relation` 의 성격이 **지킬 가치가
   있는 것인지** 다시 읽는다 — 그 성격이 3-E-45 의 세 번째 답을 가능하게
   했다.
3. 비교가 들어갈 자리가 정해지면, **`UNKNOWN` 으로 적을 길이 생기는가** —
   선언이 행위자를 적지 않았을 때 `VALID/OK` 가 아니라 보류가 나야 한다.
   그것이 이 결함의 진짜 수리다.
4. `watching(event)` 가 후보 **전에** 돌아간다는 순서를 바꿔야 하는가.
   바꾸지 않고도 되는 선택지가 있는지 먼저 본다.

**이 Phase 는 그 작업을 하지 않았다. 다음 Phase 는 임의로 진행하지 않는다.**
