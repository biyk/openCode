import subprocess
import requests
import time
from typing import Optional
import pyautogui
import pyperclip

from lib.providers import BaseLLMClient


class BraveClient(BaseLLMClient):
    """Управление браузером Brave для работы с DeepSeek Chat."""

    def __init__(self, api_key: Optional[str] = None, history_limit: int = 10, debug_port: int = 9222):
        self._debug_port = debug_port
        self._base_url = f"http://localhost:{debug_port}"
        self._browser_pid: Optional[int] = None

    @property
    def name(self) -> str:
        return "Brave"

    def ask(self, text: str) -> Optional[str]:
        """Открывает вкладку DeepSeek и отправляет текст."""
        if self.ensure_deepseek_tab():
            time.sleep(1)
            return self.send_text_to_input(text)

        return None

    def _is_brave_running(self) -> bool:
        """Проверяет, запущен ли Brave с отладочным портом."""
        try:
            response = requests.get(f"{self._base_url}/json/version", timeout=2)
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False

    def _start_brave(self) -> bool:
        """Запускает Brave с удалённой отладкой."""
        try:
            subprocess.Popen(
                ["brave-browser", f"--remote-debugging-port={self._debug_port}", "--no-first-run", "--no-default-browser-check", "--remote-allow-origins=*"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            print(f"[Brave] Браузер запускается...")

            for _ in range(30):
                time.sleep(1)
                if self._is_brave_running():
                    print("[Brave] Браузер готов к работе")
                    return True
            print("[Brave] Браузер не готов к работе (проверьте, что X11 работает)")
            return False
        except FileNotFoundError:
            print("[Brave] brave-browser не найден в PATH")
            return False
        except Exception as e:
            print(f"[Brave] Ошибка запуска: {e}")
            return False

    def _get_tabs(self) -> list:
        """Возвращает список вкладок через CDP."""
        try:
            response = requests.get(f"{self._base_url}/json/list", timeout=5)
            print(f"[Brave] GET /json/list status: {response.status_code}")
            tabs = response.json()
            print(f"[Brave] Найдено вкладок: {len(tabs)}")
            for t in tabs:
                print(f"[Brave]   - {t.get('title', 'No title')}: {t.get('url', 'No URL')}")
            return tabs
        except requests.exceptions.RequestException as e:
            print(f"[Brave] Ошибка получения списка вкладок: {e}")
            return []

    def _find_deepseek_tab(self) -> Optional[dict]:
        """Ищет вкладку с chat.deepseek.com."""
        tabs = self._get_tabs()
        for tab in tabs:
            if "chat.deepseek.com/" in tab.get("url", ""):
                return tab
        return None

    def _switch_to_tab(self, tab_id: str) -> bool:
        """Переключается на вкладку по ID."""
        try:
            requests.post(
                f"{self._base_url}/json/activate/{tab_id}",
                timeout=5
            )
            print(f"[Brave] Переключено на вкладку {tab_id}")
            return True
        except requests.exceptions.RequestException as e:
            print(f"[Brave] Ошибка переключения: {e}")
            return False

    def _open_deepseek(self) -> bool:
        """Открывает новую вкладку с DeepSeek Chat."""
        try:
            print(f"[Brave] Открытие вкладки: PUT {self._base_url}/json/new")
            response = requests.put(
                f"{self._base_url}/json/new",
                json={"url": "https://chat.deepseek.com/"},
                timeout=5
            )
            print(f"[Brave] PUT /json/new status: {response.status_code}")
            print(f"[Brave] POST /json/new response: {response.text[:200]}")
            if response.status_code == 200:
                #TODO ждем загрузки страницы документреди и наличие элемента 
                print("[Brave] Открыта вкладка DeepSeek Chat")
                return True
            return False
        except requests.exceptions.RequestException as e:
            print(f"[Brave] Ошибка открытия вкладки: {e}")
            return False

    def ensure_deepseek_tab(self) -> bool:
        """Проверяет/запускает Brave и открывает вкладку DeepSeek."""
        if self._is_brave_running():
            print("[Brave] Браузер уже запущен")
        else:
            print("[Brave] Браузер не запущен, запускаю...")
            if not self._start_brave():
                return False

        tab = self._find_deepseek_tab()
        if tab:
            print(f"[Brave] Вкладка найдена: {tab.get('title', 'Unknown')}")
            self._switch_to_tab(tab.get("id", ""))
            return True

        print("[Brave] Вкладка не найдена, открываю...")
        if not self._open_deepseek():
            return False
        time.sleep(2)#ждем открытия вкладки
        return True

    def _focus_brave_window(self) -> bool:
        """Активирует окно Brave через wmctrl."""
        try:
            result = subprocess.run(
                ["wmctrl", "-a", "Brave"],
                capture_output=True,
                timeout=5
            )
            return result.returncode == 0
        except FileNotFoundError:
            try:
                subprocess.run(
                    ["xdotool", "search", "--name", "Brave", "windowactivate"],
                    capture_output=True,
                    timeout=5
                )
                return True
            except Exception as e:
                print(f"[Brave] Ошибка фокусировки: {e}")
                return False
        except Exception as e:
            print(f"[Brave] Ошибка фокусировки: {e}")
            return False

    def send_text_to_input(self, text: str) -> bool:
        """Отправляет текст в поле ввода DeepSeek Chat через pyautogui."""
        print("[Brave] send_text_to_input: начало")
        tab = self._find_deepseek_tab()
        if not tab:
            print("[Brave] Вкладка DeepSeek не найдена")
            return False


        time.sleep(1)

        x, y = 100, 650
        pyautogui.click(x, y)
        time.sleep(0.5)

        pyperclip.copy(text)
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(0.3)

        pyautogui.press('enter')
         #TODO ждем когда [...document.querySelectorAll('.ds-markdown')].pop().parentElement.parentElement.querySelectorAll('.ds-flex .ds-flex .ds-icon-button').length > 0
        #TODO отдаем содержимое [...document.querySelectorAll('.ds-markdown')].pop()
        print("[Brave] Текст отправлен")
        return True
