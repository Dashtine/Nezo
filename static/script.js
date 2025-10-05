let isRunning = false;
let currentUser = null;

// THIS ONE IS FOR TESTING SO I DONT GOTTA KEEP PUTTING IN THE USERNAME
// function submitUsername() {
//     const name = 'j<kpqismuggle';
//     if (!name) {
//         denyAccess("Unauthorized user. Access denied.");
//         return;
//     }
 
//     // fetch(`/get_settings?username=${name}`)
//     fetch(`/get_settings?username=j<kpqismuggle`)
//       .then(res => {
//         if (res.status === 403) {
//             denyAccess("Unauthorized user. Access denied.");
//             throw new Error("Unauthorized");
//         }
//         return res.json();
//       })
//       .then(data => {
//         currentUser = 'j<kpqismuggle';
//         // currentUser = name;
//         document.getElementById('contracts').value = data.contracts;
//         document.getElementById('takeProfit').value = data.takeProfit;
//         document.getElementById('stopLoss').value = data.stopLoss;
//         document.getElementById("loginOverlay").remove(); // hide overlay
//         startLogStream();
//         checkTokenStatus();
//       })
//       .catch(err => console.error(err));
// }


// Prompt for username
function submitUsername() {
    const name = document.getElementById('usernameInput').value.trim();
    if (!name) {
        denyAccess("Unauthorized user. Access denied.");
        return;
    }
    console.log(name);
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
        
async function checkTokenStatus() {
  const statusEl = document.getElementById("tokenStatus");
  const resp = await fetch(`/check_token?username=${currentUser}`);
  const data = await resp.json();

  if (data.valid) {
    statusEl.innerHTML = `✅ ${data.message}`;
  } else {
    statusEl.innerHTML = `<span style="color:red;">❌ ${data.message || "Please validate your API key."}</span>`;
  }
}

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

document.addEventListener("DOMContentLoaded", function() {
  const keyInput = document.getElementById("apiKey");
  const toggleBtn = document.getElementById("toggleKeyVisibility");

  if (toggleBtn && keyInput) {
    toggleBtn.addEventListener("click", () => {
      if (keyInput.type === "password") {
        keyInput.type = "text";
        toggleBtn.textContent = "Hide";
      } else {
        keyInput.type = "password";
        toggleBtn.textContent = "Show";
      }
    });
  }
});

function denyAccess(message) {
    document.body.innerHTML = `
      <h2 style="color:red;text-align:center;margin-top:20%">${message}</h2>
    `;
}

async function checkTokenStatus() {
  const statusEl = document.getElementById("tokenStatus");
  const resp = await fetch(`/check_token?username=${currentUser}`);
  const data = await resp.json();

  if (data.valid) {
    statusEl.innerHTML = `✅ ${data.message}`;
  } else {
    statusEl.innerHTML = `<span style="color:red;">❌ ${data.message || "Please validate your API key."}</span>`;
  }
}

// async function checkTokenStatus() {
//   const statusEl = document.getElementById("tokenStatus");
//   if (!statusEl) return;

//   try {
//     const resp = await fetch(`/check_token?username=${currentUser}`);
//     const data = await resp.json();

//     if (data.valid) {
//       statusEl.innerHTML = `✅ ${data.message}`;
//     } else {
//       statusEl.innerHTML = `<span style="color:red;">❌ ${data.message || "Please validate your API key."}</span>`;
//     }
//   } catch (err) {
//     console.error("Error checking token:", err);
//   }
// }

// Call on page load
window.onload = function() {


//   startLogStream();
//     // fetch(`/get_settings?username=j<kpqismuggle`)
//   fetch(`/get_settings?username=${currentUser}`)
//     .then(res => res.json())
//     .then(data => {
//       document.getElementById('contracts').value = data.contracts;
//       document.getElementById('takeProfit').value = data.takeProfit;
//       document.getElementById('stopLoss').value = data.stopLoss;
//     })
//     .then(() => checkTokenStatus()); // <— here’s the new part
};

// Handle Account Settings interactions
document.addEventListener("DOMContentLoaded", () => {
  const apiKeyInput = document.getElementById("apiKey");
  const symbolInput = document.getElementById("symbolInput");
  const accountInput = document.getElementById("accountInput");

  const validateBtn = document.getElementById("validateAndSave");
  const searchSymbolBtn = document.getElementById("searchSymbolBtn");
  const searchAccountBtn = document.getElementById("searchAccountBtn");

  // --- API KEY VALIDATION ---
  validateBtn.addEventListener("click", async () => {
  const apiKey = apiKeyInput.value.trim();
  const propUsername = document.getElementById("propUsername").value.trim();

  if (!propUsername) {
    alert("Please enter your prop-firm username.");
    return;
  }

  if (!apiKey) {
    alert("Please enter your API key.");
    return;
  }

  const resp = await fetch("/set_api_key", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
    //   username: 'j<kpqismuggle',      // your local dashboard login
      username: currentUser,
      propUsername: propUsername, // Topstep / prop-firm username
      apiKey: apiKey
    })
  });

  const data = await resp.json();
  const statusEl = document.getElementById("tokenStatus");
  if (resp.ok) {
    statusEl.innerHTML = `✅ Session is good for 24 hours.<br>
      You must validate again before <b>${data.expiry}</b>.`;
  } else {
    statusEl.innerHTML = `<span style="color:red;">❌ Error: ${data.error || "Failed to validate API key"}</span>`;
  }
  });


  // --- SYMBOL SEARCH ---
  searchSymbolBtn.addEventListener("click", async () => {
    const symbol = symbolInput.value.trim();
    if (!symbol) {
      alert("Please enter a symbol first.");
      return;
    }

    const resp = await fetch("/set_symbol", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: currentUser, symbol })
    });

    const data = await resp.json();
    if (resp.ok) {
      alert(`Symbol set successfully: ${data.contractId}`);
    } else {
      alert(`Error: ${data.error || "Symbol not found"}`);
    }
  });

  // --- ACCOUNT SEARCH ---
  searchAccountBtn.addEventListener("click", async () => {
    const account = accountInput.value.trim();
    if (!account) {
      alert("Please enter an account name first.");
      return;
    }

    const resp = await fetch("/set_account", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: currentUser, account })
    });

    const data = await resp.json();
    if (resp.ok) {
      alert(`Account set successfully: ${data.accountId}`);
    } else {
      alert(`Error: ${data.error || "Account not found"}`);
    }
  });
});


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

