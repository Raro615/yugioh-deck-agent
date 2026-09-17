"""
유희왕 Lua 카드 파일 파싱 예시 (초기 프로토타입 — 더 이상 사용하지 않음)
Yu-Gi-Oh Lua Card File Parser Example (superseded)

이 파일의 기능은 ``sources/lua_loader.py`` 로 대체되었다.
차이점:

- 여기서는 상수를 파일 전체에서 뭉뚱그려 모으므로, 어떤 효과가 어디서
  발동하는지 알 수 없다. 새 파서는 ``Effect.CreateEffect`` 블록 단위로 묶는다.
- 새 파서는 ``e4=e3:Clone()`` 의 속성 상속과 ``CARD_*``/``SET_*`` 명명 상수를
  처리하고, 파싱 결과를 캐시한다.

참고용으로 남겨 두었다. 새 코드는 ``sources/lua_loader.py`` 를 사용할 것.
"""

import re
import os
from typing import Dict, List, Any

class LuaCardParser:
    """Lua 파일에서 카드 정보를 추출하는 클래스"""
    
    def __init__(self, lua_file_path: str):
        """
        Args:
            lua_file_path: Lua 파일 경로 (예: 'c2511.lua')
        """
        self.file_path = lua_file_path
        self.card_data = {}
        self.lua_code = ""
    
    def read_file(self) -> str:
        """Lua 파일 읽기"""
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                self.lua_code = f.read()
            return self.lua_code
        except FileNotFoundError:
            print(f"❌ 파일을 찾을 수 없습니다: {self.file_path}")
            return ""
    
    def extract_card_id(self) -> int:
        """카드 ID 추출 (파일명에서)"""
        # 파일명: c2511.lua → ID: 2511
        match = re.search(r'c(\d+)\.lua', self.file_path)
        if match:
            return int(match.group(1))
        return None
    
    def extract_card_name(self) -> str:
        """카드 이름 추출 (주석에서)"""
        # 예: --白銀の城の狂時計 또는 --Labrynth Cooclock
        lines = self.lua_code.split('\n')
        
        # 첫 3줄에서 찾기
        for i in range(min(3, len(lines))):
            line = lines[i]
            if line.startswith('--') and len(line) > 2:
                # 주석만 추출
                name = line[2:].strip()
                if name:  # 공백 제외
                    return name
        
        return "Unknown"
    
    def extract_series(self) -> List[str]:
        """테마/시리즈 추출"""
        # 패턴: s.listed_series={SET_LABRYNTH}
        matches = re.findall(r'SET_(\w+)', self.lua_code)
        return matches
    
    def extract_effect_keywords(self) -> List[str]:
        """효과 키워드 추출"""
        # 패턴: EFFECT_TYPE_QUICK_O, CATEGORY_TOHAND 등
        effect_types = re.findall(r'EFFECT_TYPE_(\w+)', self.lua_code)
        categories = re.findall(r'CATEGORY_(\w+)', self.lua_code)
        
        return list(set(effect_types + categories))
    
    def extract_listed_names(self) -> List[int]:
        """연계된 카드 이름/ID 추출"""
        # 패턴: s.listed_names={id, 123456}
        match = re.search(r's\.listed_names=\{([^}]+)\}', self.lua_code)
        if match:
            content = match.group(1)
            # 숫자만 추출
            ids = re.findall(r'\d+', content)
            return [int(id_) for id_ in ids]
        return []
    
    def extract_functions(self) -> List[str]:
        """함수 목록 추출"""
        # 패턴: function s.acop, function s.thcon 등
        functions = re.findall(r'function s\.(\w+)', self.lua_code)
        return functions
    
    def extract_conditions(self) -> List[str]:
        """발동 조건 추출"""
        # 패턴: EVENT_FREE_CHAIN, EVENT_TO_GRAVE 등
        conditions = re.findall(r'EVENT_(\w+)', self.lua_code)
        return list(set(conditions))
    
    def extract_effects_count(self) -> int:
        """총 효과 개수"""
        # e1, e2, e3... 개수 세기
        effects = re.findall(r'local e\d+', self.lua_code)
        return len(effects)
    
    def parse(self) -> Dict[str, Any]:
        """모든 정보 파싱"""
        if not self.lua_code:
            self.read_file()
        
        self.card_data = {
            'file_name': os.path.basename(self.file_path),
            'card_id': self.extract_card_id(),
            'card_name': self.extract_card_name(),
            'series': self.extract_series(),
            'effect_keywords': self.extract_effect_keywords(),
            'linked_cards': self.extract_listed_names(),
            'functions': self.extract_functions(),
            'trigger_events': self.extract_conditions(),
            'total_effects': self.extract_effects_count(),
        }
        
        return self.card_data
    
    def print_info(self):
        """파싱된 정보 출력"""
        if not self.card_data:
            self.parse()
        
        print("\n" + "="*50)
        print(f"카드 정보: {self.card_data['card_name']}")
        print("="*50)
        print(f"📋 파일: {self.card_data['file_name']}")
        print(f"🆔 카드 ID: {self.card_data['card_id']}")
        print(f"🏷️  테마: {', '.join(self.card_data['series']) if self.card_data['series'] else 'None'}")
        print(f"⚡ 효과 키워드: {', '.join(self.card_data['effect_keywords'][:5])}")
        print(f"🔗 연계 카드: {self.card_data['linked_cards']}")
        print(f"🎯 발동 조건: {', '.join(self.card_data['trigger_events'])}")
        print(f"📊 총 효과 수: {self.card_data['total_effects']}")
        print("="*50 + "\n")


# ============ 사용 예시 ============

if __name__ == "__main__":
    # 예시 1: 단일 카드 파싱
    print("🎮 유희왕 Lua 카드 파서 예시\n")
    
    parser = LuaCardParser('c2511.lua')
    card_info = parser.parse()
    parser.print_info()
    
    print("추출된 데이터 (JSON 형식):")
    print(card_info)
    
    # ============ 예시 2: 모든 카드 파싱 ============
    print("\n\n📂 모든 카드 파싱 예시:\n")
    
    def parse_all_cards(cards_dir: str = '.') -> List[Dict[str, Any]]:
        """디렉토리의 모든 c*.lua 파일 파싱"""
        all_cards = []
        
        # c*.lua 파일 찾기
        lua_files = [f for f in os.listdir(cards_dir) if re.match(r'c\d+\.lua$', f)]
        
        print(f"✅ 찾은 파일: {len(lua_files)}개\n")
        
        # 첫 5개만 파싱 (예시)
        for lua_file in lua_files[:5]:
            file_path = os.path.join(cards_dir, lua_file)
            parser = LuaCardParser(file_path)
            card_data = parser.parse()
            all_cards.append(card_data)
            print(f"✓ {lua_file} 파싱 완료")
        
        return all_cards
    
    # all_cards = parse_all_cards()
    # print(f"\n총 파싱된 카드: {len(all_cards)}개")
    
    # ============ 예시 3: 테마별 분류 ============
    print("\n\n🏷️  테마별 카드 분류 예시:\n")
    
    def group_by_series(cards: List[Dict[str, Any]]) -> Dict[str, List[int]]:
        """테마별로 카드 ID 그룹화"""
        series_dict = {}
        
        for card in cards:
            for series in card['series']:
                if series not in series_dict:
                    series_dict[series] = []
                series_dict[series].append(card['card_id'])
        
        return series_dict
    
    # 예시 사용
    # series_groups = group_by_series(all_cards)
    # for series, card_ids in series_groups.items():
    #     print(f"{series}: {len(card_ids)}개 - IDs: {card_ids}")
