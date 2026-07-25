"""Playwright-based fichador engine with interactive 2FA support."""
import asyncio
import json
import logging
from datetime import datetime, date, time
from typing import Optional
from pathlib import Path
from enum import Enum

from playwright.async_api import async_playwright, Browser, Page, BrowserContext

from app.config import settings

logger = logging.getLogger(__name__)

COOKIES_DIR = Path("data/cookies")
SESSION_FILE = COOKIES_DIR / "holded_session.json"
DEBUG_DIR = Path("data/debug")
DEBUG_MANIFEST = DEBUG_DIR / "manifest.json"


class AuthState(str, Enum):
    IDLE = "idle"
    LOGGING_IN = "logging_in"
    WAITING_2FA = "waiting_2fa"
    COMPLETED = "completed"
    ERROR = "error"


class HoldedFichador:
    """Automates clock-in/out on Holded with interactive 2FA."""

    def __init__(self):
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self._ensure_cookies_dir()

        # Headless mode (False = visible browser for debugging)
        # Load from config if available
        self.headless: bool = self._load_headless_from_config()

        # Auth state for 2FA flow
        self.auth_state = AuthState.IDLE
        self.auth_message = ""
        self.auth_error = None
        self._2fa_code: Optional[str] = None
        self._2fa_event = asyncio.Event()

        # Debug screenshots
        self._debug_steps: list = []

    def _load_headless_from_config(self) -> bool:
        """Load headless setting from config.json."""
        try:
            import json
            from pathlib import Path
            config_file = Path("data/config.json")
            if config_file.exists():
                config = json.loads(config_file.read_text())
                if "headless" in config:
                    val = config["headless"]
                    logger.info(f"Loaded headless={val} from config.json")
                    return bool(val)
        except Exception as e:
            logger.debug(f"Could not load headless from config: {e}")
        return True  # Default to headless

    def _ensure_cookies_dir(self):
        COOKIES_DIR.mkdir(parents=True, exist_ok=True)
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    def _debug_screenshot(self, step: str, action: str = ""):
        """Save a debug screenshot with step name and metadata. Non-async for convenience."""
        try:
            if not self.page:
                return
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(self._async_debug_screenshot(step, action))
            else:
                loop.run_until_complete(self._async_debug_screenshot(step, action))
        except Exception as e:
            logger.debug(f"Debug screenshot failed: {e}")

    async def _async_debug_screenshot(self, step: str, action: str = ""):
        """Async version of debug screenshot."""
        try:
            if not self.page:
                return
            # Clean step name for filename
            safe_step = step.replace(" ", "_").replace("/", "-")[:50]
            timestamp = datetime.now().strftime("%H%M%S_%f")[:-3]
            filename = f"{timestamp}_{safe_step}.png"
            filepath = DEBUG_DIR / filename

            await self.page.screenshot(path=str(filepath), full_page=False)

            # Update manifest
            entry = {
                "step": step,
                "action": action,
                "filename": filename,
                "timestamp": datetime.now().isoformat(),
                "url": self.page.url if self.page else ""
            }
            self._debug_steps.append(entry)

            # Save manifest
            DEBUG_MANIFEST.write_text(json.dumps(self._debug_steps, indent=2, ensure_ascii=False))
            logger.info(f"Debug screenshot: {step}")
        except Exception as e:
            logger.debug(f"Async debug screenshot failed: {e}")

    def _clear_debug_steps(self):
        """Clear debug steps at the start of an operation."""
        self._debug_steps = []
        # Clean old debug files
        try:
            for f in DEBUG_DIR.glob("*.png"):
                f.unlink()
            if DEBUG_MANIFEST.exists():
                DEBUG_MANIFEST.unlink()
        except:
            pass

    def get_debug_steps(self) -> list:
        """Return current debug steps."""
        return self._debug_steps

    async def start(self, headless: bool = True):
        try:
            import os
            import subprocess
            import shutil

            self.playwright = await async_playwright().start()

            launch_args = ['--no-sandbox', '--disable-setuid-sandbox']

            # Ensure Xvfb is running for visible mode
            if not headless:
                # Check if DISPLAY is already set and valid
                display = os.environ.get('DISPLAY')
                if not display:
                    # Start Xvfb on :99
                    xvfb_running = subprocess.run(
                        ['pgrep', '-f', 'Xvfb :99'],
                        capture_output=True
                    ).returncode == 0

                    if not xvfb_running:
                        if shutil.which('Xvfb'):
                            logger.info("Starting Xvfb on :99 for visible mode")
                            subprocess.Popen(
                                ['Xvfb', ':99', '-screen', '0', '1920x1080x24'],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL
                            )
                            await asyncio.sleep(2)
                            logger.info("Xvfb started on :99")
                        else:
                            logger.warning("Xvfb not installed, falling back to headless mode")
                            headless = True
                    else:
                        logger.info("Xvfb already running on :99")

                    os.environ['DISPLAY'] = ':99'

            # Launch browser
            try:
                self.browser = await self.playwright.chromium.launch(
                    headless=headless,
                    args=launch_args
                )
                logger.info(f"Browser launched (headless={headless})")
            except Exception as launch_error:
                if not headless:
                    logger.warning(f"Visible mode failed ({launch_error}), falling back to headless")
                    self.browser = await self.playwright.chromium.launch(
                        headless=True,
                        args=launch_args
                    )
                else:
                    raise

            # Try to restore full session (cookies + localStorage + sessionStorage)
            storage_state = await self._load_storage_state()
            context_opts = {
                'viewport': {'width': 1920, 'height': 1080},
                'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            if storage_state:
                context_opts['storage_state'] = storage_state
                logger.info("Creating context with saved storage state")

            self.context = await self.browser.new_context(**context_opts)
            self.context.set_default_timeout(60000)
            self.page = await self.context.new_page()
            logger.info("Browser started successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to start browser: {e}")
            return False

    async def stop(self, save_session: bool = True):
        try:
            if save_session:
                await self._save_session()
            if self.page:
                await self.page.close()
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
            logger.info("Browser stopped successfully")
        except Exception as e:
            logger.error(f"Error stopping browser: {e}")
        finally:
            self.page = None
            self.context = None
            self.browser = None
            self.playwright = None

    async def _save_session(self, user_email: str = ""):
        try:
            if self.context:
                cookies = await self.context.cookies()
                storage = await self.context.storage_state()
                session_data = {
                    "cookies": cookies,
                    "storage": storage,
                    "saved_at": datetime.now().isoformat(),
                    "user_email": user_email
                }
                SESSION_FILE.write_text(json.dumps(session_data, indent=2))
                logger.info(f"Session saved successfully (email={user_email})")
        except Exception as e:
            logger.error(f"Failed to save session: {e}")

    async def _load_storage_state(self) -> Optional[dict]:
        """Load full storage state (cookies + localStorage) from saved session."""
        try:
            if SESSION_FILE.exists():
                session_data = json.loads(SESSION_FILE.read_text())
                storage = session_data.get("storage")
                if storage:
                    logger.info("Loaded storage state from saved session")
                    return storage
                # Fallback: old format with just cookies
                cookies = session_data.get("cookies", [])
                if cookies:
                    logger.info(f"Loaded {len(cookies)} cookies (legacy format)")
                    return {"cookies": cookies, "origins": []}
        except Exception as e:
            logger.warning(f"Failed to load storage state: {e}")
        return None

    def is_session_valid(self) -> bool:
        if not SESSION_FILE.exists():
            return False
        try:
            session_data = json.loads(SESSION_FILE.read_text())
            saved_at = datetime.fromisoformat(session_data.get("saved_at", ""))
            return (datetime.now() - saved_at).total_seconds() < 604800  # 7 days
        except:
            return False

    def get_auth_status(self) -> dict:
        """Get current authentication status."""
        return {
            "state": self.auth_state.value,
            "message": self.auth_message,
            "error": self.auth_error
        }

    def set_2fa_code(self, code: str):
        """Set the 2FA code received from the user."""
        self._2fa_code = code
        self._2fa_event.set()
        logger.info("2FA code received and set")

    async def _wait_for_2fa_code(self, timeout: int = 300) -> Optional[str]:
        """Wait for 2FA code from user (via API)."""
        self._2fa_code = None
        self._2fa_event.clear()

        try:
            await asyncio.wait_for(self._2fa_event.wait(), timeout=timeout)
            return self._2fa_code
        except asyncio.TimeoutError:
            logger.warning("2FA code wait timed out")
            return None
        finally:
            self._2fa_code = None
            self._2fa_event.clear()

    # ============================================================
    # LOGIN with 2FA - Using exact selectors from recorded scripts
    # ============================================================

    async def login_with_2fa(self, email: str, password: str) -> dict:
        """
        Login with automatic 2FA handling.
        Uses exact Playwright selectors from recorded Holded scripts.
        """
        try:
            self.auth_state = AuthState.LOGGING_IN
            self.auth_message = "Iniciando navegador..."
            self.auth_error = None

            # Delete stale session file before starting fresh login
            if SESSION_FILE.exists():
                SESSION_FILE.unlink()
                logger.info("Deleted stale session file")

            # Start browser (respetar modo debug/headless del usuario)
            if not await self.start(headless=self.headless):
                self.auth_state = AuthState.ERROR
                self.auth_error = "No se pudo iniciar el navegador"
                return {"status": "error", "message": "No se pudo iniciar el navegador"}

            self.auth_message = "Navegando a Holded..."
            # Navigate to root URL (recorded script goes to https://app.holded.com/)
            await self.page.goto("https://app.holded.com/", wait_until='domcontentloaded', timeout=60000)
            await asyncio.sleep(5)

            # Check if already logged in (not on login page)
            current_url = self.page.url
            is_logged_in = '/login' not in current_url and ('myzone' in current_url or 'dashboard' in current_url)
            if is_logged_in:
                self.auth_state = AuthState.COMPLETED
                self.auth_message = "Ya estás logueado"
                await self._save_session(user_email=email)
                await self.stop()
                return {"status": "success", "message": "Ya estás logueado"}

            self.auth_message = "Introduciendo credenciales..."

            # Dismiss cookie consent (ES: "Aceptar todo" / EN: "Accept all")
            try:
                for name in ["Aceptar todo", "Accept all"]:
                    accept_btn = self.page.get_by_role("button", name=name)
                    if await accept_btn.count() > 0:
                        await accept_btn.click()
                        await asyncio.sleep(1)
                        logger.info(f"Dismissed cookie consent ({name})")
                        break
            except Exception as e:
                logger.debug(f"Cookie consent not found or already dismissed: {e}")

            # Fill email (ES: "Correo electrónico" / EN: "E-mail address")
            email_input = None
            for name in ["Correo electrónico", "E-mail address"]:
                try:
                    email_input = self.page.get_by_role("textbox", name=name)
                    if await email_input.count() > 0:
                        await email_input.wait_for(timeout=5000)
                        await email_input.fill(email)
                        logger.info(f"Email filled (selector: {name})")
                        break
                    email_input = None
                except:
                    email_input = None

            if not email_input:
                self.auth_state = AuthState.ERROR
                self.auth_error = "No se encontró el campo de email"
                await self.stop(save_session=False)
                return {"status": "error", "message": self.auth_error}

            # Tab to password field (as in recorded script)
            await email_input.press("Tab")
            await asyncio.sleep(0.5)

            # Fill password (ES: "Contraseña" / EN: "Password")
            password_input = None
            for name in ["Contraseña", "Password"]:
                try:
                    password_input = self.page.get_by_role("textbox", name=name)
                    if await password_input.count() > 0:
                        await password_input.fill(password)
                        logger.info(f"Password filled (selector: {name})")
                        break
                    password_input = None
                except:
                    password_input = None

            if not password_input:
                self.auth_state = AuthState.ERROR
                self.auth_error = "No se encontró el campo de contraseña"
                await self.stop(save_session=False)
                return {"status": "error", "message": self.auth_error}

            # Click login (ES: "Iniciar sesión" / EN: "Sign in")
            login_clicked = False
            for name in ["Iniciar sesión", "Sign in"]:
                try:
                    login_button = self.page.get_by_role("button", name=name)
                    if await login_button.count() > 0:
                        await login_button.click()
                        login_clicked = True
                        logger.info(f"Clicked login button ({name})")
                        break
                except:
                    continue

            if not login_clicked:
                await password_input.press("Enter")

            self.auth_message = "Esperando respuesta de Holded..."
            await asyncio.sleep(5)

            # Wait for navigation after login click
            try:
                await self.page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass

            # Check result
            current_url = self.page.url
            logger.info(f"After login submit, URL: {current_url}")

            # Check if login was successful (no 2FA)
            if '/login' not in current_url and ('myzone' in current_url or 'dashboard' in current_url):
                self.auth_state = AuthState.COMPLETED
                self.auth_message = "Login exitoso"
                await self._save_session(user_email=email)
                await self.stop()
                return {"status": "success", "message": "Login exitoso"}

            # Wait a bit more for 2FA form to fully render
            await asyncio.sleep(3)

            # Take screenshot for debugging
            await self.page.screenshot(path="data/before_2fa_detection.png")
            logger.info(f"Screenshot saved. Current URL: {self.page.url}")

            # Check for 2FA
            has_2fa = await self._detect_2fa_form()

            if has_2fa:
                self.auth_state = AuthState.WAITING_2FA
                self.auth_message = "Se requiere código 2FA. Introducelo en la web."

                # Wait for 2FA code from user
                code = await self._wait_for_2fa_code(timeout=300)

                if code:
                    # Submit 2FA code
                    success = await self._submit_2fa_code(code)

                    # Take screenshot after 2FA submission for debugging
                    try:
                        await self.page.screenshot(path="data/after_2fa_submission.png")
                    except Exception:
                        pass

                    if success:
                        self.auth_state = AuthState.COMPLETED
                        self.auth_message = "Login completado con 2FA"
                        await self._save_session(user_email=email)
                        await self.stop()
                        return {"status": "success", "message": "Login completado con 2FA"}
                    else:
                        self.auth_state = AuthState.ERROR
                        self.auth_error = "Código 2FA incorrecto"
                        await self.stop(save_session=False)
                        return {"status": "error", "message": "Código 2FA incorrecto"}
                else:
                    self.auth_state = AuthState.ERROR
                    self.auth_error = "Timeout esperando código 2FA"
                    await self.stop(save_session=False)
                    return {"status": "error", "message": "Timeout esperando código 2FA"}

            # Check for error
            has_error = await self._detect_login_error()
            if has_error:
                self.auth_state = AuthState.ERROR
                self.auth_error = "Credenciales incorrectas"
                await self.stop(save_session=False)
                return {"status": "error", "message": "Credenciales incorrectas"}

            # If we get here, login might have succeeded without 2FA and without redirect detection
            # Try to save session with email
            self.auth_state = AuthState.COMPLETED
            self.auth_message = "Login completado"
            await self._save_session(user_email=email)
            await self.stop()
            return {"status": "success", "message": "Login completado"}

        except Exception as e:
            logger.error(f"Login failed: {e}")
            self.auth_state = AuthState.ERROR
            self.auth_error = str(e)
            try:
                await self.stop(save_session=False)
            except:
                pass
            return {"status": "error", "message": str(e)}

    async def _detect_2fa_form(self) -> bool:
        """Detect if 2FA form is displayed."""
        # Method 1: Check for "Digit 1" textbox (exact selector from recorded script)
        try:
            digit1 = self.page.get_by_role("textbox", name="Digit 1")
            count = await digit1.count()
            if count > 0:
                logger.info(f"Found 2FA form (Digit 1 textbox, count={count})")
                return True
        except Exception as e:
            logger.debug(f"Digit 1 check failed: {e}")

        # Method 2: Check for "Didn't get the code?" text
        try:
            resend_btn = self.page.get_by_role("button", name="Didn't get the code")
            if await resend_btn.count() > 0:
                logger.info("Found 2FA form (resend code button)")
                return True
        except Exception as e:
            logger.debug(f"Resend button check failed: {e}")

        # Method 3: Check for "Didn't get the code?" with different text
        try:
            resend_btn = await self.page.query_selector('button:has-text("Didn\'t get the code"), button:has-text("Reenviar")')
            if resend_btn:
                logger.info("Found 2FA form (resend code button via CSS)")
                return True
        except Exception as e:
            logger.debug(f"Resend CSS check failed: {e}")

        # Method 4: Check for 6 single-digit inputs (w-12 class)
        try:
            single_inputs = await self.page.query_selector_all('input[type="text"].w-12, input[type="text"][class*="w-12"]')
            if len(single_inputs) >= 4:
                logger.info(f"Found {len(single_inputs)} w-12 inputs (2FA form)")
                return True
        except Exception as e:
            logger.debug(f"w-12 input check failed: {e}")

        # Method 5: Check for any input with maxlength=1 (common 2FA pattern)
        try:
            single_char_inputs = await self.page.query_selector_all('input[maxlength="1"]')
            if len(single_char_inputs) >= 4:
                logger.info(f"Found {len(single_char_inputs)} maxlength=1 inputs (2FA form)")
                return True
        except Exception as e:
            logger.debug(f"maxlength=1 check failed: {e}")

        # Method 6: Look for text mentioning "verification" or "código"
        try:
            body_text = await self.page.inner_text('body')
            verification_texts = ['verification code', 'código de verificación', 'two-factor', '2FA', 'two step']
            for text in verification_texts:
                if text.lower() in body_text.lower():
                    logger.info(f"Found 2FA indicator text: '{text}'")
                    return True
        except Exception as e:
            logger.debug(f"Body text check failed: {e}")

        logger.info("No 2FA form detected")
        return False

    async def _submit_2fa_code(self, code: str) -> bool:
        """Submit 2FA code using exact selectors from recorded scripts.
        
        The Holded 2FA form auto-submits when all 6 digits are filled.
        After filling, we wait for navigation and verify the result.
        """
        try:
            # Find digit inputs (exact from recorded script: "Digit 1" .. "Digit 6")
            digit_inputs = []
            for i in range(1, 7):
                try:
                    digit_input = self.page.get_by_role("textbox", name=f"Digit {i}")
                    if await digit_input.count() > 0:
                        digit_inputs.append(digit_input)
                    else:
                        break
                except:
                    break

            if len(digit_inputs) < 6:
                # Fallback: try w-12 class inputs
                single_inputs = await self.page.query_selector_all('input[type="text"].w-12, input[type="text"][class*="w-12"]')
                if len(single_inputs) >= 4:
                    logger.info(f"Fallback: found {len(single_inputs)} w-12 inputs")
                    digit_inputs = single_inputs[:6]
                else:
                    logger.error("No 2FA inputs found")
                    return False

            logger.info(f"Filling {len(digit_inputs)} 2FA digit inputs")

            # Fill each digit exactly as in recorded script
            for i, digit_input in enumerate(digit_inputs):
                digit = code[i] if i < len(code) else ""
                await digit_input.click()
                # For Digit 1, the recorded script does: click, ArrowUp, then fill
                if i == 0:
                    await digit_input.press("ArrowUp")
                await digit_input.fill(digit)
                await asyncio.sleep(0.15)

            logger.info("All 6 digits filled, waiting for auto-submit...")

            # The form auto-submits after all digits are filled.
            # Wait for navigation away from the login/2FA page.
            try:
                await self.page.wait_for_url(
                    lambda url: '/login' not in url and ('myzone' in url or 'dashboard' in url),
                    timeout=15000
                )
                logger.info(f"2FA auto-submit succeeded, now at: {self.page.url}")
                return True
            except Exception:
                logger.debug("Auto-submit wait timed out, checking current state...")

            # Check if we're already on the right page
            current_url = self.page.url
            if '/login' not in current_url and ('myzone' in current_url or 'dashboard' in current_url):
                return True

            # Fallback: try pressing Enter on last digit
            try:
                last_input = digit_inputs[-1]
                await last_input.press("Enter")
                await asyncio.sleep(5)
                current_url = self.page.url
                if '/login' not in current_url and ('myzone' in current_url or 'dashboard' in current_url):
                    return True
            except:
                pass

            # Fallback: navigate directly to myzone
            try:
                await self.page.goto("https://app.holded.com/myzone", wait_until='domcontentloaded', timeout=30000)
                await asyncio.sleep(5)
                current_url = self.page.url
                if '/login' not in current_url and ('myzone' in current_url or 'dashboard' in current_url):
                    return True
            except:
                pass

            logger.warning(f"2FA submit: still on URL {self.page.url}")
            return False

        except Exception as e:
            logger.error(f"Failed to submit 2FA code: {e}")
            return False

    async def _detect_login_error(self) -> bool:
        """Detect login error messages."""
        try:
            # Check for specific error elements, not just body text substring
            error_selectors = [
                '[class*="error"]',
                '[class*="alert-danger"]',
                '[role="alert"]',
            ]
            for sel in error_selectors:
                try:
                    element = await self.page.query_selector(sel)
                    if element:
                        text = await element.inner_text()
                        if text and len(text.strip()) > 0:
                            logger.warning(f"Found error element: {sel} -> {text[:100]}")
                            return True
                except:
                    pass

            # Check for specific error text patterns (not just 'error' substring)
            specific_patterns = ['incorrect', 'inválido', 'incorrecta', 'invalid credentials', 'credenciales incorrectas']
            body_text = await self.page.inner_text('body')
            for pattern in specific_patterns:
                if pattern.lower() in body_text.lower():
                    logger.warning(f"Found error pattern in body: {pattern}")
                    return True
        except:
            pass
        return False

    async def _detect_holded_error(self) -> Optional[str]:
        """Detect Holded error messages (toast/snackbar notifications).
        Returns the error text if found, None otherwise.
        """
        try:
            # Holded uses MUI Snackbar for notifications
            # Check for snackbar/alert elements with error content
            error_selectors = [
                '[role="alert"]',
                '.MuiAlert-root',
                '.MuiSnackbar-root',
                '[class*="Snackbar"]',
                '[class*="snackbar"]',
                '[class*="toast"]',
                '[class*="notification"]',
            ]
            for sel in error_selectors:
                try:
                    elements = await self.page.query_selector_all(sel)
                    for element in elements:
                        text = await element.inner_text()
                        if text and len(text.strip()) > 2:
                            logger.warning(f"Holded notification ({sel}): {text.strip()[:200]}")
                            return text.strip()
                except:
                    pass

            # Also check body text for common Holded error patterns
            body_text = await self.page.inner_text('body')
            error_patterns = [
                'no tiene un contrato activo',
                'no tienes un contrato activo',
                'error al guardar',
                'error al registrar',
                'no se pudo guardar',
                'operación no permitida',
                'permiso denegado',
            ]
            for pattern in error_patterns:
                if pattern.lower() in body_text.lower():
                    logger.warning(f"Holded error pattern found: {pattern}")
                    return pattern

        except Exception as e:
            logger.debug(f"Holded error detection failed: {e}")
        return None

    # ============================================================
    # NAVIGATION
    # ============================================================

    async def navigate_to_time_control(self) -> bool:
        """Navigate to Control horario page."""
        try:
            # First try the "Control horario" button (as in recorded script)
            try:
                control_btn = self.page.get_by_role("button", name="Control horario")
                if await control_btn.count() > 0:
                    await control_btn.click()
                    await asyncio.sleep(3)
                    logger.info("Clicked 'Control horario' button")
                    return True
            except:
                pass

            # Fallback: direct URL
            await self.page.goto(
                "https://app.holded.com/myzone/time-tracking",
                wait_until='domcontentloaded',
                timeout=60000
            )
            await asyncio.sleep(3)
            return True
        except Exception as e:
            logger.error(f"Failed to navigate: {e}")
            return False

    async def _close_intercom_panel(self):
        """Close the Intercom help panel if it's open. It blocks the timer controls."""
        try:
            # Strategy 1: JavaScript - click any element with data-testid="close-button"
            result = await self.page.evaluate('''() => {
                // Click the close button (div with role="button", not a <button>)
                const closeBtn = document.querySelector('[data-testid="close-button"]');
                if (closeBtn) { closeBtn.click(); return 'clicked_close_button'; }

                // Try aria-label "Cerrar"
                const cerrar = document.querySelector('[aria-label="Cerrar"]');
                if (cerrar) { cerrar.click(); return 'clicked_cerrar'; }

                // Try aria-label "Close"
                const close = document.querySelector('[aria-label="Close"]');
                if (close) { close.click(); return 'clicked_close'; }

                // Try Intercom class
                const intercomClose = document.querySelector('.intercom-close-button');
                if (intercomClose) { intercomClose.click(); return 'clicked_intercom_close'; }

                return 'not_found';
            }''')
            logger.info(f"Intercom close attempt: {result}")

            if result != 'not_found':
                await asyncio.sleep(1)
                # Verify it closed
                still_open = await self.page.evaluate('''() => {
                    const panel = document.querySelector('[data-testid="close-button"]');
                    return panel ? panel.offsetParent !== null : false;
                }''')
                if not still_open:
                    logger.info("Intercom panel closed successfully")
                    return

            # Strategy 2: Hide the entire Intercom container via JS
            await self.page.evaluate('''() => {
                // Hide all Intercom elements
                document.querySelectorAll('[id*="intercom"], [class*="intercom"], [data-testid*="intercom"]').forEach(el => {
                    el.style.display = 'none';
                    el.style.visibility = 'hidden';
                    el.style.height = '0';
                    el.style.overflow = 'hidden';
                });
                // Also hide the space-help-panel
                const helpPanel = document.querySelector('[aria-label="space-help-panel"], #spaces-help-panel');
                if (helpPanel) {
                    helpPanel.style.display = 'none';
                    helpPanel.style.visibility = 'hidden';
                }
            }''')
            await asyncio.sleep(0.5)
            logger.info("Hidden Intercom panel via CSS manipulation")

        except Exception as e:
            logger.debug(f"Could not close Intercom panel: {e}")
            # Last resort: press Escape
            try:
                await self.page.keyboard.press("Escape")
                await asyncio.sleep(0.5)
            except:
                pass

    # ============================================================
    # LIVE TRACKING - Using exact MUI selectors from recorded scripts
    # ============================================================

    async def start_live_tracking(self) -> dict:
        """Click the play button to start live time tracking."""
        self._clear_debug_steps()
        try:
            if not await self.start(headless=self.headless):
                return {"status": "error", "message": "No se pudo iniciar el navegador"}

            await self._async_debug_screenshot("Navegador abierto", "start")

            if not self.is_session_valid() or not await self.check_session():
                await self.stop()
                return {"status": "session_expired", "message": "Sesión expirada"}

            await self._async_debug_screenshot("Sesion verificada", "check_session")

            # Navigate to time-tracking (where the play/stop/pause controls live)
            await self.page.goto(
                "https://app.holded.com/myzone/time-tracking",
                wait_until='domcontentloaded',
                timeout=60000
            )
            await asyncio.sleep(8)

            await self._async_debug_screenshot("En time-tracking", "navigate")

            await self._close_intercom_panel()
            await self._async_debug_screenshot("Intercom cerrado", "close_intercom")

            clicked = await self._click_play_button()

            await asyncio.sleep(3)
            await self._async_debug_screenshot("Despues de Play", "after_play")

            if clicked:
                return {"status": "success", "message": "Fichaje iniciado"}
            else:
                await self.stop()
                return {"status": "error", "message": "No se encontró el botón de play"}

        except Exception as e:
            logger.error(f"Failed to start live tracking: {e}")
            return {"status": "error", "message": str(e)}
        finally:
            await self.stop()

    async def _click_play_button(self) -> bool:
        """Click the play/start button in the live tracking widget.

        The play button contains an SVG with aria-label="Icon-play".
        """
        # Strategy 1: SVG aria-label (most reliable)
        try:
            btn = self.page.locator('button:has(svg[aria-label="Icon-play"])')
            if await btn.count() > 0:
                await btn.first.click()
                logger.info("Clicked play button via svg[aria-label=Icon-play]")
                return True
        except Exception as e:
            logger.debug(f"SVG Icon-play selector failed: {e}")

        # Strategy 2: Find the control stack (MuiStack with 2+ icon buttons)
        try:
            stacks = self.page.locator('[class*="MuiStack-root"]')
            count = await stacks.count()
            for i in range(count):
                stack = stacks.nth(i)
                buttons = stack.locator('button.MuiButtonBase-root.MuiIconButton-root')
                btn_count = await buttons.count()
                if btn_count >= 2:
                    box = await stack.bounding_box()
                    if box and box['x'] > 400 and box['y'] < 120:
                        await buttons.first.click()
                        logger.info(f"Clicked play button (1st in control stack at x={box['x']}, y={box['y']})")
                        return True
        except Exception as e:
            logger.debug(f"MuiStack control strategy failed: {e}")

        # Strategy 3: aria-label based
        for name in ["Iniciar", "Start", "Play", "Iniciar fichaje"]:
            try:
                btn = self.page.get_by_role("button", name=name)
                if await btn.count() > 0:
                    await btn.click()
                    logger.info(f"Clicked play button via aria-label: {name}")
                    return True
            except:
                pass

        logger.error("All play button strategies failed")
        return False

    async def pause_live_tracking(self) -> dict:
        """Pause live time tracking."""
        try:
            self._clear_debug_steps()

            if not await self.start(headless=self.headless):
                return {"status": "error", "message": "No se pudo iniciar el navegador"}

            if not self.is_session_valid() or not await self.check_session():
                await self.stop()
                return {"status": "session_expired", "message": "Sesión expirada"}

            await self._async_debug_screenshot("Navegador abierto", "start")

            # Navigate to time-tracking (where the controls live)
            await self.page.goto("https://app.holded.com/myzone/time-tracking", wait_until='domcontentloaded', timeout=60000)
            await asyncio.sleep(8)

            await self._async_debug_screenshot("En time-tracking", "navigate")

            await self._close_intercom_panel()
            await self._async_debug_screenshot("Intercom cerrado", "close_intercom")

            clicked = await self._click_pause_button()

            await asyncio.sleep(3)
            await self._async_debug_screenshot("Despues de Pausa", "after_pause")

            if clicked:
                return {"status": "success", "message": "Fichaje pausado"}
            else:
                await self.stop()
                return {"status": "error", "message": "No se encontró el botón de pausa"}

        except Exception as e:
            logger.error(f"Failed to pause live tracking: {e}")
            return {"status": "error", "message": str(e)}
        finally:
            await self.stop()

    async def _check_timer_active(self) -> bool:
        """Check if the live tracking timer is active (showing running time)."""
        try:
            await asyncio.sleep(2)  # Wait for page to fully load
            result = await self.page.evaluate('''() => {
                // Method 1: Search entire body text
                const bodyText = document.body.innerText || document.body.textContent || '';
                // Match patterns like "02h 59m 20s" or "2h 59m 20s"
                const timerMatch = bodyText.match(/\\d{1,2}h \\d{2}m \\d{2}s/);
                if (timerMatch) {
                    return {found: true, text: timerMatch[0], method: 'body_text'};
                }

                // Method 2: Search for elements with specific text
                const xpath = "//text()[contains(., 'h ') and contains(., 'm ') and contains(., 's')]";
                const textNodes = document.evaluate(xpath, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
                for (let i = 0; i < textNodes.snapshotLength; i++) {
                    const node = textNodes.snapshotItem(i);
                    const text = node.textContent.trim();
                    if (text.match(/\\d{1,2}h \\d{2}m \\d{2}s/)) {
                        return {found: true, text: text, method: 'xpath_text'};
                    }
                }

                // Method 3: Check for green timer chip specifically
                const greenChip = document.querySelector('[style*="background"][style*="green"], [style*="background"][style*="#0"], [class*="green"], [class*="timer"]');
                if (greenChip) {
                    const chipText = greenChip.textContent || '';
                    if (chipText.match(/\\d{1,2}h/)) {
                        return {found: true, text: chipText.substring(0, 30), method: 'green_chip'};
                    }
                }

                return {found: false, bodyLength: bodyText.length, snippet: bodyText.substring(0, 500)};
            }''')
            logger.info(f"Timer check result: {result}")
            return result.get('found', False)
        except Exception as e:
            logger.error(f"Timer check failed: {e}")
            return False

    async def _verify_pause_worked(self) -> bool:
        """Verify that pause actually worked by checking if timer stopped or status changed."""
        try:
            # Wait a moment for UI to update
            await asyncio.sleep(2)

            # Check 1: Look for "Pausado" status text
            result = await self.page.evaluate('''() => {
                const body = document.body.innerText;

                // Check for pause status indicators
                const pauseIndicators = ['Pausado', 'En pausa', 'Pausa activa'];
                for (const indicator of pauseIndicators) {
                    if (body.includes(indicator)) {
                        return {paused: true, reason: indicator};
                    }
                }

                // Check if timer is no longer running (stopped incrementing)
                // The timer should show a static time or "Pausado"
                const timerMatch = body.match(/\\d{2}h \\d{2}m \\d{2}s/);
                if (!timerMatch) {
                    return {paused: true, reason: 'timer_disappeared'};
                }

                return {paused: false, reason: 'timer_still_running'};
            }''')
            logger.info(f"Pause verification: {result}")
            return result.get('paused', False)
        except Exception as e:
            logger.debug(f"Pause verification failed: {e}")
            return False

    async def _click_pause_button(self) -> bool:
        """Click the pause button in the live tracking widget.

        The pause button contains an SVG with aria-label="Icon-pause".
        """
        # Strategy 1: SVG aria-label (most reliable)
        try:
            btn = self.page.locator('button:has(svg[aria-label="Icon-pause"])')
            if await btn.count() > 0:
                await btn.first.click()
                logger.info("Clicked pause button via svg[aria-label=Icon-pause]")
                return True
        except Exception as e:
            logger.debug(f"SVG Icon-pause selector failed: {e}")

        # Strategy 2: Find control stack (MuiStack with 2+ icon buttons in header)
        try:
            stacks = self.page.locator('[class*="MuiStack-root"]')
            count = await stacks.count()
            for i in range(count):
                stack = stacks.nth(i)
                buttons = stack.locator('button.MuiButtonBase-root.MuiIconButton-root')
                btn_count = await buttons.count()
                if btn_count >= 2:
                    box = await stack.bounding_box()
                    if box and box['x'] > 400 and box['y'] < 120:
                        await buttons.nth(1).click()
                        logger.info(f"Clicked pause button (2nd in control stack at x={box['x']}, y={box['y']})")
                        return True
        except Exception as e:
            logger.debug(f"MuiStack control strategy failed: {e}")

        # Strategy 3: aria-label based
        for name in ["Pausa", "Pause", "Pausar"]:
            try:
                btn = self.page.get_by_role("button", name=name)
                if await btn.count() > 0:
                    await btn.click()
                    logger.info(f"Clicked pause button via aria-label: {name}")
                    return True
            except:
                pass

        logger.error("All pause button strategies failed")
        return False

    async def stop_live_tracking(self) -> dict:
        """Stop live time tracking."""
        try:
            self._clear_debug_steps()

            if not await self.start(headless=self.headless):
                return {"status": "error", "message": "No se pudo iniciar el navegador"}

            if not self.is_session_valid() or not await self.check_session():
                await self.stop()
                return {"status": "session_expired", "message": "Sesión expirada"}

            await self._async_debug_screenshot("Navegador abierto", "start")

            # Navigate to time-tracking (where the controls live)
            await self.page.goto(
                "https://app.holded.com/myzone/time-tracking",
                wait_until='domcontentloaded',
                timeout=60000
            )
            await asyncio.sleep(8)

            await self._async_debug_screenshot("En time-tracking", "navigate")

            await self._close_intercom_panel()
            await self._async_debug_screenshot("Intercom cerrado", "close_intercom")

            await self._async_debug_screenshot("Antes de Stop", "before_stop")
            clicked = await self._click_stop_button()

            await asyncio.sleep(3)

            # Handle "Sí, he terminado" confirmation dialog
            try:
                confirm_btn = self.page.get_by_role("button", name="Sí, he terminado")
                if await confirm_btn.count() > 0:
                    await confirm_btn.click()
                    await asyncio.sleep(2)
                    logger.info("Clicked 'Sí, he terminado' confirmation")
            except:
                pass

            await self._async_debug_screenshot("Despues de Stop", "after_stop")

            if clicked:
                return {"status": "success", "message": "Fichaje finalizado"}
            else:
                await self.stop()
                return {"status": "error", "message": "No se encontró el botón de stop"}

        except Exception as e:
            logger.error(f"Failed to stop live tracking: {e}")
            return {"status": "error", "message": str(e)}
        finally:
            await self.stop()

    async def _click_stop_button(self) -> bool:
        """Click the stop button in the live tracking widget.

        The stop button contains an SVG with aria-label="Icon-stop".
        Selector: button:has(svg[aria-label="Icon-stop"])
        """
        # Strategy 1: SVG aria-label (most reliable)
        try:
            btn = self.page.locator('button:has(svg[aria-label="Icon-stop"])')
            if await btn.count() > 0:
                await btn.first.click()
                logger.info("Clicked stop button via svg[aria-label=Icon-stop]")
                return True
        except Exception as e:
            logger.debug(f"SVG Icon-stop selector failed: {e}")

        # Strategy 2: Find the control stack (MuiStack with 2+ icon buttons)
        try:
            stacks = self.page.locator('[class*="MuiStack-root"]')
            count = await stacks.count()
            for i in range(count):
                stack = stacks.nth(i)
                buttons = stack.locator('button.MuiButtonBase-root.MuiIconButton-root')
                btn_count = await buttons.count()
                if btn_count >= 2:
                    box = await stack.bounding_box()
                    if box and box['x'] > 400 and box['y'] < 120:
                        await buttons.first.click()
                        logger.info(f"Clicked stop button (1st in control stack at x={box['x']}, y={box['y']})")
                        return True
        except Exception as e:
            logger.debug(f"MuiStack control strategy failed: {e}")

        # Strategy 3: aria-label based
        for name in ["Detener", "Stop", "Parar", "Finalizar", "Terminar"]:
            try:
                btn = self.page.get_by_role("button", name=name)
                if await btn.count() > 0:
                    await btn.click()
                    logger.info(f"Clicked stop button via aria-label: {name}")
                    return True
            except:
                pass

        logger.error("All stop button strategies failed")
        return False

    # ============================================================
    # MANUAL FICHAJE - Using exact selectors from recorded script
    # ============================================================

    async def fichar_manual(
        self,
        work_blocks: list,
        target_date: Optional[date] = None,
        location: Optional[str] = None
    ) -> dict:
        """
        Manual fichaje: fills the 'Añadir fichaje' form in Holded.
        Uses exact selectors from recorded script.
        """
        try:
            self._clear_debug_steps()

            if target_date is None:
                target_date = date.today()

            if not work_blocks:
                return {"status": "error", "message": "No hay bloques de trabajo configurados"}

            if not await self.start(headless=self.headless):
                return {"status": "error", "message": "No se pudo iniciar el navegador"}

            await self._async_debug_screenshot("Navegador abierto", "start")

            # Check session
            if not self.is_session_valid() or not await self.check_session():
                await self.stop()
                return {"status": "session_expired", "message": "Sesión expirada. Inicia sesión manualmente primero."}

            await self._async_debug_screenshot("Sesion verificada", "check_session")

            # Navigate to Control horario: getByRole('button', { name: 'Control horario' })
            try:
                control_btn = self.page.get_by_role("button", name="Control horario")
                await control_btn.click()
                await asyncio.sleep(3)
            except:
                if not await self.navigate_to_time_control():
                    await self.stop()
                    return {"status": "error", "message": "No se pudo navegar a Control horario"}

            await self._async_debug_screenshot("En Control horario", "navigate")

            await self._close_intercom_panel()
            await self._async_debug_screenshot("Intercom cerrado", "close_intercom")

            # Click "Añadir fichaje": getByRole('button', { name: 'Añadir fichaje' })
            try:
                add_btn = self.page.get_by_role("button", name="Añadir fichaje")
                await add_btn.click()
                await asyncio.sleep(2)
            except Exception as e:
                await self.stop()
                return {"status": "error", "message": f"No se pudo abrir el formulario de fichaje: {e}"}

            await self._async_debug_screenshot("Formulario abierto", "open_form")

            # Set date: use spinbuttons for Day and Month
            await self._set_date_manual(target_date)
            await asyncio.sleep(1)

            # Set location (default to "ARCO C.B." if not specified)
            fichaje_location = location or "ARCO C.B."
            await self._set_location_manual(fichaje_location)
            await asyncio.sleep(1)

            # Build timeline from work blocks (each block has a type: Trabajado or Pausa)
            timeline = []
            for block in work_blocks:
                entry = block.get("entry", "")[:5]
                exit_t = block.get("exit", "")[:5]
                block_type = block.get("type", "Trabajado")
                timeline.append({"type": block_type, "entry": entry, "exit": exit_t})

            # Fill the rows using recorded script selectors
            await self._fill_fichaje_rows_manual(timeline)
            await asyncio.sleep(1)

            await self._async_debug_screenshot("Formulario rellenado", "fill_form")

            # Click Aceptar: getByRole('button', { name: 'Aceptar' })
            try:
                accept_btn = self.page.get_by_role("button", name="Aceptar")
                await accept_btn.click()
                await asyncio.sleep(4)
            except:
                logger.warning("Could not find Aceptar button")

            await self._async_debug_screenshot("Despues de Aceptar", "after_accept")

            # Take screenshot for debugging
            await self.page.screenshot(path="data/after_manual_fichaje.png")

            # Check for Holded error messages (toast/snackbar notifications)
            holded_error = await self._detect_holded_error()
            if holded_error:
                logger.warning(f"Holded error after manual fichaje: {holded_error}")
                await self.stop()
                return {"status": "error", "message": f"Holded: {holded_error}"}

            logger.info(f"Manual fichaje completed for {target_date} with {len(work_blocks)} blocks")
            return {"status": "success", "message": f"Fichaje manual registrado para {target_date}"}

        except Exception as e:
            logger.error(f"Manual fichaje failed: {e}")
            return {"status": "error", "message": str(e)}
        finally:
            await self.stop()

    # ============================================================
    # MODIFY FICHAJE - Edit existing fichaje in Holded
    # ============================================================

    async def modificar_fichaje(
        self,
        target_date: date,
        work_blocks: list,
        location: Optional[str] = None
    ) -> dict:
        """
        Modify an existing fichaje in Holded.
        Navigates to Control horario, clicks on the date entry,
        clicks 'Editar fichajes', modifies the form, and saves.

        Args:
            target_date: The date of the fichaje to modify
            work_blocks: List of {"entry": "HH:MM", "exit": "HH:MM", "type": "Trabajado"|"Pausa"}
            location: Optional location to set
        """
        try:
            if not work_blocks:
                return {"status": "error", "message": "No hay bloques de trabajo configurados"}

            if not await self.start(headless=self.headless):
                return {"status": "error", "message": "No se pudo iniciar el navegador"}

            if not self.is_session_valid() or not await self.check_session():
                await self.stop()
                return {"status": "session_expired", "message": "Sesión expirada. Inicia sesión manualmente primero."}

            # Navigate to Control horario
            try:
                control_btn = self.page.get_by_role("button", name="Control horario")
                await control_btn.click()
                await asyncio.sleep(3)
            except:
                if not await self.navigate_to_time_control():
                    await self.stop()
                    return {"status": "error", "message": "No se pudo navegar a Control horario"}

            await self.page.screenshot(path="data/before_modificar_fichaje.png")

            # Click on the target date entry in the fichaje list
            # Try multiple strategies to find the correct entry
            clicked_entry = await self._click_fichaje_entry(target_date)
            if not clicked_entry:
                await self.stop()
                return {"status": "error", "message": f"No se encontró el fichaje del {target_date}"}

            await asyncio.sleep(1)

            # Click "Editar fichajes" button
            try:
                edit_btn = self.page.get_by_role("button", name="Editar fichajes")
                if await edit_btn.count() > 0:
                    await edit_btn.click()
                    await asyncio.sleep(2)
                    logger.info("Clicked 'Editar fichajes' button")
                else:
                    # Fallback: try text selector
                    edit_btn = await self.page.query_selector('button:has-text("Editar fichajes")')
                    if edit_btn:
                        await edit_btn.click()
                        await asyncio.sleep(2)
                    else:
                        await self.stop()
                        return {"status": "error", "message": "No se encontró el botón 'Editar fichajes'"}
            except Exception as e:
                await self.stop()
                return {"status": "error", "message": f"No se pudo abrir el formulario de edición: {e}"}

            # Set location if provided
            if location:
                await self._set_edit_location(location)
                await asyncio.sleep(1)

            # Build timeline from work_blocks
            timeline = []
            for i, block in enumerate(work_blocks):
                block_type = block.get("type", "Trabajado")
                entry = block.get("entry", "")[:5]
                exit_t = block.get("exit", "")[:5]
                timeline.append({"type": block_type, "entry": entry, "exit": exit_t})

            # Fill the edit form rows
            await self._fill_edit_form_rows(timeline)
            await asyncio.sleep(1)

            # Click "Guardar" to save changes
            try:
                save_btn = self.page.get_by_role("button", name="Guardar")
                if await save_btn.count() > 0:
                    await save_btn.click()
                    await asyncio.sleep(2)
                    # Click again if there's a confirmation
                    try:
                        save_btn2 = self.page.get_by_role("button", name="Guardar")
                        if await save_btn2.count() > 0:
                            await save_btn2.click()
                            await asyncio.sleep(2)
                    except:
                        pass
                    logger.info("Clicked 'Guardar' button")
            except:
                logger.warning("Could not find Guardar button")

            await self.page.screenshot(path="data/after_modificar_fichaje.png")

            # Check for Holded errors
            holded_error = await self._detect_holded_error()
            if holded_error:
                logger.warning(f"Holded error after modify fichaje: {holded_error}")
                await self.stop()
                return {"status": "error", "message": f"Holded: {holded_error}"}

            logger.info(f"Modify fichaje completed for {target_date}")
            return {"status": "success", "message": f"Fichaje modificado para {target_date}"}

        except Exception as e:
            logger.error(f"Modify fichaje failed: {e}")
            return {"status": "error", "message": str(e)}
        finally:
            await self.stop()

    async def _click_fichaje_entry(self, target_date: date) -> bool:
        """Click on a specific fichaje entry in the Control horario page."""
        try:
            # Strategy 1: Look for date text (e.g., "2 jul" or "2 de julio")
            date_str = target_date.strftime("%-d")
            month_names = {
                1: "enero", 2: "febrero", 3: "marzo", 4: "abril",
                5: "mayo", 6: "junio", 7: "julio", 8: "agosto",
                9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre"
            }
            month_name = month_names.get(target_date.month, "")

            # Try various date text formats
            date_patterns = [
                f"{date_str} {month_name[:3]}",
                f"{date_str} de {month_name}",
                f"{target_date.strftime('%d/%m')}",
                f"{target_date.strftime('%d-%m')}",
                str(target_date.day),
            ]

            for pattern in date_patterns:
                try:
                    elements = self.page.get_by_text(pattern, exact=False)
                    count = await elements.count()
                    if count > 0:
                        # Click the first matching element (the date entry)
                        await elements.first.click()
                        logger.info(f"Clicked fichaje entry with pattern: {pattern}")
                        return True
                except:
                    continue

            # Strategy 2: Try clicking on any "Pendiente" or status text near the date
            try:
                pending = self.page.get_by_text("Pendiente")
                if await pending.count() > 0:
                    await pending.first.click()
                    logger.info("Clicked 'Pendiente' entry as fallback")
                    return True
            except:
                pass

            logger.warning(f"Could not find fichaje entry for {target_date}")
            return False

        except Exception as e:
            logger.error(f"Failed to click fichaje entry: {e}")
            return False

    async def _set_edit_location(self, location: str) -> bool:
        """Set location in the edit form using combobox."""
        try:
            # Try combobox selector (from recorded script)
            combobox = self.page.get_by_role("combobox", name="Ubicación")
            if await combobox.count() > 0:
                await combobox.click()
                await asyncio.sleep(0.5)

                # Select location from dropdown
                location_option = await self.page.query_selector(f'[role="option"]:has-text("{location}")')
                if not location_option:
                    location_option = await self.page.query_selector(f'li:has-text("{location}")')
                if not location_option:
                    location_option = self.page.get_by_text(location, exact=True).first

                if location_option:
                    await location_option.click()
                    await asyncio.sleep(0.5)
                    logger.info(f"Set edit location: {location}")
                    return True

            # Fallback: try the same approach as manual fichaje
            return await self._set_location_manual(location)

        except Exception as e:
            logger.error(f"Failed to set edit location: {e}")
            return False

    async def _fill_edit_form_rows(self, timeline: list) -> bool:
        """Fill rows in the edit form. Handles clearing existing rows first."""
        try:
            # First, check if there are existing rows and clear them
            # The edit form may have pre-filled rows from the existing fichaje
            existing_rows = await self.page.query_selector_all('[role="button"]:has-text("Trabajado"), [role="button"]:has-text("Pausa")')
            logger.info(f"Found {len(existing_rows)} existing type buttons in edit form")

            # Fill/modify each row in the timeline
            for i, item in enumerate(timeline):
                row_type = item["type"]
                entry = item["entry"]
                exit_t = item["exit"]

                # If we have more rows than timeline items, we might need to remove extras
                # For now, we'll just fill what we have

                # Add a new row if needed (for rows beyond the first)
                if i > 0:
                    try:
                        add_franja_btn = self.page.get_by_role("button", name="Añadir franja")
                        if await add_franja_btn.count() > 0:
                            await add_franja_btn.click()
                            await asyncio.sleep(0.5)
                    except:
                        pass

                # Set the row type
                await self._set_edit_row_type(i, row_type)
                await asyncio.sleep(0.3)

                # Fill time inputs for this row
                await self._fill_edit_row_times(i, entry, exit_t)
                await asyncio.sleep(0.3)

            return True
        except Exception as e:
            logger.error(f"Failed to fill edit form rows: {e}")
            return False

    async def _set_edit_row_type(self, row_index: int, row_type: str) -> bool:
        """Set the type for a row in the edit form."""
        try:
            # Find type buttons - use generic selector
            type_buttons = self.page.locator('[class*="row"]').get_by_role("button")
            count = await type_buttons.count()

            if row_index < count:
                btn = type_buttons.nth(row_index)
                await btn.click()
                await asyncio.sleep(0.3)

                # Select from menu
                if row_type == "Pausa":
                    option = self.page.get_by_role("menuitem", name="Pausa")
                else:
                    option = self.page.get_by_role("menuitem", name="Trabajado")

                if await option.count() > 0:
                    await option.click()
                    await asyncio.sleep(0.3)
                    return True

            return False
        except Exception as e:
            logger.error(f"Failed to set edit row type: {e}")
            return False

    async def _fill_edit_row_times(self, row_index: int, entry: str, exit_t: str) -> bool:
        """Fill time inputs for a row in the edit form."""
        try:
            # Find all time inputs (each row has entry + exit)
            time_inputs = self.page.get_by_role("textbox", name=":00")
            count = await time_inputs.count()

            # Row N has inputs at index N*2 and N*2+1
            entry_idx = row_index * 2
            exit_idx = row_index * 2 + 1

            if exit_idx < count:
                # Fill entry time
                entry_input = time_inputs.nth(entry_idx)
                await entry_input.click()
                await entry_input.fill(entry)
                await entry_input.press("Tab")
                await asyncio.sleep(0.2)

                # Fill exit time
                exit_input = time_inputs.nth(exit_idx)
                await exit_input.click()
                await exit_input.fill(exit_t)
                await exit_input.press("Tab")
                await asyncio.sleep(0.2)

                return True

            return False
        except Exception as e:
            logger.error(f"Failed to fill edit row times: {e}")
            return False

    async def _set_date_manual(self, target_date: date) -> bool:
        """Set date range using spinbuttons, same approach as recorded script.
        
        From holded-fichaje-manual.ts:
          getByRole('spinbutton', { name: 'Day' }).first().click()
          getByRole('spinbutton', { name: 'Day' }).first().fill(day)
          getByRole('spinbutton', { name: 'Month' }).first().fill(month)
          For end date: click on current day text, then fill day and month.
        """
        try:
            day = str(target_date.day)
            month = str(target_date.month)

            # Start date: click day, fill day, fill month
            day_btn = self.page.get_by_role("spinbutton", name="Day")
            if await day_btn.count() > 0:
                await day_btn.first.click()
                await asyncio.sleep(0.2)
                await day_btn.first.fill(day)
                logger.info(f"Set start day: {day}")

            month_btn = self.page.get_by_role("spinbutton", name="Month")
            if await month_btn.count() > 0:
                await month_btn.first.fill(month)
                await asyncio.sleep(0.2)
                logger.info(f"Set start month: {month}")

            # End date: click on the second day section, fill day and month
            if await day_btn.count() > 1:
                await day_btn.nth(1).click()
                await asyncio.sleep(0.2)
                await day_btn.nth(1).fill(day)
                logger.info(f"Set end day: {day}")

            if await month_btn.count() > 1:
                await month_btn.nth(1).fill(month)
                await asyncio.sleep(0.2)
                logger.info(f"Set end month: {month}")

            await asyncio.sleep(0.5)
            logger.info(f"Date range set to {target_date}")
            return True

        except Exception as e:
            logger.error(f"Failed to set date: {e}")
            return False

    async def _set_location_manual(self, location: str) -> bool:
        """Set location in the Holded fichaje form.
        The form has multiple comboboxes (date, location). We need to find 
        the one showing 'Sin definir' for the location.
        """
        try:
            # The location dropdown shows "Sin definir" by default.
            # Find ALL comboboxes and identify the one for location.
            comboboxes = self.page.locator('[role="combobox"]')
            count = await comboboxes.count()
            logger.info(f"Found {count} comboboxes in the form")

            location_combobox = None
            for i in range(count):
                cb = comboboxes.nth(i)
                try:
                    text = await cb.inner_text(timeout=2000)
                    logger.info(f"  Combobox {i}: '{text}'")
                    if "Sin definir" in text:
                        location_combobox = cb
                        break
                except:
                    continue

            if not location_combobox:
                logger.warning("Could not find location combobox (Sin definir)")
                return False

            await location_combobox.click()
            await asyncio.sleep(1)

            # Now look for the location option in the opened dropdown
            # Try listbox role first
            try:
                listbox = self.page.locator('[role="listbox"]')
                if await listbox.count() > 0:
                    option = listbox.get_by_text(location, exact=True)
                    if await option.count() > 0:
                        await option.first.click()
                        logger.info(f"Selected '{location}' from listbox")
                        await asyncio.sleep(0.5)
                        return True
            except:
                pass

            # Try option role
            try:
                option = self.page.locator('[role="option"]').get_by_text(location, exact=True)
                if await option.count() > 0:
                    await option.first.click()
                    logger.info(f"Selected '{location}' from option role")
                    await asyncio.sleep(0.5)
                    return True
            except:
                pass

            # Fallback: any visible element with the location text
            try:
                option = self.page.get_by_text(location, exact=True)
                if await option.count() > 0:
                    await option.first.click()
                    logger.info(f"Selected '{location}' via text")
                    await asyncio.sleep(0.5)
                    return True
            except:
                pass

            await self.page.keyboard.press("Escape")
            logger.warning(f"Could not find '{location}' option in dropdown")
            return False

        except Exception as e:
            logger.error(f"Failed to set location: {e}")
            try:
                await self.page.keyboard.press("Escape")
            except:
                pass
            return False

    async def _fill_fichaje_rows_manual(self, timeline: list) -> bool:
        """Fill fichaje rows using recorded script selectors."""
        try:
            for i, item in enumerate(timeline):
                row_type = item["type"]
                entry = item["entry"]
                exit_t = item["exit"]

                if i > 0:
                    # Click "Añadir franja" to add a new row
                    try:
                        add_franja_btn = self.page.get_by_role("button", name="Añadir franja")
                        await add_franja_btn.click()
                        await asyncio.sleep(0.5)
                    except:
                        add_franja_btn = await self.page.query_selector('button:has-text("Añadir franja")')
                        if add_franja_btn:
                            await add_franja_btn.click()
                            await asyncio.sleep(0.5)

                # Set the row type if it's not Trabajado (default)
                if row_type == "Pausa":
                    await self._set_row_type_pausa_safe(i)

                # Fill time inputs for this row
                await self._fill_row_times_manual(i, entry, exit_t)
                await asyncio.sleep(0.3)

            return True
        except Exception as e:
            logger.error(f"Failed to fill fichaje rows: {e}")
            return False

    async def _set_row_type_pausa_safe(self, row_index: int) -> bool:
        """Try to set a row to 'Pausa' type. Non-destructive: if it fails, logs and continues."""
        try:
            # Find buttons that contain "Trabajado" text (the type selector)
            trabajado_btns = self.page.get_by_role("button", name="Trabajado")
            count = await trabajado_btns.count()
            logger.info(f"Found {count} 'Trabajado' buttons, row_index={row_index}")

            if row_index < count:
                btn = trabajado_btns.nth(row_index)
                await btn.click()
                await asyncio.sleep(0.5)

                # Take debug screenshot of the dropdown
                await self._async_debug_screenshot(f"Dropdown tipo fila {row_index}", "type_dropdown")

                # Try to find and click "Pausa" in any dropdown/menu
                pausa = self.page.get_by_text("Pausa", exact=True)
                if await pausa.count() > 0:
                    await pausa.first.click()
                    logger.info(f"Set row {row_index} to Pausa")
                    await asyncio.sleep(0.3)
                    return True

                # If Pausa not found, close menu and continue
                await self.page.keyboard.press("Escape")
                logger.warning(f"Pausa option not found for row {row_index}, keeping Trabajado")

            return False
        except Exception as e:
            logger.warning(f"Could not set row type to Pausa: {e}")
            try:
                await self.page.keyboard.press("Escape")
            except:
                pass
            return False

    async def _fill_row_times_manual(self, row_index: int, entry: str, exit_t: str) -> bool:
        """Fill time inputs for a specific row."""
        try:
            # Find all time inputs (each row has entry + exit)
            time_inputs = self.page.get_by_role("textbox", name=":00")
            count = await time_inputs.count()

            # Row N has inputs at index N*2 and N*2+1
            entry_idx = row_index * 2
            exit_idx = row_index * 2 + 1

            if exit_idx < count:
                # Fill entry time
                entry_input = time_inputs.nth(entry_idx)
                await entry_input.click()
                await entry_input.fill(entry)
                await entry_input.press("Tab")
                await asyncio.sleep(0.2)

                # Fill exit time
                exit_input = time_inputs.nth(exit_idx)
                await exit_input.click()
                await exit_input.fill(exit_t)
                await exit_input.press("Tab")
                await asyncio.sleep(0.2)

                return True

            return False
        except Exception as e:
            logger.error(f"Failed to fill row times: {e}")
            return False

    # ============================================================
    # SESSION CHECK
    # ============================================================

    async def check_session(self) -> bool:
        """Check if current session is still valid."""
        try:
            if not self.page:
                return False
            await self.page.goto("https://app.holded.com/myzone", wait_until='domcontentloaded', timeout=60000)
            await asyncio.sleep(5)
            current_url = self.page.url
            if '/login' in current_url:
                return False
            return 'myzone' in current_url or 'dashboard' in current_url
        except:
            return False

    async def fichar(
        self,
        email: str,
        password: str,
        entry_time: time,
        exit_time: time,
        target_date: Optional[date] = None
    ) -> dict:
        """Simple fichaje with single entry/exit time."""
        try:
            work_blocks = [{"entry": entry_time.strftime("%H:%M"), "exit": exit_time.strftime("%H:%M")}]
            result = await self.fichar_manual(work_blocks=work_blocks, target_date=target_date)
            return result
        except Exception as e:
            return {"status": "error", "message": str(e)}


fichador = HoldedFichador()
