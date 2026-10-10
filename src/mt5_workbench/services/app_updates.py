"""Read public GitHub releases; never download or replace a running program."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from mt5_workbench import __version__

REPOSITORY = "xiaomingxinggit/mt5-gold-workbench"
RELEASES_URL = f"https://github.com/{REPOSITORY}/releases"
API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
EXE_NAME = "MT5Workbench.exe"
MAX_RESPONSE_BYTES = 1024 * 1024


def version_tuple(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", value)
    if not match:
        raise ValueError("发布版本号必须为 v主版本.次版本.修订版本，例如 v0.2.1")
    return tuple(int(part) for part in match.groups())


def trusted_release_url(value: str, *, download: bool = False) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlsplit(value)
    prefix = f"/{REPOSITORY}/releases/" + ("download/" if download else "tag/")
    return (parsed.scheme == "https" and parsed.netloc == "github.com"
            and not parsed.query and not parsed.fragment
            and parsed.path.startswith(prefix)
            and (parsed.path.endswith("/" + EXE_NAME) if download else True))


def initial_update_state(current_version: str = __version__) -> dict:
    return {"currentVersion": current_version, "latestVersion": "", "status": "idle",
            "message": "启动后自动检查，每 6 小时复查，也可手动检查。",
            "checkedAt": "", "releaseUrl": RELEASES_URL, "downloadUrl": "",
            "releaseNotes": "", "available": False, "busy": False}


def parse_release(payload: dict, current_version: str = __version__) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("GitHub 返回了无效的发布数据")
    if payload.get("draft") or payload.get("prerelease"):
        raise ValueError("该版本尚未正式发布")
    tag = payload.get("tag_name", "")
    if not isinstance(tag, str):
        raise ValueError("发布版本号无效")
    remote = version_tuple(tag)
    current = version_tuple(current_version)
    page = payload.get("html_url", "")
    if not trusted_release_url(page):
        raise ValueError("发布链接不是当前项目的 GitHub Release")
    result = initial_update_state(current_version)
    result.update(latestVersion=tag.removeprefix("v"), releaseUrl=page,
                  releaseNotes=str(payload.get("body") or "")[:6000])
    if remote <= current:
        result.update(status="current", message="当前已是最新版本。")
        return result
    assets = payload.get("assets", [])
    if not isinstance(assets, list):
        raise ValueError("发布附件数据无效")
    asset = next((item for item in assets if isinstance(item, dict)
                  and item.get("name") == EXE_NAME and item.get("state") == "uploaded"
                  and isinstance(item.get("size"), int) and item["size"] > 0
                  and trusted_release_url(item.get("browser_download_url", ""), download=True)), None)
    if asset is None:
        result.update(status="pending", message=f"发现 {tag}，但 Windows EXE 尚未发布完成，请稍后检查。")
        return result
    result.update(status="available", available=True,
                  downloadUrl=asset["browser_download_url"],
                  message=f"发现新版本 {tag}，可下载新版 EXE。关闭程序后替换 EXE；日志和设置保存在用户数据目录。")
    return result


def check_for_updates(current_version: str = __version__, *, opener=urlopen) -> dict:
    result = initial_update_state(current_version)
    request = Request(API_URL, headers={"Accept": "application/vnd.github+json",
                                       "User-Agent": f"MT5Workbench/{current_version}"})
    try:
        with opener(request, timeout=10) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError("发布数据超过大小限制")
        result = parse_release(json.loads(body.decode("utf-8")), current_version)
    except HTTPError as exc:
        if exc.code == 404:
            result.update(status="unpublished", message="远程仓库尚无正式 Release；代码提交不会触发版本提示。")
        elif exc.code in (403, 429):
            result.update(status="error", message="GitHub 请求受限，请稍后重试。")
        else:
            result.update(status="error", message=f"检查更新失败（HTTP {exc.code}），请稍后重试。")
    except (URLError, OSError, TimeoutError):
        result.update(status="error", message="无法连接 GitHub，请检查网络后重试。")
    except (ValueError, TypeError, UnicodeError):
        result.update(status="error", message="发布数据或版本号无效，请到发布页面查看。")
    result["checkedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return result
