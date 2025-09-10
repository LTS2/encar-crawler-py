#!/bin/bash

echo "================================"
echo "엔카 크롤러 설치 스크립트"
echo "================================"

# Python 버전 확인
echo "Python 버전 확인 중..."
python3 --version

# 가상환경 생성
echo "가상환경 생성 중..."
python3 -m venv venv

# 가상환경 활성화
echo "가상환경 활성화 중..."
source venv/bin/activate

# 패키지 설치
echo "필요한 패키지 설치 중..."
pip install --upgrade pip
pip install -r requirements.txt

# Playwright 브라우저 설치
echo "Playwright 브라우저 설치 중..."
playwright install chromium

# 데이터베이스 초기화
echo "데이터베이스 초기화 중..."
python main.py --init-db

echo "================================"
echo "설치 완료!"
echo "================================"
echo ""
echo "실행 방법:"
echo "1. 가상환경 활성화: source venv/bin/activate"
echo "2. 테스트 실행: python main.py --test"
echo "3. 전체 크롤링: python main.py"
echo ""
