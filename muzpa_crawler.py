"""
Muzpa Crawler & Scraping Module.
Manages multi-browser launching (Chrome, Brave, Edge, Chromium), persistent profiles,
multi-tab coordination, SPA search navigation, DOM parsing, and Fuzzy Matching.
"""

import os
import re
import asyncio
import logging
import urllib.parse
from typing import List, Optional, Tuple, Dict, Any
from pathlib import Path
from playwright.async_api import async_playwright, BrowserContext, Page, ElementHandle, TimeoutError as PlaywrightTimeoutError
from rapidfuzz import fuzz

from config import settings
from models import SpotifyTrack, MuzpaCandidate

logger = logging.getLogger("muzpa_crawler")


def detect_available_browsers() -> Dict[str, Dict[str, Any]]:
    """Detects available web browsers installed on the host system."""
    detected = {}

    # 1. Google Chrome
    chrome_mac = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    if chrome_mac.exists():
        detected["chrome"] = {
            "name": "Google Chrome",
            "channel": "chrome",
            "executable_path": str(chrome_mac),
            "installed": True,
            "recommended": True
        }

    # 2. Brave Browser
    brave_mac = Path("/Applications/Brave Browser.app/Contents/MacOS/Brave Browser")
    if brave_mac.exists():
        detected["brave"] = {
            "name": "Brave Browser",
            "channel": None,
            "executable_path": str(brave_mac),
            "installed": True,
            "recommended": False
        }

    # 3. Microsoft Edge
    edge_mac = Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge")
    if edge_mac.exists():
        detected["edge"] = {
            "name": "Microsoft Edge",
            "channel": "msedge",
            "executable_path": str(edge_mac),
            "installed": True,
            "recommended": False
        }

    # 4. Bundled Playwright Chromium (Always available)
    detected["chromium"] = {
        "name": "Playwright Chromium (Bundled)",
        "channel": None,
        "executable_path": None,
        "installed": True,
        "recommended": not bool(detected)
    }

    return detected


def parse_duration_string(val: Optional[str] = None, raw_text: str = "", target_duration_ms: int = 0) -> str:
    """
    Robustly parses and normalizes track duration strings into clean MM:SS or H:MM:SS format.
    Handles:
      - Clean timestamps: '03:45', '3:45', '1:05:30'
      - Text with units: '3m 45s', '3m45s', '03:45 min', '225 sec'
      - Pure seconds/milliseconds: '225', '225.5', '225000'
      - Raw text fallback with music duration filtering & proximity matching to target Spotify track.
    """
    def _seconds_to_str(total_seconds: int) -> str:
        if total_seconds < 0:
            return "0:00"
        hours = total_seconds // 3600
        mins = (total_seconds % 3600) // 60
        secs = total_seconds % 60
        if hours > 0:
            return f"{hours}:{mins:02d}:{secs:02d}"
        return f"{mins}:{secs:02d}"

    def _str_to_seconds(time_str: str) -> Optional[int]:
        parts = time_str.strip().split(":")
        try:
            if len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
            elif len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        except (ValueError, TypeError):
            pass
        return None

    # 1. Try explicit val if provided
    if val:
        v = str(val).strip().strip("()[]{}|•- ")
        
        # Format: MM:SS or H:MM:SS
        if re.match(r"^\d{1,2}:\d{2}(?::\d{2})?$", v):
            secs = _str_to_seconds(v)
            if secs is not None and 10 <= secs <= 7200:
                return _seconds_to_str(secs)

        # Format: 3m 45s, 3min 45sec
        min_sec_match = re.search(r"(\d+)\s*(?:m|min|mins|'|:)\s*(\d+)\s*(?:s|sec|secs|\"|$)", v, re.IGNORECASE)
        if min_sec_match:
            mins, secs = int(min_sec_match.group(1)), int(min_sec_match.group(2))
            return _seconds_to_str(mins * 60 + secs)

        # Format: pure numbers (seconds or ms)
        if re.match(r"^\d+(?:\.\d+)?\s*(?:s|sec|secs)?$", v, re.IGNORECASE):
            num_str = re.sub(r"[^\d.]", "", v)
            try:
                num = float(num_str)
                if num > 10000:  # milliseconds
                    num = num / 1000.0
                total_secs = int(round(num))
                if 10 <= total_secs <= 7200:
                    return _seconds_to_str(total_secs)
            except Exception:
                pass

        # Check for timestamp inside string (e.g. "Duration: 03:45" or "03:45 / 320kbps")
        embedded_match = re.search(r"(?:^|\s|\(|\[)([0-5]?\d:[0-5]\d)(?:\s|\)|\]|$)", v)
        if embedded_match:
            secs = _str_to_seconds(embedded_match.group(1))
            if secs is not None and 10 <= secs <= 7200:
                return _seconds_to_str(secs)

    # 2. Extract from raw_text with proximity matching
    if raw_text:
        # Find all timestamp candidates in raw_text
        found_matches = re.findall(r"\b([0-5]?\d:[0-5]\d)\b", raw_text)
        valid_candidates = []
        for m in found_matches:
            s = _str_to_seconds(m)
            if s is not None and 15 <= s <= 3600:  # Reasonable music track range 15s to 60min
                valid_candidates.append((m, s))

        if valid_candidates:
            if target_duration_ms > 0:
                target_sec = int(target_duration_ms / 1000)
                # Pick the candidate closest to target track duration
                best_match = min(valid_candidates, key=lambda c: abs(c[1] - target_sec))
                return _seconds_to_str(best_match[1])
            else:
                return _seconds_to_str(valid_candidates[0][1])

    return "--:--"


class MuzpaCrawlerEngine:
    def __init__(self, browser_name: Optional[str] = None):
        self.browser_name = browser_name or settings.BROWSER_NAME
        self._playwright = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._dashboard_page: Optional[Page] = None
        self._lock: Optional[asyncio.Lock] = None
        self._is_initialized = False

    @property
    def lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def initialize(self, browser_name: Optional[str] = None, open_dashboard_tab: Optional[bool] = None) -> None:
        """Initializes persistent browser context with the chosen browser."""
        if browser_name:
            self.browser_name = browser_name

        should_open_tab = (
            open_dashboard_tab if open_dashboard_tab is not None else settings.OPEN_DASHBOARD_TAB
        ) and not settings.IS_DESKTOP_APP and not settings.HEADLESS

        async with self.lock:
            if self._is_initialized and self._context and self._page:
                if should_open_tab:
                    await self._ensure_dashboard_tab()
                return

            available = detect_available_browsers()
            chosen_key = self.browser_name.lower() if self.browser_name.lower() in available else "chrome"
            if chosen_key not in available:
                chosen_key = "chromium"

            browser_info = available[chosen_key]
            logger.info(f"Launching persistent browser: {browser_info['name']} (headless={settings.HEADLESS})...")

            self._playwright = await async_playwright().start()

            # Dedicated profile per browser
            profile_dir = settings.BROWSER_PROFILE_DIR / f"profile_{chosen_key}"
            profile_dir.mkdir(parents=True, exist_ok=True)

            launch_kwargs: Dict[str, Any] = {
                "user_data_dir": str(profile_dir),
                "headless": settings.HEADLESS,
                "viewport": {"width": 1366, "height": 850},
                "accept_downloads": True,
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--no-default-browser-check",
                    "--no-first-run",
                ]
            }

            if browser_info.get("channel"):
                launch_kwargs["channel"] = browser_info["channel"]
            elif browser_info.get("executable_path"):
                launch_kwargs["executable_path"] = browser_info["executable_path"]

            try:
                self._context = await self._playwright.chromium.launch_persistent_context(**launch_kwargs)
            except Exception as e:
                logger.warning(f"Error launching {browser_info['name']}, falling back to standard Chromium: {e}")
                launch_kwargs.pop("channel", None)
                launch_kwargs.pop("executable_path", None)
                self._context = await self._playwright.chromium.launch_persistent_context(**launch_kwargs)

            # Retrieve existing page for Muzpa
            pages = self._context.pages
            self._page = pages[0] if pages else await self._context.new_page()
            self._page.set_default_timeout(settings.PAGE_LOAD_TIMEOUT_MS)

            # 1. Navigate Page 1 to Muzpa
            try:
                logger.info(f"Opening Muzpa tab at: {settings.MUZPA_BASE_URL}")
                await self._page.goto(settings.MUZPA_BASE_URL, wait_until="domcontentloaded", timeout=settings.PAGE_LOAD_TIMEOUT_MS)
                await asyncio.sleep(1.0)
                await self.attempt_auto_login()
            except Exception as e:
                logger.warning(f"Initial Muzpa navigation notice: {e}")

            # 2. Open Page 2 for Spotify to Muzpa Dashboard if explicitly requested
            if should_open_tab:
                await self._ensure_dashboard_tab()

            self._is_initialized = True
            logger.info(f"Crawler Engine successfully initialized using {browser_info['name']}.")

    async def _ensure_dashboard_tab(self) -> None:
        """Ensures the local Web Studio dashboard tab is open in the same browser window."""
        if not self._context or settings.HEADLESS:
            return

        dashboard_url = f"http://{settings.HOST}:{settings.PORT}"
        try:
            for p in self._context.pages:
                if f":{settings.PORT}" in p.url or "localhost" in p.url or "127.0.0.1" in p.url:
                    self._dashboard_page = p
                    await self._dashboard_page.bring_to_front()
                    return

            logger.info(f"Opening Spotify to Muzpa Studio tab at: {dashboard_url}")
            self._dashboard_page = await self._context.new_page()
            await self._dashboard_page.goto(dashboard_url, wait_until="domcontentloaded", timeout=10000)
            await self._dashboard_page.bring_to_front()
        except Exception as e:
            logger.warning(f"Notice while opening dashboard tab: {e}")

    async def bring_muzpa_to_front(self) -> None:
        if self._page:
            try:
                await self._page.bring_to_front()
            except Exception as e:
                logger.debug(f"Could not focus Muzpa tab: {e}")

    async def bring_dashboard_to_front(self) -> None:
        if self._dashboard_page:
            try:
                await self._dashboard_page.bring_to_front()
            except Exception as e:
                logger.debug(f"Could not focus Dashboard tab: {e}")

    async def close(self) -> None:
        """Closes browser context and Playwright instance."""
        async with self.lock:
            if self._context:
                try:
                    await self._context.close()
                except Exception as e:
                    logger.debug(f"Error closing browser context: {e}")
                self._context = None
                self._page = None
                self._dashboard_page = None

            if self._playwright:
                try:
                    await self._playwright.stop()
                except Exception as e:
                    logger.debug(f"Error stopping playwright: {e}")
                self._playwright = None

            self._is_initialized = False
            logger.info("Crawler Engine closed.")

    @property
    def page(self) -> Page:
        if not self._page:
            raise RuntimeError("Crawler engine not initialized. Call initialize() first.")
        return self._page

    @property
    def context(self) -> BrowserContext:
        if not self._context:
            raise RuntimeError("Crawler engine context not initialized.")
        return self._context

    async def autofill_login_form(self, email: Optional[str] = None, password: Optional[str] = None, submit: bool = False) -> bool:
        """
        Detects, reveals (if modal/link), and auto-fills the Muzpa login form with credentials.
        Dispatches native JavaScript input/change events to support AngularJS (ng-model) and SPA reactivity.
        """
        user_email = email or settings.MUZPA_EMAIL
        user_pass = password or settings.MUZPA_PASSWORD

        if not user_email or not user_pass:
            logger.info("No Muzpa credentials configured for auto-fill.")
            return False

        if not self._page:
            logger.warning("Crawler page not initialized for auto-fill.")
            return False

        try:
            logger.info(f"Attempting to auto-fill Muzpa login for user: '{user_email}'...")

            # 1. Check if login button/link needs to be clicked to open login modal/dropdown
            login_triggers = [
                'a:has-text("Log In")', 'a:has-text("Sign In")', 'a:has-text("Login")',
                'button:has-text("Log In")', 'button:has-text("Login")',
                'a[href*="login"]', 'a[href*="signin"]', '.btn-login', '.login-btn'
            ]
            for trigger_sel in login_triggers:
                try:
                    trigger = await self._page.query_selector(trigger_sel)
                    if trigger and await trigger.is_visible():
                        logger.debug(f"Clicking login modal trigger: {trigger_sel}")
                        await trigger.click()
                        await asyncio.sleep(0.6)
                        break
                except Exception:
                    pass

            # 2. Locate Username/Email and Password fields
            email_selectors = [
                'input[type="email"]', 'input[name="email"]', 'input[name="username"]',
                'input[name="login"]', 'input[name="user"]', 'input[ng-model*="email"]',
                'input[ng-model*="user"]', 'input[ng-model*="login"]',
                'input[placeholder*="Email" i]', 'input[placeholder*="User" i]',
                'input[placeholder*="Login" i]', '#email', '#username', '#login'
            ]

            pass_selectors = [
                'input[type="password"]', 'input[name="password"]', 'input[name="pass"]',
                'input[ng-model*="pass"]', 'input[ng-model*="password"]',
                'input[placeholder*="Pass" i]', 'input[placeholder*="Contraseña" i]',
                '#password', '#pass'
            ]

            email_el = None
            for sel in email_selectors:
                el = await self._page.query_selector(sel)
                if el and await el.is_visible():
                    email_el = el
                    break

            pass_el = None
            for sel in pass_selectors:
                el = await self._page.query_selector(sel)
                if el and await el.is_visible():
                    pass_el = el
                    break

            if email_el and pass_el:
                # Clear and fill fields
                await email_el.click()
                await email_el.fill(user_email)
                # Dispatch Angular / JS reactive events
                await self._page.evaluate("""(el) => {
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    el.style.border = '2px solid #1DB954';
                }""", email_el)

                await pass_el.click()
                await pass_el.fill(user_pass)
                await self._page.evaluate("""(el) => {
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    el.style.border = '2px solid #1DB954';
                }""", pass_el)

                logger.info("Successfully auto-filled Muzpa username/email and password fields!")

                # 3. Optional auto-submit
                if submit:
                    submit_selectors = [
                        'button[type="submit"]', 'input[type="submit"]',
                        'button:has-text("Log In")', 'button:has-text("Sign In")',
                        'button:has-text("Login")', 'button:has-text("Entrar")',
                        '.btn-submit', '.btn-login', 'button.submit'
                    ]
                    for sub_sel in submit_selectors:
                        sub_btn = await self._page.query_selector(sub_sel)
                        if sub_btn and await sub_btn.is_visible():
                            logger.info(f"Submitting login form via: {sub_sel}")
                            await sub_btn.click()
                            await self._page.wait_for_load_state("networkidle", timeout=8000)
                            break

                return True
            else:
                logger.debug("Muzpa login inputs not currently visible (user might already be logged in).")

        except Exception as e:
            logger.warning(f"Notice during Muzpa auto-fill: {e}")

        return False

    async def attempt_auto_login(self) -> bool:
        """Attempts best-effort login if credentials are supplied."""
        return await self.autofill_login_form(submit=False)

    def calculate_fuzzy_score(self, target: SpotifyTrack, cand_title: str, cand_artist: str, cand_duration: str = "") -> float:
        """Calculates a composite fuzzy match score (0 to 100)."""
        target_title = target.title.lower().strip()
        target_artist = target.artist.lower().strip()
        c_title = cand_title.lower().strip()
        c_artist = cand_artist.lower().strip()

        title_ratio = fuzz.token_set_ratio(target_title, c_title)
        artist_ratio = fuzz.token_set_ratio(target_artist, c_artist)

        target_full = f"{target_artist} - {target_title}"
        cand_full = f"{c_artist} - {c_title}"
        full_ratio = fuzz.token_set_ratio(target_full, cand_full)
        sort_ratio = fuzz.token_sort_ratio(target_full, cand_full)

        composite_score = (title_ratio * 0.40) + (artist_ratio * 0.30) + ((full_ratio + sort_ratio) / 2 * 0.30)

        if cand_duration and ":" in cand_duration:
            try:
                parts = cand_duration.strip().split(":")
                cand_seconds = int(parts[0]) * 60 + int(parts[1])
                target_seconds = int(target.duration_ms / 1000)
                diff = abs(cand_seconds - target_seconds)

                if diff <= 4:
                    composite_score = min(100.0, composite_score + 5.0)
                elif diff > 45:
                    composite_score = max(0.0, composite_score - 15.0)
            except Exception:
                pass

        return round(composite_score, 1)

    async def search_track(self, track: SpotifyTrack, custom_query: Optional[str] = None) -> List[MuzpaCandidate]:
        """Searches Muzpa for track, parses DOM, and returns ranked candidates."""
        async with self.lock:
            if not self._is_initialized:
                await self.initialize()

            query = custom_query or track.clean_search_query
            logger.info(f"Searching Muzpa for: '{query}'")

            encoded_query = urllib.parse.quote(query)
            search_url = f"{settings.MUZPA_BASE_URL}/#/search?text={encoded_query}"

            try:
                await self._page.goto(search_url, wait_until="domcontentloaded", timeout=settings.PAGE_LOAD_TIMEOUT_MS)
            except Exception as e:
                logger.warning(f"Goto timeout/issue, retrying search navigation: {e}")
                await self._page.goto(search_url, timeout=settings.PAGE_LOAD_TIMEOUT_MS)

            await asyncio.sleep(settings.RATE_LIMIT_DELAY_SECONDS)

            selectors = [
                "ms-release-track",
                ".ms-release-track",
                "div.release-track",
                "table.tracks-table tr",
                ".search-results .track",
                ".track-row"
            ]

            track_elements: List[ElementHandle] = []
            for selector in selectors:
                try:
                    await self._page.wait_for_selector(selector, timeout=4000)
                    track_elements = await self._page.query_selector_all(selector)
                    if track_elements:
                        break
                except PlaywrightTimeoutError:
                    continue

            if not track_elements:
                download_btns = await self._page.query_selector_all("a.ms-release-dwnldbtn, button.download, a[href*='download']")
                if download_btns:
                    track_elements = download_btns

            candidates: List[MuzpaCandidate] = []

            for idx, el in enumerate(track_elements):
                try:
                    raw_text = (await el.inner_text()).strip()
                    if not raw_text:
                        continue

                    cand_title = ""
                    cand_artist = ""
                    cand_duration = ""
                    cand_bitrate = None
                    direct_href = None

                    title_el = await el.query_selector(".track-title, .title, .song-name, strong, a.track-link")
                    artist_el = await el.query_selector(".track-artist, .artist, .artist-name, em")
                    dwnld_el = await el.query_selector("a.ms-release-dwnldbtn, a[href*='download'], button.download, .dwnldbtn")

                    if title_el:
                        cand_title = (await title_el.inner_text()).strip()
                    if artist_el:
                        cand_artist = (await artist_el.inner_text()).strip()
                    if dwnld_el:
                        direct_href = await dwnld_el.get_attribute("href")

                    if not cand_title or not cand_artist:
                        lines = [line.strip() for line in raw_text.split("\n") if line.strip()]
                        if len(lines) >= 2:
                            cand_artist = lines[0]
                            cand_title = lines[1]
                        elif len(lines) == 1:
                            if " - " in lines[0]:
                                parts = lines[0].split(" - ", 1)
                                cand_artist, cand_title = parts[0].strip(), parts[1].strip()
                            else:
                                cand_title = lines[0]
                                cand_artist = track.artist

                    # Extract duration using DOM evaluate with selectors/attributes + parse_duration_string
                    try:
                        dom_dur = await el.evaluate("""(node) => {
                            const durSelectors = [
                                '.ms-release-track-duration',
                                '.ms-release-track-time',
                                '.ms-track-duration',
                                '.ms-track-time',
                                '.track-duration',
                                '.track-time',
                                '.duration',
                                '.time',
                                '.length',
                                'span[class*="duration"]',
                                'span[class*="time"]',
                                'div[class*="duration"]',
                                'div[class*="time"]',
                                '[ng-bind*="duration"]',
                                '[ng-bind*="length"]',
                                '[ng-bind*="time"]'
                            ];
                            for (const sel of durSelectors) {
                                const found = node.querySelector(sel);
                                if (found) {
                                    const txt = (found.innerText || found.textContent || '').trim();
                                    if (txt && !txt.toLowerCase().includes('kbps')) return txt;
                                }
                            }
                            const attrNames = ['data-duration', 'data-time', 'data-length', 'duration', 'length'];
                            for (const attr of attrNames) {
                                if (node.hasAttribute(attr)) return node.getAttribute(attr);
                                const childWithAttr = node.querySelector(`[${attr}]`);
                                if (childWithAttr) return childWithAttr.getAttribute(attr);
                            }
                            return '';
                        }""")
                    except Exception:
                        dom_dur = ""

                    cand_duration = parse_duration_string(
                        val=dom_dur,
                        raw_text=raw_text,
                        target_duration_ms=track.duration_ms
                    )

                    bitrate_match = re.search(r"\b(320|256|192|128)\s*kbps\b", raw_text, re.IGNORECASE)
                    if bitrate_match:
                        cand_bitrate = bitrate_match.group(0).upper()

                    score = self.calculate_fuzzy_score(track, cand_title, cand_artist, cand_duration)

                    candidate = MuzpaCandidate(
                        id=f"cand_{idx}",
                        title=cand_title or f"Result #{idx+1}",
                        artist=cand_artist or "Unknown",
                        duration=cand_duration or "--:--",
                        bitrate=cand_bitrate,
                        score=score,
                        download_selector=f"candidate-index-{idx}",
                        direct_href=direct_href,
                        raw_text=raw_text[:200]
                    )
                    candidates.append(candidate)

                except Exception as ex:
                    logger.debug(f"Error parsing candidate element {idx}: {ex}")

            candidates.sort(key=lambda c: c.score, reverse=True)
            logger.info(f"Extracted {len(candidates)} candidates for '{track.title}'. Top score: {candidates[0].score if candidates else 0.0}")
            return candidates
