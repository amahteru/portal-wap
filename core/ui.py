from html import escape

from fastapi import Request, Response

XHTML_SHELL = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html PUBLIC "-//WAPFORUM//DTD XHTML Mobile 1.0//EN" "http://www.wapforum.org/DTD/xhtml-mobile10.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh-CN" lang="zh-CN">
<head>
    <title>{title}</title>
    <link rel="apple-touch-icon" href="/speeddial-icon.png?v=3" />
    <link rel="icon" type="image/png" sizes="128x128" href="/speeddial-icon.png?v=3" />
    <link rel="shortcut icon" href="/favicon.ico?v=3" type="image/x-icon" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=2.0, user-scalable=yes" />
    <style type="text/css">
        body {{ background-color: whitesmoke; color: black; margin: 0; padding: 0; }}
        a {{ color: darkblue; text-decoration: none; }}
        a:visited {{ color: darkblue; }}
        a:hover {{ text-decoration: underline; }}
        .header {{ background-color: #3B5998; color: white; padding: 4px 6px; font-weight: bold; }}
        .content {{ padding: 6px; line-height: 1.5; word-wrap: break-word; }}
        .content b {{ color: black; }}
        hr {{ border: 0; border-bottom: 1px solid silver; margin: 6px 0; }}
        select, input {{ border: 1px solid silver; background-color: white; margin-top: 4px; }}
        input[type="submit"] {{ background-color: gainsboro; border: 1px solid silver; padding: 2px 6px; }}
        .card {{ background-color: white; border: 1px solid silver; padding: 4px 6px; margin: 4px 0; }}
        .nav {{ background-color: gainsboro; padding: 6px; border-top: 1px solid silver; text-align: center; }}
        .item {{ padding: 1px 1px; display: block; }}
        .odd {{ background-color: lightgray; }}
        .even {{ background-color: white; }}
        {extra_css}
    </style>
</head>
<body>
{body}
</body>
</html>"""


def render_xhtml(
    request: Request, title: str, body: str, extra_css: str = "", status_code: int = 200, headers: dict | None = None
) -> Response:
    accept = request.headers.get("Accept", "")
    if "application/vnd.wap.xhtml+xml" in accept:
        media_type = "application/vnd.wap.xhtml+xml"
    elif "application/xhtml+xml" in accept:
        media_type = "application/xhtml+xml"
    else:
        media_type = "text/html"

    rendered = XHTML_SHELL.format(title=escape(title), body=body, extra_css=extra_css)

    resp_headers = {
        "Connection": "keep-alive",
        "Keep-Alive": "timeout=15, max=100",
    }
    if headers:
        resp_headers.update(headers)

    return Response(
        content=rendered, media_type=f"{media_type}; charset=utf-8", headers=resp_headers, status_code=status_code
    )
