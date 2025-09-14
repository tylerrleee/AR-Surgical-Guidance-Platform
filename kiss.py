#!/usr/bin/env python3
from flask import Flask, request
app = Flask(__name__)
img = ''

@app.route('/')
def index():
    return f'<img src="data:image/jpeg;base64,{img}" style="width:100%">'

@app.route('/frame', methods=['POST'])
def frame():
    global img
    img = request.json['img']
    return 'ok'

app.run(host='0.0.0.0', port=5000)