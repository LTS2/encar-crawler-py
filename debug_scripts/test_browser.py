"""
브라우저 테스트 스크립트
"""
import asyncio

from playwright.async_api import async_playwright


async def test():
    print("브라우저 시작 중...")
    playwright = await async_playwright().start()
    browser = None

    try:
        # 여러 브라우저 시도
        browsers = [
            ("chromium", playwright.chromium),
            ("firefox", playwright.firefox),
            ("webkit", playwright.webkit),
        ]

        for browser_name, browser_type in browsers:
            try:
                print(f"\n{browser_name} 실행 시도 중...")
                browser = await browser_type.launch(
                    headless=True,  # headless로 먼저 시도
                    args=["--no-sandbox", "--disable-setuid-sandbox"]
                    if browser_name == "chromium"
                    else [],
                )

                print(f"{browser_name} 실행 성공!")

                print("페이지 생성 중...")
                page = await browser.new_page()

                print("구글 접속 중...")
                await page.goto("https://www.google.com")

                print("페이지 타이틀:", await page.title())

                print(f"{browser_name} 테스트 성공!")
                break

            except Exception as e:
                print(f"{browser_name} 실행 실패: {e}")
                if browser:
                    await browser.close()
                    browser = None
                continue

    except Exception as e:
        print(f"전체 오류: {e}")
        import traceback

        traceback.print_exc()

    finally:
        if browser:
            print("브라우저 종료 중...")
            await browser.close()
        await playwright.stop()
        print("완료!")


if __name__ == "__main__":
    asyncio.run(test())
