

# Burp Suite Automated Multi-Target Scanner

A production-grade automation framework for running **Burp Suite Professional scans** against multiple targets using Burp’s **official REST API**, with intelligent pause handling, automatic recovery, and structured result exporting.

This tool is designed for **long-running, unattended security scanning** in a stable and controlled manner.

---

## Overview

This project automates Burp Suite Professional to:

* Launch Burp with a predefined project template (`fix.burp`)
* Automatically start scans for multiple targets
* Monitor scan progress via Burp’s REST API
* Detect paused scans and attempt automatic resume
* Abort safely if a scan remains paused too long
* Export full or partial scan results in formatted JSON
* Repeat the process for multiple websites sequentially

The script is built to be **robust, fault-tolerant, and suitable for large scanning workloads**.

---

## Main Script

**Entry point:** `main.py`

This script orchestrates the entire scanning workflow:

* Starts Burp
* Creates scans
* Monitors execution
* Handles failures and timeouts
* Exports results
* Moves to the next target automatically

---

## Key Features

### 1. Multi-Target Scanning

Reads a list of websites from:

```
input/websites.txt
```

Each target is scanned in sequence using a fresh Burp project instance.

---

### 2. Official Burp REST API Integration

All scan control and monitoring is done through Burp’s built-in API:

* Start scan: `/v0.1/scan`
* Monitor scan: `/v0.1/scan/{task_id}`
* Resume scan: `/v0.1/scan/{task_id}/resume`

No unofficial hacks or extensions are used.

---

### 3. Automatic Pause Detection & Recovery

If Burp pauses a scan:

* The script detects the `paused` status
* Attempts to resume using the API
* Tracks how long the scan remains paused

If a scan stays paused longer than the configured timeout, it:

* Aborts further execution for that target
* Saves partial results
* Moves on to the next target (no infinite retry loops)

---

### 4. Safe Burp Project Handling

For every target:

1. A temporary project file is created.
2. The template project `config/fix.burp` is copied.
3. Burp is launched using that project.
4. Scheduled tasks and configuration from the template are preserved.

This ensures consistent scan behavior across targets.

---

### 5. Stable Long-Run Operation

The script includes several stability safeguards:

* Forces Windows to stay awake (prevents sleep/lock)
* Uses G1GC and JVM memory limits for stability
* Waits for Burp UI and API to fully initialize
* Handles process termination safely
* Stores detailed logs for debugging

---

## Project Structure

```
project_root/
│
├── main.py                  # Main automation script
├── burpsuite_pro.jar        # Burp Suite Professional JAR
│
├── config/
│   ├── fix.burp             # Burp project template
│   ├── scan_template.json   # Optional scan configuration
│   └── burp_config.json     # Optional Burp runtime config
│
├── input/
│   └── websites.txt         # List of targets (one per line)
│
├── output/
│   ├── scan_*.json          # Scan results
│   └── burp_projects_temp/  # Temporary Burp project files
│
└── logs/
    └── burp_scanner_*.log   # Execution logs
```

---

## Requirements

### Software

* **Burp Suite Professional**
* **Java 21+**
* **Python 3.9+**
* Windows (sleep-prevention logic is Windows-specific)

### Python Dependencies

Install with:

```bash
pip install -r requirements.txt
```

`requirements.txt`:

```
requests==2.31.0
psutil==5.9.6
```

---

## Setup

### 1. Place Burp JAR

Put your Burp Pro JAR in the project root and name it:

```
burpsuite_pro.jar
```

---

### 2. Add Targets

Edit:

```
input/websites.txt
```

Example:

```
https://example.com
testphp.vulnweb.com
```

(If protocol is missing, `https://` is automatically added.)

---

### 3. Prepare Template Project

Place your configured Burp project here:

```
config/fix.burp
```

This project can include:

* Scan configurations
* Scheduled tasks
* Custom project settings

---

### 4. (Optional) Scan Template

You may define detailed scan behavior in:

```
config/scan_template.json
```

If present, it is automatically injected into scan creation requests.

---

## Running the Scanner

From the project root:

```bash
python main.py
```

The script will:

1. Validate environment and files
2. Launch Burp
3. Scan each target sequentially
4. Save results in the `output/` folder

---

## Output

### Scan Results

Saved as formatted JSON:

```
output/scan_<target>_<timestamp>.json
```

If a scan is aborted due to timeout:

```
output/scan_<target>_<timestamp>_INCOMPLETE.json
```

---

### Logs

Detailed execution logs are stored in:

```
logs/burp_scanner_<timestamp>.log
```

These logs include:

* Burp startup details
* Scan progress updates
* Pause recovery attempts
* Errors and stack traces

---

## Timeout & Retry Behavior

| Situation            | Behavior                              |
| -------------------- | ------------------------------------- |
| Scan succeeds        | Results exported normally             |
| Scan fails           | Retries (up to configured attempts)   |
| Scan paused briefly  | Auto resume attempted                 |
| Scan paused too long | Partial results saved, target skipped |
| Burp fails to start  | Retry (limited attempts)              |

---

## Safety Notes

* Designed for **authorized security testing only**
* Ensure you have permission to scan all listed targets
* Long scans can be resource-intensive (CPU, RAM, disk)

---

## Summary

This tool turns Burp Suite into a **controlled, automated scanning engine** suitable for:

* Batch security assessments
* Continuous testing environments
* Large target lists
* Long unattended scan sessions

It focuses on **reliability, controlled execution, and clean result handling** rather than speed alone.

---
