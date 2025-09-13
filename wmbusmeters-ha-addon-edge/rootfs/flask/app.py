import json, requests, os, re, base64, zipfile, xmltodict, subprocess
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
    try:
        subprocess.run(['s6-svc', '-r', '/run/service/wmbusmeters'], check=True)
        print("wmbusmeters service restarted successfully.")
    except subprocess.CalledProcessError as e:
        print(f"Failed to restart wmbusmeters service: {e}")

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
    filename = file.filename
    password = request.form['password']

    try:
        file_bytes = file.read()
    except Exception as e:
        return jsonify({"ERROR": f"Failed to read input file '{filename}': {e}"}), 400

    kem_file_content = None
    try:
        if zipfile.is_zipfile(BytesIO(file_bytes)):
            with zipfile.ZipFile(BytesIO(file_bytes), 'r') as zipobj:
                for name in zipobj.namelist():
                    if name.lower().endswith(('.kem', '.kem2')):
                        kem_file_content = zipobj.read(name)
                        break
            if not kem_file_content:
                return jsonify({"ERROR": f"The zip file '{filename}' does not seem to contain any '.kem' file."})
        else:
            kem_file_content = file_bytes
    except Exception as e:
        return jsonify({"ERROR": f"Error reading '{filename}': {e}"}), 400

    try:
        xmldoc = minidom.parseString(kem_file_content)
        encrypedtext = xmldoc.getElementsByTagName('CipherValue')[0].firstChild.nodeValue
        encrypeddata = base64.b64decode(encrypedtext)
    except Exception:
        return jsonify({"ERROR": f"The file '{filename}' does not seem to contain valid data - decryption failed."})

    key = bytes(str(password).encode('utf-8'))
    if len(key) < 16:
        key += (16 - len(key)) * b'\0'
    elif len(key) > 16:
        key = key[:16]

    backend = default_backend()
    cipher = Cipher(algorithms.AES(key), modes.CBC(key), backend=backend)
    decryptor = cipher.decryptor()
    decryptedtext = decryptor.update(encrypeddata) + decryptor.finalize()

    try:
        _ = decryptedtext.decode('utf-8')
    except UnicodeDecodeError:
        return jsonify({'ERROR': 'Looks like password is wrong - decryption failed!'})

    trimmedText = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\xff]', '', decryptedtext.decode('utf-8'))
    try:
        resp = xmltodict.parse(trimmedText)
    except Exception as e:
        return jsonify({'ERROR': f'Unable to parse decrypted XML: {e}'}), 400

    def as_list(x):
        return x if isinstance(x, list) else [x]

    def pick_first_key(keys_node):
        if not isinstance(keys_node, dict):
            return None
        k = keys_node.get('Key')
        if isinstance(k, list):
            for item in k:
                t = item.get('@Type') or item.get('Type')
                v = item.get('Value')
                if v and (t == 'DEK'):
                    return v
            for item in k:
                if item.get('Value'):
                    return item['Value']
            return None
        if isinstance(k, dict):
            return k.get('Value')
        return None

    meters = []

    if 'MetersInOrder' in resp:
        meters_node = resp['MetersInOrder'].get('Meter', [])
        for m in as_list(meters_node):
            meterid = m.get('MeterNo') or m.get('SerialNo')
            meterkey = None
            enc = m.get('EncKeys')
            if isinstance(enc, dict):
                meterkey = enc.get('DEK') or enc.get('DEKKey') or enc.get('Key')
            if not meterkey:
                meterkey = m.get('DEK')
            if meterid and meterkey:
                meters.append({'id': meterid, 'key': meterkey})

    elif 'Devices' in resp:
        devices_node = resp['Devices'].get('Device', [])
        for d in as_list(devices_node):
            meterid = None
            did = d.get('DeviceId')
            if isinstance(did, dict):
                meterid = did.get('SerialNumber') or did.get('Id')
            meterid = meterid or d.get('SerialNumber') or d.get('CustomerDeviceNumber')
            meterkey = pick_first_key(d.get('Keys')) or d.get('Value')
            if meterid and meterkey:
                meters.append({'id': meterid, 'key': meterkey})
    else:
        return jsonify({'ERROR': 'Unable to extract details from file'})

    if not meters:
        return jsonify({'ERROR': 'No meters found in the decrypted file'})

    if len(meters) == 1:
        return jsonify({'OK': meters[0]})
    return jsonify({'OK': meters})
        
@app.route('/drivers')
def drivers():
    try:
        files = os.listdir(DRIVER_DIRECTORY)
        return render_template('drivers.html', files=files)
    except Exception as e:
        print(f"Error listing drivers: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/add_driver', methods=['GET', 'POST'])
def add_driver():
    if request.method == 'POST':
        filename = request.form['filename']
        content = request.form['content']
        filepath = os.path.join(DRIVER_DIRECTORY, filename)
        try:
            with open(filepath, 'w') as f:
                f.write(content)
            Thread(target=restart_call, args=()).start()
            return jsonify({'status': 'success', 'redirect_url': url_for('drivers')})
        except Exception as e:
            print(f"Error adding driver {filename}: {e}")
            return jsonify({'status': 'error', 'message': str(e)}), 500
    return render_template('add_driver.html', filename='', content='')

@app.route('/edit_driver/<filename>', methods=['GET', 'POST'])
def edit_driver(filename):
    filepath = os.path.join(DRIVER_DIRECTORY, filename)
    if request.method == 'POST':
        content = request.form['content']
        try:
            with open(filepath, 'w') as f:
                f.write(content)
            Thread(target=restart_call, args=()).start()
            return jsonify({'status': 'success', 'redirect_url': url_for('drivers')})
        except Exception as e:
            print(f"Error editing driver {filename}: {e}")
            return jsonify({'status': 'error', 'message': str(e)}), 500
    try:
        with open(filepath, 'r') as f:
            content = f.read()
    except FileNotFoundError:
        abort(404)
    return render_template('edit_driver.html', filename=filename, content=content)

@app.route('/delete_driver/<filename>', methods=['POST'])
def delete_driver(filename):
    filepath = os.path.join(DRIVER_DIRECTORY, filename)
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
        Thread(target=restart_call, args=()).start()
        return jsonify({'status': 'success', 'redirect_url': url_for('drivers')})
    except Exception as e:
        print(f"Error deleting driver {filename}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/check_filename', methods=['POST'])
def check_filename():
    data = request.json
    filename = data.get('filename')
    if not filename:
        return jsonify({'error': 'No filename provided'}), 400
    file_path = os.path.join(DRIVER_DIRECTORY, filename)
    if os.path.exists(file_path):
        return jsonify({'exists': True})
    return jsonify({'exists': False})

if __name__ == '__main__':
    serve(app, host="127.0.0.1", port=5000)
