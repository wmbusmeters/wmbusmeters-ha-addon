function renderJsonPair(key = '', value = '') {

    const newPair = document.createElement('div');
    newPair.className = 'json-pair input-group mb-3';
    newPair.innerHTML = `<input class="key form-control" type="text" value="${key}" required>
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
                    case 'enable_mqtt_discovery':
                        if (dataForParse[key]) {
                            document.getElementById('mqtt-status').value = true;
                        }
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
                            const keys = Object.keys(dataForParse[key][i]);
                            const values = Object.values(dataForParse[key][i]);
                            renderSection(keys, values);
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
        })
        .catch(error => console.error('Error fetching JSON: ', error));


    const escapeHtml = (unsafe) => {
        if (typeof unsafe === 'string'){
            return unsafe.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#039;');
        } else {return unsafe;}
    }
    const unescapeHtml = (unsafe) => {
        if (typeof unsafe === 'string') {
            return unsafe.replaceAll('&amp;', '&').replaceAll('&lt;', '<').replaceAll('&gt;', '>').replaceAll('&quot;', '"').replaceAll('&#039;', "'");
        } else {return unsafe;}
    }

    function renderMqtt(keys=['server', 'port', 'username', 'password'], values=['', '', '', '']) {
            const newMqtt = document.createElement('div');
            let mqttFieldsHtml = '';
            const MQTT_FIELDS = '';
            for (let i = 0; i < keys.length; i++) {
                mqttFieldsHtml += `
                    <div class="input-group mb-3">
                        <input class="mqtt-key form-control" type="text" value="${keys[i]}" required>
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

    function renderSection(keys=['name', 'driver', 'id', 'key'], values=['', '', '', '']) {
        const newSection = document.createElement('div');
        newSection.className = 'json-section';
        let newSectionHtml = '';
        for (let i = 0; i < keys.length; i += 1) {
            newSectionHtml += `
                <div class="json-pair input-group mb-3">
                    <input class="section-key form-control" value="${keys[i]}" type="text" required>
                    <input class="section-value form-control" value="${values[i]}" type="text" required>
                    <button class="delete-pair btn btn-outline-danger" type="button">Delete</button>
                </div>`;
        }
        newSection.innerHTML = newSectionHtml + `<button class="add-pair btn btn-outline-success" type="button">Add New parameter for meter</button>
                    <button class="delete-section btn btn-outline-danger" type="button">Remove meter</button><hr class="my-4">`;
        document.getElementById('sections').appendChild(newSection);

    };
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
            valueForWrite = value === 'true'}
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
        const mqtt_status = document.getElementById('mqtt-status').value === 'true';
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
            sectionsData.push(sectionData)
        }
        const json = {
            'data_path': data_path,
            'enable_mqtt_discovery': mqtt_status,
            'conf': confData,
            'meters': sectionsData,
            'mqtt': mqttData
        };


        fetch('/save_json', {
            method: 'POST',
            body: JSON.stringify({data: json}),
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