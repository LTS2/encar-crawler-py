"""
엔카 시세 페이지 찾기 스크립트
"""
import asyncio

from playwright.async_api import async_playwright


async def find_price_page():
    """시세 페이지를 찾기 위한 스크립트"""
    playwright = await async_playwright().start()
    browser = await playwright.firefox.launch(headless=False)

    try:
        page = await browser.new_page()

        print("엔카 메인 페이지 접속 중...")
        await page.goto("https://www.encar.com", wait_until="networkidle")

        print("현재 URL:", page.url)
        print("페이지 타이틀:", await page.title())

        # 시세 관련 링크 찾기
        print("\n시세 관련 링크 검색 중...")

        # 여러 가능한 시세 링크 패턴
        price_link_selectors = [
            'a:has-text("시세")',
            'a:has-text("가격")',
            'a:has-text("시세조회")',
            'a:has-text("중고차시세")',
            'a[href*="price"]',
            'a[href*="pr_"]',
            'a[href*="시세"]',
            '.gnb a:has-text("시세")',
            'nav a:has-text("시세")',
        ]

        for selector in price_link_selectors:
            try:
                links = await page.query_selector_all(selector)
                if links:
                    print(f"\n'{selector}' 셀렉터로 {len(links)}개 링크 발견:")
                    for i, link in enumerate(links[:3]):  # 처음 3개만
                        text = await link.inner_text()
                        href = await link.get_attribute("href")
                        print(f"  {i+1}. 텍스트: '{text}', 링크: {href}")
            except:
                pass

        # 시세 페이지 직접 접속 시도
        print("\n\n가능한 시세 페이지 URL 테스트:")

        test_urls = [
            "https://www.encar.com/pr/pr_index.do",
            "https://www.encar.com/price",
            "https://www.encar.com/pr/pr_list.do",
            "https://www.encar.com/sise",
            "http://www.encar.com/pr/pr_index.do",
        ]

        for url in test_urls:
            print(f"\n테스트: {url}")
            response = await page.goto(
                url, wait_until="domcontentloaded", timeout=10000
            )
            await page.wait_for_timeout(2000)

            current_url = page.url
            title = await page.title()
            status = response.status if response else "N/A"

            print(f"  상태: {status}")
            print(f"  최종 URL: {current_url}")
            print(f"  타이틀: {title}")

            # 시세 관련 요소 찾기
            price_elements = await page.query_selector_all(
                '.wrp_price, .price, [class*="price"], [id*="price"]'
            )
            select_elements = await page.query_selector_all("select")

            print(f"  가격 관련 요소: {len(price_elements)}개")
            print(f"  Select 요소: {len(select_elements)}개")

            if len(select_elements) > 3:
                print(f"  ✓ 이 페이지가 시세 페이지일 가능성이 높습니다!")

                # 스크린샷 저장
                await page.screenshot(path=f'test_{url.split("/")[-1]}.png')

                # Select 요소 ID 확인
                for i, select in enumerate(select_elements[:6]):
                    select_id = await select.get_attribute("id")
                    select_name = await select.get_attribute("name")
                    if select_id or select_name:
                        print(
                            f"    Select {i+1}: id='{select_id}', name='{select_name}'"
                        )

        print("\n\n30초 후 브라우저가 종료됩니다. 수동으로 시세 페이지를 찾아보세요...")
        await page.wait_for_timeout(30000)

    except Exception as e:
        print(f"오류: {e}")
        import traceback

        traceback.print_exc()

    finally:
        await browser.close()
        await playwright.stop()


if __name__ == "__main__":
    asyncio.run(find_price_page())
