"""
Burp Suite Professional Automated Scanner
Uses burp-rest-api extension for proper API access
Scans multiple websites with config and exports vulnerabilities as XML

File: main.py
Requirements: Java 21+, Burp Suite Pro, burp-rest-api JAR
Author: Your Name
License: MIT
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
# Update these paths to match your system
BURP_JAR_PATH = r"C:\path\to\burpsuite_pro.jar"
BURP_REST_API_JAR = r"C:\path\to\burp-rest-api.jar"

BURP_API_URL = "http://localhost:8090"
BURP_API_KEY = os.getenv("BURP_API_KEY", "your-api-key-here")  # Use environment variable or hardcode

INPUT_FILE = "input/websites.txt"
CONFIG_FILE = "config/burp_config.json"
OUTPUT_DIR = "output"

API_HEADERS = {
    "Content-Type": "application/json",
    "API-KEY": BURP_API_KEY
}


class BurpManager:
    """Manages Burp Suite process lifecycle"""
    
    def __init__(self, burp_jar, rest_api_jar, api_key, config_file):
        self.burp_jar = burp_jar
        self.rest_api_jar = rest_api_jar
        self.api_key = api_key
        self.config_file = config_file
        self.process = None
        self.temp_project = None
    
    def cleanup_orphaned_temp_files(self):
        """Clean up leftover temp project files"""
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
        """Start Burp Suite with REST API"""
        print("[*] Starting Burp Suite Professional with REST API...")
        
        self.cleanup_orphaned_temp_files()
        
        if self.is_running():
            print("[!] Previous Burp instance still running. Killing it...")
            self.kill()
            time.sleep(5)
        
        # Verify files exist
        if not os.path.exists(self.burp_jar):
            print(f"[!] ERROR: Burp JAR not found: {self.burp_jar}")
            return False
        
        if not os.path.exists(self.rest_api_jar):
            print(f"[!] ERROR: burp-rest-api JAR not found: {self.rest_api_jar}")
            return False
        
        try:
            self.temp_project = f"temp_burp_project_{int(time.time())}.burp"
            
            # Build command to start Burp with REST API
            cmd = [
                "java",
                "--add-opens=java.desktop/javax.swing=ALL-UNNAMED",
                "--add-opens=java.base/java.lang=ALL-UNNAMED",
                "--add-opens=java.base/java.io=ALL-UNNAMED",
                "-Xmx4g",  # Allocate 4GB RAM (adjust as needed)
                "-Djava.awt.headless=true",
                "-jar",
                self.rest_api_jar,
                f"--burp.jar={self.burp_jar}",
                f"--apikey={self.api_key}",
                "--headless.mode=true",
                f"--project-file={self.temp_project}"
            ]
            
            # Add config if exists
            if os.path.exists(self.config_file):
                cmd.append(f"--config-file={self.config_file}")
            
            print(f"[*] Burp JAR: {self.burp_jar}")
            print(f"[*] REST API JAR: {self.rest_api_jar}")
            print(f"[*] Project: {self.temp_project}")
            
            # Start Burp process
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            
            print(f"[+] Burp Suite started (PID: {self.process.pid})")
            print(f"[*] Running in HEADLESS mode (no GUI)")
            return True
            
        except Exception as e:
            print(f"[!] Failed to start Burp: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def is_running(self):
        """Check if our Burp process is alive"""
        if self.process is None:
            return False
        
        try:
            return psutil.pid_exists(self.process.pid) and self.process.poll() is None
        except:
            return False
    
    def kill(self):
        """Kill our Burp process and cleanup"""
        print("[*] Killing Burp Suite process...")
        
        if self.process is None:
            print("[!] No process to kill")
            time.sleep(2)
            return
        
        try:
            proc = psutil.Process(self.process.pid)
            
            # Kill children first
            children = proc.children(recursive=True)
            for child in children:
                try:
                    print(f"[*] Killing child process (PID: {child.pid})")
                    child.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            
            # Kill main process
            print(f"[*] Killing main Burp process (PID: {self.process.pid})")
            proc.kill()
            proc.wait(timeout=10)
            print(f"[+] Successfully killed Burp (PID: {self.process.pid})")
            
        except psutil.NoSuchProcess:
            print(f"[!] Process {self.process.pid} already dead")
        except psutil.TimeoutExpired:
            print(f"[!] Process didn't die gracefully, forcing...")
            try:
                proc.kill()
            except:
                pass
        except Exception as e:
            print(f"[!] Error killing process: {e}")
        
        finally:
            # Cleanup temp project
            if self.temp_project and os.path.exists(self.temp_project):
                try:
                    time.sleep(2)
                    os.remove(self.temp_project)
                    print(f"[+] Cleaned up: {self.temp_project}")
                except Exception as e:
                    print(f"[!] Failed to clean temp project: {e}")
            
            self.process = None
            time.sleep(3)
    
    def wait_for_api(self, timeout=120):
        """Wait for Burp REST API to be ready"""
        print("[*] Waiting for Burp REST API...")
        print("[*] This may take 30-90 seconds...")
        
        start_time = time.time()
        last_error = None
        
        while time.time() - start_time < timeout:
            try:
                if not self.is_running():
                    print("[!] Burp process died unexpectedly!")
                    return False
                
                response = requests.get(
                    f"{BURP_API_URL}/burp/versions",
                    headers=API_HEADERS,
                    timeout=5
                )
                
                if response.status_code == 200:
                    version_info = response.json()
                    print(f"[+] Burp API is ready!")
                    print(f"[+] Burp Version: {version_info.get('burpVersion', 'Unknown')}")
                    print(f"[+] REST API Version: {version_info.get('burpRestApiVersion', 'Unknown')}")
                    return True
                else:
                    last_error = f"HTTP {response.status_code}"
                    
            except requests.exceptions.ConnectionError:
                last_error = "Connection refused (API starting...)"
            except requests.exceptions.Timeout:
                last_error = "Timeout"
            except Exception as e:
                last_error = str(e)
            
            elapsed = int(time.time() - start_time)
            print(f"[*] Waiting... {elapsed}s - {last_error}")
            time.sleep(5)
        
        print(f"[!] Timeout after {timeout}s")
        print(f"[!] Last error: {last_error}")
        return False


class BurpAPIClient:
    """Burp REST API client"""
    
    def __init__(self, api_url, headers):
        self.api_url = api_url
        self.headers = headers
    
    def spider_scan(self, target_url):
        """Start spider/crawl scan"""
        print(f"[*] Starting spider scan: {target_url}")
        
        payload = {"baseUrl": target_url}
        
        try:
            response = requests.post(
                f"{self.api_url}/burp/spider",
                headers=self.headers,
                json=payload,
                timeout=30
            )
            
            if response.status_code == 201:
                print(f"[+] Spider started")
                return True
            else:
                print(f"[!] Spider failed: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            print(f"[!] Spider error: {e}")
            return False
    
    def wait_for_spider(self, timeout=1800):
        """Wait for spider to complete"""
        print(f"[*] Waiting for spider...")
        
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                response = requests.get(
                    f"{self.api_url}/burp/spider/status",
                    headers=self.headers,
                    timeout=10
                )
                
                if response.status_code == 200:
                    status = response.json()
                    progress = status.get('scanPercentage', 0)
                    print(f"[*] Spider: {progress}%")
                    
                    if progress >= 100:
                        print(f"[+] Spider completed")
                        return True
            except Exception as e:
                print(f"[!] Spider status error: {e}")
            
            time.sleep(10)
        
        print("[!] Spider timeout")
        return False
    
    def active_scan(self, target_url):
        """Start active vulnerability scan"""
        print(f"[*] Starting active scan: {target_url}")
        
        payload = {"baseUrl": target_url}
        
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
                print(f"[!] Active scan failed: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            print(f"[!] Active scan error: {e}")
            return False
    
    def wait_for_scan(self, timeout=3600):
        """Wait for active scan to complete"""
        print(f"[*] Waiting for active scan...")
        
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                response = requests.get(
                    f"{self.api_url}/burp/scanner/status",
                    headers=self.headers,
                    timeout=10
                )
                
                if response.status_code == 200:
                    status = response.json()
                    progress = status.get('scanPercentage', 0)
                    print(f"[*] Scan: {progress}%")
                    
                    if progress >= 100:
                        print(f"[+] Scan completed")
                        return True
            except Exception as e:
                print(f"[!] Scan status error: {e}")
            
            time.sleep(15)
        
        print("[!] Scan timeout")
        return False
    
    def get_issues(self):
        """Fetch all vulnerabilities found"""
        print(f"[*] Fetching vulnerabilities...")
        
        try:
            response = requests.get(
                f"{self.api_url}/burp/scanner/issues",
                headers=self.headers,
                timeout=30
            )
            
            if response.status_code == 200:
                issues = response.json()
                count = len(issues.get('issues', []))
                print(f"[+] Found {count} vulnerabilities")
                return issues
            else:
                print(f"[!] Failed to get issues: {response.status_code}")
                return {"issues": []}
                
        except Exception as e:
            print(f"[!] Error fetching issues: {e}")
            return {"issues": []}
    
    def get_sitemap(self):
        """Fetch sitemap data"""
        print(f"[*] Fetching sitemap...")
        
        try:
            response = requests.get(
                f"{self.api_url}/burp/target/sitemap",
                headers=self.headers,
                timeout=30
            )
            
            if response.status_code == 200:
                sitemap = response.json()
                print(f"[+] Sitemap retrieved")
                return sitemap
            else:
                print(f"[!] Sitemap failed: {response.status_code}")
                return {}
                
        except Exception as e:
            print(f"[!] Sitemap error: {e}")
            return {}


class XMLExporter:
    """Export scan results to XML"""
    
    @staticmethod
    def create_vulnerability_xml(issues, sitemap, target_url):
        """Create XML report with vulnerabilities"""
        root = ET.Element("burp_scan_report")
        
        # Scan info
        scan_info = ET.SubElement(root, "scan_info")
        ET.SubElement(scan_info, "target").text = target_url
        ET.SubElement(scan_info, "scan_date").text = datetime.now().isoformat()
        ET.SubElement(scan_info, "total_issues").text = str(len(issues.get('issues', [])))
        
        # Vulnerabilities
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
            
            # Details
            issue_detail = ET.SubElement(issue_elem, "issue_detail")
            issue_detail.text = str(issue.get('issueDetail', 'No details'))
            
            issue_background = ET.SubElement(issue_elem, "issue_background")
            issue_background.text = str(issue.get('issueBackground', 'No background'))
            
            remediation = ET.SubElement(issue_elem, "remediation")
            remediation.text = str(issue.get('remediationDetail', 'No remediation'))
            
            if 'references' in issue:
                refs = ET.SubElement(issue_elem, "references")
                refs.text = str(issue.get('references', ''))
        
        # Sitemap summary
        if sitemap:
            sitemap_elem = ET.SubElement(root, "sitemap_summary")
            ET.SubElement(sitemap_elem, "total_urls").text = str(len(sitemap.get('messages', [])))
        
        return root
    
    @staticmethod
    def prettify_xml(elem):
        """Pretty print XML"""
        rough_string = ET.tostring(elem, encoding='unicode')
        reparsed = minidom.parseString(rough_string)
        return reparsed.toprettyxml(indent="  ")
    
    def export(self, issues, sitemap, target_url, output_path):
        """Export to XML file"""
        print(f"[*] Exporting to: {output_path}")
        
        try:
            xml_root = self.create_vulnerability_xml(issues, sitemap, target_url)
            xml_string = self.prettify_xml(xml_root)
            
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(xml_string)
            
            print(f"[+] Export successful")
            print(f"[+] Vulnerabilities: {len(issues.get('issues', []))}")
            return True
            
        except Exception as e:
            print(f"[!] Export failed: {e}")
            return False


def read_websites(file_path):
    """Read target websites from file"""
    if not os.path.exists(file_path):
        print(f"[!] File not found: {file_path}")
        return []
    
    with open(file_path, 'r') as f:
        websites = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    
    print(f"[+] Loaded {len(websites)} websites")
    return websites


def sanitize_filename(url):
    """Convert URL to safe filename"""
    domain = url.replace('https://', '').replace('http://', '')
    domain = domain.replace('/', '-').replace(':', '-').replace('?', '-')
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    return f"{domain}_{timestamp}_scan.xml"


def main():
    """Main execution"""
    print("=" * 70)
    print("Burp Suite Professional - Automated Scanner")
    print("=" * 70)
    
    # Setup
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(INPUT_FILE), exist_ok=True)
    
    websites = read_websites(INPUT_FILE)
    if not websites:
        print("[!] No websites to scan")
        return
    
    # Initialize
    burp_manager = BurpManager(BURP_JAR_PATH, BURP_REST_API_JAR, BURP_API_KEY, CONFIG_FILE)
    api_client = BurpAPIClient(BURP_API_URL, API_HEADERS)
    xml_exporter = XMLExporter()
    
    # Process each website
    for idx, website in enumerate(websites, 1):
        print("\n" + "=" * 70)
        print(f"Processing {idx}/{len(websites)}: {website}")
        print("=" * 70)
        
        # Start Burp
        if not burp_manager.start():
            print(f"[!] Failed to start Burp. Skipping {website}")
            continue
        
        # Wait for API
        if not burp_manager.wait_for_api():
            print(f"[!] API not ready. Skipping {website}")
            burp_manager.kill()
            continue
        
        try:
            # Spider
            if api_client.spider_scan(website):
                api_client.wait_for_spider()
            
            # Active scan
            if api_client.active_scan(website):
                api_client.wait_for_scan()
            
            # Get results
            issues = api_client.get_issues()
            sitemap = api_client.get_sitemap()
            
            # Export
            output_file = os.path.join(OUTPUT_DIR, sanitize_filename(website))
            xml_exporter.export(issues, sitemap, website, output_file)
            
        except Exception as e:
            print(f"[!] Scan error: {e}")
            import traceback
            traceback.print_exc()
        
        # Kill Burp to free RAM
        burp_manager.kill()
        
        # Wait before next
        if idx < len(websites):
            print(f"\n[*] Waiting 5s before next scan...")
            time.sleep(5)
    
    print("\n" + "=" * 70)
    print("All scans completed!")
    print(f"Results in: {OUTPUT_DIR}/")
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