window.addEventListener('load', () => {

function showkemresp(data) {
  var status = (Object.keys(data)[0]);
  if (status == "OK") {
    var meterid = (data.OK.id);
    var meterkey = (data.OK.key);
    document.getElementById("kemresp").removeAttribute("hidden");
    document.getElementById("kemdectext1").removeAttribute("hidden");
    document.getElementById("kemresp").classList.replace('alert-danger', 'alert-success');
    document.getElementById("kemdechead").innerHTML = ("Decrypted meter details:");
    document.getElementById("kemdectext").innerHTML = ("id = " + meterid);
    document.getElementById("kemdectext1").innerHTML = ("key = " + meterkey);
  } else if (status == "ERROR") {
    var kemerrtxt = (data.ERROR);
    document.getElementById("kemresp").removeAttribute("hidden");
    document.getElementById("kemdectext1").setAttribute("hidden", "");
    document.getElementById("kemresp").classList.replace('alert-success', 'alert-danger');
    document.getElementById("kemdechead").innerHTML = ("Error!");
    document.getElementById("kemdectext").innerHTML = (kemerrtxt);
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