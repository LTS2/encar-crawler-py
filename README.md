# 엔카 시세 크롤러 (Encar Price Crawler)

엔카(encar.com)의 차량 시세 정보를 자동으로 크롤링하는 파이썬 프로젝트입니다.

⚠️ **중요**: 엔카 웹사이트 구조가 변경되어 시세 페이지 접근 방식이 달라졌습니다.
현재 프레임워크는 완성되었으며, 페이지 구조에 맞게 셀렉터를 수정하여 사용하시면 됩니다.

## 🚀 주요 기능

- 모든 차량 옵션 조합의 시세 자동 크롤링
- DOM 재렌더링 문제 해결
- 데이터베이스 자동 저장
- 재시도 로직 및 에러 처리
- 실시간 진행 상황 표시

## 📋 요구사항

- Python 3.8+
- MySQL 5.7+ (또는 SQLite)
- Chrome 브라우저

## 🔧 설치 방법

### 1. 프로젝트 클론
```bash
cd ~/encar-crawling
```

### 2. 가상환경 생성 및 활성화
```bash
python -m venv venv
source venv/bin/activate  # macOS/Linux
# venv\Scripts\activate  # Windows
```

### 3. 패키지 설치
```bash
pip install -r requirements.txt
```

### 4. Playwright 브라우저 설치
```bash
playwright install chromium
```

### 5. 환경 설정
```bash
# .env 파일 생성
cat > .env << EOF
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=your_password
DB_NAME=encar_prices
EOF
```

### 6. 데이터베이스 초기화
```bash
python main.py --init-db
```

## 💻 사용 방법

### 전체 크롤링 실행
```bash
python main.py
```

### 테스트 모드 (단일 조합)
```bash
python main.py --test
```

### Headless 모드로 실행
```bash
python main.py --headless
```

### 크롤링 통계 확인
```bash
python main.py --stats
```

## 🗄️ 데이터베이스 구조

### car_prices 테이블
- `manufacturer`: 제조사
- `model`: 모델
- `detailed_model`: 세부모델
- `year`: 연식
- `fuel_type`: 연료
- `grade`: 등급
- `detailed_grade`: 세부등급
- `price`: 시세 (만원)
- `is_price_available`: 시세 제공 여부
- `crawled_at`: 크롤링 시간

## ⚙️ 설정 옵션

`config.py` 파일에서 다음 설정을 변경할 수 있습니다:

- `HEADLESS`: 브라우저 표시 여부 (False=표시, True=숨김)
- `TIMEOUT`: 요소 대기 시간 (밀리초)
- `RETRY_COUNT`: 재시도 횟수
- `WAIT_BETWEEN_ACTIONS`: 액션 간 대기 시간 (밀리초)

## 🔍 문제 해결

### MySQL 연결 오류
SQLite로 전환하려면 `database.py`의 `get_db_engine()` 함수에서:
```python
# MySQL 대신 SQLite 사용
connection_string = "sqlite:///encar_prices.db"
```

### DOM 재렌더링 문제
- `WAIT_BETWEEN_ACTIONS` 값을 늘려보세요 (기본: 1500ms)
- `HEADLESS`를 False로 설정하여 문제를 시각적으로 확인

### 크롤링 속도가 느린 경우
- 병렬 처리는 엔카 서버에 부담을 줄 수 있으므로 권장하지 않습니다
- 야간 시간대에 실행하는 것을 권장합니다

## ⚠️ 주의사항

1. **robots.txt 준수**: 이 크롤러는 엔카의 robots.txt를 준수합니다
2. **서버 부담 최소화**: 과도한 요청을 피하기 위해 적절한 딜레이를 사용합니다
3. **개인 용도**: 상업적 사용 시 엔카의 이용약관을 확인하세요
4. **데이터 정확성**: 크롤링된 데이터는 참고용이며, 실제 거래 시 엔카에서 직접 확인하세요

## 📊 예상 소요 시간

- 전체 옵션 조합: 약 10,000-50,000개 (차량 종류에 따라 다름)
- 예상 시간: 5-20시간 (네트워크 상태와 옵션 수에 따라 다름)
- 권장: 야간에 실행하거나 특정 제조사만 선택하여 크롤링

## 🛠️ 개발 모드

### 특정 제조사만 크롤링
`crawler.py`의 `crawl_all_combinations()` 함수에서 제조사 필터링:
```python
manufacturers = [m for m in manufacturers if '현대' in m['text']]
```

### 디버그 모드
```python
# crawler.py에서
self.headless = False  # 브라우저 표시
console.print(f"[debug]{변수명}[/debug]")  # 디버그 출력
```

## 📝 라이센스

이 프로젝트는 교육 및 연구 목적으로만 사용하세요.
