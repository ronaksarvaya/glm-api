import requests
import json

response = requests.post("http://127.0.0.1:5000/api/process", json={"stream": True}, stream=True)
print(response.status_code)
for line in response.iter_lines():
    if line:
        print(line.decode('utf-8'))
        break
