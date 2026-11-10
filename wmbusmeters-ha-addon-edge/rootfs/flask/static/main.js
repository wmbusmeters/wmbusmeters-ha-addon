function renderJsonPair(key = '', value = '') {

  const newPair = document.createElement('div');
  newPair.className = 'json-pair input-group mb-3';
  newPair.innerHTML = `<input class="key form-control" type="text" value="${key}" required>
                         <span class="input-group-text">=</span>
                         <input class="value form-control" type="text" value="${value}" required>
                         <button class="delete-pair btn btn-outline-danger">Delete</button>`;
  document.getElementById('conf').appendChild(newPair);
}



window.addEventListener('load', () => {
  fetch(`/get_json`)
    .then(response => response.json())
    .then(data => {
      const dataForParse = data;
      Object.entries(dataForParse).forEach(([key, value]) => {
        switch (key) {
          case 'data_path':
            document.getElementById('file-path').value = dataForParse[key];
            break;
          case 'mqtt_discovery':
            document.getElementById('mqtt-discovery').value = dataForParse[key];
            break;
          // Configurations written before the mode became a choice: the panel
          // shows them as auto/disable, run.sh rewrites them on the next start.
          case 'enable_mqtt_discovery':
            document.getElementById('mqtt-discovery').value =
              String(dataForParse[key]) === 'true' ? 'auto' : 'disable';
            break;
          case 'conf':
            //console.log(dataForParse);
            Object.entries(dataForParse[key]).forEach(([key1, value1]) => {
              renderJsonPair(key1, escapeHtml(value1));
              //console.log(value1);
            });
            break;
          case 'meters':
            for (let i = 0; i < dataForParse[key].length; i++) {
              // Same order as a new meter: name, driver, id, key, then the rest.
              const keys = orderMeterKeys(Object.keys(dataForParse[key][i]));
              const values = keys.map(k => dataForParse[key][i][k]);
              // The meter's own "MQTT discovery" mode has its own select, see
              // renderSection.
              renderSection(keys, values, dataForParse[key][i].mqtt_discovery || '');
            }
            break;
          case 'mqtt':
            const mqttValuesForRendering = Object.values(dataForParse[key]);
            if (mqttValuesForRendering.length) {
              const keys = Object.keys(dataForParse[key]);
              const values = Object.values(dataForParse[key]);
              renderMqtt(keys, values);
              document.getElementById('mqtt-enabled').checked = true;
            }

        }
      });
      updateMeterDefaultLabels();
    })
    .catch(error => console.error('Error fetching JSON: ', error));


  const escapeHtml = (unsafe) => {
    if (typeof unsafe === 'string') {
      return unsafe.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#039;');
    } else {
      return unsafe;
    }
  }
  const unescapeHtml = (unsafe) => {
    if (typeof unsafe === 'string') {
      return unsafe.replaceAll('&amp;', '&').replaceAll('&lt;', '<').replaceAll('&gt;', '>').replaceAll('&quot;', '"').replaceAll('&#039;', "'");
    } else {
      return unsafe;
    }
  }

  function renderMqtt(keys = ['server', 'port', 'username', 'password'], values = ['', '', '', '']) {
    const newMqtt = document.createElement('div');
    let mqttFieldsHtml = '';
    const MQTT_FIELDS = '';
    for (let i = 0; i < keys.length; i++) {
      mqttFieldsHtml += `
                    <div class="input-group mb-3">
                        <input class="mqtt-key form-control" type="text" value="${keys[i]}" required>
                        <span class="input-group-text">=</span>
                        <input class="mqtt-value form-control" value="${values[i]}" type="text" required>
                    </div>`;
    }
    newMqtt.id = 'mqtt_input';
    newMqtt.innerHTML = mqttFieldsHtml;
    document.getElementById('mqtt').appendChild(newMqtt);
  };

  document.getElementById('mqtt-enabled').addEventListener('change', event => {
    if (event.target.checked) {
      renderMqtt();
    } else {
      const input = document.getElementById('mqtt_input');
      document.getElementById('mqtt').removeChild(input);
    }
  });

  document.getElementById('add-pair').addEventListener('click', () => {
    renderJsonPair();
  });

  // delete a top-level key-value pair
  document.addEventListener('click', event => {
    if (event.target && event.target.classList.contains('delete-pair')) {
      event.target.parentNode.remove();
    }
  });
  // add a new section
  document.getElementById('add-section').addEventListener('click', () => {
    renderSection();
  });

  const METER_KEY_ORDER = ['name', 'driver', 'id', 'key'];

  // The title of a meter card: "name (driver, id)", kept up to date while typing.
  function meterField(section, name) {
    for (const pair of section.querySelectorAll('.json-pair')) {
      const key = pair.querySelector('.section-key');
      if (key && key.value.trim() === name) {
        return pair.querySelector('.section-value').value.trim();
      }
    }
    return '';
  }

  function updateMeterTitle(section) {
    const title = section.querySelector('.meter-title');
    if (!title) {
      return;
    }
    const details = [meterField(section, 'driver'), meterField(section, 'id')].filter(v => v);
    title.textContent = (meterField(section, 'name') || 'New meter') + (details.length ? ` (${details.join(', ')})` : '');
  }

  document.addEventListener('input', event => {
    const section = event.target.closest && event.target.closest('.json-section');
    if (section) {
      updateMeterTitle(section);
    }
  });

  function orderMeterKeys(keys) {
    const first = METER_KEY_ORDER.filter(k => keys.includes(k));
    return first.concat(keys.filter(k => !METER_KEY_ORDER.includes(k)));
  }

  // The "Add-on default" choice of a meter names the mode it stands for.
  const MODE_NAMES = { disable: 'Disable', auto: 'Automatic', manual: 'Manual' };

  function meterDefaultLabel() {
    const mode = document.getElementById('mqtt-discovery').value;
    return `Add-on default (${MODE_NAMES[mode] || mode})`;
  }

  function updateMeterDefaultLabels() {
    document.querySelectorAll('.meter-discovery option[value=""]').forEach(option => {
      option.textContent = meterDefaultLabel();
    });
  }

  document.getElementById('mqtt-discovery').addEventListener('change', updateMeterDefaultLabels);

  // Every meter can override the add-on's "MQTT discovery" setting: the choice
  // is stored as the meter's own "mqtt_discovery" key. run.sh keeps that key out
  // of the wmbusmeters config, see the "MQTT discovery" section of DOCS.md.
  function renderDiscoverySelect(mode = '') {
    const choices = [
      ['', meterDefaultLabel()],
      ['disable', 'Disable'],
      ['auto', 'Automatic'],
      ['manual', 'Manual (applied in the panel)']
    ];
    let known = false;
    let options = '';
    for (const [value, label] of choices) {
      options += `<option value="${value}"${value === mode ? ' selected' : ''}>${label}</option>`;
      if (value === mode) {
        known = true;
      }
    }
    if (!known) {
      // Keep a value the add-on does not know instead of dropping it on save.
      options += `<option value="${escapeHtml(mode)}" selected>${escapeHtml(mode)} (unknown)</option>`;
    }
    return `
                <div class="meter-discovery-row input-group mb-3">
                    <span class="input-group-text form-control text-start">MQTT discovery for this meter</span>
                    <span class="input-group-text">=</span>
                    <select class="meter-discovery form-select">${options}</select>
                    <button class="btn btn-outline-danger invisible" type="button" tabindex="-1" aria-hidden="true">Delete</button>
                </div>`;
  }

  function renderSection(keys = ['name', 'driver', 'id', 'key'], values = ['', '', '', ''], mode = '') {
    const newSection = document.createElement('div');
    newSection.className = 'json-section';
    let newSectionHtml = '';
    for (let i = 0; i < keys.length; i += 1) {
      // The per-meter "MQTT discovery" mode is the select below, not a pair.
      if (keys[i] === 'mqtt_discovery') {
        continue;
      }
      newSectionHtml += `
                <div class="json-pair input-group mb-3">
                    <input class="section-key form-control" value="${keys[i]}" type="text" required>
                    <span class="input-group-text">=</span>
                    <input class="section-value form-control" value="${values[i]}" type="text" required>
                    <button class="delete-pair btn btn-outline-danger" type="button">Delete</button>
                </div>`;
    }
    newSection.innerHTML = '<div class="meter-title"></div>' + newSectionHtml + renderDiscoverySelect(mode) + renderDiscoveryTools() + `<button class="add-pair btn btn-outline-success" type="button">Add New parameter for meter</button>
                    <button class="delete-section btn btn-outline-danger" type="button">Remove meter</button>`;
    document.getElementById('sections').appendChild(newSection);
    updateMeterTitle(newSection);
    refreshDiscoveryState(newSection);
  };

  // --- Manual MQTT discovery of a meter -------------------------------------
  // A draft is made from the generated discovery of the meter (or uploaded),
  // can be downloaded for editing and is applied after a preview of what it
  // adds, changes and removes. Applying makes the meter "manual". The files
  // belong to the meter id, see discovery_files.py and DOCS.md.
  function renderDiscoveryTools() {
    return `
                <fieldset class="meter-discovery-tools">
                    <legend>Manual MQTT discovery (Home Assistant entities)</legend>
                    <div class="discovery-state small text-muted mb-1">Discovery files: save the configuration to see them.</div>
                    <div class="btn-group flex-wrap" role="group">
                        <button class="discovery-generate btn btn-outline-secondary btn-sm" type="button">Generate draft</button>
                        <button class="discovery-download btn btn-outline-secondary btn-sm" type="button">Download draft</button>
                        <button class="discovery-upload btn btn-outline-secondary btn-sm" type="button">Upload draft</button>
                        <button class="discovery-apply btn btn-outline-primary btn-sm" type="button">Apply as manual...</button>
                    </div>
                    <input class="discovery-file" type="file" accept=".json,application/json" hidden>
                </fieldset>`;
  }

  function meterIdOf(section) {
    const keys = section.querySelectorAll('.section-key');
    const values = section.querySelectorAll('.section-value');
    for (let i = 0; i < keys.length; i++) {
      if (keys[i].value === 'id') {
        return values[i].value.trim();
      }
    }
    return '';
  }

  function describeFile(label, file) {
    if (!file) {
      return `${label}: none`;
    }
    const when = file.modified ? new Date(file.modified * 1000).toLocaleString() : '';
    return `${label}: ${file.entities} entities${when ? ' (' + when + ')' : ''}`;
  }

  function refreshDiscoveryState(section) {
    const state = section.querySelector('.discovery-state');
    const id = meterIdOf(section);
    if (!state) {
      return;
    }
    if (!id) {
      state.textContent = 'Discovery files: the meter needs an id.';
      return;
    }
    fetch(`/discovery_api/${encodeURIComponent(id)}/status`)
      .then(response => response.json())
      .then(data => {
        if (data.error) {
          state.textContent = `Discovery files: ${data.error}`;
          return;
        }
        state.textContent = [
          describeFile('Generated', data.files.generated),
          describeFile('Draft', data.files.drafts),
          describeFile('Applied', data.files.applied)
        ].join(' | ');
      })
      .catch(error => { state.textContent = `Discovery files: ${error}`; });
  }

  function showMessage(text, problems = [], reload = false) {
    const popup = document.createElement('div');
    popup.className = 'discovery-popup';
    popup.style.cssText = 'position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);padding:20px;' +
      'border:1px solid #ccc;background:#fff;z-index:9999;max-width:90vw;max-height:80vh;overflow:auto';
    let html = `<p>${escapeHtml(text)}</p>`;
    if (problems.length) {
      html += '<ul>' + problems.map(p => `<li>${escapeHtml(p)}</li>`).join('') + '</ul>';
    }
    popup.innerHTML = html + '<button class="btn btn-outline-success" type="button">Ok</button>';
    popup.querySelector('button').addEventListener('click', () => {
      popup.remove();
      if (reload) {
        location.reload();
      }
    });
    document.body.appendChild(popup);
  }

  // The actions talk to the broker and can take a few seconds: show what is
  // going on and keep the buttons from being pressed again meanwhile.
  function showBusy(text) {
    const busy = document.createElement('div');
    busy.className = 'discovery-busy';
    busy.style.cssText = 'position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);padding:20px;' +
      'border:1px solid #ccc;background:#fff;z-index:10000';
    busy.innerHTML = '<div class="d-flex align-items-center"><div class="spinner-border spinner-border-sm me-2" ' +
      `role="status"></div><span>${escapeHtml(text)}</span></div>`;
    document.body.appendChild(busy);
    const buttons = document.querySelectorAll('.meter-discovery-tools button');
    buttons.forEach(b => { b.disabled = true; });
    let open = true;
    return () => {
      if (!open) {
        return;
      }
      open = false;
      busy.remove();
      buttons.forEach(b => { b.disabled = false; });
    };
  }

  // A question in the style of the panel, instead of the browser's own dialog.
  function showConfirm(text, okLabel, onOk) {
    const popup = document.createElement('div');
    popup.className = 'discovery-popup';
    popup.style.cssText = 'position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);padding:20px;' +
      'border:1px solid #ccc;background:#fff;z-index:9999;max-width:90vw;max-height:80vh;overflow:auto';
    popup.innerHTML = `<p>${escapeHtml(text)}</p>` +
      `<button class="confirm-ok btn btn-outline-primary" type="button">${escapeHtml(okLabel)}</button> ` +
      '<button class="confirm-cancel btn btn-outline-secondary" type="button">Cancel</button>';
    popup.querySelector('.confirm-cancel').addEventListener('click', () => popup.remove());
    popup.querySelector('.confirm-ok').addEventListener('click', () => {
      popup.remove();
      onOk();
    });
    document.body.appendChild(popup);
  }

  function topicList(title, topics) {
    if (!topics.length) {
      return '';
    }
    const items = topics.map(t => `<li><code>${escapeHtml(t)}</code></li>`).join('');
    return `<p class="mb-1"><strong>${title} (${topics.length})</strong></p><ul class="small">${items}</ul>`;
  }

  function showPreview(id, preview, onApply) {
    const popup = document.createElement('div');
    popup.className = 'discovery-popup';
    popup.style.cssText = 'position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);padding:20px;' +
      'border:1px solid #ccc;background:#fff;z-index:9999;max-width:90vw;max-height:80vh;overflow:auto';
    popup.innerHTML = `<h5>Apply the draft of meter ${escapeHtml(id)}?</h5>` +
      topicList('Added', preview.added) +
      topicList('Changed', preview.changed) +
      topicList('Removed from Home Assistant', preview.removed) +
      `<p class="small text-muted">Unchanged: ${preview.unchanged.length}. The meter uses the manual mode afterwards; ` +
      'the add-on publishes this configuration at every start until you apply another one.</p>' +
      '<button class="preview-apply btn btn-outline-primary" type="button">Apply</button> ' +
      '<button class="preview-cancel btn btn-outline-secondary" type="button">Cancel</button>';
    popup.querySelector('.preview-cancel').addEventListener('click', () => popup.remove());
    popup.querySelector('.preview-apply').addEventListener('click', () => {
      popup.remove();
      onApply();
    });
    document.body.appendChild(popup);
  }

  function discoveryRequest(url, options = {}) {
    return fetch(url, options).then(response =>
      response.json().then(data => ({ ok: response.ok, status: response.status, data })));
  }

  function generateDraft(section, id, force = false) {
    const done = showBusy('Generating the draft...');
    discoveryRequest(`/discovery_api/${encodeURIComponent(id)}/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ force })
    }).then(({ ok, data }) => {
      if (!ok && data.confirm && !force) {
        done();
        showConfirm(`${data.error} Replace it with the generated discovery?`, 'Replace',
          () => generateDraft(section, id, true));
        return;
      }
      showMessage(ok ? data.message : data.error);
      refreshDiscoveryState(section);
    }).catch(error => showMessage(String(error))).finally(done);
  }

  document.addEventListener('click', event => {
    const target = event.target;
    if (!target || !target.closest) {
      return;
    }
    const section = target.closest('.json-section');
    if (!section) {
      return;
    }
    const id = meterIdOf(section);
    const known = ['discovery-generate', 'discovery-download', 'discovery-upload', 'discovery-apply'];
    if (!known.some(c => target.classList.contains(c))) {
      return;
    }
    target.blur();
    if (!id) {
      showMessage('The meter needs an id first.');
      return;
    }
    if (target.classList.contains('discovery-generate')) {
      generateDraft(section, id);
    } else if (target.classList.contains('discovery-download')) {
      const done = showBusy('Preparing the file...');
      fetch(`/discovery_api/${encodeURIComponent(id)}/file?kind=drafts`)
        .then(response => {
          if (!response.ok) {
            return response.json().then(data => { throw new Error(data.error); });
          }
          return response.blob();
        })
        .then(blob => {
          const link = document.createElement('a');
          link.href = URL.createObjectURL(blob);
          link.download = `wmbusmeters_discovery_${id}.json`;
          document.body.appendChild(link);
          link.click();
          link.remove();
        })
        .catch(error => showMessage(error.message))
        .finally(done);
    } else if (target.classList.contains('discovery-upload')) {
      section.querySelector('.discovery-file').click();
    } else if (target.classList.contains('discovery-apply')) {
      const reading = showBusy('Reading the discovery of this meter from the broker...');
      discoveryRequest(`/discovery_api/${encodeURIComponent(id)}/preview`)
        .then(({ ok, data }) => {
          reading();
          if (!ok) {
            showMessage(data.error, data.problems || []);
            return;
          }
          const count = data.added.length + data.changed.length + data.unchanged.length;
          showPreview(id, data, () => {
            const applying = showBusy(`Publishing ${count} entities to Home Assistant...`);
            discoveryRequest(`/discovery_api/${encodeURIComponent(id)}/apply`, { method: 'POST' })
              .then(({ ok, data }) => showMessage(ok ? data.message : data.error, data.problems || [], ok))
              .catch(error => showMessage(String(error)))
              .finally(applying);
          });
        })
        .catch(error => {
          reading();
          showMessage(String(error));
        });
    }
  });

  document.addEventListener('change', event => {
    const target = event.target;
    if (!target || !target.classList || !target.classList.contains('discovery-file') || !target.files.length) {
      return;
    }
    const section = target.closest('.json-section');
    const id = meterIdOf(section);
    const done = showBusy('Checking and saving the draft...');
    target.files[0].text()
      .then(text => discoveryRequest(`/discovery_api/${encodeURIComponent(id)}/draft`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: text
      }))
      .then(({ ok, data }) => {
        showMessage(ok ? data.message : data.error, data.problems || []);
        refreshDiscoveryState(section);
      })
      .catch(error => showMessage(String(error)))
      .finally(() => {
        done();
        target.value = '';
      });
  });

  // delete a section
  document.addEventListener('click', event => {
    if (event.target && event.target.classList.contains('delete-section')) {
      event.target.parentNode.remove();
    }
  });

  // add a new pair to a section
  document.addEventListener('click', event => {
    if (event.target && event.target.classList.contains('add-pair')) {
      const newPair = document.createElement('div');
      newPair.className = 'json-pair input-group mb-3';
      newPair.innerHTML = `<input class="section-key form-control" type="text" required>
                                 <span class="input-group-text">=</span>
                                 <input class="section-value form-control" type="text" required>
                                 <button class="delete-pair btn btn-outline-danger">Delete</button>`;
      event.target.parentNode.insertBefore(newPair, event.target);
    }
  });

  // delete a pair within a section
  document.addEventListener('click', event => {
    if (event.target && event.target.classList.contains('delete-pair')) {
      event.target.parentNode.remove();
    }
  });

  function parseValue(value) {
    let valueForWrite = value;
    if (value === 'true' || value === 'false') {
      valueForWrite = value === 'true'
    }
    return valueForWrite;
  };


  function showPopup(message_text) {
    let popup = document.createElement('div');
    popup.style.position = 'fixed';
    popup.style.top = '50%';
    popup.style.left = '50%';
    popup.style.transform = 'translate(-50%, -50%)';
    popup.style.padding = '20px';
    popup.style.border = '1px solid #ccc';
    popup.style.background = '#fff';
    popup.style.zIndex = '9999';

    const message = document.createElement('p');
    message.innerHTML = message_text;

    const button = document.createElement('button');
    button.className = 'btn btn-outline-success'
    button.innerHTML = 'Ok';
    button.addEventListener('click', function() {
      location.reload();
    });

    popup.appendChild(message);
    popup.appendChild(button);

    document.body.appendChild(popup);
  }

  document.getElementById('save-json').addEventListener('click', event => {
    event.preventDefault();
    const data_path = document.getElementById('file-path').value;
    const mqtt_discovery = document.getElementById('mqtt-discovery').value;
    const keys = document.querySelectorAll('.key');
    const values = document.querySelectorAll('.value');
    let confData = {};
    for (let i = 0; i < keys.length; i++) {
      let value = unescapeHtml(values[i].value);
      confData[keys[i].value] = parseValue(value);
    }

    let mqttData = {};
    const mqtt = document.getElementById('mqtt_input');
    if (document.getElementById('mqtt-enabled').checked) {
      const mqttKeys = mqtt.querySelectorAll('.mqtt-key');
      const mqttValues = mqtt.querySelectorAll('.mqtt-value');

      for (let i = 0; i < mqttKeys.length; i++) {
        let value = mqttValues[i].value
        mqttData[mqttKeys[i].value] = parseValue(value);
      }
    }

    let sectionsData = []
    const sections = document.querySelectorAll('.json-section');
    for (let i = 0; i < sections.length; i++) {
      let sectionData = {};
      const sectionKeys = sections[i].querySelectorAll('.section-key');
      const sectionValues = sections[i].querySelectorAll('.section-value');
      for (let i = 0; i < sectionKeys.length; i++) {
        let value = sectionValues[i].value;
        sectionData[sectionKeys[i].value] = parseValue(value);
      }
      // The per-meter "MQTT discovery" choice: the empty "Default" choice means
      // "use the add-on setting", so the key is left out then. The select wins
      // over a "mqtt_discovery" pair that was added by hand.
      const sectionMode = sections[i].querySelector('.meter-discovery');
      if (sectionMode && sectionMode.value !== '') {
        sectionData['mqtt_discovery'] = sectionMode.value;
      } else {
        delete sectionData['mqtt_discovery'];
      }
      sectionsData.push(sectionData)
    }
    const json = {
      'data_path': data_path,
      'mqtt_discovery': mqtt_discovery,
      'conf': confData,
      'meters': sectionsData,
      'mqtt': mqttData
    };


    fetch('/save_json', {
        method: 'POST',
        body: JSON.stringify({
          data: json
        }),
        headers: {
          'Content-Type': 'application/json'
        }
      })
      .then(response => response.json())
      .then(data => {
        showPopup(data['message']);
      })
      .catch(error => console.error(error));


  });
});