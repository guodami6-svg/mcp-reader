import os
import json
from datetime import datetime
from supabase import create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
MCP_AUTH_TOKEN = os.environ.get("MCP_AUTH_TOKEN", "")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

TOOLS = [
    {
        "name": "upload_book",
        "description": "上传一本新书，传入书名和完整内容，自动按段落拆分存储",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "书名"},
                "content": {"type": "string", "description": "书的完整文本内容"}
            },
            "required": ["title", "content"]
        }
    },
    {
        "name": "get_paragraphs",
        "description": "读取某本书的段落，支持指定范围",
        "inputSchema": {
            "type": "object",
            "properties": {
                "book_id": {"type": "integer", "description": "书的ID"},
                "start": {"type": "integer", "description": "起始段落号", "default": 1},
                "end": {"type": "integer", "description": "结束段落号", "default": 5}
            },
            "required": ["book_id"]
        }
    },
    {
        "name": "add_comment",
        "description": "给某段落写评论",
        "inputSchema": {
            "type": "object",
            "properties": {
                "book_id": {"type": "integer", "description": "书的ID"},
                "paragraph_number": {"type": "integer", "description": "段落编号"},
                "commenter": {"type": "string", "description": "评论者：衍 或 Minx"},
                "comment": {"type": "string", "description": "评论内容"}
            },
            "required": ["book_id", "paragraph_number", "commenter", "comment"]
        }
    },
    {
        "name": "get_comments",
        "description": "查看某段落的所有评论",
        "inputSchema": {
            "type": "object",
            "properties": {
                "book_id": {"type": "integer", "description": "书的ID"},
                "paragraph_number": {"type": "integer", "description": "段落编号"}
            },
            "required": ["book_id", "paragraph_number"]
        }
    },
    {
        "name": "list_books",
        "description": "查看所有已上传的书",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    }
]


def handle_tool(name, args):
    if name == "upload_book":
        title = args["title"]
        content = args["content"]
        paragraphs = [p.strip() for p in content.split("\n") if p.strip()]
        book = supabase.table("books").insert({"title": title, "total_paragraphs": len(paragraphs)}).execute()
        book_id = book.data[0]["id"]
        rows = [{"book_id": book_id, "paragraph_number": i+1, "content": p} for i, p in enumerate(paragraphs)]
        batch_size = 500
        for i in range(0, len(rows), batch_size):
            supabase.table("book_paragraphs").insert(rows[i:i+batch_size]).execute()
        return f"《{title}》上传成功！共 {len(paragraphs)} 段，book_id={book_id}"

    elif name == "get_paragraphs":
        book_id = args["book_id"]
        start = args.get("start", 1)
        end = args.get("end", start + 4)
        result = supabase.table("book_paragraphs").select("paragraph_number, content").eq("book_id", book_id).gte("paragraph_number", start).lte("paragraph_number", end).order("paragraph_number").execute()
        if not result.data:
            return "没有找到段落"
        text = ""
        for row in result.data:
            text += f"【第{row['paragraph_number']}段】\n{row['content']}\n\n"
        return text

    elif name == "add_comment":
        supabase.table("book_comments").insert({
            "book_id": args["book_id"],
            "paragraph_number": args["paragraph_number"],
            "commenter": args["commenter"],
            "comment": args["comment"]
        }).execute()
        return f"{args['commenter']}的评论已保存！"

    elif name == "get_comments":
        result = supabase.table("book_comments").select("*").eq("book_id", args["book_id"]).eq("paragraph_number", args["paragraph_number"]).order("created_at").execute()
        if not result.data:
            return "这段还没有评论"
        text = ""
        for row in result.data:
            text += f"[{row['commenter']}] {row['comment']}\n"
        return text

    elif name == "list_books":
        result = supabase.table("books").select("*").order("created_at", desc=True).execute()
        if not result.data:
            return "还没有上传任何书"
        text = ""
        for row in result.data:
            text += f"ID:{row['id']} 《{row['title']}》 共{row['total_paragraphs']}段\n"
        return text

    return "未知工具"


async def handle_mcp(request_body):
    method = request_body.get("method", "")
    req_id = request_body.get("id")

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {"listChanged": False}}, "serverInfo": {"name": "mcp-reader", "version": "1.0.0"}}}
    elif method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}
    elif method == "tools/call":
        tool_name = request_body["params"]["name"]
        tool_args = request_body["params"].get("arguments", {})
        result = handle_tool(tool_name, tool_args)
        return {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": result}]}}
    elif method == "notifications/initialized":
        return None
    else:
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": "Method not found"}}


async def app(scope, receive, send):
    if scope["type"] == "http":
        body = b""
        while True:
            msg = await receive()
            body += msg.get("body", b"")
            if not msg.get("more_body", False):
                break

        path = scope.get("path", "")
        method = scope.get("method", "GET")
        query = scope.get("query_string", b"").decode()

        token_from_query = ""
        for param in query.split("&"):
            if param.startswith("token="):
                token_from_query = param.split("=", 1)[1]

        headers_dict = {k.decode(): v.decode() for k, v in scope.get("headers", [])}
        token_from_header = headers_dict.get("authorization", "").replace("Bearer ", "")
        token = token_from_query or token_from_header

        if MCP_AUTH_TOKEN and token != MCP_AUTH_TOKEN:
            resp = json.dumps({"error": "滚"}).encode()
            await send({"type": "http.response.start", "status": 403, "headers": [[b"content-type", b"application/json"]]})
            await send({"type": "http.response.body", "body": resp})
            return

        if method == "GET":
            resp = json.dumps({"status": "mcp-reader alive"}).encode()
            await send({"type": "http.response.start", "status": 200, "headers": [[b"content-type", b"application/json"]]})
            await send({"type": "http.response.body", "body": resp})
            return

        try:
            request_body = json.loads(body)
        except:
            resp = json.dumps({"error": "bad json"}).encode()
            await send({"type": "http.response.start", "status": 400, "headers": [[b"content-type", b"application/json"]]})
            await send({"type": "http.response.body", "body": resp})
            return

        result = await handle_mcp(request_body)
        if result is None:
            resp = b""
            await send({"type": "http.response.start", "status": 204, "headers": []})
            await send({"type": "http.response.body", "body": resp})
        else:
            resp = json.dumps(result).encode()
            await send({"type": "http.response.start", "status": 200, "headers": [[b"content-type", b"application/json"]]})
            await send({"type": "http.response.body", "body": resp})
