"""
wrp_price 영역 상세 분석
"""
import asyncio

from playwright.async_api import async_playwright


async def analyze_wrp_price():
    """wrp_price 영역 상세 분석"""
    playwright = await async_playwright().start()
    browser = await playwright.firefox.launch(headless=False)

    try:
        page = await browser.new_page()

        print("엔카 시세 페이지 접속 중...")
        await page.goto(
            "https://www.encar.com/pr/pr_index.do",
            wait_until="networkidle",
            timeout=30000,
        )
        await page.wait_for_timeout(5000)

        print(f"현재 URL: {page.url}")
        print(f"타이틀: {await page.title()}\n")

        # wrp_price 영역 분석
        wrp_price = await page.query_selector(".wrp_price")
        if wrp_price:
            print("✓ .wrp_price 영역 발견!\n")

            # wrp_price 내부의 모든 select 요소 찾기
            selects = await wrp_price.query_selector_all("select")
            print(f".wrp_price 내부 Select 개수: {len(selects)}개")

            for i, select in enumerate(selects):
                select_id = await select.get_attribute("id")
                select_name = await select.get_attribute("name")
                select_class = await select.get_attribute("class")
                options = await select.query_selector_all("option")

                print(f"\nSelect {i+1}:")
                print(f"  ID: {select_id}")
                print(f"  Name: {select_name}")
                print(f"  Class: {select_class}")
                print(f"  옵션 개수: {len(options)}")

                if len(options) > 0:
                    for j, option in enumerate(options[:3]):  # 처음 3개만
                        option_text = await option.inner_text()
                        option_value = await option.get_attribute("value")
                        print(
                            f"    옵션 {j+1}: text='{option_text}', value='{option_value}'"
                        )

            # wrp_price 내부의 input 요소 찾기
            print("\n.wrp_price 내부 Input 요소:")
            inputs = await wrp_price.query_selector_all("input")
            print(f"Input 개수: {len(inputs)}개")

            for i, input_elem in enumerate(inputs[:5]):
                input_type = await input_elem.get_attribute("type")
                input_id = await input_elem.get_attribute("id")
                input_name = await input_elem.get_attribute("name")
                print(
                    f"  Input {i+1}: type='{input_type}', id='{input_id}', name='{input_name}'"
                )

            # wrp_price 내부의 버튼 찾기
            print("\n.wrp_price 내부 버튼:")
            buttons = await wrp_price.query_selector_all(
                'button, a[href*="javascript"], [onclick]'
            )
            print(f"버튼/클릭 가능 요소: {len(buttons)}개")

            for i, button in enumerate(buttons[:5]):
                button_text = await button.inner_text()
                onclick = await button.get_attribute("onclick")
                print(f"  버튼 {i+1}: text='{button_text.strip()}', onclick='{onclick}'")

            # HTML 구조 일부 출력
            print("\n.wrp_price HTML 구조 (일부):")
            inner_html = await wrp_price.inner_html()
            print(inner_html[:1000])

        else:
            print("✗ .wrp_price 영역을 찾을 수 없습니다.")

            # 전체 페이지에서 select 찾기
            all_selects = await page.query_selector_all("select")
            print(f"\n전체 페이지 Select 개수: {len(all_selects)}개")

            for i, select in enumerate(all_selects[:5]):
                select_id = await select.get_attribute("id")
                select_name = await select.get_attribute("name")
                print(f"  Select {i+1}: id='{select_id}', name='{select_name}'")

        # 페이지 스크린샷
        await page.screenshot(path="wrp_price_analysis.png", full_page=True)
        print("\n스크린샷 저장: wrp_price_analysis.png")

        print("\n30초 후 종료. 페이지를 확인하세요...")
        await page.wait_for_timeout(30000)

    except Exception as e:
        print(f"오류: {e}")
        import traceback

        traceback.print_exc()

    finally:
        await browser.close()
        await playwright.stop()


if __name__ == "__main__":
    asyncio.run(analyze_wrp_price())
