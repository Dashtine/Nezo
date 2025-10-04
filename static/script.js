let isRunning = false;
let currentUser = null;

// Prompt for username
function submitUsername() {
    const name = document.getElementById('usernameInput').value.trim();
    if (!name) {
        denyAccess("Unauthorized user. Access denied.");
        return;
    }

    fetch(`/get_settings?username=${name}`)
      .then(res => {
        if (res.status === 403) {
            denyAccess("Unauthorized user. Access denied.");
            throw new Error("Unauthorized");
        }
        return res.json();
      })
      .then(data => {
        currentUser = name;
        document.getElementById('contracts').value = data.contracts;
        document.getElementById('takeProfit').value = data.takeProfit;
        document.getElementById('stopLoss').value = data.stopLoss;
        document.getElementById("loginOverlay").remove(); // hide overlay
        startLogStream();
      })
      .catch(err => console.error(err));
}

// Allow pressing "Enter" in the input field
document.addEventListener("keydown", function(event) {
    if (event.key === "Enter" && document.getElementById("loginOverlay")) {
        event.preventDefault(); // stop form submit/reload
        submitUsername();
    }
});

function denyAccess(message) {
    document.body.innerHTML = `
      <h2 style="color:red;text-align:center;margin-top:20%">${message}</h2>
    `;
}

// Flips the start/stop button
function toggleBot() {
    const button = document.getElementById('toggleButton');
    const isStarted = button.classList.contains('start');
    
    const contracts = document.getElementById('contracts');
    const takeProfit = document.getElementById('takeProfit');
    const stopLoss = document.getElementById('stopLoss');
    const saveBtn = document.querySelector('.save');
    
    if (isStarted) {
        button.classList.remove('start');
        button.classList.add('stop');
        button.textContent = 'Stop';
        contracts.disabled = true;
        takeProfit.disabled = true;
        stopLoss.disabled = true;
        saveBtn.disabled = true;

        fetch('/start', { method: 'POST' });
    } else {
        button.classList.remove('stop');
        button.classList.add('start');
        button.textContent = 'Start';
        contracts.disabled = false;
        takeProfit.disabled = false;
        stopLoss.disabled = false;
        saveBtn.disabled = false;

        fetch('/stop', { method: 'POST' });
    }
}

// Saves the settings the user has set
function saveSettings() {
    const settings = {
        username: currentUser,
        contracts: parseInt(document.getElementById('contracts').value),
        takeProfit: parseInt(document.getElementById('takeProfit').value),
        stopLoss: parseInt(document.getElementById('stopLoss').value)
    };

    fetch('/save_settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings)
    });
}

// Places a test market long order
function TestLong() {
    fetch('/test_long', { method: 'POST' });
}

// Places a test market short order
function TestShort() {
    fetch('/test_short', { method: 'POST' });
}

// Starts up the on screen messages
function startLogStream(){
    const eventSource = new EventSource('/logs');
    eventSource.onmessage = function(event){
        const logContainer = document.getElementById('logs');
        logContainer.innerHTML += event.data + '<br>';
        logContainer.scrollTop = logContainer.scrollHeight;
    };
}

