window.addEventListener('load', () => {

function showkemresp(data) {
  const status = Object.keys(data)[0];

  const showError = (msg) => {
    document.getElementById("kemresp").removeAttribute("hidden");
    document.getElementById("kemdectext1").setAttribute("hidden", "");
    document.getElementById("kemresp").classList.replace('alert-success', 'alert-danger');
    document.getElementById("kemdechead").textContent = "Error!";
    document.getElementById("kemdectext").textContent = msg;
  };

  if (status === "OK") {
    const ok = data.OK;
    const items = Array.isArray(ok) ? ok : [ok];

    document.getElementById("kemresp").removeAttribute("hidden");
    document.getElementById("kemresp").classList.replace('alert-danger', 'alert-success');
    document.getElementById("kemdechead").textContent =
      items.length === 1 ? "Decrypted meter details:" : `Decrypted meter details (${items.length}):`;

    const body = items
      .map(m => `id = ${m.id}\n\nkey = ${m.key}`)
      .join("\n\n");

    const textEl = document.getElementById("kemdectext");
    textEl.textContent = body; // relies on CSS white-space: pre-line
    document.getElementById("kemdectext1").setAttribute("hidden", "");
  } else if (status === "ERROR") {
    showError(data.ERROR);
  } else {
    showError("Unexpected response.");
  }
}

function validateform() {
  var name = document.forms["decrypt-form"]["file"].value;
  var password = document.forms["decrypt-form"]["password"].value;

  if (name.length < 1) {
    document.getElementById("file").classList.add("is-invalid");
    document.getElementById("password").classList.remove("is-invalid");
    return false;
  } else if (password.length < 1) {
    document.getElementById("file").classList.remove("is-invalid");
    document.getElementById("password").classList.add("is-invalid");
    return false;
  }
}

document.getElementById('decrypt').addEventListener('click', event => {
  if (validateform() === false) {
    event.preventDefault();
    event.stopPropagation();
    return false;
  }
  document.getElementById("file").classList.remove("is-invalid");
  document.getElementById("password").classList.remove("is-invalid");
  event.preventDefault();
  const fileInput = document.getElementById('file');
  const passwordInput = document.getElementById('password');

  const formData = new FormData();
  formData.append('file', fileInput.files[0]);
  formData.append('password', passwordInput.value);

  fetch('/decrypt', {
      method: 'POST',
      body: formData
    })
    .then(response => response.json())
    .then(showkemresp)
    .catch(error => console.error(error));
});});