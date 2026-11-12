# -*- coding: utf-8 -*-
"""Keep local Alpaca market-data keys outside the published GitHub files."""
from pathlib import Path
import getpass, json, os

def main():
    p=Path(__file__).resolve().parent/'data'/'alpaca_private.json'
    p.parent.mkdir(exist_ok=True)
    print('Alpaca 시세 조회 API 키 설정 (주문 기능 없음)')
    print('주의: 이 파일/키를 GitHub에 업로드하면 안 됩니다.')
    key=input('API Key ID: ').strip()
    secret=getpass.getpass('Secret Key (입력 숨김): ').strip()
    if not key or not secret:
        print('설정 취소: 키 값이 비어 있습니다');return
    p.write_text(json.dumps({'key_id':key,'secret_key':secret},ensure_ascii=False),encoding='utf-8')
    try:os.chmod(p,0o600)
    except OSError:pass
    print('로컬 키 저장 완료. 이 파일을 GitHub에 올리지 마세요.')

if __name__=='__main__':main()
