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

async function applyAccount() {
  const username = document.getElementById("propUsername").value.trim();
  const apiKey = document.getElementById("apiKey").value.trim();
  const accountId = document.getElementById("accountInput").value.trim();
  const symbol = document.getElementById("symbolInput").value.trim();
  const tokenStatus = document.getElementById("tokenStatus");

  // Simple validation
  if (!username || !apiKey) {
    tokenStatus.textContent = "Username or API key is missing.";
    tokenStatus.style.color = "red";
    return;
  }
  if (!accountId) {
    tokenStatus.textContent = "Account ID is missing.";
    tokenStatus.style.color = "red";
    return;
  }
  if (!symbol) {
    tokenStatus.textContent = "Symbol is missing.";
    tokenStatus.style.color = "red";
    return;
  }

  tokenStatus.textContent = "Validating...";
  tokenStatus.style.color = "#444";

  try {
    // 1. Validate username + API key
    const userRes = await fetch("/set_api_key", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ username, apiKey })
    });
    const userData = await userRes.json();
    console.log("userData" + userData.status)
    if (userData.status !== "ok") throw new Error(userData.message || "Username/API validation failed.");

    // 2. Validate account ID
    const accountRes = await fetch("/set_account", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ accountId })
    });
    const accountData = await accountRes.json();
    if (accountData.status !== "ok") throw new Error(accountData.message || "Account validation failed.");

    // 3. Validate symbol
    const symbolRes = await fetch("/set_contract", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ symbol })
    });
    const symbolData = await symbolRes.json();
    if (symbolData.status !== "ok") throw new Error(symbolData.message || "Symbol validation failed.");

    // If all steps succeed:

    tokenStatus.textContent = "Connected!";
    tokenStatus.style.color = "#166534"; // green


  } catch (err) {
    tokenStatus.textContent = err.message;
    tokenStatus.style.color = "red";
  }
}


// ===== PRESET PROFILE STUFF ======
document.addEventListener("DOMContentLoaded", () => {
  // existing API/account code is already here in your file

  // Preset events
  loadPresetList();

  document.getElementById("savePresetBtn").addEventListener("click", savePresetHandler);
  document.getElementById("loadPresetBtn").addEventListener("click", loadPresetHandler);
  document.getElementById("deletePresetBtn").addEventListener("click", deletePresetHandler);

  const toggle = document.getElementById("presetDropdownToggle");
  const menu = document.getElementById("presetDropdownMenu");
  const input = document.getElementById("presetName");

  toggle.addEventListener("click", () => {
    menu.classList.toggle("open");
  });

  // Close dropdown when clicking outside
  document.addEventListener("click", (e) => {
    if (!menu.contains(e.target) && !toggle.contains(e.target) && !input.contains(e.target)) {
      menu.classList.remove("open");
    }
  });

  // Filter presets while typing
  input.addEventListener("input", () => {
    renderPresetDropdown(input.value.trim());
  });

  // Dark Mode Event Listener
  const dark_toggle = document.getElementById("darkModeToggle");

  // Load saved preference
  if (localStorage.getItem("darkMode") === "enabled") {
    document.body.classList.add("dark-mode");
    dark_toggle.checked = true;
  }

  dark_toggle.addEventListener("change", () => {
    if (dark_toggle.checked) {
      document.body.classList.add("dark-mode");
      localStorage.setItem("darkMode", "enabled");
    } else {
      document.body.classList.remove("dark-mode");
      localStorage.setItem("darkMode", "disabled");
    }
  });
});


function loadPresetList() {
  fetch("/preset/list")
    .then(res => res.json())
    .then(data => {
      presetNames = data.presets || [];
      renderPresetDropdown();
    });
}


function savePresetHandler() {
  const name = document.getElementById("presetName").value.trim();
  if (!name) {
    alert("Give your preset a name first.");
    return;
  }

  const settings = gatherAllSettings();

  fetch("/preset/save", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, settings })
  })
  .then(res => res.json())
  .then(data => {
    if (data.status === "ok") {
      loadPresetList();
    } else {
      alert("Failed to save preset.");
    }
  });
}

function renderPresetDropdown(filterText = "") {
  const menu = document.getElementById("presetDropdownMenu");
  const input = document.getElementById("presetName");
  menu.innerHTML = "";

  const filtered = presetNames.filter(name =>
    !filterText || name.toLowerCase().includes(filterText.toLowerCase())
  );

  if (filtered.length === 0) {
    const empty = document.createElement("div");
    empty.className = "preset-option";
    empty.textContent = "(no presets)";
    empty.style.color = "#777";
    menu.appendChild(empty);
    return;
  }

  filtered.forEach(name => {
    const item = document.createElement("div");
    item.className = "preset-option";
    item.textContent = name;
    item.addEventListener("click", () => {
      input.value = name;
      menu.classList.remove("open");
    });
    menu.appendChild(item);
  });
}

function loadPresetHandler() {
  const name = document.getElementById("presetName").value.trim();
  if (!name) {
    alert("Enter a preset name to load.");
    return;
  }

  fetch("/preset/load", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name })
  })
  .then(res => res.json())
  .then(data => {
    if (data.error) {
      alert(data.error);
      return;
    }

    applySettingsToForm(data.settings);
  });
}

function deletePresetHandler() {
  const name = document.getElementById("presetName").value.trim();
  if (!name) {
    alert("Enter a preset name to delete.");
    return;
  }

  fetch("/preset/delete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name })
  })
  .then(res => res.json())
  .then(data => {
    if (data.status === "ok") {
      loadPresetList();
    }
  });
}

function gatherAllSettings() {
  const selectedMethod = document.querySelector('input[name="tpslMethod"]:checked');
  const selectedBE = document.querySelector('input[name="beMethod"]:checked');

  return {
    propUsername: document.getElementById("propUsername").value.trim(),
    apiKey: document.getElementById("apiKey").value.trim(),
    accountInput: document.getElementById("accountInput").value.trim(),
    symbolInput: document.getElementById("symbolInput").value.trim(),

    contracts: parseInt(document.getElementById('contracts').value),
    takeProfit: parseInt(document.getElementById('takeProfit').value),
    stopLoss: parseInt(document.getElementById('stopLoss').value),

    contractsTP1 : parseInt(document.getElementById('contractsTP1').value),
    contractsTP2 : parseInt(document.getElementById('contractsTP2').value),
    backupTP1 : parseInt(document.getElementById('backupTP1').value),
    backupTP2 : parseInt(document.getElementById('backupTP2').value),
    backupSL : parseInt(document.getElementById('backupSL').value),

    tpslMethod: selectedMethod.value,
    beMethod: selectedBE.value,
    useMacro: document.getElementById('useMacro').checked,

    sessions: [
      {
        enabled: document.getElementById('session1_enabled').checked,
        start: document.getElementById('session1_start').value,
        end: document.getElementById('session1_end').value
      },
      {
        enabled: document.getElementById('session2_enabled').checked,
        start: document.getElementById('session2_start').value,
        end: document.getElementById('session2_end').value
      },
      {
        enabled: document.getElementById('session3_enabled').checked,
        start: document.getElementById('session3_start').value,
        end: document.getElementById('session3_end').value
      }
    ]
  };
}

function applySettingsToForm(s) {
  // Restore API / account data
  document.getElementById("propUsername").value = s.propUsername ?? "";
  document.getElementById("apiKey").value = s.apiKey ?? "";
  document.getElementById("accountInput").value = s.accountInput ?? "";
  document.getElementById("symbolInput").value = s.symbolInput ?? "";

  document.getElementById('contracts').value = s.contracts ?? 0;
  document.getElementById('takeProfit').value = s.takeProfit ?? 0;
  document.getElementById('stopLoss').value = s.stopLoss ?? 0;

  document.getElementById('contractsTP1').value = s.contractsTP1 ?? 0;
  document.getElementById('contractsTP2').value = s.contractsTP2 ?? 0;

  document.getElementById('backupTP1').value = s.backupTP1 ?? 0;
  document.getElementById('backupTP2').value = s.backupTP2 ?? 0;
  document.getElementById('backupSL').value = s.backupSL ?? 0;

  // TPSL mode
  document.getElementById('useLevels').checked = s.tpslMethod === "levels";
  document.getElementById('useTicks').checked = s.tpslMethod === "ticks";

  // Breakeven mode
  document.getElementById('beFirstInt').checked = s.beMethod === "first";
  document.getElementById('beAtTP1').checked = s.beMethod === "tp1";
  document.getElementById('beNone').checked = !s.beMethod;

  // Macro toggle
  document.getElementById('useMacro').checked = s.useMacro ?? false;

  // Sessions
  if (s.sessions && s.sessions.length >= 3) {
    const sessions = s.sessions;

    document.getElementById('session1_enabled').checked = sessions[0].enabled;
    document.getElementById('session1_start').value = sessions[0].start;
    document.getElementById('session1_end').value = sessions[0].end;

    document.getElementById('session2_enabled').checked = sessions[1].enabled;
    document.getElementById('session2_start').value = sessions[1].start;
    document.getElementById('session2_end').value = sessions[1].end;

    document.getElementById('session3_enabled').checked = sessions[2].enabled;
    document.getElementById('session3_start').value = sessions[2].start;
    document.getElementById('session3_end').value = sessions[2].end;
  }

  // Trigger UI logic (enables/disables ticks vs levels)
  document.getElementById("useLevels").dispatchEvent(new Event("change"));
  document.getElementById("useTicks").dispatchEvent(new Event("change"));
}


// ===== Bot Controls =====
function toggleBot() {
  const button = document.getElementById('toggleButton');
  const isStarting = button.classList.contains('start');

  // Inputs for disabling/enabling
  const inputsToToggle = [
    'contracts','takeProfit','stopLoss',
    'useLevels','useTicks',
    'contractsTP1','contractsTP2',
    'beFirstInt','beAtTP1','beNone',
    'backupTP1','backupTP2','backupSL',
    'useMacro',
    'session1_enabled','session1_start','session1_end',
    'session2_enabled','session2_start','session2_end',
    'session3_enabled','session3_start','session3_end'
  ].map(id => document.getElementById(id));

  if (isStarting) {

    // 🔥 AUTO-SAVE all settings before starting
    saveSettings();

    // ---- Start bot ----
    button.classList.remove('start');
    button.classList.add('stop');
    button.textContent = 'Stop';

    // Disable all inputs while bot is running
    inputsToToggle.forEach(el => el.disabled = true);

    fetch('/start', { method: 'POST' });

  } else {

    // ---- Stop bot ----
    button.classList.remove('stop');
    button.classList.add('start');
    button.textContent = 'Start';

    // Re-enable everything
    inputsToToggle.forEach(el => el.disabled = false);

    fetch('/stop', { method: 'POST' });
  }
}
// ===== END OF PRESET PROFILE STUFF ======

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
    backupTP1 : parseInt(document.getElementById('backupTP1').value),
    backupTP2 : parseInt(document.getElementById('backupTP2').value),
    backupSL : parseInt(document.getElementById('backupSL').value),
    tpslMethod: tpslMethod,
    beMethod: beMethod,
    useMacro: document.getElementById('useMacro').checked,

    sessions: [
      {
        enabled: document.getElementById('session1_enabled').checked,
        start: document.getElementById('session1_start').value,
        end: document.getElementById('session1_end').value
      },
      {
        enabled: document.getElementById('session2_enabled').checked,
        start: document.getElementById('session2_start').value,
        end: document.getElementById('session2_end').value
      },
      {
        enabled: document.getElementById('session3_enabled').checked,
        start: document.getElementById('session3_start').value,
        end: document.getElementById('session3_end').value
      }
    ]
  };

  fetch('/save_settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(settings)
  });
}

/* CALCULATE ANALYTICS */ 
document.getElementById("analytics-calc-btn").onclick = async function () {

    // collect inputs
    const from = document.getElementById("analytics-from").value;
    const to = document.getElementById("analytics-to").value;
    const account = document.getElementById("analytics-account").value.trim();
    const symbol = document.getElementById("analytics-symbol").value.trim();

    // collect timeframe selections
    const tfs = Array.from(document.querySelectorAll(".tf-check:checked"))
        .map(x => x.value);

    const payload = {
        from,
        to,
        account,
        symbol,
        timeframes: tfs
    };

    try {
        const res = await fetch("/analytics/calc", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });

        const data = await res.json();

        // update results card
        document.getElementById("res-winrate").innerText = data.win_rate;
        document.getElementById("res-rr").innerText = data.avg_rr;
        document.getElementById("res-trades").innerText = data.total_trades;
        document.getElementById("res-wins").innerText = data.wins;
        document.getElementById("res-losses").innerText = data.losses;

        // hide inputs, show results
        document.getElementById("analytics-inputs").style.display = "none";
        document.getElementById("analytics-results").style.display = "block";

    } catch (err) {
        console.log("Analytics error:", err);
    }
};

document.getElementById("analytics-back-btn").onclick = function () {
    document.getElementById("analytics-results").style.display = "none";
    document.getElementById("analytics-inputs").style.display = "block";
};


// ===== Testing =====
function runTest() {
  const direction = document.getElementById("testDirection").value;
  const timeframe = document.getElementById("testTimeframe").value;

  // Construct fake alert message exactly like a TradingView alert
  const msg = `${direction} ${timeframe} IFVG TEST`;

  fetch('/webhook_ifvg', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message: msg })
  })
  .then(res => res.json())
  .then(data => {
  });
}


// ===== Logs =====
function startLogStream() {
  const eventSource = new EventSource('/logs');
  eventSource.onmessage = e => {
    const logContainer = document.getElementById('logs');
    logContainer.innerHTML += e.data + '<br>';
    logContainer.scrollTop = logContainer.scrollHeight;
  };
}
