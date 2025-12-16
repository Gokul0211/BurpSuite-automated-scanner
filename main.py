"""
Burp Suite Professional Automated Scanner - CORRECTED VERSION
Uses burp-rest-api extension for proper API access
Scans multiple websites with config and exports vulnerabilities as XML

File: main.py
"""

import subprocess
import requests
import time
import json
import os
import sys
import psutil
from pathlib import Path
from datetime import datetime
import xml.etree.ElementTree as ET
from xml.dom import minidom

# ==================== CONFIGURATION ====================
# IMPORTANT: Download burp-rest-api.jar from https://github.com/vmware/burp-rest-api/releases
BURP_JAR_PATH = r"C:\Program Files\BurpSuitePro\burpsuite_pro.jar"  # Windows
BURP_REST_API_JAR = r"burp-rest-api-2.3.2.jar"  # Place in same directory as script

# For Mac: /Applications/Burp Suite Professional.app/Contents/Java/app/burpsuite_pro.jar
# For Linux: /opt/BurpSuitePro/burpsuite_pro.jar

BURP_API_URL = "http://localhost:8090"  # burp-rest-api default port
BURP_API_KEY = "your-custom-api-key-here"  # Set a secure API key

INPUT_FILE = "input/websites.txt"
CONFIG_FILE = "config/burp_config.json"  # Burp project config file
OUTPUT_DIR = "output"

# API Headers
API_HEADERS = {
    "Content-Type": "application/json",
    "API-KEY": BURP_API_KEY  # Custom API key for authentication
}


class BurpManager:
    """Manages Burp Suite process with REST API extension"""
    
    def __init__(self, burp_jar, rest_api_jar, api_key, config_file):
        self.burp_jar = burp_jar
        self.rest_api_jar = rest_api_jar
        self.api_key = api_key
        self.config_file = config_file
        self.process = None
        self.temp_project = None
    
    def cleanup_orphaned_temp_files(self):
        """Clean up any leftover temp project files from crashed runs"""
        try:
            for file in os.listdir('.'):
                if file.startswith('temp_burp_project_') and file.endswith('.burp'):
                    try:
                        os.remove(file)
                        print(f"[+] Cleaned up orphaned temp file: {file}")
                    except:
                        pass
        except:
            pass
    
    def start(self):
        """Start Burp Suite with REST API enabled"""
        print("[*] Starting Burp Suite Professional with REST API...")
        
        # Check if already running
        if self.is_running():
            print("[!] Burp Suite is already running. Killing existing instance...")
            self.kill()
            time.sleep(5)
        
        try:
            # Create temporary project file
            self.temp_project = f"temp_burp_project_{int(time.time())}.burp"
            
            # Build command for Windows
            if os.name == 'nt':
                cmd = [
                    "java",
                    "--add-opens=java.desktop/javax.swing=ALL-UNNAMED",
                    "--add-opens=java.base/java.lang=ALL-UNNAMED",
                    "-jar",
                    self.rest_api_jar,
                    "--burp.jar=" + self.burp_jar,
                    f"--apikey={self.api_key}",
                    "--headless.mode=true",
                    f"--project-file={self.temp_project}",
                    f"--config-file={self.config_file}" if os.path.exists(self.config_file) else ""
                ]
            else:
                # Linux/Mac
                cmd = [
                    "java",
                    "--add-opens=java.desktop/javax.swing=ALL-UNNAMED",
                    "--add-opens=java.base/java.lang=ALL-UNNAMED",
                    "-cp",
                    f"{self.burp_jar}:{self.rest_api_jar}",
                    "org.springframework.boot.loader.launch.JarLauncher",
                    f"--apikey={self.api_key}",
                    "--headless.mode=true",
                    f"--project-file={self.temp_project}",
                    f"--config-file={self.config_file}" if os.path.exists(self.config_file) else ""
                ]
            
            # Remove empty strings
            cmd = [c for c in cmd if c]
            
            print(f"[*] Executing: {' '.join(cmd)}")
            
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            
            print(f"[+] Burp Suite started (PID: {self.process.pid})")
            return True
            
        except Exception as e:
            print(f"[!] Failed to start Burp Suite: {e}")
            return False
    
    def is_running(self):
        """Check if OUR Burp Suite process is running"""
        if self.process is None:
            return False
        
        try:
            # Check if our specific process is still alive
            return psutil.pid_exists(self.process.pid) and self.process.poll() is None
        except:
            return False
    
    def kill(self):
        """Kill OUR Burp Suite process and cleanup"""
        print("[*] Killing Burp Suite process...")
        
        if self.process is None:
            print("[!] No Burp process to kill (process reference is None)")
            time.sleep(2)
            return
        
        try:
            # Get the process object
            proc = psutil.Process(self.process.pid)
            
            # Kill all child processes first (Burp may spawn children)
            children = proc.children(recursive=True)
            for child in children:
                try:
                    print(f"[*] Killing child process (PID: {child.pid})")
                    child.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            
            # Kill the main process
            print(f"[*] Killing main Burp process (PID: {self.process.pid})")
            proc.kill()
            
            # Wait for process to die
            proc.wait(timeout=10)
            print(f"[+] Successfully killed Burp process (PID: {self.process.pid})")
            
        except psutil.NoSuchProcess:
            print(f"[!] Process {self.process.pid} already dead")
        except psutil.TimeoutExpired:
            print(f"[!] Process {self.process.pid} didn't die gracefully, forcing...")
            try:
                proc.kill()  # Force kill
            except:
                pass
        except Exception as e:
            print(f"[!] Error killing process: {e}")
        
        finally:
            # Clean up temp project file
            if self.temp_project and os.path.exists(self.temp_project):
                try:
                    os.remove(self.temp_project)
                    print(f"[+] Cleaned up temporary project: {self.temp_project}")
                except Exception as e:
                    print(f"[!] Failed to clean temp project: {e}")
            
            # Reset process reference
            self.process = None
            time.sleep(3)  # Wait for cleanup
    
    def wait_for_api(self, timeout=90):
        """Wait for Burp REST API to become available"""
        print("[*] Waiting for Burp REST API to become ready...")
        
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                # Test with version endpoint
                response = requests.get(
                    f"{BURP_API_URL}/burp/versions",
                    headers=API_HEADERS,
                    timeout=5
                )
                if response.status_code == 200:
                    version_info = response.json()
                    print(f"[+] Burp API is ready - Version: {version_info.get('burpVersion', 'Unknown')}")
                    return True
            except requests.exceptions.RequestException as e:
                pass
            
            print(f"[*] Waiting... ({int(time.time() - start_time)}s)")
            time.sleep(5)
        
        print("[!] Timeout waiting for Burp API")
        return False


class BurpAPIClient:
    """Handles Burp Suite REST API interactions"""
    
    def __init__(self, api_url, headers):
        self.api_url = api_url
        self.headers = headers
    
    def spider_scan(self, target_url):
        """Start spider scan"""
        print(f"[*] Starting spider scan for: {target_url}")
        
        payload = {
            "baseUrl": target_url
        }
        
        try:
            response = requests.post(
                f"{self.api_url}/burp/spider",
                headers=self.headers,
                json=payload,
                timeout=30
            )
            
            if response.status_code == 201:
                print(f"[+] Spider scan started")
                return True
            else:
                print(f"[!] Failed to start spider: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            print(f"[!] Error starting spider: {e}")
            return False
    
    def wait_for_spider(self):
        """Wait for spider to complete"""
        print(f"[*] Waiting for spider to complete...")
        
        while True:
            try:
                response = requests.get(
                    f"{self.api_url}/burp/spider/status",
                    headers=self.headers,
                    timeout=10
                )
                
                if response.status_code == 200:
                    status = response.json()
                    progress = status.get('scanPercentage', 0)
                    print(f"[*] Spider progress: {progress}%")
                    
                    if progress >= 100:
                        print(f"[+] Spider completed")
                        return True
            except Exception as e:
                print(f"[!] Error checking spider status: {e}")
            
            time.sleep(10)
    
    def active_scan(self, target_url):
        """Start active scan"""
        print(f"[*] Starting active scan for: {target_url}")
        
        payload = {
            "baseUrl": target_url
        }
        
        try:
            response = requests.post(
                f"{self.api_url}/burp/scanner/scans/active",
                headers=self.headers,
                json=payload,
                timeout=30
            )
            
            if response.status_code == 201:
                print(f"[+] Active scan started")
                return True
            else:
                print(f"[!] Failed to start active scan: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            print(f"[!] Error starting active scan: {e}")
            return False
    
    def wait_for_scan(self):
        """Wait for active scan to complete"""
        print(f"[*] Waiting for active scan to complete...")
        
        while True:
            try:
                response = requests.get(
                    f"{self.api_url}/burp/scanner/status",
                    headers=self.headers,
                    timeout=10
                )
                
                if response.status_code == 200:
                    status = response.json()
                    progress = status.get('scanPercentage', 0)
                    print(f"[*] Scan progress: {progress}%")
                    
                    if progress >= 100:
                        print(f"[+] Active scan completed")
                        return True
            except Exception as e:
                print(f"[!] Error checking scan status: {e}")
            
            time.sleep(15)
    
    def get_issues(self):
        """Get all discovered issues/vulnerabilities"""
        print(f"[*] Retrieving scan issues...")
        
        try:
            response = requests.get(
                f"{self.api_url}/burp/scanner/issues",
                headers=self.headers,
                timeout=30
            )
            
            if response.status_code == 200:
                issues = response.json()
                print(f"[+] Retrieved {len(issues.get('issues', []))} issues")
                return issues
            else:
                print(f"[!] Failed to get issues: {response.status_code}")
                return {"issues": []}
                
        except Exception as e:
            print(f"[!] Error retrieving issues: {e}")
            return {"issues": []}
    
    def get_sitemap(self):
        """Get sitemap data"""
        print(f"[*] Retrieving sitemap...")
        
        try:
            response = requests.get(
                f"{self.api_url}/burp/target/sitemap",
                headers=self.headers,
                timeout=30
            )
            
            if response.status_code == 200:
                sitemap = response.json()
                print(f"[+] Retrieved sitemap data")
                return sitemap
            else:
                print(f"[!] Failed to get sitemap: {response.status_code}")
                return {}
                
        except Exception as e:
            print(f"[!] Error retrieving sitemap: {e}")
            return {}


class XMLExporter:
    """Exports scan results with vulnerabilities to XML"""
    
    @staticmethod
    def create_vulnerability_xml(issues, sitemap, target_url):
        """Create comprehensive XML report"""
        root = ET.Element("burp_scan_report")
        
        # Add scan info
        scan_info = ET.SubElement(root, "scan_info")
        ET.SubElement(scan_info, "target").text = target_url
        ET.SubElement(scan_info, "scan_date").text = datetime.now().isoformat()
        ET.SubElement(scan_info, "total_issues").text = str(len(issues.get('issues', [])))
        
        # Add issues/vulnerabilities
        issues_elem = ET.SubElement(root, "vulnerabilities")
        
        for issue in issues.get('issues', []):
            issue_elem = ET.SubElement(issues_elem, "vulnerability")
            
            ET.SubElement(issue_elem, "severity").text = str(issue.get('severity', 'Unknown'))
            ET.SubElement(issue_elem, "confidence").text = str(issue.get('confidence', 'Unknown'))
            ET.SubElement(issue_elem, "issue_name").text = str(issue.get('issueName', 'Unknown'))
            ET.SubElement(issue_elem, "issue_type").text = str(issue.get('issueType', 'Unknown'))
            ET.SubElement(issue_elem, "url").text = str(issue.get('url', 'Unknown'))
            ET.SubElement(issue_elem, "host").text = str(issue.get('host', 'Unknown'))
            ET.SubElement(issue_elem, "path").text = str(issue.get('path', 'Unknown'))
            
            # Issue details
            issue_detail = ET.SubElement(issue_elem, "issue_detail")
            issue_detail.text = str(issue.get('issueDetail', 'No details available'))
            
            # Issue background
            issue_background = ET.SubElement(issue_elem, "issue_background")
            issue_background.text = str(issue.get('issueBackground', 'No background available'))
            
            # Remediation
            remediation = ET.SubElement(issue_elem, "remediation")
            remediation.text = str(issue.get('remediationDetail', 'No remediation available'))
            
            # References
            if 'references' in issue:
                refs = ET.SubElement(issue_elem, "references")
                refs.text = str(issue.get('references', ''))
        
        # Add sitemap summary
        if sitemap:
            sitemap_elem = ET.SubElement(root, "sitemap_summary")
            ET.SubElement(sitemap_elem, "total_urls").text = str(len(sitemap.get('messages', [])))
        
        return root
    
    @staticmethod
    def prettify_xml(elem):
        """Return pretty-printed XML"""
        rough_string = ET.tostring(elem, encoding='unicode')
        reparsed = minidom.parseString(rough_string)
        return reparsed.toprettyxml(indent="  ")
    
    def export(self, issues, sitemap, target_url, output_path):
        """Export complete scan results to XML"""
        print(f"[*] Exporting results to: {output_path}")
        
        try:
            xml_root = self.create_vulnerability_xml(issues, sitemap, target_url)
            xml_string = self.prettify_xml(xml_root)
            
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(xml_string)
            
            print(f"[+] Results exported successfully")
            print(f"[+] Total vulnerabilities: {len(issues.get('issues', []))}")
            return True
            
        except Exception as e:
            print(f"[!] Failed to export XML: {e}")
            return False


def read_websites(file_path):
    """Read website list from file"""
    if not os.path.exists(file_path):
        print(f"[!] Website list not found: {file_path}")
        return []
    
    with open(file_path, 'r') as f:
        websites = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    
    print(f"[+] Loaded {len(websites)} websites from {file_path}")
    return websites


def sanitize_filename(url):
    """Convert URL to safe filename"""
    domain = url.replace('https://', '').replace('http://', '')
    domain = domain.replace('/', '-').replace(':', '-').replace('?', '-')
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    return f"{domain}_{timestamp}_scan.xml"


def main():
    """Main execution flow"""
    print("=" * 70)
    print("Burp Suite Professional - Automated Scanner with REST API")
    print("=" * 70)
    
    # Create directories
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(INPUT_FILE), exist_ok=True)
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    
    # Verify REST API JAR exists
    if not os.path.exists(BURP_REST_API_JAR):
        print(f"[!] ERROR: burp-rest-api JAR not found: {BURP_REST_API_JAR}")
        print("[!] Download from: https://github.com/vmware/burp-rest-api/releases")
        return
    
    # Load websites
    websites = read_websites(INPUT_FILE)
    if not websites:
        print("[!] No websites to scan. Exiting.")
        return
    
    # Initialize components
    burp_manager = BurpManager(BURP_JAR_PATH, BURP_REST_API_JAR, BURP_API_KEY, CONFIG_FILE)
    api_client = BurpAPIClient(BURP_API_URL, API_HEADERS)
    xml_exporter = XMLExporter()
    
    # Process each website
    for idx, website in enumerate(websites, 1):
        print("\n" + "=" * 70)
        print(f"Processing {idx}/{len(websites)}: {website}")
        print("=" * 70)
        
        # Start Burp Suite
        if not burp_manager.start():
            print(f"[!] Failed to start Burp Suite for {website}. Skipping...")
            continue
        
        # Wait for API
        if not burp_manager.wait_for_api():
            print(f"[!] Burp API not available for {website}. Killing and skipping...")
            burp_manager.kill()
            continue
        
        try:
            # Run spider scan
            if api_client.spider_scan(website):
                api_client.wait_for_spider()
            
            # Run active scan
            if api_client.active_scan(website):
                api_client.wait_for_scan()
            
            # Get results
            issues = api_client.get_issues()
            sitemap = api_client.get_sitemap()
            
            # Export to XML
            output_file = os.path.join(OUTPUT_DIR, sanitize_filename(website))
            xml_exporter.export(issues, sitemap, website, output_file)
            
        except Exception as e:
            print(f"[!] Error during scan: {e}")
        
        # Kill Burp Suite to clear RAM
        burp_manager.kill()
        
        # Wait before next iteration
        if idx < len(websites):
            print(f"\n[*] Waiting 5 seconds before next scan...")
            time.sleep(5)
    
    print("\n" + "=" * 70)
    print("All scans completed!")
    print(f"Results saved in: {OUTPUT_DIR}/")
    print("=" * 70)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[!] Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n[!] Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)