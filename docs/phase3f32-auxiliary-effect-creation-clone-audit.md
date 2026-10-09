# Phase 3-F-32 — 보조 함수 생성 Effect 와 미인식 `Clone` 형태 감사

**최종 판정: `MIXED_FINDINGS`**

세 갈래가 각각 다른 답을 냈고, 하나로 뭉개지 않았다.

| 갈래 | 판정 | 조치 |
|---|---|---|
| `Clone` 의 인자 있는 형태 · 점 형태 | **`CONFIRMED_AUXILIARY_EFFECT_BUG`** | 🔴 최소 수정함 (3 스크립트 / 블록 +3) |
| 라이브러리 보조 함수 (`Fusion.CreateSummonEff` 등) | **`UNKNOWN_BY_DESIGN`** | 수정하지 않음 — 구현 원문이 저장소에 없다 |
| 식 receiver 의 `Clone` (Group clone) · 코퍼스 내 정의 보조 함수 | **`CONFIRMED_SAFE`** | 수정하지 않음 — 현재 동작이 옳다 |

---

## 1. 실제 HEAD / base 검증

`git log` · `git show` · `git rev-parse` · `git status` 로 직접 확인했다. **지시서의
기준과 전부 일치한다.**

| 항목 | 지시서 | 실측 | 결과 |
|---|---|---|---|
| 작업 시작 HEAD | — | `0ef466d6d9f9b2ad54fb6ca4cd2ff7894e94bda4` | — |
| 3-F-31 작업 commit | `8f93391` | `8f93391` *audit variable rebinding semantics* (10 files, +1468/−44) | 일치 |
| 3-F-31 보고서 commit | `0ef466d` | `0ef466d` *document variable rebinding audit* (471줄) | 일치 |
| 브랜치 | `claude/pensive-goodall-te1egy` | 같음 | 일치 |
| `origin/claude/...` | — | `0ef466d` — **HEAD 와 동일 (동기화됨)** | — |
| worktree | — | **clean** | — |
| 기준 전체 테스트 | 4,912 / 4 skipped / 0 failed | **같음** — 이 HEAD 에서 worktree clean 상태로 실측 (3-F-31 종료 시 확인) | 일치 |

기존 commit 은 rewrite/amend 하지 않았다. Engine V1 freeze 유지, Lua 파일 위치·내용
무변경, README 무변경.

### 1.1 이 Phase 가 만든 commit

| commit | 제목 | 내용 |
|---|---|---|
| `81eed74` | *Phase 3-F-32: audit auxiliary effect creation and clone forms* | production 2파일 (+81 / −11) |
| `b382afd` | *Phase 3-F-32: update tests for the recognized clone forms* | 신규 1 + 기존 12 테스트 파일 |
| (아래) | *Phase 3-F-32: document auxiliary effect creation and clone audit* | 이 보고서 |

---

## 2. 조사 범위와 검색 방법

### 2.1 가장 먼저 확인한 것 — 저장소에 무엇이 있는가

🔴 **저장소의 Lua 는 `c*.lua` 카드 스크립트 12,702개가 전부다.** EDOPro 의 공유
라이브러리(`utility.lua` · `proc_fusion.lua` · `proc_ritual.lua` 등)는 **들어 있지
않다.** 이것이 이번 Phase 의 가장 중요한 제약이고, §8 의 `UNKNOWN` 근거다.

```
$ ls *.lua | wc -l            → 12702
$ ls *.lua | grep -v '^c[0-9]' → (없음)
```

### 2.2 측정 방법 — 이름으로 고르지 않는다

조사 대상을 **함수 이름으로 고르지 않았다.** 다음 두 단계로 코퍼스가 스스로
말하게 했다.

1. **production 의 이벤트 재생을 그대로 복제**한다 — 같은 정규식
   (`_RE_CREATE_EFFECT` · `_RE_CLONE_EFFECT` · `_RE_REBIND` · `_RE_SETTER`),
   같은 `_is_card_effect` 게이트, 같은 정렬(`_EVENT_ORDER`), 같은 7개 설정자
   모집단. 이 복제가 3-F-31 의 숫자(설정자 **121,636** · 추적 **120,301** ·
   버려짐 **1,335**)를 **정확히 재현**하는 것을 먼저 확인했다. 재현하지 못하는
   계측으로는 아무 결론도 내지 않는다.
2. 그 재생에서 **바인딩이 풀린 변수**가 그 뒤 실제로
   ① production 이 다루는 7개 설정자를 받는지, ② `RegisterEffect` 의 인자로
   쓰이는지를 **그 대입 이후·다음 대입 이전** 구간에서만 센다.

🔴 **처음에는 "파일 안에 그 이름의 설정자가 등장하는가" 로 셌고 과포착했다.**
`Duel.SelectMatchingCard` 가 44건, `Duel.GetFirstTarget` 이 15건 "Effect 로
쓰인다" 고 나왔다 — `tc:SetStatus(...)` 같은 **Card 메서드**와 변수 이름이 겹친
것이다. 순서를 지킨 계측으로 다시 세니 그 항목들은 전부 사라졌다.

### 2.3 모든 `Clone` 형태를 정규화해 전수 열거

`Clone(` 토큰 **2,831개**를 "줄 시작부터 호출 끝까지" 잘라 식별자를 `V` 로
치환해 정규화했다. 서로 다른 형태는 **4개**뿐이다.

| 형태 | 호출 | 스크립트 | 예 |
|---|---:|---:|---|
| `V=V:V()` | 2,827 | 2,213 | `local e4=e3:Clone()` |
| `V=V:V(V)` | 2 | 2 | `local e2=e1:Clone(e1)` |
| `V=V.V(V)` | 1 | 1 | `local e2=Effect.Clone(e1)` |
| `V=V.V(0,V):V()` | 1 | 1 | `local tg=Duel.GetChainInfo(0,CHAININFO_TARGET_CARDS):Clone()` |

---

## 3. 보조 함수별 호출 수 및 고유 스크립트 수

🔴 **`f{...}` 는 Lua 의 테이블 호출 설탕**(`f({...})`)이므로 호출로 센다. `f(...)`
만 세면 `Fusion.CreateSummonEff` 가 5건 적게 나온다 — 3-F-31 이 "221곳" 이라고
적은 것이 그 때문이고, 아래가 다시 센 값이다.

### 3.1 지시서 §2 가 지명한 6개

| 함수 | 호출 | 스크립트 | 변수 배정 | 다중 배정 |
|---|---:|---:|---:|---:|
| `Fusion.CreateSummonEff` | 89 | 89 | 74 | 0 |
| `aux.AddNormalSummonProcedure` | 56 | 56 | 52 | 0 |
| `Spirit.AddProcedure` | 41 | 41 | 3 | 3 |
| `Ritual.CreateProc` | 23 | 23 | 23 | 0 |
| `Ritual.AddProcGreater` | 19 | 19 | 5 | 0 |
| `aux.CreateWitchcrafterReplace` | 2 | 2 | 2 | 0 |
| **합계** | **230** | **230** | **159** | **3** |

### 3.2 조사에서 **추가로** 드러난 것 (지시서 §2 "그 밖에")

반환값을 변수에 받아 설정자나 `RegisterEffect` 에 쓰는 것만 적는다.

| 함수 | 호출 | 스크립트 | 변수 배정 | 다중 배정 | 비고 |
|---|---:|---:|---:|---:|---|
| `Synchro.AddProcedure` | 475 | 474 | 2 | 0 | 거의 전부 반환값을 버린다 |
| `Fusion.AddProcMix` | 324 | 324 | 2 | 0 | 같음 |
| `aux.AddEquipProcedure` | 242 | 242 | 5 | 0 | 같음 |
| `Fusion.AddProcMixN` | 133 | 133 | 2 | 0 | 같음 |
| `Ritual.AddProcGreaterCode` | 34 | 34 | 1 | 0 | |
| `aux.AddNormalSetProcedure` | 34 | 34 | 31 | 0 | |
| `aux.createContinuousLizardCheck` | 16 | 16 | 16 | 0 | 16곳 전부 `RegisterEffect` |
| `Ritual.AddProcEqual` | 11 | 11 | 2 | 0 | |
| `Ritual.AddWholeLevelTribute` | 8 | 8 | 2 | 0 | |
| `Effect.CreateMysteruneQPEffect` | 8 | 8 | 8 | 1 | `Effect` 테이블의 **비표준** 이름 |
| `aux.AddKaijuProcedure` | 7 | 7 | 7 | **7** | 7곳 전부 다중 배정 |
| `aux.AddLavaProcedure` | 5 | 5 | 2 | 0 | |
| `aux.createTempLizardCheck` | 1 | 1 | 1 | 0 | |
| 🔴 `reglevel` | 5 | **1** | 4 | 0 | **코퍼스 안에 정의가 있다** |
| 🔴 `s.tempregister` | 3 | **1** | 2 | 2 | **코퍼스 안에 정의가 있다** |

### 3.3 다중 대입으로 Effect 둘 이상을 받는 자리

**13곳** — `aux.AddKaijuProcedure` 7 · `Spirit.AddProcedure` 3 ·
`s.tempregister` 2 · `Effect.CreateMysteruneQPEffect` 1.
(3-F-31 은 `Spirit` 만 보고 "3곳" 이라고 적었다.)

### 3.4 보조 함수 뒤에서 **실제로 버려지는** 설정자

순서를 지킨 계측으로, 바인딩이 풀린 뒤 Effect 로 **실제 쓰인** 자리만.

| RHS 형태 | 풀린 자리 | 쓰인 자리 | 설정자 | `RegisterEffect` |
|---|---:|---:|---:|---:|
| `Fusion.CreateSummonEff(...)` | 69 | 69 | 48 | 69 |
| `Ritual.CreateProc(...)` | 23 | 23 | 41 | 23 |
| `aux.createContinuousLizardCheck(...)` | 16 | 16 | 0 | 16 |
| `Effect.CreateMysteruneQPEffect(...)` | 9 | 9 | 0 | 9 |
| `Spirit.AddProcedure(...)` | 6 | 4 | 4 | 0 |
| `<테이블 호출> Fusion.CreateSummonEff{...}` | 5 | 5 | 4 | 5 |
| `aux.AddEquipProcedure(...)` | 5 | 5 | 5 | 0 |
| `Ritual.AddProcGreater(...)` | 5 | 4 | 6 | 1 |
| 그 밖 7종 | 8 | 7 | 6 | 3 |
| **합계** | | **142** | **114** | **126** |
| 🔴 `e:GetLabelObject(...)` | **1,196** | **1** | 3 | 0 |

🔴 마지막 줄이 중요하다. `GetLabelObject` 는 바인딩을 **1,196곳**에서 풀지만, 그
뒤 설정자가 실제로 오는 자리는 **단 1곳**(`c52445243`)이다. 3-F-31 이 위험 N3 으로
남긴 것의 실제 규모가 이것이다 — 1,195곳은 아무것도 잃지 않는다.

---

## 4. Effect 생성 · Clone · 반환 경로 분류

지시서 §2 의 5분류로 전수 배정했다. **하나도 같은 방식으로 처리하지 않았다.**

### ① 보조 함수가 Effect 객체를 **실제로 생성**하는 경우

| 경로 | 근거 | 판정 |
|---|---|---|
| `reglevel` (`c46005939`) | 🟢 **원문이 있다** — 정의 안에서 `Effect.CreateEffect` 1번, `return e1` | `CONFIRMED_SAFE` |
| `s.tempregister` (`c65351555`) | 🟢 **원문이 있다** — 정의 안에서 2번, `return e1,e2` | `CONFIRMED_SAFE` |
| 라이브러리 15종 (`Fusion.CreateSummonEff` 등) | 🔴 **원문이 없다.** 호출 자리의 `RegisterEffect` **126건**은 "반환값이 Effect 다" 까지만 말해 주고 **몇 개를 만드는지는 말해 주지 않는다** | `UNKNOWN_BY_DESIGN` |

🔴 **코퍼스 안의 정의 둘은 파서가 이미 올바르게 센다.** 정의가 **그 호출자와 같은
파일**에 있으므로, 그 `Effect.CreateEffect` 텍스트가 블록 하나를 만든다. 호출
자리는 블록을 **하나도 더하지 않는다** — `reglevel` 은 4번 호출되지만 블록은 1개다.
이것은 누락이 아니라 설계다: `EffectSpec` 은 **정적 정의**이고 런타임 인스턴스
수가 아니다. `EffectRef(card_id, ordinal)` 도 정의를 가리킨다.

### ② 기존 Effect 객체를 **복제**하는 경우

| 형태 | 자리 | 수정 전 | 수정 후 | 판정 |
|---|---:|---|---|---|
| `V=V:V()` | 2,827 | 블록이 된다 | 같음 | `CONFIRMED_SAFE` |
| `V=V:V(V)` | 2 | 🔴 **블록이 안 된다** | 블록이 된다 | **`CONFIRMED_BUG`** |
| `V=V.V(V)` | 1 | 🔴 **블록이 안 된다** | 블록이 된다 | **`CONFIRMED_BUG`** |

### ③ 기존 Effect 객체를 **반환하거나 전달**하는 경우

| 경로 | 자리 | 판정 |
|---|---:|---|
| `e:GetLabelObject()` — 런타임에 다른 효과를 가리킨다 | 1,196 | `UNKNOWN_BY_DESIGN` |
| 함수 매개변수 `e` 의 설정자 | 661 | `UNKNOWN_BY_DESIGN` (원리적으로 불가능) |
| Effect → Effect **alias** (`e2=e1`) | **0** | `NOT_APPLICABLE` — 3-F-31 이 bare-var 대입 579건 전수 조사 (`nil` 223 · `true` 101 · `false` 82 · 나머지 상수). **코퍼스에 존재하지 않는다** |

### ④ **다른 객체 또는 일반 값**을 반환하는 경우 — 🔴 반례

| 경로 | 자리 | 판정 |
|---|---:|---|
| `Duel.GetChainInfo(0,CHAININFO_TARGET_CARDS):Clone()` — **Group** 의 Clone | 1 | **`CONFIRMED_SAFE`** — 블록이 되지 않는다 |
| `g:Clone()` · `rg:Clone()` 등 Group 변수의 Clone | 83 | **`CONFIRMED_SAFE`** — `_is_card_effect` 게이트가 거부한다 |
| `Effect.GlobalEffect()` (`ge1` 등) | 220 | `CONFIRMED_SAFE` — 이 카드의 효과가 아니다 (3-F-28) |

🔴 **이 반례가 수정의 모양을 정했다.** `Clone(...)` 의 인자를 허용하되 **받는 쪽은
맨 식별자로 묶어 두었다.** 식 receiver 를 허용하면 Group clone 에 **가짜 효과
블록**이 생긴다. 게이트가 이미 거부하는 83건의 변수 이름이 `g` 26 · `rg` 21 ·
`tg` · `sg` · `trg` · `ntrg` 로 압도적으로 Group 쪽인 것이 그 방어가 작동한다는
증거다.

### ⑤ 함수 내부 구현을 **현재 자료만으로 확인할 수 없는** 경우

라이브러리 15종 전부. §8 에 근거를 적는다.

### 🔴 `Effect.Clone(e1) == e1:Clone()` 의 근거

라이브러리 원문이 없으므로 **코퍼스 안의 증거**로만 판단했다. 점 형태
`Class.Method` 상위 40개 가운데 **37개**가 같은 이름으로 **콜론 메서드로도**
쓰인다 (`Card.IsFaceup` 은 점 1,219 · 콜론 7,732 — 필터 술어로 넘길 때 점 형태를
쓴다). 그렇지 **않은** 셋은 `Effect.CreateEffect` · `Group.FromCards` ·
`Group.CreateGroup` 으로 **진짜 정적 생성자**다. `Clone` 은 콜론 **2,829** · 점
**1** 이므로 메서드 쪽이다. (`Group.Clone` 의 점 형태는 **0건**이다.)

---

## 5. ordinal 및 EffectRef 영향

### 5.1 누락된 블록은 **기존 `ordinal` 을 밀지 않는다**

`ordinal` 은 파서 **자신의** `card.script.effects` 안의 위치이고, 블록은 원문
등장 순서로 **append-only** 로 쌓인다. 그래서 파서가 끝까지 보지 못한 Effect 는
**목록에 없는 것**이지 다른 블록의 자리를 바꾸지 않는다. 라이브러리 보조 함수가
만드는 Effect 는 **이 스크립트 텍스트에 아무 설명이 없으므로** 파싱할 대상 자체가
없다 — **coverage 문제이고 correctness 문제가 아니다.**

### 5.2 반대로 **블록을 추가하면** `ordinal` 이 밀린다

새 블록은 **원문 순서**로 끼어들기 때문에, 그 뒤에 생성이 더 있으면 밀린다.
전수로 측정했다.

| 카드 | 새 블록 위치 | 기존 `ordinal` 이동 |
|---|---|---|
| `c44887817` | L58 → **맨 끝** (ord 4) | 없음 |
| `c56410769` | L30 → **맨 끝** (ord 2) | 없음 |
| 🔴 `c4997565` | L78 → **중간** (ord 3) | **ord 3 → ord 4 하나** |

🔴 **코퍼스 전체에서 기존 블록의 `ordinal` 이 움직인 자리는 1곳뿐이다.**

### 5.3 불변식은 유지된다

* `ordinal` == 원문 등장 순서: **12,702 스크립트 / 34,684 블록 중 불일치 0**
* `EffectRef(card_id, i).resolve(card) is card.script.effects[i]`: 세 카드 전부 성립
* 새 식별 체계 없음 — `EffectRef(card_id, ordinal)` 그대로

---

## 6. 최소 재현 사례

지시서 §2·§6 의 범주를 실제 파서로 돌렸다. 가상 동작을 사실처럼 테스트하지
않았다 — 전부 실제 Lua 원문에서 나온 모양이다.

| | Lua | 수정 **전** | 수정 **후** |
|---|---|---|---|
| A | `local e1=Effect.CreateEffect(c)` + `SetCode` | ord 0 `code=A` | 같음 |
| B | `local e2=e1:Clone()` + `e2:SetCode(B)` | ord 0·1 각자 제 code | 같음 |
| C | `local ge1=Effect.GlobalEffect()` + 설정자 | 블록 없음 (게이트) | 같음 |
| **D** | `local e2=e1:Clone(e1)` + `e2:SetCode(D)` | 🔴 **블록 없음 · 설정자 버려짐** | **블록 생김 · `code=D`** |
| **E** | `local e3=e2:Clone(c)` + `e3:SetCode(E)` | 🔴 **블록 없음 · 설정자 버려짐** | **블록 생김 · `code=E`** |
| **F** | `local e2=Effect.Clone(e1)` + `e2:SetCode(F)` | 🔴 **블록 없음 · 설정자 버려짐** | **블록 생김 · `code=F`** |
| G | `local tg=Duel.GetChainInfo(0,X):Clone()` | 블록 없음 | **같음 — 반례 보존** |
| H | `local rg=g:Clone()` + `rg:SetType(...)` | 블록 없음 (게이트) | 같음 |
| I | `local e1=Fusion.CreateSummonEff(c,f)` + 설정자 | 블록 없음 · **버려짐** | 같음 |
| J | `local e1=Ritual.CreateProc(...)` 뒤 설정자 | 앞 블록을 **오염시키지 않는다** | 같음 |
| K | `local e1,e2=Spirit.AddProcedure(c,true)` 뒤 설정자 | **왼쪽 이름 전부** 풀림 | 같음 |
| L | `local e2=e1:Clone(\n e1)` (여러 줄) | 받지 않는다 | **같음 — 한 줄로 제한** |
| M | `local e2=e1:Clone(f(x))` (중첩 괄호) | 받지 않는다 | **같음** |
| N | Clone 뒤 `e2=e:GetLabelObject()` + 설정자 | — | **다시 버려진다** |

### 6.1 실제 세 카드의 최종 값 (원문과 한 줄씩 대조)

```
c44887817  ord4  code='EFFECT_CANNOT_MSET'              ← L59
                 effect_types=['FIELD']                  ← L52 (부모 e1 에게서)
                 properties=['PLAYER_TARGET']            ← L54 (부모에게서)
                 cloned_from='e1'
c4997565   ord3  code='EFFECT_DISABLE_EFFECT'            ← L79
                 properties=['CANNOT_DISABLE']           ← L74 (부모에게서)
                 cloned_from='e1'
           ord4  index='e3'  code='EFFECT_UPDATE_DEFENSE' ← 밀려난 기존 블록
c56410769  ord2  code='EFFECT_CANNOT_ATTACK_ANNOUNCE'    ← L32
                 properties=['IGNORE_IMMUNE']            ← L31
                 target_ranges=['MZONE']                 ← L33
                 effect_types=['FIELD'], ranges=['MZONE'] ← 부모 e2 에게서
                 cloned_from='e2'
```

---

## 7. 정상 동작과 실제 버그의 구분

### 7.1 전수 검색 수를 곧바로 버그 수로 세지 않았다

| 센 것 | 수 | 그중 버그 |
|---|---:|---:|
| `Clone(` 토큰 | 2,831 | **3** |
| 보조 함수 호출 (§2 의 6종) | 230 | **0** — 판정 불가 |
| 보조 함수 호출 (추가 발견 15종) | 1,302 | **0** — 판정 불가 |
| `GetLabelObject` 호출 | 2,200 | **0** — UNKNOWN 이 맞다 |
| 바인딩이 풀리는 자리 | 1,330 설정자 | **0** — 전부 UNKNOWN 이 맞다 |

### 7.2 "정상적인 다중 Effect 생성" 을 누락으로 오판하지 않았다

* 한 스크립트가 `Effect.CreateEffect` 를 여러 번 쓰는 것은 **정상**이고 블록이
  그만큼 생긴다 (평균 2.7개).
* 보조 함수가 효과를 여러 개 만드는 것도 **정상**이다. 문제는 "몇 개인가" 를
  저장소 자료로 알 수 없다는 것이지 파서가 틀린 값을 만드는 것이 아니다.
* 🔴 **`reglevel` 을 "4번 호출하는데 블록이 1개뿐" 이라고 버그로 쓰지 않았다.**
  정적 정의와 런타임 인스턴스는 다른 것이고, `EffectSpec` 은 전자다.

### 7.3 설정자 귀속 3자 비교 — 🔴 총계가 같다고 "원상 복구" 가 아니다

| 시점 | 설정자 | 버려짐 | 추적 |
|---|---:|---:|---:|
| 3-F-30 끝 | 121,636 | 1,330 | 120,306 |
| 3-F-31 끝 | 121,636 | **1,335** | 120,301 |
| 3-F-32 (지금) | 121,636 | **1,330** | 120,306 |

총계가 1,330 으로 되돌아왔지만 **같은 집합이 아니다.** 자리 단위로 비교했다.

* 3-F-31 이 **새로 버린 5건**: `c44887817`(1) · `c4997565`(1) · `c52445243`(3)
* 3-F-32 가 **되살린 5건**: `c44887817`(1) · `c4997565`(1) · `c56410769`(3)
* **겹치는 것은 2건뿐이다.** `c52445243` 의 3건은 `e:GetLabelObject()` 라서
  계속 UNKNOWN 이 맞고, `c56410769` 의 3건은 3-F-30 이전부터 버려지던 것이다.

(`test_38` 이 이 비동일성을 명시적으로 못 박는다 — 숫자만 보고 "복구" 라고
적으면 거짓이 된다.)

---

## 8. 확인 불가 항목과 `UNKNOWN` 근거

### 8.1 라이브러리 보조 함수 — 왜 추측하지 않는가

| 질문 | 답 | 근거 |
|---|---|---|
| 몇 개의 Effect 를 만드는가 | **알 수 없다** | 구현 원문이 저장소에 없다 (§2.1) |
| 반환값이 Effect 인가 | 그렇다 | 🟢 호출 자리의 `RegisterEffect` 126건 — 코퍼스 내부 증거 |
| 몇 개를 **반환**하는가 | 일부만 안다 | 🟢 다중 대입 13곳은 왼쪽 이름 수로 "둘 이상" 을 알 수 있다 |
| 만든 Effect 의 type·code·범위는 | **알 수 없다** | 함수 본문을 읽어야 한다 |

지시서 §2 가 "함수 이름이나 관례만으로 Effect 생성 개수를 추측하지 않는다" 고
적었고, 그 금지를 지켰다. 이름에 `Create` 가 들어가니 1개일 것이라거나,
`AddProcedure` 니 절차 효과 하나일 것이라는 추론은 **하지 않았다.**

### 8.2 `UNKNOWN` 이 **올바른 상태**인 이유

파서는 이 자리에서 설정자를 **버린다**(3-F-31). 그 결과 `code=None` ·
`categories=[]` 가 되고, 이것은 "효과가 없다" 가 아니라 "읽지 못했다" 다.
`engine/validation.py` 의 `effect_count == 0` 처리(ADR-006, 실측 195장)와 같은
원칙이다. **틀린 값을 만드는 것보다 모른다고 말하는 것이 맞다.**

### 8.3 이 Phase 가 판정하지 않은 것

* `e1:Clone(e1)` 의 **추가 인자가 무슨 뜻인지** — EDOPro 바인딩이 무시하는지
  아닌지는 저장소 자료로 알 수 없다. 이 Phase 는 **"그 자리가 Effect 하나를
  만든다"** 까지만 판정했고(그 근거는 §4 의 `RegisterEffect` 와 설정자), 인자의
  의미는 UNKNOWN 으로 남긴다.
* 라이브러리 함수가 **이미 있는** Effect 를 돌려주는지 새로 만드는지 —
  구별할 자료가 없다.

---

## 9. downstream 영향

### 9.1 실제 호출 경로를 확인했다 — 이름만 보고 판단하지 않았다

`EffectSpec` **에만** 있는 칸(`effect_types` · `target_ranges` · `cloned_from` ·
`count_limit`)으로 AST 속성 접근을 전수 조사했다. `.code` · `.index` 같은
이름은 **다른 클래스에도 있다** — 3-F-28 과 3-F-30 이 그 함정에 각각 한 번씩
빠졌다 (`engine/action_target.py` 의 `self.index` 는 존 번호다).

| 계층 | `EffectSpec` 을 읽는가 | 이번 수정의 영향 |
|---|---|---|
| `sources/lua_loader.py` | 만든다 | 🔴 **블록 34,681 → 34,684** |
| `analysis/effect_analyzer.py` | 🔴 읽는다 | 🔴 **아래 9.2** |
| `core/card_search.py` | 읽는다 (`has_category` · `usable_from`) | 🔴 **아래 9.3** |
| `core/query_parser.py` | 읽지 않는다 | 없음 |
| `engine/` | 🟢 네 칸 중 **하나도** 읽지 않는다 | **없음 — 아래 §12** |
| `agent/` · AI/Search | 🟢 하나도 읽지 않는다 | **없음** |

### 9.2 `analysis/effect_analyzer.py` — 🔴 실제로 좋아졌다

| 카드 | `initial_effect` 등록 효과 | 해결 중 생성 효과 |
|---|---|---|
| `c56410769` | 🔴 **2 → 3** | 0 → 0 |
| `c4997565` | 2 → 2 | 🔴 **2 → 3** |
| `c44887817` | 3 → 3 | 🔴 **1 → 2** |

🔴 `c56410769` *파문조 / 波紋鳥 / Ripple Bird* 의 **세 번째 효과**가 그 전에는
**분석 결과에 아예 없었다.** 스크립트가 그 블록에 직접 붙여 둔 주석이
`--While all monsters you control are in Defense Position, your opponent cannot
declare an attack` (원문 L29) 이고, 블록은 L30-35 다. (공식 카드 텍스트는 이
보고서에서 번역하지 않는다 — 스크립트 주석을 원문 그대로 인용한다.)

이것이 수정 조건 ③("downstream 또는 분석 결과에 실제 영향") 의 근거다.

🔴 **정합성도 확인했다.** `EffectAnalyzer._collect_handlers` 는 `order` 길이가
`card.script.effects` 와 **같아야** 하고(어긋나면 `entries[position]` 이 다른
블록의 핸들러를 붙인다 — 3-F-28 이 겪은 실패), 두 모듈이 `_RE_CLONE_EFFECT` 와
`_clone_source` 를 **공유**하므로 자동으로 맞는다. 코퍼스 전수 **불일치 0**.

### 9.3 `core/card_search.py`

| 측정 | 결과 |
|---|---|
| 카테고리 필터 — 결과 집합 + 순위 지문 | 🟢 **완전히 동일** (새 블록 셋 다 `categories=[]`) |
| `LuaScriptInfo` 파일 단위 칸 지문 | 🟢 **완전히 동일** |
| 위치 필터 — 결과 **집합** | 🟢 동일 (MZONE 5,170장 그대로) |
| 위치 필터 — **순위** | 🔴 **`c56410769` 1568위 → 528위** (그 한 장만) |

🔴 순위가 오른 것은 **더 정확해진 것**이다. `c56410769` 는 실제로 MZONE 범위
효과가 **3개**(`e1`·`e2`·clone `e3`)이고, 그 전에는 2개로 세었다.

### 9.4 🟡 새로 발견한 괴리 — 지금은 영향 0

`analysis/effect_analyzer.py` 는 `_RE_REBIND` 를 **import 하지 않는다.** 즉 3-F-31
이 로더에 넣은 "모르는 대입이면 바인딩을 푼다" 가 분석기에는 **없다.** 그래서
분석기가 `SetCost`/`SetCondition`/`SetTarget`/`SetOperation` 을 옛 바인딩에 붙일
수 **있다.**

🔴 **코퍼스 전수로 재니 그런 자리는 0건이다.** 잠재적 설계 위험이지 지금의
버그가 아니다 — 위험 **N7** 로 기록하고 이 Phase 에서 고치지 않는다 (수정 조건
③ "실제 영향" 을 만족하지 않는다).

---

## 10. production 수정 여부와 정확한 diff

### 10.1 §5 의 수정 조건을 전부 충족한다

| 조건 | 충족 | 근거 |
|---|---|---|
| ① 실제 parser bug 가 재현됨 | ✅ | §6 의 D·E·F — 블록 3개가 아예 없었고 설정자 5건이 버려졌다 |
| ② 현재 parser contract 를 위반 | ✅ | 계약은 "이 스크립트 텍스트에서 만들어지는 효과마다 블록 하나" 다 |
| ③ downstream·분석 결과에 실제 영향 | ✅ | §9.2 — 등록된 효과 하나가 **없었다** · §9.3 — 검색 순위 |
| ④ 최소 수정 가능 | ✅ | 정규식 2개 + 헬퍼 1개, **파일 2개** |
| ⑤ `EffectSpec` API 를 깨지 않음 | ✅ | 9개 칸 그대로, 새 칸·새 enum 없음 |
| ⑥ Engine V1 freeze 를 깨지 않음 | ✅ | §12 |

금지 사항 전부 지켰다 — Lua 인터프리터 없음 · dataflow 엔진 없음 · CFG 없음 ·
`EffectGraph` 없음 · Effect ID/UUID 없음 · 새 enum/public API/abstraction 없음 ·
Lua 파일 무변경 · README 무변경 · `engine/`·`agent/`·AI/Search 무변경 ·
기존 commit rewrite 없음.

### 10.2 `sources/lua_loader.py` (+71 / −8, 주석 포함)

```diff
-_RE_CLONE_EFFECT = re.compile(
-    r"(?:\b(local)\s+)?([A-Za-z_]\w*)\s*=\s*([A-Za-z_]\w*)\s*:\s*Clone\s*\(\s*\)"
-)
+_RE_CLONE_EFFECT = re.compile(
+    r"(?:\b(local)\s+)?([A-Za-z_]\w*)\s*=\s*"
+    r"(?:([A-Za-z_]\w*)\s*:\s*Clone\s*\([^()\n]*\)"
+    r"|Effect\s*\.\s*Clone\s*\(\s*([A-Za-z_]\w*)\s*\))"
+)
+
+
+def _clone_source(match: "re.Match[str]") -> str:
+    """``_RE_CLONE_EFFECT`` 매치에서 **원본 변수 이름**을 돌려준다."""
+    return match.group(3) or match.group(4)
```

```diff
 _RE_REBIND = re.compile(
     ...
     r"(?!\s*(?:Effect\.(?:CreateEffect|GlobalEffect)\s*\("
-    r"|[A-Za-z_]\w*\s*:\s*Clone\s*\(\s*\)))",
+    r"|[A-Za-z_]\w*\s*:\s*Clone\s*\([^()\n]*\)"
+    r"|Effect\s*\.\s*Clone\s*\(\s*[A-Za-z_]\w*\s*\)))",
     re.M,
 )
```

```diff
     for m in _RE_CLONE_EFFECT.finditer(body):
-        if not _is_card_effect(body, m.group(1), m.group(2), m.group(3)):
+        src_var = _clone_source(m)
+        if not _is_card_effect(body, m.group(1), m.group(2), src_var):
             continue
-        events.append((m.start(), "clone", f"{m.group(2)}={m.group(3)}"))
+        events.append((m.start(), "clone", f"{m.group(2)}={src_var}"))
```

```diff
-        return f"v8:{count}:{newest:.0f}"
+        return f"v9:{count}:{newest:.0f}"
```

### 10.3 `analysis/effect_analyzer.py` (+10 / −3)

같은 두 줄(`_is_card_effect` 인자와 이벤트 payload)을 `_clone_source` 로 바꾸고
그 함수를 import 한다. 🔴 **이 파일을 함께 바꾸는 것이 필수다** — 3-F-28 이
탐지 정규식을 공유하도록 만든 이유가 `order` 길이 정합이고, 여기서 `group(3)` 을
그대로 두면 점 형태에서 `None` 이 들어가 블록이 어긋난다.

### 10.4 🔴 두 정규식을 **함께** 바꿔야 하는 이유 (혼자서 고치면 더 나빠진다)

처음에는 `_RE_CLONE_EFFECT` 만 넓혀 prototype 을 돌렸다. 블록은 생겼지만
`_RE_REBIND` 가 **같은 자리에서** 그 변수를 곧바로 풀어 버려(이벤트 순서
`clone`=0 → `rebind`=1), 뒤따르는 설정자가 계속 버려졌다. 그 결과:

```
c44887817 ord4  code='EFFECT_CANNOT_SUMMON'   ← 🔴 부모의 값이다. Lua 는 EFFECT_CANNOT_MSET
```

즉 **부모의 값을 자식의 값처럼 주장**한다 — 블록이 아예 없는 것보다 나쁘다.
`_RE_REBIND` 의 선읽기를 함께 동기화해 해결했고, 그 의존성을 production 주석과
`test_30` 에 못 박았다.

### 10.5 전수 영향

```
블록 총계        34,681 → 34,684  (+3)
달라진 스크립트   3 (c44887817 · c4997565 · c56410769)
기존 ordinal 이동 1 (c4997565 ord3 → ord4)
Clone 정규식 매치 2,827 → 2,830   거부 83 (불변)
CreateEffect      32,157 매치 / 31,937 블록 / 220 거부 (전부 불변)
설정자 추적       120,301 → 120,306   버려짐 1,335 → 1,330
목록 칸  effect_types 45,337→45,340 · ranges 15,063→15,064
         target_ranges 2,062→2,063 · properties 23,884→23,887
         categories 20,503 (불변)
```

---

## 11. 신규 · 기존 테스트 결과

### 11.1 신규

`tests/test_auxiliary_effect_creation_clone_audit.py` — **52개** (지시서 최소 25개).
지시서 §6 의 13개 범주를 전부 덮는다. 개수를 채우기 위한 중복 테스트는 없다 —
각 테스트가 서로 다른 측정값이나 서로 다른 재현 사례를 고정한다.

삭제 0 · skip 추가 0 · assertion 약화 0 · threshold 완화 0.
(`test_51`·`test_52` 는 이 Phase 의 commit 이 아직 없을 때만 skip 하는 guard 이고,
commit 후에는 실행된다.)

### 11.2 신규 테스트 작성 중 **내가** 틀린 것 5건 (전부 기록)

| 테스트 | 내가 쓴 값 | 실측 | 원인 |
|---|---|---|---|
| `test_25` | `reglevel` 파일의 `Effect.CreateEffect` 1개 | **3개** | 함수 **정의 안**만 보고 파일 전체를 세지 않았다. 정의 구간을 잘라서 세도록 고쳤다 |
| `test_26` | `"return e1,e2" in body.replace(" ","")` | — | 공백을 지우면 `return` 과 `e1` 이 붙는다. 정규식으로 바꿨다 |
| `test_42` | digest 핀 7개 | **8개** | 🔴 **내가 쓴 테스트 파일 자신**이 그 digest 문자열을 담고 있어 하나 더 세어졌다. 자기 파일을 제외했다 |
| `test_44` | `c56410769` 의 MZONE 블록 2개 | **3개** | `e1` 도 L15 에서 `SetRange(LOCATION_MZONE)` 를 쓴다. 세어 보지 않고 썼다 |
| `test_47` | `resolution_effects[2]` 가 clone | **[1]** | `resolution_effects` 안의 위치를 `ordinal` 과 혼동했다 |

### 11.3 기존 테스트 — 수정한 것과 **왜 기존 가정이 틀렸는지**

전체 회귀 1차에서 **40건**이 실패했다 (2차 13건 → 3차 2건 → 0건). 전부 원인을
확인해 고쳤고, 하나도 삭제하거나 skip 하거나 약화하지 않았다. 총 **12개 파일**을
손봤다.

#### (a) 캐시 서명 `v8` → `v9` — 10곳 / 6파일

`LuaScriptSource._signature()` 에 **파서 버전이 들어 있지 않다**. 스크립트
파일이 변하지 않으면 서명이 같아서, 고친 파서가 옛 캐시를 계속 읽는다. 그래서
파서가 같은 입력에서 다른 결과를 내면 **수동으로** 올려야 한다.
🔴 **다섯 Phase 연속 수동**(v5→v6→v7→v8→v9)이다 — 위험 **E4** 로 유지한다.

#### (b) 코퍼스 총계 +3 — 블록 수와 목록 칸

`BLOCKS` 34,681 → 34,684 (6파일), `cards.cdb` 에 붙은 블록 34,632 → 34,635
(3파일), 목록 칸 4개(§10.5), `index` 중복 합 6,802 → 6,804,
`FIELD` 단독 8,881 → 8,883.
**기존 가정이 틀렸던 이유**: 그 숫자들은 "`Clone` 은 빈 괄호 형태뿐" 이라는
전제 위에 세어진 값이다. 이 Phase 가 코퍼스에 세 형태가 더 있음을 전수로
확인하면서 전제가 바뀌었다.

#### (c) 🔴 테스트가 들고 있던 **탐지 규칙의 복사본** — 6파일

3-F-28 이 바로 이 함정을 기록해 두었는데(`analysis/effect_analyzer.py` 가 정규식
복사본을 갖고 있어 블록이 어긋났다), 테스트 쪽에 같은 문제가 남아 있었다.

* `_RE_CLONE_EFFECT` 의 **그룹 번호**를 직접 읽는 자리 — `m.group(3)`.
  점 형태에서 `None` 이 나와 `create_effect_ordinal::test_34` 가
  `AttributeError` 로 터졌다. 전부 `lua_loader._clone_source(m)` 로 바꿨다.
* `branch_setter::test_23` 은 `is_clone = ^\s*\w+:Clone\(\s*\)` 라는 **자기
  복사본**으로 재바인딩을 판정하면서 바인딩은 production 정규식으로 만들었다.
  그래서 같은 자리가 bind 이면서 rebind 로 동시에 세어져 25 → 26 이 됐다.
  production 과 같은 세 형태를 받도록 맞췄다.
* `effect_type_quick::replace_rule` 도 같은 그룹 번호 문제였다 — 3-F-28 이 이
  함수에 대해 남긴 정정 주석 바로 아래에서 또 걸렸다.

#### (d) 🔴 전제가 **뒤집힌** 어서션 — 4곳

| 테스트 | 기존 | 왜 틀렸나 |
|---|---|---|
| `variable_rebinding::test_18` | `assert not _RE_CLONE_EFFECT.search("local e2=e1:Clone(e1)")` | "빈 괄호를 요구하므로 못 잡는다" 는 **그때의 사실**이다. 3-F-32 가 코퍼스의 `Clone` 형태가 4개뿐이고 그중 하나만 Group clone 임을 전수로 확인한 뒤 넓혔다. 그 Phase 의 결론(ord 1 의 code 는 `None`)은 **그대로 유지**된다 |
| `variable_rebinding::test_19` | 같음 (점 형태) | 같음. 근거는 §4 의 점/콜론 37/40 증거 |
| `variable_rebinding::test_29` | `assert "EFFECT_DISABLE_EFFECT" not in codes` | 그때는 **그 clone 블록 자체가 없었다**. 지금은 제 블록에 있어야 한다. 중요한 것은 `EVENT_CHAINING` 을 **덮지 않는다**는 것이고 그 줄은 그대로 지킨다 (`count == 1` 로 강화했다) |
| `branch_setter::test_23` | 잘못 귀속 5건 / 그림자 25 | 3-F-32 가 두 자리를 블록으로 인정하면서 옛 규칙조차 그 자리에서는 제 블록을 가리킨다 → 3건 / 23. 남은 3건은 `c52445243` 뿐이고 **UNKNOWN 이 맞다** |

#### (e) 🔴 `variable_rebinding::test_20` — 5 → 3

이 테스트는 `_RE_REBIND` **없는** 옛 규칙과 지금을 비교한다. 3-F-32 가 두
형태를 인정하면서 옛 규칙의 오귀속 5건 중 2건이 사라졌다.
**3-F-31 의 결론이 약해진 것이 아니다** — "옛 규칙은 틀린 값을 만들었고 지금은
만들지 않는다" 는 그대로이고, 그중 2건은 3-F-32 가 **값을 버리는 대신 제자리에
붙이는** 데까지 갔다.

### 11.4 회귀 결과 — 전부 실측

| 실행 | 결과 |
|---|---|
| 기준 (3-F-31 끝, `0ef466d`) | 4,912 passed / 4 skipped / 0 failed |
| 1차 (production 수정 후, 테스트 미갱신) | **40 failed** / 4,872 passed / 4 skipped |
| 신규 파일 단독 (내 실수 5건 고친 뒤) | 50 passed / 2 skipped |
| 2차 (캐시 서명 · 총계 · `_clone_source`) | **13 failed** / 4,949 passed / 6 skipped |
| 3차 (파생 총계) | **2 failed** / 4,960 passed / 6 skipped |
| **최종 (commit 된 상태)** | 🟢 **4,964 passed / 4 skipped / 0 failed** |

### 11.5 최종 전체 회귀

```
4964 passed, 4 skipped in 1766.37s (0:29:26)
```

🔴 **계정이 맞는다**: 4,912 → 4,964 는 **+52** 이고, 신규 테스트 수와 정확히
같다. skip 은 4 → **4** 로 되돌아왔다 — 2·3차의 6 은 `test_51`·`test_52` 가
"이 Phase 의 commit 이 아직 없다" 로 건너뛴 것이고, commit 후에는 **실행되어
통과한다**.

---

## 12. `state_hash` / RNG / hidden-info / Engine V1 불변성

| 불변 조건 | 확인 방법 | 결과 |
|---|---|---|
| `state_hash` 불변 | `GameState.canonical_state` 를 **AST 로** 읽어, 넣는 것이 `players`·`turn`·`uses`·`rule_uses`·`result` 다섯뿐이고 `effects`·`effect_count`·`script` 가 **없음**을 확인 | 🟢 **구조적으로 무관** |
| RNG · digest 불변 | 6듀얼 / 611결정 digest 핀 **7개** 그대로 | 🟢 불변 |
| hidden information 경계 | `GameStateView` 만 `effect_count=len(card.script.effects)` 를 노출하고, 그것은 `canonical_state` 밖이다. 세 카드는 Engine V1 의 어느 덱에도 없다 | 🟢 불변 |
| `GameStateView` 경계 | 위와 같음 | 🟢 불변 |
| Engine V1 freeze | 🔴 `EFFECT_LIBRARY` 의 **16개 정의가 전부 `ordinal 0`** 이고, `{4997565, 44887817, 56410769}` 가 **하나도 없다** | 🟢 불변 |
| `EffectRef(card_id, ordinal)` 설계 | 그대로. 새 식별 체계·UUID 없음 | 🟢 유지 |
| Card Definition/Instance 분리 | 건드리지 않음 | 🟢 유지 |
| 기존 UNKNOWN 의미 | `code=None` = "읽지 못했다" 그대로. 🔴 보조 함수 1,330건은 **계속 UNKNOWN** 이다 | 🟢 유지 |
| AI/Search 동작 | `agent/` 가 네 칸을 하나도 읽지 않음 (AST 전수) | 🟢 불변 |
| Lua 파일 위치·내용 | `git show --name-only` 에 `.lua` **0건** | 🟢 불변 |
| skip 수 증가 없음 | 4 → 4 | 🟢 불변 |
| 기존 commit rewrite 없음 | `git log` 로 확인 | 🟢 없음 |

🔴 `engine/action_validation.py` 의 `ref.ordinal >= definition.effect_count` 게이트는
세 카드에서 `effect_count` 가 **늘어나** 더 느슨해진다. 그러나 Engine V1 에 그 세
카드의 정의가 없으므로 그 게이트에 도달하는 활성화 자체가 없다.

---

## 13. 최종 판정 및 남은 구조적 위험

## **`MIXED_FINDINGS`**

근거를 복수로 적는다. 증거 없이 결론을 강하게 만들지 않는다.

1. **`CONFIRMED_AUXILIARY_EFFECT_BUG`** — `Clone` 의 인자 있는 형태 2곳과 점
   형태 1곳에서 **실제 Effect 블록 3개가 누락**되어 있었고, 그중 하나는
   `initial_effect` 에 등록된 효과라 **분석 결과에서 효과 하나가 사라져
   있었다.** 최소 수정했다.
2. **`UNKNOWN_BY_DESIGN`** — 라이브러리 보조 함수 15종(1,532 호출)이 만드는
   Effect 는 **구현 원문이 저장소에 없어** 개수조차 셀 수 없다. 추측하지 않고
   설정자 1,330건을 계속 버린다. 이것이 올바른 상태다.
3. **`CONFIRMED_SAFE`** — 식 receiver 의 `Clone`(Group clone) 1곳과 게이트가
   거부하는 Group 변수 Clone 83곳은 **지금 동작이 옳다.** 코퍼스 안에 정의가
   있는 보조 함수 2종도 파서가 이미 올바르게 센다.

### 13.1 이 Phase 에서 새로 발견한 위험

| # | 위험 | severity | 재현 | production | Engine | AI/Search | 왜 지금 안 고치는가 |
|---|---|---|---|---|---|---|---|
| **N6** | 🔴 **`_RE_CLONE_EFFECT` 와 `_RE_REBIND` 가 같은 형태 목록을 두 곳에 적는다** | 🟠 중 | `test_30` | 한쪽만 바꾸면 **부모 값을 자식 값으로 주장**한다 | 없음 | 없음 | 하나로 합치려면 정규식을 조립식으로 만들어야 하고, 그것이 `_RE_REBIND` 의 선읽기 구조를 바꾼다. 지금은 **주석과 테스트로 의존성을 못 박았다** |
| **N7** | 🟡 **분석기에 `_RE_REBIND` 가 없다** — 로더와 바인딩 규칙이 다르다 | 🟡 하 | 측정 **0건** | 핸들러 4개를 옛 바인딩에 붙일 **수** 있다 | 없음 | 없음 | 🔴 **코퍼스 전수로 그런 자리가 0건이다.** 수정 조건 ③("실제 영향")을 만족하지 않는다. 잠재 위험으로만 기록한다 |
| **N8** | 🟡 **라이브러리 원문이 저장소에 없다** — 1,532 호출의 생성 개수를 알 수 없다 | 🟠 중 | `test_23` | 설정자 1,330건이 UNKNOWN | 없음 | 없음 | 라이브러리를 들여오는 것은 이 Phase 의 범위가 아니고, 들여오더라도 "몇 개를 만드는가" 는 **함수 본문 해석**(= dataflow)이다 — 금지 사항 |
| **N9** | 🟡 **다중 반환 보조 함수 13곳** — 왼쪽 이름 수만 알고 무엇인지 모른다 | 🟡 하 | `test_28` | 설정자가 버려진다 | 없음 | 없음 | N8 과 같은 뿌리다 |
| **N10** | 🟢 **`[^()\n]*` 는 한 줄·비중첩으로 제한** — 코퍼스에 그런 `Clone` 은 없다 | 🟢 정보 | `test_14`·`test_15` | 그런 자리가 생기면 블록이 안 된다 | 없음 | 없음 | 넓히면 **어디서 끝나는지 모르는 호출**을 받는다. 좁은 쪽이 안전하다 |

### 13.2 기존 위험 (유지)

| # | 위험 | 출처 | 상태 |
|---|---|---|---|
| E1 | 네 설정자의 Lua API 의미가 문서화되지 않음 | 3-F-29 | **유지** |
| E2 | 목록 칸에 "모른다" 를 표현할 값이 없다 | 3-F-29 | **유지** |
| E3 | 한 블록의 두 번째 이후 setter 는 더하기 | 3-F-29 | **유지** |
| E4 | 캐시 서명에 파서 버전이 없다 | 3-F-27~29 | **유지** — 🔴 **다섯 Phase 연속 수동** (`v9`) |
| E5 | 보조 함수 생성 effect | 3-F-28 | 🔴 **N8 로 재정의** — 이 Phase 가 "왜 못 세는가" 까지 확정했다 |
| E6 | `EffectSpec.index` 가 유일하지 않다 | 3-F-28 | **유지** — 🔴 새 블록 둘이 기존 이름(`e2`)을 다시 써서 중복이 6,802 → 6,804 가 됐다 |
| E7 | `SetCategory(aux.Stringid(...))` 8건 | 3-F-29 | **유지** |
| E8 | 분기별 의미를 표현할 칸이 없다 | 3-F-30 | **유지** — 🔴 `c56410769` 가 그 예다. `e2` 는 `SetTargetRange(LOCATION_MZONE,0)`, clone `e3` 는 `SetTargetRange(0,LOCATION_MZONE)` 인데 **둘 다 `['MZONE']`** 이다. "어느 쪽 플레이어" 를 담을 칸이 없다 |
| E9 | 배타 분기 값 병합 2블록 | 3-F-30 | **유지** |
| N1 | 보조 함수를 블록으로 보지 않는다 | 3-F-31 | 🔴 **N8 로 흡수** |
| N2 | 주석 처리된 설정자가 적용된다 (`c69526976`) | 3-F-31 | **유지** |
| N3 | `GetLabelObject` 가 가리키는 블록을 알 수 없다 | 3-F-31 | **유지** — 🔴 실제 규모를 이 Phase 가 측정했다: 1,196곳 중 설정자가 오는 곳은 **1곳**뿐 |
| N4 | 미인식 `Clone` 형태 3곳 | 3-F-31 | 🟢 **해소** — 이 Phase 가 고쳤다 |
| N5 | 함수 매개변수 `e` 의 설정자 661건 | 3-F-31 | **유지** — 원리적으로 불가능 |

---

## 14. 다음 Phase 후보 1개

**Phase 3-F-33 — 로더와 분석기의 바인딩 규칙 일원화 감사 (N6 + N7)**

이 Phase 가 같은 뿌리로 확정한 둘을 함께 다룬다 — **블록 탐지·바인딩 규칙이
세 곳에 흩어져 있다.**

* `sources/lua_loader.py` 의 `_RE_CLONE_EFFECT` 와 `_RE_REBIND` 가 **같은 세
  형태 목록을 각각** 적는다 (N6). 한쪽만 바꾸면 파서가 **부모의 값을 자식의
  값처럼 주장**하는데, 이 Phase 가 prototype 에서 실제로 그 상태를 만들어 봤다.
* `analysis/effect_analyzer.py` 는 `_RE_CREATE_EFFECT`·`_RE_CLONE_EFFECT`·
  `_clone_source` 는 import 하면서 **`_RE_REBIND` 는 하지 않는다** (N7). 지금은
  영향이 0건이지만, 규칙이 둘로 갈린 상태 자체가 3-F-28 이 겪은 실패의 모양이다.
* 테스트 쪽에도 같은 복사본이 **6파일**에 남아 있었고 이 Phase 가 전부
  `_clone_source` 로 바꿨다 — 그 과정에서 3-F-28 이 남긴 정정 주석 바로 아래에서
  또 같은 함정에 걸렸다.

🔴 **먼저 재야 할 것**: ① 분석기에 `_RE_REBIND` 를 넣으면 코퍼스 산출물이 **몇
자리** 바뀌는지 (이 Phase 의 측정으로는 0건이어야 하고, 0이 아니면 그 자체가
발견이다). ② 세 형태 목록을 한 곳에 모으는 최소 리팩터가 `_RE_REBIND` 의 선읽기
구조를 **깨지 않고** 가능한지. 둘 다 "산출물 무변화" 가 성공 기준이므로,
3-F-28 의 전수 diff 방법론(34,684 블록 · 16개 정의 · 캐시 서명)을 그대로 쓸 수
있다. 산출물이 바뀌면 그때는 **리팩터가 아니라 또 다른 버그 수정**이므로, 이
Phase 처럼 `ordinal` 영향부터 재야 한다.
