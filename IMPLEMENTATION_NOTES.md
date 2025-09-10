# 엔카 크롤러 구현 노트

## 📌 현재 상황

엔카 웹사이트가 구조를 변경하여 기존에 언급된 `op_dep1~6` 셀렉터들이 더 이상 존재하지 않습니다.
현재 `/pr/pr_index.do` 페이지는 메인 페이지로 리다이렉트되고 있습니다.

## 🔧 완성된 기능

### 1. **프로젝트 구조**
- ✅ Python 기반 (유지보수 용이)
- ✅ Playwright 사용 (동적 페이지 처리)
- ✅ SQLite/MySQL 데이터베이스 지원
- ✅ 비동기 처리로 성능 최적화

### 2. **주요 파일**
- `crawler.py`: 메인 크롤링 로직
- `database.py`: 데이터베이스 모델 및 연결
- `config.py`: 설정 파일
- `main.py`: 실행 진입점

### 3. **해결한 문제들**
- ✅ Chromium 호환성 문제 → Firefox로 전환
- ✅ DOM 재렌더링 대기 로직 구현
- ✅ 재시도 로직 구현
- ✅ 데이터베이스 저장 로직

## 🔍 크롤링 전략

### 방법 1: 직접 API 호출 분석
```python
# 브라우저 개발자 도구에서 Network 탭을 열고
# 시세 조회 시 발생하는 API 호출을 캡처
# 해당 API를 직접 호출하는 방식
```

### 방법 2: 현재 페이지 구조에 맞게 수정
```python
# find_exact_elements.py 참고
# 실제 페이지의 select 요소 ID/name을 찾아서
# crawler.py의 get_select_options() 메서드 수정
```

### 방법 3: 시세 페이지 직접 탐색
```python
# navigate_to_price.py 참고
# 메인 페이지에서 시작하여
# 시세 관련 메뉴를 클릭하여 이동
```

## 💡 수정 필요 부분

### crawler.py 수정 예시:
```python
# 기존 코드 (op_dep1~6 사용)
manufacturers = await self.get_select_options('op_dep1')

# 수정 필요 (실제 셀렉터로 변경)
manufacturers = await self.get_select_options('실제_제조사_셀렉터_ID')
```

## 🚦 실행 방법

### 1. 환경 설정
```bash
# 가상환경 생성 및 활성화
python -m venv venv
source venv/bin/activate  # macOS/Linux

# 패키지 설치
pip install -r requirements.txt

# 브라우저 설치
playwright install firefox
```

### 2. 데이터베이스 초기화
```bash
python main.py --init-db
```

### 3. 페이지 구조 분석 (디버깅)
```bash
# 시세 페이지 찾기
python find_price_page.py

# 페이지 요소 분석
python analyze_price_page.py

# 정확한 요소 찾기
python find_exact_elements.py
```

### 4. 크롤링 실행
```bash
# 테스트 모드
python main.py --test

# 전체 크롤링 (셀렉터 수정 후)
python main.py
```

## 📝 다음 단계

1. **페이지 분석**: 현재 엔카 시세 페이지의 정확한 구조 파악
2. **셀렉터 업데이트**: crawler.py의 셀렉터를 실제 페이지에 맞게 수정
3. **API 분석**: 가능하다면 직접 API 호출 방식으로 전환
4. **테스트**: 수정된 코드로 소규모 테스트 진행
5. **전체 실행**: 모든 옵션 조합 크롤링

## 🔧 트러블슈팅

### 문제: Select 요소를 찾을 수 없음
```python
# 해결: 동적 로딩 대기 시간 증가
await page.wait_for_timeout(5000)

# 또는 특정 요소 대기
await page.wait_for_selector('select', timeout=10000)
```

### 문제: 페이지 리다이렉트
```python
# 해결: 쿠키/세션 설정 확인
await context.add_cookies([...])

# 또는 User-Agent 변경
context = await browser.new_context(
    user_agent='Mozilla/5.0...'
)
```

### 문제: 가격 정보 추출 실패
```python
# 해결: 여러 셀렉터 시도
price_selectors = [
    '.price_result',
    '[class*="price"]',
    'span:has-text("만원")'
]
```

## 📌 중요 참고사항

- **robots.txt 준수**: `/pr/` 경로는 크롤링 허용
- **요청 간격**: 서버 부담 최소화를 위해 적절한 딜레이 사용
- **에러 처리**: 모든 요청에 try-except 적용
- **데이터 검증**: 저장 전 데이터 유효성 확인

## 🤝 기여 방법

1. 현재 페이지 구조 분석
2. 셀렉터 업데이트
3. 테스트 및 검증
4. Pull Request 제출

---

**작성일**: 2024년 9월
**Python 버전**: 3.8+
**주요 라이브러리**: Playwright, SQLAlchemy, BeautifulSoup4
