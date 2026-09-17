"""
EDOPro / ygopro 카드 데이터베이스 비트마스크 상수 및 한국어 게임 용어 어휘.

이 모듈의 값은 실제 ``cards.cdb`` 데이터로 검증되었다.
- ``datas.type``      : TYPE_* 비트마스크 (예: Dark Magician = 0x11 = MONSTER|NORMAL)
- ``datas.attribute`` : ATTRIBUTE_* 비트마스크 (예: 0x20 = DARK)
- ``datas.race``      : RACE_* 비트마스크 (예: 0x2 = SPELLCASTER)
- ``datas.level``     : 하위 바이트가 레벨/랭크/링크 값, 상위 바이트에 펜듈럼 스케일이 패킹됨
                        (예: D/D Savant Thomas = 0x06060008 -> 레벨 8, 스케일 6/6)
- ``datas.def``       : 링크 몬스터인 경우 수비력이 아니라 링크 마커 비트마스크
- ``atk``/``def``     : -2 는 물음표(?) 수치를 의미한다

한국어 어휘 테이블은 '게임 용어'(종족/속성/카드 종류)만 담는다.
공식 카드명과 카드 텍스트는 번역 대상이 아니며, 이 모듈에서 다루지 않는다.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 카드 종류 (datas.type)
# ---------------------------------------------------------------------------
TYPE_MONSTER = 0x1
TYPE_SPELL = 0x2
TYPE_TRAP = 0x4
TYPE_NORMAL = 0x10
TYPE_EFFECT = 0x20
TYPE_FUSION = 0x40
TYPE_RITUAL = 0x80
TYPE_TRAPMONSTER = 0x100
TYPE_SPIRIT = 0x200
TYPE_UNION = 0x400
TYPE_GEMINI = 0x800
TYPE_TUNER = 0x1000
TYPE_SYNCHRO = 0x2000
TYPE_TOKEN = 0x4000
TYPE_MAXIMUM = 0x8000
TYPE_QUICKPLAY = 0x10000
TYPE_CONTINUOUS = 0x20000
TYPE_EQUIP = 0x40000
TYPE_FIELD = 0x80000
TYPE_COUNTER = 0x100000
TYPE_FLIP = 0x200000
TYPE_TOON = 0x400000
TYPE_XYZ = 0x800000
TYPE_PENDULUM = 0x1000000
TYPE_SPSUMMON = 0x2000000
TYPE_LINK = 0x4000000

TYPE_NAMES: dict[int, str] = {
    TYPE_MONSTER: "MONSTER",
    TYPE_SPELL: "SPELL",
    TYPE_TRAP: "TRAP",
    TYPE_NORMAL: "NORMAL",
    TYPE_EFFECT: "EFFECT",
    TYPE_FUSION: "FUSION",
    TYPE_RITUAL: "RITUAL",
    TYPE_TRAPMONSTER: "TRAPMONSTER",
    TYPE_SPIRIT: "SPIRIT",
    TYPE_UNION: "UNION",
    TYPE_GEMINI: "GEMINI",
    TYPE_TUNER: "TUNER",
    TYPE_SYNCHRO: "SYNCHRO",
    TYPE_TOKEN: "TOKEN",
    TYPE_MAXIMUM: "MAXIMUM",
    TYPE_QUICKPLAY: "QUICKPLAY",
    TYPE_CONTINUOUS: "CONTINUOUS",
    TYPE_EQUIP: "EQUIP",
    TYPE_FIELD: "FIELD",
    TYPE_COUNTER: "COUNTER",
    TYPE_FLIP: "FLIP",
    TYPE_TOON: "TOON",
    TYPE_XYZ: "XYZ",
    TYPE_PENDULUM: "PENDULUM",
    TYPE_SPSUMMON: "SPSUMMON",
    TYPE_LINK: "LINK",
}

# 카드 종류 한국어 표기 (게임 용어)
TYPE_KO: dict[int, str] = {
    TYPE_MONSTER: "몬스터",
    TYPE_SPELL: "마법",
    TYPE_TRAP: "함정",
    TYPE_NORMAL: "일반",
    TYPE_EFFECT: "효과",
    TYPE_FUSION: "융합",
    TYPE_RITUAL: "의식",
    TYPE_TRAPMONSTER: "함정몬스터",
    TYPE_SPIRIT: "스피릿",
    TYPE_UNION: "유니온",
    TYPE_GEMINI: "듀얼",
    TYPE_TUNER: "튜너",
    TYPE_SYNCHRO: "싱크로",
    TYPE_TOKEN: "토큰",
    TYPE_MAXIMUM: "맥시멈",
    TYPE_QUICKPLAY: "속공",
    TYPE_CONTINUOUS: "지속",
    TYPE_EQUIP: "장착",
    TYPE_FIELD: "필드",
    TYPE_COUNTER: "카운터",
    TYPE_FLIP: "리버스",
    TYPE_TOON: "툰",
    TYPE_XYZ: "엑시즈",
    TYPE_PENDULUM: "펜듈럼",
    TYPE_SPSUMMON: "특수소환",
    TYPE_LINK: "링크",
}

# ---------------------------------------------------------------------------
# 속성 (datas.attribute)
# ---------------------------------------------------------------------------
ATTRIBUTE_EARTH = 0x1
ATTRIBUTE_WATER = 0x2
ATTRIBUTE_FIRE = 0x4
ATTRIBUTE_WIND = 0x8
ATTRIBUTE_LIGHT = 0x10
ATTRIBUTE_DARK = 0x20
ATTRIBUTE_DIVINE = 0x40

ATTRIBUTE_NAMES: dict[int, str] = {
    ATTRIBUTE_EARTH: "EARTH",
    ATTRIBUTE_WATER: "WATER",
    ATTRIBUTE_FIRE: "FIRE",
    ATTRIBUTE_WIND: "WIND",
    ATTRIBUTE_LIGHT: "LIGHT",
    ATTRIBUTE_DARK: "DARK",
    ATTRIBUTE_DIVINE: "DIVINE",
}

ATTRIBUTE_KO: dict[int, str] = {
    ATTRIBUTE_EARTH: "땅",
    ATTRIBUTE_WATER: "물",
    ATTRIBUTE_FIRE: "불",
    ATTRIBUTE_WIND: "바람",
    ATTRIBUTE_LIGHT: "빛",
    ATTRIBUTE_DARK: "어둠",
    ATTRIBUTE_DIVINE: "신",
}

# ---------------------------------------------------------------------------
# 종족 (datas.race)
# ---------------------------------------------------------------------------
RACE_WARRIOR = 0x1
RACE_SPELLCASTER = 0x2
RACE_FAIRY = 0x4
RACE_FIEND = 0x8
RACE_ZOMBIE = 0x10
RACE_MACHINE = 0x20
RACE_AQUA = 0x40
RACE_PYRO = 0x80
RACE_ROCK = 0x100
RACE_WINDBEAST = 0x200
RACE_PLANT = 0x400
RACE_INSECT = 0x800
RACE_THUNDER = 0x1000
RACE_DRAGON = 0x2000
RACE_BEAST = 0x4000
RACE_BEASTWARRIOR = 0x8000
RACE_DINOSAUR = 0x10000
RACE_FISH = 0x20000
RACE_SEASERPENT = 0x40000
RACE_REPTILE = 0x80000
RACE_PSYCHIC = 0x100000
RACE_DIVINE = 0x200000
RACE_CREATORGOD = 0x400000
RACE_WYRM = 0x800000
RACE_CYBERSE = 0x1000000
RACE_ILLUSION = 0x2000000

RACE_NAMES: dict[int, str] = {
    RACE_WARRIOR: "WARRIOR",
    RACE_SPELLCASTER: "SPELLCASTER",
    RACE_FAIRY: "FAIRY",
    RACE_FIEND: "FIEND",
    RACE_ZOMBIE: "ZOMBIE",
    RACE_MACHINE: "MACHINE",
    RACE_AQUA: "AQUA",
    RACE_PYRO: "PYRO",
    RACE_ROCK: "ROCK",
    RACE_WINDBEAST: "WINGED_BEAST",
    RACE_PLANT: "PLANT",
    RACE_INSECT: "INSECT",
    RACE_THUNDER: "THUNDER",
    RACE_DRAGON: "DRAGON",
    RACE_BEAST: "BEAST",
    RACE_BEASTWARRIOR: "BEAST_WARRIOR",
    RACE_DINOSAUR: "DINOSAUR",
    RACE_FISH: "FISH",
    RACE_SEASERPENT: "SEA_SERPENT",
    RACE_REPTILE: "REPTILE",
    RACE_PSYCHIC: "PSYCHIC",
    RACE_DIVINE: "DIVINE_BEAST",
    RACE_CREATORGOD: "CREATOR_GOD",
    RACE_WYRM: "WYRM",
    RACE_CYBERSE: "CYBERSE",
    RACE_ILLUSION: "ILLUSION",
}

RACE_KO: dict[int, str] = {
    RACE_WARRIOR: "전사",
    RACE_SPELLCASTER: "마법사",
    RACE_FAIRY: "천사",
    RACE_FIEND: "악마",
    RACE_ZOMBIE: "언데드",
    RACE_MACHINE: "기계",
    RACE_AQUA: "물",
    RACE_PYRO: "화염",
    RACE_ROCK: "암석",
    RACE_WINDBEAST: "비행야수",
    RACE_PLANT: "식물",
    RACE_INSECT: "곤충",
    RACE_THUNDER: "번개",
    RACE_DRAGON: "드래곤",
    RACE_BEAST: "야수",
    RACE_BEASTWARRIOR: "야수전사",
    RACE_DINOSAUR: "공룡",
    RACE_FISH: "어류",
    RACE_SEASERPENT: "해룡",
    RACE_REPTILE: "파충류",
    RACE_PSYCHIC: "사이킥",
    RACE_DIVINE: "환신야수",
    RACE_CREATORGOD: "창조신",
    RACE_WYRM: "환룡",
    RACE_CYBERSE: "사이버스",
    RACE_ILLUSION: "환상마",
}


# 공식 카드 텍스트(영문 원문)에 등장하는 종족 표기.
# 카드명/카드 텍스트를 번역하기 위한 것이 아니라,
# "마법사족에 좋은 카드" 같은 서포트 질의에서 원문을 검색하기 위한 용어 대조표다.
RACE_TEXT_EN: dict[int, tuple[str, ...]] = {
    RACE_WARRIOR: ("Warrior",),
    RACE_SPELLCASTER: ("Spellcaster",),
    RACE_FAIRY: ("Fairy",),
    RACE_FIEND: ("Fiend",),
    RACE_ZOMBIE: ("Zombie",),
    RACE_MACHINE: ("Machine",),
    RACE_AQUA: ("Aqua",),
    RACE_PYRO: ("Pyro",),
    RACE_ROCK: ("Rock",),
    RACE_WINDBEAST: ("Winged Beast",),
    RACE_PLANT: ("Plant",),
    RACE_INSECT: ("Insect",),
    RACE_THUNDER: ("Thunder",),
    RACE_DRAGON: ("Dragon",),
    RACE_BEAST: ("Beast",),
    RACE_BEASTWARRIOR: ("Beast-Warrior",),
    RACE_DINOSAUR: ("Dinosaur",),
    RACE_FISH: ("Fish",),
    RACE_SEASERPENT: ("Sea Serpent",),
    RACE_REPTILE: ("Reptile",),
    RACE_PSYCHIC: ("Psychic",),
    RACE_DIVINE: ("Divine-Beast",),
    RACE_CREATORGOD: ("Creator God",),
    RACE_WYRM: ("Wyrm",),
    RACE_CYBERSE: ("Cyberse",),
    RACE_ILLUSION: ("Illusion",),
}

# ---------------------------------------------------------------------------
# 링크 마커 (링크 몬스터의 datas.def 컬럼)
# ---------------------------------------------------------------------------
LINK_MARKER_BOTTOM_LEFT = 0x1
LINK_MARKER_BOTTOM = 0x2
LINK_MARKER_BOTTOM_RIGHT = 0x4
LINK_MARKER_LEFT = 0x8
LINK_MARKER_RIGHT = 0x20
LINK_MARKER_TOP_LEFT = 0x40
LINK_MARKER_TOP = 0x80
LINK_MARKER_TOP_RIGHT = 0x100

LINK_MARKER_KO: dict[int, str] = {
    LINK_MARKER_TOP_LEFT: "좌상",
    LINK_MARKER_TOP: "상",
    LINK_MARKER_TOP_RIGHT: "우상",
    LINK_MARKER_LEFT: "좌",
    LINK_MARKER_RIGHT: "우",
    LINK_MARKER_BOTTOM_LEFT: "좌하",
    LINK_MARKER_BOTTOM: "하",
    LINK_MARKER_BOTTOM_RIGHT: "우하",
}

# ---------------------------------------------------------------------------
# 특수 수치
# ---------------------------------------------------------------------------
STAT_UNKNOWN = -2  # ?ATK / ?DEF
STAT_NONE = -1  # 수치 없음 (링크 몬스터의 수비력 등)

# ot (OCG/TCG 발매 여부)
OT_OCG = 0x1
OT_TCG = 0x2

OT_KO: dict[int, str] = {
    OT_OCG: "OCG",
    OT_TCG: "TCG",
    OT_OCG | OT_TCG: "OCG/TCG",
}


def decode_bitmask(value: int, names: dict[int, str]) -> list[str]:
    """비트마스크를 이름 목록으로 분해한다. 정의되지 않은 비트는 무시한다."""
    return [name for bit, name in names.items() if value & bit]


def encode_bitmask(names: list[str], table: dict[int, str]) -> int:
    """이름 목록을 비트마스크로 합친다. 알 수 없는 이름은 무시한다."""
    reverse = {v: k for k, v in table.items()}
    mask = 0
    for name in names:
        bit = reverse.get(name)
        if bit is not None:
            mask |= bit
    return mask


def _reverse_ko(table: dict[int, str]) -> dict[str, int]:
    return {ko: bit for bit, ko in table.items()}


# 한국어 용어 -> 비트값 (쿼리 파서가 사용)
KO_TO_RACE: dict[str, int] = _reverse_ko(RACE_KO)
KO_TO_ATTRIBUTE: dict[str, int] = _reverse_ko(ATTRIBUTE_KO)
KO_TO_TYPE: dict[str, int] = _reverse_ko(TYPE_KO)

# 종족/속성의 흔한 이형 표기 보강
KO_RACE_ALIASES: dict[str, int] = {
    "전사족": RACE_WARRIOR,
    "마법사족": RACE_SPELLCASTER,
    "천사족": RACE_FAIRY,
    "악마족": RACE_FIEND,
    "언데드족": RACE_ZOMBIE,
    "좀비족": RACE_ZOMBIE,
    "기계족": RACE_MACHINE,
    "물족": RACE_AQUA,
    "화염족": RACE_PYRO,
    "암석족": RACE_ROCK,
    "비행야수족": RACE_WINDBEAST,
    "새붙이족": RACE_WINDBEAST,
    "식물족": RACE_PLANT,
    "곤충족": RACE_INSECT,
    "번개족": RACE_THUNDER,
    "드래곤족": RACE_DRAGON,
    "용족": RACE_DRAGON,
    "야수족": RACE_BEAST,
    "야수전사족": RACE_BEASTWARRIOR,
    "공룡족": RACE_DINOSAUR,
    "어류족": RACE_FISH,
    "해룡족": RACE_SEASERPENT,
    "파충류족": RACE_REPTILE,
    "사이킥족": RACE_PSYCHIC,
    "환신야수족": RACE_DIVINE,
    "창조신족": RACE_CREATORGOD,
    "환룡족": RACE_WYRM,
    "사이버스족": RACE_CYBERSE,
    "환상마족": RACE_ILLUSION,
}

KO_ATTRIBUTE_ALIASES: dict[str, int] = {
    "땅속성": ATTRIBUTE_EARTH,
    "지속성": ATTRIBUTE_EARTH,
    "물속성": ATTRIBUTE_WATER,
    "수속성": ATTRIBUTE_WATER,
    "불속성": ATTRIBUTE_FIRE,
    "화속성": ATTRIBUTE_FIRE,
    "염속성": ATTRIBUTE_FIRE,
    "바람속성": ATTRIBUTE_WIND,
    "풍속성": ATTRIBUTE_WIND,
    "빛속성": ATTRIBUTE_LIGHT,
    "광속성": ATTRIBUTE_LIGHT,
    "어둠속성": ATTRIBUTE_DARK,
    "암속성": ATTRIBUTE_DARK,
    "신속성": ATTRIBUTE_DIVINE,
}
