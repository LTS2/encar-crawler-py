# 린팅 설정 가이드

이 프로젝트는 파이썬 파일 저장 시 자동으로 린팅이 적용되도록 설정되어 있습니다.

## 설정된 도구들

### 1. Black (코드 포맷팅)

- **설정 파일**: `pyproject.toml`
- **기능**: 자동 들여쓰기, 줄 길이 조정, 코드 스타일 통일
- **라인 길이**: 88자

### 2. isort (Import 정렬)

- **설정 파일**: `pyproject.toml`
- **기능**: import 문 자동 정렬
- **프로필**: black과 호환되는 설정

### 3. Pre-commit (자동 실행)

- **설정 파일**: `.pre-commit-config.yaml`
- **기능**: Git 커밋 시 자동으로 린팅 도구 실행

## 사용법

### 1. 수동 실행

```bash
# 가상환경 활성화
source venv/bin/activate

# Black으로 포맷팅
python -m black .

# isort로 import 정렬
python -m isort .

# 모든 파일에 대해 한 번에 실행
python -m black . && python -m isort .
```

### 2. 자동 실행 (권장)

- **VS Code**: 파일 저장 시 자동으로 포맷팅 적용
- **Git 커밋**: 커밋 시 자동으로 린팅 검사 및 수정

### 3. VS Code 설정

`.vscode/settings.json` 파일이 포함되어 있어 다음 기능이 자동으로 활성화됩니다:

- 파일 저장 시 자동 포맷팅
- import 자동 정렬
- 불필요한 공백 제거
- 파일 끝에 새 줄 자동 추가

## 설정 파일들

### pyproject.toml

```toml
[tool.black]
line-length = 88
target-version = ['py39']

[tool.isort]
profile = "black"
multi_line_output = 3
line_length = 88
```

### .pre-commit-config.yaml

```yaml
repos:
  - repo: https://github.com/psf/black
    rev: 23.12.1
    hooks:
      - id: black
        language_version: python3.9

  - repo: https://github.com/pycqa/isort
    rev: 5.13.2
    hooks:
      - id: isort
        args: ["--profile", "black"]
```

## 문제 해결

### 1. Pre-commit이 작동하지 않는 경우

```bash
# 가상환경 활성화 후 재설치
source venv/bin/activate
pre-commit install
```

### 2. 특정 파일을 린팅에서 제외하고 싶은 경우

`.gitignore` 파일에 해당 파일을 추가하거나, `pyproject.toml`의 `extend-exclude` 섹션에 추가합니다.

### 3. 수동으로 린팅 오류 수정

```bash
# Black으로 포맷팅
python -m black [파일명]

# isort로 import 정렬
python -m isort [파일명]
```

## 주의사항

- 모든 파이썬 파일은 저장 시 자동으로 포맷팅됩니다
- Git 커밋 시 린팅 검사가 실행되며, 오류가 있으면 커밋이 실패합니다
- 팀 작업 시 일관된 코드 스타일을 유지할 수 있습니다
