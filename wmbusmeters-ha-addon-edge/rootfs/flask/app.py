import json, requests, os, re, base64, zipfile, xmltodict
from flask import Flask, jsonify, render_template, request, redirect, url_for
from waitress import serve
from threading import Thread
from xml.dom import minidom
from io import BytesIO
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

app = Flask(__name__, static_url_path='')

cfgfile = '/data/options_custom.json'
DRIVER_DIRECTORY = '/data/drivers'
RESTART_URL = "http://supervisor/addons/self/restart"
URL_HEADER = { "Authorization": "Bearer " + os.environ.get('SUPERVISOR_TOKEN'), "content-type": "application/json" }

@app.route('/', methods=['GET', 'POST'])
def index():
    return render_template('index.html')
	
@app.route('/kem', methods=['GET', 'POST'])
def kem():
    return render_template('kem.html')

@app.route('/save_json', methods=['POST'])
def save_json_to_file():
    try:
        request_json = request.json
        data = request_json['data']
        with open(cfgfile, 'w') as file:
            json.dump(data, file, indent=True)

    except ValueError as e:
        error_message = str(e)
        return jsonify({'error': error_message}), 400

    Thread(target=restart_call, args=()).start()

    return jsonify({'message': 'Config saved and addon restarted successfully.'})

def restart_call():
    requests.post(RESTART_URL, headers=URL_HEADER)

@app.route('/get_json')
def get_json():
    try:
        with open(cfgfile, 'r') as file:
            data = json.load(file)
            return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
		
@app.route('/decrypt', methods=['POST'])
def decrypt():
    file = request.files['file']
    filename = request.files['file'].filename
    password = request.form['password']
    
    kem_file_content = None

    if (zipfile.is_zipfile(file)):
        with zipfile.ZipFile(file,'r') as zipobj:
            file_list = zipobj.namelist()
            for file_name in file_list:
                if file_name.endswith('.kem') or file_name.endswith('.kem2'):
                    kem_file_content = zipobj.read(file_name)
			
            if (not kem_file_content):
                return jsonify({"ERROR": "The zip file '%s' does not seem to contain any '.kem' file." % (filename)})
    else:
        file.seek(0)
        kem_file_content = file.read()

    try:
        xmldoc = minidom.parseString(kem_file_content)
        encrypedtext = xmldoc.getElementsByTagName('CipherValue')[0].firstChild.nodeValue
        encrypeddata = base64.b64decode(encrypedtext)
    except:
        return jsonify({"ERROR": "The file '%s' does not seem to contain valid data - decryption failed." % (filename)})

    data = BytesIO(file.read())

    key = bytes(str(password).encode('utf-8'))
    if (len(key) < 16): key += (16-len(key)) * b'\0'

    backend = default_backend()
    cipher = Cipher(algorithms.AES(key), modes.CBC(key), backend=backend)
    decryptor = cipher.decryptor()
    decryptedtext = decryptor.update(encrypeddata) + decryptor.finalize()

    try:
        decodedtext = decryptedtext.decode('utf-8')
    except UnicodeDecodeError:
        return jsonify({'ERROR': 'Looks like password is wrong - decryption failed!'})

    trimmedText = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\xff]', '', decryptedtext.decode('utf-8'))
    data_dict = xmltodict.parse(trimmedText)
    json_data = json.dumps(data_dict)
    resp = json.loads(json_data)
    if 'MetersInOrder' in resp:
        meterid = resp['MetersInOrder']['Meter']['MeterNo']
        meterkey = resp['MetersInOrder']['Meter']['EncKeys']['DEK']
        return jsonify({'OK': {'id': meterid, 'key': meterkey}})
    elif 'Devices' in resp:
        meterid = resp['Devices']['Device']['DeviceId']['SerialNumber']
        meterkey = resp['Devices']['Device']['Keys']['Key']['Value']
        return jsonify({'OK': {'id': meterid, 'key': meterkey}})	
    else:
        return jsonify({'ERROR': 'Unable to extract details from file'})
        
@app.route('/drivers')
def drivers():
    files = os.listdir(DRIVER_DIRECTORY)
    return render_template('drivers.html', files=files)

@app.route('/edit_driver/<filename>', methods=['GET', 'POST'])
def edit_driver(filename):
    filepath = os.path.join(DRIVER_DIRECTORY, filename)
    if request.method == 'POST':
        content = request.form['content']
        with open(filepath, 'w') as f:
            f.write(content)
        return redirect(url_for('drivers'))

    with open(filepath, 'r') as f:
        content = f.read()
    return render_template('edit_driver.html', filename=filename, content=content)

@app.route('/add_driver', methods=['GET', 'POST'])
def add_driver():
    if request.method == 'POST':
        filename = request.form['filename']
        content = request.form['content']
        filepath = os.path.join(DRIVER_DIRECTORY, filename)
        with open(filepath, 'w') as f:
            f.write(content)
        return redirect(url_for('drivers'))
    return render_template('add_driver.html', filename='', content='')

@app.route('/delete_driver/<filename>', methods=['POST'])
def delete_driver(filename):
    filepath = os.path.join(DRIVER_DIRECTORY, filename)
    if os.path.exists(filepath):
        os.remove(filepath)
    return redirect(url_for('drivers'))
    
@app.route('/check_filename', methods=['POST'])
def check_filename():
    data = request.json
    filename = data.get('filename')
    if not filename:
        return jsonify({'error': 'No filename provided'}), 400
    file_path = os.path.join(DRIVER_DIRECTORY, filename)
    if os.path.exists(file_path):
        return jsonify({'exists': True})
    else:
        return jsonify({'exists': False})

if __name__ == '__main__':
    serve(app, host="127.0.0.1", port=5000)