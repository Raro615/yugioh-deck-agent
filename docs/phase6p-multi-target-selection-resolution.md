# Phase 6-P — 다중 대상 선택 및 효과 해결 경로 검증

작성: 2026-10-16 · 브랜치 `claude/pensive-goodall-te1egy` · 기준 `ee50d4f` (Phase 6-O)

---

## 0. 한 줄 요약

🔴 **다중 대상은 실제 BLOCKER 였고, 막고 있던 것은 대상 모델이 아니라 열거
한 줄이었다.** 복수 선택을 표현하는 모델 · 장수 검증 · 중복 검증 · 환전 ·
실행기는 **전부 이미 있었고**, `target_combinations` 가 "한 장짜리"만
열거했다. 그 한 줄을 **정확히 N장**으로 넓혔더니 벌금(92595643)이 조합
10개를 얻고 실제로 해결되었다 — 패 5 → 3, 묘지 0 → 3.

그러나 **`legal_actions` 에는 여전히 오르지 않는다.** 벌금은 함정이고
함정은 `TRAP_TRIGGER_MISSING` (Phase 3-E-16) 때문에 `ActionValidator` 에서
`UNKNOWN` 이다. 이 Phase 는 그 관문을 열지 않았고, 그래서 **수준 3 을
달성했다고 쓰지 않는다** (§19).

---

## 1. 기존 대상 선택 구조와 지원 범위 (§4-A)

### 1-1. 모델은 이미 복수 선택을 표현했다

| 질문 (§4-A) | 답 | 어디에 |
|---|---|---|
| 1. 여러 장의 선택을 표현할 수 있는가 | 🟢 **있었다** | `ChoiceSpec.minimum` / `maximum` |
| 2. 최소·최대 선택 수 | 🟢 **있었다** | 같음 (`is_exact` · `is_optional` 까지) |
| 3. 정확히 N · 최대 N · 1 이상 구분 | 🟢 **표현 가능** | `minimum == maximum` / `minimum=0` / `minimum<maximum` |
| 4. 서로 다른 종류의 대상을 동시에 | 🟢 **표현 가능** | `EffectDefinition.targets` 가 튜플 (`TargetBinding` 여럿) |
| 5. 같은 카드 중복 방지 | 🟢 **있었다** | `ChoiceSpec.allow_duplicates` + `Selection.has_duplicates` + `TargetResolver._check_count` 의 `DUPLICATE_SELECTION` |
| 6. 자기 자신 포함·제외 | 🟢 **있었다** | `CandidateSource.exclude_source`, 그리고 6-L 의 `SELF_TARGET` |
| 7. 후보 개수를 어디서 검증하는가 | 🟢 **있었다** | `TargetResolver.candidates` → `CandidateSet` (`eligible` · `undecided` · `unchecked`) |

🔴 **즉 §19 수준 1 의 "지원 범위" 는 "모델이 모자랐다" 가 아니다.** 모자란
것은 **그 모델을 후보 목록으로 펼치는 절차** 하나였다.

### 1-2. 실측 — 등재된 효과의 선택 수 분포

```
정의 17개 / 대상 바인딩 9개
    5318639 @primary   targeting ChoiceSpec          min=1 max=1  (싸이크론)
   15103313 @primary   targeting ChoiceSpec          min=1 max=1  (자기 미라화)
   92595643 @primary   choosing  ChoiceSpec          min=2 max=2  <<< 🔴 다중
   94192409 @primary   targeting ChoiceSpec          min=1 max=1  (강제 탈출 장치)
   81439173 @primary   choosing  ChoiceSpec          min=1 max=1  (어리석은 매장)
   73148972 @primary   targeting ChoiceSpec          min=1 max=1  (무정한 말살)
   73148972 @random    random    RandomSelectionSpec  —           (무정한 말살)
   69091732 @random    random    RandomSelectionSpec  —           (의적의 입문서)
   22589918 @primary   all       AllMatchingSpec      —           (리로드)
```

| 범주 (§6) | 등재 건수 |
|---|---|
| 정확히 1장 | 5 |
| **정확히 N장 (N>1)** | **1 — 벌금뿐** |
| 최대 N장 (최소≠최대) | **0** |
| 선택하지 않을 수 있다 (`minimum=0`) | **0** |
| 중복 허용 | **0** |
| 고르는 자리가 2개 이상 | **0** |

🔴 **이 수가 이 Phase 의 범위를 정했다.** "모든 범주를 한꺼번에 구현하지
않는다" (§6) 를 지킬 수 있었던 것은 **실제로 필요한 범주가 하나**임을
세었기 때문이다.

### 1-3. 발동 시 대상 지정 경로 (§4-B)

```
PlayerAction(targets=(ActionTarget.instance(#41), ActionTarget.instance(#42)))
      ↓  selections_for(definition, action)        ← 순서 → 이름 환전
(TargetSelection(@primary, Selection((#41, #42))),)
      ↓  EffectActivator.activate(selections=...)
ChainLink(selections=...)                          ← 🟢 보존된다 (test_h04)
      ↓  ChainResolver → EffectExecutor
GameState 변경 + EventJournal
```

| 질문 | 답 |
|---|---|
| 1. 언제 지정하는가 | 발동 절차에서. `PlayerAction.targets` 로 들어온다 |
| 2. 인스턴스 ID 가 전달되는가 | 🟢 `ActionTargetKind.INSTANCE` 만 받는다 |
| 3. 체인 링크에 보존되는가 | 🟢 `ChainLink.selections` (`test_h04` 가 두 장 다 확인) |
| 4. 비용 전후 유효성 | ⚪ **검증되지 않음** — 등재된 17개 효과 전부 비용이 없고, `Duel._activation_actions` 가 `definition.cost.costs` 가 있으면 후보에서 **제외**한다 (ADR-008: 비용을 치른 뒤 깨지면 되돌릴 수 없다). 그래서 비용↔대상 순서는 이번에도 **잴 수 없었다** |
| 5. 무효가 됐을 때 | ⚪ 체인 무효화 자체가 아직 없다 (이 Phase 의 범위 밖) |

### 1-4. 해결 계층 (§4-C)

| 질문 | 답 (실측) |
|---|---|
| 1. 여러 대상을 받는가 | 🟢 **받았다** — `Selection.chosen` 이 튜플이다 |
| 2. 해결 시 남아 있는지 검사하는가 | 🟢 `TargetResolver.validate` 를 실행 직전에 다시 본다 (`test_i01`) |
| 3. 부분 해결 | 🔴 **하지 않는다** — 한 장이 자리를 벗어나면 효과 전체가 적용되지 않는다 (`test_i02` 가 그 행동을 못 박았다) |
| 4. 전원 필수 vs 일부 가능 구분 | ⚪ **구분하는 축이 없다**. 지금은 전부 "전원 필수" 처럼 행동한다 |
| 5. 여러 카드에 연산 적용 | 🟢 **된다** — 한 `AppliedOperation` 에 `instances` 둘, `ZoneMoved` 둘 (`test_a05` · `test_h03`) |
| 6. 여러 Delta 가 실패하면 | 계획이 **전부 읽기 전용**으로 끝난 뒤에 `_apply` 한다 (ADR-008). 그래서 "일부 적용 후 실패" 가 생기지 않는다 |
| 7. 순차 · 동시 구분 | ⚪ **축이 없다.** 그래서 임의의 순차 실행으로 대체하지 않았다 (§9) |

### 1-5. Lua 및 분석 데이터 (§4-D)

분석 계층에는 `EffectSelection.min_count` / `max_count` 가 **있다.** 그리고
**신뢰할 수 없다.** 코퍼스 전수 실측:

```
스크립트 있는 카드 12,968장 / 효과 블록 26,933개 / 선택 명세 12,233개

min=0     max=1       7,610건   ← 🔴 선택 수가 아니다
min=None  max=None    4,159건   ← 수를 읽지 못했다
min=1     max=1         247건
min=0     max=2         128건
…
min=1     max=120         1건   ← 🔴
min=87526784 max=23915499 1건   ← 🔴 패스코드를 장수로 읽었다
```

원인을 하나씩 열어서 확인했다.

| 행 | 원본 Lua | 왜 틀렸나 |
|---|---|---|
| `min=0,max=1` (7,610건) | `Duel.IsExistingTarget(s.filter,tp,LOCATION_GRAVE,0,1,nil,e,tp)` | **존재 검사**이고 선택이 아니다. 위치 인자 `s=0`·`o=1` 을 `min`·`max` 로 읽었다 |
| `min=87526784,max=23915499` | `Duel.GetMatchingGroup(s.spfilter,tp,...,nil,87526784,23915499,50319138)` | 추가 필터 인자로 넘긴 **카드 패스코드**를 장수로 읽었다 |
| `min=1,max=120` | `Duel.SelectTarget(tp,s.filter,tp,LOCATION_GRAVE,LOCATION_GRAVE,1,120,nil)` | 인자 수가 달라 자리가 밀렸다 |

🔴 **그래서 §4-D-5 의 답은 명확하다 — 분석 데이터로 선택 수를 확정할 수
없다.** 이것이 효과 라이브러리를 **손으로 적는** 이유(ADR-006)를 다시
증명한다. 6-P 는 분석 계층의 수를 **한 번도 읽지 않았고**, 벌금의 장수는
공식 텍스트와 공식 Lua 에서 왔다 (§7).

🟡 위 세 줄은 분석 계층의 결함이지만 **이번 범위가 아니다** (§16: 관련 없는
구조적 TODO 를 수정하지 않는다). 수치만 남긴다.

---

## 2. 실제 다중 대상 차단 사례 (§5)

### 2-1. 사례 — 벌금 (92595643, 함정)

§5 의 일곱 조건을 하나씩 **측정해서** 확인했다.

| # | 조건 | 판정 | 근거 |
|---|---|---|---|
| 1 | 공식 텍스트가 존재한다 | 🟢 | `cards.cdb` `desc` = **"자신은 패를 2장 버린다."** / `desc_en` = "Discard 2 cards." |
| 2 | 복수 카드 선택을 요구한다 | 🟢 | `Duel.DiscardHand(p,nil,2,2,REASON_EFFECT|REASON_DISCARD)` → `minimum = maximum = 2` |
| 3 | 기존 엔진이 일부를 지원한다 | 🟢 | 손으로 2장을 지정하면 `can_activate` 가 **VALID** 이고 해결까지 갔다 |
| 4 | 다중 대상 때문에 실행이 중단된다 | 🟢 | `target_combinations` = **0개** → `legal_actions` 에 FINE 발동 **0건** |
| 5 | 기존 대상 모델을 재사용할 수 있다 | 🟢 | `ChoiceSpec(2,2)` · `selections_for` · `_check_count` 전부 그대로 |
| 6 | 선택 수와 조건을 확인할 수 있다 | 🟢 | 공식 텍스트 + 공식 Lua 둘이 같은 수를 말한다 |
| 7 | 수정 후 GameState 변화를 검증할 수 있다 | 🟢 | 패 −2, 묘지 +3 |

🔴 **일곱 조건을 모두 만족하므로 "다중 대상이 실제 BLOCKER" 라는 가정을
철회하지 않았다.** (§5 는 만족하는 사례가 없으면 철회하라고 했다.)

### 2-2. 수정 **전** 실측

```
required_target_count(벌금)            = 2
target_combinations(…)                 = 0개      🔴 ← 여기서 끊긴다
legal_actions 총 11개 / FINE 발동      = 0개
─── 그런데 손으로 2장을 넣으면 ───
selections_for  → [('@primary', [41, 42])]
can_activate    → valid
resolve_all     → resolved=True
GameState       → HAND 5 → 3 · GRAVE 0 → 3
```

**발동도 해결도 막고 있지 않았다.** 막고 있던 것은 후보 열거 하나다.

---

## 3. 근본 원인과 기존 기능 재사용 가능성 (§18-3)

원인은 `engine/target_bridge.py` 의 **세 줄**이었다.

```python
if len(bindings) > 1:          # pragma: no cover - 목록에 아직 없다
    return []
binding = bindings[0]
choice = binding.spec.choice
if choice is None or choice.minimum != 1 or choice.maximum != 1:
    return []
```

그 자리의 주석이 이유를 정확히 적고 있었다 — *"둘 이상이거나 N장이면 조합
폭발과 순서 규칙을 함께 정해야 하고, 그 규칙이 아직 없으므로 추측하지
않는다"*. 6-P 가 한 일은 **그 두 규칙을 정한 것**이다 (§5-1 의 순서, §5-2 의
상한).

재사용한 것 / 새로 만든 것:

| | |
|---|---|
| 재사용 | `TargetResolver.candidates` · `TargetResolver.validate` · `_check_count` · `CandidateSet` · `Selection` · `ChoiceSpec` · `selections_for` · `targets_from` · `EffectExecutor` · `EventJournal` |
| 새로 만든 것 | `itertools.combinations` 호출 **한 줄**, 미지원 사유 **str 상수 4개**, 판정 함수 `unsupported_enumeration` **하나**, 상한 상수 **하나** |
| **새 데이터 타입** | 🟢 **0개** (`test_f02` 가 AST 로 센다 — 파일의 클래스는 여전히 `TargetBridgeError` 하나다) |

---

## 4. 대상 지정과 해결 시 선택의 구분 (§7 · §18-4)

| §7 범주 | 모델에 있는가 | 실행 경로가 가르는가 |
|---|---|---|
| A. 발동 시 지정한 대상 | 🟢 `TargetRequirement.TARGETING` | 🔴 **아니오** |
| B. 해결 시 고르는 카드 | 🟢 `TargetRequirement.CHOOSING` | 🔴 **아니오** |
| C. 자동으로 결정되는 카드 | 🟢 `ALL` (`AllMatchingSpec`) · `RANDOM` | 🟢 예 — 다리가 짝에서 **제외**한다 |
| D. 발동한 카드 자신 | 🟢 `SELF_TARGET` (6-L) | 🟢 예 — 고르는 자리가 아니다 |

🔴 **A 와 B 를 가르지 않았고, 가를 수 있다고 주장하지도 않는다.** 실측:
`TargetSpec.is_targeting` 을 읽는 프로덕션 자리는 **`engine/effect/target.py`
의 설명 문구 하나뿐**이다 (`test_f05` 가 `engine/` 전체를 AST 로 훑어
확인한다). 즉 다리와 활성화기는 TARGETING 과 CHOOSING 을 **같은 자리**에서
받는다.

그 둘을 가르려면 "발동 시 확정 → 해결 시 재확인" 과 "해결 중 선택" 이라는
**두 개의 서로 다른 해결 절차**가 필요하고, §9 가 새 체인 해결 시스템을
금지한다. 벌금은 `CHOOSING` 이므로 이 Phase 가 넓힌 것은 **그 기존 계약
안**이다.

`test_f05` 가 그 공백을 **못 박는다** — 누군가 가르기 시작하면 깨지고, 그때
§7 을 다시 읽게 된다.

---

## 5. 채택한 최소 구현 방식과 대안 (§10 · §18-5)

### 5-1. 채택 — §10 의 **B + C**

> B. `CandidateResolver` 의 복수 후보 반환 경로 활용
> C. `target_bridge` 에서 실제 선택한 인스턴스 목록 전달

```python
bindings = chosen_bindings(definition)
if not bindings:
    return [()]
shape = unsupported_enumeration(definition)      # 모양을 먼저 본다
if shape is not None:
    return []
take = choice.minimum                            # == maximum (보증됨)
…
pool = tuple(i for i in found.eligible if ordinary.find(i) is not None)
if unsupported_enumeration(definition, len(pool)) is not None:
    return []                                    # 🔴 자르지 않는다
return [targets_from(combo) for combo in itertools.combinations(pool, take)]
```

**순서 규칙**: `eligible` 은 관측 순서(`CandidateResolver` 가 존을 훑는
순서)이고 `itertools.combinations` 는 그 순서의 사전식이다. 그래서 같은
판이면 같은 목록이 나온다 (`test_b04` 가 3회 반복해서 확인).

**중복**: `combinations` 는 서로 다른 자리를 고르고 후보 목록에 같은
`InstanceId` 가 두 번 없으므로 **구조적으로** 중복이 생기지 않는다. 중복
검사를 따로 쓰지 않은 이유가 그것이다 (두 곳이 같은 규칙을 갖지 않는다).
그럼에도 `_check_count` 가 `DUPLICATE_SELECTION` 을 다시 보므로 관문은 둘이다.

### 5-2. 상한 — `MAX_TARGET_COMBINATIONS = 256`

🔴 **유희왕 규칙이 아니라 선언한 공학적 상한이다.** 규칙에 "조합이 몇
가지까지 적법한가" 라는 것은 없다. 두는 이유는 조합 수가 후보 수에 대해
지수적으로 늘기 때문이다 (덱에서 5장이면 `C(40,5) = 658,008`).

**넘으면 자르지 않고 열거를 포기한다.** 252개를 돌려주고 나머지를 버리면
"`legal_actions` 에 오른 것이 전부다" 가 거짓이 되고, 정책은 자기가 못 본
수가 있다는 사실조차 모른다. 포기하면 지금까지와 똑같이 빈 목록이므로
**없던 허가가 생기지 않는다** — 안전한 쪽으로 틀린다 (`test_e03`).

값의 근거: 등재된 유일한 다중 선택에서 실측 `C(5,2) = 10`, 룰북이 적은 패
상한 6장이면 `C(6,2) = 15` (`sd-rulebook-en-v10.json` 의 `zones`). 256 은
2장 선택을 패 23장까지 덮고 폭발하는 모양을 거부한다. 경계를 시험이 직접
센다 — `C(10,5) = 252` 는 열거하고 `C(11,5) = 462` 는 거부한다
(`test_e02` · `test_e03`).

### 5-3. 고르지 않은 대안

| 대안 | 왜 쓰지 않았나 |
|---|---|
| §10-A 새 선택 수 계약 | `ChoiceSpec` 이 이미 `minimum`/`maximum` 을 들고 있다. 새 계약이 필요 없다 |
| §10-D `ResolutionContext` 확장 | 선택은 이미 `ChainLink.selections` → `ResolutionContext` 로 전달된다 (`test_h04`) |
| §10-E 실행기 확장 | 실행기는 **처음부터** 여러 장을 받았다 (`test_a05`) |
| `SelectionCount` 를 `ChoiceSpec` 에 도입 | `SelectionCount` 는 **선언한 수**(2-AD)의 축이고 고를 장수가 아니다. 섞으면 "2장" 과 "2" 가 같은 칸에 들어간다 |
| 조합을 상한에서 **자르기** | §5-2 — `legal_actions` 의 완전성 주장이 거짓이 된다 |
| 가변 장수를 `minimum` 으로 열거 | 공식 근거 없이 "최대 2장" 의 최소값을 엔진이 정하는 일이다 (§6) |

---

## 6. 변경한 파일 및 함수 (§18-6)

| 종류 | 파일 | 증감 |
|---|---|---|
| **production** | `engine/target_bridge.py` | **+167 −12** |
| 테스트(신규) | `tests/engine/test_multi_target_selection.py` | 58개 |
| 테스트(수정) | `tests/engine/test_set_trap_timing_audit.py` | +28 −5 |
| 보고서 | `docs/phase6p-multi-target-selection-resolution.md` | 신규 |

🔴 **프로덕션은 한 파일이다.** `ChoiceSpec` · `TargetSpec` ·
`TargetResolver` · `EffectExecutor` · `PlayerAction` · `Duel` · `GameState` ·
효과 라이브러리 · 규칙 데이터는 **한 줄도 바뀌지 않았다.**

### 6-1. 함수별

| 함수 | 무엇을 했나 |
|---|---|
| `unsupported_enumeration` (신규) | 열거할 수 없는 모양이면 **이유의 이름**, 할 수 있으면 `None`. `pool_size` 를 주면 상한까지 본다 |
| `target_combinations` (수정) | "한 장" → **"정확히 N장"**. 거른 뒤의 후보로 `itertools.combinations` |
| `selections_for` (수정) | 가변 장수를 **거부**한다 (조용히 최소값으로 깎지 않는다) |
| `required_target_count` | 코드는 그대로. 거짓이 된 문서 문구를 고쳤다 (아래) |

### 6-2. 미지원 사유 이름 — `engine.effect.semantics` 의 `MISSING_*` 과 같은 모양

```python
UNSUPPORTED_MULTIPLE_BINDINGS   = "multiple-chosen-bindings (… 조합 순서 규칙 …)"
UNSUPPORTED_VARIABLE_COUNT      = "variable-selection-count (… 후보가 부족할 때 …)"
UNSUPPORTED_DUPLICATE_CHOICE    = "duplicate-selection (… 등재된 효과에 하나도 없다)"
UNSUPPORTED_COMBINATION_COUNT   = "combination-ceiling (… 자르지 않고 포기한다)"
```

🔴 **이것은 적법성 판정이 아니다.** "이 효과를 발동할 수 없다" 가 아니라
"이 다리가 후보를 열거할 줄 모른다" 다. 둘을 섞으면 "영원히 못 쓴다" 와
"지금 판에 후보가 없다" 가 구분되지 않는다 (`test_c02`).

### 6-3. 거짓이 된 문서 문구 하나

`required_target_count` 의 docstring 이 이렇게 적고 있었다.

> 지금 목록의 모든 효과가 `minimum == maximum == 1` 이지만, 그 사실에
> 기대지 않는다.

**벌금이 2/2 이므로 그 진술은 이미 거짓이었다.** 코드는 처음부터 합으로
적어 둔 덕분에 고칠 것이 없었고, **문구만** 고쳤다.

---

## 7. 공식 규칙 및 카드 효과 근거 (§5-1 · §6)

| 출처 | 내용 |
|---|---|
| `cards.cdb` `desc` | **"자신은 패를 2장 버린다."** |
| `cards.cdb` `desc_en` | "Discard 2 cards." |
| `c92595643.lua` | `Duel.SetTargetPlayer(tp); Duel.DiscardHand(p,nil,2,2,REASON_EFFECT|REASON_DISCARD)` |
| `sd-rulebook-en-v10.json` `zones` | 패 상한 6장 — §5-2 의 상한 근거 |

🔴 **"최대 2장" 이 아니라 "2장" 이다.** 그래서 `minimum == maximum` 이
옳고, 후보가 1장일 때 1장짜리 조합을 만들지 않는다 — 만들면 엔진이 공식
텍스트를 고쳐 쓴 셈이 된다 (`test_c01`).

🔴 **공식 사이트에 접속하지 않았다.** `scripts/fetch_ocg_rulings.py --all`
은 금지되어 있고 실행하지 않았다. 이 Phase 가 쓴 근거는 전부 **이미 저장소에
있는 것**이다.

---

## 8. 선택 수 검증 결과 (§18-7)

### 8-1. 열거 — `C(n, 2)` 를 따라간다

| 패의 후보 | 조합 수 (실측) | `C(n,2)` |
|---|---|---|
| 0 | 0 | 0 |
| 1 | 0 | 0 |
| 2 | 1 | 1 |
| 3 | 3 | 3 |
| 4 | 6 | 6 |
| **5** | **10** | **10** |
| 6 | 15 | 15 |
| 7 | 21 | 21 |

상수가 아니라 **이항계수**다 (`test_b02`). 전에는 전부 0이었다.

### 8-2. 검증 — 이미 있던 세 코드가 전부 잡는다

| 입력 | 판정 | 코드 |
|---|---|---|
| 2장 | `legal` | `ok` |
| 1장 | `illegal` | `too_few_selected` |
| 3장 | `illegal` | `too_many_selected` |
| 0장 | `illegal` | `too_few_selected` |
| 같은 것 2번 | `illegal` | `duplicate_selection` |
| 덱의 카드 | **`unknown`** | `hidden_card` |

🔴 **마지막 줄이 중요하다.** 관측에 없는 카드는 `ILLEGAL` 이 아니라
`UNKNOWN` 이다 — 없는 것과 가려진 것을 구분하지 못하므로 단정하지 않고,
`UNKNOWN` 을 허가로 바꾸지도 않는다 (`test_i03`).

### 8-3. 지원하지 않는 모양 — 이유의 이름을 댄다

| 모양 | 판정 |
|---|---|
| `min=1,max=2` · `0,2` · `0,1` · `2,3` | `UNSUPPORTED_VARIABLE_COUNT` |
| `min=max=0` | `UNSUPPORTED_VARIABLE_COUNT` (고를 것이 있다면서 0장은 모순) |
| 고르는 자리 2개 | `UNSUPPORTED_MULTIPLE_BINDINGS` |
| `allow_duplicates=True` | `UNSUPPORTED_DUPLICATE_CHOICE` |
| `C(11,5) = 462 > 256` | `UNSUPPORTED_COMBINATION_COUNT` |

전부 **빈 목록**이 되므로 후보가 되지 않는다 (`test_d05`).

---

## 9. 카드 인스턴스 식별과 중복 방지 (§8 · §18-8)

| §8 상황 | 결과 (실측) |
|---|---|
| 1. 같은 카드 ID 의 다른 인스턴스 | 🟢 후보 5장이 **전부 취옥의 비룡**인데 조합이 10개다. ID 로 묶었다면 1개였다 (`test_b05`) |
| 2. 자신과 상대의 같은 이름 카드 | 🟢 벌금은 `owner=CONTROLLER` 이므로 상대 패가 후보에 없다 (`test_j01`) |
| 3. 앞면 · 뒷면 | 🟢 세워 둔 벌금 자신은 `SZONE` 이고 후보 자리는 `HAND` 다 — 자리로 갈린다 (`test_j03`) |
| 4. 다른 영역의 카드 | 🟢 `CandidateSource.zones` 가 거른다 |
| 5. 소유자 ≠ 컨트롤러 | 🟢 `CandidateSource.owner` 가 `PlayerRef` 로 본다 (6-M 의 `movement_player` 와 같은 축) |
| 6. 선택 후 영역 이동 | 🟢 같은 인스턴스가 `LEGAL` → `CANDIDATE_NOT_ELIGIBLE` 로 바뀐다 (`test_i01`) |
| 7. 더 이상 존재하지 않는 카드 | 🟢 `UNKNOWN` / `HIDDEN_CARD` — 없다고 단정하지 않는다 (`test_i03`) |
| 8. 선택 수보다 후보가 많다 | 🟢 조합을 **전부** 열거한다 (상한 아래에서) |
| 9. 선택 수보다 후보가 적다 | 🟢 조합 0개. 장수를 줄이지 않는다 (`test_c01`) |
| 10. 같은 인스턴스 중복 선택 | 🟢 조합에 구조적으로 없고, 손으로 넣으면 `DUPLICATE_SELECTION` |

**비공개 정보**: 조합 수가 상대 패 장수(0 · 3 · 6)와 무관하게 10으로
고정이다 (`test_j02`) — 조합 수를 읽어 상대 패를 세는 길이 없다. 그리고
상한은 **거른 뒤의** 후보로 본다 (`test_e04`): 덱에 30장이 있어도 패의
10장만 세므로, 쓸 수 없는 후보 때문에 쓸 수 있는 효과가 막히지 않는다.

---

## 10. 해결 시 대상 유효성 · 부분 해결 (§9 · §18-9 · §18-10)

### 10-1. 해결 시 재확인은 **있다**

실행 직전 `TargetResolver` 가 다시 판정하므로, 고른 뒤 자리를 벗어난 대상은
거기서 걸린다. 같은 `InstanceId` 가 같은 판정기에서 `LEGAL` →
`CANDIDATE_NOT_ELIGIBLE` 로 바뀌는 것을 실측했다 (`test_i01`). 즉 선택은
발동 시점의 **기록**이고 적법성은 **볼 때마다 다시** 본다.

### 10-2. 부분 해결은 🔴 **정하지 않았다**

§9 가 *"무조건 허용하거나 무조건 금지하지 않는다"* 고 했고, 그것을 정할
근거(개별 카드 효과 + 공식 재정)가 없다 — 등재된 다중 선택이 한 장뿐이다.

그래서 **기존 실행기의 행동을 그대로 두고, 그 행동이 무엇인지만 쟀다.**

> 실측: 고른 두 장 중 한 장을 미리 묘지로 옮기면 **해결되지 않는다.**
> 남은 한 장은 패에 그대로 있고 묘지 수가 변하지 않는다.

즉 지금 엔진은 **"전원이 필요하다"** 쪽으로 행동한다. `test_i02` 가 그
사실을 못 박았다 — 누군가 부분 해결을 넣으면 깨지고, 그때 §9 의 근거를
먼저 확인하게 된다. 이 Phase 는 임의의 순차 실행으로 대체하지 않았고 새
체인 해결 시스템을 만들지 않았다.

### 10-3. 동시 · 순차 축

⚪ **없다.** `AppliedOperation` 하나에 `instances` 둘이 들어가므로 실행
자체는 "한 조작을 여러 장에" 다. 그것이 규칙상의 "동시" 인지는 이 모델이
말하지 않으며, 말하지 않는 것을 말한다고 적지 않았다.

---

## 11. 실제 다중 대상 효과 실행 결과 (§11 · §18-11)

### 11-1. 🔴 엔진이 스스로 열거한 조합으로 해결했다

```
target_combinations(…)   = 10개            ← 엔진이 만든 조합
고른 조합                = [#41, #42]       ← combos[0] 를 그대로 썼다
selections_for           = @primary=[#41, #42]
can_activate             = valid
resolve_all              = resolved=True
                           "체인1 P0 92595643:e[0] 대상 @primary=[#41, #42] 를 해결했습니다."
```

| 자리 | 전 | 후 |
|---|---|---|
| `HAND` | 5 | **3** |
| `GRAVE` | 0 | **3** |
| `SZONE` | 1 | **0** |
| #41 | `HAND` | **`GRAVE`** |
| #42 | `HAND` | **`GRAVE`** |
| 벌금 자신 | `SZONE` | `GRAVE` |

손으로 고른 두 장이 아니라 **`target_combinations` 가 만든 조합**을 썼다는
점이 이 Phase 의 산출물이다. 그리고 **조합마다 결과가 다르다** —
`combos[0]` 과 `combos[9]` 가 서로 다른 두 장을 버린다 (`test_h02`).

### 11-2. 🔴 그런데 `legal_actions` 에는 오르지 않는다 — 솔직하게 적는다

위 실행은 **허가를 손으로 넣은 것**이다 (`force_resolve`, 6-O 의
`_force_execute` 와 같은 태도). 실제 관문은 이렇게 답한다.

```
legal_actions(P0) 의 ACTIVATE_EFFECT   = 0건
ActionValidator.validate(…)            = unknown / RULE_NOT_IMPLEMENTED
이유: TRAP_TRIGGER_MISSING
      "trap-activation-timing (함정의 유발 조건을 효과마다 구분할 수 없다 —
       공식 스크립트의 SetCode(EVENT_*) 가 EffectDefinition 에 없다)"
```

**그 관문은 다중 대상과 무관하다.** 단일 대상 함정(강제 탈출 장치)도 같은
자리에서 같은 코드로 막힌다 (`test_g02`). 즉 남은 BLOCKER 는 "여러 장" 이
아니라 **"함정"** 이다. §16 이 TRIGGER 자동 발동 시스템을 금지하므로 열지
않았다.

🟡 **6-O 의 실행 사례에도 같은 조건이 붙는다.** 6-O 가 "강제 탈출 장치가
실제로 해결된다" 고 보고한 것도 `_force_execute` 로 허가를 넣은 경로였다.
6-P 가 그 사실을 다시 측정했고(`test_g02`), 오해를 남기지 않기 위해 여기에
적는다.

---

## 12. GameState 변경 및 EventJournal (§12-O · §18-12)

```
#0 ActionEvent   set_spell_trap    deltas=(CardSet(#40 HAND→SZONE FACEDOWN),)
#1 ActionEvent   activate_effect   deltas=(SpellRevealed(#40 SZONE FACEUP),)
#2 EffectEvent   92595643:e[0]     actor=P0  source=#40
                 applied=(AppliedOperation(DISCARD, reason=('DISCARD','EFFECT'),
                                           instances=(#41, #42)),)
                 deltas=(ZoneMoved(DISCARD #41 P0:HAND→P0:GRAVE),
                         ZoneMoved(DISCARD #42 P0:HAND→P0:GRAVE))
#3 ActionEvent   activate_effect   deltas=(SpellRetired(#40 SZONE→GRAVE),)
```

| 재는 것 | 결과 |
|---|---|
| `EffectEvent` 수 | **1개** — 두 조작으로 쪼개지지 않았다 |
| `applied` 수 | **1개** — 한 `DISCARD` 다 |
| `applied[0].instances` | **2장**, 그리고 고른 순서를 보존한다 |
| `deltas` | **2개** — 실제로 움직인 카드마다 하나 |
| 각 delta | `HAND → GRAVE`, `source_player == destination_player == P0` |

🔴 **적용되지 않은 이동을 성공으로 적지 않는다.** `test_i02` 의 부분 해결
시도에서는 `EffectEvent` 가 아예 없고 묘지 수가 변하지 않는다.

---

## 13. 어니스트와 Phase 6-O 실행 회귀 (§18-13)

| 회귀 | 결과 |
|---|---|
| **어니스트 ① (6-L `SELF_TARGET`)** | 🟢 `references_self=True`, `chosen_bindings = 0`, 조합 `[()]`, `selections_for → ()`. 열거를 넓힌 것이 자기 참조를 건드리지 않았다 (`test_k05`) |
| **Phase 6-O `MZONE → HAND`** | 🟢 강제 탈출 장치 조합 1개, 해결 성공, 대상이 `HAND`, 상대 패 +1장 (`test_k06`) |
| **6-O 의 경계** | 🟢 효과 몬스터(사이버 드래곤) 대상이면 **여전히 멈춘다** — `IsAbleToHand`. 열거를 넓힌 것이 규칙 지식을 넓히지 않았다 (`test_k07`) |
| **파괴 판정 공백** | 🟢 싸이크론은 여전히 파괴 판정에서 멈춘다 — 조합 1개는 그대로, 멈추는 이유가 대상이 아니라 파괴다 (`test_k09`) |

---

## 14. 기존 단일 대상 및 자기 참조 회귀 (§18-14)

| 효과 | 전 | 후 |
|---|---|---|
| 강제 탈출 장치 (상대 몬스터 2장) | 조합 2개 | 🟢 **2개** |
| 자기 미라화 (내 몬스터 2장) | 조합 2개 | 🟢 **2개**, 해결 성공, 고른 쪽만 묘지 |
| 싸이크론 (앞면 마법 1장) | 조합 1개 | 🟢 **1개** |
| 무정한 말살 (`@primary` + `@random`) | 조합 2개 | 🟢 **2개** — `@random` 은 여전히 짝에서 빠진다 |
| 어리석은 매장 (덱 대상) | 조합 0개 | 🟢 **0개** — 관측 경계 그대로 (STRUCTURAL-125) |
| 욕망의 항아리 (대상 없음) | `[()]` | 🟢 **`[()]`** — 없는 곳에 지정 절차를 넣지 않았다 |
| 어니스트 (`SELF_TARGET`) | `[()]` | 🟢 **`[()]`** |

---

## 15. 실행 가능성 전후 비교 (§14 · §18-15)

| # | 지표 | 전 | 후 |
|---|---|---|---|
| 1 | 기존 단일 대상 지원 범위 | 5건 | 5건 (변화 없음) |
| 2 | 기존 복수 대상 지원 범위 | **0건** | **1건** |
| 3 | 실제 다중 대상 차단 사례 | **1건** (벌금) | **0건** (열거 기준) |
| 4 | 새로 올바르게 선택 가능한 효과 | 0건 | **1건** / 조합 **0 → 10개** |
| 5 | 새로 실행 가능한 다중 대상 효과 | 0건 | **1건** (벌금) |
| 6 | GameState 변경 검증 사례 | — | **1건** — `HAND 5→3`, `GRAVE 0→3` |
| 7 | EventJournal 일관성 | — | 🟢 `EffectEvent` 1 / `applied` 1 / `instances` 2 / `deltas` 2 |
| 8 | 불법 선택을 거절한 사례 | — | **5/5** (부족 · 초과 · 0장 · 중복 · 가려진 카드) |
| 9 | 어니스트 실행 | 성공 | 🟢 유지 |
| 10 | Phase 6-O 효과 실행 | 성공 | 🟢 유지 |
| 11 | 새로운 구조적 차단 요인 | — | 🔴 **없음** (새로 만든 것). 남은 것은 기존 `TRAP_TRIGGER_MISSING` |

🔴 **정적 열거와 실제 실행을 가른다.** 4번(조합 10개)은 정적 후보 생성이고,
5·6번이 실제 실행이다. 그리고 `legal_actions` 기준으로는 **0건 증가**다
(§11-2) — 그 수를 늘린 것처럼 적지 않는다.

**검사 범위**: 전수가 아니다. 등재된 효과 **17개 / 대상 바인딩 9개**가
표본이고, 코퍼스 12,968장은 §1-5 의 분석 데이터 신뢰도 측정에만 썼다.

---

## 16. 타깃 · 통합 · 최종 회귀 테스트 결과 (§15 · §18-16)

### 16-1. 신규 — `tests/engine/test_multi_target_selection.py` (58개)

| 절 | 무엇 | 개수 |
|---|---|---|
| A | 감사 — 모델·장수 규칙·실행기가 **이미** 있었다 / 공식 텍스트 근거 | 5 |
| B | 정확히 N장 열거 — `C(n,2)` · 중복 없음 · 순서 결정성 · 같은 ID 다른 인스턴스 | 10 |
| C | 후보 부족 — 장수를 줄이지 않는다 / 모양 미지원과 다르다 | 4 |
| D | 미지원 모양 — 이유의 이름 넷 + 가변 장수 거부 | 7 |
| E | 상한 — 선언임을 명시 · 252 열거 · 462 거부 · 거른 뒤로 센다 · 동등 변이 불변식 | 6 |
| F | 금지 사항 — 새 엔진 0 · 새 타입 0 · 열거 자리 하나 · 카드 ID 분기 0 · TARGETING/CHOOSING 공백 | 5 |
| G | 🔴 남은 관문 — `legal_actions` 0건 · 단일 대상 함정도 같다 | 2 |
| H | 🔴 실제 실행 — 해결 · 조합마다 다른 결과 · EventJournal · ChainLink | 4 |
| I | 선택 후 이동 · 부분 해결 미지원 · 사라진 대상 `UNKNOWN` | 3 |
| J | 비공개 정보 — 상대 패 비후보 · 조합 수 누출 없음 · 뒷면 | 3 |
| K | 회귀 — 단일 대상 · 대상 없음 · `@random` · 덱 대상 · `SELF_TARGET` · 6-O · 6-O 경계 · 자기 미라화 · 파괴 공백 | 9 |

### 16-2. 움직인 기존 테스트 — **한 파일 / 한 개**

🔴 지운 테스트 · 추가한 skip · 약화한 단언 · 완화한 threshold 는 **없다.**

| 테스트 | 무엇이 틀린 전제였나 | 어떻게 고쳤나 |
|---|---|---|
| `test_set_trap_timing_audit.py::test_08` | 🔴 **"벌금은 `target_bridge` 에서 조합 0개로 막힌다"** — 6-P 가 그 공백을 닫았다. 이름 자체(`the_two_that_do_not_execute`)가 **거짓 진술**이 되었다 | 과거형으로 **이름을 바꿨다** (`the_two_that_did_not_execute`). 재는 수를 지우지 않고 **더 센다**: 조합 10개 · `resolved` · 패 −2 · 벌금 자신 `GRAVE`. 다리의 한계가 카드 종류와 무관하다는 단언은 새 표지(`UNSUPPORTED_VARIABLE_COUNT` · `itertools.combinations(pool, take)`)로 유지 |

🔴 **그 시험의 결론은 이제 두 번 증명되었다.** "막히는 이유가 함정과
무관하다" — 둘 다 함정을 한 줄도 건드리지 않고 풀렸다. 하나는 규칙 지식
(6-O), 하나는 열거 절차(6-P)였다. 그리고 함정 자체의 관문은 여전히 닫혀
있다 (`test_g01` · `test_g02` 가 센다).

### 16-3. Mutation 테스트 — 12개

**내가 바꾼 코드만** 대상으로 했다. `git checkout` 을 쓰지 않았고 원본을
메모리에 들고 있다가 되돌리고 `assert` 로 확인했다
(`scratchpad/mutate7.py`). 판정 테스트는 신규 파일 + `test_target_bridge` +
`test_set_trap_timing_audit` + `test_self_reference_target` 이고
**pytest 의 실제 종료 코드**로 판정했다.

| # | 고의 결함 | 결과 |
|---|---|---|
| M1 | 열거를 6-P 전으로 되돌린다 | killed |
| M2 | `combinations` → `combinations_with_replacement` | killed |
| M3 | 가변 장수도 열거한다 | killed |
| M4 | 자리가 둘이어도 첫 자리만 열거한다 | killed |
| M5 | 중복 허용을 무시한다 | killed |
| M6 | 상한을 보지 않는다 | killed |
| M7 | 상한을 넘으면 **자른다** (`islice`) | killed |
| M8 | 상한을 **거르기 전** 후보 수로 본다 | killed |
| M9 | 가려진 카드도 조합에 넣는다 | killed |
| M10 | `selections_for` 가 가변 장수를 조용히 깎는다 | killed |
| M11 | `take = choice.maximum` 으로 읽는다 | 🟡 **생존 — 동등 변이** |
| M12 | 열거 순서를 뒤집는다 | killed |

**11/12 killed, 생존 1 (동등 변이).**

#### 🟡 M11 은 테스트의 구멍이 아니라 **동등 변이**다

`take = choice.minimum` 에 닿는 유일한 경로는
`unsupported_enumeration(definition) is None` 을 통과한 뒤이고, 그 함수가
`minimum != maximum` 를 거부한다. 따라서 그 자리에서 `minimum` 과
`maximum` 은 **항상 같은 값**이고, 두 프로그램은 동일하다. 어떤 시험으로도
가를 수 없다 — 가를 수 있다면 불변식이 깨진 것이다.

그래서 숨기지 않고 **불변식을 시험으로 못 박았다** (`test_e06`): `(min,max)`
를 0~3 범위로 전수 만들어 열거가 허용되는 모양이 `[(1,1), (2,2), (3,3)]`
뿐임을 확인하고, 등재된 효과에서도 같음을 확인한다. 관문을 풀면 이 시험이
깨지고, 그때 `minimum`/`maximum` 중 무엇을 집을지 §6 을 다시 읽게 된다.
재측정에서도 M11 은 생존한다 (151 passed) — **그것이 정답이다.**

### 16-4. 🔴 Phase 6-O 보고서의 수치 하나를 바로잡는다

6-O 보고서 §19-1 은 최종 엔진 회귀를 **3,317 passed** 로 적었다. 실측하면
그 시점 이후가 빠져 있다.

| 측정 | 수 |
|---|---|
| 6-O 보고서의 엔진 수 | 3,317 |
| 깨끗한 `HEAD`(`ee50d4f`) 의 `tests/engine` 수집 수 | **3,320** |
| 차이 | **+3** |

원인: 6-O 의 엔진 회귀는 mutation R4 · R6 을 죽이기 위해 더한 세 시험
(`test_b06` · `test_b07` · `test_b08`) **보다 먼저** 돌았다. 그 셋을 더한
뒤 엔진 전체를 다시 돌리지 않았으므로 보고서의 수가 세 개 적었다.

🔴 **회귀가 깨졌던 것이 아니다** — 지금 깨끗한 HEAD 에서 3,320개가 수집되고
6-P 의 회귀에서 전부 통과한다. 그래도 **보고한 수가 실제와 달랐으므로**
적는다. 6-P 의 기준선은 **3,320** 이고, 3,378 − 58(신규) = 3,320 으로
맞는다.

### 16-5. 실행 기록

(§19 에 명령 · 시간 · 종료 코드와 함께 적었다.)

---

## 17. 남아 있는 구조적 BLOCKER (§18-17)

### 17-1. 🔴 함정 유발 조건 — `TRAP_TRIGGER_MISSING` (가장 큼)

```
trap-activation-timing (함정의 유발 조건을 효과마다 구분할 수 없다 —
공식 스크립트의 SetCode(EVENT_*) 가 EffectDefinition 에 없다)
```

등재된 함정 5장은 **전부 `EVENT_FREE_CHAIN`** 이고 그 사실이 `core` 의
`Card.script` 에 **있다.** 그런데 `EffectDefinition` 에 옮겨지지 않았다.
그래서 엔진은 "유발 조건 없는 함정" 과 "무언가가 일어났을 때만 발동하는
함정" 을 구분할 수 없고, 구분하지 못한 채 종류 전체를 통과시키면 유발
함정이 아무 때나 발동한다. 그래서 `UNKNOWN` 으로 막혀 있다.

**영향**: 등재된 함정 5장 중 실행 가능한 4장이 `legal_actions` 에 전혀
오르지 못한다 — 벌금(다중 대상)과 강제 탈출 장치(6-O)를 포함한다.

### 17-2. 🟠 부분 해결의 축이 없다

"전원이 필요한 효과" 와 "유효한 것만 처리하는 효과" 를 구분하는 칸이
`EffectDefinition` 에 없다. 지금은 전부 전자처럼 행동하고
(`test_i02` 가 못 박았다), 그것이 옳은지는 **카드마다 공식 재정이 필요**하다.
등재된 다중 선택이 한 장이므로 지금은 드러나지 않는다.

### 17-3. 🟠 대상 지정과 해결 시 선택이 실행에서 갈리지 않는다

모델은 `TARGETING` / `CHOOSING` 을 구분하지만 읽는 프로덕션 자리가 설명
문구 하나뿐이다 (§4). 영향: 대상 내성 · "대상이 되었을 때" 유발 · 대상
변경 효과를 지금은 표현할 수 없다.

### 17-4. 🟡 가변 장수 · 자리 둘 · 중복 허용

열거가 거부한다 (이유의 이름을 댄다). 등재 0건이므로 **지금은 실행을
막지 않는다.** 실제 카드를 등재하기 전에 §6 의 기준(후보가 부족할 때 줄여도
되는가 / 어느 자리를 먼저 고르는가)을 공식 근거로 정해야 한다.

### 17-5. 🟡 분석 계층의 선택 수가 신뢰할 수 없다

§1-5 의 세 결함. 영향: 효과를 **자동으로** 등재하는 길을 지금은 쓸 수 없다.
`OPERATION_RULINGS` 와 효과 라이브러리를 손으로 적는 이유가 그것이다.

### 17-6. 🟡 비용과 대상의 순서를 잴 수 없다

등재된 17개 효과 전부 비용이 없어서 `_activation_actions` 의 비용 관문이
아무것도 거르지 않는다. 비용 있는 효과가 생기면 ADR-008(일반 rollback 부재)
때문에 "비용 → 대상 → 실패" 경로를 먼저 설계해야 한다.

---

## 18. 다음 단계의 최소 실행 선행 조건 (§18-18)

🔴 **§17-1 (함정 유발 조건)** 을 권한다.

| 기준 | 판정 |
|---|---|
| 실제 Duel 실행을 차단하는가 | 🟢 실행 가능한 함정 **4장**이 `legal_actions` 에 0건 |
| 규칙 지식이 아니라 **연결**인가 | 🟢 `EVENT_FREE_CHAIN` 이 `core` 에 **이미 있다** — 6-O 와 같은 모양의 작업이다 |
| 범위가 작은가 | 🟡 `EffectDefinition` 에 칸 하나 + 컴파일러 연결 + 검증기 한 곳. **공유 계약 변경**이므로 승인이 필요하다 |
| 정확성 위험 | 🟠 **큼** — 종류 전체를 통과시키면 유발 함정이 아무 때나 발동한다. `EVENT_FREE_CHAIN` **한 값만** 열고 나머지는 `UNKNOWN` 으로 두는 것이 전제다 |
| 승인 필요 | 🔴 **예** — `EffectDefinition` 은 공유 계약이다 (§10 · §16) |

그 다음 후보는 **§17-3 (TARGETING / CHOOSING 을 실행에서 가르기)** 이다.
다중 대상이 열린 지금이 그것을 가를 자연스러운 시점이지만, 체인 해결 절차가
새로 필요하므로 **범위와 승인을 먼저 정해야 한다.**

🔴 **이 Phase 는 위 둘 중 아무것도 진행하지 않았다.**

---

## 19. 테스트 실행 기록 및 Git 커밋 · 푸시 결과

### 19-1. 실행한 테스트 명령어 · 시간 · 결과 · 🔴 **실제 종료 코드**

모두 `YGO_CARDS_CDB=data/cards.cdb` 를 설정하고 `-p no:randomly` 로 돌렸다
(§15). 종료 코드는 `| tail` 이 가리지 않도록 **pytest 자신의 종료 코드**를
따로 읽었다.

| # | 단계 | 명령어 | 시간 | 통과 | 실패 | skip | 종료 코드 |
|---|---|---|---|---|---|---|---|
| 1 | 1·2단계 — 타깃 | `pytest tests/engine/test_multi_target_selection.py -q -p no:randomly --no-header --tb=short` | 4.03s | **58** | 0 | 0 | 🟢 **0** |
| 2 | 3단계 — 엔진 (1차, 신규 파일 전) | `pytest tests/engine -q -p no:randomly --no-header --tb=line` | 389.30s (6:29) | 3,319 | 🔴 **1** | 0 | 🔴 **1** |
| 3 | 수정한 핀 단독 | `pytest tests/engine/test_set_trap_timing_audit.py -q -p no:randomly --no-header --tb=short` | 3.75s | **18** | 0 | 0 | 🟢 **0** |
| 4 | 3단계 — 엔진 (최종) | `pytest tests/engine -q -p no:randomly --no-header --tb=short` | 384.88s (6:24) | **3,378** | 0 | 0 | 🟢 **0** |
| 5 | 4단계 — 루트 53파일 | `pytest <53 files> -q -p no:randomly --no-header --tb=short` | 2370.78s (39:30) | **1,581** | 0 | 0 | 🟢 **0** |
| 6 | Mutation 12건 | `scratchpad/mutate7.py` (판정은 pytest 종료 코드) | — | killed **11/12** | 생존 **1 (동등 변이)** | — | — |

🔴 **#2 의 1건을 숨기지 않는다.** `test_08` 이 6-P 가 닫은 공백을 "열려
있다" 고 단언하고 있었고, §16-2 에 "왜 그 전제가 거짓이 되었는지" 를 적었다.

루트 53파일 선정 기준(§15 4단계): `target_bridge` · `target_combinations` ·
`selections_for` · `chosen_bindings` · `required_target_count` ·
`TargetSelection` · `ChoiceSpec` · `TargetRequirement` · `legal_actions` ·
`PlayerAction.activate_effect` · `ActionTarget` · `minimum` · `maximum` ·
`def test_37` 중 하나라도 언급하는 루트 테스트 파일 전부 (`conftest.py` 제외).

🔴 **돌리지 않은 것**: `scripts/fetch_ocg_rulings.py --all`(14,000장 크롤링)
은 금지되어 있어 실행하지 않았다. 공식 사이트에 접속한 적이 없고, 저장소
전체 회귀도 돌리지 않았다 (§15: 광범위한 아키텍처 변경이 아니다).

### 19-2. 루트 회귀 결과

```
=== root (53 files) start 07:17:56 ===
ROOT_EXIT=0
1581 passed, 1 warning in 2370.78s (0:39:30)
=== DONE 07:57:28 ===
```

🟢 **움직인 루트 핀이 0건이다.** 6-N · 6-O 가 각각 고쳐야 했던 census 핀
(`counts(base)` vs `counts("HEAD")`) 이 이번에는 하나도 걸리지 않았다 —
이 Phase 가 **기존 테스트 파일에 테스트를 더하지 않았기** 때문이다
(신규는 새 파일 하나, 수정은 기존 한 개의 본문뿐).

경고 1건은 `discord.py` 의 `audioop` DeprecationWarning 이고 이 Phase 와
무관하다 (Python 3.13 예고).

### 19-3. 커밋

작업 브랜치: `claude/pensive-goodall-te1egy`.
기존 commit 을 rewrite · amend 하지 않았고 force push 하지 않았다.
새 브랜치와 PR 을 만들지 않았다.

(실제 SHA 는 19-4 에 적는다.)

### 19-4. 푸시 결과

(커밋 직후 실제 SHA 와 푸시 출력을 기록한다.)

---

## 20. 완료 수준 판정 (§19)

### 🟢 수준 1 — 다중 대상 구조 감사 **달성**

- 기존 대상 선택 기능의 실제 지원 범위를 확인했다 (§1).
- 다중 대상 실행을 막는 구조적 요인을 찾았다 — `target_combinations` 의
  열거 한 줄 (§2 · §3).
- 발동 시 대상 지정과 해결 시 선택을 구분했다 — **모델은 가르고 실행은
  가르지 않는다**는 사실까지 (§4).
- Engine V1 공개 계약을 유지했다 (프로덕션 한 파일, 새 타입 0개).
- 조사 결과를 근거와 함께 문서화했다.

### 🟢 수준 2 — 다중 대상 판정 개선 **달성**

- 실제 차단 원인을 최소 범위에서 수정했다 (한 파일 +167 −12).
- 선택 수와 선택 조건을 정확히 검증한다 (§8 — 5/5 불법 선택 거절).
- 같은 카드 ID 의 여러 인스턴스를 구분한다 (§9-1 — 후보 5장 전부 같은
  카드인데 조합 10개).
- 불법 선택과 중복 선택을 차단한다.
- 단일 대상 · 자기 참조 기능을 유지한다 (§13 · §14).
- 관련 테스트를 통과한다 (§16 · §19).

### 🔴 수준 3 — 실제 다중 대상 효과 실행 **미달성**

여섯 항목 중 **다섯**이 실측으로 충족된다.

| 항목 | 판정 |
|---|---|
| 실제 Duel 에서 **합법적인** 효과를 발동한다 | 🔴 **아니다** — `legal_actions` 0건, 검증기가 `UNKNOWN`. 허가를 손으로 넣었다 |
| 복수 대상을 기존 계약으로 선택한다 | 🟢 `target_combinations` → `ActionTarget` → `selections_for` → `TargetSelection` |
| 기존 `EffectExecutor` 가 해결한다 | 🟢 `resolved=True` |
| 실제 GameState 변경 | 🟢 `HAND 5→3`, `GRAVE 0→3` |
| EventJournal 이 실제 결과와 일치 | 🟢 `applied` 1 / `instances` 2 / `deltas` 2 |
| 어니스트 · 6-O 실행 유지 | 🟢 둘 다 유지 |

🔴 **그래서 "다중 대상 판정 개선 완료, 실제 다중 대상 효과 실행 미달성"
이라고 보고한다.** 막는 것은 다중 대상이 아니라 **함정 유발 조건**
(§17-1)이고, 그것은 §16 이 금지한 범위다. 정적 분석만으로 수준 3 을
주장하지 않으며, 실행이 된 사실과 발동이 적법해진 사실을 **섞지 않는다.**

---

## 21. 다음 Phase

🔴 **다음 Phase 는 자동으로 시작하지 않는다** (§18).

§18 이 권하는 §17-1(함정 유발 조건)은 `EffectDefinition` 이라는 **공유 계약
변경**이므로 §10 · §16 에 따라 **사용자 승인을 기다린다.** 어느 쪽을 할지와
"`EVENT_FREE_CHAIN` 한 값만 열 것인지" 의 범위는 지시를 받은 뒤에 정한다.
