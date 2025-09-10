"""
엔카 시세 페이지 상세 분석
"""
import asyncio
import json

from playwright.async_api import async_playwright


async def analyze_price_page():
    """시세 페이지 상세 분석"""
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

        # 페이지 완전 로드 대기
        print("페이지 로드 대기 중...")
        await page.wait_for_timeout(5000)

        print(f"현재 URL: {page.url}")
        print(f"페이지 타이틀: {await page.title()}\n")

        # 1. iframe 확인
        iframes = await page.query_selector_all("iframe")
        print(f"iframe 개수: {len(iframes)}")

        if iframes:
            for i, iframe in enumerate(iframes):
                src = await iframe.get_attribute("src")
                name = await iframe.get_attribute("name")
                print(f"  iframe {i+1}: name='{name}', src='{src}'")

        # 2. 모든 select 요소 찾기
        print("\nSelect 요소 검색:")

        # 메인 페이지의 select
        selects = await page.query_selector_all("select")
        print(f"메인 페이지 Select 개수: {len(selects)}")

        for i, select in enumerate(selects[:10]):
            select_id = await select.get_attribute("id")
            select_name = await select.get_attribute("name")
            select_class = await select.get_attribute("class")
            options_count = len(await select.query_selector_all("option"))
            print(
                f"  {i+1}. id='{select_id}', name='{select_name}', class='{select_class}', options={options_count}"
            )

        # 3. 동적 로딩 요소 확인
        print("\n동적 요소 검색:")

        # Ajax/동적 컨텐츠 영역 찾기
        dynamic_areas = await page.evaluate(
            """
            () => {
                const results = [];

                // Angular, React, Vue 등의 힌트 찾기
                if (window.angular) results.push('Angular 감지');
                if (window.React) results.push('React 감지');
                if (window.Vue) results.push('Vue 감지');

                // jQuery Ajax 설정 확인
                if (window.jQuery && window.jQuery.ajax) results.push('jQuery Ajax 사용');

                // 동적 렌더링 컨테이너 찾기
                const containers = document.querySelectorAll('[id*="container"], [class*="container"], [id*="content"], [class*="content"]');
                results.push(`컨테이너 요소: ${containers.length}개`);

                return results;
            }
        """
        )

        for item in dynamic_areas:
            print(f"  - {item}")

        # 4. 시세 관련 요소 찾기
        print("\n시세 관련 요소:")

        price_elements = await page.evaluate(
            """
            () => {
                const results = [];

                // 제조사 관련
                const makers = document.querySelectorAll('[id*="maker"], [name*="maker"], [id*="manufacturer"]');
                if (makers.length > 0) results.push(`제조사 요소: ${makers.length}개`);

                // 모델 관련
                const models = document.querySelectorAll('[id*="model"], [name*="model"]');
                if (models.length > 0) results.push(`모델 요소: ${models.length}개`);

                // 가격 표시 영역
                const prices = document.querySelectorAll('[class*="price"], [id*="price"]');
                if (prices.length > 0) results.push(`가격 요소: ${prices.length}개`);

                // 폼 요소
                const forms = document.querySelectorAll('form');
                if (forms.length > 0) {
                    results.push(`폼 요소: ${forms.length}개`);
                    forms.forEach((form, i) => {
                        results.push(`  폼 ${i+1}: action='${form.action}', method='${form.method}'`);
                    });
                }

                return results;
            }
        """
        )

        for item in price_elements:
            print(f"  {item}")

        # 5. 클릭 가능한 탭/메뉴 찾기
        print("\n클릭 가능한 탭/메뉴:")

        tabs = await page.query_selector_all(
            'a[href*="tab"], button[onclick], .tab, .menu'
        )
        print(f"탭/메뉴 요소: {len(tabs)}개")

        for i, tab in enumerate(tabs[:5]):
            text = await tab.inner_text()
            print(f"  {i+1}. {text.strip()[:30]}")

        # 6. 스크린샷 저장
        await page.screenshot(path="price_page_analysis.png", full_page=True)
        print("\n스크린샷 저장: price_page_analysis.png")

        # 7. HTML 샘플 저장
        html_content = await page.content()
        with open("price_page.html", "w", encoding="utf-8") as f:
            f.write(html_content[:10000])  # 처음 10000자만
        print("HTML 샘플 저장: price_page.html")

        print("\n분석 완료! 브라우저를 확인하세요...")
        print("20초 후 종료됩니다...")
        await page.wait_for_timeout(20000)

    except Exception as e:
        print(f"오류: {e}")
        import traceback

        traceback.print_exc()

    finally:
        await browser.close()
        await playwright.stop()


if __name__ == "__main__":
    asyncio.run(analyze_price_page())
