import uvicorn
import socket

def get_local_ip():
    """Get local IP address"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

if __name__ == "__main__":
    local_ip = get_local_ip()
    print(f"\n🏈 NFL Stats App Starting...")
    print(f"📱 Share with friends: http://{local_ip}:8000")
    print(f"💻 Local access: http://localhost:8000")
    print(f"🔄 Press Ctrl+C to stop\n")
    
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)