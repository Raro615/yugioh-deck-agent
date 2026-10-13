# Phase 4-C — 실제 듀얼 실행 가능성 검증 및 최소 실행 테스트

**기준 commit**: `6114ae3` (Phase 4-B 완료 상태) · **조사일**: 2026-10-13
**성격**: 조사·실행 검증. **production 코드 변경 0건 · 새 테스트 0건.**

---

## 0. 판정

## 🟡 **B — 부분 실행 가능**

* 🟢 **제한된 카드 풀에서는 A 조건이 실측으로 충족된다.** 통상 몬스터 +
  욕망의 항아리 덱으로 **48판 전부 완주**(3 매치업 × 시드 1~16), 전부
  LP 0 으로 승자가 선언됐다.
* 🔴 **그러나 일반 듀얼 완주에 필요한 핵심 기능이 빠져 있다.** 엔진의
  실행 가능 카드 13장을 모두 넣으면 **파괴 효과가 듀얼을 멈춘다.**
  특수 소환은 후보로 **한 번도** 나오지 않는다.

그래서 "현재 엔진으로 듀얼이 된다" 는 **카드 풀을 말하지 않으면 틀린
문장**이다. 아래에 범위를 수치로 적는다.

---

## 1. 작업 전 상태

| 항목 | 값 |
|---|---|
| branch | `claude/pensive-goodall-te1egy` |
| HEAD | `6114ae3` = origin ✔ |
| 작업 트리 | clean ✔ |
| 실행 중인 테스트 프로세스 | 없음 |

### 1.1 Engine V1 의 실행 진입점과 초기화

| 항목 | 실제 코드 |
|---|---|
| 진입점 | `engine.duel.Duel.start(repository, *, decks, seed, first_player=0, life_points=DEFAULT_LIFE_POINTS)` |
| 초기화 | `GameState.create(...)` → `shuffle=True` → 양쪽 `draw(seat, OPENING_HAND)` → `Phase.DRAW` · `TurnStep.OPEN` |
| 🔴 `seed` 는 **필수** | "씨앗 없는 무작위는 재현할 수 없고, 이 엔진은 그것을 다른 모든 자리에서 이미 거부한다" |
| 선공 첫 턴 드로우 | 하지 않는다 (`TurnStep.OPEN`) — 룰북대로 |

실측 초기 상태 (seed=11): `LP=(8000, 8000)` · 턴플레이어 `P0` · 행동권
`P0` · 페이즈 `DRAW` · 양쪽 패 5장 / 덱 15장 / 묘지 0장.

### 1.2 `GameStateView` · `LegalActions` · `PlayerAction` · 실행기의 연결

실제로 도는 고리는 이것 하나다 (`agent/runner.py::DuelRunner._step`):

```
duel.advance()                       ← 고르지 않아도 일어나는 일 먼저
duel.to_act                          ← 누구 차례인가
duel.legal_actions(seat)             → LegalActions(allowed, withheld)
policy.decide(duel.view(seat), legal) → PlayerAction | None
  (관측과 후보만 넘어간다 — Duel 도 GameState 도 넘기지 않는다)
_judge(...)                          ← 후보 밖의 수인지 검사
duel.apply(action)                   → DuelStep(accepted, code, reason)
_record(...)                         → Transcript
```

`Policy.decide` 는 `PlayerAction` 을 **직접** 돌려준다 (`Decision` 이
아니다 — `Decision` 은 `agent.policy` 의 별도 자료형이다).

### 1.3 실제 효과 실행이 가능한 카드

`engine/effect/library.py` 의 `EFFECT_LIBRARY` 16항목 중 `executable=True`
**13장**이고 전부 마법·함정이다.

| # | 카드 | 종류 | 실제 듀얼에서 발동됨 |
|---|---|---|---|
| 1 | 욕망의 항아리 `55144522` | 마법 | ✔ |
| 2 | 은혜의 단비 `66719324` | 마법 | ✔ |
| 3 | 싸이크론 `5318639` | 마법/속공 | ✔ (🔴 해결 실패) |
| 4 | 치료의 신 다이안 켓 `84257639` | 마법 | ✔ |
| 5 | 욕망의 선물 `5915629` | 함정 | ✘ |
| 6 | 갑부 고블린 `70368879` | 마법 | ✔ |
| 7 | 육신보살 `15103313` | 마법/속공 | ✔ (🔴 해결 실패) |
| 8 | 벌금 `92595643` | 함정 | ✘ |
| 9 | 강제 탈출 장치 `94192409` | 함정 | ✘ |
| 10 | 어리석은 매장 `81439173` | 마법 | ✘ |
| 11 | 무정한 말살 `73148972` | 마법 | ✔ |
| 12 | 의적의 입문서 `69091732` | 함정 | ✘ |
| 13 | 리로드 `22589918` | 마법/속공 | ✔ |

실측: 12판에서 **8/13 종**이 실제로 발동됐다. 발동되지 않은 5종 중
**4종이 함정**이다 — 세트는 되지만(`set_spell_trap` 48회 관측) 상대 턴에
발동되는 자리가 이 측정에서 나오지 않았다.

### 1.4 턴·소환·공격·효과·체인·승패의 구현 상태 (실측)

| 기능 | 상태 | 근거 |
|---|---|---|
| 턴·페이즈 진행 | 🟢 **동작** | `duel.advance()` · 48판에서 5~11턴 진행 |
| 일반 소환 | 🟢 **동작** | `normal_summon` 누적 330회 |
| 세트 (몬스터/마법함정) | 🟢 **동작** | `set_monster` 19 · `set_spell_trap` 104 |
| 효과 발동 | 🟢 **동작** (13장 한정) | `activate_effect` 누적 260회 |
| 공격 | 🟢 **동작** | `attack` 누적 371회 |
| 전투 데미지 · LP 감소 | 🟢 **동작** | `8000→6100→5400→3500→1600→0` 실측 |
| 승패 판정 | 🟢 **동작** | `DuelResult(winner=0, reason='P1: 라이프 포인트가 0 이 되었다')` |
| 체인 | 🟡 쌓이고 해결되나 **관측 최대 길이 0** | `apply` 가 체인을 끝까지 해결하고 돌아오므로 외부에서 길이를 볼 수 없다. 거절 메시지에 `체인1`·`체인2` 가 나타난다 |
| **파괴 실행** | 🔴 **없다** | §4.2 |
| **특수 소환** | 🔴 후보로 **0회** | §4.3 |
| 융합·싱크로·엑시즈·링크 | 🔴 절차 없음 | Phase 4-A §4.3 과 동일 |

### 1.5 AI 구현 상태

| 정책 | 파일 | 상태 |
|---|---|---|
| `FirstLegalPolicy` · `RandomPolicy` · `ScriptedPolicy` | `agent/policy.py` | 🟢 기준점 |
| `RuleBasedPolicy` | `agent/heuristic.py` (511줄) | 🟢 Consideration 4개 |
| `SearchPolicy` + `Simulator` | `agent/search.py` · `simulation.py` | 🟢 사본에 실제 엔진 적용 |
| `StateEvaluator` | `agent/evaluation.py` (881줄) | 🟢 |
| 실행기 | `agent/runner.py` · `arena.py` | 🟢 `run_match` · `run_series` |

공장 함수가 이미 있다: `make_rule_based()` · `make_random(seed)` ·
`make_first_legal()` · `make_search(depth=...)`.

### 1.6 실제 게임 진행을 검증하는 기존 테스트

`tests/agent/` 14개 파일. 특히 `test_ai_vs_ai.py` 25개 테스트가 완주·
재현성·관측 격리·난수 분리를 이미 검증한다. 그중
`test_a_whole_series_completes_on_every_seed` 가 **완주를 이미 단정**한다
(세 조합 × 시드 1~8, `refusals == 0` · `draws == 0`).

🔴 **그래서 "완주한다" 는 주장은 이번에 새로 만든 것이 아니다.** 이번
Phase 가 새로 한 것은 **카드 풀을 넓혔을 때 무엇이 깨지는가**를 특정한
것이다 (§4.2).

---

## 2. §3 의 10단계 — 실제 API 호출로 하나씩

`Duel` 을 직접 몰아 10단계를 전부 밟았다 (seed=11, Rule-Based vs Random).

| 단계 | 결과 |
|---|---|
| 1. 초기화 | `LP=(8000,8000)` · P0 선공 · `DRAW` |
| 2. 두 덱 구성 | 양쪽 20장, 패 5 / 덱 15 |
| 3. AI 정책 연결 | `<rule-based 규칙 4개>` vs `<random draws=0>` |
| 4. 상태 관찰 | `duel.view(seat)` → `GameStateView` |
| 5. 합법 행동 목록 | `duel.legal_actions(seat)` |
| 6. AI 선택 | `policy.decide(view, legal)` |
| 7. 검증·실행 | `duel.apply(action)` → `DuelStep` |
| 8. 상태 변화 기록 | LP 변화 `[(8000,8000),(8000,6100),(8000,5400),(8000,3500),(8000,1600),(8000,0)]` |
| 9. 턴·페이즈 진행 | `duel.advance()` |
| 10. 승패 확인 | `is_over=True` · `DuelResult(winner=0, reason='P1: 라이프 포인트가 0 이 되었다')` |

총 62걸음. 실제로 둔 행동:
`end_phase 27 · pass 12 · activate_effect 6 · attack 6 · normal_summon 4 ·
set_spell_trap 2 · set_monster 1`.

**모의 구현은 하나도 넣지 않았다.** 전부 기존 API 다.

---

## 3. AI 대 AI 실행 — 48판

덱(양쪽 동일, 20장): 블러드 보어 `11091375`×3 · 미노타우로스 `5053103`×3 ·
코지코치 `1184620`×3 · 13번째 묘 `32864`×3 · 화이트 더스턴 `3557275`×3 ·
욕망의 항아리 `55144522`×5. (기존 `tests/agent/test_ai_vs_ai.py` 와 **같은
풀** — 풀을 임의로 넓히지 않았다.)

| 매치업 | 판수 | outcome | 승자 | 턴 범위 | 행동 범위 | LP 감소 |
|---|---|---|---|---|---|---|
| Rule-Based vs Random | 16 | **completed 16** | P0 16 | 5~11 (평균 6.8) | 53~106 | 16/16 |
| Rule-Based vs FirstLegal | 16 | **completed 16** | P0 14 · P1 2 | 5~10 (평균 6.8) | 45~109 | 16/16 |
| Rule-Based vs Search | 16 | **completed 16** | P0 11 · P1 5 | 6~11 (평균 8.3) | 54~102 | 16/16 |

**48/48 완주. 거절 0 · 예외 0 · 무승부 0.** 종료 사유는 전부
`P?: 라이프 포인트가 0 이 되었다`.

실제로 둔 행동 (3 매치업 누적):

```
end_phase 1950 · pass 520 · attack 371 · normal_summon 330
· activate_effect 260 · set_spell_trap 104 · set_monster 19
```

**재현성**: seed=7 을 두 번 돌려 `state_hash` · 승자 · 행동 수가 모두
일치했다. 재현 입력은 `seed` + 양쪽 덱 + 수락된 행동 순서 +
`advance()` 끼워 넣기 네 가지다 (`Transcript` 의 계약).

**난수 분리**: 정책의 무작위는 `make_random(seed=99)` 로 따로 주고, 듀얼의
무작위는 `Duel.start(seed=...)` 가 쥔다 — 기존 설계대로이고 섞지 않았다.

---

## 4. 🔴 일반 듀얼 완주를 막는 것 — 실측으로 특정

### 4.1 측정 방법

엔진의 실행 가능 카드 **13종 × 2장 + 몬스터 12장 = 38장** 덱으로 12판을
돌렸다. 풀을 넓힌 것은 **엔진이 실제로 아는 카드 안에서**다.

```
outcome 분포: {'policy_refused': 10, 'completed': 2}
```

**12판 중 10판이 중단됐다.**

### 4.2 🔴 원인 — 파괴를 실행할 수 없다

거절 사유가 12판 전부 같은 문장이다.

```
ValidationCode.RULE_NOT_IMPLEMENTED
체인2 P1 5318639:e[0] 대상 @primary=[#47] 를 해결하지 못했습니다:
#47 를 파괴해도 되는지 판정할 수 없습니다: 이 카드가 파괴될 수 있는가
(파괴 내성) · 파괴 대신 다른 일이 일어나는가 (대체 효과).
판정할 수 없는 것을 허가로 바꾸지 않습니다.
```

이것은 엔진이 스스로 적어 둔 설계다 (`engine/__init__.py`, Phase 2-D-2):

> 파괴는 아직 실행하지 않는다 — 파괴 내성 · 파괴 대체 · 파괴 트리거가
> 없기 때문이다.

걸리는 카드: **싸이크론**(`5318639`) · **육신보살**(`15103313`). 둘 다
**발동과 대상 지정까지는 합법으로 통과**하고 **해결에서 막힌다.**

🔴 **이것이 일반 듀얼 완주를 막는 핵심이다.** 파괴는 통상 몬스터만 쓰는
덱에서는 안 나오지만, 실제 카드 대부분이 파괴를 포함한다.

### 4.3 🔴 특수 소환은 후보로 나오지 않는다

같은 덱으로 300걸음을 돌며 셌다.

| 측정 | 값 |
|---|---|
| `SPECIAL_SUMMON` 이 **합법 후보**로 나온 횟수 | **0** |
| `SPECIAL_SUMMON` 이 **보류**로 적힌 횟수 | **0** |

보류에도 안 나오는 이유: 이 풀의 카드 중 특수 소환을 할 수 있는 것이
없어서 **후보 생성 자체가 시작되지 않는다**. `ActionValidator` 가
`SPECIAL_SUMMON` 에 언제나 `UNKNOWN` 을 돌려주는 것(Phase 4-A §4.3)은
그보다 뒤 단계의 사실이다.

### 4.4 `legal_actions` 가 보류한 것

62걸음 동안 보류 사유는 **한 종류뿐**이었다.

```
58x  activate_card 의 남은 적법성을 판정할 규칙 계층이 아직 없습니다.
     확인할 수 있는 것은 전부 통…
```

`ACTIVATE_CARD` 는 Engine V1 에서 유효한 행위가 아니고(Phase 3-F-21~23),
그 사실이 매 걸음 보류로 기록된다 — 조용히 사라지지 않는다.

### 4.5 🔴 **분류 결함** — 엔진 공백이 "정책 결함" 으로 적힌다

이것은 §2 가 "AI 가 불법 행동을 선택하면 조용히 다른 행동으로 대체하지
말고 원인을 기록한다" 고 한 자리라서 **반드시 적는다.**

`agent/runner.py::DuelRunner._step` 은 거절을 **두 곳**에서 만든다.

```python
decision = self._judge(seat, policy, legal, chosen)
if not decision.accepted:            # (1) 정책이 후보 밖의 수를 골랐다
    return self._record(decision, at=at)

applied: DuelStep = self.duel.apply(decision.action)
return self._record(Decision(..., applied.accepted, applied.reason), at=at)
                                      # (2) **엔진**이 합법 행동을 거절했다
```

그런데 둘이 **같은 `accepted` 칸**에 들어가고,
`Transcript.refusals` 는 그 칸만 본다. 그 프로퍼티의 docstring 은

> `refusals` 가 비어 있지 않으면 **정책이 규약을 어긴 것**이고, 그것은
> 듀얼의 사실이 아니라 **정책의 결함**이다.

라고 적고, `agent/arena.py:424` 가 그것을 그대로 `MatchOutcome.POLICY_REFUSED`
("정책이 규약을 어겼다") 로 바꾼다.

**직접 증명했다:**

```
🔴 거절된 걸음 발견
   행동          : pass
   후보 안에 있었나 : True  (후보 1개)
   코드          : ValidationCode.RULE_NOT_IMPLEMENTED
   이유          : … 파괴해도 되는지 판정할 수 없습니다 …
```

정책은 **엔진이 준 유일한 후보**(`pass`)를 골랐다. 규약을 어기지 않았다.
거절한 주체는 엔진이고 사유는 파괴 실행 공백이다. 그런데 결과는
`policy_refused` 로 적힌다.

🔴 이것은 `MatchOutcome` 이 스스로 경계한 것과 **같은 종류의 혼동**이다 —
그 enum 의 docstring 이 "둘을 한 칸에 담으면 '안전 상한에 걸렸다' 가
'졌다' 로 읽힌다" 고 적어 두었는데, 정작 "엔진이 못 했다" 와 "정책이
틀렸다" 가 한 칸에 담겨 있다.

**고치지 않았다.** `Transcript.refusals` 와 `MatchOutcome` 은 여러 테스트가
읽는 **공유 계약**이고, §6 이 "공유 계약이나 구조를 변경해야만 하면 변경
전에 이유와 대안을 보고하고 승인을 기다린다" 고 했다. §7 에 제안만 적는다.

---

## 5. 수정한 파일

**없다.** production 0건 · 테스트 0건.

§6 의 "단순 조사만으로 충분하다면 코드를 수정하지 않는다" 를 적용했다.
근거:

* "듀얼이 완주한다" 는 주장은 `test_a_whole_series_completes_on_every_seed`
  가 **이미** 단정한다. 같은 것을 다시 쓰면 중복이다.
* 파괴 거절은 `tests/engine/test_semantic_effects.py` ·
  `test_phase2_contracts.py` · `test_effect_action_space_audit.py` 가 이미
  다룬다.
* 남은 새 사실은 §4.5 의 **분류 결함** 하나인데, 그것을 테스트로 고정하면
  **결함 동작을 계약으로 만든다.** 수정이 승인되기 전에는 적지 않는 것이
  맞다.

이번 Phase 의 산출물은 **이 보고서와 실행 기록**이다.

---

## 6. 실행한 테스트와 결과

전체 회귀는 **실행하지 않았다** (§6 의 지시). 코드를 바꾸지 않았으므로
회귀로 확인할 변경이 없다.

실행한 것은 **실제 듀얼 실행 측정** 네 가지다 (전부 기존 API 호출).

| # | 무엇 | 결과 |
|---|---|---|
| 1 | 3 매치업 × 시드 1~3, 결정 기록 포함 | 9/9 completed |
| 2 | 3 매치업 × 시드 1~16 | **48/48 completed** · 거절 0 · 예외 0 · 무승부 0 |
| 3 | §3 10단계 직접 호출 (seed=11) | 10단계 전부 실행 · 승자 선언 |
| 4 | 13장 풀 덱 12판 + 원인 규명 | **10/12 중단** · 원인 파괴 실행 공백 |

재현 명령은 §3·§4.1 에 적은 덱과 시드로 `agent.arena.run_match` 를 부르면
된다. 측정 스크립트는 작업용 임시 디렉터리에 두었고 저장소에 커밋하지
않았다 — 조사 산출물이지 제품 코드가 아니다.

---

## 7. 다음 단계에서 가장 먼저 해결해야 할 **단일 구조적 장애물**

> ### 파괴 실행 계층 (파괴 내성 · 파괴 대체 · 파괴 트리거)

왜 이것 하나인가:

* **지금 듀얼을 실제로 멈추는 유일한 원인**이다. 13장 풀에서 10/12 판이
  이것 때문에 중단됐고, 다른 사유는 하나도 없었다.
* **실제 카드 대부분이 파괴를 쓴다.** 이것이 없으면 카드 풀을 넓히는
  모든 작업이 같은 자리에서 막힌다 — 효과 컴파일러(`STRUCTURAL-7`)를
  먼저 만들어도 컴파일된 효과가 파괴를 호출하는 순간 같은 벽을 만난다.
* **특수 소환보다 먼저다.** 특수 소환은 후보가 아예 생성되지 않아
  (§4.3) 듀얼을 **멈추지 않는다**. 파괴는 발동을 허가한 뒤 해결에서
  멈추므로 **중단을 만든다** — 더 나쁜 실패 양식이다.

### 7.1 함께 올리는 제안 (승인 대기)

🔴 §4.5 의 **분류 결함**. 최소 수정안:

```
agent/runner.py — 거절의 출처를 구분해 적는다
  (1) 정책이 후보 밖의 수를 골랐다      → 정책 결함
  (2) 엔진이 합법 행동을 거절했다        → 엔진 공백 (ValidationCode 로 구분 가능)
agent/arena.py — (2) 를 POLICY_REFUSED 로 적지 않는다
```

`DuelStep.code` 에 이미 `ValidationCode.RULE_NOT_IMPLEMENTED` 가 들어 있어
**새 필드 없이** 구분할 수 있다. 다만 `Transcript.refusals` 와
`MatchOutcome` 은 여러 테스트가 읽는 공유 계약이므로 **승인 전에 손대지
않았다.**

이 수정 없이 파괴 계층을 만들면, 중간 상태에서 나는 중단이 계속 "정책
결함" 으로 기록돼 원인을 잘못 짚게 된다.

🔴 다음 Phase 는 자동으로 시작하지 않는다.
