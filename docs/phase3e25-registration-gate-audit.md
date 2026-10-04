# Phase 3-E-25 — LibraryEntry Registration Gate / UnimplementedRule Enforcement Audit

## 1. HEAD / Base

| | |
|---|---|
| Base (지시) | `c13b817` |
| 실제 HEAD | `c13b817` — Phase 3-E-24 (동일) |
| Working tree | clean |
| Branch | `claude/pensive-goodall-te1egy` |

## 2. BLOCKER / Engine 변경

**BLOCKER: NO** · **Engine 변경: NO** (production diff 0줄). 추가한 것은
`tests/test_registration_gate_audit.py` (12개)와 이 문서.

## 3. 핵심 결론

> **등록 관문은 "출처 · 근거 · 서술 · 의미" 를 엄격히 막는데 ``activation``
> 조건에는 관문이 하나도 없다.** 그래서 기제는 **C(SILENT PASS)** 다.
>
> 그런데 **§11 의 설계 B(DORMANT REGISTRATION)는 코드를 한 줄도 바꾸지 않고
> 오늘 이미 가능하다** — 조건을 `UnimplementedRule` 로 적으면 등록은 통과하고
> 발동은 `UNKNOWN` 으로 막히며 `missing_rule` 에 이름이 남는다.
>
> 그리고 **지금 등록된 16개는 일관적이다** — 전수 대조 결과
> `activation=None` 인 것들은 **원문에도 조건이 없는** 것들이었다. 관문이
> 막지 않아도 사람이 지켰고, `lua_excerpt` 덕분에 그것을 **대조할 수 있었다.**

## 4. LibraryEntry 등록 경로

```
공식 Lua (c*.lua)
  ↓  (자동 변환 없음 — 아래 §10)
손으로 쓴 EffectDefinition 리터럴  (engine/effect/library.py)
  ├ activation: Condition | None     ← 관문이 보지 않는다
  ├ operations · targets · cost · requirements · guards
  └ provenance (source · verified)
  ↓
LibraryEntry(definition, lua_file, lua_excerpt, executable, note)
  ↓  __post_init__  ← 여기가 유일한 등록 관문
  ↓
definition_registry() / implementation_registry()
  ↓
EffectActivator.can_activate → _check_condition → ValidationResult
  ↓
Duel.legal_actions / Duel.apply
```

`__post_init__` 이 실제로 막는 것 (전부 `EffectDefinitionError`, `test_01` 이
하나씩 실측):

| 검사 | 막는 이유 |
|---|---|
| `OFFICIAL_LUA` 인데 `lua_file` 없음 | 근거 없는 정의는 추측이다 |
| `executable=False` 인데 `note` 없음 | **"무엇이 없어서인지" 를 반드시 적어야 한다** |
| `provenance.is_forbidden` | ADR-004 — 등록 자체를 거부 |
| `not provenance.verified` | 검증되지 않은 것을 실행하지 않는다 |
| `not definition.is_described` | 빈 효과를 실행하면 "아무 일도 없었는데 해결됐다" 가 된다 |
| `OperationKind.MOVE` | ADR-002 — 의미 없는 저수준 이동 |

**`activation` 에 대한 검사는 없다.** 관문 본문에 그 글자가 아예 나오지 않는다
(`test_02`).

## 5. condition=None 의 의미

**두 뜻이 한 값에 들어 있고, 두 모듈이 그것을 반대로 읽는다** (`test_05`).

| 모듈 | 적어 둔 뜻 | 하는 일 |
|---|---|---|
| `EffectActivator._check_condition` | "`None` 은 **'조건이 없다' 가 아니라 '적지 않았다'**" | **넘어간다** (= 참으로 친다) |
| `TriggerSpec.condition` | "`None` 이면 조건이 없다는 뜻이 아니라 적지 않았다는 뜻이다. **적지 않은 조건을 참으로 치지 않기 위해** 정의의 `activation` 도 함께 본다" | 정의에 미룬다 |

즉 **받침이 되어야 할 쪽(정의의 `activation`)이 `None` 이면 받치지 않는다.**
트리거 계층은 "참으로 치지 않겠다" 고 적고 정의 계층에 미루는데, 정의 계층은
`None` 을 통과시킨다. 사다리의 마지막 칸이 비어 있다.

## 6. all_of([]) 의 의미

`all_of([]) is TRUE` 는 **논리적으로 정상인 vacuous truth** 이고 **고치면 안
된다** (`test_06`) — 바꾸면 "조건이 진짜 없는 통상 마법" 이 발동할 수 없게 된다.
실제로 등록된 16개 중 5개가 그런 카드다.

문제는 규약이 아니라 **빈 조건이 무엇을 뜻하는가**다. 그리고 `UNKNOWN` 이 하나라도
섞이면 전체가 `UNKNOWN` 이므로, **빈 묶음과 "모르는 것이 든 묶음" 은 이미
구별된다.** 즉 `UnimplementedRule` 을 적으면 vacuous truth 경로를 타지 않는다.

## 7. UnimplementedRule — 등록 / 평가 / 실행

실측 (욕망의 항아리 정의의 `activation` 만 바꿔 끼우고 `can_activate` 를 물었다):

| `activation` | 등록 | `validity` | `code` | `missing_rule` |
|---|---|---|---|---|
| `None` | **통과** | **VALID** | `ok` | — |
| `UnimplementedRule("…")` | **통과** | **UNKNOWN** | `information_unavailable` | **"규칙 미구현: …"** |
| `Always()` | 통과 | VALID | `ok` | — |
| 원래 조건 (`ZoneCountAtLeast`) | 통과 | VALID | `ok` | — |

읽는 법:

* **`UnimplementedRule` 은 등록되고, 발동되지 않고, 이유를 남긴다.** 이것이
  §11 의 B 설계 그 자체이고 **지금 작동한다.**
* **`None` 과 `Always()` 는 판정에서 구별되지 않는다** (`test_04`). 구조에서는
  다른 값인데 결과가 같다 — 구별은 **표현에만** 있다.
* 직렬화는 보존된다 — `Condition.to_dict`/`canonical_state` 가 `UnimplementedRule`
  을 `("unimplemented", rule)` 로 적는다.

## 8. 네 경우 비교 (§5 의 Case A~D)

| Case | 등록 결과 | 발동 결과 | 지금 의미가 보존되는가 |
|---|---|---|---|
| **A** `condition=None` | 통과 | VALID | **아니다** — "조건 없음" 과 "적지 않음" 이 같은 값 |
| **B** `UnimplementedRule(...)` | 통과 | UNKNOWN + 이름 | **그렇다** |
| **C** `missing_rule` (조건이 `missing_rules` 를 돌려준다) | 통과 | B 와 같은 경로 (`UnimplementedRule` 이 그 수단이다) | 그렇다 |
| **D** 평가 결과가 `UNKNOWN` (정보 없음) | 통과 | UNKNOWN + `information_unavailable` | 그렇다 — 단 코드가 C 와 같다 (§13 의 🟡) |

A 만 의미가 겹친다. B·C·D 는 전부 `UNKNOWN` 으로 나가고 허가가 되지 않는다.

## 9. Registration vs Activation

**분리된다 — 구조로.** `test_11` 이 같은 엔트리가 "등록 통과 + 발동 거부" 가
되는 것을 실측했다.

```
REGISTRATION   LibraryEntry.__post_init__      출처 · 근거 · 서술 · 의미
    ↓
CANDIDATE      Duel._activation_actions         세 관문 전부 통과한 것만
    ↓
VALIDATION     EffectActivator.can_activate     조건 · 대상 · 권위
    ↓
ACTIVATION     EffectActivator.activate         비용 지불 + ChainLink
    ↓
EXECUTION      ChainResolver / EffectExecutor
```

등록 단계가 runtime 의미를 미리 결정하지 **않는다** — `UnimplementedRule` 이 그
증거다. 거꾸로, 등록을 막는 축이 이미 하나 있다: **출처**(ADR-004 금지 ·
미검증). 즉 이 repository 는 "출처는 STRICT GATE · 조건은 DORMANT 허용" 으로
축을 나눠 쓰고 있다.

## 10. Parser → LibraryEntry 경계

**경계가 아니라 단절이다.** `engine/effect/library.py` 는 `analysis` ·
`sources` · `core` 를 **import 하지 않는다** (`test_09`, AST 확인). 조건은
`engine.condition` 에서 가져와 **손으로 세운 리터럴**이고 `lua_excerpt` 가 근거로
따라붙는다 (ADR-006).

따라서 §9 가 걱정한 "parser failure 가 `condition=None` 으로 조용히 변환되는가" 는
**구조적으로 일어날 수 없다** — 변환 자체가 없다. 그 대신 사람이 옮기고,
`lua_excerpt` 가 **대조 가능성**을 남긴다.

실제로 이번에 그 대조를 전수로 해 봤다 (§11).

## 11. Corpus 결과 (등록된 16개 전수)

| 분류 | 수 | 확인 |
|---|---|---|
| **A** 조건이 진짜 없다 (`activation=None` + 원문에 `SetCondition` 없음) | **8** (실행 가능 5 · 실행 불가 3) | `test_07` — 어긋남 0 |
| **B** 조건이 명시되어 있다 (`activation` 있음) | 8 (`ZoneCountAtLeast` 7 · `And` 1) | |
| **C** 사건 의존 조건 | **0** | 등록된 것 전부 `EVENT_FREE_CHAIN` (3-E-20) |
| **D** 미구현 조건(`UnimplementedRule`)으로 등록된 것 | **0** | 쓸 자리가 아직 없었다 |
| **E** parser 실패로 `None` 이 된 것 | **0 (구조적으로 불가)** | §10 |
| **F** `missing_rule` 로 등록된 것 | 0 | |
| **G** 데이터 없음으로 `None` 이 된 것 | 0 | |

원문에 `SetCondition` 이 있는 등록 카드는 **하나**(`c69091732` 의적의 입문서)이고,
그 조건이 `activation` 에 **정확히 옮겨져 있다** (`test_08`):

```
Lua   e1:SetCondition(s.condition)
      s.condition → Duel.GetFieldGroupCount(tp,0,LOCATION_HAND)>4
등록  activation.describe_ko() == "상대 HAND 에 5장 이상"
근거  lua_excerpt 에 그 Lua 한 줄이 들어 있다
```

→ **`lua_excerpt` 가 사실상 조건 대응의 감사 수단**이다. 기계적 관문은 없지만
**검증 가능성**은 설계에 박혀 있다.

## 12. Safety Invariant

| # | Invariant | 판정 | 근거 |
|---|---|---|---|
| 1 | "조건을 모른다" 를 TRUE 로 승격하지 않는다 | **조건부 PASS** | `UnimplementedRule`·`UNKNOWN` 은 승격되지 않는다 (`test_03`·`test_12`). 그러나 **`activation=None` 은 승격된다** — 기제가 보장하지 않는다. 현재 corpus 에서 위반 사례는 **0건** (`test_07`) |
| 2 | "규칙 미구현" 을 FALSE 로 승격하지 않는다 | **PASS** | `UNKNOWN` 이지 `INVALID` 가 아니다 (`test_12`) |
| 3 | "parser 가 못 읽었다" 를 "조건 없음" 으로 간주하지 않는다 | **PASS (구조적으로 불가)** | parser→Condition 변환 경로가 없다 (`test_09`) |
| 4 | registration 성공 ≠ activation 성공 | **PASS** | `test_11` |
| 5 | dormant 라는 이유로 runtime path 를 삭제하지 않는다 | **PASS** | 아무것도 지우지 않았다 (production diff 0줄) |

## 13. 설계 비교 (§11)

| 설계 | 현재 | 평가 |
|---|---|---|
| **A STRICT GATE** (조건을 표현할 수 없으면 등록 거부) | 아니다 | **부적합 — 실측으로 확인했다.** 고의 위반 C 로 관문에 조건 검사를 넣자 **기존 라이브러리가 import 시점에 터졌다** (`activation=None` 인 8개 때문에). "조건이 진짜 없는 카드" 가 실재하므로 A 는 참을 거짓으로 만든다 |
| **B DORMANT REGISTRATION** (등록은 허용 · runtime 에서 UNKNOWN) | **이미 가능하다** | **가장 안전하다.** 코드 변경 없이 작동하고, `missing_rule` 로 추적까지 된다 |
| **C SILENT PASS** (조건을 표현할 수 없으면 없는 것으로) | **기본값이 이것이다** | 위험한 쪽이지만, **지금은 사람이 지키고 `lua_excerpt` 로 감사된다** |

→ **남기는 계약**: 사건 의존 조건을 가진 카드를 등록할 때는 `activation` 을
**비워 두지 말고 `UnimplementedRule("…")` 로 적는다.** 그러면 등록은 되고 발동은
`UNKNOWN` 으로 막히며 무엇이 없는지 이름이 남는다. 이 Phase 는 그것을 **강제하는
코드를 넣지 않았다** (구현 금지 범위).

## 14. Engine / AI 영향

| | 결과 |
|---|---|
| production diff | **0줄** (`engine/` · `agent/` · `core/` · `analysis/` · `sources/`) |
| engine validation | 변경 없음 |
| trigger execution | 변경 없음 (여전히 dormant) |
| `legal_actions` | 변경 없음 |
| Search · Evaluation | 변경 없음 |
| `GameStateView` | 변경 없음 |

## 15. Tests

신규 `tests/test_registration_gate_audit.py` — **12개**.

| # | 검증 |
|---|---|
| 01 | 관문이 막는 네 가지(실측 예외) · 조건은 막지 않는다 |
| 02 | 관문 본문에 `activation` 이라는 글자가 없다 |
| 03 | `UnimplementedRule` 은 등록되고 발동은 `UNKNOWN` + `missing_rule` |
| 04 | `None` 과 `Always()` 가 판정에서 구별되지 않는다 |
| 05 | 두 모듈의 설명이 같은 `None` 을 반대로 읽는다 |
| 06 | `all_of([])==TRUE` 는 정상이고 `UNKNOWN` 과는 구별된다 |
| 07 | 등록된 `activation=None` 전부가 원문에도 조건이 없다 (전수) |
| 08 | 원문에 조건이 있는 하나는 정확히 옮겨져 있고 `lua_excerpt` 가 근거다 |
| 09 | library 가 parser/analysis 를 import 하지 않는다 |
| 10 | 🟡 `_check_condition` 의 UNKNOWN 코드가 하나로 묶여 있다 |
| 11 | registration ≠ activation (Invariant 4) |
| 12 | 미구현을 거짓으로도 접지 않는다 (Invariant 2) |

고의 위반 5건 — **전부 잡혔다**:

| | 위반 | 잡은 테스트 |
|---|---|---|
| A | `_check_condition` 이 `UnimplementedRule` 을 통과시킨다 | 03 · 11 · 12 |
| B | 미구현을 거짓으로 접는다(`is not FALSE` 통과) | 03 · 11 · 12 |
| C | 관문에 조건 검사를 넣는다 (설계 A) | **라이브러리가 import 시점에 터졌다** — 설계 A 가 부적합하다는 실측 증거 |
| D | library 가 `analysis` 를 import 한다 | 09 |
| E | `executable=False` 의 `note` 강제를 뺀다 | 01 · 02 |

전체: **3642 passed · 4 skipped · 0 failed · 378s.**
Regression **0** · 신규 12 · 수정 **0** · 삭제 **0** · skip 증가 **0**.

## 16. 신규 STRUCTURAL

**신규 STRUCTURAL 없음.**

§15 의 다섯 조건으로 따진 결과 (대상: "`activation=None` 이 두 뜻을 갖는다"):

| 조건 | 충족 | 근거 |
|---|---|---|
| 1. 기존 구조로 표현할 수 없다 | **아니다** | `UnimplementedRule` 이 바로 그 표현이고 지금 작동한다 (`test_03`) |
| 2. registration semantics 가 구조적으로 손실된다 | **아니다** | 손실은 "적지 않았을 때" 만 일어나고, 적을 수단이 있다 |
| 3. Trigger 연결 전에 반드시 해결해야 한다 | 그렇다 | 사건 의존 조건이 들어오는 순간 A 경로가 위험해진다 |
| 4. 단순 parser bug 가 아니다 | 그렇다 | |
| 5. 단순 missing rule 구현이 아니다 | 그렇다 | |

→ 조건 1·2 불성립 → **감사 소견 + 등록 계약**으로 남긴다 (🟠 성격, ID 없음).

함께 기록하는 🟡 하나: `EffectActivator._check_condition` 의 `UNKNOWN` 분기가
"정보 없음" 과 "규칙 없음" 을 같은 `INFORMATION_UNAVAILABLE` 로 적는다
(`ActionValidator._check_requirements` 는 가른다). `missing` 에 이름이 남으므로
**정보는 잃지 않는다** — 코드만 덜 정확하다. 3-E-24 의 발견 ①과 같은 모양이고,
그것과 함께 고치는 것이 자연스럽다.

## 17. 기존 TODO

| ID | 상태 |
|---|---|
| STRUCTURAL-31 / -32 / -33 | 유지 |
| STRUCTURAL-34 / -124 / -128 / -131 / -133 | 유지 — unaffected |
| STRUCTURAL-134 · SET_ACTIVATION_MISSING | RESOLVED 유지 |
| SET_ACTIVATION_TIMING · SET_ACTIVATION_EXECUTION · SET_CARD_EFFECT_EXECUTION | 유지 |
| AFTER_CHAIN_RULE · UNRESOLVED_PROGRESSION_RULES · UNRESOLVED_ORDER_RULES | 유지 |
| 🟡 `_check_condition` 의 UNKNOWN 코드 통합 · 🟠 `activation=None` 의 두 뜻 | **새로 기록** (ID 없음) |

## 18. 최종 판정

**B. AUDIT-ONLY / FUTURE ARCHITECTURE GAP.**

`C`(STRUCTURAL ISSUE)가 아닌 이유: "조건 없음 / 미구현 / parser 실패" 가
registration 단계에서 **구조적으로 구분 불가능하지 않다.** parser 실패는 경로가
없어 애초에 생길 수 없고(§10), 미구현은 `UnimplementedRule` 로 적을 수 있으며
그것이 발동을 `UNKNOWN` 으로 막는다(§7). 남은 것은 **"적지 않았을 때의 기본값이
통과" 라는 한 가지**이고, 현재 등록 corpus 에서 위반 사례는 0건이다.

`D`(BLOCKER)도 아니다 — 지금 잘못 만들어지는 행위가 없다.

## 19. 다음 Phase 후보 — 정확히 하나

> **`UNKNOWN` 코드 정합성의 **최소 수정** Phase (감사 아님).**
>
> 3-E-24 와 3-E-25 가 같은 모양의 흠집을 **세 군데**에서 각각 측정했다.
>
> 1. `TriggerCollector._judge` — 조건이 **거짓**인데 `code=RULE_NOT_IMPLEMENTED`
>    (쓸 코드: `CANDIDATE_NOT_ELIGIBLE`)
> 2. `TriggerCollector._judge` — **금지**인데 `code=RULE_NOT_IMPLEMENTED`
>    (쓸 코드: `EXECUTION_FORBIDDEN`, 그리고 `GateVerdict.forbids` 가 바로 그
>    코드로 금지를 알아본다 — 지금은 서로 못 알아본다)
> 3. `EffectActivator._check_condition` — "규칙 없음" 과 "정보 없음" 을 같은
>    `INFORMATION_UNAVAILABLE` 로 적는다 (`ActionValidator` 는 가른다)
>
> 세 자리 모두 **`validity` 와 `missing_rule` 은 정확하고 `code` 만 덜 정확하다.**
> 그래서 고치는 일은 **값 하나씩 바꾸는 것**이고, 새 enum·새 구조·새 subsystem 이
> 필요 없다. 감사가 이미 끝났으므로 다음은 **그 세 줄을 고치고 회귀를 확인하는
> 최소 구현 Phase** 가 자연스럽다 — 더 감사할 것이 남아서가 아니라, **측정된
> 흠집을 더 쌓지 않기 위해서**다.
>
> (그 Phase 에서 함께 결정할 것 하나: `GateVerdict.forbids` 가 코드로 금지를
> 알아보는 구조를 유지할지, 아니면 `TriggerStatus.FORBIDDEN` 을 직접 볼지.)

다음 Phase 는 지시 없이 진행하지 않는다.
