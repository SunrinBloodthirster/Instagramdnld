"use strict";
const $manual = (id) => document.getElementById(id);
const manualForm = $manual("manual-form");
const manualFeedback = $manual("manual-feedback");
function manualMessage(message, type = "info") {
  manualFeedback.hidden = false;
  manualFeedback.textContent = message;
  manualFeedback.className = "feedback " + type;
}
manualForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const urls = $manual("image-urls").value.trim().split(/\s+/).filter(Boolean);
  if (urls.length < 1 || urls.length > 15) {
    manualMessage("이미지 URL은 1~15개 입력해 주세요.", "error");
    return;
  }
  const githubPages = location.hostname.endsWith(".github.io");
  const backend = localStorage.getItem("framekeep_api") || (githubPages ? "" : location.origin);
  if (!backend) {
    $manual("settings").open = true;
    manualMessage("먼저 Render 서버 주소를 설정해 주세요.", "error");
    return;
  }
  const button = $manual("manual-submit");
  button.disabled = true;
  manualMessage("이미지를 내려받아 ZIP으로 묶는 중입니다.");
  try {
    const headers = {"Content-Type": "application/json"};
    const key = localStorage.getItem("framekeep_key");
    if (key) headers["X-App-Key"] = key;
    const resp = await fetch(backend + "/api/download-direct", {
      method: "POST", headers, body: JSON.stringify({image_urls: urls}),
      signal: AbortSignal.timeout(210000)
    });
    if (!resp.ok) {
      let error = "서버 오류 (HTTP " + resp.status + ")";
      try {const data = await resp.json();if(data.error) error=data.error;} catch {}
      throw new Error(error);
    }
    const blob = await resp.blob();
    if (blob.size < 100) throw new Error("ZIP 파일이 비어 있습니다.");
    const obj = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = obj;
    link.download = "instagram_network_photos.zip";
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(obj), 60000);
    const count = resp.headers.get("X-Photo-Count") || "여러";
    const failures = Number(resp.headers.get("X-Failed-Posts") || "0");
    manualMessage(count + "장의 사진을 ZIP 파일로 저장했습니다." +
      (failures ? "\n" + failures + "개는 실패했습니다. ZIP의 download_report.txt를 확인해 주세요." : ""), "success");
  } catch (err) {
    const timeout = err.name === "TimeoutError" || err.name === "AbortError";
    manualMessage(timeout
      ? "브라우저 대기시간(210초)을 초과했습니다. 이미지 URL을 1~3개씩 나누어 시도해 주세요."
      : "다운로드 실패: " + err.message, "error");
  } finally {
    button.disabled = false;
  }
});
