#!/usr/bin/env python3

"""
Network connectivity test for Gotify server.
Run this with: source venv/bin/activate && python test_connectivity.py
"""

import socket
import requests
import sys
import os

# Add utils to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'utils'))

from config_loader import load_config

def test_connectivity():
    """Test network connectivity to Gotify server."""
    
    try:
        # Load config
        print("Loading configuration...")
        config = load_config()
        
        # Get Gotify URL
        apprise_urls = config.get('notifications', {}).get('apprise_urls', [])
        if not apprise_urls:
            print("❌ No Apprise URLs found in config!")
            return False
        
        for i, url in enumerate(apprise_urls):
            print(f"\n--- Testing connectivity for URL {i+1}: {url} ---")
            
            # Parse URL
            if url.startswith("gotify://"):
                # Extract host and port
                url_parts = url.replace("gotify://", "").split("/")
                host_port = url_parts[0]
                
                if ":" in host_port:
                    host, port = host_port.split(":")
                    port = int(port)
                else:
                    host = host_port
                    port = 80  # Default HTTP port
                    
                print(f"Host: {host}")
                print(f"Port: {port}")
                
                # Test 1: Basic socket connection
                print(f"\n1. Testing socket connection to {host}:{port}...")
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(10)
                    result = sock.connect_ex((host, port))
                    sock.close()
                    
                    if result == 0:
                        print("✅ Socket connection successful")
                    else:
                        print(f"❌ Socket connection failed (error code: {result})")
                        return False
                except Exception as e:
                    print(f"❌ Socket connection error: {e}")
                    return False
                
                # Test 2: HTTP GET request
                print(f"\n2. Testing HTTP GET request to {host}:{port}...")
                try:
                    protocol = "https" if port == 443 else "http"
                    test_url = f"{protocol}://{host}:{port}"
                    
                    response = requests.get(test_url, timeout=10, verify=False)
                    print(f"✅ HTTP request successful (Status: {response.status_code})")
                    
                    if response.status_code == 200:
                        print("✅ Gotify server appears to be responding")
                    else:
                        print(f"⚠️  Gotify server responded with status {response.status_code}")
                        
                except requests.exceptions.SSLError:
                    print("⚠️  SSL/TLS error - trying HTTP instead...")
                    try:
                        test_url = f"http://{host}:{port}"
                        response = requests.get(test_url, timeout=10)
                        print(f"✅ HTTP request successful (Status: {response.status_code})")
                    except Exception as e:
                        print(f"❌ HTTP request failed: {e}")
                        return False
                        
                except Exception as e:
                    print(f"❌ HTTP request failed: {e}")
                    return False
                
                # Test 3: DNS resolution
                print(f"\n3. Testing DNS resolution for {host}...")
                try:
                    ip = socket.gethostbyname(host)
                    print(f"✅ DNS resolution successful: {host} -> {ip}")
                except Exception as e:
                    print(f"❌ DNS resolution failed: {e}")
                    return False
                
            elif url.startswith("gotifys://"):
                # HTTPS Gotify
                url_parts = url.replace("gotifys://", "").split("/")
                host_port = url_parts[0]
                
                if ":" in host_port:
                    host, port = host_port.split(":")
                    port = int(port)
                else:
                    host = host_port
                    port = 443  # Default HTTPS port
                    
                print(f"Host: {host}")
                print(f"Port: {port}")
                
                # Test HTTPS connection
                print(f"\n1. Testing HTTPS connection to {host}:{port}...")
                try:
                    test_url = f"https://{host}:{port}"
                    response = requests.get(test_url, timeout=10, verify=False)
                    print(f"✅ HTTPS request successful (Status: {response.status_code})")
                except Exception as e:
                    print(f"❌ HTTPS request failed: {e}")
                    return False
                    
        return True
        
    except Exception as e:
        print(f"❌ Error during connectivity test: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🌐 KeroTrack Connectivity Test Script")
    print("=" * 40)
    
    success = test_connectivity()
    
    if success:
        print("\n✅ Connectivity test PASSED")
        print("Network connectivity to Gotify server appears to be working.")
        sys.exit(0)
    else:
        print("\n❌ Connectivity test FAILED")
        print("There are network connectivity issues to the Gotify server.")
        sys.exit(1) 