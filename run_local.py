import argparse
import os
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
    parser = argparse.ArgumentParser(description="Run the NFL Stats app locally")
    parser.add_argument(
        "--host",
        default=os.getenv("HOST", "127.0.0.1"),
        help="Interface to bind (default: HOST env var or 127.0.0.1). Use 0.0.0.0 to share on your LAN.",
    )
    args = parser.parse_args()

    print(f"\n🏈 NFL Stats App Starting...")
    print(f"💻 Local access: http://localhost:8000")
    if args.host in ("127.0.0.1", "localhost"):
        print(f"🔒 Only reachable from this computer. Use --host 0.0.0.0 (or HOST=0.0.0.0) to share on your LAN.")
    else:
        local_ip = get_local_ip()
        print(f"📱 Share with friends: http://{local_ip}:8000")
        print(f"⚠️  The app is visible to everyone on your network while it runs.")
    print(f"🔄 Press Ctrl+C to stop\n")
    
    uvicorn.run("app:app", host=args.host, port=8000, reload=True)
