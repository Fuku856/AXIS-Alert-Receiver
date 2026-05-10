import time
from axis_client import AxisClient
import config

def on_msg(channel, msg):
    print(f"MSG: [{channel}] {msg}")

def on_status(status):
    print(f"STATUS: {status}")

client = AxisClient(on_msg, on_status)
print("Starting client...")
client.start()

try:
    time.sleep(10)
except KeyboardInterrupt:
    pass

client.stop()
print("Done.")
