/** ERP 请求层；Gemini 优化样式时保留这里的接口契约。 */
let _token = localStorage.getItem("erp-api-token") || "demo-admin-token";

export function setToken(token) {
    /**
     * 设置当前页面调用 ERP 的令牌并保存到本机浏览器。
     *
     * Args:
     *     token - 用户输入的 API 令牌
     * Returns:
     *     undefined - 更新请求令牌及浏览器本地存储。
     */
    _token = token.trim();
    localStorage.setItem("erp-api-token", _token);
}

export function getToken() {
    /**
     * 读取页面当前使用的 API 令牌。
     *
     * Args:
     *     无。
     * Returns:
     *     当前令牌字符串。
     */
    return _token;
}

export async function api(path, options = {}) {
    /**
     * 调用 ERP HTTP 接口并将错误响应转换为可显示的异常。
     *
     * Args:
     *     path - 同源 ERP 接口路径
     *     options - HTTP 方法、JSON 请求体及可复用的 idempotencyKey
     * Returns:
     *     接口 JSON 结果；请求失败时抛出包含业务错误信息的异常。
     */
    const method = options.method || "GET";
    const headers = {Authorization: "Bearer " + _token};
    if (method !== "GET") {
        headers["Content-Type"] = "application/json";
        headers["Idempotency-Key"] = options.idempotencyKey || crypto.randomUUID();
    }
    const response = await fetch(path, {method, headers, body: options.body === undefined ? undefined : JSON.stringify(options.body)});
    const result = await response.json();
    if (!response.ok) {
        const error = result.error || {};
        const details = (error.details || []).map(item => item.loc.join(".") + ": " + item.msg).join("；");
        throw new Error((error.message || "接口请求失败") + (details ? "；" + details : ""));
    }
    return result;
}
