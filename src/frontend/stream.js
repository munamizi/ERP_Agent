/**
 * 读取 POST 响应中的 SSE，正确合并跨网络分片的 UTF-8 文本和事件。
 * Args:
 *     response - 已通过 HTTP 状态检查的流式 Response
 *     onEvent - 收到完整事件时调用，参数为事件名和解析后的 JSON 数据
 * Returns:
 *     Promise<void> - 流结束时完成；无响应体、JSON 无效或读取失败时抛出异常。
 */
export async function readEventStream(response, onEvent) {
  if (!response.body) throw new Error("浏览器未收到可读取的响应流");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let terminal = false;

  // 后端每个事件以空行结束；逐行处理同时兼容 LF 和 CRLF。
  const _dispatch = (block) => {
    let event = "message";
    const data = [];
    for (const line of block.split(/\r?\n/)) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
    }
    if (!data.length) return;
    onEvent(event, JSON.parse(data.join("\n")));
    if (event === "done" || event === "error") terminal = true;
  };

  try {
    while (!terminal) {
      const { value, done } = await reader.read();
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
      let boundary;
      while ((boundary = /\r?\n\r?\n/.exec(buffer)) !== null) {
        const block = buffer.slice(0, boundary.index);
        buffer = buffer.slice(boundary.index + boundary[0].length);
        _dispatch(block);
        if (terminal) break;
      }
      if (done) {
        if (buffer.trim() && !terminal) _dispatch(buffer);
        break;
      }
    }
    if (!terminal) throw new Error("响应流已断开，未收到结束事件。请刷新会话记录确认执行状态。");
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
