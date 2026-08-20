import requests

from app.utils.operational_errors import RECOVERABLE_ERRORS

# CDN URL from the image message
cdn_url = "https://vweixinf.tc.qq.com/weixin-android/s/tmp/mmsns/3057020100044b304902010002041d3bf20d02032f53a3020433752d70020469bfaba5042464303638643365302d303934312d346166652d613632622d373536313739346564306164020405152a010201000405004c4d9b00"

print("Testing CDN access...")
try:
    resp = requests.head(cdn_url, timeout=5)
    print(f"Status: {resp.status_code}")
    print(f"Headers: {dict(resp.headers)}")
except RECOVERABLE_ERRORS as e:  # noqa: BLE001 - script boundary records arbitrary integration failures
    print(f"Error: {e}")

# Also try the video CDN URL
video_url = "https://vweixinf.tc.qq.com/weixin-android/s/tmp/mmsns/3057020100044b304902010002041d3bf20d02032dcd0302044f1daa24020469bc16ab042434396362383930382d326162642d346165302d383361342d39313564636334393463613302040d1808040201000405004c57c300"
print("\nTesting video CDN access...")
try:
    resp = requests.head(video_url, timeout=5)
    print(f"Status: {resp.status_code}")
except RECOVERABLE_ERRORS as e:  # noqa: BLE001 - script boundary records arbitrary integration failures
    print(f"Error: {e}")
