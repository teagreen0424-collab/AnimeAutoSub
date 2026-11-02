import requests
import json

# 1. Test /api/tasks
r = requests.get('http://127.0.0.1:8000/api/tasks')
print('GET /api/tasks status:', r.status_code)
d = r.json()
print('Total tasks returned:', d['data']['total'])
for t in d['data']['tasks'][:6]:
    print(f"  - [{t['status']}] {t['task_id']} | {t['title']} (legacy: {t['is_legacy']}, has_video: {t['has_video']})")

# 2. Test /api/tasks/work_ko_1080p_final
r2 = requests.get('http://127.0.0.1:8000/api/tasks/work_ko_1080p_final')
print('GET /api/tasks/work_ko_1080p_final status:', r2.status_code)
detail = r2.json()['data']
print('Stages in detail:', len(detail['stages']))
print('Products in detail:', len(detail['products']))

# 3. Test /api/tasks/114877-720p (legacy task)
r_leg = requests.get('http://127.0.0.1:8000/api/tasks/114877-720p')
print('GET /api/tasks/114877-720p status:', r_leg.status_code)
detail_leg = r_leg.json()['data']
print('Legacy task title:', detail_leg['title'])
print('Legacy task is_legacy:', detail_leg['is_legacy'])

# 4. Test /api/system/gpu
r3 = requests.get('http://127.0.0.1:8000/api/system/gpu')
print('GET /api/system/gpu status:', r3.status_code)
print('GPU data:', r3.json()['data'])

# 5. Test HTTP 206 Range on video
r4 = requests.get('http://127.0.0.1:8000/api/tasks/work_ko_1080p_final/video', headers={'Range': 'bytes=0-1023'})
print('GET video Range 0-1023 status:', r4.status_code)
print('Content-Range header:', r4.headers.get('Content-Range'))
print('Bytes returned:', len(r4.content))
assert r4.status_code == 206
assert len(r4.content) == 1024
print('All API assertions passed successfully!')
