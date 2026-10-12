(function () {
  "use strict";

  let token = "";
  let taskId = "";
  let refreshing;

  async function readResponse(response) {
    let value;
    try {
      value = await response.json();
    } catch (error) {
      throw new Error(`Reader 服务返回了非 JSON 响应（HTTP ${response.status}），请刷新页面后重试。`);
    }
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      throw new Error(`Reader 服务响应格式无效（HTTP ${response.status}）。`);
    }
    return value;
  }

  async function refreshToken() {
    if (!refreshing) {
      refreshing = (async () => {
        const response = await fetch("/api/bootstrap", { cache: "no-store" });
        const value = await readResponse(response);
        if (!response.ok) throw new Error(value.error || `请求失败：${response.status}`);
        if (!value.token || !value.task_id) throw new Error("Reader 服务令牌无效，请刷新页面。");
        if (taskId && value.task_id !== taskId) {
          throw new Error("Reader 已切换到其他任务，请刷新页面后重试。");
        }
        token = value.token;
        taskId = value.task_id;
      })().finally(() => { refreshing = undefined; });
    }
    await refreshing;
  }

  async function request(path, options = {}, retry = true) {
    const headers = { ...options.headers };
    if (token) headers["X-Reader-Token"] = token;
    const sentToken = headers["X-Reader-Token"];
    const response = await fetch(path, { cache: "no-store", ...options, headers });
    const value = await readResponse(response);
    // Only authentication rejection is safe to replay: no operation has run yet.
    if (response.status === 403 && value.code === "invalid_token" && retry && path !== "/api/bootstrap") {
      if (!token || token === sentToken) await refreshToken();
      return request(path, options, false);
    }
    if (!response.ok) throw new Error(value.error || `请求失败：${response.status}`);
    if (path === "/api/bootstrap") {
      token = value.token || "";
      taskId = value.task_id || "";
    }
    return value;
  }

  window.ReaderApi = { request };
})();
