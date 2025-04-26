import sys
import ujson as json

data = json.loads(sys.stdin.read())
for key, value in data.items():
    print(f"{key} {value}")