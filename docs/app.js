"use strict";
const $ = (id) => document.getElementById(id);
const form = $("download-form");
const linksInput = $("links");
const feedback = $("feedback");
const submitBtn = $("submit-btn");
const serverStatus = $("server-status");
const serverLight = $("server-light");
const apiInput = $("api-url");
const keyInput = $("access-key");
const githubPages = location.hostname.endsWith(".github.io");
let apiBase = localStorage.getItem("framekeep_api") || "";
let accessKey = localStorage.getItem("framekeep_key") || "";
apiInput.value = apiBase;
keyInput.value = accessKey;

function setFeedback(message, type = "info") {
  feedback.hidden = false;
  feedback.textContent = message;
  feedback.className = `feedback ${type}`;
}
function getApiBase() {
  return apiBase || (githubPages ? "" : location.origin);
}
function parseInstagramUrl(input) {
  let url;
  try { url = new URL(input); } catch { throw new Error("올바른 URL을 입력해 주세요."); }
  if (url.protocol !== "https:" || !["www.instagram.com", "instagram.com", "m.instagram.com"].includes(url.hostname) || url.port || url.username || url.password) {
    throw new Error("인스타그램 HTTPS 게시물 링크만 사용할 수 있습니다.");
  }
  const match = url.pathname.match(/^\/(p|reel|tv)\/([a-zA-Z0-9_-]{5,32})\/?$/);
  if (!match) throw new Error("인스타그램의 개별 게시물(/p/) 링크를 입력해 주세요.");
  return `https://www.instagram.com/${match[1]}/${match[2]}/`;
}
function parseLinks(input) {
  const raw = input.trim().split(/\s+/).filter(Boolean);
  if (raw.length === 0 || raw.length > 3) throw new Error("게시물 링크는 한 번에 1~3개까지 입력해 주세요.");
  return [...new Set(raw.map(parseInstagramUrl))];
}
function setServerState(state, text) {
  serverStatus.textContent = text;
  serverLight.className = `status-light ${state}`;
}
async function checkHealth() {
  const base = getApiBase();
  if (!base) {
    setServerState("fail", "Render 서버 주소 설정 필요");
    $("settings").open = true;
    return;
  }
  setServerState("", "서버 연결 확인 중");
  try {
    const response = await fetch(`${base}/api/health`, {signal: AbortSignal.timeout(85000)});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (!data.ok) throw new Error("Invalid server");
    setServerState("ok", data.access_key_required ? "서버 연결됨 · 접근 키 필요" : "서버 연결됨");
  } catch {
    setServerState("fail", "서버에 연결되지 않음");
  }
}

$("paste-button").addEventListener("click", async () => {
  try {
    const text = await navigator.clipboard.readText();
    linksInput.value = linksInput.value.trim() ? `${linksInput.value.trim()}\n${text.trim()}` : text.trim();
    linksInput.focus();
  } catch {
    setFeedback("클립보드 권한이 허용되지 않았습니다. Ctrl+V로 붙여넣어 주세요.", "error");
  }
});

$("save-settings").addEventListener("click", () => {
  const raw = apiInput.value.trim().replace(/\/+$/, "");
  if (raw) {
    try {
      const parsed = new URL(raw);
      if (parsed.protocol !== "https:" && !(["localhost", "127.0.0.1"].includes(parsed.hostname) && parsed.protocol === "http:")) throw new Error();
      if (parsed.pathname !== "/" || parsed.search || parsed.hash || parsed.username || parsed.password) throw new Error();
    } catch {
      setFeedback("서버 주소는 https://앱이름.onrender.com 형식으로 입력해 주세요.", "error");
      return;
    }
  }
  apiBase = raw;
  accessKey = keyInput.value.trim();
  if (apiBase) localStorage.setItem("framekeep_api", apiBase);
  else localStorage.removeItem("framekeep_api");
  if (accessKey) localStorage.setItem("framekeep_key", accessKey);
  else localStorage.removeItem("framekeep_key");
  setFeedback("서버 연결 설정을 저장했습니다.", "success");
  checkHealth();
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  let urls;
  try { urls = parseLinks(linksInput.value); } catch (error) {
    setFeedback(error.message, "error");
    return;
  }
  const base = getApiBase();
  if (!base) {
    $("settings").open = true;
    setFeedback("GitHub Pages에서 사용하려면 아래 서버 연결 설정에 Render 주소를 입력해 주세요.", "error");
    return;
  }
  submitBtn.disabled = true;
  submitBtn.classList.add("loading");
  $("button-label").textContent = "사진 처리 중";
  setFeedback("사진 주소를 조회하고 ZIP 파일을 생성하는 중입니다. 서버 상태에 따라 시간이 걸릴 수 있습니다.");
  try {
    const headers = {"Content-Type": "application/json"};
    if (accessKey) headers["X-App-Key"] = accessKey;
    const response = await fetch(`${base}/api/download`, {
      method: "POST", headers, body: JSON.stringify({urls}), signal: AbortSignal.timeout(160000),
    });
    if (!response.ok) {
      let error = `서버 오류 (HTTP ${response.status})`;
      let code = "";
      try {
        const data = await response.json();
        if (data.error) error = data.error;
        code = data.code || "";
      } catch {}
      const failure = new Error(error);
      failure.code = code;
      throw failure;
    }
    const blob = await response.blob();
    if (blob.size < 100) throw new Error("서버가 빈 파일을 보냈습니다.");
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    const disposition = response.headers.get("Content-Disposition") || "";
    anchor.download = disposition.match(/filename="?([^";]+)"?/i)?.[1] || "instagram_photos.zip";
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
    const images = response.headers.get("X-Photo-Count");
    const failed = Number(response.headers.get("X-Failed-Posts") || "0");
    const report = images ? `${images}장의 사진이 포함된 ZIP 파일을 저장했습니다.` : "ZIP 파일 다운로드를 시작했습니다.";
    setFeedback(failed ? `${report}\n${failed}개 게시물은 가져오지 못했습니다. ZIP 안의 download_report.txt를 확인하세요.` : report, "success");
  } catch (error) {
    const timeout = error.name === "TimeoutError" || error.name === "AbortError";
    if (error.code === "ACCESS_RESTRICTED") {
      $("manual-mode").open = true;
      setFeedback("다운로드 실패: " + error.message + "\n서버 연결은 정상입니다. 아래 이미지 주소 직접 저장 방식을 이용할 수 있습니다.", "error");
    } else {
      setFeedback(timeout ? "다운로드 처리 시간이 초과되었습니다." : "다운로드 실패: " + error.message, "error");
    }
  } finally {
    submitBtn.disabled = false;
    submitBtn.classList.remove("loading");
    $("button-label").textContent = "사진 다운로드";
  }
});

checkHealth();
