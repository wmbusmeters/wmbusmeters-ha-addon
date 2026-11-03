import json, requests, os, re, base64, zipfile, xmltodict, subprocess, time
from flask import Flask, jsonify, render_template, request, redirect, url_for
from waitress import serve
from threading import Thread
from xml.dom import minidom
from io import BytesIO
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
import discovery_files
import tempfile

app = Flask(__name__, static_url_path='')

cfgfile = '/data/options_custom.json'
DRIVER_DIRECTORY = '/data/drivers'

SUPERVISOR_URL = os.environ.get("SUPERVISOR", "http://supervisor")
SUPERVISOR_TOKEN = os.environ["SUPERVISOR_TOKEN"]

def get_addon_slug() -> str:
    # Right after an add-on update the Supervisor can be too busy to answer within
    # a few seconds, so retry for up to two minutes instead of failing at once.
    delay = 2
    deadline = time.monotonic() + 120
    while True:
        try:
            r = requests.get(
                f"{SUPERVISOR_URL}/addons/self/info",
                headers={"Authorization": f"Bearer {SUPERVISOR_TOKEN}"},
                timeout=10,
            )
            r.raise_for_status()
            return r.json()["data"]["slug"]
        except requests.RequestException as e:
            if time.monotonic() + delay > deadline:
                # The slug is only used for the Logs link. The container hostname
                # is the slug with "-" instead of the first "_".
                slug = os.environ.get("HOSTNAME", "").replace("-", "_", 1)
                print(f"Could not get the add-on slug from the Supervisor ({e}), using {slug!r}", flush=True)
                return slug
            print(f"Supervisor not answering yet ({e}), retrying in {delay} s", flush=True)
            time.sleep(delay)
            delay = min(delay * 2, 30)

ADDON_SLUG = get_addon_slug()

@app.context_processor
def inject_addon_slug():
    return {"addon_slug": ADDON_SLUG}

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

# --- MQTT discovery of a meter in the "manual" mode -----------------------------
# The panel prepares the discovery of one meter as a draft (from the generated
# discovery, or an uploaded file) and applies it: the draft is published, the
# discovery of the meter that the draft does not hold any more is removed, the
# draft becomes the applied configuration and the meter's mode becomes "manual".
# mqtt_discovery.sh publishes the applied configuration again at every start.
# See discovery_files.py and the "MQTT discovery" section of DOCS.md.

MQTT_BATCH = '/wmbusmeters/mosquitto_batch.sh'


def panel_log(message, level='INFO'):
    """A line in the add-on log, in the format of the bashio lines around it."""
    print(f"[{time.strftime('%H:%M:%S')}] {level}: panel: {message}", flush=True)
MQTT_RETAINED = '/wmbusmeters/mosquitto_retained.sh'
DISCOVERY_PREFIX_FILE = '/wmbusmeters/discovery_prefix'


def discovery_prefix():
    try:
        with open(DISCOVERY_PREFIX_FILE) as f:
            prefix = f.read().strip()
            return prefix or 'homeassistant'
    except OSError:
        return 'homeassistant'


def read_config():
    with open(cfgfile, 'r') as f:
        return json.load(f)


def retained_topics(prefix):
    if not os.access(MQTT_RETAINED, os.X_OK):
        raise RuntimeError('No MQTT broker is configured.')
    out = subprocess.run([MQTT_RETAINED, 'list', f'{prefix}/+/wmbusmeters/+/config'],
                         capture_output=True, text=True, timeout=30)
    return [line.strip() for line in out.stdout.splitlines() if line.strip()]


def discovery_meter(meter_id):
    """The meter of the configuration and its name and driver, or an error response."""
    if not discovery_files.valid_meter_id(meter_id):
        return None, (jsonify({'error': 'Only a meter with a concrete id (no wildcard) can have its own discovery.'}), 400)
    try:
        meter = discovery_files.find_meter(read_config(), meter_id)
    except Exception as e:
        return None, (jsonify({'error': f'Cannot read the configuration: {e}'}), 500)
    if meter is None:
        return None, (jsonify({'error': f'There is no meter with id {meter_id} in the saved configuration. Save the configuration first.'}), 404)
    return meter, None


@app.route('/discovery_api/<meter_id>/status')
def discovery_status(meter_id):
    meter, error = discovery_meter(meter_id)
    if error:
        return error
    files = {}
    for kind in discovery_files.KINDS:
        data = discovery_files.load(kind, meter_id)
        files[kind] = None if data is None else {
            'entities': len(data) if isinstance(data, dict) else 0,
            'modified': discovery_files.modified(kind, meter_id),
        }
    return jsonify({'id': meter_id, 'mode': meter.get('mqtt_discovery', ''), 'files': files})


@app.route('/discovery_api/<meter_id>/generate', methods=['POST'])
def discovery_generate(meter_id):
    meter, error = discovery_meter(meter_id)
    if error:
        return error
    generated = discovery_files.load('generated', meter_id)
    if generated is None:
        return jsonify({'error': 'No telegram of this meter has been received since the add-on started. '
                                 'The draft can be generated once a telegram arrives.'}), 409
    draft = discovery_files.load('drafts', meter_id)
    force = bool((request.get_json(silent=True) or {}).get('force'))
    if draft is not None and draft != generated and not force:
        return jsonify({'error': 'This meter already has a different draft. Generating replaces it.',
                        'confirm': True}), 409
    discovery_files.save('drafts', meter_id, generated)
    panel_log(f"draft of meter {meter.get('name', '')} ({meter_id}) generated: {len(generated)} entities")
    return jsonify({'message': f'Draft generated with {len(generated)} entities.'})


@app.route('/discovery_api/<meter_id>/file')
def discovery_download(meter_id):
    meter, error = discovery_meter(meter_id)
    if error:
        return error
    kind = request.args.get('kind', 'drafts')
    if kind not in discovery_files.KINDS:
        return jsonify({'error': f'Unknown file {kind!r}.'}), 400
    data = discovery_files.load(kind, meter_id)
    if data is None:
        return jsonify({'error': f'This meter has no {kind} file.'}), 404
    body = json.dumps(data, indent=2, sort_keys=True) + '\n'
    name = f'wmbusmeters_discovery_{meter_id}_{kind}.json'
    return app.response_class(body, mimetype='application/json',
                              headers={'Content-Disposition': f'attachment; filename="{name}"'})


@app.route('/discovery_api/<meter_id>/draft', methods=['POST'])
def discovery_upload(meter_id):
    meter, error = discovery_meter(meter_id)
    if error:
        return error
    try:
        data = json.loads(request.get_data(as_text=True))
    except ValueError as e:
        return jsonify({'error': f'The file is not valid JSON: {e}'}), 400
    problems = discovery_files.validate(data)
    if problems:
        panel_log(f"uploaded draft of meter {meter.get('name', '')} ({meter_id}) refused: {'; '.join(problems)}", 'WARNING')
        return jsonify({'error': 'The file cannot be used as a draft.', 'problems': problems}), 400
    discovery_files.save('drafts', meter_id, data)
    panel_log(f"draft of meter {meter.get('name', '')} ({meter_id}) uploaded: {len(data)} entities")
    return jsonify({'message': f'Draft saved with {len(data)} entities.'})


def discovery_baseline(meter_id):
    """What was published last for the meter: the applied file, else the generated one."""
    applied = discovery_files.load('applied', meter_id)
    return applied if applied is not None else discovery_files.load('generated', meter_id)


@app.route('/discovery_api/<meter_id>/preview')
def discovery_preview(meter_id):
    meter, error = discovery_meter(meter_id)
    if error:
        return error
    draft = discovery_files.load('drafts', meter_id)
    if draft is None:
        return jsonify({'error': 'This meter has no draft. Generate or upload one first.'}), 404
    problems = discovery_files.validate(draft)
    if problems:
        return jsonify({'error': 'The draft cannot be applied.', 'problems': problems}), 400
    prefix = discovery_prefix()
    try:
        retained = retained_topics(prefix)
    except Exception as e:
        return jsonify({'error': f'Cannot read the discovery from the broker: {e}'}), 503
    result = discovery_files.preview(draft, discovery_baseline(meter_id), retained, meter_id,
                                     meter.get('name', ''), discovery_files.driver_name(meter), prefix)
    return jsonify(result)


@app.route('/discovery_api/<meter_id>/apply', methods=['POST'])
def discovery_apply(meter_id):
    meter, error = discovery_meter(meter_id)
    if error:
        return error
    draft = discovery_files.load('drafts', meter_id)
    if draft is None:
        return jsonify({'error': 'This meter has no draft. Generate or upload one first.'}), 404
    problems = discovery_files.validate(draft)
    if problems:
        return jsonify({'error': 'The draft cannot be applied, nothing was changed.', 'problems': problems}), 400
    if not os.access(MQTT_BATCH, os.X_OK):
        return jsonify({'error': 'No MQTT broker is configured, nothing was changed.'}), 503
    prefix = discovery_prefix()
    try:
        retained = retained_topics(prefix)
    except Exception as e:
        return jsonify({'error': f'Cannot read the discovery from the broker, nothing was changed: {e}'}), 503
    new_topics = discovery_files.topics(draft, meter_id, meter.get('name', ''),
                                        discovery_files.driver_name(meter), prefix)
    # Publish first; remove only when everything is published, so that a failure
    # leaves the meter with its old entities rather than with none. One start of
    # the batch helper for all topics: a start per topic takes about a second.
    with tempfile.NamedTemporaryFile('w', suffix='.publish', delete=False) as f:
        for topic, payload in new_topics.items():
            f.write(f'{topic}\t{payload}\n')
        publish_file = f.name
    try:
        out = subprocess.run([MQTT_BATCH, 'publish', publish_file], capture_output=True, text=True, timeout=120)
    finally:
        os.remove(publish_file)
    if out.returncode != 0:
        panel_log(f"applying the draft of meter {meter.get('name', '')} ({meter_id}) failed, nothing changed: "
                  f"{out.stderr.strip()}", 'WARNING')
        return jsonify({'error': 'Publishing failed, the applied configuration is unchanged: '
                                 f'{out.stderr.strip()}'}), 502
    removed = [t for t in discovery_files.meter_topics(retained, meter_id) if t not in new_topics]
    if removed:
        with tempfile.NamedTemporaryFile('w', suffix='.clear', delete=False) as f:
            f.write(''.join(f'{t}\n' for t in removed))
            clear_file = f.name
        try:
            subprocess.run([MQTT_BATCH, 'clear', clear_file], capture_output=True, text=True, timeout=120)
        finally:
            os.remove(clear_file)
    discovery_files.save('applied', meter_id, draft)
    panel_log(f"MQTT discovery (manual) of meter {meter.get('name', '')} ({meter_id}) applied: "
              f"published {len(new_topics)} entities, removed {len(removed)}")
    for topic in removed:
        panel_log(f"removed discovery that the applied configuration does not hold: {topic}")
    # The meter is manual from now on: the generated discovery does not replace it.
    config = read_config()
    found = discovery_files.find_meter(config, meter_id)
    if found is not None and found.get('mqtt_discovery') != 'manual':
        found['mqtt_discovery'] = 'manual'
        with open(cfgfile, 'w') as f:
            json.dump(config, f, indent=True)
        panel_log(f"meter {meter.get('name', '')} ({meter_id}) uses the manual MQTT discovery mode now")
    return jsonify({'message': f'Applied: {len(new_topics)} entities published, {len(removed)} removed. '
                               f'The meter uses the manual mode now.',
                    'published': len(new_topics), 'removed': removed})


if __name__ == '__main__':
    serve(app, host="127.0.0.1", port=5000)
