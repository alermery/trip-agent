const apiBaseInput = document.getElementById("apiBase");
const usernameInput = document.getElementById("username");
const passwordInput = document.getElementById("password");
const hintEl = document.getElementById("hint");
const registerBtn = document.getElementById("registerBtn");
const loginBtn = document.getElementById("loginBtn");

function showHint(text, isError = false) {
  hintEl.textContent = text;
  hintEl.classList.toggle("error", isError);
}

function getApiBase() {
  return apiBaseInput.value.trim().replace(/\/$/, "");
}

async function postJson(path, body) {
  const response = await fetch(`${getApiBase()}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await readResponseJson(response);
  if (!response.ok) {
    const msg = data._notJson
      ? data._raw || "请求失败"
      : formatApiDetail(data.detail) || "请求失败";
    throw new Error(msg);
  }
  return data;
}

function saveBaseAndToken(base, token) {
  localStorage.setItem("xc_api_base", base);
  localStorage.setItem("xc_token", token);
}

if (localStorage.getItem("xc_api_base")) {
  apiBaseInput.value = localStorage.getItem("xc_api_base");
}

(() => {
  const session = new URLSearchParams(window.location.search).get("session");
  if (session === "expired" && hintEl) {
    showHint("登录状态已失效（例如长时间未使用或更换了服务端密钥），请重新登录。", true);
  }
})();

if (registerBtn) {
  registerBtn.addEventListener("click", async () => {
    try {
      const username = usernameInput.value.trim();
      const password = passwordInput.value.trim();
      const data = await postJson("/auth/register", { username, password });
      saveBaseAndToken(getApiBase(), data.access_token);
      showHint("注册成功，正在跳转...", false);
      setTimeout(() => {
        window.location.href = "./index.html";
      }, 350);
    } catch (error) {
      showHint(`注册失败: ${error.message}`, true);
    }
  });
}

if (loginBtn) {
  loginBtn.addEventListener("click", async () => {
    try {
      const username = usernameInput.value.trim();
      const password = passwordInput.value.trim();
      const data = await postJson("/auth/login", { username, password });
      saveBaseAndToken(getApiBase(), data.access_token);
      showHint("登录成功，正在跳转...", false);
      setTimeout(() => {
        window.location.href = "./index.html";
      }, 350);
    } catch (error) {
      showHint(`登录失败: ${error.message}`, true);
    }
  });
}
