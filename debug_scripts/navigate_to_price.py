"""
메인 페이지에서 시세 페이지로 네비게이션
"""

import asyncio

from playwright.async_api import async_playwright


async def navigate_to_price():
    """메인 페이지에서 시세 페이지로 이동"""
    playwright = await async_playwright().start()
    browser = await playwright.firefox.launch(headless=False)

    try:
        page = await browser.new_page()

        # 1. 메인 페이지 접속
        print("엔카 메인 페이지 접속 중...")
        await page.goto("https://www.encar.com", wait_until="networkidle")
        await page.wait_for_timeout(3000)

        print(f"현재 URL: {page.url}")
        print(f"페이지 타이틀: {await page.title()}\n")

        # 2. 시세 링크 클릭
        print("시세 링크 찾는 중...")

        # 여러 시세 링크 시도
        price_link_clicked = False

        # GNB 메뉴에서 시세 찾기
        try:
            gnb_price = await page.query_selector('.gnb a:has-text("시세")')
            if gnb_price:
                print("GNB에서 시세 링크 발견!")
                await gnb_price.click()
                price_link_clicked = True
        except:
            pass

        if not price_link_clicked:
            # 일반 링크에서 시세 찾기
            try:
                price_link = await page.query_selector('a:has-text("시세"):first')
                if price_link:
                    print("시세 링크 발견!")
                    await price_link.click()
                    price_link_clicked = True
            except:
                pass

        if price_link_clicked:
            print("시세 페이지로 이동 중...")
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(5000)

            print(f"\n이동 후 URL: {page.url}")
            print(f"이동 후 타이틀: {await page.title()}\n")

            # 3. 시세 페이지 요소 분석
            print("시세 페이지 요소 분석:")

            # 탭 메뉴 확인
            tabs = await page.query_selector_all('.tab, [class*="tab"], ul.tab_menu li')
            print(f"탭 요소: {len(tabs)}개")

            # 탭 텍스트 확인
            for i, tab in enumerate(tabs[:10]):
                try:
                    tab_text = await tab.inner_text()
                    if tab_text.strip():
                        print(f"  탭 {i + 1}: {tab_text.strip()}")
                except:
                    pass

            # 시세조회 탭 클릭 시도
            print("\n시세조회 관련 탭 찾기...")

            # 여러 가능한 탭 텍스트
            tab_texts = ["시세조회", "조회", "시세", "가격조회", "중고차시세"]

            for text in tab_texts:
                try:
                    tab_element = await page.query_selector(f"text={text}")
                    if tab_element:
                        print(f"'{text}' 탭 발견! 클릭 시도...")
                        await tab_element.click()
                        await page.wait_for_timeout(3000)
                        break
                except:
                    pass

            # Select 요소 확인
            print("\nSelect 요소 검색...")

            selects = await page.query_selector_all("select")
            print(f"Select 요소: {len(selects)}개 발견!")

            for i, select in enumerate(selects[:10]):
                select_id = await select.get_attribute("id")
                select_name = await select.get_attribute("name")
                options = await select.query_selector_all("option")
                print(
                    f"  {i + 1}. id='{select_id}', name='{select_name}', options={len(options)}개"
                )

                # 옵션 내용 확인
                if len(options) > 0:
                    first_option = await options[0].inner_text()
                    print(f"      첫 옵션: '{first_option}'")

            # 4. 가격 조회 영역 확인
            print("\n가격 조회 영역:")
            price_areas = await page.query_selector_all(
                '[class*="price"], [id*="price"]'
            )
            print(f"가격 관련 요소: {len(price_areas)}개")

            # 5. 페이지 스크린샷
            await page.screenshot(path="price_page_final.png", full_page=True)
            print("\n스크린샷 저장: price_page_final.png")

            # 6. 테스트 선택
            print("\n테스트 선택 시도:")
            if len(selects) > 0:
                # 첫 번째 select에서 옵션 선택
                first_select = selects[0]
                first_select_id = await first_select.get_attribute("id")

                # 옵션 선택
                await first_select.select_option(index=1)
                print(f"첫 번째 셀렉트박스({first_select_id})에서 옵션 선택 완료")

                await page.wait_for_timeout(2000)

                # 두 번째 select 확인
                selects_after = await page.query_selector_all("select")
                if len(selects_after) > 1:
                    second_select = selects_after[1]
                    second_options = await second_select.query_selector_all("option")
                    print(f"두 번째 셀렉트박스 옵션: {len(second_options)}개")

        else:
            print("시세 링크를 찾을 수 없습니다!")

        print("\n30초 후 종료됩니다. 페이지를 확인하세요...")
        await page.wait_for_timeout(30000)

    except Exception as e:
        print(f"오류: {e}")
        import traceback

        traceback.print_exc()

    finally:
        await browser.close()
        await playwright.stop()


if __name__ == "__main__":
    asyncio.run(navigate_to_price())
