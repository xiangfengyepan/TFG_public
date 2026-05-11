#!/usr/bin/env python3
"""
open_gephi.py  -  Launch Gephi Lite and load graph + layout via UI automation.

Usage:
  py -3 open_gephi.py [options]

Options:
  --gexf PATH        Path to the .gexf file   (default: raw_swe_bench_graph.gexf)
  --session PATH     Path to session JSON     (default: config/session_<layout>.json)
  --layout NAME      Layout name             (default: radial)
  --url URL          Gephi Lite URL          (default: https://lite.gephi.org/v1.0.2/#/)
  --local            Use local dev server at http://localhost:5173/gephi-lite/ (overrides --url)
  --local-port PORT  Port for local dev server (default: 5173)
  --start-server     Auto-start the local Gephi Lite dev server (requires --local)
  --gephi-dir PATH   Path to cloned gephi-lite repo (default: ./gephi-lite)
  --filter NAME      Filter folder name      (e.g. 'repo' → config/filters_repo.json)
  --export           Click Workspace → Export graph file after setup
  --export-path PATH Save exported file to PATH (implies --export; sets browser download dir)
  --no-interaction   Exit automatically after all steps instead of waiting for browser close

Requires: pip install selenium
"""

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait
except ImportError:
    print("Error: selenium is not installed. Run: pip install selenium")
    sys.exit(1)

GEPHI_URL = "https://lite.gephi.org/v1.0.2/#/"
LOCAL_URL_TEMPLATE = "http://localhost:{port}/gephi-lite/"
DEFAULT_LAYOUT = "radial"
DEFAULT_LOCAL_PORT = 5173


# ── Local dev server ──────────────────────────────────────────────────────────


def _server_ready(url: str, timeout: int = 60) -> bool:
    """Poll url until it returns HTTP 200 (or any response), up to timeout seconds."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=2)
            return True
        except Exception:
            time.sleep(1)
    return False


def start_local_server(gephi_dir: Path, port: int) -> subprocess.Popen:
    """Start `npm run start` in gephi_dir; return the Popen handle."""
    if not gephi_dir.exists():
        print(f"Error: gephi-lite directory not found: {gephi_dir}")
        sys.exit(1)
    print(f"  Starting local Gephi Lite dev server (port {port})...")
    proc = subprocess.Popen(
        ["npm", "run", "start"],
        cwd=str(gephi_dir),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        shell=True,
    )
    url = LOCAL_URL_TEMPLATE.format(port=port)
    if not _server_ready(url, timeout=120):
        proc.terminate()
        print(f"Error: dev server did not become ready at {url} within 120 s.")
        sys.exit(1)
    print(f"  Dev server ready at {url}")
    return proc


# ── Helpers ───────────────────────────────────────────────────────────────────


def load_json(path: Path, default):
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    print(f"  [warn] {path} not found, using default.")
    return default


def extract_script(session: dict) -> str:
    """Pull the JS function body from the session JSON script array."""
    try:
        parts = session["layoutsParameters"]["script"]["script"]
        return parts[1] if len(parts) >= 2 else ""
    except (KeyError, IndexError, TypeError):
        return ""


def open_browser(download_dir: str = None):
    """Try Edge → Chrome → Firefox. Configure automatic download dir if given."""
    prefs: dict = {}
    if download_dir:
        Path(download_dir).mkdir(parents=True, exist_ok=True)
        prefs = {
            "download.default_directory": str(Path(download_dir).resolve()),
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
        }
    try:
        opts = webdriver.EdgeOptions()
        opts.add_argument("--start-maximized")
        if prefs:
            opts.add_experimental_option("prefs", prefs)
        return webdriver.Edge(options=opts)
    except Exception:
        pass
    try:
        opts = webdriver.ChromeOptions()
        opts.add_argument("--start-maximized")
        if prefs:
            opts.add_experimental_option("prefs", prefs)
        return webdriver.Chrome(options=opts)
    except Exception:
        pass
    try:
        profile = webdriver.FirefoxProfile()
        if download_dir:
            abs_dir = str(Path(download_dir).resolve())
            profile.set_preference("browser.download.dir", abs_dir)
            profile.set_preference("browser.download.folderList", 2)
            profile.set_preference("browser.download.useDownloadDir", True)
            profile.set_preference(
                "browser.helperApps.neverAsk.saveToDisk",
                "application/gexf+xml,application/xml,text/xml",
            )
        return webdriver.Firefox(firefox_profile=profile)
    except Exception as exc:
        print(f"Error: could not launch Edge, Chrome, or Firefox.\n  {exc}")
        sys.exit(1)


# ── Storage injection ─────────────────────────────────────────────────────────


def load_storage(driver, session_items: dict = None, local_items: dict = None):
    """Inject key-value pairs into sessionStorage and/or localStorage.
    Call this right after the page loads, before React reads storage on init.
    Dicts/lists are automatically JSON-serialised; plain strings are stored as-is.
    """
    for storage, items in (
        ("sessionStorage", session_items or {}),
        ("localStorage", local_items or {}),
    ):
        for key, value in items.items():
            try:
                v = (
                    value
                    if isinstance(value, str)
                    else json.dumps(value, ensure_ascii=False)
                )
                driver.execute_script(
                    f"{storage}.setItem(arguments[0], arguments[1]);", key, v
                )
            except Exception as exc:
                print(f"  [error] {storage}.setItem('{key}'): {exc}")


# ── Download helper ───────────────────────────────────────────────────────────


def _wait_for_download(download_dir: Path, before: set, timeout: int = 30, suffix: str = ".gexf") -> "Path | None":
    """Poll download_dir until a new file with *suffix* appears that was not in *before*."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        candidates = {
            f for f in download_dir.iterdir()
            if f.suffix == suffix
            and not f.name.endswith(".crdownload")
            and not f.name.endswith(".part")
        }
        new_files = candidates - before
        if new_files:
            return max(new_files, key=lambda f: f.stat().st_mtime)
        time.sleep(0.5)
    return None


# ── UI automation steps ───────────────────────────────────────────────────────


def _react_select(driver, wait: WebDriverWait, container_id: str, option_text: str):
    """Open a React Select dropdown by its container id and select the given option."""
    control = wait.until(
        EC.element_to_be_clickable(
            (By.CSS_SELECTOR, f"#{container_id} .react-select__control")
        )
    )
    control.click()
    time.sleep(0.3)
    inp = driver.find_element(By.CSS_SELECTOR, f"#{container_id} input")
    inp.send_keys(option_text)
    time.sleep(0.3)
    option = wait.until(
        EC.element_to_be_clickable(
            (
                By.XPATH,
                f"//div[contains(@class,'react-select__option') and normalize-space(.)='{option_text}']",
            )
        )
    )
    option.click()
    time.sleep(0.2)


def _send_file_to_input(driver, wait: WebDriverWait, gexf_path: Path):
    """Send the GEXF path to the file input, then click the Open button."""
    file_input = wait.until(
        EC.presence_of_element_located((By.CSS_SELECTOR, 'input[type="file"]'))
    )
    driver.execute_script(
        "arguments[0].style.cssText='display:block;visibility:visible;opacity:1;';",
        file_input,
    )
    file_input.send_keys(str(gexf_path))
    time.sleep(0.3)

    # Click the Open button that submits the openForm
    open_btn = wait.until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, 'button[form="openForm"]'))
    )
    open_btn.click()

    # Wait for the success toast notification
    gexf_name = gexf_path.name
    try:
        wait.until(
            lambda d: d.execute_script(
                "var c=document.querySelector('.toasts-container');"
                "return c && c.innerText.includes(arguments[0]);",
                f"{gexf_name} has been successfully loaded",
            )
        )
    except Exception:
        time.sleep(5)


def upload_gexf(driver, wait: WebDriverWait, gexf_path: Path):
    """Upload the GEXF file via the welcome modal or the Workspace dropdown."""

    # ── Path A: welcome modal is open → click "Open a local file" directly ────
    try:
        local_file_btn = WebDriverWait(driver, 4).until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, 'button[title="Open a local file"]')
            )
        )
        local_file_btn.click()
        time.sleep(0.4)
        _send_file_to_input(driver, wait, gexf_path)
        print(f"  GEXF loaded: {gexf_path.name}")
        return
    except Exception:
        pass

    # ── Path B: no welcome modal → use Workspace dropdown ────────────────────
    ws_btns = driver.find_elements(
        By.XPATH,
        "//button[contains(@class,'dropdown-toggle') and normalize-space(.)='Workspace']",
    )
    ws_btn = next((b for b in ws_btns if b.is_displayed()), None)
    if ws_btn is None:
        raise RuntimeError("Cannot find Workspace button or 'Open a local file' entry.")
    ws_btn.click()
    time.sleep(0.4)

    open_item = wait.until(
        EC.element_to_be_clickable(
            (
                By.XPATH,
                "//button[contains(normalize-space(.), 'Open') "
                "and not(contains(@class,'dropdown-toggle'))]",
            )
        )
    )
    open_item.click()
    time.sleep(0.4)

    _send_file_to_input(driver, wait, gexf_path)
    print(f"  GEXF loaded: {gexf_path.name}")


def set_appearance(driver, wait: WebDriverWait):
    """Appearance → Nodes: color = node_type, size = Degree (dynamic)."""

    # Expand Appearance panel in the side menu
    appearance_btn = wait.until(
        EC.element_to_be_clickable(
            (
                By.XPATH,
                "//button[.//span[@class='side-menu-item' and normalize-space(text())='Appearance']]",
            )
        )
    )
    appearance_btn.click()
    time.sleep(0.4)

    # Click Nodes in the nested appearance menu (button, not span, to avoid Metrics heading)
    nodes_btn = wait.until(
        EC.element_to_be_clickable(
            (
                By.XPATH,
                "//ul[contains(@class,'nested-side-menu')]"
                "//button[.//span[normalize-space(text())='Nodes']]",
            )
        )
    )
    nodes_btn.click()
    time.sleep(0.5)

    # Color: set from node_type
    _react_select(driver, wait, "nodes-colorMode", "node_type")

    # Size: set from Degree (dynamic)
    _react_select(driver, wait, "nodes-sizeMode", "Degree (dynamic)")

    # Switch to Edges
    edges_btn = wait.until(
        EC.element_to_be_clickable(
            (
                By.XPATH,
                "//ul[contains(@class,'nested-side-menu')]"
                "//button[.//span[normalize-space(text())='Edges']]",
            )
        )
    )
    edges_btn.click()
    time.sleep(0.4)

    # Color: set from Target nodes
    _react_select(driver, wait, "edges-colorMode", "Target nodes")

    print(
        "  Appearance: nodes color=node_type, size=Degree (dynamic); edges color=Target nodes."
    )


def set_custom_layout(driver, wait: WebDriverWait, session: dict):
    """Write 1.0_session to sessionStorage, then apply the custom layout via UI."""

    driver.execute_script(
        "sessionStorage.setItem(arguments[0], arguments[1]);",
        "1.0_session",
        json.dumps(session, ensure_ascii=False),
    )
    time.sleep(0.2)

    # Expand the Layout panel in the side menu
    layout_btn = wait.until(
        EC.element_to_be_clickable(
            (
                By.XPATH,
                "//button[.//span[@class='side-menu-item' and normalize-space(text())='Layout']]",
            )
        )
    )
    layout_btn.click()
    time.sleep(0.4)

    # Click Custom layout
    custom_btn = wait.until(
        EC.element_to_be_clickable(
            (
                By.XPATH,
                "//button[.//span[normalize-space(text())='Custom layout']]",
            )
        )
    )
    custom_btn.click()
    time.sleep(0.5)

    # Click the Apply button in the sidebar panel (no modal)
    apply_btn = wait.until(
        EC.element_to_be_clickable(
            (By.CSS_SELECTOR, 'button[type="submit"].gl-btn-fill')
        )
    )
    apply_btn.click()
    print("  Custom layout applied.")

    # Close the panel via the X button
    time.sleep(0.3)
    try:
        close_btn = driver.find_element(
            By.CSS_SELECTOR, 'button.gl-btn-close[aria-label="Close"]'
        )
        close_btn.click()
    except Exception:
        pass


def set_layout_quality(driver, wait: WebDriverWait):
    """Layout panel → Layout quality → enable Connected-closeness."""

    # The Layout nested menu stays expanded after set_custom_layout (the X button only
    # closes the panel body, not the accordion). Clicking layout_btn when it's already
    # open would collapse it, hiding "Layout quality". Only open if collapsed.
    layout_expanded = driver.execute_script(
        """
        var spans = document.querySelectorAll('ul.nested-side-menu span.side-menu-item');
        for (var s of spans) {
            if (s.textContent.trim() === 'Layout quality') {
                var rah = s.closest('.rah-static');
                return rah ? rah.getAttribute('aria-hidden') === 'false' : false;
            }
        }
        return false;
    """
    )

    if not layout_expanded:
        layout_btn = wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//button[.//span[@class='side-menu-item' and normalize-space(text())='Layout']]",
                )
            )
        )
        layout_btn.click()
        time.sleep(0.4)

    quality_btn = wait.until(
        EC.element_to_be_clickable(
            (
                By.XPATH,
                "//button[.//span[@class='side-menu-item' and normalize-space(text())='Layout quality']]",
            )
        )
    )
    quality_btn.click()
    time.sleep(0.4)

    checkbox = wait.until(EC.presence_of_element_located((By.ID, "qualityEnabled")))
    if not checkbox.is_selected():
        checkbox.click()
    time.sleep(0.2)
    # Close the panel via the X button
    time.sleep(0.3)
    try:
        close_btn = driver.find_element(
            By.CSS_SELECTOR, 'button.gl-btn-close[aria-label="Close"]'
        )
        close_btn.click()
    except Exception:
        pass

    print("  Layout quality: Connected-closeness enabled.")


def export_graph(driver, wait: WebDriverWait, export_path: Path = None):
    """Workspace → Export graph file. If export_path is given, waits and renames the download."""

    download_dir = export_path.parent if export_path else None
    before: set = set()
    if download_dir and download_dir.exists():
        before = {f for f in download_dir.iterdir() if f.suffix == ".gexf"}

    # Open Workspace dropdown
    ws_btns = driver.find_elements(
        By.XPATH,
        "//button[contains(@class,'dropdown-toggle') and normalize-space(.)='Workspace']",
    )
    ws_btn = next((b for b in ws_btns if b.is_displayed()), None)
    if ws_btn is None:
        print("  [warn] Cannot find Workspace button for export.")
        return
    ws_btn.click()
    time.sleep(0.4)

    export_btn = wait.until(
        EC.element_to_be_clickable(
            (
                By.XPATH,
                "//button[contains(@class,'gl-menu-item') and normalize-space(.)='Export graph file']",
            )
        )
    )
    export_btn.click()
    time.sleep(1)

    # Confirm export modal if one appears (some Gephi Lite versions show one)
    try:
        confirm_btn = WebDriverWait(driver, 3).until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//button[contains(@class,'gl-btn-fill') and "
                    "(normalize-space(.)='Export' or normalize-space(.)='Download')]",
                )
            )
        )
        confirm_btn.click()
        time.sleep(0.5)
    except Exception:
        pass  # no modal — download triggered directly

    if download_dir:
        downloaded = _wait_for_download(download_dir, before)
        if downloaded:
            downloaded.replace(export_path)
            print(f"  Exported: {export_path}")
        else:
            print(f"  [warn] Export timed out, check {download_dir}")
    else:
        print("  Graph exported (check your browser downloads folder).")


def export_png(
    driver,
    wait: WebDriverWait,
    export_path: Path = None,
    width: int = 2480,
    height: int = 3508,
):
    """Workspace → Export image → set dimensions/filename and save as PNG."""

    download_dir = export_path.parent if export_path else None
    before: set = set()
    if download_dir and download_dir.exists():
        before = {f for f in download_dir.iterdir() if f.suffix == ".png"}

    # Open Workspace dropdown
    ws_btns = driver.find_elements(
        By.XPATH,
        "//button[contains(@class,'dropdown-toggle') and normalize-space(.)='Workspace']",
    )
    ws_btn = next((b for b in ws_btns if b.is_displayed()), None)
    if ws_btn is None:
        print("  [warn] Cannot find Workspace button for PNG export.")
        return
    ws_btn.click()
    time.sleep(0.4)

    export_img_btn = wait.until(
        EC.element_to_be_clickable(
            (
                By.XPATH,
                "//button[contains(@class,'gl-menu-item') and normalize-space(.)='Export image']",
            )
        )
    )
    export_img_btn.click()
    time.sleep(0.5)

    # Filename
    if export_path:
        filename_input = wait.until(EC.presence_of_element_located((By.ID, "filename")))
        filename_input.clear()
        filename_input.send_keys(export_path.name)

    # Width and height — the modal's height <input> has id="width" (HTML bug), so
    # select all number inputs within the modal form and address them by position.
    modal = wait.until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "form.modal-content"))
    )
    number_inputs = modal.find_elements(By.CSS_SELECTOR, 'input[type="number"]')

    def _set_number(inp, value: int):
        inp.click()
        inp.clear()
        inp.send_keys(str(value))

    if len(number_inputs) >= 1:
        _set_number(number_inputs[0], width)
    if len(number_inputs) >= 2:
        _set_number(number_inputs[1], height)

    # Click Save
    save_btn = wait.until(
        EC.element_to_be_clickable(
            (By.XPATH, "//button[@type='submit' and @title='Save']")
        )
    )
    save_btn.click()
    time.sleep(1)

    if download_dir:
        downloaded = _wait_for_download(download_dir, before, suffix=".png")
        if downloaded:
            downloaded.replace(export_path)
            print(f"  PNG exported: {export_path}")
        else:
            print(f"  [warn] PNG export timed out, check {download_dir}")
    else:
        print("  PNG exported (check your browser downloads folder).")


# ── Main ──────────────────────────────────────────────────────────────────────


def main():
    here = Path(__file__).parent

    parser = argparse.ArgumentParser(
        description="Open Gephi Lite with graph and layout."
    )
    parser.add_argument(
        "--gexf",
        default=str(here / "raw_swe_bench_graph.gexf"),
        help="Path to the .gexf file",
    )
    parser.add_argument(
        "--session",
        default=None,
        help="Path to session JSON (default: auto from layout name)",
    )
    parser.add_argument(
        "--layout",
        default=DEFAULT_LAYOUT,
        help="Layout name ('radial', 'hierarchical')",
    )
    parser.add_argument("--url", default=GEPHI_URL, help="Gephi Lite URL")
    parser.add_argument(
        "--local",
        action="store_true",
        default=False,
        help="Use local dev server at http://localhost:<port>/gephi-lite/ (overrides --url)",
    )
    parser.add_argument(
        "--local-port",
        type=int,
        default=DEFAULT_LOCAL_PORT,
        metavar="PORT",
        help=f"Port for local dev server (default: {DEFAULT_LOCAL_PORT})",
    )
    parser.add_argument(
        "--start-server",
        action="store_true",
        default=False,
        help="Auto-start the local Gephi Lite dev server (requires --local)",
    )
    parser.add_argument(
        "--gephi-dir",
        default=None,
        metavar="PATH",
        help="Path to cloned gephi-lite repo (default: <script-dir>/gephi-lite)",
    )
    parser.add_argument(
        "--filter",
        default=None,
        help="Filter name (subfolder in filters/), e.g. 'repo' → config/filters_repo.json",
    )
    parser.add_argument(
        "--export",
        action="store_true",
        default=False,
        help="Export the graph file via Workspace → Export graph file after setup",
    )
    parser.add_argument(
        "--export-path",
        default=None,
        metavar="PATH",
        help="Save exported GEXF to PATH (implies --export; sets browser download dir)",
    )
    parser.add_argument(
        "--export-png",
        action="store_true",
        default=False,
        help="Export a PNG snapshot via Workspace → Export image after setup",
    )
    parser.add_argument(
        "--export-png-path",
        default=None,
        metavar="PATH",
        help="Save exported PNG to PATH (implies --export-png; sets browser download dir)",
    )
    parser.add_argument(
        "--png-width",
        type=int,
        default=2480,
        metavar="PX",
        help="PNG export width in pixels (default: 2480)",
    )
    parser.add_argument(
        "--png-height",
        type=int,
        default=3508,
        metavar="PX",
        help="PNG export height in pixels (default: 3508)",
    )
    parser.add_argument(
        "--png-layout",
        default=None,
        help="Layout to apply before PNG export (default: same as --layout). "
             "If different from --layout, re-applies the layout in the same browser session.",
    )
    parser.add_argument(
        "--no-interaction",
        action="store_true",
        default=False,
        help="Exit automatically after all steps instead of waiting for browser close",
    )
    args = parser.parse_args()

    # Resolve Gephi Lite URL
    gephi_url = args.url
    if args.local:
        gephi_url = LOCAL_URL_TEMPLATE.format(port=args.local_port)

    # Optionally auto-start the local dev server
    dev_server_proc = None
    if args.start_server:
        if not args.local:
            print("Warning: --start-server has no effect without --local; ignoring.")
        else:
            gephi_dir = Path(args.gephi_dir) if args.gephi_dir else here / "gephi-lite"
            dev_server_proc = start_local_server(gephi_dir, args.local_port)

    gexf_path = Path(args.gexf).resolve()
    if not gexf_path.exists():
        print(f"Error: GEXF file not found: {gexf_path}")
        sys.exit(1)

    # Resolve session file
    if args.session is not None:
        session_path = Path(args.session)
    else:
        session_path = here / "config" / f"session_{args.layout}.json"
        if not session_path.exists():
            print(
                f"  [warn] {session_path.name} not found, falling back to session.json"
            )
            session_path = here / "config" / "session.json"

    session = load_json(session_path, {})
    if not extract_script(session):
        print(f"  [warn] No layout script found in {session_path.name}.")

    # Resolve filter file
    filters_data = {}
    if args.filter is not None:
        filter_path = here / "config" / f"filters_{args.filter}.json"
        filters_data = load_json(filter_path, {})
        if filters_data:
            print(f"  Filter  : {filter_path.name}")

    export_path = Path(args.export_path).resolve() if args.export_path else None
    do_export = args.export or export_path is not None

    export_png_path = Path(args.export_png_path).resolve() if args.export_png_path else None
    do_export_png = args.export_png or export_png_path is not None

    # Browser download dir: prefer the PNG path's parent (first export needing a rename),
    # fall back to the GEXF path's parent.
    download_dir = None
    if export_png_path:
        download_dir = str(export_png_path.parent)
    elif export_path:
        download_dir = str(export_path.parent)

    print(f"Opening Gephi Lite (layout={args.layout}, url={gephi_url})...")
    driver = open_browser(download_dir=download_dir)

    try:
        driver.get(gephi_url)
        wait = WebDriverWait(driver, 3)
        wait.until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )

        # Inject session before React reads it, then refresh so layout initialises with our values.
        # Filters are NOT injected here: Gephi Lite resets 1.0_filters when a graph is loaded,
        # so we inject them after upload_gexf instead (mirrors the manual paste-then-use flow).
        load_storage(driver, session_items={"1.0_session": session})
        driver.refresh()
        wait.until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        time.sleep(2)

        upload_gexf(driver, wait, gexf_path)

        # Inject filters after GEXF load so the key is not wiped by the graph-load reset,
        # then reload immediately so Gephi Lite activates the filter before we apply the layout.
        # This ensures the layout runs on the already-filtered (smaller) graph.
        if filters_data:
            load_storage(driver, session_items={"1.0_filters": filters_data})
            driver.refresh()
            wait.until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            time.sleep(2)

        set_appearance(driver, wait)

        if session:
            set_custom_layout(driver, wait, session)

        set_layout_quality(driver, wait)

        if do_export:
            export_graph(driver, wait, export_path)

        if do_export_png:
            # Re-apply layout if --png-layout differs from --layout
            png_layout_name = args.png_layout or args.layout
            if png_layout_name != args.layout:
                png_session_path = here / "config" / f"session_{png_layout_name}.json"
                if not png_session_path.exists():
                    print(f"  [warn] {png_session_path.name} not found, keeping current layout.")
                else:
                    png_session = load_json(png_session_path, {})
                    if png_session:
                        print(f"  Switching to layout '{png_layout_name}' for PNG export...")
                        set_custom_layout(driver, wait, png_session)
                        time.sleep(1)
            export_png(driver, wait, export_png_path, args.png_width, args.png_height)

        print(f"  GEXF   : {gexf_path.name}")
        print(f"  Session: {session_path.name}")
        if filters_data:
            print(f"  Filter : filters_{args.filter}.json")

        if not args.no_interaction:
            print("  Press Ctrl+C or close the browser to exit.")
            while True:
                try:
                    _ = driver.window_handles
                    time.sleep(2)
                except Exception:
                    break
    except KeyboardInterrupt:
        pass
    finally:
        try:
            driver.quit()
        except Exception:
            pass
        if dev_server_proc is not None:
            dev_server_proc.terminate()
            print("  Dev server stopped.")


if __name__ == "__main__":
    main()
