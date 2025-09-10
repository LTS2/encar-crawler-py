"""
데이터베이스 모델 및 연결 관리
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

Base = declarative_base()


class CarPrice(Base):
    """차량 시세 정보 테이블"""

    __tablename__ = "car_prices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    manufacturer = Column(String(100), nullable=False, comment="제조사")
    model = Column(String(100), nullable=False, comment="모델")
    detailed_model = Column(String(200), comment="세부모델")
    year = Column(String(50), comment="연식")
    fuel_type = Column(String(50), comment="연료")
    grade = Column(String(100), comment="등급")
    detailed_grade = Column(String(200), comment="세부등급")

    # 가격 정보
    price = Column(Float, comment="시세 (만원)")
    is_price_available = Column(Boolean, default=True, comment="시세 제공 여부")
    price_message = Column(Text, comment="시세 미제공시 메시지")

    # 메타데이터
    crawled_at = Column(DateTime, default=datetime.now, comment="크롤링 시간")
    options_hash = Column(String(255), comment="옵션 조합 해시값")

    # 추가 정보
    manufacturer_code = Column(String(50), comment="제조사 코드")
    model_code = Column(String(50), comment="모델 코드")
    detailed_model_code = Column(String(50), comment="세부모델 코드")
    year_code = Column(String(50), comment="연식 코드")
    fuel_code = Column(String(50), comment="연료 코드")
    grade_code = Column(String(50), comment="등급 코드")
    detailed_grade_code = Column(String(50), comment="세부등급 코드")

    def __repr__(self):
        return (
            f"<CarPrice({self.manufacturer} {self.model} {self.year} - {self.price}만원)>"
        )


class CrawlingLog(Base):
    """크롤링 로그 테이블"""

    __tablename__ = "crawling_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    started_at = Column(DateTime, default=datetime.now)
    ended_at = Column(DateTime)
    status = Column(String(50))  # SUCCESS, FAILED, PARTIAL
    total_combinations = Column(Integer)
    success_count = Column(Integer)
    failed_count = Column(Integer)
    error_message = Column(Text)


def get_db_engine():
    """데이터베이스 엔진 생성"""
    # SQLite 사용 (바로 실행 가능)
    connection_string = "sqlite:///encar_prices.db"

    # MySQL 사용시 아래 주석 해제
    # connection_string = f"mysql+pymysql://{config.DB_USER}:{config.DB_PASSWORD}@{config.DB_HOST}:{config.DB_PORT}/{config.DB_NAME}?charset=utf8mb4"

    engine = create_engine(
        connection_string,
        echo=False,
        pool_pre_ping=True if "mysql" in connection_string else False,
        pool_recycle=3600 if "mysql" in connection_string else -1,
    )
    return engine


def init_database():
    """데이터베이스 초기화"""
    engine = get_db_engine()
    Base.metadata.create_all(engine)
    return engine


def get_session():
    """데이터베이스 세션 생성"""
    engine = get_db_engine()
    Session = sessionmaker(bind=engine)
    return Session()
