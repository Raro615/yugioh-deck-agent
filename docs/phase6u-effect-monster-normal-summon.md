# Phase 6-U — 효과 몬스터 일반 소환 조건 판정 및 실제 Duel 실행 개선

## 1. 작업 전 상태 확인

| 항목 | 값 |
| --- | --- |
| 브랜치 | `claude/pensive-goodall-te1egy` |
| 시작 HEAD | `5a145a5` (= `origin/claude/pensive-goodall-te1egy`) |
| 작업 트리 | 깨끗 (`git status --porcelain` 출력 없음) |
| 사용자 변경 사항 | 없음 — 덮어쓴 것이 없다 |

## 2. §2 전제의 재확인 — 실제로 재현되는가

이전 보고서의 관찰을 사실로 전제하지 않고 **실제 Duel 로 재현**했다.
어니스트 3장 · 기르수 3장 · 레벨 4 통상 몬스터 36장으로 레시피를 만들고,
6-T 의 `build_opening` 으로 선공 메인 페이즈 1 을 세운 뒤 패 5장
(어니스트 · 기르수 · 통상 3장) 각각에 `NORMAL_SUMMON` 을 물었다.

```
허용 후보: {'normal_summon': 3, 'set_monster': 3, 'end_phase': 1}

    37742478 어니스트              unknown  code=rule_not_implemented
    69811710 잭나이츠 오르페골 기르수   unknown  code=rule_not_implemented
      549481 갑옷 쥐               valid    code=ok
      732302 Temple of Skulls      valid    code=ok
     1184620 마물 사냥꾼            valid    code=ok
```

§2 의 전제는 **그대로 재현된다**. 통상 몬스터 3장은 소환되고 효과 몬스터
2장은 `UNKNOWN` 이다.

## 3. §4-A — 판정이 나오는 자리는 **한 곳**이다

`summoning-condition` 문자열을 내놓는 생산 코드는
`engine/summon_rules.py` 의 `assess_normal_summon` **마지막 갈래 하나**뿐이다
(전수 grep). 즉 고칠 자리가 흩어져 있지 않다.

`assess_normal_summon` 의 판정 순서(수정 전):

1. `definition is None` → `UNDETERMINED`
2. `not is_monster` → `FORBIDDEN`
3. `is_extra_deck` → `FORBIDDEN`
4. `NEVER_NORMAL_SUMMONABLE`(`RITUAL`·`TOKEN`·`SPSUMMON`) → `FORBIDDEN`
5. `monster_level is None` → `UNDETERMINED`
6. `level > 4` → `NEEDS_TRIBUTE`
7. `"NORMAL" in type_names` → `ORDINARY`
8. **그 외 전부** → `UNDETERMINED` + `summoning-condition`

8번이 효과 몬스터를 전부 받는다.

## 4. §17 — 실제 원인은 다른 계층이 아니다

§17 은 "실제 원인이 소환 조건 데이터 누락이 아니라 다른 계층에 있다면 그
사실을 먼저 보고한다" 고 요구한다. **그래서 먼저 확인했다.**

관문을 **측정 전용으로** 열어(파일을 고치지 않고 `engine.action_validation`
의 참조만 임시로 바꿔) 그 뒤 경로가 실제로 동작하는지 쟀다.

```
패치 후 normal_summon 후보 5건 (패치 전 3건)
DuelStep: accepted=True code=ok
소환 전 소환권 (0, 0) → 소환 후 (1, 0)
소환 후 MZONE: [(37742478, InstanceId(79), Position.FACEUP_ATTACK)]
패 5장 → 4장
소환 후 허용 후보: {'activate_effect': 1, 'end_phase': 1}
체인 0 · pending 0
```

실행기 · 배치 · 소환권 기록 · 표시(앞면 공격) · 후속 후보 생성까지 **모두
이미 동작한다.** 막고 있던 것은 판정 하나다. 다른 계층의 문제가 아니다.

## 5. §6 — 가장 중요한 구분: 제약 없음과 정보 없음

데이터로 상황 1(제약이 없음을 **확인**)과 상황 2(확인할 **정보가 없음**)를
가를 수 있는지가 이 Phase 의 갈림길이었다.

### 5.1 왜 카드 텍스트로 판정하지 않는가

`engine/summon_rules.py` 의 모듈 설명이 이미 적어 둔 측정이 결론을 준다.
「(이 카드는) 일반(통상) 소환할 수 없다」 라는 **문구**를 가진 메인덱
몬스터 11장이 `TYPE_SPSUMMON` 비트를 **갖지 않고**, 그 11장은 전부 다른
규칙이다. 문구로 세면 그 11장을 틀리게 접는다.

6-U 가 그 측정을 역방향으로도 확인했다 (아래 5.4).

### 5.2 EDOPro 는 "일반 소환할 수 없다" 를 어디에 적는가

전 코퍼스 12,972 스크립트 측정:

| 상수 | 등장 파일 수 |
| --- | --- |
| `EFFECT_CANNOT_BE_NORMAL_SUMMONED` | **0** |
| `EFFECT_CANNOT_SUMMON` | 133 |
| `EFFECT_SPSUMMON_CONDITION` | 518 |
| `EFFECT_SUMMON_PROC` | 106 |
| `EFFECT_CANNOT_SSET` | 27 |
| `EFFECT_LIMIT_SUMMON_PROC` | 7 |

🔴 **「일반 소환할 수 없다」 를 적는 전용 상수는 존재하지 않는다.** EDOPro
는 그것을 **카드 종류 비트** `TYPE_SPSUMMON` 으로 적고, 그 비트는
`NEVER_NORMAL_SUMMONABLE` 이 이미 접고 있다 (메인덱 344장).

남은 네 상수는 비트로 적지 않는 나머지 — 조건부 제약과 대체 절차다.

### 5.3 후보 집합을 셋으로 나눈 결과

`summoning-condition` 으로 막힌 **4,229장** 전수:

| 갈래 | 매수 | §6 상황 |
| --- | --- | --- |
| 스크립트를 읽었고 네 상수가 **한 건도 없다** | 4,028 | 상황 1 — 제약 없음 확인 |
| 스크립트를 읽었고 상수를 찾았다 | 48 | 상황 2 — 모른다 |
| **스크립트 자체가 없다** | 153 | 상황 2 — 모른다 |

### 5.4 §9 거짓 허가 측정 — 공식 텍스트 역검산

4,028장의 공식 한국어 / 영어 텍스트를 여덟 가지 표현으로 훑었다.
**문구로 판정하기 위해서가 아니라, 상수 기반 판정을 검산하기 위해서다.**

| 표현 | 걸린 카드 |
| --- | --- |
| `(일반\|통상)\s*소환[^。.\n]{0,12}수\s*없` | 5 |
| `세트[^。.\n]{0,8}수\s*없` | 0 |
| `특수\s*소환해야` | 0 |
| `경우에만[^。.\n]{0,20}(일반\|통상)\s*소환` | 0 |
| `Cannot be Normal Summoned` | 2 |
| `[Mm]ust (first )?be Special Summoned` | 2 |
| `[Cc]an only be Normal Summoned` | 0 |

걸린 카드를 **한 장씩** 읽었다.

| 카드 | 공식 텍스트 | 왜 자기 제약이 아닌가 |
| --- | --- | --- |
| 프린시퍼그 `11496832` | 「… 자신 필드의 **통상 소환할 수 없는 몬스터** 1장을 대상으로 하고 …」 | **다른 카드**의 성질을 가리킨다 |
| 황금의 사교신 `78642798` | 「… 자신 필드의 **통상 소환할 수 없는** "새크리파이스" 몬스터 1장에 장착한다」 | 다른 카드다 |
| 붉은 눈의 비룡 `67300516` | 「이 카드의 효과를 발동하는 턴에, **자신은** 통상 소환할 수 없다」 | 플레이어·턴에 걸리는 **판 상태**다 (아래 참고) |
| 늑장 오크 `64892035` | 「이 카드는 일반 소환한 턴에는 **공격**할 수 없다」 | 공격 제약이다 |
| SR 셰이부메랑 `80559548` | 같은 공격 제약 | 같다 |
| 이블 히어로 톡식 버블 `3598351` | "…but you cannot Special Summon for the rest of this turn, except …" | **특수** 소환 제약이다 |
| 이블 히어로 데스 프리즌 `30583090` | "If you control a Fusion Monster that **must be Special Summoned with** 「다크 퓨전」…" | 다른 카드의 성질이다 |

🔴 **자기 자신의 일반 소환을 금지하는 카드는 4,028장 중 0장이다.**

붉은 눈의 비룡은 스크립트가 그 제약을 어떻게 적는지까지 확인했다.

```lua
function s.spcon(e,tp,eg,ep,ev,re,r,rp)
    return Duel.IsTurnPlayer(tp) and Duel.GetActivityCount(tp,ACTIVITY_NORMALSUMMON)==0
end
```

제약은 **이 카드의 묘지 효과를 발동할 조건**으로 적혀 있다 — 이 카드를
일반 소환하는 것을 막는 것이 아니다. 즉 `ORDINARY` 가 규칙상 맞는 답이다.

### 5.5 반대 방향도 쟀다

상수를 가진 48장 중 23장이 공식 텍스트에 금지 문구를 갖는다 (고스트릭
13장 · 가면레온 · 그랜드 드래곤 · 레프티레스 서번트 · 도도도 보트 ·
미스틱 스워드맨 LV4 등). 남은 25장은 상수가 **다른 카드**에 걸리는
경우(인스펙트 보더 · 성스러운 광채)이거나 한국어 텍스트가 없는 경우다.
그 방향의 오차는 "모른다" 로 남으므로 **안전한 쪽**이다.

스크립트가 없는 153장 중 1장이 금지 문구를 갖는다 — **체츠커
`77435268`** 「자신 필드에 몬스터가 존재할 경우, 이 카드는 일반 소환할
수 없다」. 상수로는 잡을 수 없다. **그래서 "스크립트 없음 → UNKNOWN 유지"
가 반드시 필요하다.** 비어 있는 튜플과 `None` 을 합치면 이 한 장이 조용히
허가된다.

## 6. §6 — 기존 Effect Analysis 와 중복되지 않는가

새로운 정적 분석기를 만들지 않았다. 쓰는 데이터는 **이미 추출되어 있던**
`core.card_model.LuaScriptInfo.effect_codes` 다 (`sources/lua_loader.py`
가 채운다 — "스크립트 전체에서 등장한 `EFFECT_*` 상수"). `analysis/`
패키지를 건드리지 않았고 ADR-007 (engine 은 analysis 에서 기호 하나만
빌린다) 도 그대로다.

`CardDefinitionView` 가 그 사실을 실어 보내는 선례도 이미 있었다 —
`effect_count` 가 `len(card.script.effects)` 를 싣는다.

## 7. §9 — 고른 수정 (가장 작은 것)

세 파일, 네 군데.

### 7.1 `core/card_model.py` — 데이터 계층이 **증거**를 내놓는다

`NORMAL_SUMMON_RESTRICTION_CODES` (네 상수) 와
`Card.normal_summon_restriction_signals` 를 더했다. 이 속성은 **판정하지
않는다** — 세 가지 답을 그대로 돌려준다.

- `None` — 스크립트가 없다 (정보 없음)
- `()` — 끝까지 읽었고 한 건도 없다 (제약 없음 확인)
- 비어 있지 않음 — 제약일 수 있는 상수를 찾았다

### 7.2 `engine/game_state_view.py` — 관측이 그 사실 하나를 싣는다

`CardDefinitionView.normal_summon_restriction_signals`
(`None` 기본값) 를 더하고 `of()` · `canonical_state()` · `to_dict()` 에
반영했다.

🔴 **기본값이 `None` 인 것이 설계다.** 손으로 만든 관측은 "적지 않았다 =
읽지 않았다" 로 읽혀 조용히 허가를 얻지 않는다.

### 7.3 `engine/summon_rules.py` — 마지막 갈래를 셋으로 나눈다

```
signals is None  → UNDETERMINED (스크립트를 읽을 수 없다)
signals          → UNDETERMINED (제약일 수 있는 상수를 찾았다)
signals == ()    → ORDINARY     (RULE-SUMMON-009 의 "most")
```

`SUMMON_RESTRICTION_RULE` 상수를 빼서 두 갈래가 **같은 이름**을 쓰게 했다.

### 7.4 금지한 것을 하지 않았다 (§9)

- 카드 ID 화이트리스트를 만들지 않았다 — 판정은 전수 규칙이다
- 카드 종류만으로 단정하지 않았다 — 종류(`NORMAL`)는 **상수를 보기 전**
  갈래에 이미 있었고, 새 갈래는 **카드별 증거**를 본다
- 임의의 문자열 포함 여부로 확정하지 않았다 — 문구는 **검산**에만 썼다
  (테스트 F 묶음)
- 새로운 소환 엔진을 만들지 않았다 — 실행 경로를 한 줄도 고치지 않았다

## 8. §14 — 수정 전 / 후 측정

### 8.1 전수 판정 분포 (14,127장)

| 판정 | 수정 전 | 수정 후 |
| --- | --- | --- |
| `FORBIDDEN` | 7,552 | 7,552 |
| `ORDINARY` | 542 | **4,570** (542 + 4,028) |
| `NEEDS_TRIBUTE` | 1,804 | 1,804 |
| `UNDETERMINED` | 4,229 | **201** |
| ↳ 스크립트 없음 | — | 153 |
| ↳ 제약 신호 있음 | — | 48 |

새로 허가된 4,028장의 레벨 분포: 1 레벨 572 · 2 레벨 570 · 3 레벨 950 ·
4 레벨 1,936.

### 8.2 거짓 허가 / 거짓 차단

| 축 | 수정 전 | 수정 후 |
| --- | --- | --- |
| 거짓 허가 (제약이 있는데 `ORDINARY`) | 0 | **0** (전수 역검산) |
| 거짓 차단 (제약이 없는데 `UNDETERMINED`) | 4,028 | **48** (안전한 쪽) |
| 정보 없어 보류 | (구분 못 함) | 153 |

## 9. 남은 BLOCKER — 이 Phase 가 고치지 않은 것

### BLOCKER-1 판 상태에 걸리는 소환 제약을 읽지 않는다

`assess_normal_summon` 은 **판을 보지 않는다** (설계). 그래서
`ORDINARY` 는 "이 카드 자신에게 제약이 없다" 는 뜻이고 "지금 소환해도
된다" 는 뜻이 **아니다**. 예:

- 레프티레스 서번트 `16008155` 가 앞면 표시로 있으면 **서로** 일반 소환
  할 수 없다
- 붉은 눈의 비룡 `67300516` 의 효과를 발동한 턴에는 그 플레이어가 일반
  소환할 수 없다

이 두 제약은 지속 효과 계층이 생겨야 걸린다. 테스트 `test_g01` 이 그
간격을 고정한다.

### BLOCKER-2 소환·세트 후보의 보류 이유가 보고되지 않는다

`Duel._withheld_board_actions` 는 `ACTIVATE_CARD` 만 한 줄 남긴다.
`summoning-condition` 으로 막힌 소환·세트 후보는 `withheld` 에 **적히지
않고 조용히 빠진다** (실측). 검증기에 직접 물으면 이유가 나온다 — 사라진
것은 판정이 아니라 **보고**다. 테스트 `test_e04` 가 측정한 대로 고정한다.

### BLOCKER-3 대체 일반 소환 절차가 없다

`EFFECT_SUMMON_PROC` · `EFFECT_LIMIT_SUMMON_PROC` 을 쓰는 카드(레벨 워리어
`97385276` · 뱀파이어 소서러 `88728507` · 도도도 보트 `19700943` ·
미스틱 스워드맨 LV4 `74591968`)는 그 절차가 없어 `UNDETERMINED` 다.

### BLOCKER-4 스크립트가 없는 153장

이 저장소의 Lua 코퍼스에 없는 카드는 증거를 만들 수 없다. 체츠커가 그
예다. 데이터가 채워지면 자동으로 갈린다 — 코드를 더 고칠 필요가 없다.

### BLOCKER-5 상수가 누구에게 걸리는지 모른다

파일 전체 긁기이므로 `EFFECT_CANNOT_SUMMON` 이 자신에게 걸리는지(고스트릭)
상대에게 걸리는지(인스펙트 보더) 구분하지 못한다. 25장이 그래서 과도하게
보류된다. 블록 단위 분석이 생기면 좁힐 수 있다.

## 10. §19 — 소환했다는 것과 효과가 발동했다는 것

기르수를 일반 소환했다고 해서 그 효과가 발동했다고 주장하지 않는다.
`test_e02` 가 소환 직후 **체인이 비어 있음**을 고정한다 (RULE-CHAIN-011 —
소환은 효과 발동이 아니다). 어니스트는 소환 **뒤에** 발동 후보로 올라가는
것을 확인했을 뿐이고, 그 발동을 해결한 것은 아니다.

## 11. §15 — 테스트 정책

### 11.1 새로 쓴 테스트

`tests/engine/test_effect_monster_normal_summon.py` (A–G 묶음).

| 묶음 | 무엇을 고정하는가 |
| --- | --- |
| A | 세 답이 서로 다르다 (`()` ≠ `None` ≠ 비어 있지 않음) |
| B | 바뀌지 않아야 하는 것 — 통상 · `TYPE_SPSUMMON` · 의식 · 엑스트라 덱 · 레벨 5+ · 손으로 만든 관측 · 정의 없음 |
| C | 관측이 그 사실을 싣고 왕복한다 (`None` 이 `[]` 로 변하지 않는다) |
| D | 검증기 — 소환과 세트가 **같은 판정**을 쓴다 · 소환권 · 빈 칸 · 페이즈 |
| E | 실제 Duel — 후보 · 실행 · 판 변화 · **체인이 비어 있다** (§19) |
| F | 코퍼스 전수 역검산 — 거짓 허가 0건 · 예외 목록이 낡지 않는다 |
| G | 남은 BLOCKER 를 테스트로 적는다 (판 상태 제약 · 대체 절차) |

### 11.2 고쳐야 했던 기존 테스트와 그 까닭

기존 테스트를 **삭제하지 않았고 skip 을 더하지 않았고 assertion 을 약화
하지 않았다.** 아래는 전부 "효과 몬스터는 전부 `UNDETERMINED`" 를 기대하던
테스트이고, 그 기대가 **왜 잘못된 가정이었는지** 적는다.

🔴 공통된 잘못된 가정: 그 테스트들은 "이 엔진에는 소환 제약을 읽는 계층이
없다" 를 "이 엔진은 어떤 효과 몬스터에도 제약이 있는지 모른다" 로 옮겨
적었다. **두 문장은 다른 사실이다.** 앞의 것은 맞았지만(지금도 조건부로
맞다), 뒤의 것은 **측정된 적이 없는 전제**였다 — 카드 자신의 스크립트에
제약 상수가 있는지는 이미 추출되어 있었고, 6-U 가 그것을 세기 전까지
아무도 보지 않았다.

### 11.3 측정 (실패 0)

| 묶음 | 수정 전 | 수정 후 |
| --- | --- | --- |
| `tests/engine` 전체 | 3,497 passed | **3,530 passed** (+33) |
| 루트 3파일 (`test_opening_duel_integration` · `test_unimplemented_rule_semantics_audit` · `agent/test_rule_based_ai`) | 94 passed | **95 passed** (+1) |
| 12파일 빠른 묶음 | 461 passed / **10 failed** | **473 passed** |
| 루트 chunk00 (27파일) | (측정 못 함, 아래 §13) | 626 passed / 2 failed → **1건은 6-U 가 고쳤고 1건은 6-U 이전부터 실패** |

늘어난 33건 = 새 파일 32 + `test_normal_summon.py` 에 더한 1건
(`test_an_effect_monster_whose_restriction_cannot_be_read_is_still_unknown`).
루트 +1 = `test_g01c`.

## 12. §12 — Discord `/combo` 경로의 실제 변화

6-T 의 선공 전개 경로(`deck/opening.py` 의 `execute_opening`)를 어니스트가
든 패로 돌린 결과다. **한 걸음에서 여섯 걸음으로** 늘었다.

```
1 activate_effect  55144522 욕망의 항아리  acc=True gate=OK eff=('55144522:e[0]',) res=True
2 normal_summon    37742478 어니스트      acc=True gate=OK eff=()                res=True
3 activate_effect  37742478 어니스트      acc=True gate=OK eff=('37742478:e[0]',) res=True
4 set_spell_trap    5915629 욕망의 선물    acc=True gate=OK eff=()                res=True
5 set_spell_trap    5915629 욕망의 선물    acc=True gate=OK eff=()                res=True
6 set_spell_trap    5915629 욕망의 선물    acc=True gate=OK eff=()                res=True

stopped: 판을 바꿀 후보가 더 없습니다 — 남은 후보는 흐름뿐입니다
         (['end_phase']). 전개가 여기서 끝났다는 뜻이고, 막힌 것이 아닙니다.
```

🔴 **§19 가 구조로 보존된다.** 2번 걸음(소환)의 `effect_events` 는 **비어
있고**, 발동은 **3번이라는 다른 걸음**이다. 즉 "기르수를 일반 소환했으므로
그 효과도 발동했다" 는 주장이 이 기록에서는 **구조적으로 불가능하다.**
기록(`EventJournal`)의 `EFFECT` 사건 두 건은 걸음들이 적은
`effect_events` 의 합과 정확히 같다 (`test_e03` 이 양쪽을 맞댄다).

## 13. 🔴 6-U 가 만들지 않은, 이전부터 있던 실패 1건

`tests/agent/test_opponent_resource_weighting_audit.py`
`::test_07_a_whole_duel_never_offers_a_choice_about_opponent_resources`

### 13.1 6-U 가 원인이 아니라는 증거

수정한 프로덕션 3파일을 `5a145a5`(6-U 시작 시점) 버전으로 **임시 교체**해
같은 테스트를 돌렸다. 똑같이 실패한다.

```
# 5a145a5 버전의 core/card_model.py · engine/game_state_view.py ·
# engine/summon_rules.py 로 교체한 상태
FAILED ...::test_07_a_whole_duel_never_offers_a_choice_about_opponent_resources
1 failed in 6.69s
```

(교체 뒤 `git checkout HEAD --` 로 복원했고 작업 트리가 깨끗함을 확인했다.
커밋되지 않은 작업을 버린 것이 아니라 **커밋된 내용을 되찾은 것**이다.)

### 13.2 실제 원인 (계측)

그 감사는 "결정마다 후보들의 상대 자원 결과가 **언제나 한 가지**" 임을
고정한다. 듀얼 전체를 돌려 2가지가 나오는 결정을 찾으면 **정확히 한 건**이다.

```
턴 5 DRAW 페이즈
  (drawn=2, hand=9)  <- activate_effect 5915629 (욕망의 선물)
  (drawn=0, hand=7)  <- end_phase
```

세트된 「욕망의 선물」(통상 함정 — 상대가 덱에서 2장 드로우)을 드로우
페이즈에 발동할 수 있게 되면서, 상대 자원을 **바꾸는** 선택지와 바꾸지
않는 선택지가 같은 결정에 함께 올라온다. 같은 파일의 `test_08` 이
"막고 있는 것이 가중치가 아니다 ... 발동 계층이다" 라고 적어 둔 그 계층이
열린 것이다.

즉 이것은 **한계 주장이 무효가 된 것**이고(6-T 의 `test_g01` 과 같은
모양), 어느 이전 Phase 가 열었는지는 이 Phase 가 특정하지 않았다.

### 13.3 왜 아무도 몰랐는가

루트 전체 테스트가 한 번에 돌지 않았다. 이 저장소의 루트 묶음은 코퍼스
감사(12,972 스크립트 · 14,127 카드)가 많아 **한 시간을 넘긴다.** 이번
Phase 에서 전체 루트 실행이 60분 한도에 걸려 결과 없이 중단되었고, 그래서
묶음을 나눠 돌리는 쪽으로 바꿨다 — 그 과정에서 이 실패가 드러났다.

### 13.4 6-U 가 이것을 고치지 않는 이유

소환 조건 Phase 에서 **에이전트 평가 계층의 감사 기준을 바꾸는 것**은
범위를 조용히 넓히는 일이다. 그 감사가 묻는 질문("에이전트가 상대 자원을
옳게 저울질하는가")은 이제 **살아 있는 질문**이 되었고, 답하려면 평가
계층을 봐야 한다. 테스트를 고쳐 통과시키지 않았고, 삭제하지도 약화하지도
않았다. 그대로 두고 여기 적는다. §20 에서 다음 Phase 후보로 올린다.

## 13-A. 루트 chunk01 (26파일) — 7건 실패, 셋만 6-U 의 것

| 테스트 | 원인 | 조치 |
| --- | --- | --- |
| `test_clone_sibling_contamination_audit::test_31` | 🔴 **6-U** — `CardDefinitionView` 칸 수 26→27 | 핀 갱신 + 금지 목록에 `effect_codes` 추가 |
| `test_create_effect_ordinal_audit::test_27` | 🔴 **6-U** — 같음 | 같음 |
| `test_event_free_chain_semantic_audit::test_07` | 🔴 **6-U** — 같음 | 같음 |
| `test_event_free_chain_semantic_audit::test_12` | Lua 코퍼스 드리프트 | 통상 마법 975→977 · 지속 마법 468→469 |
| `test_event_free_chain_semantic_audit::test_13` | Lua 코퍼스 드리프트 | 통상 함정 917→918 |
| `test_event_free_chain_semantic_audit::test_27` | **데이터 없음** | 🔴 **고치지 않았다** (아래 13-A.3) |
| `test_effect_type_quick_audit::test_29` | **데이터 없음** | 🔴 **고치지 않았다** |

### 13-A.1 6-U 가 원인이 아님을 어떻게 확인했는가

프로덕션 3파일을 `5a145a5` 버전으로 **임시 교체**해 네 건을 다시 돌렸다.
넷 전부 똑같이 실패한다.

```
# 5a145a5 버전으로 교체한 상태
FAILED ...test_12_spell_corpus_activate_blocks_are_unanimous   E assert ('통상 마법', {True: 977})
FAILED ...test_13_trap_corpus_and_the_counter_trap_counter_example  E assert 918 == 917
FAILED ...test_27_the_official_corpus_never_uses_the_term       E assert 15 >= 600
FAILED ...test_29_the_lua_names_are_absent_from_official_material  E assert 15 >= 800
4 failed in 3.87s
```

교체 뒤 `git checkout HEAD --` 로 복원하고 작업 트리가 깨끗함(0개 변경)을
확인했다. **커밋되지 않은 작업을 버린 것이 아니라 커밋된 내용을 되찾은
것이다.**

### 13-A.2 코퍼스 드리프트 두 건 (`test_12` · `test_13`)

Lua 스크립트 코퍼스는 `.gitignore` 대상이고 컨테이너마다 다시 내려받는다.
그 사이 카드가 늘어 `ACTIVATE` 블록 수가 움직였다 (통상 마법 +2 · 지속
마법 +1 · 통상 함정 +1). 6-T 가 `archetype_setcode_constants.lua` 615→616
을 처리한 것과 **같은 성격**이다.

🔴 **두 시험의 결론은 하나도 약해지지 않았다.** 그것이 주장하는 것은 절대
수가 아니다.

- `test_12` 는 **만장일치**를 주장한다 → `per[label][False] == 0` 가 다섯
  종류 전부에서 여전히 참이다 (그 단언은 건드리지 않았다)
- `test_13` 은 **카운터 함정과의 대비**를 주장한다 → `EVENT_CHAINING` 144 ·
  `FREE_CHAIN` 3/210 이 그대로다 (그 단언들도 건드리지 않았다)

측정값(픽스처 `typed_cards` = `repository._cards.values()` 기준, alias 포함):

```
통상 마법 {True: 977}   장착 마법 {True: 32}   지속 마법 {True: 469}
필드 마법 {True: 312}   의식 마법 {True: 5}
통상 함정 {True: 918, False: 390}
카운터 함정 EVENT_CHAINING 144 · FREE_CHAIN 3 · 합 210
```

### 13-A.3 🔴 고치지 않고 남긴 두 건 (`test_27` · `test_29`)

두 시험은 `data/rules` · `data/rulings` · `data/ko` 의 파일을 세어
`scanned >= 600` (또는 `>= 800`) 을 요구한다. 측정된 `scanned` 는 **15** 다.

```
data/rules:   3 파일
data/rulings: 11 파일   (전부 data/rulings/ocg/, git 추적 11건)
data/ko:      1 파일
            ───────────
              15
```

🔴 **15는 커밋된 파일 수와 정확히 같다.** 두 시험이 전제하는 829파일은
`.gitignore` 에 적힌 `data/rulings/.cache/` 의 **크롤 결과**이고, 신규
컨테이너에는 존재하지 않는다. 즉 **깨끗한 체크아웃에서 통과할 수 없는
구조**이고, 이것은 6-U 가 만든 문제도 프로덕션 코드의 결함도 아니다 —
시험이 커밋되지 않은 로컬 데이터에 의존한다.

세 가지 손댈 방법이 있었고 **셋 다 하지 않았다.**

| 가능한 조치 | 왜 하지 않았는가 |
| --- | --- |
| `scanned` 임계값을 15로 낮춘다 | **threshold 완화 금지.** 그리고 15파일에서 0건을 찾는 것은 "많은 공식 자료에 그 용어가 없다" 를 전혀 증명하지 못한다 — 시험의 의미가 사라진다 |
| `data/rulings/.cache/` 를 크롤로 채운다 | 사용자가 `scripts/fetch_ocg_rulings.py --all` (14,000장 크롤) 실행을 금지했다 |
| 데이터가 없으면 skip 한다 | **skip 추가 금지.** 그리고 실패를 가리는 일이다 |

그래서 **실패한 채로 남겨 두고 여기 적는다.** 판단이 필요한 자리이므로
사용자에게 올린다 — 선택지는 (가) 크롤 1회 허용, (나) 축소된 재정 묶음을
저장소에 커밋, (다) 이 두 시험을 "로컬 데이터 필요" 로 명시적으로 분류하는
구조를 만드는 것(그러면 `skip` 이 숨김이 아니라 **분류**가 된다)이다.

## 13-B. 루트 chunk02 (26파일) — 6건 실패, **6-U 가 만든 것은 0건**

```
6 failed, 573 passed, 9 skipped in 1033.20s (0:17:13)
```

| 테스트 | 원인 | 6-U 가 만들었나 |
| --- | --- | --- |
| `test_korean_overlay_display_boundary_audit::test_21_no_existing_test_was_modified_or_deleted` | 감사가 **움직이는 `HEAD`** 와 비교한다 | **아니다** (아래 13-B.1) |
| `test_korean_overlay_return_value_audit::test_11_the_sole_discarded_apply_claim_is_scoped_to_production` | `PRODUCTION_DIRS` 에 `deck` 이 없다 | **아니다** — 6-T 가 `deck/` 를 만들었다 |
| `test_korean_overlay_unapplied_audit::test_01` | 카드 DB / ko 오버레이 드리프트 | **아니다** |
| `test_korean_overlay_unapplied_audit::test_13` | 같음 | **아니다** |
| `test_korean_overlay_unapplied_audit::test_21` | 같음 | **아니다** |
| `test_korean_overlay_unapplied_audit::test_25` | 같음 | **아니다** |

### 13-B.1 `test_21` — 감사가 자기 Phase 가 아니라 `HEAD` 를 본다

이 감사는 3-F-44 Phase 가 **기존 테스트를 수정하지 않았음**을 주장한다.
그런데 끝점을 `counts("HEAD")` 로 잡아서, **그 뒤의 모든 Phase** 가 기존
파일에 테스트를 한 건이라도 더하면 깨진다.

`def test_` 개수를 시점별로 직접 세어 보면:

| 시점 | 달라진 테스트 파일 |
| --- | --- |
| 3-F-44 자신의 마지막 커밋 `cdeaf7a7` | **0개** ← 🔴 감사의 **실제 주장은 참이다** |
| `5a145a5` (6-U 시작 전) | **1개** — `tests/engine/test_random_selection.py` 37→38 ← **이미 실패하고 있었다** |
| HEAD (6-U 적용 후) | 2개 — 위의 한 건 + `tests/engine/test_normal_summon.py` 59→60 |

즉 **6-U 전에 이미 빨간불**이었고, 6-U 는 이미 실패하던 단언에 줄 하나를
더했을 뿐이다. 6-U 가 더한 그 한 건은 `test_an_effect_monster_whose_
restriction_cannot_be_read_is_still_unknown` — 체츠커로 보류 경로를 고정하는
**정당한 추가**다.

🔴 **고치지 않았다.** 고치려면 감사의 끝점을 `shas[0]` 로 바꿔야 하는데
그것은 범위 밖의 assertion 변경이다. 되돌리려면 정당한 테스트 추가를
지워야 하므로 그쪽도 하지 않는다.

### 13-B.2 `test_11` — `PRODUCTION_DIRS` 에 `deck` 이 없다

```
PRODUCTION_DIRS = ("analysis","app","core","engine","rules","rulings",
                   "scripts","sources","agent")
```

`rows` 에 `('deck/opening.py', 352, False)` 가 들어 있는데 `deck` 이 목록에
없어 `len(prod) + len(tests) == len(rows)` 가 **12 + 339 ≠ 354** 로 깨진다.
`deck/` 는 **6-T** 가 만든 패키지다. 6-U 는 `deck/` 를 한 줄도 고치지 않았다.

### 13-B.3 드리프트 4건 — 카드 DB 가 4장 늘었다

```
load 레코드   14,514 → 14,518   (+4)
합계 모집단   14,755 → 14,759   (+4)
```

`data/cards.cdb` 는 `.gitignore` 대상이고 컨테이너마다 다시 내려받는다
(`python -m scripts.fetch_official_db`). 그 사이 카드가 4장 늘었다.

### 13-B.4 판별 방법 — 5건 전부 `5a145a5` 에서도 동일하게 실패

프로덕션 3파일을 `5a145a5` 버전으로 임시 교체해 다시 돌렸다. **숫자까지
똑같다.**

```
# 5a145a5 버전으로 교체한 상태
E assert (12 + 339) == 354
E AssertionError: {'ko 항목': 13899, 'load 레코드': 14518, '오버레이 적용': 13892, 'canonical 카드': 14127}
E assert 14759 == 14755
E assert 14759 == 14755
E assert (14518 + 241) == 14755
5 failed, 30 passed, 4 skipped in 106.89s
```

(`test_21` 은 git 이력을 보는 감사라 프로덕션 교체로는 판별되지 않으므로
위 13-B.1 처럼 `def test_` 개수를 시점별로 직접 셌다.)

교체 뒤 `git checkout HEAD --` 로 복원하고 작업 트리가 깨끗함(0개 변경)을
확인했다.

## 13-C. 루트 chunk03 (24파일) — 2건 실패, **둘 다 6-U 의 것**

```
2 failed, 554 passed in 779.82s (0:12:59)
```

| 테스트 | 원인 | 조치 |
| --- | --- | --- |
| `test_settype_clone_contamination_audit::test_31_hidden_information_and_view_are_unchanged` | 🔴 **6-U** — 칸 수 26→27 | 핀 갱신 + `effect_codes` 금지 추가 |
| `test_variable_rebinding_audit::test_32_hidden_information_and_the_view_are_unchanged` | 🔴 **6-U** — 같음 | 같음 |

고친 뒤 둘 다 통과한다. 금지 목록은 약해지지 않았고 한 줄 늘었다.

## 13-D. §9 변이 테스트 — **15/15 전부 죽었다**

내가 쓴 프로덕션 코드가 실제로 지켜지는지 보려고 변이 15개를 넣고 각각
테스트를 돌렸다. 살아남은 변이가 **0건**이다.

| 변이 | 무엇을 망가뜨리는가 | 결과 |
| --- | --- | --- |
| M1 | `script is None` → `()` 로 합친다 (§6 상황1/2 혼동) | **KILLED** |
| M2 | `EFFECT_CANNOT_SSET` 을 감시 목록에서 뺀다 | **KILLED** |
| M3 | `EFFECT_CANNOT_SUMMON` 을 뺀다 | **KILLED** |
| M4 | `EFFECT_LIMIT_SUMMON_PROC` · `EFFECT_SUMMON_PROC` 을 뺀다 | **KILLED** |
| M5 | 관측이 신호를 안 싣는다 (항상 `None`) | **KILLED** |
| M6 | 관측이 신호를 `()` 로 싣는다 (전부 허가) | **KILLED** |
| M7 | `canonical_state` 가 신호를 빼먹는다 | **KILLED** |
| M8 | `to_dict` 가 `None` 을 `[]` 로 적는다 | **KILLED** |
| M9 | 신호가 있어도 허가한다 | **KILLED** |
| M10 | 스크립트가 없어도 허가한다 | **KILLED** |
| M11 | 레벨 검사를 건너뛴다 (레벨 5+ 가 제물 없이 통과) | **KILLED** |
| M12 | 통상 몬스터 갈래를 지운다 | **KILLED** |
| M13 | `ORDINARY` 대신 `UNDETERMINED` 를 돌려준다 (수정 무효화) | **KILLED** |
| M14 | `FORBIDDEN` 종류 검사를 지운다 (`TYPE_SPSUMMON` 통과) | **KILLED** |
| M15 | `missing_rule` 을 빼먹는다 | **KILLED** |

🔴 **M1 · M6 · M9 · M10 이 이 Phase 의 핵심 불변식을 지킨다** — "제약 없음"
과 "정보 없음" 을 합치거나, 모름을 조용히 허가로 바꾸는 변이는 전부 죽는다.

방법: 원본을 **메모리에 들고** 변이를 쓰고, `finally` 에서 되돌린 뒤
`assert path.read_text() == original` 로 복원을 확인했다. `git checkout --`
를 쓰지 않았다 (커밋되지 않은 작업을 버릴 위험이 있다). 변이가 적용된 채로
다른 테스트를 돌리지 않았다.

## 13-E. 부록 — 재정 데이터 재배포 조사 (6-U 의 소환 판정과 **분리된** 사안)

🔴 **이 절은 6-U 의 소환 조건 판정과 무관하다.** `test_27` · `test_29`
(13-A.3) 를 어떻게 할지 결정하기 위한 조사 기록이고, 이 Phase 는 그
두 테스트와 재정 데이터를 **한 줄도 바꾸지 않았다.**

### 13-E.1 커밋된 11파일의 정체

`scripts/fetch_ocg_rulings.py` 의 머리말이 직접 말한다.

```
# 샘플 (저장소에 커밋되는 검증용 표본)
python -m scripts.fetch_ocg_rulings --sample
```

즉 `data/rulings/ocg/` 의 11파일은 **이미 fixture 다** — 파싱 검증용으로
의도적으로 커밋된 표본이고, `--all` 의 크롤 캐시만 `.gitignore` 로 제외된다.
`bb7796a` 의 커밋 메시지도 "db.yugioh-card.com 에서 **두 장만** 받아
확인했다 (`--card-id`, `--all` 아님)" 이라고 적는다.

### 13-E.2 재배포 허용 여부 — **확인되지 않는다**

| 확인 항목 | 결과 |
| --- | --- |
| 공식 DB 저작권 표시 | `©2026 Konami Digital Entertainment.` · `©2020 Studio Dice/SHUEISHA, TV TOKYO, KONAMI.` |
| DB 이용 조건 | **이용 약관 동의 필수** — "To use Yu-Gi-Oh! Neuron(TRADING CARD GAME CARD DATABASE), you must agree to the Terms of Use." |
| DB 페이지의 라이선스·재배포 조항 | **없음** |
| 약관 본문 | 🔴 **읽지 못했다.** `legal.konami.com` · `www.konami.com` 이 이 환경의 네트워크 정책에서 차단된다 (`getaddrinfo ENOTFOUND`) |
| 저장소 `LICENSE` / `NOTICE` | **없음** |
| 저장소 자체의 태도 | `.gitignore` — "원본 룰북 PDF 는 **저작물이라** 저장소에 넣지 않는다. 추출 결과만 커밋한다" |

저작권 주장과 필수 약관은 확인됐고 **허용 조항은 확인할 수 없었다.**
그래서 재정 데이터를 **한 건도 커밋하지 않았고**, 기존 캐시 파일을 추적
대상으로 바꾸지도 않았다.

### 13-E.3 🔴 fixture 로는 이 두 테스트의 주장을 담을 수 없다

두 테스트가 주장하는 것은 **"공식 코퍼스 전체에 그 용어가 없다"** 는 전수
부정이다 (`QUICK_O` 는 공식 용어가 아니다 · `free chain` 은 공식 표현이
아니다). fixture 는 **고른 데이터**이므로 "내가 고른 데이터에 없다" 는
공식 용어 여부를 증명하지 못한다.

그래서 **실제 공식 재정을 검증하는 테스트**(전수 부정)와 **fixture 기반
구조 테스트**(훑는 기계가 작동하는가)는 서로 다른 것이고, 뒤의 것으로 앞의
것을 대체하면 통과하는 테스트가 더 적게 증명한다. 대체하지 않았다.

### 13-E.4 그런데 측정하면 깨진 것은 **대리 지표**다

커밋된 공식 자료만으로 실제 내용을 쟀다.

```
커밋된 공식 자료 15파일 · 7,978 KB (≈8.0 MB)
  data/rules/documents/sd-rulebook-en-v10.json    117 KB   공식 영문 룰북
  data/rules/{index,structured}/*.json             25 KB
  data/rulings/ocg/*.json (11파일)              1,328 KB   (4909.json 혼자 636 KB)
  data/ko/ko-KR.json                           6,506 KB   공식 한국어 카드 텍스트 전량

Lua 이름 적중 (QUICK_O · QUICK_F · TRIGGER_O · TRIGGER_F · EFFECT_TYPE): 0건
"free chain" / "freechain" 적중: 0건

양성 대조 — 공식 어휘는 실제로 잡힌다
  룰북:     Quick Effect ✓  Spell Speed ✓  Ignition Effect ✓
            Trigger Effect ✓  Flip Effect ✓
  재정 표본: 誘発即時 ✓  誘発効果 ✓
```

🔴 **두 테스트는 파일 *개수*를 세는데, 주장은 공식 텍스트의 *분량*에 관한
것이다.** `scanned >= 600` / `>= 800` 은 작은 HTML 캐시 파일 829개에 맞춰
교정된 **대리 지표**이고, 지금 커밋된 15파일은 8.0 MB 의 공식 텍스트를
담으면서 적중 0건이며 양성 대조가 전부 작동한다.

즉 **주장의 실체는 이미 깨끗한 체크아웃에서 검증 가능하고, 깨진 것은 파일
개수라는 대리 지표뿐이다.**

### 13-E.5 결론과 남긴 결정

올바른 수정은 fixture 도 임계값 인하도 아니라 **대리 지표를 바꾸는 것**
— 파일 개수 대신 훑은 공식 텍스트의 분량과 양성 대조를 재는 것이다. 주장을
**강화**하는 방향이지만 어쨌든 assertion 변경이므로, 승인 없이 손대지
않았다. 두 테스트는 실패한 채로 남아 있다.

하지 않은 것: 재정 데이터 커밋 · 캐시 파일 추적 전환 · 임계값 인하 ·
skip 추가 · assertion 완화 · 크롤 실행 · 6-U 소환 판정 로직과의 혼합.

## 14. §15 — 거짓 성공 점검

각 항목에 **무엇으로 확인했는지**를 함께 적는다. 확인하지 않은 것은
"확인하지 않았다" 고 적는다.

| 주장하지 않는 것 | 어떻게 확인했는가 |
| --- | --- |
| "모든 효과 몬스터를 일반 소환할 수 있다" | 201장이 그대로 `UNDETERMINED` 다. `test_f05` 가 신호를 가진 카드 전부에 `permits_procedure is False` 를 요구한다 |
| "카드 텍스트의 소환 제약을 읽는다" | 읽지 않는다. 읽는 것은 **스크립트의 상수 등장 여부**다. 그것이 누구에게 걸리는지는 모른다 (BLOCKER-5) |
| "지금 소환해도 된다" | `assess_normal_summon` 은 판을 보지 않는다. `test_g01` 이 그 간격을 고정한다 (BLOCKER-1) |
| "기르수의 효과가 발동했다" | 소환 걸음의 `effect_events` 가 비어 있고 체인이 0이다 (`test_e02` · `test_g01`) |
| "마그나의 유발 효과가 해결된다" | `entry_for(MAGNA) is None` — 등재가 없다 (ADR-006). `test_09` 가 소환과 해결을 따로 잰다 |
| "거짓 허가가 없다" | 4,028장 전수를 공식 텍스트 8표현으로 역검산했고 자기 제약 0건. `test_f02` 가 회귀로 고정하고 `test_f03` 이 예외 목록의 노후화를 막는다 |
| "제물 소환을 구현했다" | 하지 않았다. `NEEDS_TRIBUTE` 1,804장 그대로 (`test_b04`) |
| "특수 소환을 구현했다" | 하지 않았다. 범위 밖이다 |
| "덱 합법성을 완전히 검증했다" | 6-T 와 같다 — 금지·제한 데이터가 없다 |
| "실제 셔플로 뽑은 패다" | 아니다. 6-T 의 `unknowns` 가 그대로 적는다 |
| "루트 테스트 전체가 통과한다" | **확인하지 않았다.** chunk00(27파일)만 돌렸고 1건이 6-U 이전부터 실패한다 (§13). chunk01~03 은 진행 중 |

## 15. §9 금지 사항 점검

| 금지된 것 | 지켰는가 |
| --- | --- |
| 소환 전용 카드 ID 화이트리스트 | 만들지 않았다. 프로덕션에 카드 ID 가 한 개도 없다 |
| 카드 종류만으로 모든 소환 가능성을 단정 | 하지 않았다. 종류 갈래(`NORMAL` · `SPSUMMON` · `RITUAL` · `TOKEN`)는 6-C 가 만든 **기존** 갈래이고, 새 갈래는 **카드별 증거**를 본다 |
| 임의의 문자열 포함 여부로 최종 판정 확정 | 하지 않았다. 문구는 **검산**에만 썼고, 그 사실을 `_FORBIDDING_PHRASES` 주석에 적었다 |
| 새로운 소환 엔진 | 만들지 않았다. `engine/normal_summon.py` · `engine/summon.py` 를 한 줄도 고치지 않았다 |
| 모든 특수 소환·엑스트라 덱 소환 구현 | 하지 않았다 |
| 새 정적 분석기 (기존 Effect Analysis 와 중복) | 만들지 않았다. `analysis/` 를 건드리지 않았고, 쓴 데이터는 `sources/lua_loader.py` 가 이미 채우던 것이다 |
| `UNKNOWN` 을 임의로 true/false 로 처리 | 하지 않았다. `None` 과 `()` 를 **구조적으로** 분리했고, 합치는 변이(M1)를 테스트가 죽인다 |
| 테스트를 수정해서 통과시키기 | 하지 않았다. 10건은 **판정이 규칙상 바뀌어서** 기대가 바뀐 것이고, 각 자리에 까닭을 적었다. 6-U 가 만들지 않은 실패 1건은 **고치지 않고 그대로 두고 보고했다** (§13) |

## 16. §20 — 다음 Phase 후보

**A. 지속 효과 · 판 상태 소환 제약 (BLOCKER-1)** — 지금 `ORDINARY` 는
"카드 자신에게 제약이 없다" 까지만 말한다. 레프티레스 서번트가 필드에
있을 때 소환이 막히는 것, 붉은 눈의 비룡의 효과를 발동한 턴에 그 플레이어가
막히는 것을 읽는 계층이 없다. 6-U 가 허가를 4,028장 늘렸으므로 **이
간격이 실제로 닿는 범위도 그만큼 넓어졌다.** 가장 시급하다.

**B. 에이전트 상대 자원 저울질 (§13)** — `test_07` 이 고정했던 한계가
무효가 되었다. "상대에게 이득을 주는 선택지" 가 실제로 후보에 오르는데
평가 계층이 그것을 옳게 저울질하는지는 **검증된 적이 없다.** 6-U 범위가
아니어서 손대지 않았다.

**C. 제물 소환 절차 (BLOCKER-3 의 이웃)** — `NEEDS_TRIBUTE` 1,804장이
그대로 막혀 있고, `tributes_required` 가 이미 몇 장인지 적어 둔다. 선공
전개의 폭을 넓히는 쪽으로는 이것이 가장 크다.

🔴 **다음 Phase 는 자동으로 시작하지 않는다.** 사용자의 지시를 기다린다.

## 17. 측정 완료 현황

🔴 **커밋 시점에 끝나지 않은 측정을 "끝났다" 고 적지 않는다.** 아래는
최종 상태다.

| 항목 | 상태 |
| --- | --- |
| `tests/engine` 전체 | **완료** — 3,530 passed / 0 failed / 592.00s |
| 새 파일 32건 | **완료** — 32 passed / 5.28s |
| 12파일 빠른 묶음 | **완료** — 473 passed / 141.52s |
| 루트 chunk00 (27파일) | **완료** — 626 passed / 2 failed |
| 루트 chunk01 (26파일) | **완료** — 761 passed / 7 failed |
| 루트 chunk02 (26파일) | **완료** — 573 passed / 6 failed |
| 루트 chunk03 (24파일) | **완료** — 554 passed / 2 failed |
| 최종 회귀 (6-U 가 건드린 루트 10파일) | **완료** — 346 passed / 2 failed |
| §9 변이 테스트 15건 | **완료** — 15/15 KILLED, 생존 0 |
| 루트 전체를 한 번에 | 🔴 **하지 않았다** — 60분 한도에 걸려 결과 없이 중단됐고, 103파일을 4묶음으로 나눠 전부 돌렸다 (§13-A.3 의 설명) |

### 17.1 성공 수준 판정

**수준 3** 으로 판단한다. 근거:

1. §2 의 전제를 실제 Duel 로 재현했고, §17 이 요구한 "원인이 다른 계층인가"
   를 먼저 확인했다 (실행 경로는 이미 동작했고 막던 것은 판정 하나였다)
2. 규칙 근거가 확인된 범위에서만 열었다 — RULE-SUMMON-009 의 "most Effect
   Monsters (unless they have a specific restriction)" 를 **카드별 증거**로
   판정했고, 거짓 허가를 4,028장 전수 역검산해 **0건**을 확인했다
3. `UNKNOWN` 을 허가로 바꾸지 않았다 — 201장이 남았고, 그것이 **옳다**는
   것을 체츠커 한 장으로 증명했다 (`()` 와 `None` 을 합쳤다면 조용히
   허가됐을 카드)
4. 어니스트와 기르수가 실제로 필드에 나오는 것을 측정했고, **소환과 효과
   발동이 다른 사실임**을 구조로 보존했다 (기르수는 소환 후에도 발동 후보가
   생기지 않는다)
5. 변이 15/15 가 죽었다 — 핵심 불변식이 테스트로 지켜진다
6. 금지 사항을 하나도 어기지 않았다 (§15 의 표)

🔴 **낮추는 요소도 적는다.** 재정 데이터 의존 테스트 2건이 미해결이고,
BLOCKER 5건이 남아 있고, 루트 전체를 한 번의 명령으로 통과시키지는 못했다
(묶음으로 나눠 전부 돌렸다). 이 셋 중 어느 것도 6-U 가 만든 것은 아니지만,
"저장소 전체가 녹색이다" 라고 말할 수 없다는 사실은 그대로다.

🔴 **다음 Phase 는 자동으로 시작하지 않는다.** §16 의 A/B/C 를 후보로
올려 두고 사용자의 지시를 기다린다.

## 18. 최종 결과 — 요청된 여섯 구분

### 18-1. Phase 6-U 의 소환 기능 테스트 결과

이 Phase 가 **기능으로서** 검증한 것만 적는다.

| 묶음 | 수정 전 | 수정 후 | 실패 |
| --- | --- | --- | --- |
| `tests/engine` 전체 | 3,497 passed | **3,530 passed** | 0 |
| 루트 3파일 (소환 관련) | 94 passed | **95 passed** | 0 |
| 12파일 빠른 묶음 | 461 passed / 10 failed | **473 passed** | 0 |
| 새 파일 `test_effect_monster_normal_summon.py` | (없었음) | **32 passed** | 0 |

새 파일 32건의 구성은 §11.1 의 표(A–G)와 같다. 늘어난 33건 = 새 파일 32 +
`test_normal_summon.py` 에 더한 1건. 루트 +1 = `test_g01c`.

### 18-2. 🔴 기존 재정 데이터 의존 테스트 2건 — **미해결**

| 테스트 | 상태 |
| --- | --- |
| `tests/test_event_free_chain_semantic_audit.py::test_27_the_official_corpus_never_uses_the_term` | **FAILED** (`assert 15 >= 600`) |
| `tests/test_effect_type_quick_audit.py::test_29_the_lua_names_are_absent_from_official_material` | **FAILED** (`assert 15 >= 800`) |

- **6-U 가 만든 실패가 아니다.** 프로덕션 3파일을 `5a145a5` 버전으로 임시
  교체해도 동일하게 실패한다 (§13-A.1 에 실행 출력).
- **원인은 코드가 아니라 테스트 환경이다.** 두 시험은 `data/rulings/.cache/`
  의 크롤 결과 814파일에 의존하고, 그 경로는 `.gitignore` 대상이다.
  `scanned` 15 는 커밋된 파일 수(ocg 11 + rules 3 + ko 1)와 정확히 같다.
- **이 Phase 는 두 시험의 검증 기준을 바꾸지 않았다.** 삭제·skip·assertion
  완화·임계값 인하를 하지 않았고, 재정 데이터를 커밋하지 않았으며, 크롤을
  실행하지 않았다. 소환 판정 수정과 **분리해** 두었다.

#### 🔴 두 주장을 섞지 않는다

조사 과정에서 "이미 커밋된 자료에서 공식 어휘가 실제로 추출된다" 는 사실을
측정했다 (§13-E.4). **그것은 전혀 다른 주장이다.**

| 측정으로 확인한 것 | 확인하지 **못한** 것 |
| --- | --- |
| 커밋된 공식 자료 15파일(7,978 KB) 안에서 룰북의 `Quick Effect` · `Spell Speed` · `Ignition Effect` · `Trigger Effect` · `Flip Effect` 와 재정 표본의 「誘発即時」 · 「誘発効果」 가 **추출된다** | 공식 재정 데이터 **전체가 저장소에 있다**는 것 |
| 그 15파일 안에서 Lua 이름과 `free chain` 이 **0건**이다 | 공식 코퍼스 **전체**에 그 용어가 없다는 **전수 부정** |
| 즉 **훑는 기계와 양성 대조가 작동한다** | 즉 **재정 데이터의 완전성** |

앞의 것은 **구조 확인**이고 뒤의 것은 **데이터 완전성 검증**이다. 앞의 것이
참이라는 이유로 `test_27` · `test_29` 가 주장하는 전수 부정이 증명되지
않는다. 그래서 두 시험을 통과시키지 않고 **실패한 채로 남겼다.**

### 18-3. 실제 어니스트 · 기르수 일반 소환 실행 결과

선공 메인 페이즈 1 까지 `END_PHASE` 를 실제로 적용해 걸어간 뒤
(`Duel.start(seed=11)`, 덱 40장 단일 카드) 후보를 받아 적용한 실측이다.

| 항목 | 어니스트 `37742478` | 기르수 `69811710` |
| --- | --- | --- |
| `normal_summon` 후보 | 5건 | 5건 |
| `DuelStep` | `accepted=True` `code=ok` | `accepted=True` `code=ok` |
| 필드 | `(37742478, FACEUP_ATTACK)` | `(69811710, FACEUP_ATTACK)` |
| 소환권 | `(0,0)` → `(1,0)` | `(0,0)` → `(1,0)` |
| 패 | 5 → 4 | 5 → 4 |
| 체인 · pending | **0 · 0** | **0 · 0** |
| 소환 **후** 후보 | `activate_effect` · `end_phase` | **`end_phase` 뿐** |

🔴 **마지막 줄이 §19 의 증거다.** 두 카드 모두 일반 소환은 되지만, 소환
직후 체인은 **비어 있다** — 소환은 효과 발동이 아니다 (RULE-CHAIN-011).
그리고 기르수는 소환 뒤에도 **발동 후보가 하나도 생기지 않는다**: 그 효과가
등재되어 있지 않기 때문이다 (`entry_for(GIRSU) is None`, ADR-006). 어니스트
쪽만 `activate_effect` 가 생기고, 그것은 6-L 이 등재한 효과다.

즉 **"기르수를 일반 소환했다"** 와 **"기르수의 효과가 발동했다"** 는 이
엔진에서 서로 다른 사실이고, 뒤의 것은 **아직 일어날 수 없다.**

6-T 의 선공 전개 경로(`/combo` 가 쓰는 `execute_opening`)에서의 변화는
§12 에 걸음 단위로 적었다 — 1걸음 → 6걸음, 소환 걸음의 `effect_events` 는
비어 있고 발동은 별개의 걸음이다.

### 18-4. 신규 소환 가능 판정의 정확성과 `UNKNOWN` 유지

**정확성 — 거짓 허가 0건.** 새로 허가한 4,028장 전수의 공식 한국어/영어
텍스트를 여덟 표현으로 역검산했고, 자기 자신의 일반 소환을 금지하는 카드가
**0장**이다. 걸린 7장은 전부 다른 사실이었다 (§5.4 의 카드별 표).

| 축 | 수정 전 | 수정 후 |
| --- | --- | --- |
| 거짓 허가 (제약이 있는데 `ORDINARY`) | 0 | **0** |
| 거짓 차단 (제약이 없는데 `UNDETERMINED`) | 4,028 | **48** |
| 정보가 없어 보류 | (구분 못 함) | **153** |

**`UNKNOWN` 유지 — 201장.** 메인덱 몬스터 7,067장 기준:

| 판정 | 수정 전 | 수정 후 |
| --- | --- | --- |
| `ORDINARY` | 542 | **4,570** |
| `UNDETERMINED` | 4,229 | **201** |
| ↳ 스크립트가 없다 (§6 상황 2) | — | 153 |
| ↳ 제약 상수를 찾았다 | — | 48 |
| `FORBIDDEN` | 492 | 492 (그대로) |
| `NEEDS_TRIBUTE` | 1,804 | 1,804 (그대로) |

남은 201장은 **허가하지 않은 것이 옳은** 카드들이다. 대표 두 장:

- **체츠커 `77435268`** — 공식 텍스트가 「자신 필드에 몬스터가 존재할 경우,
  이 카드는 일반 소환할 수 없다」 라고 **직접** 말하는데 이 저장소에
  스크립트가 없다. `()` 와 `None` 을 합쳤다면 **조용히 허가됐을 한 장**이다
  (`test_a01` · `test_a03` · `test_d02` · `test_g01c` 가 네 층에서 고정한다)
- **고스트릭 랜턴 `54512827`** — `EFFECT_CANNOT_SUMMON` 을 찾았다. 그것이
  자신에게 걸리는지 상대에게 걸리는지 이 계층은 구분하지 못하므로 모른다로
  남는다 (`test_a04`)

`test_f05` 가 신호를 가진 카드 **전부**에 `permits_procedure is False` 를
요구하고, `test_f01`~`test_f03` 이 허가 집합의 규모와 역검산 예외 목록의
노후화를 함께 막는다.

### 18-5. 최종 테스트 명령어 · 통과 · 실패 · 실행 시간

전부 `-p no:randomly` 로, 실제 종료 코드를 읽었다 (`| tail` 로 가리지 않았다).

| # | 명령어 | 통과 | 실패 | 시간 |
| --- | --- | --- | --- | --- |
| 1 | `pytest tests/engine -p no:randomly -q` | **3,530** | **0** | 592.00s (9:52) |
| 2 | `pytest tests/engine/test_effect_monster_normal_summon.py -p no:randomly -q` | **32** | **0** | 5.28s |
| 3 | 12파일 빠른 묶음 (§11.1 의 회귀 대상) | **473** | **0** | 141.52s (2:21) |
| 4 | 루트 chunk00 (27파일) | 626 | 2 | 1,453.01s (24:13) |
| 5 | 루트 chunk01 (26파일) | 761 | 7 | 1,665.16s (27:45) |
| 6 | 루트 chunk02 (26파일) | 573 | 6 | 1,033.20s (17:13) |
| 7 | 루트 chunk03 (24파일) | 554 | 2 | 779.82s (12:59) |
| 8 | 최종 회귀 — 6-U 가 건드린 루트 10파일 | **346** | **2** | 1,493.49s (24:53) |
| 9 | §9 변이 테스트 15건 | 15 KILLED | 0 생존 | 약 65s |

#### 묶음 4~7 의 실패 17건 분류 — **6-U 의 것 5건은 전부 고쳤다**

| 원인 | 건수 | 6-U 의 것인가 | 상태 |
| --- | --- | --- | --- |
| `CardDefinitionView` 칸 수 26→27 | 5 | 🔴 **예** | **전부 고쳐 통과** (§13-A · §13-B · §13-C) |
| Lua 코퍼스 드리프트 (`ACTIVATE` 블록 수) | 2 | 아니다 | 6-T 선례대로 핀 갱신, 단언 불변 |
| `cards.cdb` 드리프트 (+4장) | 4 | 아니다 | 고치지 않고 기록 |
| `PRODUCTION_DIRS` 에 `deck` 없음 (6-T 산) | 1 | 아니다 | 고치지 않고 기록 |
| 감사가 `HEAD` 와 비교 (6-U 전부터 빨간불) | 1 | 아니다 | 고치지 않고 기록 |
| 에이전트 상대 자원 한계 주장 무효화 | 1 | 아니다 | 고치지 않고 기록 (§13) |
| **재정 데이터 의존** (`.gitignore` 크롤 캐시 필요) | **2** | **아니다** | 🔴 **미해결 — 승인 없이 손대지 않음** (§18-2) |

묶음 8 의 실패 2건이 바로 그 재정 데이터 의존 2건이다. 그 둘을 빼면
**6-U 가 건드린 루트 파일에서 실패 0건**이다.

🔴 **6-U 와 무관한 10건은 전부 프로덕션 3파일을 `5a145a5` 버전으로 임시
교체해 동일 실패를 확인했고**(숫자까지 같다), 확인 뒤 `git checkout HEAD --`
로 복원해 작업 트리가 깨끗함을 확인했다. `test_21` 만 git 이력 감사라
`def test_` 개수를 세 시점에서 직접 셌다 (§13-B.1).

### 18-6. Git 커밋 · 푸시 상태

브랜치 `claude/pensive-goodall-te1egy` · 시작 HEAD `5a145a5`.

| 커밋 | 내용 |
| --- | --- |
| `a74f0a4` | **프로덕션** — 3파일 4군데 (`core/card_model.py` · `engine/game_state_view.py` · `engine/summon_rules.py`) |
| `ea13577` | **테스트** — 새 파일 32건 + 기존 기대 10건 정정 + 낡은 주석 4곳 |
| `1f9b272` | 칸 수 핀 `test_branch_setter_audit::test_30` |
| `e6e3bee` | **보고서** 초안 (§17 에 미완료 항목 명시) |
| `37c7a33` | 칸 수 핀 3곳 + Lua 코퍼스 드리프트 2곳 |
| `794615d` | 보고서 — chunk01 결과 + 재정 데이터 재배포 조사 |
| `5d9732c` | 보고서 — 요청된 여섯 구분 중 1~4 |
| `bfdb22a` | 보고서 — chunk02 결과 |
| `494894b` | 칸 수 핀 2곳 + 변이 테스트 15/15 |
| (이 커밋) | 보고서 — 여섯 구분 중 5·6 과 §17 갱신 |

- 전부 `claude/pensive-goodall-te1egy` 에 푸시됨 (`git push -u origin ...`,
  재시도 없이 1회 성공)
- **기존 commit 을 rewrite/amend 하지 않았다.** force push 하지 않았다.
  새 브랜치를 만들지 않았고 PR 을 열지 않았다
- 프로덕션 · 테스트 · 보고서를 **분리된 커밋**으로 올렸다
- 모든 커밋에 요구된 attribution 두 줄이 붙어 있다
