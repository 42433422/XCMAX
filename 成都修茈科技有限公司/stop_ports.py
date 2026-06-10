import subprocess
import re

def stop_processes_on_port(port):
    # 使用netstat命令获取占用指定端口的进程
    result = subprocess.run(
        ['netstat', '-ano'],
        capture_output=True,
        text=True
    )
    
    # 解析输出，找到占用指定端口的进程ID
    pattern = rf':{port}\s+.*LISTENING\s+(\d+)'
    matches = re.findall(pattern, result.stdout)
    
    for pid in matches:
        try:
            # 使用taskkill命令终止进程
            subprocess.run(
                ['taskkill', '/PID', pid, '/F'],
                capture_output=True,
                text=True
            )
            print(f"已终止进程 {pid}")
        except Exception as e:
            print(f"终止进程 {pid} 失败: {e}")

if __name__ == "__main__":
    print("停止占用9999端口的进程...")
    stop_processes_on_port(9999)
    print("停止占用8765端口的进程...")
    stop_processes_on_port(8765)
    print("完成")
