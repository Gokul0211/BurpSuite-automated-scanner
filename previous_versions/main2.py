#!/usr/bin/env python3
"""
Burp Suite Pro Multi-Target Automation Scanner
Using Burp's Official Built-in REST API + GUI Auto-Unpause + Smart Logic + Pretty JSON
Integrations: Pause Timeout Handler, Aggressive Resume Clicker, No Retry on Execution Timeout
"""

import os
import sys
import time
import json
import shutil
import logging
import requests
import subprocess
import signal
import pyautogui  # For auto-clicking
from pathlib import Path
from typing import Optional, Dict, List, Union, Tuple
from dataclasses import dataclass
from datetime import datetime

# ============================================================================
# PROJECT PATHS
# ============================================================================

PROJECT_ROOT = Path(__file__).parent.resolve()
CONFIG_DIR = PROJECT_ROOT / "config"
INPUT_DIR = PROJECT_ROOT / "input"
LOGS_DIR = PROJECT_ROOT / "logs"
OUTPUT_DIR = PROJECT_ROOT / "output"

# Burp JAR Version 2025.11.6
BURP_PRO_JAR = PROJECT_ROOT / "burpsuite_pro_v2025.11.6.jar"
TARGETS_FILE = INPUT_DIR / "websites.txt"
SCAN_TEMPLATE = CONFIG_DIR / "scan_template.json"
BURP_CONFIG = CONFIG_DIR / "burp_config.json"
GOLDEN_PROJECT = CONFIG_DIR / "golden.burp"
RESUME_BUTTON_IMG = CONFIG_DIR / "resume.png"


# ============================================================================
# CONFIGURATION
# ============================================================================

@dataclass
class BurpConfig:
    """Burp Suite configuration"""
    burp_jar_path: Path = BURP_PRO_JAR
    java_path: str = "java"
    jvm_max_memory: str = "4g"
    jvm_min_memory: str = "2g"
    api_host: str = "127.0.0.1"
    api_port: int = 8090
    api_key: str = ""     # No API key required for local automation
    temp_projects_dir: Path = OUTPUT_DIR / "burp_projects_temp"
    scan_results_dir: Path = OUTPUT_DIR
    
    # Integration Parameters
    pause_timeout: int = 120          # seconds to wait after clicking resume before aborting
    pause_check_interval: int = 15    # how often to check status
    max_resume_attempts: int = 8      # max check cycles before giving up
    
    @property
    def api_base_url(self) -> str:
        return f"http://{self.api_host}:{self.api_port}"
    
    def validate(self) -> bool:
        """Validate configuration"""
        if not self.burp_jar_path.exists():
            logging.error(f"❌ Burp JAR not found: {self.burp_jar_path}")
            return False
        
        if not TARGETS_FILE.exists():
            logging.error(f"❌ Targets file not found: {TARGETS_FILE}")
            return False
        
        if not RESUME_BUTTON_IMG.exists():
            logging.warning(f"⚠️  Resume image missing: {RESUME_BUTTON_IMG}")
            logging.warning("   Auto-clicker will NOT work. Please save a screenshot of the Resume button.")

        for d in [LOGS_DIR, OUTPUT_DIR, CONFIG_DIR, self.temp_projects_dir]:
            d.mkdir(parents=True, exist_ok=True)
        
        logging.info(f"✓ Project root: {PROJECT_ROOT}")
        logging.info(f"✓ Burp JAR: {self.burp_jar_path.name}")
        logging.info(f"✓ Targets file: {TARGETS_FILE}")
        
        return True


# ============================================================================
# LOGGING SETUP
# ============================================================================

def setup_logging() -> None:
    """Configure logging"""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = LOGS_DIR / f"burp_scanner_{timestamp}.log"
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    logging.info(f"📝 Logging to: {log_file}")


# ============================================================================
# AUTO CLICKER
# ============================================================================

def force_unpause_gui() -> bool:
    """
    Aggressively tries to find and click the 'Resume' button.
    Searches for 10 seconds.
    """
    if not RESUME_BUTTON_IMG.exists():
        logging.warning("⚠️  Resume image not found. Cannot auto-click.")
        return False

    logging.info("🖱️  Auto-Clicker: Searching for 'Resume' button...")
    
    # Try for 10 seconds to account for slight delays
    start = time.time()
    while time.time() - start < 10:
        try:
            # FIX: Removed 'confidence' parameter
            location = pyautogui.locateOnScreen(str(RESUME_BUTTON_IMG))
            
            if location:
                logging.info(f"   Found button at {location}!")
                point = pyautogui.center(location)
                
                # Simple, single click
                pyautogui.click(point)
                logging.info("   ✓ CLICKED RESUME")
                
                # Optional: Move mouse away to ensure button isn't hovered (sometimes affects UI state)
                pyautogui.moveRel(100, 100) 
                
                return True
        except Exception as e:
            pass
        
        time.sleep(1)
    
    logging.warning("   Button not found (Burp might be minimized or already running)")
    return False


# ============================================================================
# BURP PROCESS MANAGER
# ============================================================================

class BurpProcessManager:
    """Manages Burp Suite process with official REST API"""
    
    def __init__(self, config: BurpConfig):
        self.config = config
        self.process: Optional[subprocess.Popen] = None
        self.project_file: Optional[Path] = None
        
    def start(self, target_url: str) -> bool:
        """Start Burp Suite with official REST API enabled"""
        try:
            self.config.temp_projects_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = target_url.replace("https://", "").replace("http://", "").replace("/", "_")[:50]
            self.project_file = self.config.temp_projects_dir / f"{safe_name}_{timestamp}.burp"
            
            # Clone the Golden Image if it exists
            if GOLDEN_PROJECT.exists():
                logging.info(f"📋 Cloning golden project to: {self.project_file.name}")
                shutil.copy(GOLDEN_PROJECT, self.project_file)
            else:
                logging.warning("⚠️  Starting with fresh project (Might be paused!)")

            # Burp command with official REST API
            cmd = [
                self.config.java_path,
                f"-Xmx{self.config.jvm_max_memory}",
                f"-Xms{self.config.jvm_min_memory}",
                "-XX:+UseG1GC",
                # Java 21 compatibility flags
                "--add-opens=java.base/java.lang=ALL-UNNAMED",
                "--add-opens=java.base/java.util=ALL-UNNAMED",
                "--add-opens=java.desktop/java.awt=ALL-UNNAMED",
                "--enable-native-access=ALL-UNNAMED",
                "-jar", str(self.config.burp_jar_path),
                "--project-file=" + str(self.project_file),
                # FIX: Explicitly load the config file to force "Don't Pause" setting
                "--config-file=" + str(BURP_CONFIG) if BURP_CONFIG.exists() else "",
            ]
            
            # Remove empty strings
            cmd = [c for c in cmd if c]
            
            logging.info(f"🚀 Starting Burp instance for: {target_url}")
            
            # Write logs to file
            burp_log = LOGS_DIR / f"burp_startup_{timestamp}.log"
            log_handle = open(burp_log, "w", encoding="utf-8")
            
            self.process = subprocess.Popen(
                cmd,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                preexec_fn=os.setsid if os.name != 'nt' else None
            )
            
            # UPDATED: Timeout increased to 180 seconds (3 minutes)
            if not self._wait_for_api_ready(timeout=180):
                logging.error("❌ Burp API failed to start within 180s")
                
                log_handle.close()
                try:
                    with open(burp_log, "r", encoding="utf-8") as f:
                        logs = f.read()
                        if logs:
                            logging.error(f"🔥 BURP LOGS:\n{logs[-2000:]}")
                except:
                    pass
                
                self.stop()
                return False
            
            logging.info(f"✓ Burp started (PID: {self.process.pid})")
            
            # --- STARTUP DELAY REMOVED ---
            # Try to unpause immediately after API is ready
            # But give a small 5s buffer for window rendering
            time.sleep(5) 
            force_unpause_gui()
            
            return True
            
        except Exception as e:
            logging.error(f"❌ Failed to start Burp: {e}")
            return False
    
    def stop(self) -> None:
        """Stop Burp"""
        if not self.process:
            return
        
        try:
            logging.info(f"🛑 Stopping Burp (PID: {self.process.pid})")
            
            if self.process.poll() is None:
                if os.name != 'nt':
                    os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
                else:
                    self.process.terminate()
                time.sleep(2)
                
            if self.process.poll() is None:
                if os.name != 'nt':
                    os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
                else:
                    self.process.kill()
                
            self.process.wait(timeout=5)
            logging.info("✓ Burp stopped")
            
        except Exception as e:
            logging.error(f"⚠️  Error stopping Burp: {e}")
        finally:
            self.process = None
    
    def _wait_for_api_ready(self, timeout: int = 120) -> bool:
        """Wait for Burp REST API"""
        start = time.time()
        headers = {} 
        
        while time.time() - start < timeout:
            try:
                resp = requests.get(
                    f"{self.config.api_base_url}/",
                    headers=headers,
                    timeout=2
                )
                if resp.status_code in [200, 404]:
                    print("\n   API responding, waiting 30s for project to load...", flush=True)
                    time.sleep(30) # Critical wait for project load
                    return True
            except:
                pass
            
            elapsed = int(time.time() - start)
            print(f"\r   Waiting for API ({elapsed}s/{timeout}s)...", end='', flush=True)
            time.sleep(3)
        
        print()
        return False


# ============================================================================
# PAUSE MONITOR
# ============================================================================

class PauseMonitor:
    """Dedicated pause detection and recovery logic"""
    
    def __init__(self, config: BurpConfig, task_id: str):
        self.config = config
        self.task_id = task_id
        self.pause_start_time = None
        self.total_attempts = 0
        self.successful_resume_clicks = 0  # Track successful clicks
        
    def handle_pause(self):
        """Clicks resume and tracks pause time"""
        if not self.pause_start_time:
            self.pause_start_time = time.time()
            
        self.total_attempts += 1
        elapsed = int(time.time() - self.pause_start_time)
        
        logging.warning(f"🔍 Pause detected, attempting resume (attempt {self.total_attempts})")
        logging.info(f"⏱️  Pause timer: {elapsed}/{self.config.pause_timeout} seconds")
        
        # Track if the click was actually successful (button found)
        if force_unpause_gui():
            self.successful_resume_clicks += 1
        
    def is_timeout_exceeded(self) -> bool:
        """Checks if pause duration exceeded limit"""
        if self.pause_start_time:
            if (time.time() - self.pause_start_time) > self.config.pause_timeout:
                return True
        return False
        
    def reset_pause_timer(self):
        """Reset timer when scan starts moving again"""
        if self.pause_start_time:
            logging.info("✓ Scan resumed successfully")
        self.pause_start_time = None
        self.total_attempts = 0


# ============================================================================
# BURP SCANNER
# ============================================================================

class BurpScanner:
    """Handles scanning using Burp's official API"""
    
    def __init__(self, config: BurpConfig):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json"
        })
        
    def scan_target(self, target_url: str) -> Optional[str]:
        """
        Initiate scan using Burp Scanner
        Returns task_id if successful
        """
        try:
            logging.info(f"🎯 Starting scan: {target_url}")
            
            # Base scan config structure
            scan_config = {
                "urls": [target_url],
                "scope": {
                    "include": [{"rule": target_url}],
                    "exclude": []
                }
            }

            # Inject detailed scan settings from scan_template.json if it exists
            if SCAN_TEMPLATE.exists():
                try:
                    with open(SCAN_TEMPLATE, 'r') as f:
                        template_data = json.load(f)
                        if "scanner" in template_data:
                             scan_config["scanner"] = template_data["scanner"]
                        else:
                             scan_config.update(template_data)
                    logging.info(f"✓ Loaded scan settings from {SCAN_TEMPLATE.name}")
                except Exception as e:
                    logging.warning(f"⚠️  Could not load scan template: {e}")
            
            # POST to /v0.1/scan
            resp = self.session.post(
                f"{self.config.api_base_url}/v0.1/scan",
                json=scan_config,
                timeout=30
            )
            
            if resp.status_code != 201:
                logging.error(f"❌ Scan creation failed: {resp.status_code} - {resp.text}")
                return None
            
            # Extract task_id from Location header
            location = resp.headers.get("Location", "")
            task_id = location.split("/")[-1] if location else None
            
            if not task_id:
                logging.error(f"❌ No task ID in response")
                return None
            
            logging.info(f"✓ Scan created: task_id={task_id}")

            # ATTEMPT UNPAUSE via Clicker AGAIN after scan creation
            # No extra delay here as we rely on BurpProcessManager start delay or PauseMonitor
            force_unpause_gui()

            return task_id
            
        except Exception as e:
            logging.error(f"❌ Failed to start scan: {e}")
            return None
    
    # UPDATED SIGNATURE: Returns Tuple with status AND pause_monitor object
    def wait_for_scan_completion(self, task_id: str, poll_interval: int = 30, max_wait: int = 3600) -> Tuple[Union[bool, str], Optional[PauseMonitor]]:
        """
        Monitor scan progress using task_id with Pause Monitor integration
        Returns:
            (status, pause_monitor_instance)
            Status can be: True, False, "timeout"
        """
        try:
            logging.info(f"⏳ Monitoring scan (max {max_wait//60} minutes)...")
            start_time = time.time()
            
            # Initialize Pause Monitor
            pause_monitor = PauseMonitor(self.config, task_id)
            
            while time.time() - start_time < max_wait:
                try:
                    resp = self.session.get(
                        f"{self.config.api_base_url}/v0.1/scan/{task_id}",
                        timeout=10
                    )
                    
                    if resp.status_code == 200:
                        data = resp.json()
                        scan_status = data.get("scan_status", "unknown")
                        issue_count = data.get("issue_events", 0) 
                        if isinstance(issue_count, list):
                            issue_count = len(issue_count)
                        
                        elapsed = int(time.time() - start_time)
                        logging.info(f"   Time: {elapsed}s | Status: {scan_status} | Issues: {issue_count}")
                        
                        # --- PAUSE HANDLING ---
                        if scan_status == "paused":
                            # This loop calls handle_pause repeatedly every poll_interval (15s)
                            # if status remains "paused", effectively "looking for pause as long as it's not pressed"
                            pause_monitor.handle_pause()
                            if pause_monitor.is_timeout_exceeded():
                                logging.error("⚠️  Still paused after 120s, aborting scan")
                                return "timeout", pause_monitor
                        else:
                            pause_monitor.reset_pause_timer()

                        # --- TERMINAL STATES ---
                        if scan_status == "succeeded":
                            logging.info("✓ Scan completed successfully")
                            return True, pause_monitor
                        elif scan_status == "failed":
                            logging.error("❌ Scan failed reported by API")
                            return False, pause_monitor
                    
                except Exception as e:
                    logging.debug(f"   Scan check error: {e}")
                
                time.sleep(self.config.pause_check_interval)
            
            logging.warning(f"⏰ Max wait time ({max_wait//60}m) reached")
            return True, pause_monitor # Treat as success (timeout) to attempt export
            
        except Exception as e:
            logging.error(f"❌ Error monitoring scan: {e}")
            return False, None
    
    def export_results(self, task_id: str, target_url: str) -> Optional[Path]:
        """Export scan results using task_id"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = target_url.replace("https://", "").replace("http://", "").replace("/", "_")[:50]
            output_file = OUTPUT_DIR / f"scan_{safe_name}_{timestamp}.json"
            
            logging.info(f"💾 Exporting results...")
            
            resp = self.session.get(
                f"{self.config.api_base_url}/v0.1/scan/{task_id}",
                headers={"Accept": "application/json"},
                timeout=60
            )
            
            if resp.status_code != 200:
                logging.error(f"❌ Export failed: {resp.status_code}")
                return None
            
            try:
                data = resp.json()
                json_str = json.dumps(data, indent=4)
                output_file.write_text(json_str, encoding='utf-8')
            except:
                output_file.write_bytes(resp.content)

            size_kb = output_file.stat().st_size / 1024
            logging.info(f"✓ Results saved: {output_file.name} ({size_kb:.1f} KB)")
            
            return output_file
            
        except Exception as e:
            logging.error(f"❌ Export failed: {e}")
            return None

    def export_partial_results(self, task_id: str, target_url: str, reason: str) -> Optional[Path]:
        """Save whatever exists when scan is aborted"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = target_url.replace("https://", "").replace("http://", "").replace("/", "_")[:50]
            output_file = OUTPUT_DIR / f"scan_{safe_name}_{timestamp}_INCOMPLETE.json"
            
            logging.info(f"💾 Saving partial results before abort...")
            
            resp = self.session.get(
                f"{self.config.api_base_url}/v0.1/scan/{task_id}",
                headers={"Accept": "application/json"},
                timeout=60
            )
            
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    data["scan_metadata"] = {
                        "scan_status": "aborted",
                        "abort_reason": f"{reason}_exceeded",
                        "aborted_at": datetime.now().isoformat()
                    }
                    json_str = json.dumps(data, indent=4)
                    output_file.write_text(json_str, encoding='utf-8')
                    logging.info(f"✓ Partial results saved: {output_file.name}")
                    return output_file
                except:
                    pass
            return None
        except Exception as e:
            logging.error(f"❌ Partial export failed: {e}")
            return None


# ============================================================================
# MAIN ORCHESTRATOR
# ============================================================================

class BurpMultiTargetScanner:
    """Multi-target scanner orchestrator"""
    
    def __init__(self, config: BurpConfig):
        self.config = config
        self.results: List[Dict] = []
        
    def scan_all_targets(self) -> None:
        """Scan all targets"""
        
        logging.info("\n" + "="*80)
        logging.info("🚀 BURP MULTI-TARGET SCANNER")
        logging.info("="*80)
        
        targets = self._load_targets(TARGETS_FILE)
        if not targets:
            logging.error("❌ No valid targets")
            return
        
        logging.info(f"✓ Loaded {len(targets)} target(s)\n")
        
        for idx, target_url in enumerate(targets, 1):
            logging.info("\n" + "="*80)
            logging.info(f"TARGET {idx}/{len(targets)}: {target_url}")
            logging.info("="*80 + "\n")
            
            result = self._scan_single_target(target_url)
            self.results.append(result)
            
            if idx < len(targets):
                logging.info("⏸  Pausing before next target...\n")
                time.sleep(5)
        
        self._print_summary()
    
    def _scan_single_target(self, target_url: str, max_retries: int = 2) -> Dict:
        """Scan single target with SMART retry logic"""
        result = {
            "target": target_url,
            "success": False,
            "status": "failed",
            "start_time": datetime.now().isoformat(),
            "output_file": None,
            "error": None,
            "attempts": 0,
            "abort_reason": None
        }
        
        for attempt in range(1, max_retries + 1):
            result["attempts"] = attempt
            logging.info(f"🔄 Attempt {attempt}/{max_retries}")
            
            burp_mgr = BurpProcessManager(self.config)
            scanner = BurpScanner(self.config)
            
            try:
                # 1. Start Burp
                if not burp_mgr.start(target_url):
                    raise Exception(f"Failed to start Burp (attempt {attempt})")
                
                # 2. Start Scan
                task_id = scanner.scan_target(target_url)
                if not task_id:
                    raise Exception(f"Failed to start scan (attempt {attempt})")
                
                # 3. Wait with enhanced return values
                scan_result, pause_monitor = scanner.wait_for_scan_completion(task_id, max_wait=14400)
                
                # --- HANDLING RESULT STATUS ---
                if scan_result == True:
                    # Success
                    output_file = scanner.export_results(task_id, target_url)
                    if output_file:
                        result["success"] = True
                        result["status"] = "success"
                        result["output_file"] = str(output_file.relative_to(PROJECT_ROOT))
                        burp_mgr.stop()
                        logging.info(f"✓ Success on attempt {attempt}")
                        return result
                    else:
                        raise Exception(f"Export failed (attempt {attempt})")
                
                elif scan_result == "timeout":
                    # TIMEOUT (Paused > 120s) -> SAVE AND SKIP (NO RETRY)
                    logging.warning("⚠️  Pause timeout exceeded (120s). Aborting execution.")
                    
                    logging.warning("⚠️  Scan persistently paused despite attempts. SKIPPING target.")
                    output_file = scanner.export_partial_results(task_id, target_url, "pause_timeout")
                    result["success"] = False
                    result["status"] = "partial"
                    result["abort_reason"] = "pause_timeout"
                    if output_file:
                        result["output_file"] = str(output_file.relative_to(PROJECT_ROOT))
                    
                    burp_mgr.stop()
                    return result # RETURN IMMEDIATELY - NO RETRY
                
                else:
                    # Generic Failure (False) - Standard retry applies
                    raise Exception(f"Scan did not complete (attempt {attempt})")
                
            except Exception as e:
                logging.error(f"❌ Error on attempt {attempt}: {e}")
                result["error"] = str(e)
                burp_mgr.stop()
                if attempt < max_retries:
                    logging.warning(f"   Retrying in 10 seconds...")
                    time.sleep(10)
            finally:
                result["end_time"] = datetime.now().isoformat()
        
        logging.error(f"❌ All {max_retries} attempts failed")
        return result
    
    def _load_targets(self, file: Path) -> List[str]:
        """Load targets from file"""
        try:
            targets = []
            with open(file, 'r') as f:
                for line in f:
                    url = line.strip()
                    if url and not url.startswith('#'):
                        if not url.startswith(('http://', 'https://')):
                            url = f"https://{url}"
                        targets.append(url)
            return targets
        except Exception as e:
            logging.error(f"❌ Failed to load targets: {e}")
            return []
    
    def _print_summary(self) -> None:
        """Print summary"""
        logging.info("\n\n" + "="*80)
        logging.info("📊 SCAN SUMMARY")
        logging.info("="*80)
        
        total = len(self.results)
        complete = sum(1 for r in self.results if r["status"] == "success")
        partial = sum(1 for r in self.results if r["status"] == "partial")
        failed = total - complete - partial
        
        logging.info(f"\nTotal: {total} | Complete: {complete} | Partial: {partial} | Failed: {failed}")
        
        if partial > 0:
            logging.info(f"\n⚠️  Partial Scans (Review Needed):")
            for r in self.results:
                if r["status"] == "partial":
                    logging.info(f"   ⚠ {r['target']} - Reason: {r['abort_reason']}")

        if any(r.get("attempts", 0) > 1 for r in self.results):
            logging.info(f"\n🔄 Retries:")
            for r in self.results:
                attempts = r.get("attempts", 1)
                if attempts > 1:
                    status = "✓" if r["success"] else "✗"
                    logging.info(f"   {status} {r['target']}: {attempts} attempts")

        if any(r["output_file"] for r in self.results):
            logging.info(f"\n📁 Results:")
            for r in self.results:
                if r["output_file"]:
                    mark = "✓" if r["status"] == "success" else "⚠️"
                    logging.info(f"   {mark} {r['output_file']}")
        
        logging.info("\n" + "="*80 + "\n")


# ============================================================================
# MAIN
# ============================================================================

def main():
    """Main execution"""
    try:
        setup_logging()
        logging.info("🔧 Initializing...")
        
        # Ensure this points to your Java 21 install
        JAVA_PATH = r"C:\Program Files\Java\jdk-21\bin\java.exe"
        
        if not os.path.exists(JAVA_PATH):
            logging.error(f"❌ Java not found: {JAVA_PATH}")
            sys.exit(1)
        
        logging.info(f"   Java: {JAVA_PATH}")
        
        config = BurpConfig(
            burp_jar_path=BURP_PRO_JAR,
            java_path=JAVA_PATH,
            jvm_max_memory="4g",
            api_port=8090,
            api_key=""
        )
        
        if not config.validate():
            logging.error("❌ Configuration validation failed")
            sys.exit(1)
        
        scanner = BurpMultiTargetScanner(config)
        scanner.scan_all_targets()
        
    except KeyboardInterrupt:
        logging.warning("\n⚠️  Interrupted")
        sys.exit(130)
    except Exception as e:
        logging.error(f"❌ Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()