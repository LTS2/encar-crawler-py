"""
사용자가 언급한 정확한 요소들 찾기
"""
import asyncio

from playwright.async_api import async_playwright


async def find_exact_elements():
    """op_dep1 ~ op_dep6 요소 찾기"""
    playwright = await async_playwright().start()
    browser = await playwright.firefox.launch(headless=False)

    try:
        page = await browser.new_page()

        # 여러 가능한 URL 시도
        urls = [
            "https://www.encar.com/pr/pr_index.do",
        ]

        for url in urls:
            print(f"\n테스트 URL: {url}")

            try:
                await page.goto(url, wait_until="networkidle", timeout=30000)
                await page.wait_for_timeout(5000)

                print(f"현재 URL: {page.url}")
                print(f"타이틀: {await page.title()}")

                # wrp_price 클래스 찾기
                wrp_price = await page.query_selector(".wrp_price")
                if wrp_price:
                    print("✓ .wrp_price 요소 발견!")

                # op_dep1 ~ op_dep6 찾기
                found_elements = []
                for i in range(1, 7):
                    element_id = f"op_dep{i}"
                    element = await page.query_selector(f"#{element_id}")
                    if element:
                        print(f"✓ #{element_id} 요소 발견!")
                        found_elements.append(element_id)

                        # 옵션 내용 확인
                        options = await element.query_selector_all("option")
                        if options and len(options) > 1:
                            first_option = await options[1].inner_text()
                            print(f"  첫 옵션: {first_option}")

                if found_elements:
                    print(
                        f"\n성공! {len(found_elements)}개 요소 발견: {', '.join(found_elements)}"
                    )
                    print("이 페이지가 맞습니다!")

                    # 페이지 스크린샷
                    await page.screenshot(path="correct_page.png", full_page=True)
                    print("스크린샷 저장: correct_page.png")

                    # 시세 계산 테스트
                    print("\n시세 계산 테스트:")

                    # 제조사 선택
                    manufacturer_select = await page.query_selector("#op_dep1")
                    if manufacturer_select:
                        await manufacturer_select.select_option(index=1)
                        await page.wait_for_timeout(2000)

                        # 모델 선택
                        model_select = await page.query_selector("#op_dep2")
                        if model_select:
                            model_options = await model_select.query_selector_all(
                                "option"
                            )
                            if len(model_options) > 1:
                                await model_select.select_option(index=1)
                                await page.wait_for_timeout(2000)

                                print("옵션 선택 완료!")

                                # 가격 영역 확인
                                price_elements = await page.query_selector_all(
                                    '[class*="price"], [id*="price"]'
                                )
                                for elem in price_elements:
                                    text = await elem.inner_text()
                                    if "만원" in text or "시세" in text:
                                        print(f"가격 정보: {text}")

                    print("\n30초 후 종료. 페이지를 확인하세요...")
                    await page.wait_for_timeout(30000)
                    return

            except Exception as e:
                print(f"  오류: {e}")
                continue

        print("\n요소를 찾을 수 없습니다. 페이지 구조가 변경되었을 수 있습니다.")

    except Exception as e:
        print(f"전체 오류: {e}")
        import traceback

        traceback.print_exc()

    finally:
        await browser.close()
        await playwright.stop()


if __name__ == "__main__":
    asyncio.run(find_exact_elements())
