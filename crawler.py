"""
엔카 시세 크롤러 - Playwright 기반
"""
import asyncio
import hashlib
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from playwright.async_api import Page, async_playwright
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

import config
from database import CarPrice, CrawlingLog, get_session

console = Console()


class EncarCrawler:
    def __init__(self, headless: bool = config.HEADLESS):
        self.headless = headless
        self.page: Optional[Page] = None
        self.dom = None  # 현재 DOM 컨텍스트(page 또는 frame)를 가리킨다
        self.browser = None
        self.context = None
        self.playwright = None
        self.session = get_session()
        self.crawling_log = None

    async def initialize(self):
        """브라우저 초기화"""
        self.playwright = await async_playwright().start()

        # 기존 브라우저 선택은 유지하되, 탐지 우회를 위한 컨텍스트 옵션을 강화한다.
        self.browser = await self.playwright.firefox.launch(headless=self.headless)

        # 실제 사용 환경과 최대한 유사하게 맞춘다.
        self.context = await self.browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="ko-KR",
            timezone_id="Asia/Seoul",
        )
        await self.context.set_extra_http_headers(
            {"Accept-Language": "ko-KR,ko;q=0.9", "Upgrade-Insecure-Requests": "1"}
        )

        # 기본적인 자동화 탐지 우회 스크립트
        await self.context.add_init_script(
            """
            // webdriver 플래그 제거
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            // languages 지정
            Object.defineProperty(navigator, 'languages', { get: () => ['ko-KR', 'ko'] });
            // platform 지정
            Object.defineProperty(navigator, 'platform', { get: () => 'MacIntel' });
            // Chrome 객체 존재 보장
            window.chrome = window.chrome || {};
        """
        )

        self.page = await self.context.new_page()
        self.dom = self.page

        # 네트워크/리다이렉트 로깅
        self.page.on(
            "response", lambda resp: asyncio.create_task(self._log_response(resp))
        )
        self.page.on("console", lambda msg: None)  # 필요 시 콘솔 로그 수집

        console.print("[cyan]브라우저/컨텍스트 초기화 완료[/cyan]")

    async def _close_price_guide_if_present(self):
        """시세 페이지 진입 시 노출되는 가이드 레이어가 있으면 '다시보지않기'를 클릭해 닫는다."""
        try:
            # 레이어가 렌더될 시간을 짧게 준다. (있을 때만 닫는다)
            layer_sel = ".layer_container.ui_start"
            close_sel = ".ui_close_cookie, .ui_close_guide"
            # 레이어가 있으면 닫기
            layer = await self.dom.query_selector(layer_sel)
            if not layer:
                try:
                    await self.dom.wait_for_selector(layer_sel, timeout=1500)
                    layer = await self.dom.query_selector(layer_sel)
                except Exception:
                    layer = None
            if layer:
                # '다시보지않기' 버튼 클릭
                try:
                    await self.dom.click(close_sel, timeout=2000)
                    await self.dom.wait_for_timeout(300)  # 애니메이션 종료 대기
                except Exception:
                    pass
        except Exception:
            pass

    async def dismiss_price_guide(self) -> None:
        """시세 진입 시 나타나는 가이드 레이어(.layer_container.ui_start)를 닫는다."""
        try:
            layer_sel = ".layer_container.ui_start"
            # 레이어가 잠깐 늦게 뜨는 케이스 대비
            layer = await self.dom.query_selector(layer_sel)
            if not layer:
                try:
                    await self.dom.wait_for_selector(layer_sel, timeout=1500)
                    layer = await self.dom.query_selector(layer_sel)
                except Exception:
                    layer = None
            if not layer:
                return

            # '다시보지않기'와 보조 닫기 둘 다 시도
            for sel in ("a.ui_close_cookie", "a.ui_close_guide"):
                try:
                    btn = await self.dom.query_selector(sel)
                    if btn:
                        await btn.click()
                        await self.dom.wait_for_timeout(100)
                except Exception:
                    pass

            try:
                await self.dom.wait_for_selector(
                    layer_sel, state="detached", timeout=2000
                )
            except Exception:
                pass
        except Exception:
            pass

    async def _switch_to_price_frame_if_exists(self):
        """시세 영역이 iframe 으로 렌더링되면 해당 프레임으로 컨텍스트를 전환한다."""
        try:
            # 프레임 중에서 시세 페이지 형태를 가진 프레임을 찾는다.
            for fr in self.page.frames:
                try:
                    url = fr.url or ""
                    if "/pr/pr_index.do" in url or "/pr/" in url:
                        el = await fr.query_selector(
                            'li.op_dep1 .select.ui_select, form[name="prForm"] .list_select'
                        )
                        if el:
                            self.dom = fr
                            console.print("[cyan]iframe 컨텍스트로 전환됨[/cyan]")
                            return True
                except Exception:
                    continue
        except Exception:
            pass
        # 못 찾으면 기본 page 를 사용한다.
        self.dom = self.page
        return False

    async def _log_response(self, resp):
        try:
            req = resp.request
            from_url = getattr(req, "redirected_from", None)
            redir = " (redirected)" if from_url else ""
            console.print(f"[dim]{resp.status} {resp.url}{redir}[/dim]")
        except Exception:
            pass

    async def wait_for_element_change(
        self,
        selector: str,
        attribute: str = "innerText",
        old_value: Optional[str] = None,
        timeout: int = 10000,
    ) -> bool:
        """요소의 텍스트/속성이 변경될 때까지 대기"""
        deadline = time.time() + timeout / 1000.0
        while time.time() < deadline:
            try:
                el = await self.dom.query_selector(selector)
                if el:
                    if attribute in ("innerText", "textContent"):
                        current = await el.inner_text()
                    else:
                        current = await el.get_attribute(attribute)
                    if current != old_value:
                        return True
            except Exception:
                pass
            await asyncio.sleep(0.1)
        return False

    async def _find_ui_dep(self, dep_class: str):
        """li.op_dep* 영역에서 메뉴/컨테이너/히든인풋을 찾는다."""
        li = await self.dom.query_selector(f"li.{dep_class}")
        if not li:
            # fuel 은 op_dep* 가 아닐 수 있으니 li 내 data-name="fuel" 로도 탐색
            if dep_class in ("fuel", "op_fuel"):
                li = await self.dom.query_selector(
                    'li .select.ui_select[data-name="fuel"]'
                )
                if li:
                    # 실제 구조는 select.ui_select 가 div 이므로 상위 li 를 찾아준다
                    li = await li.evaluate_handle('el => el.closest("li")')
        if not li:
            return None, None, None, None
        menu = await li.query_selector("a.select_menu.ui_menu")
        container = await li.query_selector(".select_container.ui_container")
        hidden = await li.query_selector("input.ui_inpt")
        return li, menu, container, hidden

    async def _open_ui_menu(self, dep_class: str):
        """해당 li.op_dep* 의 드롭다운을 연다."""
        li, menu, container, hidden = await self._find_ui_dep(dep_class)
        if not menu:
            return False, (None, None, None, None)
        try:
            await menu.click()
        except Exception:
            # 메뉴가 이미 열려 있거나 가려진 경우 스크롤 후 재시도
            try:
                await menu.scroll_into_view_if_needed()
                await self.dom.wait_for_timeout(100)
                await menu.click()
            except Exception:
                pass
        await self.dom.wait_for_timeout(120)
        return True, (li, menu, container, hidden)

    async def _ui_list_options(self, dep_class: str):
        """li.op_dep* 의 ul.list_option 안의 옵션들을 파싱한다."""
        ok, ctx = await self._open_ui_menu(dep_class)
        if not ok:
            return []
        li, menu, container, hidden = ctx
        # data-init="true" 는 안내 텍스트이므로 제외
        anchors = await li.query_selector_all(
            'ul.list_option a.select_opt.ui_opt:not([data-init="true"])'
        )
        results = []
        for a in anchors:
            code = await a.get_attribute("data-code")
            val = await a.get_attribute("data-value")
            # 좌측 표시 텍스트(.lt) 기준으로 항목명을 받는다
            try:
                txt_el = await a.query_selector(".lt, .ui_opt_txt")
                text = (await txt_el.inner_text()) if txt_el else (await a.inner_text())
            except Exception:
                text = await a.inner_text()
            results.append(
                {"code": code or "", "value": val or "", "text": (text or "").strip()}
            )
        return results

    async def _ui_select_by(self, dep_class: str, code_or_text: str) -> bool:
        """li.op_dep* 에서 code(정확일치) 또는 텍스트(부분일치)로 항목 선택"""
        ok, ctx = await self._open_ui_menu(dep_class)
        if not ok:
            return False
        li, menu, container, hidden = ctx
        if not li or not menu:
            return False

        try:
            old_label = await menu.inner_text()
        except Exception:
            old_label = ""

        target = None
        if code_or_text:
            target = await li.query_selector(
                f'a.select_opt.ui_opt[data-code="{code_or_text}"]'
            ) or await li.query_selector(
                f'a.select_opt.ui_opt[data-value="{code_or_text}"]'
            )

        if not target and code_or_text:
            for o in await li.query_selector_all("a.select_opt.ui_opt"):
                try:
                    txt_el = await o.query_selector(".lt, .ui_opt_txt")
                    txt = await (txt_el.inner_text() if txt_el else o.inner_text())
                except Exception:
                    txt = await o.inner_text()
                if code_or_text in (txt or ""):
                    target = o
                    break

        if not target:
            return False

        try:
            await target.click()
        except Exception:
            try:
                await target.evaluate("(el)=>el.click()")
            except Exception:
                return False

        try:
            await self.wait_for_element_change(
                selector="a.select_menu.ui_menu .ui_menu_txt",
                attribute="innerText",
                old_value=old_label,
                timeout=5000,
            )
        except Exception:
            pass

        await self.dom.wait_for_timeout(150)
        return True

    async def navigate_to_price_page(self):
        """엔카 시세 페이지로 이동 (세션 프라임 → '시세' 메뉴 클릭 → 가이드 레이어 닫기 → 검증)"""
        console.print("[cyan]엔카 시세 페이지로 이동 중...[/cyan]")

        # 1) 세션 프라임: 인덱스 페이지를 먼저 열어 쿠키 확보
        idx_url = "https://www.encar.com/index.do"
        await self.page.goto(idx_url, wait_until="domcontentloaded", timeout=60000)
        await self.dom.wait_for_timeout(1000)

        # 2) '시세' 메뉴를 클릭하여 내부 네비게이션으로 진입
        price_url = config.ENCAR_URL  # /pr/pr_index.do
        selectors = [
            "ul.gnb.right a[href='/pr/pr_index.do']",
            "a[href*='/pr/pr_index.do']",
            "a:has-text('시세')",
            "a:has-text('내차시세')",
            "a:has-text('가격')",
        ]
        clicked = False
        for sel in selectors:
            try:
                await self.dom.wait_for_selector(sel, timeout=2500)
                await self.dom.click(sel)
                clicked = True
                break
            except Exception:
                continue

        if not clicked:
            # 폴백: referer 를 index.do 로 주고 직접 이동
            await self.page.goto(
                price_url, wait_until="domcontentloaded", referer=idx_url, timeout=60000
            )

        # 프레임 전환 시도
        await self._switch_to_price_frame_if_exists()

        await self.dom.wait_for_timeout(800)

        # 최종 URL/타이틀 확인
        current_url = self.page.url
        title = await self.page.title()
        console.print(f"[yellow]현재 URL: {current_url}[/yellow]")
        console.print(f"[yellow]페이지 타이틀: {title}[/yellow]")

        # 진입 시 가이드 레이어가 있으면 닫는다
        await self.dismiss_price_guide()

        # 4) 가격 페이지 핵심 셀렉터 검증
        try:
            await self.dom.wait_for_selector(
                "li.op_dep1 .select.ui_select", timeout=5000
            )
        except Exception:
            await self.page.screenshot(path="debug_page.png", full_page=True)
            raise RuntimeError("가격 페이지 접근 실패: li.op_dep1 을 찾지 못함 (가드/리다이렉트 가능성)")

        # 추가 셀렉터(존재 시) 로그: op_dep1~6 및 연료
        ids = [
            "op_dep1",
            "op_dep2",
            "op_dep3",
            "op_dep4",
            "op_dep5",
            "op_dep6",
            "op_fuel",
            "fuel",
        ]
        for sid in ids:
            try:
                el = await self.dom.query_selector(f"li.{sid}")
                if not el and sid in ("fuel", "op_fuel"):
                    el = await self.dom.query_selector(
                        'li .select.ui_select[data-name="fuel"]'
                    )
                if el:
                    console.print(f"[green]존재: {sid}[/green]")
                else:
                    console.print(f"[yellow]없음: {sid}[/yellow]")
            except Exception as _:
                pass

        # 디버깅용 스크린샷
        await self.page.screenshot(path="debug_page.png", full_page=True)
        console.print("[green]스크린샷 저장: debug_page.png[/green]")

    async def wait_for_element_change(
        self,
        selector: str,
        attribute: str = "innerText",
        old_value: str = None,
        timeout: int = 10000,
    ) -> bool:
        """요소의 속성이 변경될 때까지 대기"""
        start_time = time.time()

        while (time.time() - start_time) * 1000 < timeout:
            try:
                element = await self.dom.query_selector(selector)
                if element:
                    current_value = await element.get_attribute(attribute)
                    if current_value != old_value:
                        return True
            except:
                pass
            await asyncio.sleep(0.1)

        return False

    async def get_select_options(self, select_id: str) -> List[Dict[str, str]]:
        """옵션 리스트를 가져온다.

        - 신 UI(op_dep1~6, fuel): li.op_dep* 내부의 a.select_opt.ui_opt 들을 파싱
        - 구형 select 요소(id 기반): fallback
        """
        # 1) 신 UI
        if select_id.startswith("op_dep") or select_id in ("fuel", "op_fuel"):
            try:
                return await self._ui_list_options(
                    select_id if select_id != "op_fuel" else "fuel"
                )
            except Exception as e:
                console.print(f"[red]신 UI 옵션 파싱 실패 ({select_id}): {e}[/red]")
                return []

        # 2) 구형 select fallback
        try:
            await self.page.wait_for_function(
                f"""() => {{
                    const select = document.getElementById('{select_id}');
                    return select && select.options && select.options.length > 1;
                }}""",
                timeout=5000,
            )
            options = await self.dom.evaluate(
                f"""
                () => {{
                    const select = document.getElementById('{select_id}');
                    if (!select) return [];
                    return Array.from(select.options)
                        .filter(o => o.value && !o.disabled)
                        .map(o => ({{ value: o.value, text: o.textContent.trim() }}));
                }}
            """
            )
            return options
        except Exception as e:
            console.print(f"[red]옵션 가져오기 실패 ({select_id}): {e}[/red]")
            return []

    async def select_option_with_retry(
        self, select_id: str, value: str, text: str
    ) -> bool:
        """옵션 선택 (재시도 로직 포함)

        - 신 UI(op_dep1~6, fuel): _ui_select_by 로 클릭 처리
        - 구형 select 요소: 기존 JS 값 설정
        """
        # 신 UI 경로
        if select_id.startswith("op_dep") or select_id in ("fuel", "op_fuel"):
            try:
                code_or_text = value or text  # data-code가 있으면 그 값을, 없으면 표시 텍스트로
                return await self._ui_select_by(
                    select_id if select_id != "op_fuel" else "fuel", code_or_text
                )
            except Exception as e:
                console.print(f"[red]신 UI 선택 실패 ({select_id}/{text}): {e}[/red]")
                return False

        # 구형 select 요소 경로 (fallback)
        max_retries = 3
        for attempt in range(max_retries):
            try:
                await self.dom.wait_for_selector(
                    f"#{select_id}:not([disabled])", timeout=5000
                )
                success = await self.dom.evaluate(
                    f"""
                    () => {{
                        const select = document.getElementById('{select_id}');
                        if (!select) return false;
                        const match = Array.from(select.options).find(o => o.value === '{value}' || o.textContent.trim() === '{text}');
                        if (!match) return false;
                        select.value = match.value;
                        const ev = new Event('change', {{ bubbles: true }});
                        select.dispatchEvent(ev);
                        return true;
                    }}
                """
                )
                if success:
                    await self.page.wait_for_timeout(200)
                    return True
                console.print(
                    f"[yellow]옵션 미선택, 재시도 {attempt+1}/{max_retries}: {select_id} - {text}({value})[/yellow]"
                )
                await self.page.wait_for_timeout(300)
            except Exception as e:
                console.print(
                    f"[yellow]옵션 선택 재시도 {attempt+1}/{max_retries}: {select_id} - {text}({value}) => {e}[/yellow]"
                )
                await self.page.wait_for_timeout(300)
        return False

    async def get_fuel_options(self) -> List[Dict[str, str]]:
        """연료 옵션 가져오기 (신 UI 지원)"""
        try:
            # 신 UI: li[data-name="fuel"] 내부 옵션
            return await self._ui_list_options("fuel")
        except Exception as e:
            console.print(f"[yellow]연료 옵션(UI) 파싱 실패, 구형 방식 시도: {e}[/yellow]")
        # 구형 대비 fallback
        try:
            fuel_options = await self.dom.evaluate(
                """
                () => {
                    const fuelRadios = document.querySelectorAll('input[type="radio"][name*="fuel"], input[type="radio"][id*="fuel"]');
                    if (fuelRadios.length === 0) {
                        const fuelSelect = document.querySelector('select[id*="fuel"], select[name*="fuel"]');
                        if (fuelSelect) {
                            return Array.from(fuelSelect.options)
                                .filter(opt => opt.value && !opt.disabled)
                                .map(opt => ({ value: opt.value, text: opt.textContent.trim() }));
                        }
                        return [];
                    }
                    return Array.from(fuelRadios).map(r => ({ value: r.value, text: r.nextElementSibling ? r.nextElementSibling.textContent.trim() : r.value }));
                }
            """
            )
            return fuel_options or []
        except Exception as e2:
            console.print(f"[red]연료 옵션 파싱 실패: {e2}[/red]")
            return []

    async def select_fuel_option(self, value: str) -> bool:
        """연료 옵션 선택 (신 UI 지원)"""
        try:
            return await self._ui_select_by("fuel", value)
        except Exception:
            # 구형 fallback
            try:
                return await self.dom.evaluate(
                    f"""
                    () => {{
                        const fuelRadios = document.querySelectorAll('input[type="radio"][name*="fuel"], input[type="radio"][id*="fuel"]');
                        for (const r of fuelRadios) {{
                            if (r.value === '{value}') {{ r.click(); return true; }}
                        }}
                        const fuelSelect = document.querySelector('select[id*="fuel"], select[name*="fuel"]');
                        if (fuelSelect) {{
                            fuelSelect.value = '{value}';
                            fuelSelect.dispatchEvent(new Event('change', {{ bubbles: true }}));
                            return true;
                        }}
                        return false;
                    }}
                """
                )
            except Exception as e:
                console.print(f"[red]연료 선택 실패: {e}[/red]")
                return False

    async def get_price_info(self) -> Tuple[Optional[float], bool, str]:
        """현재 선택된 옵션의 가격 정보 가져오기"""
        try:
            # 가격 정보가 업데이트될 때까지 대기
            await self.dom.wait_for_timeout(2000)

            # 여러 가능한 선택자로 가격 찾기
            price_info = await self.dom.evaluate(
                """
                () => {
                    // 가격 표시 영역 찾기
                    const priceSelectors = [
                        '.price_result',
                        '.result_price',
                        '[class*="price"]',
                        '[id*="price"]'
                    ];

                    for (const selector of priceSelectors) {
                        const elements = document.querySelectorAll(selector);
                        for (const elem of elements) {
                            const text = elem.textContent.trim();

                            // 시세 미제공 체크
                            if (text.includes('시세 미제공') || text.includes('거래량이 적어')) {
                                return {
                                    price: null,
                                    available: false,
                                    message: text
                                };
                            }

                            // 가격 추출 (숫자와 '만원' 패턴)
                            const priceMatch = text.match(/([0-9,]+)\s*만원/);
                            if (priceMatch) {
                                const price = parseFloat(priceMatch[1].replace(/,/g, ''));
                                return {
                                    price: price,
                                    available: true,
                                    message: text
                                };
                            }
                        }
                    }

                    return {
                        price: null,
                        available: false,
                        message: '가격 정보를 찾을 수 없습니다'
                    };
                }
            """
            )

            return (
                price_info.get("price"),
                price_info.get("available", False),
                price_info.get("message", ""),
            )

        except Exception as e:
            console.print(f"[red]가격 정보 가져오기 실패: {e}[/red]")
            return None, False, str(e)

    async def crawl_all_combinations(self):
        """모든 옵션 조합 크롤링"""
        start_time = datetime.now()
        total_combinations = 0
        success_count = 0
        failed_count = 0

        # 크롤링 로그 시작
        self.crawling_log = CrawlingLog(started_at=start_time, status="RUNNING")
        self.session.add(self.crawling_log)
        self.session.commit()

        try:
            await self.navigate_to_price_page()

            # 1. 제조사 목록 가져오기
            manufacturers = await self.get_select_options("op_dep1")
            console.print(f"[green]제조사 {len(manufacturers)}개 발견[/green]")

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                for manufacturer in manufacturers:
                    task = progress.add_task(
                        f"[cyan]{manufacturer['text']} 크롤링 중...[/cyan]", total=None
                    )

                    # 제조사 선택
                    if not await self.select_option_with_retry(
                        "op_dep1", manufacturer["value"], manufacturer["text"]
                    ):
                        continue

                    # 2. 모델 목록 가져오기
                    models = await self.get_select_options("op_dep2")

                    for model in models:
                        if not await self.select_option_with_retry(
                            "op_dep2", model["value"], model["text"]
                        ):
                            continue

                        # 3. 세부모델 목록 가져오기
                        detailed_models = await self.get_select_options("op_dep3")

                        for detailed_model in detailed_models:
                            if not await self.select_option_with_retry(
                                "op_dep3",
                                detailed_model["value"],
                                detailed_model["text"],
                            ):
                                continue

                            # 4. 연식 목록 가져오기
                            years = await self.get_select_options("op_dep4")

                            for year in years:
                                if not await self.select_option_with_retry(
                                    "op_dep4", year["value"], year["text"]
                                ):
                                    continue

                                # 5. 연료 옵션 처리
                                fuel_options = await self.get_fuel_options()

                                for fuel in fuel_options:
                                    if (
                                        fuel_options
                                        and not await self.select_fuel_option(
                                            fuel["value"]
                                        )
                                    ):
                                        continue

                                    # 6. 등급 목록 가져오기
                                    grades = await self.get_select_options("op_dep5")

                                    for grade in grades:
                                        if not await self.select_option_with_retry(
                                            "op_dep5", grade["value"], grade["text"]
                                        ):
                                            continue

                                        # 7. 세부등급 목록 가져오기
                                        detailed_grades = await self.get_select_options(
                                            "op_dep6"
                                        )

                                        for detailed_grade in detailed_grades:
                                            total_combinations += 1

                                            if not await self.select_option_with_retry(
                                                "op_dep6",
                                                detailed_grade["value"],
                                                detailed_grade["text"],
                                            ):
                                                failed_count += 1
                                                continue

                                            # 가격 정보 가져오기
                                            (
                                                price,
                                                is_available,
                                                message,
                                            ) = await self.get_price_info()

                                            # 옵션 조합 해시 생성
                                            option_string = f"{manufacturer['value']}_{model['value']}_{detailed_model['value']}_{year['value']}_{fuel.get('value', '')}_{grade['value']}_{detailed_grade['value']}"
                                            options_hash = hashlib.md5(
                                                option_string.encode()
                                            ).hexdigest()

                                            # 데이터베이스 저장
                                            try:
                                                car_price = CarPrice(
                                                    manufacturer=manufacturer["text"],
                                                    model=model["text"],
                                                    detailed_model=detailed_model[
                                                        "text"
                                                    ],
                                                    year=year["text"],
                                                    fuel_type=fuel.get("text", ""),
                                                    grade=grade["text"],
                                                    detailed_grade=detailed_grade[
                                                        "text"
                                                    ],
                                                    price=price,
                                                    is_price_available=is_available,
                                                    price_message=message,
                                                    options_hash=options_hash,
                                                    manufacturer_code=manufacturer[
                                                        "value"
                                                    ],
                                                    model_code=model["value"],
                                                    detailed_model_code=detailed_model[
                                                        "value"
                                                    ],
                                                    year_code=year["value"],
                                                    fuel_code=fuel.get("value", ""),
                                                    grade_code=grade["value"],
                                                    detailed_grade_code=detailed_grade[
                                                        "value"
                                                    ],
                                                )

                                                self.session.add(car_price)
                                                self.session.commit()
                                                success_count += 1

                                                status_text = f"✓ {manufacturer['text']} {model['text']} {year['text']}"
                                                if price:
                                                    console.print(
                                                        f"[green]{status_text} - {price:,.0f}만원[/green]"
                                                    )
                                                else:
                                                    console.print(
                                                        f"[yellow]{status_text} - 시세 미제공[/yellow]"
                                                    )

                                            except Exception as e:
                                                failed_count += 1
                                                console.print(
                                                    f"[red]DB 저장 실패: {e}[/red]"
                                                )
                                                self.session.rollback()

                    progress.remove_task(task)

        except Exception as e:
            console.print(f"[red]크롤링 중 오류 발생: {e}[/red]")

        finally:
            # 크롤링 로그 업데이트
            self.crawling_log.ended_at = datetime.now()
            self.crawling_log.total_combinations = total_combinations
            self.crawling_log.success_count = success_count
            self.crawling_log.failed_count = failed_count
            self.crawling_log.status = "SUCCESS" if failed_count == 0 else "PARTIAL"
            self.session.commit()

            console.print(f"\n[bold cyan]크롤링 완료![/bold cyan]")
            console.print(f"총 조합: {total_combinations}")
            console.print(f"성공: {success_count}")
            console.print(f"실패: {failed_count}")
            console.print(f"소요 시간: {datetime.now() - start_time}")

    async def test_single_combination(self):
        """단일 조합 테스트 (디버깅용)"""
        try:
            await self.navigate_to_price_page()

            # 페이지 구조 분석
            console.print("[cyan]페이지 구조 분석 중...[/cyan]")

            # 모든 select 요소 찾기
            selects = await self.dom.evaluate(
                """
                () => {
                    const selects = document.querySelectorAll('select');
                    return Array.from(selects).map(s => ({
                        id: s.id,
                        name: s.name,
                        className: s.className,
                        optionCount: s.options.length
                    }));
                }
            """
            )

            console.print("[yellow]발견된 Select 요소들:[/yellow]")
            for select in selects:
                console.print(
                    f"  - ID: {select.get('id')}, Name: {select.get('name')}, Options: {select.get('optionCount')}"
                )

            # 제조사 관련 요소 찾기
            manufacturer_selectors = [
                'select[id*="manufacturer"]',
                'select[id*="maker"]',
                'select[id*="brand"]',
                "li.op_dep1 .select.ui_select",
                'select[name*="manufacturer"]',
                'select[name*="maker"]',
                ".wrp_price select:first-child",
            ]

            manufacturer_element = None
            for selector in manufacturer_selectors:
                try:
                    element = await self.dom.query_selector(selector)
                    if element:
                        console.print(f"[green]제조사 셀렉터 발견: {selector}[/green]")
                        manufacturer_element = selector
                        break
                except:
                    pass

            if not manufacturer_element:
                console.print("[red]제조사 셀렉터를 찾을 수 없습니다.[/red]")

                # HTML 구조 출력 (디버깅용)
                html_snippet = await self.dom.evaluate(
                    """
                    () => {
                        const priceWrapper = document.querySelector('.wrp_price');
                        if (priceWrapper) {
                            return priceWrapper.innerHTML.substring(0, 500);
                        }
                        return document.body.innerHTML.substring(0, 500);
                    }
                """
                )
                console.print(f"[dim]HTML 일부: {html_snippet}[/dim]")
                return

            # 제조사 옵션 가져오기
            options = await self.dom.evaluate(
                f"""
                () => {{
                    const select = document.querySelector('{manufacturer_element}');
                    if (!select) return [];
                    return Array.from(select.options).map(opt => ({{
                        value: opt.value,
                        text: opt.text
                    }}));
                }}
            """
            )

            console.print(f"[green]제조사 옵션 {len(options)}개 발견[/green]")
            for opt in options[:5]:  # 처음 5개만 표시
                console.print(f"  - {opt['text']} ({opt['value']})")

        except Exception as e:
            console.print(f"[red]테스트 실패: {e}[/red]")
            import traceback

            console.print(f"[red]{traceback.format_exc()}[/red]")

    async def close(self):
        """브라우저/세션 자원 정리"""
        try:
            if self.session:
                self.session.close()
        except Exception:
            pass
        try:
            if self.context:
                await self.context.close()
        except Exception:
            pass
        try:
            if self.browser:
                await self.browser.close()
        except Exception:
            pass
        try:
            if self.playwright:
                await self.playwright.stop()
        except Exception:
            pass

    async def main():
        """메인 실행 함수"""
        crawler = EncarCrawler(headless=False)  # 디버깅을 위해 headless=False

        try:
            await crawler.initialize()

            # 테스트 모드로 먼저 실행
            # await crawler.test_single_combination()

            # 전체 크롤링 실행
            await crawler.crawl_all_combinations()

        finally:
            await crawler.close()

    if __name__ == "__main__":
        asyncio.run(main())
