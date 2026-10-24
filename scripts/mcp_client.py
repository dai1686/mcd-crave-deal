"""
麦当劳 MCP 轻量客户端（仅依赖标准库）

用法:
    export MCD_MCP_TOKEN=你的Token
    python mcp_client.py tools                      # 列出全部工具
    python mcp_client.py call query-meals '{"storeCode":"1980439","orderType":1,"beType":1}' [输出文件]

说明:
    - MCP 端点: https://mcp.mcd.cn (POST, streamable-http, 单次请求响应)
    - Token 只从环境变量读取，绝不落盘、绝不进 Git
"""

import json
import os
import ssl
import sys
import urllib.error
import urllib.request

ENDPOINT = "https://mcp.mcd.cn"


def get_token() -> str:
    token = os.environ.get("MCD_MCP_TOKEN")
    if not token:
        raise SystemExit("请先设置环境变量 MCD_MCP_TOKEN（在 open.mcd.cn/mcp 控制台激活领取）")
    return token


def call(method: str, params: dict = None, timeout: int = 30) -> dict:
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    req = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": "Bearer " + get_token(),
        },
        method="POST",
    )
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        return json.loads(resp.read().decode("utf-8"))


def tools_list() -> list:
    return call("tools/list")["result"]["tools"]


def call_tool(name: str, arguments: dict, timeout: int = 30) -> dict:
    res = call("tools/call", {"name": name, "arguments": arguments}, timeout=timeout)
    if "error" in res:
        raise RuntimeError(json.dumps(res["error"], ensure_ascii=False))
    return res["result"]


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    if cmd == "tools":
        for t in tools_list():
            print(t["name"], "|", (t.get("description") or "").split("\n")[0][:80])
    elif cmd == "call":
        name = sys.argv[2]
        args = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
        out = call_tool(name, args)
        text = json.dumps(out, ensure_ascii=False, indent=2)
        if len(sys.argv) > 4:
            with open(sys.argv[4], "w", encoding="utf-8") as f:
                f.write(text)
            print("已写入", sys.argv[4], "字符数", len(text))
        else:
            print(text[:4000])
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
