#!/usr/bin/env python3

"""
Simple test script to debug Gotify notifications.
Run this with: source venv/bin/activate && python test_gotify.py
"""

import apprise
import sys
import os

# Add utils to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'utils'))

from config_loader import load_config

def test_gotify():
    """Test Gotify notification with detailed error reporting."""
    
    try:
        # Load config
        print("Loading configuration...")
        config = load_config()
        
        # Get Gotify URL
        apprise_urls = config.get('notifications', {}).get('apprise_urls', [])
        if not apprise_urls:
            print("❌ No Apprise URLs found in config!")
            return False
            
        print(f"Found {len(apprise_urls)} notification URL(s)")
        
        # Test each URL
        for i, url in enumerate(apprise_urls):
            print(f"\n--- Testing URL {i+1}: {url} ---")
            
            # Create Apprise object
            apobj = apprise.Apprise()
            
            # Modify URL for Gotify if needed
            if url.startswith("gotify://") and "format=markdown" not in url:
                separator = '&' if '?' in url else '?'
                modified_url = f"{url}{separator}format=markdown"
                print(f"Modified URL for Markdown: {modified_url}")
                apobj.add(modified_url)
            else:
                apobj.add(url)
            
            # Test notification
            print("Sending test notification...")
            success = apobj.notify(
                body="🧪 **Test Message**\n\nThis is a test notification from KeroTrack.\n\n- ✅ Connection test\n- 📊 Notification system\n- 🔧 Debug mode",
                title="KeroTrack Test",
                body_format=apprise.NotifyFormat.MARKDOWN
            )
            
            if success:
                print("✅ Notification sent successfully!")
                return True
            else:
                print("❌ Failed to send notification")
                
                # Try to get more detailed error info
                print("Attempting to get detailed error information...")
                try:
                    # Test with a simpler message
                    simple_success = apobj.notify(
                        body="Test message",
                        title="Test"
                    )
                    print(f"Simple message test: {'✅ Success' if simple_success else '❌ Failed'}")
                except Exception as e:
                    print(f"Error with simple message: {e}")
                
    except Exception as e:
        print(f"❌ Error during test: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return False

if __name__ == "__main__":
    print("🧪 KeroTrack Gotify Test Script")
    print("=" * 40)
    
    success = test_gotify()
    
    if success:
        print("\n✅ Gotify notification test PASSED")
        sys.exit(0)
    else:
        print("\n❌ Gotify notification test FAILED")
        sys.exit(1) 