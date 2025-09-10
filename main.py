"""
엔카 크롤러 메인 실행 파일
"""

import argparse
import asyncio

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

import config
from crawler import EncarCrawler
from database import CarPrice, get_session, init_database

console = Console()


def setup_database():
    """데이터베이스 초기화"""
    try:
        console.print("[cyan]데이터베이스 초기화 중...[/cyan]")
        init_database()
        console.print("[green]✓ 데이터베이스 초기화 완료[/green]")
        return True
    except Exception as e:
        console.print(f"[red]✗ 데이터베이스 초기화 실패: {e}[/red]")
        console.print(
            "[yellow]MySQL이 설치되어 있는지 확인하거나, database.py에서 SQLite로 전환하세요.[/yellow]"
        )
        return False


def show_statistics():
    """크롤링 통계 표시"""
    session = get_session()

    try:
        total_count = session.query(CarPrice).count()
        with_price = (
            session.query(CarPrice).filter(CarPrice.is_price_available == True).count()
        )
        without_price = (
            session.query(CarPrice).filter(CarPrice.is_price_available == False).count()
        )

        # 제조사별 통계
        manufacturers = (
            session.query(CarPrice.manufacturer, CarPrice.manufacturer).distinct().all()
        )

        # 통계 테이블 생성
        table = Table(title="크롤링 데이터 통계")
        table.add_column("항목", style="cyan")
        table.add_column("수량", style="magenta")

        table.add_row("전체 데이터", str(total_count))
        table.add_row("시세 제공", str(with_price))
        table.add_row("시세 미제공", str(without_price))
        table.add_row("제조사 수", str(len(manufacturers)))

        console.print(table)

        # 최근 크롤링 데이터 샘플
        recent_data = (
            session.query(CarPrice).order_by(CarPrice.crawled_at.desc()).limit(5).all()
        )

        if recent_data:
            console.print("\n[bold cyan]최근 크롤링 데이터 (5개):[/bold cyan]")
            for car in recent_data:
                price_text = f"{car.price:,.0f}만원" if car.price else "시세 미제공"
                console.print(
                    f"  • {car.manufacturer} {car.model} {car.year} - {price_text}"
                )

    except Exception as e:
        console.print(f"[red]통계 조회 실패: {e}[/red]")
    finally:
        session.close()


async def run_crawler(test_mode: bool = False):
    """크롤러 실행"""
    crawler = None

    try:
        console.print(
            Panel.fit(
                "[bold cyan]엔카 시세 크롤러 시작[/bold cyan]\n"
                + f"URL: {config.ENCAR_URL}\n"
                + f"Headless: {config.HEADLESS}",
                title="크롤링 정보",
            )
        )

        crawler = EncarCrawler(headless=config.HEADLESS)
        await crawler.initialize()

        if test_mode:
            console.print("[yellow]테스트 모드로 실행합니다.[/yellow]")
            await crawler.test_single_combination()
        else:
            await crawler.crawl_all_combinations()

    except KeyboardInterrupt:
        console.print("\n[yellow]사용자에 의해 중단되었습니다.[/yellow]")
    except Exception as e:
        console.print(f"[red]크롤링 실패: {e}[/red]")
        import traceback

        console.print(f"[dim]{traceback.format_exc()}[/dim]")
    finally:
        if crawler:
            await crawler.close()


def main():
    """메인 함수"""
    parser = argparse.ArgumentParser(description="엔카 시세 크롤러")
    parser.add_argument("--test", action="store_true", help="테스트 모드 실행")
    parser.add_argument("--stats", action="store_true", help="크롤링 통계 표시")
    parser.add_argument("--init-db", action="store_true", help="데이터베이스 초기화")
    parser.add_argument("--headless", action="store_true", help="Headless 모드로 실행")

    args = parser.parse_args()

    # Headless 모드 설정
    if args.headless:
        config.HEADLESS = True

    # 데이터베이스 초기화
    if args.init_db:
        setup_database()
        return

    # 통계 표시
    if args.stats:
        show_statistics()
        return

    # 데이터베이스 확인
    if not setup_database():
        console.print("[red]데이터베이스 설정을 확인하세요.[/red]")
        return

    # 크롤러 실행
    asyncio.run(run_crawler(test_mode=args.test))


if __name__ == "__main__":
    main()
