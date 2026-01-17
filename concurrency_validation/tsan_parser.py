"""
ThreadSanitizer Output Parser

Parses TSan output to identify specific concurrency issues:
- Data races
- Deadlocks (lock-order-inversion)
- Mutex destruction while locked
- Thread leaks
"""

import re
from typing import Dict, List, Tuple


class TSanIssue:
    """Represents a single TSan-detected issue"""
    
    def __init__(self, issue_type: str, description: str, location: str = ""):
        self.issue_type = issue_type
        self.description = description
        self.location = location
    
    def __repr__(self):
        return f"TSanIssue({self.issue_type}, {self.location})"


def parse_tsan_output(output: str) -> Dict:
    """
    Parse ThreadSanitizer output and identify concurrency issues.
    
    Args:
        output: Combined stdout/stderr from program execution
        
    Returns:
        Dictionary with:
        - data_race: bool
        - deadlock: bool  
        - mutex_destruction: bool
        - thread_leak: bool
        - issues: List[TSanIssue] with details of each detected issue
    """
    
    result = {
        'data_race': False,
        'deadlock': False,
        'mutex_destruction': False,
        'thread_leak': False,
        'issues': []
    }
    
    # Pattern 1: Data Race
    # Example: "WARNING: ThreadSanitizer: data race (pid=1234)"
    data_race_pattern = r'ThreadSanitizer: data race'
    if re.search(data_race_pattern, output, re.IGNORECASE):
        result['data_race'] = True
        # Extract location information
        location_match = re.search(r'#0\s+(\S+)\s+(\S+):(\d+)', output)
        location = ""
        if location_match:
            func = location_match.group(1)
            file = location_match.group(2)
            line = location_match.group(3)
            location = f"{file}:{line} ({func})"
        
        result['issues'].append(TSanIssue(
            'data_race',
            'Data race detected',
            location
        ))
    
    # Pattern 2: Deadlock (lock-order-inversion)
    # Example: "WARNING: ThreadSanitizer: lock-order-inversion (potential deadlock)"
    deadlock_pattern = r'ThreadSanitizer:.*(?:lock-order-inversion|deadlock)'
    if re.search(deadlock_pattern, output, re.IGNORECASE):
        result['deadlock'] = True
        result['issues'].append(TSanIssue(
            'deadlock',
            'Lock-order-inversion (potential deadlock) detected',
            ''
        ))
    
    # Pattern 3: Mutex Destruction
    # Example: "WARNING: ThreadSanitizer: destroy of a locked mutex"
    mutex_destroy_pattern = r'ThreadSanitizer:.*destroy.*locked mutex'
    if re.search(mutex_destroy_pattern, output, re.IGNORECASE):
        result['mutex_destruction'] = True
        result['issues'].append(TSanIssue(
            'mutex_destruction',
            'Destruction of locked mutex detected',
            ''
        ))
    
    # Pattern 4: Thread Leak
    # Example: "WARNING: ThreadSanitizer: thread leak"
    thread_leak_pattern = r'ThreadSanitizer:.*thread leak'
    if re.search(thread_leak_pattern, output, re.IGNORECASE):
        result['thread_leak'] = True
        result['issues'].append(TSanIssue(
            'thread_leak',
            'Thread leak detected',
            ''
        ))
    
    return result


def format_issues_for_csv(issues: List[TSanIssue]) -> str:
    """
    Format list of issues for CSV output.
    
    Args:
        issues: List of TSanIssue objects
        
    Returns:
        Pipe-separated string of issue types
    """
    if not issues:
        return "none"
    
    issue_types = [issue.issue_type for issue in issues]
    return "|".join(sorted(set(issue_types)))


def get_detected_issue_list(result: Dict) -> List[str]:
    """
    Get list of detected issue types from parse result.
    
    Args:
        result: Dictionary returned by parse_tsan_output()
        
    Returns:
        List of issue type strings
    """
    detected = []
    if result['data_race']:
        detected.append('data_race')
    if result['deadlock']:
        detected.append('deadlock')
    if result['mutex_destruction']:
        detected.append('mutex_destruction')
    if result['thread_leak']:
        detected.append('thread_leak')
    
    return detected if detected else ['none']


if __name__ == "__main__":
    # Test with sample TSan output
    sample_output = """
==================
WARNING: ThreadSanitizer: data race (pid=12345)
  Write of size 4 at 0x7fff1234 by thread T2:
    #0 increment counter.c:17
  Previous write of size 4 at 0x7fff1234 by thread T1:
    #0 increment counter.c:17
==================
    """
    
    result = parse_tsan_output(sample_output)
    print("Parse Result:", result)
    print("Detected Issues:", get_detected_issue_list(result))
    print("CSV Format:", format_issues_for_csv(result['issues']))
