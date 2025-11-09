let currentUser = null;

// Prompt for username
function submitUsername() {
  const name = document.getElementById('usernameInput').value.trim();
  if (!name) {
    denyAccess("Unauthorized user. Access denied.");
    return;
  }

  fetch('/validate_user', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: name })
  })
    .then(res => {
      if (!res.ok) throw new Error("Unauthorized");
      return res.json();
    })
    .then(data => {
      if (data.valid) {
        currentUser = name;
        document.getElementById("loginOverlay").remove();
        startLogStream();
      } else {
        denyAccess("Unauthorized user. Access denied.");
      }
    })
    .catch(() => denyAccess("Unauthorized user. Access denied."));
}

// Press Enter to login
document.addEventListener("keydown", e => {
  if (e.key === "Enter" && document.getElementById("loginOverlay")) {
    e.preventDefault();
    submitUsername();
  }
});

function denyAccess(msg) {
  document.body.innerHTML = `
    <h2 style="color:red;text-align:center;margin-top:20%">${msg}</h2>
  `;
}

// ===== Account / API Section =====
document.addEventListener("DOMContentLoaded", () => {
  const apiKeyInput = document.getElementById("apiKey");
  const propUserInput = document.getElementById("propUsername");

  // Validate API Key
  document.getElementById("validateAndSave").addEventListener("click", async () => {
    const apiKey = apiKeyInput.value.trim();
    const propUsername = propUserInput.value.trim();

    if (!apiKey || !propUsername) {
      alert("Please enter both prop username and API key.");
      return;
    }

    const resp = await fetch("/set_api_key", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ apiKey, propUsername })
    });

    const data = await resp.json();
    const statusEl = document.getElementById("tokenStatus");

    if (resp.ok) {
      statusEl.innerHTML = `✅ Session is good for 24 hours.`;
    } else {
      statusEl.innerHTML = `<span style="color:red;">❌ ${data.error || "Failed to validate API key"}</span>`;
    }
  });

  // Set account
  document.getElementById("setAccountBtn").addEventListener("click", async () => {
    const account = document.getElementById("accountInput").value.trim();
    if (!account) {
      alert("Please enter an account name first.");
      return;
    }

    const resp = await fetch("/set_account", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ account })
    });

    const data = await resp.json();
    if (resp.ok && data.status === "ok") {
      alert(`✅ Account set successfully: ${data.account} (${data.accountId})`);
    } else {
      alert(`❌ ${data.error || "Account not found."}`);
    }
  });

  // Set contract
  document.getElementById("setSymbolBtn").addEventListener("click", async () => {
    const symbol = document.getElementById("symbolInput").value.trim();
    if (!symbol) {
      alert("Please enter a contract name first.");
      return;
    }

    const resp = await fetch("/set_contract", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol })
    });

    const data = await resp.json();
    if (resp.ok && data.status === "ok") {
      alert(`✅ Contract set successfully: ${data.contractName} (${data.contractId})\n${data.description || ""}`);
    } else {
      alert(`❌ ${data.error || "Contract not found."}`);
    }
  });
});

// ===== Bot Controls =====
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
    useLevels.disabled = true;
    useTicks.disabled = true;
    contractsTP1.disabled = true;
    contractsTP2.disabled = true;
    beFirstInt.disabled = true;
    beAtTP1.disabled = true;
    beNone.disabled = true;
    
    fetch('/start', { method: 'POST' });
  } else {
    button.classList.remove('stop');
    button.classList.add('start');
    button.textContent = 'Start';
    contracts.disabled = false;
    takeProfit.disabled = false;
    stopLoss.disabled = false;
    saveBtn.disabled = false;
    useLevels.disabled = false;
    useTicks.disabled = false;
    contractsTP1.disabled = false;
    contractsTP2.disabled = false;
    beFirstInt.disabled = false;
    beAtTP1.disabled = false;
    beNone.disabled = false;
    fetch('/stop', { method: 'POST' });
  }
}

// ===== Settings =====
function saveSettings() {
  const selectedMethod = document.querySelector('input[name="tpslMethod"]:checked');
  const selectedBE = document.querySelector('input[name="beMethod"]:checked');

  const tpslMethod = selectedMethod.value;
  const beMethod = selectedBE.value;
  const settings = {
    contracts: parseInt(document.getElementById('contracts').value),
    takeProfit: parseInt(document.getElementById('takeProfit').value),
    stopLoss: parseInt(document.getElementById('stopLoss').value),
    contractsTP1 : parseInt(document.getElementById('contractsTP1').value),
    contractsTP2 : parseInt(document.getElementById('contractsTP2').value),
    tpslMethod: tpslMethod,
    beMethod: beMethod
  };

  fetch('/save_settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(settings)
  });
}

// ===== Testing =====
function TestLong() { fetch('/test_long', { method: 'POST' }); }
function TestShort() { fetch('/test_short', { method: 'POST' }); }

// ===== Logs =====
function startLogStream() {
  const eventSource = new EventSource('/logs');
  eventSource.onmessage = e => {
    const logContainer = document.getElementById('logs');
    logContainer.innerHTML += e.data + '<br>';
    logContainer.scrollTop = logContainer.scrollHeight;
  };
}
