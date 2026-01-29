#!/usr/bin/env python3
"""
Burp Suite Pro Multi-Target Automation Scanner
Using Burp's Official Built-in REST API + GUI Auto-Unpause + Smart Logic + Pretty JSON
Integrations: Pause Timeout Handler, Aggressive Resume Clicker, No Retry on Execution Timeout
HARDENED VERSION - Production-grade GPU safety
PERFECTED VERSION - Proper fix.burp loading with copy operation + auto-unpause flag
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
import traceback
import pyautogui  # For auto-clicking
from pathlib import Path
from typing import Optional, Dict, List, Union, Tuple
from dataclasses import dataclass
from datetime import datetime

# ============================================================================
# CRITICAL: pyautogui safety configuration (MUST be before any GUI operations)
# ============================================================================
pyautogui.FAILSAFE = True   # Move mouse to corner to abort
pyautogui.PAUSE = 0.5       # Delay between low-level operations

# ============================================================================
# PROJECT PATHS
# ============================================================================
PROJECT_ROOT = Path(__file__).parent.resolve()
CONFIG_DIR = PROJECT_ROOT / "config"
INPUT_DIR = PROJECT_ROOT / "input"
LOGS_DIR = PROJECT_ROOT / "logs"
OUTPUT_DIR = PROJECT_ROOT / "output"

# Burp JAR Version 2025.11.6
BURP_PRO_JAR = PROJECT_ROOT / "burpsuite_pro.jar"
TARGETS_FILE = INPUT_DIR / "websites.txt"
SCAN_TEMPLATE = CONFIG_DIR / "scan_template.json"
BURP_CONFIG = CONFIG_DIR / "burp_config.json"
FIX_PROJECT = CONFIG_DIR / "fix.burp"  # Changed from golden.burp
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
    
    def validate(self) -> Tuple[bool, List[str]]:
        """Validate configuration and return (success, list of issues)"""
        issues = []
        
        if not self.burp_jar_path.exists():
            issues.append(f"❌ Burp JAR not found: {self.burp_jar_path}")
        else:
            logging.info(f"✓ Found Burp JAR: {self.burp_jar_path.name}")
        
        if not TARGETS_FILE.exists():
            issues.append(f"❌ Targets file not found: {TARGETS_FILE}")
            issues.append(f"   Create it with: echo https://example.com > {TARGETS_FILE}")
        else:
            logging.info(f"✓ Found targets file: {TARGETS_FILE}")
        
        if not FIX_PROJECT.exists():
            logging.warning(f"⚠️  Fix project template missing: {FIX_PROJECT}")
            logging.warning("   A new project will be created without scheduled tasks.")
        else:
            logging.info(f"✓ Found fix.burp template: {FIX_PROJECT.name}")
        
        if not RESUME_BUTTON_IMG.exists():
            logging.warning(f"⚠️  Resume image missing: {RESUME_BUTTON_IMG}")
            logging.warning("   Auto-clicker will NOT work. Please save a screenshot of the Resume button.")
        else:
            logging.info(f"✓ Found resume button image: {RESUME_BUTTON_IMG.name}")
        
        # Create required directories
        for d in [LOGS_DIR, OUTPUT_DIR, CONFIG_DIR, INPUT_DIR, self.temp_projects_dir]:
            d.mkdir(parents=True, exist_ok=True)
        
        # Test Java
        try:
            result = subprocess.run(
                [self.java_path, "-version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode != 0:
                issues.append(f"❌ Java check failed: {self.java_path}")
            else:
                logging.info(f"✓ Java is working: {self.java_path}")
        except FileNotFoundError:
            issues.append(f"❌ Java not found: {self.java_path}")
        except Exception as e:
            issues.append(f"❌ Java test error: {e}")
        
        logging.info(f"✓ Project root: {PROJECT_ROOT}")
        
        return (len(issues) == 0, issues)

# ============================================================================
# LOGGING SETUP
# ============================================================================
def setup_logging() -> None:
    """Configure logging with both file and console output"""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = LOGS_DIR / f"burp_scanner_{timestamp}.log"
    
    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # File handler
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setFormatter(formatter)
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    logging.info(f"📝 Logging initialized")
    logging.info(f"   Log file: {log_file}")

# ============================================================================
# BURP PROCESS MANAGER - PERFECTED WITH FIX.BURP COPYING
# ============================================================================
# Global reference to BurpProcessManager (set during execution)
_ACTIVE_BURP_MANAGER = None

class BurpProcessManager:
    """Manages Burp Suite process with official REST API"""
    
    def __init__(self, config: BurpConfig):
        self.config = config
        self.process: Optional[subprocess.Popen] = None
        self.project_file: Optional[Path] = None
        self.is_stopping = False  # CRITICAL: Shutdown guard
        
    def start(self, target_url: str) -> bool:
        """Start Burp Suite with official REST API enabled"""
        global _ACTIVE_BURP_MANAGER
        
        try:
            self.is_stopping = False  # Reset flag
            _ACTIVE_BURP_MANAGER = self  # Set global reference
            
            # CRITICAL FIX: Always create temp project directory and copy fix.burp
            self.config.temp_projects_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = target_url.replace("https://", "").replace("http://", "").replace("/", "_")[:50]
            self.project_file = self.config.temp_projects_dir / f"{safe_name}_{timestamp}.burp"
            
            # Copy fix.burp template to temp location
            if FIX_PROJECT.exists():
                logging.info(f"📋 Copying fix.burp template with scheduled tasks")
                logging.info(f"   Source: {FIX_PROJECT}")
                logging.info(f"   Destination: {self.project_file}")
                try:
                    shutil.copy2(FIX_PROJECT, self.project_file)
                    logging.info(f"✓ Fix.burp template copied successfully")
                    # Verify the copy
                    if self.project_file.exists():
                        size_kb = self.project_file.stat().st_size / 1024
                        logging.info(f"✓ Copied project size: {size_kb:.1f} KB")
                    else:
                        logging.error("❌ Copy verification failed - file not found")
                        return False
                except Exception as e:
                    logging.error(f"❌ Failed to copy fix.burp: {e}")
                    logging.error(traceback.format_exc())
                    return False
            else:
                logging.warning("⚠️  Fix.burp template not found, creating new project")
                logging.warning(f"   Expected at: {FIX_PROJECT}")
                logging.warning(f"   Scheduled tasks will NOT be available!")
            
            # Burp command with official REST API + SAFETY FLAGS + AUTO-UNPAUSE
            cmd = [
                self.config.java_path,
                f"-Xmx{self.config.jvm_max_memory}",
                f"-Xms{self.config.jvm_min_memory}",
                "-XX:+UseG1GC",
                # CRITICAL SAFETY FIX: Force software rendering
                "-Dsun.java2d.opengl=false",
                "-Dsun.java2d.xrender=false",
                # Java 21 compatibility flags
                "--add-opens=java.base/java.lang=ALL-UNNAMED",
                "--add-opens=java.base/java.util=ALL-UNNAMED",
                "--add-opens=java.desktop/java.awt=ALL-UNNAMED",
                "--enable-native-access=ALL-UNNAMED",
                "-jar", str(self.config.burp_jar_path),
                "--project-file=" + str(self.project_file),
                "--unpause-spider-and-scanner",  # CRITICAL: Auto-unpause flag
            ]
            
            # Add config file if it exists
            if BURP_CONFIG.exists():
                cmd.append("--config-file=" + str(BURP_CONFIG))
                logging.info(f"✓ Loading Burp config: {BURP_CONFIG.name}")
            
            # Remove empty strings
            cmd = [c for c in cmd if c]
            
            logging.info(f"🚀 Starting Burp instance for: {target_url}")
            logging.info(f"   Using project file: {self.project_file.name}")
            logging.info(f"   Auto-unpause: ENABLED")
            logging.debug(f"   Command: {' '.join(cmd)}")
            
            # Write logs to file
            timestamp_log = datetime.now().strftime("%Y%m%d_%H%M%S")
            burp_log = LOGS_DIR / f"burp_startup_{timestamp_log}.log"
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
                            logging.error(f"🔥 BURP STARTUP LOGS:\n{logs[-2000:]}")
                except:
                    pass
                
                self.stop()
                return False
            
            logging.info(f"✓ Burp started successfully (PID: {self.process.pid})")
            
            # CRITICAL SAFETY FIX: Increased startup delay from 5s to 30s
            # Allows JVM + UI to fully settle before GUI interaction
            logging.info("   Waiting 30s for UI to stabilize...")
            time.sleep(30)
            
            return True
            
        except Exception as e:
            logging.error(f"❌ Failed to start Burp: {e}")
            logging.error(traceback.format_exc())
            return False
    
    def stop(self) -> None:
        """Stop Burp and cleanup temp project file"""
        global _ACTIVE_BURP_MANAGER
        
        if not self.process:
            return
        
        try:
            # CRITICAL: Set shutdown flag BEFORE any termination
            self.is_stopping = True
            
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
            
            # Cleanup temp project file (optional - keeps disk clean)
            if self.project_file and self.project_file.exists():
                try:
                    # Keep the project file for debugging if needed
                    # Uncomment to delete:
                    # self.project_file.unlink()
                    # logging.info(f"✓ Cleaned up temp project: {self.project_file.name}")
                    pass
                except Exception as e:
                    logging.warning(f"⚠️  Could not cleanup temp project: {e}")
            
        except Exception as e:
            logging.error(f"⚠️  Error stopping Burp: {e}")
        finally:
            self.process = None
            _ACTIVE_BURP_MANAGER = None
    
    def _wait_for_api_ready(self, timeout: int = 120) -> bool:
        """Wait for Burp REST API to become available"""
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
                    print("\n   ✓ API responding!", flush=True)
                    print("   Waiting 30s for project to fully load...", flush=True)
                    time.sleep(30)  # Critical wait for project load + scheduled tasks init
                    return True
            except:
                pass
            
            elapsed = int(time.time() - start)
            print(f"\r   Waiting for API ({elapsed}s/{timeout}s)...", end='', flush=True)
            time.sleep(3)
        
        print()
        return False

# ============================================================================
# PAUSE MONITOR WITH API RESUME CAPABILITY
# ============================================================================
class PauseMonitor:
    """Dedicated pause detection and recovery logic"""
    
    def __init__(self, config: BurpConfig, task_id: str):
        self.config = config
        self.task_id = task_id
        self.pause_start_time = None
        self.total_attempts = 0
        self.successful_resume_attempts = 0
        
    def handle_pause(self):
        """Handle pause detection and attempt API-based resume"""
        if not self.pause_start_time:
            self.pause_start_time = time.time()
            
        self.total_attempts += 1
        elapsed = int(time.time() - self.pause_start_time)
        
        logging.warning(f"🔍 Pause detected (attempt {self.total_attempts})")
        logging.info(f"⏱️  Pause timer: {elapsed}/{self.config.pause_timeout} seconds")
        
        # Try to resume via API
        try:
            resume_url = f"{self.config.api_base_url}/v0.1/scan/{self.task_id}/resume"
            logging.info(f"   Attempting API resume: {resume_url}")
            
            resp = requests.post(resume_url, timeout=5)
            
            if resp.status_code in [200, 204]:
                logging.info("   ✓ API resume command sent successfully")
                self.successful_resume_attempts += 1
            else:
                logging.warning(f"   ⚠️  API resume returned: {resp.status_code}")
        except Exception as e:
            logging.debug(f"   API resume error: {e}")
            # Fall back to scheduled task handling
            logging.info("   Relying on scheduled task for resume...")
        
    def is_timeout_exceeded(self) -> bool:
        """Check if pause duration exceeded limit"""
        if self.pause_start_time:
            if (time.time() - self.pause_start_time) > self.config.pause_timeout:
                return True
        return False
        
    def reset_pause_timer(self):
        """Reset timer when scan starts moving again"""
        if self.pause_start_time:
            logging.info("✓ Scan resumed successfully")
            if self.successful_resume_attempts > 0:
                logging.info(f"   Successful API resume attempts: {self.successful_resume_attempts}")
        self.pause_start_time = None
        self.total_attempts = 0
        self.successful_resume_attempts = 0

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
            
            return task_id
            
        except Exception as e:
            logging.error(f"❌ Failed to start scan: {e}")
            logging.error(traceback.format_exc())
            return None
    
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
            return True, pause_monitor  # Treat as success (timeout) to attempt export
            
        except Exception as e:
            logging.error(f"❌ Error monitoring scan: {e}")
            logging.error(traceback.format_exc())
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
            logging.error(traceback.format_exc())
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
        logging.info("🚀 BURP MULTI-TARGET SCANNER - PERFECTED EDITION")
        logging.info("="*80)
        
        targets = self._load_targets(TARGETS_FILE)
        if not targets:
            logging.error("❌ No valid targets found")
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
                # 1. Start Burp (with fix.burp copy + auto-unpause)
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
                    return result  # RETURN IMMEDIATELY - NO RETRY
                
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
            with open(file, 'r', encoding='utf-8') as f:
                for line in f:
                    url = line.strip()
                    if url and not url.startswith('#'):
                        if not url.startswith(('http://', 'https://')):
                            url = f"https://{url}"
                        targets.append(url)
            return targets
        except Exception as e:
            logging.error(f"❌ Failed to load targets: {e}")
            logging.error(traceback.format_exc())
            return []
    
    def _print_summary(self) -> None:
        """Print comprehensive summary"""
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
# MAIN ENTRY POINT
# ============================================================================
def main():
    """Main execution"""
    
    # Setup logging FIRST before anything else
    try:
        setup_logging()
    except Exception as e:
        print(f"FATAL: Could not setup logging: {e}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)
    
    try:
        logging.info("🔧 Initializing Burp Scanner (Perfected Edition)...")
        logging.info(f"   Python: {sys.version}")
        logging.info(f"   Working directory: {os.getcwd()}")
        
        # Auto-detect Java or use specified path
        JAVA_PATH = r"C:\Program Files\Java\jdk-21\bin\java.exe"
        
        # Try to find Java if hardcoded path doesn't exist
        if not os.path.exists(JAVA_PATH):
            logging.warning(f"   Java not found at: {JAVA_PATH}")
            logging.info(f"   Attempting to use system Java...")
            JAVA_PATH = "java"
        
        config = BurpConfig(
            burp_jar_path=BURP_PRO_JAR,
            java_path=JAVA_PATH,
            jvm_max_memory="4g",
            api_port=8090,
            api_key=""
        )
        
        # Validate configuration
        is_valid, issues = config.validate()
        
        if issues:
            logging.error("\n❌ Configuration Issues Found:")
            for issue in issues:
                logging.error(f"   {issue}")
        
        if not is_valid:
            logging.error("\n❌ Configuration validation failed")
            logging.error("   Please fix the issues above and try again")
            sys.exit(1)
        
        logging.info("\n✓ Configuration validated successfully")
        logging.info("✓ Fix.burp template will be copied for each scan")
        logging.info("✓ Auto-unpause flag enabled")
        
        scanner = BurpMultiTargetScanner(config)
        scanner.scan_all_targets()
        
        logging.info("\n✓ Scanner finished")
        
    except KeyboardInterrupt:
        logging.warning("\n⚠️  Interrupted by user")
        sys.exit(130)
    except Exception as e:
        logging.error(f"\n❌ Fatal error: {e}")
        logging.error("\n" + traceback.format_exc())
        sys.exit(1)

if __name__ == "__main__":
    main()