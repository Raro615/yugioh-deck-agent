# Phase 3-F-25 — `EVENT_FREE_CHAIN` 의미 확정 감사

> 공식 "Free Chain" ↔ Lua `EVENT_*` 대응 조사 · **조사 전용 + docstring 정정 2건**

---

## 0. 실제 HEAD / Base — `git` 으로 검증

지정 SHA 는 참고값이라 하셨으므로 작업 전에 실제 상태를 확인했다.

| 항목 | 지정값 | 실제 확인 | 결과 |
|---|---|---|---|
| 3-F-24 작업 commit | `d405f2f` | `d405f2f` Phase 3-F-24: audit activation precondition contract | ✅ |
| 3-F-24 보고서 commit | `f84a47a` | `f84a47a` Phase 3-F-24: document activation precondition audit | ✅ |
| 작업 시작 HEAD | — | `f84a47a` (= 3-F-24 보고서) | ✅ |
| worktree | — | `git status --short` 출력 없음 · `git diff --stat` 없음 | ✅ clean |
| branch | — | `claude/pensive-goodall-te1egy` | ✅ |
| `origin` 동기 | — | `HEAD == origin/claude/pensive-goodall-te1egy` | ✅ |

기존 commit rewrite 없음.

---

## 1. 🔴 먼저 — 측정의 **한계**를 숨기지 않는다

이 Phase 의 가장 중요한 결과는 **공식 정의를 확정하지 못했다**는 것이다.
그것을 먼저 적는다.

### 저장소의 공식 자료 — 측정 완료

| 자료 | 크기 | "Free Chain" 출현 |
|---|---|---|
| `data/rules/documents/sd-rulebook-en-v10.json` (룰북 원문 추출) | 118,046자 | **0** |
| `data/rules/structured/sd-rulebook-en-v10.json` (구조화본) | 17,902자 | **0** |
| `data/rulings/` (공식 OCG 재정) | **686 파일** | **0** |
| `data/ko/ko-KR.json` (한국어 공식 DB) | — | **0** |

`Free`, `freely` 조차 룰북 원문에 **0회**다. 공식 룰북이 쓰는 말은
`Spell Speed` · `respond` · `Quick Effect` · `Counter Trap` 이다.

### 🔴 공식 DB 온라인 조회 — **판정 실패**

`db.yugioh-card.com/yugiohdb/faq_search.action` 으로 Q&A 전문 검색을
시도했다. **그 결과를 근거로 쓰지 않는다.** 이유:

1. 검색 폼의 `<select id="stype">` 에 `2 = 「Ｑ＆Ａテキスト」検索`(본문) ·
   `1 = 「カード名」検索`(카드명) 이 있지만, **URL 파라미터로는 `stype` 이
   먹지 않는다** — `stype=1`·`2`·`3` 이 전부 같은 결과를 낸다
   (`サイクロン` → 8행 동일).
2. 공식 용어인 `スペルスピード` 조차 **0건**이 나온다. 즉 **0건이 "없다" 를
   뜻하지 않는다.**
3. probe 자체는 살아 있다 — `サイクロン` 8행 · `強制脱出装置` 1행 ·
   존재하지 않는 이름 0행으로 검증했다. 작동하는 것은 **카드명 검색뿐**이다.

> 🔴 이 "probe 검증" 을 하지 않았다면 `フリーチェーン` 0건을 "공식 용어가
> 아니다" 의 증거로 **잘못 썼을 것이다.** 처음 세 번은 결과 행 추출
> 정규식(`fid=`)이 아예 틀려서 알려진 카드명도 0행이 나왔다.

사용자 지시에 따라 나무위키 · 비공식 위키 · Reddit · 블로그 · 커뮤니티
재정 · 모델의 기존 지식은 **근거로 쓰지 않았다.** 그래서 §2 의 공식 정의는
**UNKNOWN** 으로 남는다.

---

## 2. 공식 "Free Chain" 의 의미 — §2 의 A~E

공식 자료에서 확인되지 않는 부분은 지시대로 `UNKNOWN` 으로 남긴다.

### A. 공식 규칙에서 "Free Chain" 은 정확히 무엇인가?

> **UNKNOWN.** 이 저장소의 공식 자료 전체에 그 표현이 **없다**(§1). 공식
> 온라인 DB 로도 판정하지 못했다(§1). 추측하지 않는다.

### B. 다음 중 어느 것인가? (효과 종류 / activation timing / Chain 종류 / Spell Speed 관련 / 일반 개념 / 기타)

> **UNKNOWN.** 공식 정의가 없으니 분류할 수 없다.
>
> 🔴 다만 **"무엇이 아닌지" 는 데이터로 말할 수 있다.** 공식 Spell Speed 와
> 1:1 이 아니고 양 끝에서 **뒤집힌다**(§6). 그러므로 적어도
> *"Spell Speed 와 같은 개념"* 과 *"체인에 자유롭게 끼어들 수 있음"* 은
> Lua 상수의 분포와 **맞지 않는다.**

### C. "효과의 발동 조건" 인가, "현재 체인에서 대응 가능한가" 인가?

> **UNKNOWN**(공식 측). Lua 측에서는 **전자에 가깝다** — `SetCode` 는 효과
> 하나의 **유발 사건 칸**이고, 체인 상태를 보는 함수가 아니다(§5). 그러나
> 이것은 Lua 의 구조이고 공식 개념의 답이 아니다.

### D. Spell Speed 와 어떤 관계인가?

> 공식 측은 **UNKNOWN**. 저장소 측정으로는 **관계가 1:1 이 아니고 역방향이
> 섞여 있다**(§6 · §8). `engine` 의 Spell Speed 는 이 상수를 **읽지 않고**
> **카드 종류**에서 나온다(§6의 행동 증거).

### E. Trigger / Ignition / Quick Effect / Trap activation 과 어떤 관계인가?

> 공식 측은 **UNKNOWN**. Lua 측 분포는 명확하다(§5 · §6):
>
> | 공식 효과 분류 | Lua `effect_types` | FC 비율 |
> |---|---|---|
> | (카드 발동) | `ACTIVATE` | 3,642 / 4,305 = **84.6%** |
> | Quick Effect (유발즉시) | `QUICK_O` | 1,257 / 1,875 = **67.0%** |
> | Ignition Effect (기동) | `IGNITION` | 58 / 4,180 = **1.4%** |
> | Trigger Effect (유발) | `TRIGGER_O` | **0** / 6,088 |
> | Flip Effect (리버스) | `TRIGGER_F` | **0** / 1,972 |
>
> 🔴 공식 Ignition Effect 는 **유발 사건이 없는 발동**이다(룰북:
> `activation_timing: "your Main Phase"` · `has_activation: true`). 그런데
> FC 를 거의 쓰지 않는다 — **98.5%가 `SetCode` 를 아예 부르지 않는다.**
> 이것이 이 Phase 가 정정한 핵심이다(§15).

---

## 3. `EVENT_FREE_CHAIN` corpus 통계 — §3

### 단위를 먼저 고정한다

> 🔴 3-F-24 는 **카드 단위**로 셌고 이 Phase 는 **스크립트 단위**를 기준으로
> 쓴다. 스크립트 하나가 여러 패스코드에 붙기 때문에 수가 다르다. **오류가
> 아니라 단위 차이다** — 3-F-24 의 수치(EVENT 16,727 · EFFECT 14,044 ·
> coded 30,771 · 298종)를 카드 단위로 **정확히 재현**해 확인했다.

| 단위 | 모집단 | 전체 블록 | `code is None` | `EVENT_*` | `EFFECT_*` | 상수 종류 |
|---|---|---|---|---|---|---|
| **스크립트** | 12,702 | 34,680 | 4,554 | 16,398 (70종) | 13,728 (228종) | **298** |
| 카드 | 12,968 (전체 14,520) | 35,385 | 4,614 | 16,727 (70종) | 14,044 (228종) | **298** |

`load()` 와 `load_cached()` 가 **완전히 일치**한다 (캐시 신뢰 확인).

### `EVENT_FREE_CHAIN` 자체

| 측정 | 스크립트 단위 | 카드 단위 |
|---|---|---|
| 전체 등장 블록 | **4,914** | 5,002 |
| 고유 보유자 | **4,488** 스크립트 | 4,574 카드 |
| 고유 `EffectSpec` | 4,914 (= 블록 수) | 5,002 |
| 전체 블록 중 비중 | **14.2%** | 14.1% |

**최다 상수이지만 과반이 아니다.**

### 🔴 `EffectSpec.index` 는 고유하지 않다

| 측정 | 값 |
|---|---|
| `index` 가 중복되는 스크립트 | **4,795** |
| 중복 블록 수 | **6,802** |
| `CreateEffect` 중 `initial_effect` **밖** | 7,469 / 32,150 = **23.2%** |

파서는 `CreateEffect` 를 만날 때마다 **새 `EffectSpec` 을 append** 한다
(덮어쓰지 않는다 — 코드와 주석이 그렇게 적는다). 그래서 같은 Lua 변수명이
여러 함수에서 재사용되면 같은 `index` 를 가진 spec 이 여럿 생긴다.

> 🔴 측정 중 한 번 틀렸다. 유언장(`85602018`)의 `e1` 이 두 번 나오는 것을
> 보고 *"parser 가 진짜 `e1` 을 덮어썼다"* 고 적었다. **아니다** —
> `info.effects` 에 **둘 다** 들어 있다. parser 를 읽지 않고 결과만 보고
> 단정했다. `(card_id, index)` 를 키로 쓰면 조용히 합쳐지므로, 이 Phase 는
> **블록을 세고 키로 쓰지 않는다**(`test_16`).

### `EffectSpec.code` 에 저장되는 **정확한 형태**

문자열 `"EVENT_FREE_CHAIN"` — **접두사를 포함한 상수 이름**이다. 파서가
정규식으로 접두사를 뗀 뒤 `f"EVENT_{...}"` 로 **다시 붙인다**. 숫자
`1002` 를 담는 칸은 `EffectSpec` 에 **없다**(`test_03`).

### `constant.lua` 의 정의

```lua
--Events
EVENT_STARTUP              = 1000
EVENT_FLIP                 = 1001
EVENT_FREE_CHAIN           = 1002      ← 여기
EVENT_DESTROY              = 1010
EVENT_REMOVE               = 1011
```

`--Events` 블록의 **낮은 번호대**(1000~1002)에 있고 실제 사건 코드는 1010
부터다. `EVENT_` 정의 줄 74개 중 우변이 순수 10진수인 것이 67개다(나머지
7개는 16진 플래그 `EVENT_PHASE = 0x1000` 등과 deprecated 두 줄).

> 🔴 이것은 **"그래서 의미가 무엇이다" 의 근거가 아니다.** 번호대가 같아
> 구문으로 가를 수 없다는 3-E-17 의 관찰을 숫자로 확인한 것뿐이다.
> **이름과 번호로 공식 의미를 추론하지 않는다.**

---

## 4. `EVENT_*` 전체 구조 — §7

`EVENT_FREE_CHAIN` 하나만 떼어 보면 위험하다는 §7 의 경고대로, 70종 전부를
같은 기준으로 쟀다.

| `EVENT_*` 상수 | 블록(카드 단위) | parser 저장 | production 코드 | engine/agent 코드 | trigger/event system |
|---|---|---|---|---|---|
| `EVENT_FREE_CHAIN` | 5,002 | ✅ | **0** | **0** | **0** |
| `EVENT_SPSUMMON_SUCCESS` | 2,166 | ✅ | **0** | **0** | **0** |
| `EVENT_PHASE` | 1,356 | ✅ | **0** | **0** | **0** |
| `EVENT_SUMMON_SUCCESS` | 1,281 | ✅ | **0** | **0** | **0** |
| `EVENT_TO_GRAVE` | 1,187 | ✅ | **0** | **0** | **0** |
| `EVENT_CHAINING` | 897 | ✅ | **0** | **0** | **0** |
| `EVENT_DESTROYED` | 593 | ✅ | **0** | **0** | **0** |
| `EVENT_ATTACK_ANNOUNCE` | 469 | ✅ | **0** | **0** | **0** |
| `EVENT_LEAVE_FIELD` | 335 | ✅ | **0** | **0** | **0** |
| … 나머지 61종 | — | ✅ | **0** | **0** | **0** |
| **합계 70종** | 16,727 | **70/70** | **0/70** | **0/70** | **0/70** |

문자열 리터럴을 **벗긴**(`ast.unparse` + `Constant` 비우기) production 코드
전체에서 **70종 어느 것도 한 번도 등장하지 않는다**(`test_05`).

> 🔴 **결론: `EVENT_FREE_CHAIN` 은 EVENT 체계 안에서 특별한 위치가 아니다.**
> 70종이 전부 동일하게 "저장되고, 분석되고, 실행되지 않는다."
> 공식 rule concept 과 직접 대응한다고 볼 근거는 **어느 상수에도 없다** —
> 대응을 주장할 수 있는 공식 측 자료가 없기 때문이다(§1).

주석/docstring 에 이름이 등장하는 production 파일은 넷뿐이다:
`core/card_model.py` · `analysis/effect_model.py` ·
`engine/action_validation.py` · `lua_parser_example.py`.
**등장이 소비가 아니라는 것**이 요점이다.

---

## 5. `EffectSpec` / `EffectDefinition` 경로 — §4 · §5

### 누가 쓰고 누가 읽는가 (받는 쪽 이름을 **정확히** 센다)

| 파일 | 역할 | §4 분류 |
|---|---|---|
| `sources/lua_loader.py` | `spec.code` **쓴다** + 캐시로 직렬화 | **A. 저장만 한다** |
| `analysis/effect_analyzer.py` | `spec.code` 9곳 읽음 → `trigger_event` / `effect_code` / `is_summon_procedure` | **B. 분석만 한다** |
| `core/card_model.py` | `has_effect_code()` · `can_self_special_summon_from_hand` | B |
| `core/card_search.py` | `has_effect_code(code)` 호출 — **검색 필터** | **C. production 에서 읽는다** (검색 계층) |
| `app/main.py` | CLI 표시 | C (표시) |
| **`engine/*` 전부** | — | **E. 이름만 존재하고 소비되지 않는다** |
| **`agent/*` 전부** | — | **E** |

> 🔴 3-F-24 가 받는 쪽을 `("spec","block","entry")` **부분 문자열**로 골랐다가
> `engine/activation.py` 의 `blocked.code` 를 잡았다 (`"block"` ⊂
> `"blocked"`). 그 `blocked` 는 `ActivationResult` 이고 `.code` 는
> `ValidationCode` 다. 이 Phase 는 받는 쪽 이름을 **정확히** 센다(`test_06`).

### `EffectDefinition` 으로는 **건너가지 않는다**

| 계층 | `code` 칸 |
|---|---|
| `EffectSpec` (파서) | ✅ **있다** |
| `EffectDefinition` (엔진 등재) | ❌ 없다 |
| `TriggerSpec` (유발 등록) | ❌ 없다 |
| `ChainLink` (6칸) | ❌ 없다 |
| `CardDefinitionView` (26칸) | ❌ 없다 — `effect_count`(개수)와 `setcodes`(카드군)뿐 |

> 🔴 즉 engine 은 이 값을 **"읽지 않는" 것이 아니라 볼 수조차 없다**
> (`test_07`). hidden-information 경계가 먼저 막는다.

### 실제 경로 둘 — **간선이 없다** (§5 의 D)

```
EVENT_FREE_CHAIN (Lua 원문)
  ↓  sources/lua_loader.py  parse_lua_source / _RE_SETTER "Code"
EffectSpec.code = "EVENT_FREE_CHAIN"
  ↓  analysis/effect_analyzer.py:374  spec.code.startswith("EVENT_")
EffectAnalysis.trigger_event
  ↓  core/card_search.py:323  has_effect_code(code)
검색 필터 결과
  ✗ 여기서 끝난다. engine 으로 가는 간선이 없다.


activation timing
  ↓  engine/activation_timing.py:201  classify_spell_speed(definition)
     — 읽는 속성: type_names · is_trap · is_spell · is_monster  (AST 측정)
SpellSpeedClassification(speed, basis, rules, missing)
  ↓  ActivationTimingChecker.check(timing, action)
ValidationResult
  ↓  engine/duel.py  Duel._activation_gate   (legal_actions · apply 공용)
허가 / 보류
  ✗ EffectSpec 을 만나지 않는다.
```

`trigger_event` 라는 이름은 `engine/` 전체 코드에 **0회**다(`test_10`).

### §5 의 A~D 답

| 질문 | 답 |
|---|---|
| A. 같은 의미인가? | **아니다.** 같은 FC 를 가진 두 카드가 서로 다른 스펠 스피드를 받는다(§6). |
| B. 서로 다른 계층인가? | **그렇다.** 파서/분석 계층 ↔ 실행 계층. |
| C. 일부 상황에서 상관관계만 있는가? | **그렇다.** 상관은 `ACTIVATE`/`QUICK_O` 블록에서만 강하고(85%·67%) `IGNITION` 에서는 거의 없다(1.4%). |
| D. 현재 저장소에서 서로 연결되지 않는가? | **그렇다 — 간선이 0개다.** 위 두 그래프가 만나지 않는다. |

---

## 6. activation-timing 과의 관계 — 행동 증거

`engine/activation_timing.py` 의 모듈 설명은 이미 이렇게 적는다.

> 카드 종류만으로 정해지는 것은 마법 · 함정뿐이다. 몬스터 효과의 스펠
> 스피드는 … `EFFECT_TYPE_QUICK_O` 를 읽는 계층이 없다.

`classify_spell_speed` 가 **실제로 읽는 속성**을 AST 로 뽑으면
`type_names` · `is_trap` · `is_spell` · `is_monster` 뿐이고
`code` · `effect_types` · `effects` · `script` 는 **하나도 없다**(`test_09`).

### 🔴 같은 `code`, 다른 속도 — 실제 카드로

| 카드 | passcode | `code` 전체 | 카드 종류 | `classify_spell_speed` |
|---|---|---|---|---|
| 욕망의 항아리 | 55144522 | `['EVENT_FREE_CHAIN']` | SPELL | **스펠 스피드 1** |
| 싸이크론 | 5318639 | `['EVENT_FREE_CHAIN']` | SPELL/QUICKPLAY | **스펠 스피드 2** |
| 강제 탈출 장치 | 94192409 | `['EVENT_FREE_CHAIN']` | TRAP | 스펠 스피드 2 |
| 사파이어 드래곤 | 11091375 | `[]` | MONSTER/NORMAL | **UNKNOWN** |

`code` 가 **글자 그대로 같은데** 속도가 1 과 2 로 갈린다. 근거 문자열도
`"카드 종류: SPELL"` · `"카드 종류: SPELL / QUICKPLAY"` 로 **카드 종류**를
적는다(`test_08`).

> 🔴 그러므로 `EVENT_FREE_CHAIN` 은 activation timing 을 **정하지 않는다.**
> 3-F-24 가 확정한 *"`EffectDefinition.activation` 은 activation timing 이
> 아니다"* 와 **같은 종류의 구분**이 하나 더 있는 것이다.

---

## 7. 실제 카드 표본 — 27장

실제 카드명을 측정으로 확인한 것만 적는다. "공식 의미" 칸은 **룰북의
Spell Speed 표에서** 오고, Lua 이름에서 역추론하지 않는다.

| passcode | 카드명 | FC | 카드 종류 | 공식 SS | FC블록 `effect_types` | 등재 | `code` 전체 |
|---|---|---|---|---|---|---|---|
| 55144522 | 욕망의 항아리 | ✅ | 통상마법 | 1 | `ACTIVATE` | ✅ | `EVENT_FREE_CHAIN` |
| 53129443 | 블랙홀 | ✅ | 통상마법 | 1 | `ACTIVATE` | ✅ | `EVENT_FREE_CHAIN` |
| 5318639 | 싸이크론 | ✅ | 속공마법 | 2 | `ACTIVATE` | ✅ | `EVENT_FREE_CHAIN` |
| 22589918 | 리로드 | ✅ | 속공마법 | 2 | `ACTIVATE` | ✅ | `EVENT_FREE_CHAIN` |
| 94192409 | 강제 탈출 장치 | ✅ | 통상함정 | 2 | `ACTIVATE` | ✅ | `EVENT_FREE_CHAIN` |
| 24623598 | 로스트 | ✅ | 통상함정 | 2 | `ACTIVATE` | ✅ | `EVENT_FREE_CHAIN` |
| 92595643 | 벌금 | ✅ | 통상함정 | 2 | `ACTIVATE` | ✅ | `EVENT_FREE_CHAIN` |
| 5915629 | 욕망의 선물 | ✅ | 통상함정 | 2 | `ACTIVATE` | ✅ | `EVENT_FREE_CHAIN` |
| 269012 | 신을 묶는 묘 | ✅ | 필드마법 | 1 | `ACTIVATE` | — | `EVENT_FREE_CHAIN` 외 3 |
| 365213 | 광래하는 기적 | ✅ | 지속마법 | 1 | `ACTIVATE` | — | `EVENT_FREE_CHAIN` 외 2 |
| 4081094 | 제이의 관 | — | 지속마법 | 1 | — | — | `EFFECT_CANNOT_SSET` 외 1 |
| 3574681 | 금과옥조 | ✅ | 장착마법 | 1 | `ACTIVATE` | — | `EVENT_FREE_CHAIN` 외 3 |
| 242146 | 성벽 파괴의 대창 | — | 장착마법 | 1 | — | — | `EFFECT_UPDATE_ATTACK` |
| 9236985 | 리추어의 사혼경 | ✅ | 의식마법 | 1 | `ACTIVATE` | — | `EVENT_FREE_CHAIN` |
| 7986397 | 리벤데드 버스 | — | 의식마법 | 1 | — | — | `EVENT_PHASE` |
| 27551 | 리미트 리버스 | ✅ | 지속함정 | 2 | `ACTIVATE` | — | `EVENT_FREE_CHAIN` 외 3 |
| 5914184 | 더블 페이백 | — | 지속함정 | 2 | — | — | `EVENT_DAMAGE` 외 1 |
| **25419323** | **다이놀피어 쉘** | ✅ | **카운터함정** | **3** | `ACTIVATE` | — | `EVENT_FREE_CHAIN` 외 3 |
| **28292031** | **다이놀피어 리버전** | ✅ | **카운터함정** | **3** | `ACTIVATE` | — | `EVENT_FREE_CHAIN` 외 다수 |
| **29185231** | **파르티안샷** | ✅ | **카운터함정** | **3** | `ACTIVATE` | — | `EVENT_FREE_CHAIN` |
| 703897 | 오르페골 클리막스 | ✅ | 카운터함정 | 3 | `QUICK_O` | — | `EVENT_CHAINING` 외 2 |
| 983995 | 리바운드 | — | 카운터함정 | 3 | — | — | `EVENT_CHAINING` 외 1 |
| 2511 | 라뷰린스 쿠클락 | ✅ | 몬스터 | UNKNOWN | `QUICK_O` | — | `EVENT_FREE_CHAIN` 외 2 |
| 71696014 | 매지션즈 로브 | ✅ | 몬스터 | UNKNOWN | `FIELD+QUICK_O` | — | `EVENT_FREE_CHAIN` 외 2 |
| 10000 | 텐사우전드 드래곤 | — | 몬스터 | UNKNOWN | — | — | `EFFECT_SPSUMMON_PROC` 외 3 |
| **85602018** | **유언장** | ✅ | 통상마법 | 1 | `ACTIVATE` **그리고** `FIELD+CONTINUOUS` | — | `EVENT_FREE_CHAIN` ×2 |
| **17787975** | **디멘션 스핑크스** | ✅ | 지속함정 | 2 | `FIELD+QUICK_O` | — | `EVENT_FREE_CHAIN` 외 1 |

---

## 8. 🔴 반례 — §6 이 요구한 양방향

### 가정 ① "FC = 자유롭게 발동 가능한 효과" → **깨진다**

`EFFECT_TYPE_ACTIVATE` 블록만 본 전수 측정:

| 카드 종류 | 공식 SS | 공식 룰북이 적는 것 | `ACTIVATE` 블록 | FC |
|---|---|---|---|---|
| 통상 마법 | 1 | *"cannot be activated in response to any other effects"* | 975 | **975 (100%)** |
| 장착 마법 | 1 | 〃 | 32 | **32 (100%)** |
| 지속 마법 | 1 | 〃 | 468 | **468 (100%)** |
| **필드 마법** | **1** | 〃 | **312** | **312 (100.0%)** |
| 의식 마법 | 1 | 〃 | 5 | **5 (100%)** |
| 속공 마법 | 2 | *"can typically be activated during any phase"* | 498 | 453 (91%) |
| 통상 함정 | 2 | 〃 | 1,308 | 918 (70%) |
| 지속 함정 | 2 | 〃 | 534 | 508 (95%) |
| **카운터 함정** | **3** | *"Only another Spell Speed 3 card may be used to respond"* | **210** | **3 (1.4%)** |

> 🔴 **가장 자유롭게 체인하는 쪽(카운터 함정)이 1.4%, 전혀 체인하지 못하는
> 쪽(필드 마법)이 100%다.** 70배 차이가 공식 속도와 **반대 방향**으로 난다.
> 카운터 함정의 나머지는 `EVENT_CHAINING` 144 · `EVENT_SPSUMMON` 26 ·
> `EVENT_SUMMON` 20 … 로 **실제 사건**을 적는다.

> 🔴 **측정 중 한 번 과장했다.** `most_common(3)` 출력만 보고 카운터 함정을
> *"210블록 중 0건"* 이라고 적었다 — 전수로 세면 **3건**이다(다이놀피어 쉘 ·
> 다이놀피어 리버전 · 파르티안샷). 상위 N 출력은 **"없다" 의 근거가 될 수
> 없다.** 이 Phase 가 쓴 docstring 두 곳의 "0건" 도 같이 고쳤고,
> `test_13` 은 **전수**로 센다.

전체 카드 단위 교차표(1:1 검정, `test_14`):

| 공식 Spell Speed | FC 있음 | FC 없음 | 비율 |
|---|---|---|---|
| 1 | 1,789 | 391 | 82.1% |
| 2 | 1,892 | 455 | 80.6% |
| 3 | 15 | 152 | **9.0%** |

**세 등급 모두 섞여 있으므로 1:1 함수가 아니다.**

### 가정 ② "FC = 특정 timing 에서만 발동 가능" → **깨진다**

- FC 를 쓰는 스크립트 4,488개 중 `SetHintTiming` 이 **있는 것 1,768 / 없는
  것 2,720**. 같은 상수가 timing 힌트가 있는 효과와 없는 효과에 모두 붙는다.
- `classify_spell_speed` 가 이 값을 읽지 않으므로 **엔진의 timing 판정에는
  아무 영향이 없다**(§6).

### 반례 ③ 발동이 **아닌** 블록에도 붙는다

| 카드 | 블록 | `effect_types` | 공식 분류 |
|---|---|---|---|
| 유언장 `85602018` | `s.activate` 안에서 런타임 등록 | `FIELD+CONTINUOUS` | Continuous Effect — 룰북: `has_activation: false` · *"There is no trigger for its activation"* |
| 디멘션 스핑크스 `17787975` | `initial_effect` 의 `e3` | `FIELD+QUICK_O` | — |
| 매지션즈 로브 `71696014` | `initial_effect` 의 `e1` | `FIELD+QUICK_O` | — |

공식 Continuous Effect 는 **발동이 아예 없다.** 그 블록에도 같은 상수가
붙는다 — 즉 이 상수는 "발동" 개념에만 쓰이는 것도 아니다.

### 반례 ④ 🔴 **"없다" 의 유일한 표기가 아니다** (이 Phase 의 정정)

| `effect_types` | 블록 | `EVENT_FREE_CHAIN` | `code is None` |
|---|---|---|---|
| `ACTIVATE` | 4,305 | 3,642 (84.6%) | **0** |
| `QUICK_O` | 1,875 | 1,257 (67.0%) | **0** |
| `IGNITION` | 4,180 | 58 (1.4%) | **4,119 (98.5%)** |
| `TRIGGER_O` | 6,088 | **0** | 63 |
| `TRIGGER_F` | 1,972 | **0** | 8 |

- `ACTIVATE` · `QUICK_O` 블록은 `SetCode` 를 **반드시** 부른다(`None` 0건).
- `IGNITION` 블록은 거꾸로 **98.5%가 아예 부르지 않는다** — 공식 기동 효과도
  유발 사건이 없는데, 같은 "없다" 를 **생략**으로 적는다.

> 🔴 그러므로 production docstring 의 *"'없다' 를 말하는 값은 `None` 이
> 아니라 `EVENT_FREE_CHAIN` 이다"* 는 **너무 넓었다.** "없다" 를 적는 방법은
> **블록 종류에 따라 둘**이다.

### 반례 ⑤ 공동 등장 열거가 불완전했다

docstring 이 *"`ACTIVATE` · `QUICK_O` · `IGNITION` 과만 함께 쓰인다"* 고
적었다. 4,914블록 전수 집계:

| `effect_types` | 블록 |
|---|---|
| `ACTIVATE` | 3,642 |
| `QUICK_O` | 1,257 |
| `IGNITION` | 58 |
| **`FIELD`** | **3** ← 빠져 있었다 |
| **`CONTINUOUS`** | **1** ← 빠져 있었다 |

단, **맞는 절반**도 전수로 확인했다 — `TRIGGER_O` · `TRIGGER_F` 와는
**0회**다.

---

## 9. production 소비 여부 — §4 의 A~E 최종

| 계층 | 파일 · 함수 | 분류 |
|---|---|---|
| parser | `sources/lua_loader.py:192` `spec.code = f"EVENT_{...}"` | **A. 저장만** |
| `EffectSpec` | `core/card_model.py:50` `code: str \| None` | **A** |
| `EffectDefinition` | — 칸이 **없다** | **E** |
| analysis | `analysis/effect_analyzer.py:374·474` | **B. 분석만** |
| `engine/trigger.py` | 코드 등장 0 · `TriggerSpec.code` 없음 | **E** |
| `engine/event_pipeline.py` | 코드 등장 0 | **E** |
| `engine/activation.py` | 0 (`blocked.code` 는 `ValidationCode`) | **E** |
| `engine/activation_timing.py` | 0 — `type_names` 만 읽음 | **E** |
| `Duel.legal_actions()` | 0 (후보 생성기 4개 전부) | **E** |
| `Duel.apply()` / `_apply_activation` | 0 | **E** |
| `EffectActivator` | 0 · `EffectSpec` 도 모름 | **E** |
| `ChainLink` 생성 | 0 · 6칸에 없음 | **E** |
| Search (`agent/simulation.py` · `search.py`) | 0 | **E** |
| AI (`agent/heuristic.py` · `policy.py` · `evaluation.py`) | 0 | **E** |
| 검색 (`core/card_search.py:323`) | `has_effect_code(code)` | **C. production 에서 읽는다** |
| CLI (`app/main.py:217·252`) | 표시 | C |

> **"필드가 존재한다" 와 "engine 이 의미를 소비한다" 는 다르다**(3-F-24).
> 여기서는 한 단계 더 좁혀진다 — engine 은 **볼 수조차 없다**(§5).

---

## 10. Chain 생성과의 관계 — §8 의 A~F

| 질문 | 답 | 근거 |
|---|---|---|
| A. `ChainLink` 생성이 읽는가? | **아니다** | 6칸(`sequence` `actor` `effect_ref` `source` `selections` `payments`)에 없고 `ChainLink`/`Chain` 코드에 0회 (`test_17`) |
| B. `legal_actions()` 가 읽는가? | **아니다** | `legal_actions` · `_activation_actions` · `_activation_gate` · `_flow_actions` · `_attack_actions` · `_withheld_board_actions` 전부 0회 (`test_18`) |
| C. `EffectActivator` 가 읽는가? | **아니다** | 0회, `EffectSpec` 도 import 하지 않음 (`test_20`) |
| D. `ChainResolver` 가 읽는가? | **아니다** | `engine/chain.py` 코드에 0회 (`test_17`) |
| E. `TriggerCandidate` 생성이 읽는가? | **아니다** | `TriggerSpec` 에 `code` 칸 없음. `TriggerCandidate.code` 는 **`ValidationCode`** (`test_21`) |
| F. Free Chain 을 명시적 상태/enum 으로 표현하는가? | **🔴 없다** | production enum 의 체인 관련 멤버 **13개 전수**를 뽑아 확인 — `FREE` 가 들어간 멤버 **0개** (`test_22`) |

있는 13개는 전부 체인의 **상태**다: `ChainResolutionStatus.EMPTY_CHAIN` ·
`CHAIN_COMPLETE` · `INVALID_CHAIN_LINK` · `ActivationStatus.CHAIN_REFUSED` ·
`ResponseStep.NO_CHAIN` · `ValidationCode.CHAIN_EMPTY` ·
`CHAIN_DEFINITION_UNAVAILABLE` 등. **발동 분류를 담는 것은 하나도 없다.**

---

## 11. `legal_actions` / `apply` 영향

**영향 없음 — 변경 0.**

- 두 함수 모두 이 값을 0회 읽는다(§10).
- `EVENT_FREE_CHAIN` 만 가진 카드로 짠 덱(욕망의 항아리 6 · 싸이크론 4 ·
  강제 탈출 장치 4 · 사파이어 드래곤 6)으로 실제 주행하면 `activate_effect`
  가 **받아들여진다**(`test_32`). "소비하지 않는다" 가 "발동이 안 된다" 는
  뜻이 아니다.
- `activate_card` 는 여전히 보류이고 사유는 `activation-timing (Phase
  2-C/2-F)` 이다 — **`EVENT_FREE_CHAIN` 이 사유로 등장하지 않는다.**

### 🔴 등재 집합에서 이 값은 **상수**다

| 측정 | 값 |
|---|---|
| 등재된 `EffectDefinition` | 16 |
| 그 카드의 `code` 목록 | **16/16 이 `['EVENT_FREE_CHAIN']` 하나뿐** |
| `ordinal` | 16/16 이 0 |
| 그런데 공식 Spell Speed | **{1, 2} 로 갈린다** (통상마법 8 · 속공마법 3 · 통상함정 5) |

상수는 **아무것도 구분하지 못한다.** 지금 이 값을 배선해도 등재된 16개의
동작은 **달라질 수 없다**(`test_28`). 반대로 속도를 가르는 것은 카드
종류이고, 그것은 이미 배선돼 있다.

---

## 12. AI / Search 영향

| 질문 | 답 |
|---|---|
| `legal_actions()` 가 Free Chain 여부를 쓰는가? | **아니다** (§10 B) |
| Search 가 후보 생성에 쓰는가? | **아니다** — `agent/` 전체에 0회, `EffectSpec` · `effect_types` · `.script` 도 0회 (`test_23`) |
| AI 가 Free Chain 을 별도 행동으로 인식하는가? | **아니다** — `PlayerActionKind` 에 그런 종류가 없고 AI 는 `legal_actions` 가 준 것만 본다 |
| AI 가 그 문자열/코드를 보고 행동을 발명할 가능성이 있는가? | **구조적으로 없다** — `CardDefinitionView` 가 그 값을 싣지 않으므로 관측에 **존재하지 않는다**(§5) |
| "Search 는 `legal_actions()` 만 탐색한다" 계약과 충돌하는가? | **아니다** — `agent/simulation.py:156·221·252` · `agent/runner.py:192` 가 유일한 입구다 |

**AI/Search 변경 0.**

---

## 13. 공식 용어 ↔ 내부 용어 대응 — §9

| 공식 | 내부 | 1:1 인가 |
|---|---|---|
| "Activate a Card or Effect" (MAIN1 `main_actions` 의 **한 항목**) | `ACTIVATE_CARD` + `ACTIVATE_EFFECT` (**두** 종류) | ❌ (3-F-23 이 확정) |
| "activation of a card or effect" | `ChainLink` · `EffectActivator` | 부분적 — `ChainLink` 는 **결과**를 담고 발동 행위를 담지 않는다 |
| **"Free Chain"** | **`EVENT_FREE_CHAIN`** | ❌ **공식 측에 그 표현이 없다**(§1) |
| Spell Speed 1/2/3 | `SpellSpeed.NORMAL/FAST/COUNTER` | ✅ (카드 종류 기준, 몬스터는 UNKNOWN) |

### 🔴 같은 글자가 **세 가지 다른 것**을 가리킨다

| 이름 | 실제로 담는 것 |
|---|---|
| `EffectSpec.code` | Lua `SetCode` 인자 (`EVENT_*` / `EFFECT_*` 상수 **이름**) |
| `TriggerCandidate.code` · `verdict.code` · `blocked.code` | **`ValidationCode`** (판정 사유) |
| `CardDefinitionView.setcodes` | **카드군(archetype)** — 정수 |

부분 문자열로 세면 조용히 틀린다(`test_29`). 3-F-24 가 실제로 한 번
틀렸다.

### `PlayerActionKind.FREE_CHAIN` 이 필요한가?

**필요하지 않다 — 그리고 이번 Phase 에서 만들지 않았다.**

근거: (1) 공식 측에 대응할 개념이 확정되지 않았다(§2). (2) 등재된 16개에서
이 값은 **상수**이므로 구분할 정보가 0비트다(§11). (3) 행위 종류가 아니라
**효과 명세의 속성**이다 — 행위 종류로 올릴 자리가 아니다. (4) Engine V1
freeze.

---

## 14. 최종 semantic classification

> ## **C. LUA_INTERNAL_TAG**
>
> 현재 저장소에서 `EVENT_FREE_CHAIN` 은 **Lua 내부 분류/태그**이고,
> **공식 규칙 개념과 1:1 로 대응하지 않는다.**

### 근거 (공식 자료 + 실제 데이터 + 코드 경로)

1. **Lua 내부 태그다.**
   - `constant.lua` 의 `--Events` 블록 낮은 번호대(1002)에 정의된 상수
     이름이고, 저장되는 것은 **문자열**이다(§3).
   - 쓰는 곳은 파서 **하나**, 읽는 곳은 analysis · card_search · CLI
     **셋**뿐이다. **engine/agent 는 0곳**(§9).
   - engine 은 읽지 않는 것이 아니라 **볼 수조차 없다** —
     `CardDefinitionView` 26칸에 없다(§5).
   - `EVENT_*` **70종 전부**가 똑같이 production 코드 0회다 — 이 상수가
     EVENT 체계에서 특별하지 않다(§4).

2. **공식 규칙 개념과 1:1 이 아니다.**
   - 저장소의 공식 자료 전체에서 "Free Chain" **0회**(§1).
   - 공식 Spell Speed 와 1:1 검정 **실패** — 세 등급이 모두 섞인다(§8).
   - 양 끝에서 **뒤집힌다** — 필드 마법(SS1, 대응 불가) 312/312 = **100%**
     vs 카운터 함정(SS3, 모든 것에 대응) 210블록 중 **3건 = 1.4%**(§8).
   - 공식 기동 효과(유발 사건 없는 발동)의 98.5%는 이 값을 **쓰지 않고**
     `SetCode` 를 생략한다(§8 ④).
   - 공식 지속 효과(발동이 **없는** 효과)의 블록에도 붙는다(§8 ③).

3. **activation timing 과 연결되지 않는다.**
   - 두 코드 경로 사이에 **간선이 0개**(§5).
   - 같은 `code` 를 가진 두 카드가 서로 다른 속도를 받는다 — 근거는
     **카드 종류**(§6).

### 왜 A 가 아닌가

A(`DIRECT_SEMANTIC_MATCH`)는 **직접 대응이 입증됨**을 뜻한다. 입증할 공식
측 자료가 **없고**(§1), 가장 가까운 공식 개념(Spell Speed)과는 분포가
**역방향**이다(§8). 입증의 반대가 측정됐다.

### 왜 B 가 아닌가

B(`CORRELATED_BUT_NOT_IDENTICAL`)는 *"관련은 있다"* 를 주장한다. 그 주장을
하려면 **관련될 공식 개념이 특정**되어야 한다. 공식 측에 그 용어가 없으니
무엇과 관련됐다고 말할 자리가 없다. 실제로 측정된 상관은
*"`EFFECT_TYPE_ACTIVATE`/`QUICK_O` 블록에서 유발 사건을 요구하지 않는다"*
라는 **Lua 구조 내부의 상관**이고, 그것은 공식 "Free Chain" 과의 상관이
아니다. 근거 없는 semantic mapping 을 만들지 않는다.

### 왜 D 가 아닌가

D(`SEMANTIC_UNRESOLVED`)는 *"현재 자료만으로 의미를 확정할 수 없다"* 다.
**공식 정의는 실제로 확정하지 못했고(§2 전체가 UNKNOWN), 그것을 숨기지
않는다.** 그러나 이 Phase 가 묻는 것은 **둘의 관계**이고, 관계는 확정됐다 —
C 의 두 주장(① 내부 태그다 ② 1:1 이 아니다)은 **공식 정의를 몰라도**
측정으로 성립한다. ②는 "어떤 공식 개념과 1:1 인가" 를 **모두 검정해서
전부 실패**했기 때문에 성립한다(Spell Speed 3등급 · 효과 분류 5종 · 카드
종류 9종).

> 🔴 **판정이 바뀔 조건을 미리 적는다.** 공식 자료(코나미 공식 룰북 ·
> 공식 DB Q&A 본문)에서 "Free Chain / フリーチェーン" 의 **정의**가 확인되면,
> 그 정의와 이 Phase 가 측정한 분포를 다시 대조해 **B 또는 A** 로 옮길 수
> 있다. 그 확인은 이 Phase 가 **하지 못했다**(§1).

---

## 15. production 변경 여부 — **docstring 2건** (실행 코드 0줄)

§12 가 허용한 *"잘못된 docstring 수정"* 과 *"이번 Phase 에서 확인한 사실을
문서화하기 위한 최소 변경"* 에만 해당한다.

| 파일 | 고친 것 |
|---|---|
| `core/card_model.py` | `EffectSpec.code` · `LuaScriptInfo.trigger_events` |
| `analysis/effect_model.py` | `EffectAnalysis.trigger_event` |

### 고친 내용 셋

1. 🔴 *"'없다' 를 말하는 값은 `None` 이 아니라 `EVENT_FREE_CHAIN` 이다"* →
   **블록 종류별 표로 교체.** `ACTIVATE`/`QUICK_O` 는 `None` 0건,
   `IGNITION` 은 98.5%가 `None`. "없다" 의 표기는 **둘**이다.
2. 🔴 공동 등장 열거에 `FIELD` 3 · `CONTINUOUS` 1 **추가**. `TRIGGER_O`/
   `TRIGGER_F` 0회는 **맞다**고 재확인해 남겼다.
3. 🔴 **공식 용어 경계 명시** — 저장소 공식 자료에 0회, 공식 Spell Speed 와
   양 끝에서 역전(필드 마법 100% vs 카운터 함정 1.4%), engine 은 읽지 않음.

### 금지 항목 — 하나도 하지 않았다

`EVENT_FREE_CHAIN` 처리 구현 ✗ · `EVENT_*` 처리 구현 ✗ · trigger engine 변경
✗ · Chain engine 변경 ✗ · activation timing 변경 ✗ · `legal_actions` 변경 ✗ ·
`ACTIVATE_CARD` 구현 ✗ · 새 `PlayerActionKind` ✗ · 새 enum ✗ ·
AI/Search 변경 ✗ · Engine V1 freeze 해제 ✗

**증명**: 문자열 리터럴을 벗긴 AST 가 base(`f84a47a`)와 **글자 그대로
같다** — 두 파일 모두(`test_30`). 그리고 바꾼 파일이 **정확히 그 둘**임을
함께 못 박는다.

---

## 16. 테스트 결과

### 신규 33개 — `tests/test_event_free_chain_semantic_audit.py`

| # | 무엇을 재는가 | §13 항목 |
|---|---|---|
| 01 | corpus 존재 (4,914블록 / 4,488스크립트) | 1 |
| 02 | 추출 경로 — `parse_lua_source` 가 만든다 | 2 |
| 03 | 저장 형태 — 접두사 포함 문자열 | 3 |
| 04 | `constant.lua` 정의 (1002, 낮은 번호대) | 1 |
| 05 | 🔴 `EVENT_*` **70종 전부** production 0회 | 5 |
| 06 | 읽는 자리 넷뿐 (engine/agent 0) | 5·6 |
| 07 | 🔴 `CardDefinitionView` 에 없다 — hidden-info 경계 | 19 |
| 08 | 🔴 같은 `code`, 다른 SpellSpeed (**행동**) | 7 |
| 09 | `classify_spell_speed` 가 읽는 속성 (AST) | 7 |
| 10 | 두 코드 경로에 간선 0 | 6·7 |
| 11 | 실제 Monster corpus (874) | 8 |
| 12 | 실제 Spell corpus (`ACTIVATE` 5종 100%) | 9 |
| 13 | 🔴 실제 Trap corpus + 카운터 함정 3/210 | 10 |
| 14 | 🔴 공식 Spell Speed 1:1 검정 **실패** | 10 |
| 15 | 필드 마법 312/312 극단 | 9 |
| 16 | `EVENT_*` 복수 code · `index` 중복 | 11 |
| 17 | `ChainLink` 소비 0 | 12 |
| 18 | `legal_actions` 소비 0 (생성기 6개) | 13 |
| 19 | `apply` 소비 0 | 14 |
| 20 | `EffectActivator` 소비 0 | 15 |
| 21 | `TriggerCandidate`/`TriggerSpec` 소비 0 | 16 |
| 22 | 🔴 Free Chain enum/state **없다** (13개 전수) | 12 |
| 23 | Search/AI 소비 0 | 17·18 |
| 24 | Search 는 `legal_actions` 만 | 17 |
| 25 | 🔴 **정정 1** — `IGNITION` 98.5%가 `None` | 5 |
| 26 | 🔴 **정정 2** — 공동 등장 열거 불완전 | 6 |
| 27 | 🔴 공식 자료에 0회 (686+파일) | 1 |
| 28 | 🔴 등재 16개에서 **상수** | 4 |
| 29 | 🔴 용어 충돌 3건 | 6 |
| 30 | 🔴 production 변경 = docstring 뿐 (AST) | — |
| 31 | `state_hash` · RNG 불변 | 20 |
| 32 | FC-heavy 덱이 실제로 돈다 | 13·14 |
| 33 | 검색 digest 불변 (611결정) | 20 |

실제 카드 **27장** 사용 — §7 의 표 그대로.

기존 테스트를 **삭제·skip·약화하지 않았고, 고친 것도 없다.**
**skip 추가 0** — `test_30` 은 commit 전에도 base 와 비교해 **skip 하지
않는다**(3-F-24 와 같은 방식).

### 전체 회귀

```
$ python -m pytest -p no:randomly -q
4692 passed, 4 skipped in 722.35s (0:12:02)
```

| 항목 | 값 |
|---|---|
| Phase 3-F-24 종료 시점 baseline | 4,659 passed |
| 이번 Phase 신규 테스트 | **+33** |
| 합계 (측정값) | **4,692 passed** |
| 실패 | **0** |
| skip | **4** — 3-F-24 와 **동일**. 이번 Phase 가 추가한 skip 은 0건 |

33 = 4,692 − 4,659 가 정확히 맞고 skip 수가 그대로이므로, **기존 테스트 중
사라지거나 실패로 바뀐 것도, 새로 건너뛴 것도 한 건도 없다.**
`-p no:randomly` 로 순서를 고정해 실행했다.

### 🔴 고의 위반 주입 12건 — 전부 검출

10개 파일을 md5 로 백업하고 하나씩 심었다 되돌렸다. 각 주입은 **먼저
`import` 로 유효성을 확인**했다 — 모듈을 깨뜨리는 주입은 "테스트가 약하다" 의
증거가 아니라 **나쁜 probe** 다.

| # | 심은 위반 | 걸린 테스트 |
|---|---|---|
| 1 | `EffectDefinition` 에 `code` 칸을 더한다 | `test_28` `test_30` |
| 2 | `classify_spell_speed` 가 `definition.code` 를 읽는다 (죽은 코드로) | `test_09` `test_30` |
| 3 | 가드 없는 enum 에 `FREE_CHAIN_PENDING` 멤버를 만든다 | `test_22` `test_30` |
| 4 | engine 코드가 `EVENT_FREE_CHAIN = 1002` 를 쓴다 | `test_05` `test_30` |
| 5 | `CardDefinitionView` 에 `effect_types` 를 싣는다 | `test_07` `test_30` |
| 6 | AI(`heuristic.py`)가 `card.script.effects` 를 들여다본다 | `test_23` `test_30` |
| 7 | `duel.py` 가 `spec.code` 를 읽는다 | `test_06` `test_30` |
| 8 | 파서가 접두사를 떼고 저장한다 | `test_01` `test_02` `test_03` `test_05` `test_16` `test_25` `test_26` `test_30` |
| 9 | `ChainLink` 가 `trigger_event` 를 들고 다닌다 | `test_10` `test_17` `test_30` |
| 10 | 정정한 docstring 을 되돌린다 (`card_model`) | `test_25` |
| 11 | 파서가 `FIELD` 타입을 다시 흘린다 | `test_16` `test_25` `test_26` `test_30` |
| 12 | 정정한 docstring 을 되돌린다 (`effect_model`) | `test_25` |

마지막 복원을 **md5 로 확인**했다 (10/10 OK).

#### 🔴 주입 10 · 12 — **진짜 테스트 약점을 찾았다**

처음 `test_25` 는 `"유일한 표기가 아니다" in text` 로 **파일 전체**를 훑었다.
한 군데를 `"유일한 표기다"` 로 뒤집어도 **다른 줄이 통과시켰다.** 부분 문자열
하나로 두 군데를 대신 세면 안 된다. 문장 단위 `count(...) == 1` 과 뒤집힌
문장의 부재, 그리고 `analysis` 쪽 수치까지 함께 보도록 고쳤다.

#### 🔴 주입이 **기존 production 가드**에 막힌 사례

처음에는 `ValidationCode` 에 `FREE_CHAIN_REFUSED` 를 심으려 했다.
`engine/validation.py` 가 **import 시점에** 거절한다:

> `CODE_VALIDITY 가 다루지 않는 ValidationCode 가 있습니다: FREE_CHAIN_REFUSED.`

내 테스트가 아니라 **저장소 자신의 가드**가 막은 것이므로, 가드가 없는
`engine/chain.py` 의 enum 으로 바꿔 `test_22` 를 검증했다.

#### 🔴 나쁜 probe 5건을 먼저 걸러냈다

`EffectDefinition`/`ChainLink` 에 기본값 필드를 **맨 위에** 넣어 dataclass
필드 순서를 깨뜨린 것 2건, `@dataclass` 와 `class Duel:` **사이**에 문장을
끼워 SyntaxError 를 낸 것 2건, 앵커가 2회 이상 걸린 것 1건. 모두 `import`
확인 단계에서 잡아 앵커를 고쳤다. **"주입이 아무것도 깨뜨리지 않았다" 를
"테스트가 약하다" 로 읽지 않는다.**

---

## 17. 불변 조건 검증 — §14

| 항목 | 결과 | 근거 |
|---|---|---|
| `state_hash` 불변 | ✅ | `test_31` — 같은 seed 동일, 다른 seed 상이 |
| RNG 불변 | ✅ | `test_31` — 뽑은 값 8개 비교 (객체 주소 비교 아님) |
| digest 불변 | ✅ | `test_33` — 6판 **611결정**, 기존 pin 7개를 AST 로 읽어 대조 |
| hidden-information 불변 | ✅ | `test_07` — `CardDefinitionView` 26칸 그대로 |
| `GameStateView` 불변 | ✅ | 변경 0 (`test_30`) |
| Search 불변 | ✅ | `test_23` `test_24` `test_33` |
| AI 불변 | ✅ | `test_23` · `agent/` 변경 0 |
| Engine V1 freeze | ✅ | `engine/` 변경 **0 파일** |
| 기존 검색 결과 불변 | ✅ | 실행 코드 0줄 변경 (AST 동일) |
| 기존 테스트 baseline + 신규 | ✅ | §16 |
| 기존 테스트 삭제 | **0** | — |
| skip 추가 | **0** | `test_30` 이 fallback 으로 skip 회피 |
| assertion 약화 | **0** | 오히려 `test_25` 를 **강화**했다 (주입 10·12) |

---

## 18. 향후 `ACTIVATE_CARD` / trigger 구현에 주는 의미

측정에서 **그대로 따라오는 것만** 적는다. 새 설계를 하지 않는다.

1. **`EVENT_FREE_CHAIN` 을 "자유 체인" 으로 읽고 구현하면 틀린다.** 공식
   Spell Speed 와 양 끝에서 역전되므로(§8), 이 값으로 체인 가능성을 정하면
   필드 마법이 상대 턴에 발동하고 카운터 함정이 못 하게 된다.
2. **지금 배선해도 등재 16개의 동작은 변하지 않는다.** 그 집합에서 이 값은
   상수이므로 정보량이 0비트다(§11). 배선의 효용은 **등재를 넓힌 뒤**에만
   생긴다.
3. **`ACTIVATE_CARD` 의 빈 자리는 이 값이 메우지 않는다.** 보류 사유는
   `activation-timing (Phase 2-C/2-F)` 이고, 그 timing 은 **카드 종류**에서
   온다 — 이미 배선돼 있다(§6).
4. **배선한다면 옮길 것은 `code` 가 아니라 `effect_types` 다.** 몬스터 스펠
   스피드가 UNKNOWN 인 이유는 `EFFECT_TYPE_QUICK_O` 를 읽는 계층이 없다는
   것이고(`activation_timing.py` 가 직접 그렇게 적는다), 그 값은
   `EffectSpec.effect_types` 에 **이미 있다**(`QUICK_O` 1,875블록).
   `EVENT_FREE_CHAIN` 은 그 문제를 풀지 못한다 — `QUICK_O` 블록의 67%에만
   붙기 때문이다.
5. **trigger 구현의 입력은 `EVENT_FREE_CHAIN` 이 아니다.** 그 상수는
   `TRIGGER_O`/`TRIGGER_F` 와 **0회** 함께 쓰인다(§8 ⑤). 유발 효과의 사건은
   `EVENT_SPSUMMON_SUCCESS` 1,553 · `EVENT_SUMMON_SUCCESS` 930 ·
   `EVENT_TO_GRAVE` 790 … 쪽에 있다.
6. **단위를 먼저 고정해야 한다.** 스크립트 단위와 카드 단위가 다르고(§3),
   `index` 가 고유하지 않고(§3), `CreateEffect` 의 23.2%가 `initial_effect`
   밖이다. 등재 대상을 셀 때 이 셋을 섞으면 숫자가 조용히 틀린다.

---

## 19. 이번 Phase 에서 **의도적으로 하지 않은 것**

1. **공식 "Free Chain" 의 정의를 확정하지 않았다.** 쓸 수 있는 공식 자료에
   없고, 공식 DB 전문 검색은 **판정 불가**였다(§1). 나무위키 · 비공식 위키 ·
   커뮤니티 재정 · 모델의 기존 지식으로 메우지 않았다. §2 는 전부 UNKNOWN 이다.
2. `EVENT_FREE_CHAIN` 을 **규칙으로 구현하지 않았다.**
3. `EVENT_*` 를 **trigger system 으로 승격하지 않았다.**
4. `iter_effects` 를 production 에 **배선하지 않았다** (3-F-24 와 같은 태도).
5. `PlayerActionKind.FREE_CHAIN` 을 **만들지 않았다** (§13 — 필요하지 않다고
   판정했고, 필요해도 이번에는 만들지 않는다).
6. **파서를 고치지 않았다.** `index` 중복과 `initial_effect` 밖 블록은
   측정해 적었지만(§3), 등재 대상 선별 규칙이 정해지기 전에 파서를 바꾸면
   무엇을 잃는지 알 수 없다.
7. activation timing · Chain engine · `legal_actions` · AI/Search 를
   **건드리지 않았다.** Engine V1 freeze 유지.

---

## 20. 남은 structural risk

| 등급 | 내용 | 근거 |
|---|---|---|
| 🔴 | **공식 "Free Chain" 의 정의가 미확정이다.** 누군가 이름만 보고 "자유 체인" 으로 구현하면 §8 의 역전 때문에 규칙이 거꾸로 선다. 정정한 docstring 이 1차 방어선이고, `test_14`/`test_15` 가 2차다. | §2 · §8 |
| 🟠 | **`code` 라는 이름이 세 가지를 가리킨다.** 부분 문자열 측정이 조용히 틀린다 — 3-F-24 가 실제로 틀렸고, 이 Phase 도 `most_common(3)` 으로 한 번 과장했다. | §13 |
| 🟠 | **몬스터 스펠 스피드가 UNKNOWN 이다.** 필요한 값(`QUICK_O`)은 `EffectSpec.effect_types` 에 있는데 `CardDefinitionView` 가 싣지 않는다. 이 Phase 는 **싣지 않았다.** | §18 ④ |
| 🟡 | **`EffectSpec.index` 가 고유하지 않다.** 4,795 스크립트 · 6,802 블록. `(card_id, index)` 를 키로 쓰는 코드가 생기면 조용히 합쳐진다. | §3 |
| 🟡 | **`CreateEffect` 의 23.2%가 `initial_effect` 밖이다.** "카드가 등록한 효과" 와 "스크립트 어딘가에서 만든 효과" 가 한 목록에 섞여 있다. | §3 |
| 🟢 | `EVENT_*` 70종이 저장만 되고 소비되지 않는다 — **의도된 경계**이고 ADR-006 과 같은 태도다. | §4 |

---

## 21. 다음 Phase 후보 (최대 1개)

> **`EFFECT_TYPE_QUICK_O` ↔ 몬스터 스펠 스피드 UNKNOWN 경계 감사 (조사 전용)**

이유는 이 Phase 의 측정에서 바로 따라온다.

- `engine/activation_timing.py` 가 **직접** 적는 단 하나의 빈칸이
  `MONSTER_CLASSIFICATION_MISSING` 이고, 그 사유를 *"`EFFECT_TYPE_QUICK_O`
  를 읽는 계층이 없다"* 라고 명시한다.
- 그 값은 **이미 있다** — `EffectSpec.effect_types` 에 `QUICK_O` 1,875블록 ·
  `TRIGGER_O` 6,088 · `IGNITION` 4,180 · `TRIGGER_F` 1,972 · `FLIP` 200.
  즉 3-F-24 가 말한 "건너지 않은 경계" 가 **여기서는 공식 개념과 이름이
  맞는다** (공식 Quick/Trigger/Ignition/Flip Effect 네 종류).
- 이 Phase 가 확정한 것은 `EVENT_FREE_CHAIN` 이 그 문제를 **풀지 못한다**는
  것이다(`QUICK_O` 블록의 67%에만 붙는다). 따라서 다음에 재야 할 것은
  **`code` 가 아니라 `effect_types`** 다.
- `EVENT_FREE_CHAIN` 과 달리 이쪽은 **공식 룰북에 대응 어휘가 실재한다**
  (`effect_types` 5종 · `spell_speed` · `activation_timing` ·
  `has_activation`). 그래서 이번처럼 "공식 정의 UNKNOWN" 에 막히지 않는다.

**구현 Phase 가 아니라 조사 Phase 로** 두는 이유: 몬스터 스펠 스피드를
UNKNOWN 에서 꺼내는 것은 `CardDefinitionView` 를 넓히는 일이고, 그것은
hidden-information 경계와 Engine V1 freeze 를 건드린다. 무엇이 1:1 로
대응하고 무엇이 안 되는지 먼저 확정해야 한다.
