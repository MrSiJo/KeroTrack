#!/usr/bin/env python3

"""
Minimal Gotify test script.
"""

import apprise
import sys
import os

# Add utils to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'utils'))

from config_loader import load_config

def simple_test():
    """Send a very simple test notification."""
    
    try:
        # Load config
        config = load_config()
        apprise_urls = config.get('notifications', {}).get('apprise_urls', [])
        
        if not apprise_urls:
            print("No Apprise URLs found!")
            return False
            
        url = apprise_urls[0]
        print(f"Testing URL: {url}")
        
        # Create Apprise object
        apobj = apprise.Apprise()
        
        # Add URL with markdown format for Gotify
        if url.startswith("gotify://") and "format=markdown" not in url:
            separator = '&' if '?' in url else '?'
            modified_url = f"{url}{separator}format=markdown"
            print(f"Modified URL: {modified_url}")
            apobj.add(modified_url)
        else:
            apobj.add(url)
        
        # Send simple test
        print("Sending simple test notification...")
        success = apobj.notify(
            body="🔔 **SIMPLE TEST**\n\nThis is a simple test notification.\n\nTimestamp: " + str(apprise.datetime.now()),
            title="KeroTrack Simple Test",
            body_format=apprise.NotifyFormat.MARKDOWN
        )
        
        if success:
            print("✅ SUCCESS: Notification sent!")
            return True
        else:
            print("❌ FAILED: Notification not sent!")
            return False
            
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🔔 Simple Gotify Test")
    print("=" * 30)
    
    success = simple_test()
    
    if success:
        print("\n✅ Test completed successfully!")
        print("Check your Gotify app/device for the notification.")
    else:
        print("\n❌ Test failed!")
    
    sys.exit(0 if success else 1) 