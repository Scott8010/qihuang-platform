import sys
sys.path.insert(0, r"C:\Users\Administrator\Desktop\岐黄大脑\平台开发\qihuang_platform")
try:
    import requests
    print("requests OK")
except ImportError:
    print("requests NOT installed")

try:
    sys.path.insert(0, r"C:\Users\Administrator\.workbuddy\binaries\python\envs\default\Lib\site-packages")
    import requests
    print("requests OK (alt path)")
except ImportError:
    print("requests NOT installed (alt path)")
