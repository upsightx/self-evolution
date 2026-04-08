import os
import json
import glob
import time
from datetime import datetime, timedelta

LOG_DIR = os.path.expanduser("~/.openclaw/logs")

def get_today_usage():
    today_str = datetime.now().strftime("%Y-%m-%d")
    total_input = 0
    total_output = 0
    
    # 查找今天的日志文件 (文件名格式通常为 log-YYYY-MM-DD.json)
    log_files = glob.glob(os.path.join(LOG_DIR, f"*{today_str}*.json"))
    
    # 如果日志目录结构不同，尝试查找最新的 log 文件
    if not log_files:
        log_files = glob.glob(os.path.join(LOG_DIR, "*.json"))
        log_files.sort(key=os.path.getmtime, reverse=True)
        log_files = log_files[:5]  # 只检查最近的5个文件以防万一

    for log_file in log_files:
        try:
            with open(log_file, 'r') as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                        # 检查条目是否包含 usage 信息
                        if 'usage' in entry:
                            usage = entry['usage']
                            if isinstance(usage, dict):
                                in_tokens = usage.get('prompt_tokens', 0) or usage.get('input_tokens', 0)
                                out_tokens = usage.get('completion_tokens', 0) or usage.get('output_tokens', 0)
                                total_input += in_tokens
                                total_output += out_tokens
                    except json.JSONDecodeError:
                        continue
        except Exception:
            continue
            
    return total_input, total_output

if __name__ == "__main__":
    start_time = time.time()
    inp, out = get_today_usage()
    duration = time.time() - start_time
    print(f"今日 Token 统计 (耗时: {duration:.2f}s):")
    print(f"输入 (Input):  {inp:,}")
    print(f"输出 (Output): {out:,}")
    print(f"总计 (Total):  {inp + out:,}")
