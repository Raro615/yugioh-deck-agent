# Phase 2-S — Activation Timing / Spell Speed Core

기준 커밋: `317e066` (Phase 2-R Chain Response / Priority Loop)

```
ResponseLoop.act(state, response, action)
    ├ 1. 우선권      PriorityResolver.may_act        (2-F-1)
    ├ 2. 스펠 스피드  ActivationTimingChecker.check   ← **이번 단계**
    └ 3. 발동        EffectActivator.activate        (2-Q)
                     ↳ authorization 은 **여전히 밖에서** 온다
```

이 단계가 만든 것은 **관문 하나**다. 완전한 OCG 타이밍 규칙이 아니라,
"타이밍 판정이 어디에 있어야 하고 무엇을 답해야 하는가" 를 구조에 앉힌다.

---

## 1. 변경 파일

| 파일 | 변경 |
|---|---|
| `engine/activation_timing.py` | **신규** — `SpellSpeed` · `SpellSpeedClassification` · `ActivationTiming` · `ActivationTimingChecker` |
| `engine/validation.py` | `ValidationCode.SPELL_SPEED_TOO_LOW` **1개** 추가 |
| `engine/response.py` | 타이밍 관문 연결 · `ResponseResult.timing` 칸 · `check_timing()` |
| `tests/engine/test_activation_timing.py` | 신규 — 41개(실행 46건) |
| `tests/engine/test_chain_response.py` | **픽스처 수정** (§17) |
| `docs/phase2s-activation-timing.md` | 신규 |
| `engine/__init__.py` | Phase 2-S 항목 |

---

## 2. 조사 — 스펠 스피드 표는 **이미 저장소에 있었다**

`data/rules/structured/sd-rulebook-en-v10.json` 의 `chain.spell_speeds` 가
공식 룰북에서 구조화된 표를 들고 있었다 (Phase 1-E). `RULE-CHAIN-003` ~
`006` 까지 근거 번호도 붙어 있다.

**그래서 규칙을 하나도 지어내지 않았다.** 엔진에는 그 표의 손으로 옮긴
사본이 있고, 원본과 어긋나면 테스트가 깨진다 —
`engine/effect/library.py` 가 Lua 원문을 근거로 들고 다니는 것과 같은 자리다.

`engine` 은 `rules` 를 import 하지 않는다 (실행 계층이 데이터 파일에 묶이지
않게). **대조는 테스트가 한다.**

| 필요했던 것 | 이미 있던 것 |
|---|---|
| 카드 종류 | `CardDefinitionView.type_names` — 새 필드 0개 |
| 차례 판정 | `PriorityResolver.may_act` (2-F-1) |
| 체인 | `Chain` · `ChainLink` (2-F-2) |
| 시점 이름 | `TimingPoint` (2-F-3-A) |
| 판정 어휘 | `ValidationResult` — 새 타입 0개 |

---

## 3. Timing 구조

`ActivationTiming(chain, priority, point=None)` — **세 값을 참조로만** 담는다.
페이즈·턴 플레이어는 관측이 이미 들고 있으므로 여기 없다 (§4 의 "중복 저장
금지"). 테스트가 `__dataclass_fields__` 로 그것을 고정한다.

`ActivationTimingChecker(view)` 는 관측만 들고 있어 **바꿀 수 있는 것이
없다** (`GameState` 를 주면 `TypeError`).

---

## 4. Spell Speed

```python
class SpellSpeed(int, Enum):
    NORMAL = 1     # 일반·장착·지속·필드·의식 마법, 기동·유발·플립 효과
    FAST = 2       # 일반·지속 함정, 속공 마법, 유발즉시(퀵) 효과
    COUNTER = 3    # 카운터 함정
```

**`UNKNOWN` 멤버를 두지 않았다.** 두면 `speed >= other` 같은 비교에 조용히
섞인다. 모른다는 것은 `SpellSpeedClassification(speed=None, missing=...)` 이
말하고, 그 dataclass 는 "speed 가 없는데 missing 도 없다" 를 거부한다.

응수 가능 여부는 **숫자 비교가 아니라 표**다.

| 속도 | 응수할 수 있는 상대 |
|---|---|
| 1 | **없음** |
| 2 | 1 · 2 |
| 3 | 1 · 2 · 3 |

`>=` 로 대신하면 "1 이 1 에 응수할 수 있다" 가 되어 버린다 — 스펠 스피드 1
이 아무것에도 응수할 수 없다는 것은 비교식이 아니라 별도의 규칙이다
(RULE-CHAIN-004).

### 분류는 카드 종류에서 온다

| 종류 | 속도 |
|---|---|
| `TRAP` + `COUNTER` | 3 |
| `TRAP` | 2 |
| `SPELL` + `QUICKPLAY` | 2 |
| `SPELL` | 1 |
| `MONSTER` | **모른다** |
| 관측에 없음 / 뒷면 | **모른다** (서로 다른 `missing`) |

**몬스터를 추측하지 않는다.** 기동 효과면 1, 유발즉시면 2 인데 그 분류
(`EFFECT_TYPE_QUICK_O`)를 읽는 계층이 이 엔진에 없다. 1 로 만들면 퀵
이펙트가 영영 응수하지 못하고, 2 로 만들면 기동 효과가 상대 턴에 발동한다.

---

## 5. Activation legality — 책임 분리 (§5)

| 책임 | 어디서 | 결과 |
|---|---|---|
| A. Action authorization | 밖에서 오는 `authorization` (2-Q) | `UNAUTHORIZED` |
| B. 구현 가용성 | `EffectActivator` (2-Q) | `FORBIDDEN` · `NOT_IMPLEMENTED` |
| C. 비용 | `EffectActivator` → `CostPayer` (2-E) | `COST_UNPAYABLE` · `COST_UNKNOWN` |
| D. 대상 | `EffectActivator` → `TargetResolver` (2-N) | `INVALID_TARGET` · `UNCHECKED_TARGET` |
| E. 우선권 | `ResponseLoop` → `PriorityResolver` (2-F-1) | `NOT_PRIORITY_HOLDER` |
| **F. 스펠 스피드** | **`ActivationTimingChecker` (2-S)** | `SPELL_SPEED_TOO_LOW` |

여섯이 **각자 다른 객체**에 있다. 하나의 거대한 if/elif 가 아니다.

### 새 코드는 **하나뿐**이다

`ValidationCode.SPELL_SPEED_TOO_LOW`. 나머지는 기존 코드를 그대로 쓴다.

- 몬스터라 분류를 모른다 → `RULE_NOT_IMPLEMENTED` + `missing_rule`
- 뒷면이라 정체를 모른다 → `INFORMATION_UNAVAILABLE` + `missing_rule`

**모르는 것에 `SPELL_SPEED_TOO_LOW` 를 쓰지 않는다** — 위반과 미상은 다른
사실이고, 정보가 생기면 답이 달라진다.

### `VALID` 는 "발동해도 된다" 가 아니다

통과한 결과의 `notes` 에 `UNRESOLVED_TIMING_RULES` 가 실려 나간다: 페이즈
제약 · 세트 턴 함정 · 턴 1회 · 타이밍 놓침 · 체인 블록 · 데미지 스텝 ·
카드별 예외. 관문은 **좁히기만 하고 넓히지 않는다** — `check_timing` 이
`VALID` 여도 `authorization` 없이는 발동되지 않는 것을 테스트가 확인한다.

---

## 6. Response 연결 (§7)

`ResponseLoop._activate` 가 **발동 계층을 부르기 전에** 관문을 지난다.
위반이면 비용도 치르지 않고 `EffectActivator` 를 부르지도 않는다.

`ResponseResult.timing` 칸이 생겨서 **어느 관문이 막았는지** 읽힌다.

| `timing` | `activation` | 뜻 |
|---|---|---|
| `None` | `None` | 우선권에서 멈췄다 (또는 PASS) |
| 있음 | `None` | **스펠 스피드에서** 멈췄다 |
| 있음 | 있음 | 타이밍은 통과, 발동에서 멈췄거나 성공 |

`ResponseLoop` 는 여전히 `EffectExecutor` 를 부르지 않고 (`execute` 라는
이름이 파일에 없다), 해결은 `ChainResolver.resolve_all` 에 넘긴다.

---

## 7. Priority

`PriorityResolver.may_act` 그대로. **타이밍 판정이 우선권을 다시 묻지
않는다** — 두 벌이 갈린다. 차례가 아니면 타이밍 관문까지 가지도 않는다
(`result.timing is None` 으로 확인).

새 우선권 시스템 없음 (AST 확인).

---

## 8. Trigger vs Response

여전히 별개다.

- `engine/activation_timing.py` 는 `TriggerCollector` ·
  `TriggerChainIntegrator` · `TriggerOrderer` 를 쓰지 않는다. `TimingPoint`
  는 **시점의 이름**으로만 쓴다.
- `engine/trigger*.py` 는 `engine.activation_timing` 을 import 하지 않는다.

---

## 9. §9 시나리오 A~G

| | 상황 | 결과 |
|---|---|---|
| A | 체인 없음 → 일반 마법 | `VALID` (응수가 아니므로 제약 없음) |
| B | 속공 마법 → 속공 마법 | `VALID` |
| C | 일반 마법 → 속공 마법 | `INVALID` / `SPELL_SPEED_TOO_LOW` |
| D | 카운터 함정 → 카운터 함정 | `VALID` · 속공 마법 → 카운터 함정은 `INVALID` |
| E | 차례가 아닌 사람 | `NOT_PRIORITY_HOLDER` (타이밍까지 가지 않음) |
| F | 응수할 링크가 **뒷면** | `UNKNOWN` / `INFORMATION_UNAVAILABLE` |
| G | 몬스터 효과로 응수 | `UNKNOWN` / `RULE_NOT_IMPLEMENTED` |

**F · G 를 `INVALID` 로 접지 않는다.** `UNKNOWN` 은 허가도 금지도 아니고,
`ResponseLoop` 는 그것으로 체인을 늘리지 않는다.

---

## 10. 실제 카드 (§12)

| 카드 | 종류 | 속도 | 비고 |
|---|---|---|---|
| 싸이크론 (5318639) | `SPELL` / `QUICKPLAY` | **2** | LUA_VERIFIED · executable |
| 욕망의 항아리 (55144522) | `SPELL` | **1** | LUA_VERIFIED · executable |
| 신의 심판 (41420027) | `TRAP` / `COUNTER` | **3** | 라이브러리에 없다 — **분류에만** 썼다 |
| 거울의 힘 (44095762) | `TRAP` | **2** | 분류 · 뒷면 시험용 |
| 페더맨 (21844576) | `MONSTER` | **미상** | 추측하지 않았다 |

카드 종류는 공식 DB 에서 읽었다. 확정할 수 없는 것(몬스터 효과 분류)은
`UNKNOWN` 으로 남겼다.

---

## 11. Failure matrix — 전부 체인 · 판 불변

| 상황 | code | 관문 |
|---|---|---|
| 차례가 아님 | `NOT_PRIORITY_HOLDER` | 우선권 |
| 스펠 스피드 위반 | `SPELL_SPEED_TOO_LOW` | 타이밍 |
| 스펠 스피드 미상 (몬스터) | `RULE_NOT_IMPLEMENTED` | 타이밍 |
| 응수 대상 미상 (뒷면) | `INFORMATION_UNAVAILABLE` | 타이밍 |
| 허가 없음 | 검증기의 코드 | 발동 |
| 대상 없음 | `TOO_FEW_SELECTED` | 발동 |

전부 `link is None` · `len(chain) == 1` · `chain is` 들어온 그대로 ·
`state_hash` 불변.

---

## 12. Determinism · 13. Hidden information

같은 입력 → 같은 `ValidationResult.canonical_state()` (미상 판정도 포함).
복제본에서도 같고, 판정을 몇 번 불러도 `state_hash` 가 그대로다.

상대의 뒷면 카드를 두고 내린 판정 결과와 분류 결과 어디에도 그 카드의
`card_id` 나 이름이 없다. 관측은 **행위자의 시점**으로만 만든다.

---

## 14. 기존 테스트 수정 (§17 의 정직한 보고)

`tests/engine/test_chain_response.py` 의 **픽스처**를 고쳤다. 테스트를
삭제하거나 약화하지 않았고, 단언은 그대로다.

**무엇이 틀렸었는가**: Phase 2-R 의 시나리오는 **몬스터 카드로 체인에
응수**하고 있었고, 체인 링크에 `source` 도 없었다. 스펠 스피드 관문이
생기자 그 시나리오는 "응수할 수 있는지 판정할 수 없음" 이 되었다 — 관문이
잘못된 것이 아니라 **픽스처가 성립하지 않는 상황을 그리고 있었다.**

| 고친 것 | 왜 |
|---|---|
| 발동하는 카드를 앞면 **속공 마법**으로 | 응수할 수 있는 종류여야 시나리오가 성립한다 |
| 체인 링크에 `source` 추가 | 발동한 카드를 모르면 그 링크의 속도를 알 수 없다 |
| `viewer` AST 검사 일반화 | `seat` 과 `action.actor` 둘 다 **결정하는 자리**다 |

Phase 2-R 의 43건은 전부 그대로 통과한다.

---

## 15. 남은 것 (기록만)

- **STRUCTURAL-58 (부분 해결)** — 스펠 스피드 관문은 생겼다. 그러나 페이즈
  제약 · 세트 턴 함정 · 턴 1회 · 타이밍 놓침 · 체인 블록 · 데미지 스텝은
  여전히 밖에서 오는 허가에 기댄다. **범위를 넓히지 않았다** (§17).
- **STRUCTURAL-59 (신규)** — 몬스터 효과의 스펠 스피드를 정할 수 없다.
  `EFFECT_TYPE_QUICK_O` 를 읽어 유발즉시를 가려내는 계층이 필요하다.
  그때까지 몬스터 효과로는 체인에 응수할 수 없다 — 금지가 아니라 **미상**이다.
- **STRUCTURAL-60 (신규)** — 링크의 스펠 스피드를 **지금의 관측**에서 읽는다.
  발동 시점의 속도를 링크가 들고 있지 않으므로, 발동한 카드가 필드를 떠나거나
  뒷면이 되면 그 링크의 속도를 더 이상 알 수 없다. `ChainLink` 가 발동 시점의
  분류를 들고 가야 풀린다 (STRUCTURAL-51 과 같은 뿌리).
- 15 · 34 · 45 · 46 · 48 ~ 57 — 변동 없음.

---

## 16. 테스트

`tests/engine/test_activation_timing.py` — 함수 **41개**, 실행 **46건**
(B · G 묶음에 `parametrize`). 전부 통과.

| 묶음 | 함수 | 보는 것 |
|---|---|---|
| A. 규칙의 출처 | 5 | 엔진 사본이 룰북과 일치 · `UNKNOWN` 멤버 없음 |
| B. 분류 | 6 | 실제 카드 4종 · 몬스터 미상 · 뒷면 · 정보 경계 |
| C. 시나리오 A~G | 7 | §9 의 일곱 경우 |
| D. `VALID` 의 뜻 | 5 | 좁히기만 한다 · 보지 않은 규칙을 들고 나간다 |
| E. ResponseLoop 연결 | 6 | 두 관문이 구분된다 · `UNKNOWN` 은 허가가 아니다 |
| F. 경계 | 5 | 트리거와 별개 · 중복 시스템 없음 · 중복 저장 없음 |
| G. 실패 · 결정론 · 정보 | 7 | 판 불변 · 같은 답 · 정체 유출 없음 |

전체 회귀: **2124 passed, 4 skipped** (직전 2078 + 46).
