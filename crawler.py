"""
엔카 시세 크롤러 - Playwright 기반
요구사항에 맞게 수정된 버전
"""

import asyncio
import hashlib
import time
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

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

        # 크롤링 상태 관리
        self.visited_combinations: Set[str] = set()
        self.current_path: List[Dict] = []  # 현재 선택된 옵션 경로
        self.crawled_data: List[Dict] = []  # 크롤링된 데이터 임시 저장

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
            // platform 지정제가
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
        self.page.on("framenavigated", self._handle_navigation)

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

    async def _handle_navigation(self, frame):
        """페이지 이동 감지 및 방지"""
        if frame == self.page.main_frame:
            current_url = frame.url
            if not current_url.startswith("https://www.encar.com/pr/pr_index.do"):
                console.print(f"[red]예상치 못한 페이지 이동 감지: {current_url}[/red]")
                # 시세 페이지로 다시 이동
                try:
                    await self.page.goto(
                        "https://www.encar.com/pr/pr_index.do",
                        wait_until="domcontentloaded",
                        timeout=10000,
                    )
                    console.print("[green]시세 페이지로 복구 완료[/green]")
                except Exception as e:
                    console.print(f"[red]페이지 복구 실패: {e}[/red]")
                    raise

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
        """엔카 시세 페이지로 이동 및 팝업 처리"""
        console.print("[cyan]엔카 시세 페이지로 이동 중...[/cyan]")

        # 직접 시세 페이지로 이동 (지연 제거)
        await self.page.goto(
            "https://www.encar.com/pr/pr_index.do",
            wait_until="domcontentloaded",
            timeout=30000,
        )

        # 가이드 팝업 처리
        await self.dismiss_price_guide()

        # 페이지 로딩 대기 및 검증
        await self.dom.wait_for_selector("li.op_dep1", timeout=10000)
        console.print("[green]시세 페이지 로딩 완료[/green]")

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
                    f"[yellow]옵션 미선택, 재시도 {attempt + 1}/{max_retries}: {select_id} - {text}({value})[/yellow]"
                )
                await self.page.wait_for_timeout(300)
            except Exception as e:
                console.print(
                    f"[yellow]옵션 선택 재시도 {attempt + 1}/{max_retries}: {select_id} - {text}({value}) => {e}[/yellow]"
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
        """요구사항에 맞는 모든 옵션 조합 크롤링 - 1가지씩 선택하는 방식"""
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

            # 1단계: op_dep1 (제조사)부터 시작
            await self._crawl_from_level(1)

            # 크롤링된 데이터를 DB에 저장
            success_count, failed_count = await self._save_crawled_data()

        except Exception as e:
            console.print(f"[red]크롤링 중 오류 발생: {e}[/red]")
            import traceback

            console.print(f"[red]{traceback.format_exc()}[/red]")

        finally:
            # 크롤링 로그 업데이트
            self.crawling_log.ended_at = datetime.now()
            self.crawling_log.total_combinations = len(self.crawled_data)
            self.crawling_log.success_count = success_count
            self.crawling_log.failed_count = failed_count
            self.crawling_log.status = "SUCCESS" if failed_count == 0 else "PARTIAL"
            self.session.commit()

            console.print("\n[bold cyan]크롤링 완료![/bold cyan]")
            console.print(f"총 조합: {len(self.crawled_data)}")
            console.print(f"성공: {success_count}")
            console.print(f"실패: {failed_count}")
            console.print(f"소요 시간: {datetime.now() - start_time}")

    async def _crawl_from_level(self, start_level: int):
        """특정 레벨부터 크롤링 시작"""
        console.print(f"[cyan]레벨 {start_level}부터 크롤링 시작[/cyan]")

        # op_dep1부터 시작
        if start_level == 1:
            await self._crawl_manufacturers()

    async def _crawl_manufacturers(self):
        """제조사(op_dep1) 크롤링 - 모든 제조사 크롤링"""
        console.print("[cyan]제조사 크롤링 시작[/cyan]")

        # 제조사 옵션 가져오기
        manufacturers = await self._get_options("op_dep1")
        console.print(f"[green]제조사 {len(manufacturers)}개 발견[/green]")

        # 모든 제조사 크롤링
        for i, manufacturer in enumerate(manufacturers):
            if i == 0:  # 첫 번째는 "제조사" 플레이스홀더
                continue

            # 시세 미제공인 경우 건너뛰기
            if "시세 미제공" in manufacturer.get("price_text", ""):
                console.print(f"[yellow]건너뛰기: {manufacturer['text']} - 시세 미제공[/yellow]")
                continue

            console.print(f"[cyan]제조사 선택 시도: {manufacturer['text']}[/cyan]")
            # 제조사 선택
            if await self._select_option("op_dep1", manufacturer):
                self.current_path = [manufacturer]
                console.print(f"[green]제조사 선택 완료: {manufacturer['text']}[/green]")
                await self.dom.wait_for_timeout(2000)  # 2초 대기
                await self._crawl_models()
            else:
                console.print(f"[red]제조사 선택 실패: {manufacturer['text']}[/red]")
                continue  # 실패해도 다음 제조사로 계속

    async def _crawl_models(self):
        """모델(op_dep2) 크롤링 - 모든 모델 크롤링"""
        console.print("[cyan]모델 크롤링 시작[/cyan]")

        models = await self._get_options("op_dep2")
        console.print(f"[green]모델 {len(models)}개 발견[/green]")

        # 모든 모델 크롤링
        for model in models:
            if "시세 미제공" in model.get("price_text", ""):
                console.print(f"[yellow]건너뛰기: {model['text']} - 시세 미제공[/yellow]")
                continue

            if await self._select_option("op_dep2", model):
                self.current_path = self.current_path[:1] + [model]
                console.print(f"[green]모델 선택 완료: {model['text']}[/green]")
                await self.dom.wait_for_timeout(2000)  # 2초 대기
                await self._crawl_detailed_models()
            else:
                console.print(f"[red]모델 선택 실패: {model['text']}[/red]")
                continue  # 실패해도 다음 모델로 계속

    async def _crawl_detailed_models(self):
        """세부모델(op_dep3) 크롤링 - 모든 세부모델 크롤링"""
        console.print("[cyan]세부모델 크롤링 시작[/cyan]")

        detailed_models = await self._get_options("op_dep3")
        console.print(f"[green]세부모델 {len(detailed_models)}개 발견[/green]")

        # 모든 세부모델 크롤링
        for detailed_model in detailed_models:
            if "시세 미제공" in detailed_model.get("price_text", ""):
                console.print(
                    f"[yellow]건너뛰기: {detailed_model['text']} - 시세 미제공[/yellow]"
                )
                continue

            if await self._select_option("op_dep3", detailed_model):
                self.current_path = self.current_path[:2] + [detailed_model]
                console.print(f"[green]세부모델 선택 완료: {detailed_model['text']}[/green]")
                await self.dom.wait_for_timeout(2000)  # 2초 대기
                await self._crawl_years()
            else:
                console.print(f"[red]세부모델 선택 실패: {detailed_model['text']}[/red]")
                continue  # 실패해도 다음 세부모델로 계속

    async def _crawl_years(self):
        """연식(op_dep4) 크롤링 - 모든 연식 크롤링"""
        console.print("[cyan]연식 크롤링 시작[/cyan]")

        years = await self._get_options("op_dep4")
        console.print(f"[green]연식 {len(years)}개 발견[/green]")

        # 모든 연식 크롤링
        for year in years:
            if "시세 미제공" in year.get("price_text", ""):
                console.print(f"[yellow]건너뛰기: {year['text']} - 시세 미제공[/yellow]")
                continue

            if await self._select_option("op_dep4", year):
                self.current_path = self.current_path[:3] + [year]
                console.print(f"[green]연식 선택 완료: {year['text']}[/green]")
                await self.dom.wait_for_timeout(2000)  # 2초 대기
                await self._crawl_fuel_options()
            else:
                console.print(f"[red]연식 선택 실패: {year['text']}[/red]")
                continue  # 실패해도 다음 연식으로 계속

    async def _crawl_fuel_options(self):
        """연료 옵션 크롤링 - 모든 연료 크롤링"""
        console.print("[cyan]연료 옵션 크롤링 시작[/cyan]")

        fuel_options = await self._get_fuel_options()
        console.print(f"[green]연료 옵션 {len(fuel_options)}개 발견[/green]")

        # 모든 연료 크롤링
        for fuel in fuel_options:
            if await self._select_fuel_option(fuel):
                self.current_path = self.current_path[:4] + [fuel]
                console.print(f"[green]연료 선택 완료: {fuel['text']}[/green]")
                await self.dom.wait_for_timeout(2000)  # 2초 대기
                await self._crawl_grades()
            else:
                console.print(f"[red]연료 선택 실패: {fuel['text']}[/red]")
                continue  # 실패해도 다음 연료로 계속

    async def _crawl_grades(self):
        """등급(op_dep5) 크롤링 - 모든 등급 크롤링"""
        console.print("[cyan]등급 크롤링 시작[/cyan]")

        grades = await self._get_options("op_dep5")
        console.print(f"[green]등급 {len(grades)}개 발견[/green]")

        # 모든 등급 크롤링
        for grade in grades:
            if "시세 미제공" in grade.get("price_text", ""):
                console.print(f"[yellow]건너뛰기: {grade['text']} - 시세 미제공[/yellow]")
                continue

            if await self._select_option("op_dep5", grade):
                self.current_path = self.current_path[:5] + [grade]
                console.print(f"[green]등급 선택 완료: {grade['text']}[/green]")
                await self.dom.wait_for_timeout(2000)  # 2초 대기
                await self._crawl_detailed_grades()
            else:
                console.print(f"[red]등급 선택 실패: {grade['text']}[/red]")
                continue  # 실패해도 다음 등급으로 계속

    async def _crawl_detailed_grades(self):
        """세부등급(op_dep6) 크롤링 - 요구사항의 핵심"""
        console.print("[cyan]세부등급 크롤링 시작[/cyan]")

        detailed_grades = await self._get_options("op_dep6")
        console.print(f"[green]세부등급 {len(detailed_grades)}개 발견[/green]")

        # op_dep6의 모든 옵션을 크롤링하되 3개까지만 가져오기
        max_grades = min(3, len(detailed_grades))
        console.print(f"[yellow]세부등급 {max_grades}개만 크롤링 (요구사항에 따라)[/yellow]")

        for i, detailed_grade in enumerate(detailed_grades[:max_grades]):
            console.print(
                f"[cyan]세부등급 {i+1}/{max_grades} 선택: {detailed_grade['text']}[/cyan]"
            )

            # 세부등급 선택
            if await self._select_option("op_dep6", detailed_grade):
                # 현재까지의 경로 + 세부등급으로 최종 데이터 생성
                final_path = self.current_path + [detailed_grade]

                # 가격 정보 가져오기
                price, is_available, message = await self._get_price_info()

                # 데이터 저장
                car_data = self._create_car_data(
                    final_path, price, is_available, message
                )
                self.crawled_data.append(car_data)

                # 로그 출력
                status_text = f"✓ {' '.join([item['text'] for item in final_path])}"
                if price:
                    console.print(f"[green]{status_text} - {price:,.0f}만원[/green]")
                else:
                    console.print(f"[yellow]{status_text} - 시세 미제공[/yellow]")

                await self.dom.wait_for_timeout(2000)  # 2초 대기
            else:
                console.print(f"[red]세부등급 선택 실패: {detailed_grade['text']}[/red]")
                continue  # 실패해도 다음 세부등급으로 계속

        console.print(f"[green]세부등급 크롤링 완료: {max_grades}개 처리됨[/green]")

    async def _check_unvisited_options(self, level: int):
        """특정 레벨에서 방문하지 않은 옵션들 체크"""
        console.print(f"[cyan]레벨 {level}에서 방문하지 않은 옵션 체크[/cyan]")
        # 구현 예정

    async def _get_options(self, dep_class: str) -> List[Dict]:
        """op_dep* 옵션들을 가져오기"""
        try:
            # 드롭다운 열기
            await self._open_dropdown(dep_class)

            # 옵션들 파싱
            options = await self.dom.evaluate(
                f"""
                () => {{
                    const li = document.querySelector('li.{dep_class}');
                    if (!li) return [];

                    const anchors = li.querySelectorAll('ul.list_option a.select_opt.ui_opt:not([data-init="true"])');
                    return Array.from(anchors).map(a => {{
                        const code = a.getAttribute('data-code') || '';
                        const value = a.getAttribute('data-value') || '';
                        const textEl = a.querySelector('.lt, .ui_opt_txt');
                        const text = textEl ? textEl.textContent.trim() : a.textContent.trim();
                        const priceEl = a.querySelector('.rt');
                        const price_text = priceEl ? priceEl.textContent.trim() : '';

                        return {{
                            code: code,
                            value: value,
                            text: text,
                            price_text: price_text
                        }};
                    }});
                }}
            """
            )

            return options or []
        except Exception as e:
            console.print(f"[red]옵션 가져오기 실패 ({dep_class}): {e}[/red]")
            return []

    async def _get_fuel_options(self) -> List[Dict]:
        """연료 옵션들 가져오기"""
        try:
            # 연료 드롭다운 열기
            await self._open_dropdown("fuel")

            # 연료 옵션들 파싱
            options = await self.dom.evaluate(
                """
                () => {
                    const fuelLi = document.querySelector('li .select.ui_select[data-name="fuel"]');
                    if (!fuelLi) return [];

                    const li = fuelLi.closest('li');
                    if (!li) return [];

                    const anchors = li.querySelectorAll('ul.list_option a.select_opt.ui_opt:not([data-init="true"])');
                    return Array.from(anchors).map(a => {
                        const code = a.getAttribute('data-code') || '';
                        const value = a.getAttribute('data-value') || '';
                        const textEl = a.querySelector('.lt, .ui_opt_txt');
                        const text = textEl ? textEl.textContent.trim() : a.textContent.trim();
                        const priceEl = a.querySelector('.rt');
                        const price_text = priceEl ? priceEl.textContent.trim() : '';

                        return {
                            code: code,
                            value: value,
                            text: text,
                            price_text: price_text
                        };
                    });
                }
            """
            )

            return options or []
        except Exception as e:
            console.print(f"[red]연료 옵션 가져오기 실패: {e}[/red]")
            return []

    async def _open_dropdown(self, dep_class: str):
        """드롭다운 열기 - Playwright 액션 사용"""
        try:
            console.print(f"[blue]드롭다운 열기 시도: {dep_class}[/blue]")

            if dep_class == "fuel":
                # 연료 드롭다운 열기
                menu_selector = (
                    'li .select.ui_select[data-name="fuel"] a.select_menu.ui_menu'
                )
            else:
                # 일반 드롭다운 열기
                menu_selector = f"li.{dep_class} a.select_menu.ui_menu"

            # Playwright 액션으로 메뉴 클릭
            try:
                await self.dom.wait_for_selector(menu_selector, timeout=5000)
                await self.dom.click(menu_selector)
                await self.dom.wait_for_timeout(500)  # 옵션들이 로드될 때까지 대기
                console.print(f"[green]드롭다운 열기 완료: {dep_class}[/green]")
            except Exception as e:
                console.print(f"[red]Playwright 드롭다운 열기 실패: {e}[/red]")
                # 대안: JavaScript로 시도
                await self._open_dropdown_fallback(dep_class)

        except Exception as e:
            console.print(f"[red]드롭다운 열기 실패 ({dep_class}): {e}[/red]")
            await self._open_dropdown_fallback(dep_class)

    async def _open_dropdown_fallback(self, dep_class: str):
        """드롭다운 열기 - 대안 방식"""
        try:
            if dep_class == "fuel":
                # 연료는 오버레이 제거 후 클릭
                await self.dom.evaluate(
                    """
                    const overlays = document.querySelectorAll('.overlay.ui_overlay');
                    overlays.forEach(overlay => {
                        if (overlay.style) {
                            overlay.style.display = 'none';
                        }
                    });
                """
                )

                menu = await self.dom.wait_for_selector(
                    'li .select.ui_select[data-name="fuel"] a.select_menu.ui_menu',
                    timeout=5000,
                )
            else:
                menu = await self.dom.wait_for_selector(
                    f"li.{dep_class} a.select_menu.ui_menu", timeout=5000
                )

            if menu:
                await menu.click(force=True)
                await asyncio.sleep(0.5)
                console.print(f"[yellow]대안 방식으로 드롭다운 열기 완료: {dep_class}[/yellow]")
        except Exception as e:
            console.print(f"[red]대안 방식도 실패 ({dep_class}): {e}[/red]")
            try:
                if dep_class == "fuel":
                    # 연료 최종 시도: JavaScript로 직접 클릭
                    await self.dom.evaluate(
                        """
                        const fuelMenu = document.querySelector('li .select.ui_select[data-name="fuel"] a.select_menu.ui_menu');
                        if (fuelMenu) {
                            fuelMenu.click();
                        }
                    """
                    )
                    console.print(f"[yellow]연료 JavaScript 최종 시도 완료[/yellow]")
                else:
                    await self.dom.click(
                        f"li.{dep_class} a.select_menu.ui_menu", force=True
                    )
                # 드롭다운이 완전히 열릴 때까지 잠시 대기
                await asyncio.sleep(0.3)
            except Exception as e2:
                console.print(f"[red]대안 클릭도 실패 ({dep_class}): {e2}[/red]")
                raise Exception(f"드롭다운 열기 실패: {e2}")

    async def _close_dropdown(self, dep_class: str):
        """드롭다운 닫기 - 강제 닫기 버전"""
        try:
            # 페이지의 다른 영역을 클릭하여 드롭다운 강제 닫기
            await self.dom.click("body", position={"x": 100, "y": 100})

            # ESC 키로도 시도
            await self.dom.keyboard.press("Escape")

            # 페이지 제목 영역 클릭으로도 시도
            try:
                await self.dom.click("h1, .header, .title", timeout=1000)
            except:
                pass

        except Exception as e:
            console.print(f"[red]드롭다운 닫기 오류 ({dep_class}): {e}[/red]")

    async def _select_option(self, dep_class: str, option: Dict) -> bool:
        """옵션 선택 - Playwright 액션 사용"""
        try:
            if dep_class == "fuel":
                return await self._select_fuel_option(option)

            console.print(
                f"[blue]옵션 선택 시도: {option['text']} (코드: {option['code']})[/blue]"
            )

            # 드롭다운 열기
            await self._open_dropdown(dep_class)

            # Playwright 액션으로 옵션 선택
            try:
                # 1단계: data-code로 시도
                selector = (
                    f'li.{dep_class} a.select_opt.ui_opt[data-code="{option["code"]}"]'
                )
                element = await self.dom.wait_for_selector(selector, timeout=3000)
                if element:
                    await element.click()
                    console.print(f"[green]data-code 클릭 성공: {option['text']}[/green]")
                else:
                    # 2단계: data-value로 시도
                    selector = f'li.{dep_class} a.select_opt.ui_opt[data-value="{option["value"]}"]'
                    element = await self.dom.wait_for_selector(selector, timeout=3000)
                    if element:
                        await element.click()
                        console.print(
                            f"[green]data-value 클릭 성공: {option['text']}[/green]"
                        )
                    else:
                        # 3단계: 텍스트로 시도
                        selector = f'li.{dep_class} a.select_opt.ui_opt:has-text("{option["text"]}")'
                        element = await self.dom.wait_for_selector(
                            selector, timeout=3000
                        )
                        if element:
                            await element.click()
                            console.print(f"[green]텍스트 클릭 성공: {option['text']}[/green]")
                        else:
                            raise Exception("옵션을 찾을 수 없음")

            except Exception as e:
                console.print(f"[red]Playwright 옵션 선택 실패: {e}[/red]")
                # 대안: JavaScript로 시도
                await self.dom.evaluate(
                    f"""
                    const options = document.querySelectorAll('li.{dep_class} a.select_opt.ui_opt');
                    for (let opt of options) {{
                        if (opt.getAttribute('data-code') === '{option["code"]}' ||
                            opt.getAttribute('data-value') === '{option["value"]}') {{
                            opt.click();
                            break;
                        }}
                    }}
                """
                )
                console.print(f"[yellow]JavaScript 대안 시도 완료: {option['text']}[/yellow]")

            # 옵션 선택 후 드롭다운 닫기
            await self.dom.click("body", position={"x": 50, "y": 50})
            await self.dom.wait_for_timeout(2000)  # 2초 대기

            # 페이지 로딩 대기
            try:
                await self.dom.wait_for_load_state("networkidle", timeout=5000)
            except:
                pass  # 타임아웃이어도 계속 진행

            return True
        except Exception as e:
            console.print(f"[red]옵션 선택 실패 ({dep_class}): {e}[/red]")
            return False

    async def _select_fuel_option(self, option: Dict) -> bool:
        """연료 옵션 선택 - Playwright 액션 사용"""
        try:
            console.print(
                f"[blue]연료 옵션 선택 시도: {option['text']} (코드: {option['code']})[/blue]"
            )

            await self._open_dropdown("fuel")

            # Playwright 액션으로 연료 옵션 선택
            try:
                # 1단계: data-code로 시도
                selector = f'li .select.ui_select[data-name="fuel"] a.select_opt.ui_opt[data-code="{option["code"]}"]'
                element = await self.dom.wait_for_selector(selector, timeout=5000)
                if element:
                    await element.click()
                    console.print(
                        f"[green]연료 옵션 선택 성공 (data-code): {option['text']}[/green]"
                    )
                else:
                    # 2단계: data-value로 시도
                    selector = f'li .select.ui_select[data-name="fuel"] a.select_opt.ui_opt[data-value="{option["value"]}"]'
                    element = await self.dom.wait_for_selector(selector, timeout=5000)
                    if element:
                        await element.click()
                        console.print(
                            f"[green]연료 옵션 선택 성공 (data-value): {option['text']}[/green]"
                        )
                    else:
                        # 3단계: 텍스트로 시도
                        selector = f'li .select.ui_select[data-name="fuel"] a.select_opt.ui_opt:has-text("{option["text"]}")'
                        element = await self.dom.wait_for_selector(
                            selector, timeout=5000
                        )
                        if element:
                            await element.click()
                            console.print(
                                f"[green]연료 옵션 선택 성공 (텍스트): {option['text']}[/green]"
                            )
                        else:
                            raise Exception("연료 옵션을 찾을 수 없음")

            except Exception as e:
                console.print(f"[red]Playwright 연료 옵션 선택 실패: {e}[/red]")
                # 대안: JavaScript로 시도
                await self.dom.evaluate(
                    f"""
                    const options = document.querySelectorAll('li .select.ui_select[data-name="fuel"] a.select_opt.ui_opt');
                    for (let opt of options) {{
                        if (opt.getAttribute('data-code') === '{option["code"]}' ||
                            opt.getAttribute('data-value') === '{option["value"]}') {{
                            opt.click();
                            break;
                        }}
                    }}
                """
                )
                console.print(f"[yellow]JavaScript 대안 시도 완료: {option['text']}[/yellow]")

            # 옵션 선택 후 드롭다운 닫기
            await self.dom.click("body", position={"x": 50, "y": 50})
            await self.dom.wait_for_timeout(2000)  # 2초 대기

            # 페이지 로딩 대기
            try:
                await self.dom.wait_for_load_state("networkidle", timeout=5000)
            except:
                pass  # 타임아웃이어도 계속 진행

            return True
        except Exception as e:
            console.print(f"[red]연료 옵션 선택 실패: {e}[/red]")
            return False

    async def _get_price_info(self) -> Tuple[Optional[float], bool, str]:
        """현재 선택된 옵션의 가격 정보 가져오기"""
        try:
            price_info = await self.dom.evaluate(
                """
                () => {
                    // 페이지 전체 텍스트에서 가격 패턴 찾기
                    const allText = document.body.textContent;

                    // 시세 미제공 체크 먼저
                    if (allText.includes('시세 미제공') || allText.includes('거래량이 적어')) {
                        return {
                            price: null,
                            available: false,
                            message: '시세 미제공'
                        };
                    }

                    // 다양한 가격 패턴 시도
                    const pricePatterns = [
                        // "금주 시세 212 ~ 1,298만원" 패턴
                        /금주 시세[\\s\\S]*?([0-9,]+)\\s*~\\s*([0-9,]+)\\s*만원/,
                        // "212 ~ 1,298만원" 패턴
                        /([0-9,]+)\\s*~\\s*([0-9,]+)\\s*만원/,
                        // "1,298만원" 패턴
                        /([0-9,]+)\\s*만원/,
                        // "212만원" 패턴 (범위가 아닌 단일 가격)
                        /([0-9,]+)\\s*만원/
                    ];

                    for (const pattern of pricePatterns) {
                        const match = allText.match(pattern);
                        if (match) {
                            // 범위가 있는 경우 첫 번째 값 사용
                            const priceStr = match[1] || match[0];
                            const price = parseFloat(priceStr.replace(/,/g, ''));
                            if (!isNaN(price) && price > 0) {
                                return {
                                    price: price,
                                    available: true,
                                    message: match[0]
                                };
                            }
                        }
                    }

                    // 가격 표시 영역에서 직접 찾기
                    const priceSelectors = [
                        '.price_result .price',
                        '.result_price .price',
                        '.price_result',
                        '.result_price',
                        '[class*="price"]',
                        '[id*="price"]',
                        '.wrp_price .price',
                        '.price_info .price',
                        '.price_text',
                        '.price_value'
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
                            const priceMatch = text.match(/([0-9,]+)\\s*만원/);
                            if (priceMatch) {
                                const price = parseFloat(priceMatch[1].replace(/,/g, ''));
                                if (!isNaN(price) && price > 0) {
                                    return {
                                        price: price,
                                        available: true,
                                        message: text
                                    };
                                }
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

    def _create_car_data(
        self, path: List[Dict], price: Optional[float], is_available: bool, message: str
    ) -> Dict:
        """차량 데이터 생성"""
        if len(path) < 6:
            raise ValueError("경로가 불완전합니다")

        # 옵션 조합 해시 생성
        option_string = "_".join([item.get("value", "") for item in path])
        options_hash = hashlib.md5(option_string.encode()).hexdigest()

        return {
            "manufacturer": path[0]["text"],
            "model": path[1]["text"],
            "detailed_model": path[2]["text"],
            "year": path[3]["text"],
            "fuel_type": path[4]["text"],
            "grade": path[5]["text"],
            "detailed_grade": path[6]["text"] if len(path) > 6 else "",
            "price": price,
            "is_price_available": is_available,
            "price_message": message,
            "options_hash": options_hash,
            "manufacturer_code": path[0].get("value", ""),
            "model_code": path[1].get("value", ""),
            "detailed_model_code": path[2].get("value", ""),
            "year_code": path[3].get("value", ""),
            "fuel_code": path[4].get("value", ""),
            "grade_code": path[5].get("value", ""),
            "detailed_grade_code": path[6].get("value", "") if len(path) > 6 else "",
        }

    async def _save_crawled_data(self) -> Tuple[int, int]:
        """크롤링된 데이터를 DB에 저장"""
        success_count = 0
        failed_count = 0

        for data in self.crawled_data:
            try:
                car_price = CarPrice(**data)
                self.session.add(car_price)
                self.session.commit()
                success_count += 1
            except Exception as e:
                failed_count += 1
                console.print(f"[red]DB 저장 실패: {e}[/red]")
                self.session.rollback()

        return success_count, failed_count

    async def test_single_combination(self):
        """단일 조합 테스트 (디버깅용) - 1순회만 확인"""
        try:
            await self.navigate_to_price_page()

            # 페이지 구조 분석
            console.print("[cyan]페이지 구조 분석 중...[/cyan]")

            # op_dep1~6 요소들 확인
            for i in range(1, 7):
                dep_class = f"op_dep{i}"
                element = await self.dom.query_selector(f"li.{dep_class}")
                if element:
                    console.print(f"[green]존재: {dep_class}[/green]")

                    # 옵션 개수 확인
                    options = await self._get_options(dep_class)
                    console.print(f"  - 옵션 {len(options)}개")

                    # 처음 3개 옵션 표시
                    for opt in options[:3]:
                        price_text = opt.get("price_text", "")
                        console.print(f"    • {opt['text']} - {price_text}")
                else:
                    console.print(f"[yellow]없음: {dep_class}[/yellow]")

            # 연료 옵션 확인
            fuel_options = await self._get_fuel_options()
            console.print(f"[green]연료 옵션 {len(fuel_options)}개 발견[/green]")
            for opt in fuel_options[:3]:
                price_text = opt.get("price_text", "")
                console.print(f"  • {opt['text']} - {price_text}")

            # 1순회 크롤링 테스트 (op_dep6까지)
            console.print("\n[cyan]1순회 크롤링 테스트 시작...[/cyan]")

            # 제조사 선택
            manufacturers = await self._get_options("op_dep1")
            if manufacturers and len(manufacturers) > 1:
                manufacturer = manufacturers[1]  # 첫 번째는 플레이스홀더
                console.print(f"[cyan]제조사 선택: {manufacturer['text']}[/cyan]")

                if await self._select_option("op_dep1", manufacturer):
                    self.current_path = [manufacturer]
                    await self.dom.wait_for_timeout(2000)  # 2초 대기

                    # 모델 선택
                    models = await self._get_options("op_dep2")
                    if models:
                        model = models[0]
                        console.print(f"[cyan]모델 선택: {model['text']}[/cyan]")

                        if await self._select_option("op_dep2", model):
                            self.current_path = self.current_path[:1] + [model]
                            await self.dom.wait_for_timeout(2000)  # 2초 대기

                            # 세부모델 선택
                            detailed_models = await self._get_options("op_dep3")
                            if detailed_models:
                                detailed_model = detailed_models[0]
                                console.print(
                                    f"[cyan]세부모델 선택: {detailed_model['text']}[/cyan]"
                                )

                                if await self._select_option("op_dep3", detailed_model):
                                    self.current_path = self.current_path[:2] + [
                                        detailed_model
                                    ]
                                    await self.dom.wait_for_timeout(2000)  # 2초 대기

                                    # 연식 선택
                                    years = await self._get_options("op_dep4")
                                    if years:
                                        year = years[0]
                                        console.print(
                                            f"[cyan]연식 선택: {year['text']}[/cyan]"
                                        )

                                        if await self._select_option("op_dep4", year):
                                            self.current_path = self.current_path[
                                                :3
                                            ] + [year]
                                            await self.dom.wait_for_timeout(
                                                2000
                                            )  # 2초 대기

                                            # 연료 선택
                                            fuel_options = (
                                                await self._get_fuel_options()
                                            )
                                            if fuel_options:
                                                fuel = fuel_options[0]
                                                console.print(
                                                    f"[cyan]연료 선택: {fuel['text']}[/cyan]"
                                                )

                                                if await self._select_fuel_option(fuel):
                                                    self.current_path = (
                                                        self.current_path[:4] + [fuel]
                                                    )
                                                    await self.dom.wait_for_timeout(
                                                        2000
                                                    )  # 2초 대기

                                                    # 등급 선택
                                                    grades = await self._get_options(
                                                        "op_dep5"
                                                    )
                                                    if grades:
                                                        grade = grades[0]
                                                        console.print(
                                                            f"[cyan]등급 선택: {grade['text']}[/cyan]"
                                                        )

                                                        if await self._select_option(
                                                            "op_dep5", grade
                                                        ):
                                                            self.current_path = (
                                                                self.current_path[:5]
                                                                + [grade]
                                                            )
                                                            await self.dom.wait_for_timeout(
                                                                2000
                                                            )  # 2초 대기

                                                            # 세부등급 선택 (op_dep6) - 3개까지만
                                                            detailed_grades = (
                                                                await self._get_options(
                                                                    "op_dep6"
                                                                )
                                                            )
                                                            console.print(
                                                                f"[green]세부등급 {len(detailed_grades)}개 발견[/green]"
                                                            )

                                                            max_grades = min(
                                                                3, len(detailed_grades)
                                                            )
                                                            console.print(
                                                                f"[yellow]세부등급 {max_grades}개만 테스트[/yellow]"
                                                            )

                                                            for (
                                                                i,
                                                                detailed_grade,
                                                            ) in enumerate(
                                                                detailed_grades[
                                                                    :max_grades
                                                                ]
                                                            ):
                                                                console.print(
                                                                    f"[cyan]세부등급 {i+1}/{max_grades} 선택: {detailed_grade['text']}[/cyan]"
                                                                )

                                                                if await self._select_option(
                                                                    "op_dep6",
                                                                    detailed_grade,
                                                                ):
                                                                    final_path = (
                                                                        self.current_path
                                                                        + [
                                                                            detailed_grade
                                                                        ]
                                                                    )

                                                                    # 가격 정보 가져오기
                                                                    (
                                                                        price,
                                                                        is_available,
                                                                        message,
                                                                    ) = (
                                                                        await self._get_price_info()
                                                                    )

                                                                    # 데이터 저장
                                                                    car_data = self._create_car_data(
                                                                        final_path,
                                                                        price,
                                                                        is_available,
                                                                        message,
                                                                    )
                                                                    self.crawled_data.append(
                                                                        car_data
                                                                    )

                                                                    # 로그 출력
                                                                    status_text = f"✓ {' '.join([item['text'] for item in final_path])}"
                                                                    if price:
                                                                        console.print(
                                                                            f"[green]{status_text} - {price:,.0f}만원[/green]"
                                                                        )
                                                                    else:
                                                                        console.print(
                                                                            f"[yellow]{status_text} - 시세 미제공[/yellow]"
                                                                        )
                                                                else:
                                                                    console.print(
                                                                        f"[red]세부등급 선택 실패: {detailed_grade['text']}[/red]"
                                                                    )

                                                            console.print(
                                                                f"[green]1순회 테스트 완료: {max_grades}개 세부등급 처리됨[/green]"
                                                            )
                                                        else:
                                                            console.print(
                                                                f"[red]등급 선택 실패: {grade['text']}[/red]"
                                                            )
                                                    else:
                                                        console.print(
                                                            "[red]등급 옵션을 찾을 수 없음[/red]"
                                                        )
                                                else:
                                                    console.print(
                                                        f"[red]연료 선택 실패: {fuel['text']}[/red]"
                                                    )
                                            else:
                                                console.print(
                                                    "[red]연료 옵션을 찾을 수 없음[/red]"
                                                )
                                        else:
                                            console.print(
                                                f"[red]연식 선택 실패: {year['text']}[/red]"
                                            )
                                    else:
                                        console.print("[red]연식 옵션을 찾을 수 없음[/red]")
                                else:
                                    console.print(
                                        f"[red]세부모델 선택 실패: {detailed_model['text']}[/red]"
                                    )
                            else:
                                console.print("[red]세부모델 옵션을 찾을 수 없음[/red]")
                        else:
                            console.print(f"[red]모델 선택 실패: {model['text']}[/red]")
                    else:
                        console.print("[red]모델 옵션을 찾을 수 없음[/red]")
                else:
                    console.print(f"[red]제조사 선택 실패: {manufacturer['text']}[/red]")
            else:
                console.print("[red]제조사 옵션을 찾을 수 없음[/red]")

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
