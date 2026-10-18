# Phase 6-W — 덱 카드 선택 및 묘지 이동 효과 실행

브랜치: `claude/pensive-goodall-te1egy` · 시작 지점 `1f05b00` (6-V 완료)

## 요약 — 달성 수준

| 수준 | 내용 | 결과 |
| --- | --- | --- |
| 수준 1 | `STRUCTURAL-125` · `MAY_BE_SENT_TO_GRAVE` 원인 확인, 선택·이동 계약 분석 | ✅ **달성** |
| 수준 2 | 덱 후보 생성 + 묘지 이동 가능 여부 **정확한 판정** | ⚠️ **절반** — 후보 생성은 정확하다 (35/35, 거짓 양성 0건). **판정은 못 한다** (A/B/C 전부 `UNKNOWN`) |
| 수준 3 | 실제 Duel 에서 덱→묘지 이동을 GameState · EventJournal 로 검증 | ❌ **미달성** — 해결이 `UNCHECKED_RULES` 에서 멈춘다 |

🔴 **수준 2 를 "판정 성공" 으로 적지 않았고, 수준 3 을 열기 위해 근거 없는
허가를 넣지 않았다.** 이유는 §3 에 있다 — 묘지 이동을 licensing 하는 룰북
문장이 **없다**. 6-U 는 그 문장이 있었기 때문에 4,028장을 열 수 있었다.

**프로덕션은 한 줄도 바꾸지 않았다.** 이 Phase 가 추가한 것은 측정과
고정(테스트 25건)과 이 보고서다. 그리고 회귀 검증 과정에서 **이전 Phase
때부터 깨져 있던 루트 감사 3건**을 찾아 고쳤다 (§10.1).

---

## 1. 기존 구조와 실제 BLOCKER 원인

### 1.1 `STRUCTURAL-125` — 범주 오류다, 결함이 아니다

발생 위치는 **한 곳**이다.

```
engine/target_bridge.py:374
```

```python
ordinary = GameStateView.from_state(state, viewer=seat)
pool = tuple(
    instance for instance in found.eligible
    if ordinary.find(instance) is not None
)
```

`target_combinations` 는 두 단계로 좁힌다. ① 규칙이 선언한
`looked_at` 을 열고 후보를 센다 → ② **평소 관측에 보이는 것만** 남긴다.
덱은 평소 관측에 보이지 않으므로 ②가 전부 걸러낸다.

🔴 **그 경계는 옳다.** 주석이 이유를 적어 둔다 — `PlayerAction` 은 정책
(AI)에게 가는 **데이터**이고, 거기에 가려진 존의 인스턴스를 적으면 정책이
후보 목록을 읽는 것만으로 덱 내용을 알게 된다.

그래서 `STRUCTURAL-125` 는 "덱 선택 정보가 부족하다" 가 아니다. **해결 시점
선택을 발동 시점 대상 지정으로 모델링한 것의 정당한 귀결**이다. 기르수의
Lua 가 그것을 증명한다.

```lua
-- s.tgtg (SetTarget) — 존재 여부만 본다. EFFECT_FLAG_CARD_TARGET 이 없다.
if chk==0 then return Duel.IsExistingMatchingCard(s.tgfilter,tp,LOCATION_DECK,0,1,nil) end

-- s.tgop (SetOperation) — 고르는 것은 여기다. 해결 중이다.
local tc=Duel.SelectMatchingCard(tp,s.tgfilter,tp,LOCATION_DECK,0,1,1,nil):GetFirst()
```

엔진 어휘도 이미 그것을 가른다 — 기르수 정의는 `TargetSpec.choosing()` 이고
`requirement` 는 `CHOOSING`, `is_targeting` 은 `False` 다 (`test_a01`).

| 측정 | 값 |
| --- | --- |
| `spec.requirement` | `CHOOSING` |
| `spec.is_targeting` | `False` |
| `spec.looked_at_zones()` | `{DECK}` |
| `looked_at` 을 열었을 때 후보 | **35** |
| 평소 관측에서 보이는 후보 | **0** |
| `target_combinations(...)` | `[]` |
| `legal_actions` 의 `activate_effect` | **없다** |

**고칠 것은 경계가 아니라, 선택을 해결 시점으로 옮기는 계약이다.**

### 1.2 `MAY_BE_SENT_TO_GRAVE` — 사실의 출처가 둘뿐이다

판정 경로는 `engine/effect/ruling.py` 의 `BoardRuling.explain` 하나다.

```
CardOperation.send_to_grave(gated=True)
  → OperationKind.SEND_TO_GRAVE
  → RuleQuestion.MAY_BE_SENT_TO_GRAVE           (semantics.py:472)
  → BoardRuling.explain(question, instance)     (ruling.py:493)
      → _facts_of(card)                         (ruling.py:557)
          ① OperationRulingRegistry  — 손으로 적은 19건
          ② rulebook_facts()         — 관측된 카드 종류에서 룰북 한 줄로
      → 없으면 UNKNOWN
```

`_facts_of` 가 찾는 자리는 **둘**인데, 묘지 질문에 대해서는 **양쪽이 같은
한 줄로 수렴한다.**

| 출처 | 항목 수 | `MAY_BE_SENT_TO_GRAVE` 에 답하는 것 |
| --- | --- | --- |
| ① `OPERATION_RULINGS` (손으로 적음) | **19** | **1건** — 엘리멘틀 히어로 페더맨(21844576) · `TRUE` · `RuleBasis.RULEBOOK` |
| ② `rulebook_facts()` → `normal_monster_facts()` | 유도 | **통상 몬스터만** · `TRUE` · `RuleBasis.RULEBOOK` |

🔴 **①의 유일한 1건도 통상 몬스터이고 근거도 같은 룰북 줄이다.** 즉 묘지
질문에 답하는 지식은 저장소 전체에 **룰북 한 줄**뿐이다.

> "Yellow Normal Monster Cards do not have effects, and have a description
> of them written here that does not affect the game."

즉 **통상 몬스터만** `TRUE` 를 받는다. 기르수 후보 35장 중 통상 몬스터는
0장이므로 전부 `UNKNOWN` 이다.

### 1.3 `Card.IsAbleToGrave` — Lua 의 실제 사용 형태

| 식별자 | 호출 수 | 파일 수 |
| --- | --- | --- |
| `IsAbleToGrave` (효과) | **676** | **544** |
| `IsAbleToGraveAsCost` (비용) | **811** | **664** |
| 둘 다 쓰는 파일 | — | **36** |

🔴 **코퍼스가 §3 의 구분을 스스로 증명한다.** 둘은 다른 함수이고, 36개
파일만 둘 다 쓴다. `MAY_BE_SENT_TO_GRAVE` 의 대응물은 **앞쪽**이다
(`semantics.py:456` 이 이미 그렇게 적어 둔다).

괄호 없는 185건은 전부 `Card.IsAbleToGrave` 를 **필터 함수로 넘기는**
형태다 — `Duel.SelectMatchingCard(tp,Card.IsAbleToGrave,...)` 22건 등.
기르수가 `s.tgfilter` 안에서 쓰는 것과 같은 모양이다.

### 1.4 해결이 멈추는 정확한 자리

```
해결 상태: UNCHECKED_RULES
해결 이유: #0 를 묘지로 보낼 수 있는지 판정할 수 없습니다:
          이 카드를 묘지로 보낼 수 있는가 (Card.IsAbleToGrave) ·
          묘지 대신 다른 곳으로 가는가 (펜듈럼 · 토큰 · 대체 효과).
          판정할 수 없는 것을 허가로 바꾸지 않습니다.
기록: []
```

🔴 **발동은 성공한다** (`activated`, 체인 길이 1). 멈추는 것은 **해결**이다.
§3 의 "효과 발동 성공과 해결 성공을 구분" 이 여기서 실제로 갈린다.

---

## 2. 선택 조건 및 카드군 판정 방식

기르수의 `s.tgfilter` 가 묻는 것은 둘이다.

```lua
function s.tgfilter(c)
	return c:IsSetCard({SET_ORCUST,SET_WORLD_LEGACY}) and c:IsAbleToGrave()
end
```

엔진은 **앞쪽만** 후보 조건으로 쓰고, 뒤쪽은 조작의 `gated=True` 로 분리해
둔다 (그래서 §1.4 에서 멈춘다). 카드군 판정은 기존 setcode 계층 그대로다.

```python
compile_archetype_condition(("SET_ORCUST", "SET_WORLD_LEGACY"))
#  → IsSetCard((0x11b, 0xfe))   ·   unresolved == ()
```

| 측정 | 값 |
| --- | --- |
| 상수 테이블에서 해석된 코드 | `0x11b` (오르페골) · `0xfe` (성유물) |
| 미해석 이름 | **0건** |
| 엑스트라 아닌 해당 카드 (기르수 제외) | **46** |
| 40장 레시피 → 패 5장 뽑은 뒤 덱 후보 | **35** |

🔴 **카드 ID 도 카드명도 프로덕션에 적지 않았다.** 정의가 적는 것은 상수
이름 두 개이고, 숫자는 `constants` 테이블이 준다. 테스트도 같은 경로로
숫자를 얻는다 (`_archetype_codes`).

### 2.1 선택은 **해결 시점**이다 — 발동 시점 대상 지정이 아니다

§4 의 "효과 해결 과정의 선택을 발동 시 대상 지정으로 잘못 바꾸지 않는다"
를 지켰다. 기르수 정의는 `TargetSpec.choosing()` 이고, Lua 에
`EFFECT_FLAG_CARD_TARGET` 이 없다는 사실과 일치한다.

🔴 **임의의 첫 카드를 자동으로 고르지 않았다.** 테스트는 후보 목록을 받고
**명시적으로** 하나를 지정해 `TargetSelection` 에 넣는다. "첫 후보가 최적" 을
주장하지 않았다.

---

## 3. `MAY_BE_SENT_TO_GRAVE` 지원 범위

### 3.1 §5 의 A / B / C 를 **구분하지 못한다**

대표 네 장을 실제 판에서 직접 물었다.

| 카드 | §5 분류 | 답 | 이유 |
| --- | --- | --- | --- |
| 차원요새 병기 (1596508) | **B 불가** (`EFFECT_CANNOT_TO_GRAVE`) | `UNKNOWN` | `1596508 에 대해 확인된 것이 없습니다.` |
| 성유물－『성장』 (93920420) | **A 가능** (자기 묘지행 유발) | `UNKNOWN` | `93920420 에 대해 확인된 것이 없습니다.` |
| 오르페골 코어 (55051920) | **C 정보부족** | `UNKNOWN` | `55051920 에 대해 확인된 것이 없습니다.` |
| 엘리멘틀 히어로 페더맨 (21844576) | 통상 몬스터 | **`TRUE`** | 룰북: *Yellow Normal Monster Cards do not have effects…* |

🔴 **세 줄의 이유가 글자까지 같다.** 지원 범위는 "통상 몬스터 = `TRUE`,
나머지 전부 `UNKNOWN`" 이고, **B 를 `FALSE` 로 답하지도 못한다.** 이것을
"판정 지원" 이라고 적을 수 없다 (`test_f01`).

기르수 후보 35장 분포: `{'UNKNOWN': 35}`.

### 3.2 재료는 이미 전부 추출되어 있다

제약 상수는 분석 계층에 **정확히** 들어 있다. 단어 경계로 세면 스크립트와
완전히 일치한다 (`test_d01`).

| 상수 | 카드 수 | 의미 | 범위 |
| --- | --- | --- | --- |
| `EFFECT_CANNOT_TO_GRAVE` | **3** | 묘지행 **금지** | B |
| `EFFECT_CANNOT_TO_GRAVE_AS_COST` | **1** | **비용 한정** 금지 | B 아님 (§3.3) |
| `EFFECT_TO_GRAVE_REDIRECT` | **31** | 묘지 **대신** 다른 곳 | B 아님 (§3.4) |
| `EFFECT_TO_GRAVE_REDIRECT_CB` | **16** | 대체 **콜백** | B 아님 (§3.4) |
| `EFFECT_LEAVE_FIELD_REDIRECT` | **255** | **필드를 떠날 때** | **범위 밖** — 덱 카드에 해당 없음 |

> 🔴 **내가 한 번 틀린 자리다.** 첫 측정은 부분 문자열로 세서
> `EFFECT_TO_GRAVE_REDIRECT` 가 `..._CB` 안에, `EFFECT_CANNOT_TO_GRAVE` 가
> `..._AS_COST` 안에 걸렸고, 분석기가 17장을 놓친 것처럼 보였다. 단어
> 경계(`\b`)로 다시 재니 **분석기가 정확했다.** 그 과정에서 네 번째 상수
> (`..._AS_COST`)를 찾았다. `test_d01` 이 두 경로(분석 계층 · 원본 스크립트)
> 의 집합이 **같다는 것**을 고정한다.

### 3.3 비용과 효과를 가른다

F.A. 윕크로서(49655592)는 `EFFECT_CANNOT_TO_GRAVE_AS_COST` **만** 등록하고
`EFFECT_CANNOT_TO_GRAVE` 는 갖지 않는다. 즉 "비용으로는 못 보내지만 효과로는
보낼 수 있다" 와 모순되지 않는다. 룰북도 그 둘을 가른다 — *"…sent to the
Graveyard **as a cost** or Tribute, is NOT considered 'destroyed.'"*

기르수의 조작은 **효과**다: `definition.cost.costs == ()` 이고
`operation.kind is OperationKind.SEND_TO_GRAVE` 다 (`test_d02`).

### 3.4 이동 불가와 대체 이동을 가른다

매크로 코스모스(30241314)는 묘지행을 **금지하지 않는다**. 묘지 **대신
제외**로 보낸다 — 원본에 `EFFECT_TO_GRAVE_REDIRECT` 와 `LOCATION_REMOVED`
가 함께 있다. 보옥수 사파이어 페가수스(7093411)는 대체 **콜백**이다.

🔴 §5 의 "지원되지 않는 대체 효과를 무시하고 묘지 이동에 성공했다고 기록
하지 않는다" 를 지켰다 — 해결 이유 문장 자체가 *"묘지 대신 다른 곳으로
가는가 (펜듈럼 · 토큰 · 대체 효과)"* 를 **미판정 항목으로 명시**한다.

### 3.5 🔴 왜 유도를 더하지 않았는가 — 룰북에 근거가 **없다**

6-U 가 4,028장의 일반 소환을 연 근거는 룰북의 **직접적 허가 문장**이었다.

> "All Normal Monsters, and most Effect Monsters (**unless they have a
> specific restriction**), can be Summoned in this way" — `RULE-SUMMON-009`

묘지에는 그런 문장이 **없다**. 룰북의 `Send to the Graveyard` 항목을 실측
했다 (`test_c01`).

| 항목 | 결과 |
| --- | --- |
| `"can be sent to the Graveyard in various ways"` | **있다** (보내는 방법 열거) |
| `"When this card is sent to the"` | **있다** (유발 효과 설명) |
| `"banished"` | **있다** (예외는 **제외 카드**에 관한 것) |
| `"unless"` | 🔴 **없다** |
| `"restriction"` | 🔴 **없다** |
| 대조군: 소환 항목의 `"unless they have a specific restriction"` | **있다** |

구조화 자료의 묘지 존도 licensing 하지 않는다 (`test_c02`).

```json
"movement": [
  "Monster Cards sent here when destroyed",
  "Spell & Trap Cards sent here when used"
]
```

🔴 **"효과로 덱에서 보내진다" 가 없다.** 그래서 "제약 상수가 없다 → 보낼 수
있다" 는 **근거 없는 허용**이고, §3 의 "카드 이동 가능 여부를 무조건 TRUE 로
처리하지 않기" · "UNKNOWN 을 근거 없이 VALID 로 변경 금지" 에 정면으로
걸린다. **그래서 하지 않았다.**

### 3.6 다음 Phase 가 쓸 증거는 재서 남겼다 (쓰지는 않았다)

카드 **자신의** 스크립트가 `EVENT_TO_GRAVE` 를 `SINGLE`(자기)로 등록하면,
그 카드는 묘지로 보내질 수 있다는 **긍정적 증거**다 — 룰북이 그 텍스트 모양
("When this card is sent to the…")을 묘지행에 직접 묶는다.

| 측정 | 값 |
| --- | --- |
| 엑스트라 아닌 카드 중 자기 묘지행 유발 보유 | **818** |
| 그중 `EFFECT_CANNOT_TO_GRAVE` 와 **모순** | 🔴 **0건** |
| 기르수 후보 46장 중 보유 | **정확히 1장** — 성유물－『성장』 |

공식 텍스트 확인: 성유물－『성장』의 `desc` 에 「묘지로 보내졌을 경우」가
있다 (`test_e02`).

> **사용자 결정에 따라 이번 Phase 는 이 유도를 넣지 않았다** ("지금은
> 유도하지 않고 BLOCKER 로 남긴다").

#### 🔴 막힌 것이 **그 사실 하나**임을 확인했다 (프로덕션 무변경)

`OPERATION_RULINGS` 의 **사본**에 성유물－『성장』의 사실 한 줄만 넣고
같은 프로덕션 해결 경로를 돌렸다. 원본 등록소는 그대로다 (19건).

```
등록소 사본: 20 (원본 19 그대로)
발동: activated
해결 상태: RESOLVED          ← UNCHECKED_RULES 가 아니다
덱:   35 -> 34
묘지:  0 -> 1
고른 인스턴스 자리: GRAVE | card_id: 93920420
기록: EffectEvent #0 69811710:e[0] P0: #34 P0/DECK → P0/GRAVE
      (send_to_grave), P0 의 DECK 34장을 섞었다
```

**읽는 법을 분명히 한다.** 이것이 보여주는 것은 "해결 경로 · 조작 ·
`EventJournal` 은 이미 완성되어 있고, 막는 것은 **판정 사실 하나**다" 다.
보여주지 **않는** 것은 818장에 대한 **유도의 정당성**이다 — 그 사실을 손으로
넣었기 때문이다.

🔴 **그래서 이 실행을 수준 3 달성으로 적지 않는다.** 프로덕션에서 기르수
효과는 여전히 해결되지 않는다 (§8). 이것은 §13.1 의 **근거**일 뿐이다.

---

## 4. 변경 파일과 함수

🔴 **프로덕션 변경 0건.** `engine/` · `core/` · `agent/` · `deck/` ·
`analysis/` · `sources/` · `app/` · `scripts/` 에 손대지 않았다.

| 파일 | 변경 | 무엇을 |
| --- | --- | --- |
| `tests/engine/test_deck_to_grave_blocker.py` | **신규** 25건 (A–I) | 되는 것과 **안 되는 것**을 같이 고정 |
| `docs/phase6w-deck-to-grave-execution.md` | **신규** | 이 보고서 |
| `tests/test_korean_overlay_display_boundary_audit.py` | `test_21` 측정 방법 · `PRODUCTION_DIRS` | 이전 Phase 의 깨진 감사 (§10.1①) |
| `tests/test_korean_overlay_return_value_audit.py` | `PRODUCTION_DIRS` + `deck` | 이전 Phase 의 깨진 감사 (§10.1②) |
| `tests/test_rule_not_implemented_code_audit.py` | 센서스 3개 정정 | 이전 Phase 의 깨진 감사 (§10.1③) |
| `tests/test_card_detail_provenance_display_audit.py` | `PRODUCTION_DIRS` + `deck` | 같은 누락 (실패 전 예방) |
| `tests/test_korean_overlay_unapplied_audit.py` | `PRODUCTION_DIRS` + `deck` | 같은 누락 |
| `tests/test_summary_korean_display_policy_audit.py` | `PRODUCTION_DIRS` + `deck` | 같은 누락 |
| `tests/test_text_analysis_consumer_policy_audit.py` | `PRODUCTION_DIRS` + `deck` | 같은 누락 |

🔴 **기존 테스트를 삭제·skip 하지 않았고, assertion 을 완화하지 않았다.**
`test_21` 은 **더 엄격해졌고**, `PRODUCTION_DIRS` 추가도 검사 범위를
**넓히는** 변경이다. 센서스 셋은 실측값으로의 정정이다 (§10.1③).

### 4.1 왜 프로덕션을 바꾸지 않는 쪽을 골랐는가

가능한 최소 변경안을 셋 비교했다.

| 안 | 내용 | 판단 |
| --- | --- | --- |
| ① `rulebook_facts` 에 "제약 상수 없음 → `TRUE`" 유도 추가 | 수준 3 이 열린다 | 🔴 **기각** — §3.5. 룰북 근거가 없다. 근거 없는 허용이다 |
| ② 자기 묘지행 유발 → `TRUE` 유도 추가 (818장) | 수준 3 이 열린다 (스크래치로 확인) | ⏸ **보류** — 사용자 결정. 근거는 있지만 범위 검증이 다음 Phase 몫 |
| ③ 프로덕션 무변경 + 원인·경계·막힌 자리 고정 | 수준 1 달성, 2·3 은 BLOCKER | ✅ **채택** |

채택안에 ②의 **근거**는 테스트로 남겼다 — 등록소 **사본**에 사실 한 줄을
넣으면 같은 프로덕션 경로가 `RESOLVED` 까지 간다 (`test_i01`), 그리고 원본
등록소는 19건 그대로다 (`test_i02`). 다음 Phase 가 ②를 집을 때 이 두 시험이
출발점이다.

②를 보류한 쪽이 안전한 이유: 818장의 유도는 `rulebook_facts` 의 **답 범위를
넓히는** 변경이고, 그 함수는 지금 통상 몬스터만 답한다. 그 경계를 넓히면
`MAY_BE_RETURNED_TO_HAND` · `MAY_BE_DISCARDED` 등 **다섯 질문**이 같은
레지스트리를 공유하므로 영향 범위가 묘지 하나로 끝나지 않는다. 823개 전체에
대한 거짓 양성 검사와 질문별 분리가 선행되어야 한다 (§13).

---

## 5. 후보 생성 전후 비교

🔴 **정직하게 적는다 — 후보 생성은 이미 되고 있었다.** Phase 지시서가
`STRUCTURAL-125` 를 "덱 선택 정보가 부족해 후보를 평가할 수 없음" 으로
요약했지만, 실제로 부족한 것은 정보가 아니었다. 그 요약이 맞는 범위는
`legal_actions` 다리(`target_combinations`)이고, `looked_at` 을 연 **규칙
내부 경로**에서는 후보가 처음부터 정확히 생성됐다.

| 경로 | 6-V 시점 | 6-W 측정 | 바뀐 것 |
| --- | --- | --- | --- |
| `TargetResolver(granted).candidates(spec, ctx)` (`looked_at={DECK}`) | 측정 안 됨 | **35건, 정확** | 측정만 |
| `target_combinations(...)` (`legal_actions` 다리) | `[]` | `[]` | 없음 (경계가 옳다) |
| `legal_actions(MINE)` 의 `activate_effect` | 없음 | 없음 | 없음 |
| `MAY_BE_SENT_TO_GRAVE` | 미측정 | **35/35 `UNKNOWN`** | 측정만 |

### 5.1 §7 의 15개 시나리오 대조

| # | 시나리오 | 결과 |
| --- | --- | --- |
| 1 | 기르수 소환 → 발동 → 해결 | 소환 ✅ · 발동 ✅ · 해결 ❌ (`UNCHECKED_RULES`) — `test_g01` |
| 2 | 적법한 오르페골 카드 선택 | ✅ `test_b01` |
| 3 | 적법한 성유물 카드 선택 | ✅ `test_b01` (두 카드군 모두 후보) |
| 4 | 다른 카드군의 잘못된 선택 방지 | ✅ 거짓 양성 **0건** — `test_b02` |
| 5 | 덱에 해당 카드가 없는 상황 | ✅ 후보 `()`, 발동 조건은 참 — `test_b03` |
| 6 | 동일 카드 여러 장 | ✅ 서로 다른 `InstanceId` — `test_b04` |
| 7 | 이동할 수 없는 카드의 정상 거절 | ❌ **못 한다** — B 가 `FALSE` 가 아니라 `UNKNOWN` (`test_f01`) |
| 8 | 확인 불가 시 `UNKNOWN` | ✅ 유지한다 (그리고 그것이 7의 이유다) |
| 9 | 효과 vs 비용 구분 | ✅ `test_d02` |
| 10 | 묘지행 대체 효과 | ✅ 구분해 둔다 · 미판정으로 명시 — `test_d03` |
| 11 | 체인 해결 이전 비이동 | ✅ `test_g02` |
| 12 | 이동 후 GameState·Journal 일관성 | 프로덕션 경로에서는 ❌ 이동이 없다 (`test_g02`). 사실 한 줄을 등록소 사본에 넣으면 ✅ 일관되게 움직인다 (`test_i01`) |
| 13 | 잘못된 인스턴스 이동 방지 | ✅ 아무것도 이동하지 않는다 |
| 14 | 효과 중복 해결 방지 | — 해결에 도달하지 못해 측정 불가 |
| 15 | 같은 구조 다른 카드의 공통성 | ✅ 어리석은 매장이 **같은 자리**에서 멈춘다 — `test_h01` |

---

## 6. 거짓 양성 및 거짓 음성 검사

### 6.1 후보 생성 — 거짓 양성 **0건**

```
후보 카드 종류 수: 35
후보 중 풀 밖 카드(거짓 양성): []
```

후보 전수를 `matches_setcode` 로 독립 재계산한 집합과 대조했다. 오르페골/
성유물이 **아닌** 카드가 후보에 든 경우는 0건이다 (`test_b02`).

### 6.2 거짓 음성 검사

| 검사 | 결과 |
| --- | --- |
| 오르페골 **또는** 성유물 양쪽이 모두 후보가 되는가 | ✅ 둘 다 (`test_b01`) |
| 기르수 자신의 덱 사본도 적법한가 | 6-V 가 확인했다 (기르수도 `0x11b` 카드다). **이번 풀은 기르수를 일부러 제외**해서 만들었으므로 여기서 다시 재지 않았다 |
| 카드군 카드가 없는 덱에서 후보가 생기는가 | 0건 — 그리고 발동 조건(덱 장수)은 참 (`test_b03`) |
| 같은 이름 3장이 1건으로 합쳐지는가 | 합쳐지지 않는다 — 3개의 `InstanceId` (`test_b04`) |

### 6.3 제약 상수 측정의 거짓 양성

§3.2 의 경고가 바로 이 항목이다. 부분 문자열 매칭은 `..._CB` · `..._AS_COST`
를 상위 상수로 **오계수**한다. `test_d01` 이 단어 경계로 두 경로(분석 계층 ·
원본 `c*.lua`)의 집합 동일성을 고정하므로 같은 실수가 반복되지 않는다.

### 6.4 🔴 범위 거짓 양성 — 255장을 "막는다" 로 적지 않았다

`EFFECT_LEAVE_FIELD_REDIRECT` 는 255장이 쓰는 큰 상수지만 말하는 자리가
**필드를 떠날 때**다. 기르수가 보내는 카드는 **덱**에 있으므로 해당하지
않는다. 범위를 가르지 않으면 "255장이 막힌다" 는 거짓 보고가 된다
(`test_d04`).

---

## 7. 실제 Duel 기르수 효과 발동·해결

프로덕션 경로만 썼다.

```
build_opening → Duel.legal_actions(MINE)
  → PlayerActionKind.NORMAL_SUMMON (기르수)        ✅ accepted
  → MonsterSummoned / MONSTER_SUMMONED             ✅ (6-V)
  → TriggerRegistry → 후보 생성 → 발동 가능         ✅ (6-V)
  → EffectActivator.activate(...)                  ✅ activated · 체인 1
  → ChainResolver.resolve_top(...)                 ❌ UNCHECKED_RULES
```

실측 (`test_g01`):

```
고른 카드: 14604710
발동: activated | 체인 길이: 1
해결 상태: UNCHECKED_RULES
해결 이유: #0 를 묘지로 보낼 수 있는지 판정할 수 없습니다: 이 카드를
          묘지로 보낼 수 있는가 (Card.IsAbleToGrave) · 묘지 대신 다른 곳으로
          가는가 (펜듈럼 · 토큰 · 대체 효과). 판정할 수 없는 것을 허가로
          바꾸지 않습니다.
```

🔴 **발동 성공과 해결 성공을 갈라 적는다** (§3 · §6). 발동은 실제로 성공
했고, 체인에 링크가 하나 쌓였다. 해결은 관문에서 멈췄다.

`legal_actions` 를 통한 자율 발동은 여전히 제공되지 않는다 —
`activate_effect` 가 후보에 없고, 제공되는 것은 `end_phase` 다 (`test_g03`).
위 발동은 테스트가 `EffectActivator` 를 **직접** 호출한 것이고, 그 사실을
보고서와 테스트 양쪽에 적는다.

---

## 8. 덱→묘지 이동 및 GameState 변화

🔴 **아무것도 움직이지 않았다.** 네 축을 전부 쟀다 (`test_g02`).

| 축 | 발동 전 | 발동 후 | 막힌 해결 후 |
| --- | --- | --- | --- |
| 덱 장수 | 35 | **35** | **35** |
| 묘지 장수 | 0 | **0** | **0** |
| 고른 인스턴스의 존 | `DECK` | **`DECK`** | **`DECK`** |

§6 의 최소 성공 기준 대조:

| 기준 | 결과 |
| --- | --- |
| 기르수 효과가 적법하게 발동 | ✅ |
| 덱에 존재하는 올바른 카드 선택 | ✅ (35 후보, 거짓 양성 0) |
| 그 카드의 묘지 이동 가능성 확인 | ❌ `UNKNOWN` |
| 실제 Deck → Graveyard 이동 | ❌ |
| 덱 카드 수 1 감소 | ❌ (35 → 35) |
| 묘지 카드 수 1 증가 | ❌ (0 → 0) |
| 정확한 `CardInstance` 보존 | ✅ (이동이 없으므로 보존된다) |
| `EventJournal` 에 실제 결과 기록 | ❌ (빈 목록) |

🔴 **덱에 적법한 카드가 없을 때 임의로 카드를 만들지 않았다** (§6). 그
상황은 후보 `()` 로 끝난다 (`test_b03`).

---

## 9. EventJournal 검증

```python
assert list(journal) == []
```

멈춘 해결은 사건을 적지 않는다. 이것이 **올바른 동작**이다 — 실행되지 않은
이동이 기록에 남으면 기록이 판과 어긋난다.

🔴 **이 Phase 는 `EventJournal` 에 쓰인 `ZoneMoved` 를 하나도 보지 못했다.**
스크래치에서는 봤지만 프로덕션 경로가 아니므로 §9 의 검증으로 세지 않는다
(§3.6).

---

## 10. 기존 기능 회귀

프로덕션 무변경이므로 구조적 회귀 위험은 **신규 테스트 파일이 저장소 감사에
미치는 영향**이다. 그 영향을 받는 감사를 grep 으로 특정했다 — 테스트 트리를
`rglob` 로 훑는 루트 감사 **28개**다 (`glob("test_*.py")` 만 쓰는 감사는
`tests/` 최상위만 보므로 영향 없음).

그리고 그 묶음이 **실패 3건을 잡았다.** 셋 다 이전 Phase 때부터 깨져 있던
것이고 (§10.1), 고치는 과정에서 루트 테스트 7파일을 손봤다. `tests/engine`
과 `tests/agent` 에는 테스트 트리를 훑는 시험이 없으므로 (`grep` 로 확인)
그 변경이 ②·③ 결과를 무효화하지 않는다.

| 단계 | 무엇을 | 결과 |
| --- | --- | --- |
| ① 변경 모듈 타깃 | 6파일 (새 파일 + 선택·묘지·소환 경로) | **225 passed** |
| ② Duel 수직 통합 + Discord | 10파일 | **492 passed** |
| ③ 관련 엔진 전체 | `tests/engine` | **3,576 passed** |
| ④ 테스트 트리를 훑는 루트 감사 | 28파일 | 1차 **3 failed** → 고친 뒤 §11 |

### 10.1 🔴 루트 감사 3건이 깨져 있었다 — 전부 **이전 Phase 의 것**이다

28파일 묶음이 실패 3건을 잡았다. **셋 다 6-W 가 만든 것이 아니다.** 6-W
시작 지점(`1f05b00`)의 worktree 를 따로 만들어 같은 셋을 돌렸고 **같은
자리에서 같은 값으로** 실패했다.

```
$ git worktree add --detach <scratch>/wt-1f05b00 1f05b00
$ cd <scratch>/wt-1f05b00 && pytest <그 세 시험>
FAILED tests/test_korean_overlay_display_boundary_audit.py::test_21_...
FAILED tests/test_korean_overlay_return_value_audit.py::test_11_...
FAILED tests/test_rule_not_implemented_code_audit.py::test_02_...
3 failed in 7.45s
```

| # | 감사 | 원인 Phase | 무엇이 틀렸는가 | 고친 것 |
| --- | --- | --- | --- | --- |
| 1 | `test_korean_overlay_display_boundary_audit::test_21` | **6-U** (`ea13577`) | `tests/engine/test_normal_summon.py` 59 → 60 | **측정 방법** |
| 2 | `test_korean_overlay_return_value_audit::test_11` | **6-T** (`d7ee8c9`) | `deck/` 이 `PRODUCTION_DIRS` 에 없다 | **분모** |
| 3 | `test_rule_not_implemented_code_audit::test_02` | **6-V** (`1f05b00`) | 문자열 87 → 88 · 코드 72 → 73 · 산문 줄번호 6개 이동 | **센서스 값** |

#### ① `test_21` — **진술은 참이었고 측정이 틀렸다**

그 감사의 진술은 "Phase 3-F-44 가 기존 테스트를 수정·삭제하지 않았다" 다.
3-F-44 의 commit 세 개가 건드린 파일을 전수 확인했다.

```
cdeaf7a  docs/phase3f44-korean-overlay-display-boundary-audit.md
ed3ea4c  docs/phase3f44-korean-overlay-display-boundary-audit.md
ee12991  tests/test_korean_overlay_display_boundary_audit.py   ← 자기 파일
```

**기존 테스트를 하나도 건드리지 않았다 — 진술은 참이다.** 그런데 시험은
`counts(base)` 와 `counts("HEAD")` 를 비교했다. 그러면 뜻이 "3-F-44 가
건드리지 않았다" 에서 "3-F-44 **이후** 아무도 건드리지 않았다" 로 바뀐다.

🔴 **그 실수를 이 저장소가 이미 적어 두었다.** 바로 위 `test_20` 의 주석이
Phase 4-B 가 두 번에 걸쳐 같은 것을 정정한 기록이다 — 그런데 `test_21` 만
고치지 않고 남아 있었다. 6-U 가 시험 하나를 더하자 터졌다.

고친 방법은 `test_20` · `_changed_files()` 와 같다 — **commit 하나하나**가
건드린 테스트 파일을 보고, 그 commit 의 부모에 이미 있던 파일을 건드렸으면
실패다. **시험 수가 같아도 실패**이므로 옛 비교보다 더 엄격하다.

#### ② `test_11` — 분모에 `deck/` 이 없었다

`PRODUCTION_DIRS` 에 `deck` 이 없어서 `deck/opening.py` 의 `.apply(...)`
세 자리가 production 도 tests 도 아닌 것으로 남았고, 전수 분류
(`len(prod) + len(tests) == len(rows)`) 가 깨졌다. `deck/` 은 Phase 6-T 가
만든 production 디렉터리다 (`d7ee8c9`).

그 세 자리는 반환값을 **버리지 않으므로** "버리는 자리는 production 에
하나" 라는 진술 자체는 참이었다. **분모만 틀렸다.** `deck` 을 더했다.

🔴 **같은 누락이 다섯 감사에 더 있었다.** 거기서는 `PRODUCTION_DIRS` 가
"이 Phase 가 production 을 바꾸지 않았다" 의 접두 필터로만 쓰여 실패하지
않았지만, `deck/` 을 건드린 Phase 가 **거짓으로 통과한다.** 다섯 곳에도
더했고, 실제로 깨지는 것이 없음을 돌려서 확인했다 (§11).
`test_event_phase_semantics_audit.py` 는 목록이 `("engine", "agent")` 로
의도적으로 좁으므로 **건드리지 않았다** — 거기에 `deck` 을 더하면 그 감사가
훑는 범위 자체가 바뀐다.

#### ③ `test_02` — 6-V 의 프로덕션 변경이 센서스를 움직였다

6-V 가 `engine/trigger.py` 에 `_zone_from_summon` 관문을 넣으면서
`ValidationCode.RULE_NOT_IMPLEMENTED` **코드 자리 하나**가 늘었다
(19 → 20). 6-V 의 51파일 묶음에 이 감사가 없어서 넘어갔다.

```
$ for ref in 73f1d8a 1f05b00; do git show $ref:engine/trigger.py | grep -c RULE_NOT_IMPLEMENTED; done
19
20
```

| 상수 | 전 | 후 | 종류 |
| --- | --- | --- | --- |
| `STRING_OCCURRENCES` | 87 | **88** | 문자열 전수 |
| `CODE_OCCURRENCES` | 72 | **73** | **코드 자리** (판이 아니라 코드가 생겨야 풀리는 모름) |
| `PROSE_OCCURRENCES` | 15 | **15** (줄번호 6개 이동) | 산문 — **수는 그대로** |

산문 줄번호는 6-V 의 삽입만큼 밀렸다: `743→775` · `771→803` ·
`1337→1369` (+32), `1696→1741` · `1702→1747` · `1725→1770` (+45).

🔴 **이 핀이 줄 번호를 세는 이유가 그것이다** — 이동이 반드시 드러나야
한다. 수를 줄이거나 핀을 지우지 않고 **움직인 자리를 실측해 적었다.**

### 10.2 `deck` 을 더하면서 건드린 파일의 기존 실패 4건 — **데이터 판본 의존**

`PRODUCTION_DIRS` 에 `deck` 을 더하려고 `tests/test_korean_overlay_unapplied_audit.py`
를 건드렸으므로 그 파일 전체를 돌렸고, 실패 4건이 나왔다. **내 변경 때문이
아니다** — 변경을 `git stash` 로 치우고 같은 4건이 같은 값으로 실패한다.

원인은 **로컬 카드 데이터베이스의 판본**이다.

| 측정 | 핀 (Phase 3-F-43-K0 가 적음) | 지금 이 컨테이너 |
| --- | --- | --- |
| `cards.cdb` 의 `texts` 행 수 | 14,755 | **14,759** |
| `OfficialDatabaseSource.load()` | 14,514 | **14,518** |
| `repo._cards` | 14,520 | **14,524** |
| `canonical` (정규 카드) | 14,127 | **14,127** ✅ |

`data/cards.cdb` 는 `.gitignore:3` 에 있어 **저장소가 추적하지 않는다** —
`python -m scripts.fetch_official_db` 로 내려받는 파일이고, 그 사이 공식
DB 가 4행 늘었다. 정규 카드 수는 그대로이므로 늘어난 넷은 alias · 토큰
쪽에서 걸러진다.

🔴 **이 네 건은 6-U 보고서 §13 이 기록한 `test_27` · `test_29` 와 같은
종류다** (데이터·환경 의존). 사용자 지시에 따라 **삭제·skip·assertion
완화를 하지 않았고**, 공식 데이터의 완전성이 검증됐다는 주장과 구분해
여기 기록만 한다. 이 Phase 의 소환·선택·묘지 판정과는 무관하다.

### 10.3 6-V 의 기존 실패 2건 — 신규 회귀가 아니다

두 건은 **28파일 묶음에 들어 있지 않다** (`tests/agent/...` 는 다른 트리이고,
`test_event_free_chain_semantic_audit.py` 는 묶음에 든 복수형
`..._semantics_audit.py` 와 **다른 파일**이다). 그래서 따로 지명해 돌렸다.

```
tests/agent/test_opponent_resource_weighting_audit.py
    ::test_07_a_whole_duel_never_offers_a_choice_about_opponent_resources
        AssertionError: [1, 1, 1, 1, 1, 1, ...]
tests/test_event_free_chain_semantic_audit.py
    ::test_27_the_official_corpus_never_uses_the_term
        AssertionError: 15   (assert 15 >= 600)
2 failed in 3.34s   ·   exit 1
```

🔴 **6-V 가 기록한 값과 같다** (`[1, 1, 1, ...]` · `15`). 이 실행 시점의
작업 트리는 추적 파일 변경이 **0건**이었다 (새 테스트 파일과 보고서만
untracked). 이후 §10.1 의 루트 감사 7파일을 손봤지만 **그 일곱 전부
`tests/` 안**이고, 두 실패가 보는 것은 에이전트 시뮬레이션과 재정 캐시이므로
무관하다.

원인은 6-U 보고서 §13 · §18-2 가 이미 적어 두었다 (에이전트 상대 자원
한계 주장 · `data/rulings/.cache` 부재). **고치지도, 완화하지도, skip
하지도 않았다.**

---

## 11. 테스트 통과·실패·시간

§8 의 위험 기반 순서를 그대로 따랐다. **모든 단계 exit 0.**

| 단계 | 명령어 | 통과 | 실패 | 건너뜀 | 시간 | exit |
| --- | --- | --- | --- | --- | --- | --- |
| ① 변경 모듈 타깃 | `pytest tests/engine/test_deck_to_grave_blocker.py tests/engine/test_target_bridge.py tests/engine/test_multi_target_selection.py tests/engine/test_rule_gate_grave_discard.py tests/engine/test_summon_trigger_execution.py tests/engine/test_effect_activation_path.py` | **227** | **0** | 0 | 43.95s | **0** |
| ② Duel 수직 통합 + Discord | `pytest tests/test_opening_duel_integration.py tests/engine/test_trigger_duel_integration.py tests/engine/test_action_legality.py tests/engine/test_legal_action_candidate_consistency.py tests/engine/test_chain.py tests/engine/test_chain_response.py tests/engine/test_trigger_chain.py tests/engine/test_trap_activation_free_chain.py tests/engine/test_card_definition_view.py tests/engine/test_archetype_condition.py tests/test_discord_bot.py` | **492** | **0** | 0 | 56.80s | **0** |
| ③ 관련 엔진 전체 | `pytest tests/engine` | **3,578** | **0** | 0 | 333.40s (5:33) | **0** |
| ④ 테스트 트리 감사 28파일 | `pytest <rootset 28파일>` | **758** | **0** | 4 | 604.21s (10:04) | **0** |

모두 `-p no:randomly -q --no-header --tb=short` 로 돌렸다.

### 11.1 수가 맞는가

| 비교 | 6-V | 6-W | 차이 |
| --- | --- | --- | --- |
| `tests/engine` | 3,553 | **3,578** | **+25** — 새 파일 전부 |
| ④ 28파일 | 762 수집 / 3 failed | **758 passed + 4 skipped** | 실패 3건 **해소** |

🔴 **새 파일의 25건이 그대로 더해졌고, 기존 수가 줄지 않았다** — 삭제도
skip 도 없었다는 뜻이다.

### 11.2 고치기 전후

| | 1차 (고치기 전) | 최종 |
| --- | --- | --- |
| ④ 28파일 | 3 failed · 755 passed · 4 skipped · 633.12s | **0 failed · 758 passed · 4 skipped · 604.21s** |

### 11.3 범위 밖에서 확인한 기존 실패 (고치지 않았다)

| 명령어 | 결과 | 분류 |
| --- | --- | --- |
| `pytest tests/agent/test_opponent_resource_weighting_audit.py::test_07_... tests/test_event_free_chain_semantic_audit.py::test_27_...` | 2 failed · exit 1 | 6-V 가 기록한 기존 실패 (§10.3) |
| `pytest tests/test_korean_overlay_unapplied_audit.py` | 4 failed · 30 passed · 4 skipped | 로컬 `cards.cdb` 판본 의존 (§10.2) |

🔴 **여섯 건 모두 삭제·skip·완화 없이 그대로 두고 원인만 기록했다.**
6-W 의 소환·선택·묘지 판정과 무관함을 각각 증명했다 (§10.2 · §10.3).

### 11.4 테스트 정책 — 금지 사항 점검

- 기존 테스트 **삭제 0건** · **skip 추가 0건** · **assertion 완화 0건** ·
  **threshold 완화 0건**.
- `test_21` 은 **더 엄격해졌다** (시험 수가 같아도 실패).
- `PRODUCTION_DIRS` 에 `deck` 추가는 검사 범위를 **넓힌다**.
- 센서스 3개는 실측값으로의 **정정**이다 (§10.1③).
- 🔴 **실제로 실행하지 않은 것을 성공으로 적지 않았다.** F·G 묶음 8건이
  "여기서 멈춘다 · 판이 변하지 않는다" 를 단언으로 적고, `test_i01` 의
  `RESOLVED` 는 등록소 **사본**이라는 사실을 docstring 과 `test_i02` 가
  함께 못박는다.

---

## 12. 남아 있는 구조적 BLOCKER

| ID | 내용 | 이번 Phase |
| --- | --- | --- |
| **BLOCKER-6W-1** | `MAY_BE_SENT_TO_GRAVE` 의 사실 출처가 **둘**인데 묘지 질문에 대해서는 양쪽이 **룰북 한 줄**로 수렴한다 (등록소 19건 중 답하는 1건도 통상 몬스터). 통상 몬스터가 아닌 모든 카드는 `UNKNOWN` 이다 | 원인 확정 · 고치지 않음 (룰북 근거 없음 — §3.5) |
| **BLOCKER-6W-2** | `EFFECT_CANNOT_TO_GRAVE` 3장이 있는데도 **B 를 `FALSE` 로 답하지 못한다.** 레지스트리에 그 세 장의 사실이 없다 | 측정 · 고치지 않음 |
| **BLOCKER-6W-3** | 묘지행 **대체 효과** (`REDIRECT` 31 + `REDIRECT_CB` 16)를 판정이 보지 않는다. 해결 이유 문장이 미판정으로 명시한다 | 측정 · 범위 확정 |
| `STRUCTURAL-125` | 해결 시점 선택이 `PlayerAction` 에 들어갈 수 없다. **경계가 옳고**, 고칠 것은 선택 시점 계약이다 | 범주 오류임을 확정 |
| `STRUCTURAL-7` | 분석 → 정의 컴파일러가 없다. 기르수 정의는 손으로 적혔다 (`EFFECT_LIBRARY` 18건 · `OPERATION_RULINGS` 19건) | 그대로 |
| `ADR-006` | 정의와 실행 가능은 다르다 | 그대로 |
| **BLOCKER-6W-4** | 🔴 **루트 감사의 사각지대.** 세 감사가 이전 Phase 때부터 깨져 있었는데 그 Phase 들의 "영향 파일" 묶음에 들어 있지 않아 넘어갔다. 영향 파일을 grep 으로 특정하는 방식은 **센서스를 가진 감사**를 놓친다 | 셋 다 고쳤다 · 방식의 한계는 남는다 (§13.4) |

---

## 13. 다음 최소 단계 추천

**13.1 (권장) `MAY_BE_SENT_TO_GRAVE` 만 여는 유도 — 질문 하나로 좁혀서**

자기 묘지행 유발 818장에 대해 `RuleFact(TRUE, RuleBasis.CARD_TEXT)` 를
유도한다. 선행 조건 세 가지:

1. `rulebook_facts` 의 **다섯 질문 공유**를 깨지 않도록, 묘지 질문만 답하는
   별도 유도 함수로 분리한다 (다른 네 질문은 `UNKNOWN` 유지).
2. 818장 전수에 대한 공식 텍스트 역검증 — 6-U 가 4,028장에 한 것과 같은
   방식 (여덟 어구). `EFFECT_CANNOT_TO_GRAVE` 와 모순 0건은 이미 확인했다.
3. `EFFECT_TO_GRAVE_REDIRECT` 보유 카드가 판에 있을 때는 `TRUE` 를 주지
   않는다 — `_interference` 가 이미 그 모양의 질문을 받는 자리다.

이 단계만으로 성유물－『성장』 한 장이 열리고 수준 3 이 달성된다. **해결
경로 쪽은 이미 증명됐다** — 사실 한 줄을 등록소 사본에 넣자
`RESOLVED` · 덱 35→34 · 묘지 0→1 · `#34 P0/DECK → P0/GRAVE
(send_to_grave)` 가 나왔다 (§3.6). 남은 일은 **그 한 줄을 818장에 대해
유도해도 되는지**를 데이터로 입증하는 것이다.

**13.2 `EFFECT_CANNOT_TO_GRAVE` 3장을 `FALSE` 로 적는다**

3장뿐이므로 `OPERATION_RULINGS` 에 손으로 적을 수 있다. 이것은 **허가가
아니라 금지**이므로 근거 부담이 가볍다 — 카드 자신의 상수가 근거다. §7-7
("이동할 수 없는 카드의 정상 거절")이 이것으로 열린다.

**13.3 해결 시점 선택 계약 (`STRUCTURAL-125` 의 올바른 해법)**

`PlayerAction` 에 덱 인스턴스를 적는 대신, 해결 중에 선택을 요청하는
계약이 필요하다. 이것은 공유 계약 변경이므로 **별도 Phase 와 사용자 승인**
대상이다.

**13.4 센서스 감사 목록을 만든다 (`BLOCKER-6W-4`)**

이 Phase 가 셋을 고쳤지만 원인은 방식이다 — 영향 파일을 grep 으로 좁히면
**프로덕션의 특정 토큰 수를 세는 감사**가 빠진다. 그 감사들은 바뀐 모듈
이름을 본문에 적지 않기 때문이다 (`STRING_OCCURRENCES` 는
`engine/trigger.py` 를 언급하지 않는다).

최소 단계: 센서스 상수를 가진 루트 감사 목록을 한 번 뽑아
`tests/` 안의 고정 목록으로 두고, 프로덕션을 건드리는 Phase 가 **그 목록을
항상 함께 돌린다.** 전체 루트(1시간+) 를 반복하는 것보다 싸고, 이번처럼
세 Phase 를 건너 쌓이는 것을 막는다.

---

## 14. Git 커밋·푸시 결과

브랜치 `claude/pensive-goodall-te1egy` · 시작 지점 `1f05b00`.

| # | 커밋 | 내용 |
| --- | --- | --- |
| 1 | `9cd4d82` | **Phase 6-W**: 덱→묘지 경로가 멈추는 자리를 측정하고 고정한다 (새 테스트 23건, A–H) |
| 2 | `be8fd5f` | **Phase 6-W**: 이전 Phase 때부터 깨져 있던 루트 감사 3건을 고친다 (루트 테스트 7파일) |
| 3 | `6d0728e` | **Phase 6-W**: 막는 것이 판정 사실 하나임을 테스트로 고정한다 (`test_i01` · `test_i02`) |
| 4 | (아래) | **Phase 6-W 보고서** |

🔴 **프로덕션 파일은 하나도 커밋에 들어 있지 않다.** 네 커밋이 건드린
것은 `tests/` 와 `docs/` 뿐이다.

푸시: `git push -u origin claude/pensive-goodall-te1egy`

(§PUSH_RESULT)
