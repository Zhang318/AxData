"""Build the AxData GitHub Pages documentation site.

The generated site is static: it reads Provider/Interface metadata from the
local plugin catalog at build time and writes HTML/JSON files under ``site/``.
Opening the generated pages never calls AxData API or third-party sources.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "site"
PYPI_URL = "https://pypi.org/project/axdata/"
PUBLIC_SOURCE_PROVIDER_IDS = (
    "axdata.source.tdx_external",
    "axdata.source.tdx_ext_external",
)
SOURCE_ORDER = (
    "通达信",
    "通达信扩展行情",
    "交易所",
    "东方财富",
    "巨潮",
    "腾讯财经",
    "新浪财经",
    "财联社",
    "开盘红",
)
TDX_ASSET_GROUP_ORDER = (
    "股票数据",
    "指数数据",
    "ETF数据",
    "基金数据",
    "期货数据",
    "期权数据",
    "债券数据",
    "外汇数据",
    "宏观数据",
    "其它数据",
)
CATEGORY_ORDER = (
    "基础数据",
    "实时数据",
    "短线数据",
    "行情数据",
    "竞价数据",
    "财务数据",
    "F10数据",
    "公告数据",
    "龙虎榜数据",
    "融资融券数据",
    "研报数据",
    "财务报表",
    "交易行为",
    "公告",
    "研报",
    "期货数据",
    "期权数据",
    "基金数据",
    "债券数据",
    "外汇数据",
    "宏观数据",
    "特色数据",
    "其它",
)
DOC_PAGES: tuple[tuple[str, str], ...] = (
    ("quickstart.md", "快速开始"),
    ("architecture.md", "架构设计"),
    ("api-design.md", "API 与 SDK"),
    ("data-layers.md", "数据分层"),
    ("schema.md", "Schema 与字段"),
    ("source-provider-development.md", "数据源插件开发"),
    ("collector-plugin-development.md", "采集器插件开发"),
    ("plugin-development.md", "插件开发总览"),
    ("axdata-development-standards.md", "开发指南"),
    ("plugin-spec.md", "插件协议"),
    ("plugin-install-management.md", "插件安装管理"),
    ("axp-packaging-guide.md", "AXP 打包分享"),
    ("release-packaging.md", "发布打包检查"),
    ("roadmap.md", "路线图"),
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build AxData static documentation site.")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Output directory for the generated static site. Defaults to ./site.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print a JSON build summary.",
    )
    args = parser.parse_args(argv)

    summary = build_site(args.output)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(
            f"Built AxData docs site: {summary['interface_count']} interfaces, "
            f"{summary['doc_count']} docs -> {summary['output_dir']}"
        )
    return 0


def build_site(output_dir: str | Path = DEFAULT_OUTPUT_DIR) -> dict[str, Any]:
    output_path = Path(output_dir).resolve()
    entries = load_interface_entries()
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    prepared_entries = prepare_interface_entries(entries)

    if output_path.exists():
        shutil.rmtree(output_path)
    (output_path / "interfaces").mkdir(parents=True, exist_ok=True)
    (output_path / "docs").mkdir(parents=True, exist_ok=True)
    copy_assets(output_path)

    write_text(output_path / ".nojekyll", "")
    write_text(output_path / "styles.css", site_css())
    write_text(output_path / "index.html", render_home(prepared_entries, generated_at))
    write_text(output_path / "interfaces" / "index.html", render_interface_index(prepared_entries, generated_at))
    write_json(output_path / "interfaces" / "catalog.json", catalog_json(prepared_entries, generated_at))

    for entry in prepared_entries:
        write_text(
            output_path / "interfaces" / f"{entry['slug']}.html",
            render_interface_detail(entry, generated_at, prepared_entries),
        )

    rendered_docs = render_doc_pages(output_path)
    write_text(output_path / "docs" / "index.html", render_docs_index(rendered_docs, generated_at))

    source_counts = Counter(entry["source_name_zh"] for entry in prepared_entries)
    return {
        "output_dir": str(output_path),
        "interface_count": len(prepared_entries),
        "source_counts": dict(sorted(source_counts.items(), key=lambda item: source_sort_key(item[0]))),
        "doc_count": len(rendered_docs),
        "generated_at": generated_at,
    }


def load_interface_entries() -> list[dict[str, Any]]:
    """Load the public interface catalog from the plugin registry."""

    ensure_repo_import_paths()
    from axdata_core.plugin_config import PluginConfig
    from axdata_core.provider_catalog import list_registry_interface_dicts

    config = PluginConfig(enabled_provider_ids=PUBLIC_SOURCE_PROVIDER_IDS)
    rows = list_registry_interface_dicts(plugin_config=config)
    enabled_rows = [
        dict(row)
        for row in rows
        if row.get("enabled", True) is True and str(row.get("plugin_status", "enabled")) == "enabled"
    ]
    return sorted(enabled_rows, key=interface_sort_key)


def ensure_repo_import_paths() -> None:
    """Allow this script to run from a clean checkout without editable installs."""

    candidates = [
        REPO_ROOT / "libs" / "axdata_core",
        *(path for path in (REPO_ROOT / "packages").glob("axdata-source-*/src")),
    ]
    for candidate in reversed(candidates):
        if candidate.is_dir():
            text = str(candidate)
            if text not in sys.path:
                sys.path.insert(0, text)


def prepare_interface_entries(entries: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    seen_slugs: set[str] = set()
    for raw in entries:
        entry = dict(raw)
        name = str(entry.get("name") or entry.get("interface_name") or "unknown_interface")
        slug = unique_slug(name, seen_slugs)
        entry["name"] = name
        entry["slug"] = slug
        entry["title"] = str(entry.get("display_name_zh") or name)
        entry["source_name_zh"] = str(entry.get("source_name_zh") or "其它")
        entry["source_code"] = str(entry.get("source_code") or "unknown")
        entry["category"] = str(entry.get("category") or "接口")
        entry["menu_path"] = normalize_menu_path(entry)
        entry["parameters"] = list(entry.get("parameters") or [])
        entry["fields"] = list(entry.get("fields") or [])
        entry["reference_sections"] = list(entry.get("reference_sections") or [])
        entry["example"] = normalize_example(entry.get("example"))
        entry["summary"] = first_text(
            entry.get("summary_zh"),
            entry.get("description_zh"),
            entry.get("description"),
            entry["title"],
        )
        entry["description_text"] = first_text(
            entry.get("description_zh"),
            entry.get("description"),
            entry["summary"],
        )
        prepared.append(entry)
    return prepared


def normalize_menu_path(entry: Mapping[str, Any]) -> list[str]:
    raw = entry.get("menu_path")
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
        values = [str(item) for item in raw if str(item).strip()]
    else:
        values = []
    if not values:
        values = [
            str(entry.get("source_name_zh") or "其它"),
            str(entry.get("category") or "接口"),
        ]
    return values


def normalize_example(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        return {"request": {}, "response": []}
    request = raw.get("request")
    response = raw.get("response")
    return {
        "request": dict(request) if isinstance(request, Mapping) else {},
        "response": list(response) if isinstance(response, list) else [],
    }


def catalog_json(entries: Sequence[Mapping[str, Any]], generated_at: str) -> dict[str, Any]:
    return {
        "project": "AxData",
        "generated_at": generated_at,
        "interface_count": len(entries),
        "sources": [
            {"name": source, "count": count}
            for source, count in sorted(
                Counter(entry["source_name_zh"] for entry in entries).items(),
                key=lambda item: source_sort_key(item[0]),
            )
        ],
        "interfaces": [
            {
                "name": entry["name"],
                "title": entry["title"],
                "source_name_zh": entry["source_name_zh"],
                "source_code": entry["source_code"],
                "category": entry["category"],
                "menu_path": entry["menu_path"],
                "asset_class": entry.get("asset_class"),
                "provider_id": entry.get("provider_id"),
                "summary": entry["summary"],
                "url": f"interfaces/{entry['slug']}.html",
            }
            for entry in entries
        ],
    }


def render_home(entries: Sequence[Mapping[str, Any]], generated_at: str) -> str:
    source_counts = sorted(
        Counter(entry["source_name_zh"] for entry in entries).items(),
        key=lambda item: source_sort_key(item[0]),
    )
    stats = "".join(
        f"<div class=\"stat\"><strong>{count}</strong><span>{escape(source)}</span></div>"
        for source, count in source_counts
    )
    screenshot_grid = "".join(
        f"<figure><img src=\"assets/{escape(name)}\" alt=\"{escape(title)}\"><figcaption>{escape(title)}</figcaption></figure>"
        for name, title in (
            ("axdata-start-overview.png", "开始页与架构边界"),
            ("axdata-interface-catalog.png", "接口目录与字段说明"),
            ("axdata-collector-task.png", "采集任务"),
            ("axdata-plugin-management.png", "插件管理"),
        )
        if (REPO_ROOT / "docs" / "assets" / name).is_file()
    )
    body = f"""
<section class="hero">
  <p class="eyebrow">开源量化数据库框架</p>
  <h1>AxData</h1>
  <p class="lead">AxData 将数据源接口、采集任务、开放文件存储、本地查询、插件管理、Python SDK、HTTP API 和 Web 控制台放在同一个可扩展的数据平台里，面向个人量化研究、本地数据管理和数据源插件开发。</p>
  <div class="actions">
    <a class="button primary" href="interfaces/index.html">查看接口文档</a>
    <a class="button" href="docs/quickstart.html">快速开始</a>
    <a class="button" href="{escape(PYPI_URL)}">PyPI 包</a>
  </div>
</section>
<section>
  <h2>接口目录</h2>
  <p>文档站在构建时从 AxData Provider Registry 读取接口声明，并生成静态页面。打开 GitHub Pages 时不会请求 AxData 后端，也不会访问第三方数据源。</p>
  <div class="stats">{stats}</div>
</section>
<section>
  <h2>项目边界</h2>
  <div class="grid two">
    <div class="panel">
      <h3>数据源接口</h3>
      <p>Provider 插件负责一次性源端请求，返回 AxData 字段，默认不写入 data 目录。</p>
    </div>
    <div class="panel">
      <h3>采集器</h3>
      <p>Collector 插件负责显式采集任务、Parquet 写出、质量检查和元数据记录。</p>
    </div>
  </div>
</section>
<section>
  <h2>界面预览</h2>
  <div class="screenshots">{screenshot_grid}</div>
</section>
<section>
  <h2>致谢与声明</h2>
  <p>感谢 pytdx、AKShare、levistock 等开源项目为公开接口研究提供参考。AxData 仅用于个人学习、协议研究和非商业研究；通过本项目获取的数据禁止用于商业行为、付费服务、生产服务、转售或其他营利用途。</p>
</section>
<p class="build-note">生成时间：{escape(generated_at)}</p>
"""
    return page("AxData 文档站", body, active="home")


def render_interface_index(entries: Sequence[Mapping[str, Any]], generated_at: str) -> str:
    source_options = "".join(
        f"<option value=\"{escape(source)}\">{escape(source)} ({count})</option>"
        for source, count in sorted(
            Counter(entry["source_name_zh"] for entry in entries).items(),
            key=lambda item: source_sort_key(item[0]),
        )
    )
    rows = "\n".join(
        render_interface_index_row(entry)
        for entry in entries
    )
    content = f"""
<section class="page-head">
  <p class="eyebrow">接口目录</p>
  <h1>接口文档</h1>
  <p class="lead">共 {len(entries)} 个 source_request 接口。所有详情页来自插件接口目录和固定 example 快照。</p>
</section>
<section class="toolbar">
  <label>
    搜索
    <input id="interface-search" type="search" placeholder="输入接口名、中文名、字段或数据源">
  </label>
  <label>
    数据源
    <select id="source-filter">
      <option value="">全部数据源 ({len(entries)})</option>
      {source_options}
    </select>
  </label>
</section>
<section>
  <div class="table-wrap">
    <table id="interface-table">
      <thead>
        <tr>
          <th>接口</th>
          <th>数据源</th>
          <th>目录</th>
          <th>参数</th>
          <th>字段</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
</section>
<p class="build-note">生成时间：{escape(generated_at)}</p>
<script>
const searchInput = document.getElementById("interface-search");
const sourceFilter = document.getElementById("source-filter");
const rows = Array.from(document.querySelectorAll("#interface-table tbody tr"));
function applyFilters() {{
  const query = searchInput.value.trim().toLowerCase();
  const source = sourceFilter.value;
  for (const row of rows) {{
    const matchesSource = !source || row.dataset.source === source;
    const matchesQuery = !query || row.dataset.text.includes(query);
    row.hidden = !(matchesSource && matchesQuery);
  }}
}}
searchInput.addEventListener("input", applyFilters);
sourceFilter.addEventListener("change", applyFilters);
</script>
"""
    body = app_shell(interface_sidebar(entries), content)
    return page("接口文档 - AxData", body, active="interfaces")


def app_shell(sidebar: str, content: str) -> str:
    return f"""
<div class="app-shell">
  <aside class="app-sidebar">{sidebar}</aside>
  <div class="app-content">{content}</div>
</div>
"""


def interface_sidebar(entries: Sequence[Mapping[str, Any]], active_slug: str | None = None) -> str:
    tree = build_interface_tree(entries)
    nodes = "\n".join(render_nav_node(node, active_slug, level=0, parent_path=()) for node in tree)
    active_index = " active" if active_slug is None else ""
    return f"""
<div class="sidebar-heading"><span class="sidebar-icon">&lt;/&gt;</span><span>接口目录</span></div>
<a class="source-filter-summary{active_index}" href="index.html">
  <span class="source-filter-current"><strong>全部接口</strong><em>{len(entries)}</em></span>
  <span class="source-filter-action">接口一览</span>
</a>
<div class="catalog-tree">{nodes}</div>
"""


def build_interface_tree(entries: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    roots: dict[str, dict[str, Any]] = {}
    for entry in entries:
        path = navigation_path(entry)
        level = roots
        node: dict[str, Any] | None = None
        for part in path:
            node = level.setdefault(part, {"title": part, "children": {}, "items": []})
            level = node["children"]
        if node is not None:
            node["items"].append(entry)
    return sorted_nav_nodes(roots, parent_path=())


def navigation_path(entry: Mapping[str, Any]) -> list[str]:
    raw = entry.get("menu_path") or []
    parts = [str(item).strip() for item in raw if str(item).strip()]
    source = str(entry.get("source_name_zh") or "其它").strip() or "其它"
    if not parts:
        parts = [source, str(entry.get("category") or "接口")]
    elif parts[0] != source and parts[0] not in SOURCE_ORDER:
        parts = [source, *parts]
    return parts


def sorted_nav_nodes(nodes: Mapping[str, dict[str, Any]], parent_path: Sequence[str]) -> list[dict[str, Any]]:
    return sorted(nodes.values(), key=lambda node: nav_sort_key(str(node["title"]), parent_path))


def nav_sort_key(title: str, parent_path: Sequence[str]) -> tuple[int, str]:
    if not parent_path:
        order = SOURCE_ORDER
    elif parent_path[0] == "通达信" and len(parent_path) == 1:
        order = TDX_ASSET_GROUP_ORDER
    else:
        order = CATEGORY_ORDER
    try:
        return (order.index(title), "")
    except ValueError:
        return (len(order), title)


def nav_node_count(node: Mapping[str, Any]) -> int:
    children = node.get("children") or {}
    return len(node.get("items") or []) + sum(nav_node_count(child) for child in children.values())


def nav_node_has_active(node: Mapping[str, Any], active_slug: str | None) -> bool:
    if not active_slug:
        return False
    if any(str(item.get("slug")) == active_slug for item in node.get("items") or []):
        return True
    return any(nav_node_has_active(child, active_slug) for child in (node.get("children") or {}).values())


def render_nav_node(
    node: Mapping[str, Any],
    active_slug: str | None,
    *,
    level: int,
    parent_path: Sequence[str],
) -> str:
    title = str(node["title"])
    children = sorted_nav_nodes(node.get("children") or {}, (*parent_path, title))
    items = sorted(node.get("items") or [], key=lambda entry: (str(entry.get("title") or ""), str(entry.get("name") or "")))
    has_active = nav_node_has_active(node, active_slug)
    open_by_default = has_active or (active_slug is None and level <= 1)
    open_attr = " open" if open_by_default else ""
    child_html = "".join(
        render_nav_node(child, active_slug, level=level + 1, parent_path=(*parent_path, title))
        for child in children
    )
    item_html = "".join(render_nav_item(entry, active_slug, level + 1) for entry in items)
    count = nav_node_count(node)
    return f"""
<details class="tree-group tree-level-{level}"{open_attr}>
  <summary class="tree-group-toggle tree-level-{level}">
    <span class="tree-chevron"></span>
    <span>{escape(title)}</span>
    <em>{count}</em>
  </summary>
  <div class="tree-children tree-level-{level}">{child_html}{item_html}</div>
</details>
"""


def render_nav_item(entry: Mapping[str, Any], active_slug: str | None, level: int) -> str:
    active = " active" if str(entry.get("slug")) == active_slug else ""
    return f"""
<a class="tree-item tree-level-{level}{active}" href="{escape(str(entry['slug']))}.html">
  <span><strong>{escape(str(entry['title']))}</strong><small>{escape(str(entry['name']))}</small></span>
  <em>POST</em>
</a>
"""


def render_interface_index_row(entry: Mapping[str, Any]) -> str:
    params = entry.get("parameters") or []
    fields = entry.get("fields") or []
    text = " ".join(
        [
            str(entry.get("name") or ""),
            str(entry.get("title") or ""),
            str(entry.get("source_name_zh") or ""),
            " ".join(str(item) for item in entry.get("menu_path") or []),
            " ".join(str(item.get("name", "")) for item in params if isinstance(item, Mapping)),
            " ".join(str(item.get("name", "")) for item in fields if isinstance(item, Mapping)),
        ]
    ).lower()
    menu_path = " / ".join(str(item) for item in entry.get("menu_path") or [])
    return f"""
<tr data-source="{escape(str(entry['source_name_zh']))}" data-text="{escape(text)}">
  <td><a href="{escape(str(entry['slug']))}.html">{escape(str(entry['title']))}</a><code>{escape(str(entry['name']))}</code></td>
  <td>{escape(str(entry['source_name_zh']))}</td>
  <td>{escape(menu_path)}</td>
  <td>{len(params)}</td>
  <td>{len(fields)}</td>
</tr>"""


def render_interface_detail(
    entry: Mapping[str, Any],
    generated_at: str,
    entries: Sequence[Mapping[str, Any]],
) -> str:
    request = entry["example"]["request"]
    response = entry["example"]["response"]
    meta = [
        ("接口类型", "临时请求（HTTP POST，查一次返回一次）"),
        ("调用路径", f"/v1/request/{entry['name']}"),
        ("接口名称", entry["name"]),
        ("Provider", entry.get("provider_id") or entry.get("source_code") or ""),
        ("源", f"{entry['source_name_zh']} / {entry['source_code']}"),
        ("资产类型", entry.get("asset_class") or "unknown"),
        ("插件状态", entry.get("plugin_status") or "enabled"),
        ("信任级别", entry.get("effective_trust_level") or entry.get("declared_trust_level") or "community"),
        ("采集支持", collection_label(entry.get("collection"))),
    ]
    content = f"""
<section class="interface-head">
  <div class="interface-title-row">
    <span class="interface-icon">&lt;/&gt;</span>
    <div>
      <h1>{escape(str(entry['title']))}<span>{escape(str(entry['source_name_zh']))}</span></h1>
      <p>{escape(str(entry['summary']))}</p>
    </div>
  </div>
</section>
<section class="interface-section">
  {metadata_list(meta)}
  <p class="section-note">{escape(str(entry['description_text']))}</p>
</section>
<section class="interface-section">
  <h2>输入参数</h2>
  {parameter_table(entry.get("parameters") or [])}
  {optional_note("参数说明", entry.get("params_note_zh"))}
  {optional_note("参数示例", entry.get("params_example_zh"))}
</section>
<section class="interface-section">
  <h2>返回字段</h2>
  {field_table(entry.get("fields") or [])}
</section>
<section class="interface-section">
  <h2>调用示例</h2>
  <div class="example-grid">
    <div>
      <h3>Python SDK</h3>
      {code_block(sdk_example(str(entry['name']), request), "python")}
    </div>
    <div>
      <h3>HTTP API</h3>
      {code_block(http_example(str(entry['name']), request), "http")}
    </div>
  </div>
</section>
<section class="interface-section">
  <h2>真实样例快照</h2>
  <p class="snapshot-note">展示插件接口目录里的固定 example.response，页面打开不会再次请求源端。</p>
  <div class="example-grid">
    <div>
      <h3>请求参数</h3>
      {code_block(json.dumps(request, ensure_ascii=False, indent=2), "json")}
    </div>
    <div>
      <h3>响应样例</h3>
      {response_preview(response)}
    </div>
  </div>
</section>
{reference_sections(entry.get("reference_sections") or [])}
<p class="build-note">生成时间：{escape(generated_at)}</p>
"""
    body = app_shell(interface_sidebar(entries, active_slug=str(entry["slug"])), content)
    return page(f"{entry['title']} - AxData 接口文档", body, active="interfaces")


def render_doc_pages(output_path: Path) -> list[dict[str, str]]:
    rendered: list[dict[str, str]] = []
    for filename, title in DOC_PAGES:
        source = REPO_ROOT / "docs" / filename
        if not source.is_file():
            continue
        slug = source.stem
        html = markdown_to_html(source.read_text(encoding="utf-8"), base_depth=1)
        body = f"""
<section class="page-head">
  <p class="breadcrumb"><a href="index.html">开发文档</a></p>
  <h1>{escape(title)}</h1>
</section>
<article class="markdown-body">{html}</article>
"""
        write_text(output_path / "docs" / f"{slug}.html", page(f"{title} - AxData 文档", body, active="docs"))
        rendered.append({"title": title, "slug": slug, "filename": filename})
    return rendered


def render_docs_index(docs: Sequence[Mapping[str, str]], generated_at: str) -> str:
    items = "".join(
        f"<a class=\"doc-card\" href=\"{escape(doc['slug'])}.html\"><strong>{escape(doc['title'])}</strong><span>{escape(doc['filename'])}</span></a>"
        for doc in docs
    )
    body = f"""
<section class="page-head">
  <p class="eyebrow">Developer Docs</p>
  <h1>开发与使用文档</h1>
  <p class="lead">这里收录 AxData 的运行、架构、插件、采集器、AXP 和发布打包文档。接口详情请查看接口文档页。</p>
</section>
<section class="doc-grid">{items}</section>
<p class="build-note">生成时间：{escape(generated_at)}</p>
"""
    return page("开发文档 - AxData", body, active="docs")


def markdown_to_html(markdown: str, *, base_depth: int = 0) -> str:
    lines = markdown.splitlines()
    output: list[str] = []
    paragraph: list[str] = []
    list_mode: str | None = None
    in_code = False
    code_lang = ""
    code_lines: list[str] = []
    table_lines: list[str] = []

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            output.append(f"<p>{render_inline(' '.join(paragraph))}</p>")
            paragraph = []

    def flush_list() -> None:
        nonlocal list_mode
        if list_mode:
            output.append(f"</{list_mode}>")
            list_mode = None

    def flush_table() -> None:
        nonlocal table_lines
        if table_lines:
            output.append(render_markdown_table(table_lines))
            table_lines = []

    for line in lines:
        if line.startswith("```"):
            flush_paragraph()
            flush_list()
            flush_table()
            if in_code:
                output.append(code_block("\n".join(code_lines), code_lang))
                in_code = False
                code_lang = ""
                code_lines = []
            else:
                in_code = True
                code_lang = line.strip("`").strip()
            continue
        if in_code:
            code_lines.append(line)
            continue

        stripped = line.strip()
        if not stripped:
            flush_paragraph()
            flush_list()
            flush_table()
            continue

        if stripped.startswith("|") and stripped.endswith("|"):
            flush_paragraph()
            flush_list()
            table_lines.append(stripped)
            continue
        flush_table()

        image_match = re.fullmatch(r"!\[([^\]]*)\]\(([^)]+)\)", stripped)
        if image_match:
            flush_paragraph()
            flush_list()
            alt, href = image_match.groups()
            output.append(f"<p><img src=\"{escape(normalize_doc_href(href))}\" alt=\"{escape(alt)}\"></p>")
            continue

        heading_match = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading_match:
            flush_paragraph()
            flush_list()
            level = min(6, len(heading_match.group(1)) + base_depth)
            text = heading_match.group(2).strip()
            output.append(f"<h{level}>{render_inline(text)}</h{level}>")
            continue

        unordered = re.match(r"^[-*]\s+(.*)$", stripped)
        ordered = re.match(r"^\d+\.\s+(.*)$", stripped)
        if unordered or ordered:
            flush_paragraph()
            wanted = "ul" if unordered else "ol"
            if list_mode != wanted:
                flush_list()
                output.append(f"<{wanted}>")
                list_mode = wanted
            text = (unordered or ordered).group(1)
            output.append(f"<li>{render_inline(text)}</li>")
            continue

        flush_list()
        paragraph.append(stripped)

    flush_paragraph()
    flush_list()
    flush_table()
    if in_code:
        output.append(code_block("\n".join(code_lines), code_lang))
    return "\n".join(output)


def render_markdown_table(lines: Sequence[str]) -> str:
    parsed = [split_table_row(line) for line in lines]
    if not parsed:
        return ""
    header = parsed[0]
    body_rows = parsed[1:]
    if body_rows and all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in body_rows[0]):
        body_rows = body_rows[1:]
    head_html = "".join(f"<th>{render_inline(cell)}</th>" for cell in header)
    rows_html = "".join(
        "<tr>" + "".join(f"<td>{render_inline(cell)}</td>" for cell in row) + "</tr>"
        for row in body_rows
    )
    return f"<div class=\"table-wrap\"><table><thead><tr>{head_html}</tr></thead><tbody>{rows_html}</tbody></table></div>"


def split_table_row(line: str) -> list[str]:
    stripped = line.strip().strip("|")
    return [cell.strip() for cell in stripped.split("|")]


def render_inline(text: str) -> str:
    escaped = escape(text)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)

    def replace_link(match: re.Match[str]) -> str:
        label = match.group(1)
        href = normalize_doc_href(match.group(2))
        return f"<a href=\"{escape(href)}\">{label}</a>"

    escaped = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", replace_link, escaped)
    return escaped


def normalize_doc_href(href: str) -> str:
    clean = href.strip()
    if clean.startswith(("http://", "https://", "#")):
        return clean
    if clean.startswith("docs/assets/"):
        return "../assets/" + clean.removeprefix("docs/assets/")
    if clean.startswith("assets/"):
        return "../" + clean
    if clean.endswith(".md"):
        return clean[:-3] + ".html"
    return clean


def page(title: str, body: str, *, active: str) -> str:
    nav_items = (
        ("home", "首页", root_link(active, "index.html")),
        ("interfaces", "接口文档", root_link(active, "interfaces/index.html")),
        ("docs", "开发文档", root_link(active, "docs/index.html")),
        ("pypi", "PyPI", PYPI_URL),
    )
    nav = "".join(
        f"<a class=\"{'active' if key == active else ''}\" href=\"{escape(href)}\">{escape(label)}</a>"
        for key, label, href in nav_items
    )
    css_href = root_link(active, "styles.css")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <link rel="stylesheet" href="{escape(css_href)}">
</head>
<body class="page-{escape(active)}">
  <header class="site-header">
    <a class="brand" href="{escape(root_link(active, 'index.html'))}"><span class="brand-mark"></span><span>AxData</span></a>
    <nav>{nav}</nav>
  </header>
  <main>{body}</main>
  <footer>AxData 是一个开源量化数据库框架，主要面向个人学习、技术研究和本地数据管理。</footer>
</body>
</html>
"""


def root_link(active: str, href: str) -> str:
    if active in {"interfaces", "docs"}:
        return "../" + href
    return href


def definition_grid(items: Sequence[tuple[str, Any]]) -> str:
    cells = "".join(
        f"<div><dt>{escape(str(label))}</dt><dd>{escape(str(value))}</dd></div>"
        for label, value in items
    )
    return f"<dl class=\"definition-grid\">{cells}</dl>"


def metadata_list(items: Sequence[tuple[str, Any]]) -> str:
    rows = "".join(
        f"<div><dt>{escape(str(label))}</dt><dd>{escape(str(value))}</dd></div>"
        for label, value in items
    )
    return f"<dl class=\"metadata-list\">{rows}</dl>"


def parameter_table(parameters: Sequence[Mapping[str, Any]]) -> str:
    if not parameters:
        return "<p>无参数。</p>"
    rows = "".join(
        "<tr>"
        f"<td><code>{escape(str(item.get('name', '')))}</code></td>"
        f"<td>{escape(str(item.get('dtype') or item.get('type') or ''))}</td>"
        f"<td>{'是' if item.get('required') else '否'}</td>"
        f"<td>{escape(description_for(item))}</td>"
        f"<td>{escape(default_for(item))}</td>"
        "</tr>"
        for item in parameters
    )
    return f"""
<div class="table-wrap"><table>
  <thead><tr><th>参数</th><th>类型</th><th>必填</th><th>说明</th><th>默认值</th></tr></thead>
  <tbody>{rows}</tbody>
</table></div>"""


def field_table(fields: Sequence[Mapping[str, Any]]) -> str:
    if not fields:
        return "<p>暂无字段声明。</p>"
    rows = "".join(
        "<tr>"
        f"<td><code>{escape(str(item.get('name', '')))}</code></td>"
        f"<td>{escape(str(item.get('dtype') or item.get('type') or ''))}</td>"
        f"<td>{escape(description_for(item))}</td>"
        "</tr>"
        for item in fields
    )
    return f"""
<div class="table-wrap"><table>
  <thead><tr><th>字段</th><th>类型</th><th>说明</th></tr></thead>
  <tbody>{rows}</tbody>
</table></div>"""


def reference_sections(sections: Sequence[Mapping[str, Any]]) -> str:
    if not sections:
        return ""
    html_parts = ["<section><h2>参考表</h2>"]
    for section in sections:
        title = str(section.get("title") or section.get("id") or "参考表")
        note = str(section.get("note") or "")
        columns = [str(column) for column in (section.get("columns") or [])]
        rows = list(section.get("rows") or [])
        html_parts.append(f"<h3>{escape(title)}</h3>")
        if note:
            html_parts.append(f"<p>{escape(note)}</p>")
        if columns and rows:
            head = "".join(f"<th>{escape(column)}</th>" for column in columns)
            body = ""
            for row in rows:
                values = row if isinstance(row, Sequence) and not isinstance(row, (str, bytes, bytearray)) else [row]
                body += "<tr>" + "".join(f"<td>{escape(str(value))}</td>" for value in values) + "</tr>"
            html_parts.append(f"<div class=\"table-wrap\"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>")
    html_parts.append("</section>")
    return "\n".join(html_parts)


def optional_note(title: str, value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return f"<div class=\"note\"><strong>{escape(title)}</strong><p>{escape(text)}</p></div>"


def response_preview(response: Sequence[Any]) -> str:
    if not response:
        return "<p class=\"empty-state\">暂无固定响应样例。</p>"
    first_mapping = next((item for item in response if isinstance(item, Mapping)), None)
    if first_mapping is None:
        return code_block(json.dumps(list(response)[:5], ensure_ascii=False, indent=2), "json")

    columns = list(first_mapping.keys())
    for item in response:
        if not isinstance(item, Mapping):
            continue
        for key in item.keys():
            if key not in columns:
                columns.append(key)

    visible_rows = [item for item in response if isinstance(item, Mapping)][:5]
    head = "".join(f"<th>{escape(str(column))}</th>" for column in columns)
    body = "".join(
        "<tr>"
        + "".join(f"<td>{escape(compact_cell(row.get(column)))}</td>" for column in columns)
        + "</tr>"
        for row in visible_rows
    )
    more = ""
    if len(response) > len(visible_rows):
        more = f"<p class=\"snapshot-more\">仅展示前 {len(visible_rows)} 条，共 {len(response)} 条固定样例。</p>"
    return f"<div class=\"table-wrap sample-table\"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>{more}"


def compact_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def sdk_example(interface_name: str, request: Mapping[str, Any]) -> str:
    if not request:
        return f'import axdata as ax\n\nclient = ax.AxDataClient()\nrows = client.call("{interface_name}")'
    params = ",\n".join(
        f"    {key}={python_literal(value)}"
        for key, value in sorted(request.items())
    )
    return (
        "import axdata as ax\n\n"
        "client = ax.AxDataClient()\n"
        "rows = client.call(\n"
        f'    "{interface_name}",\n'
        f"{params},\n"
        ")"
    )


def http_example(interface_name: str, request: Mapping[str, Any]) -> str:
    payload = json.dumps({"params": dict(request)}, ensure_ascii=False, indent=2)
    return f"POST /v1/request/{interface_name}\nContent-Type: application/json\n\n{payload}"


def code_block(value: str, lang: str = "") -> str:
    class_name = f" class=\"language-{escape(lang)}\"" if lang else ""
    return f"<pre><code{class_name}>{escape(value)}</code></pre>"


def python_literal(value: Any) -> str:
    if isinstance(value, str):
        return repr(value)
    return repr(value)


def collection_label(collection: Any) -> str:
    if not isinstance(collection, Mapping):
        return "否"
    if not collection.get("supported"):
        return "否"
    profile = collection.get("default_profile")
    return f"是，默认 {profile}" if profile else "是"


def description_for(item: Mapping[str, Any]) -> str:
    return first_text(item.get("description_zh"), item.get("description"), item.get("display_name_zh"))


def default_for(item: Mapping[str, Any]) -> str:
    if "default" not in item:
        return ""
    return json.dumps(item.get("default"), ensure_ascii=False)


def first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def unique_slug(value: str, seen: set[str]) -> str:
    base = re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-").lower() or "item"
    slug = base
    index = 2
    while slug in seen:
        slug = f"{base}-{index}"
        index += 1
    seen.add(slug)
    return slug


def interface_sort_key(entry: Mapping[str, Any]) -> tuple[int, list[str], str]:
    source = str(entry.get("source_name_zh") or "其它")
    menu = entry.get("menu_path")
    menu_parts = [str(item) for item in menu] if isinstance(menu, Sequence) and not isinstance(menu, str) else []
    return (source_sort_key(source), menu_parts, str(entry.get("name") or ""))


def source_sort_key(source: str) -> int:
    try:
        return SOURCE_ORDER.index(source)
    except ValueError:
        return len(SOURCE_ORDER)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def write_json(path: Path, data: Any) -> None:
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def copy_assets(output_path: Path) -> None:
    source_dir = REPO_ROOT / "docs" / "assets"
    if not source_dir.is_dir():
        return
    target_dir = output_path / "assets"
    shutil.copytree(source_dir, target_dir, dirs_exist_ok=True)


def site_css() -> str:
    return """
:root {
  color-scheme: light;
  --bg: #f6f8fb;
  --surface: #ffffff;
  --surface-strong: #f8fafc;
  --text: #172033;
  --muted: #64748b;
  --line: #dde6f0;
  --accent: #2563eb;
  --accent-strong: #1d4ed8;
  --accent-soft: #eaf2ff;
  --sidebar: #fbfdff;
  --ok: #2f7d5c;
  --warn: #a56218;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: Inter, "Segoe UI", "Microsoft YaHei", Arial, sans-serif;
  line-height: 1.65;
}
a { color: var(--accent); text-decoration: none; }
a:hover { color: var(--accent-strong); text-decoration: underline; }
.site-header {
  position: sticky;
  top: 0;
  z-index: 30;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  min-height: 60px;
  padding: 0 clamp(16px, 3vw, 32px);
  background: rgba(255,255,255,.94);
  border-bottom: 1px solid var(--line);
  backdrop-filter: blur(12px);
}
.brand {
  color: var(--text);
  font-weight: 800;
  font-size: 18px;
  letter-spacing: 0;
  display: inline-flex;
  align-items: center;
  gap: 10px;
}
.brand:hover { text-decoration: none; }
.brand-mark {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  display: inline-block;
  background: linear-gradient(180deg, #3b82f6, #2563eb);
  box-shadow: inset 0 0 0 5px #dbeafe;
}
nav { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
nav a {
  color: var(--muted);
  padding: 6px 12px;
  border-radius: 6px;
  font-size: 14px;
  font-weight: 650;
}
nav a.active, nav a:hover {
  background: var(--accent-soft);
  color: var(--accent-strong);
  text-decoration: none;
}
main {
  width: min(1380px, calc(100vw - 32px));
  margin: 0 auto;
  padding: 26px 0 56px;
}
.page-interfaces main {
  width: 100%;
  padding: 0;
}
section {
  margin: 0 0 28px;
  padding: 0;
}
.hero, .page-head {
  padding: 28px 0 10px;
}
.eyebrow {
  margin: 0 0 8px;
  color: var(--accent);
  font-weight: 700;
  letter-spacing: 0;
}
h1, h2, h3 {
  letter-spacing: 0;
  line-height: 1.25;
}
h1 {
  margin: 0 0 14px;
  font-size: clamp(32px, 5vw, 56px);
}
.app-content h1 {
  font-size: clamp(30px, 3vw, 38px);
}
h2 {
  margin: 0 0 14px;
  font-size: 24px;
}
h3 {
  margin: 18px 0 10px;
  font-size: 18px;
}
.lead {
  max-width: 900px;
  color: #314154;
  font-size: 18px;
}
.actions { display: flex; gap: 12px; flex-wrap: wrap; margin-top: 20px; }
.button {
  display: inline-flex;
  align-items: center;
  min-height: 38px;
  padding: 8px 14px;
  border: 1px solid var(--line);
  border-radius: 6px;
  color: var(--text);
  background: var(--surface);
}
.button.primary {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
}
.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 10px;
}
.stat, .panel, .doc-card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 14px;
}
.stat strong {
  display: block;
  font-size: 30px;
  line-height: 1;
  color: var(--accent-strong);
}
.stat span { color: var(--muted); }
.grid.two {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 14px;
}
.screenshots {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 14px;
}
figure {
  margin: 0;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 8px;
  overflow: hidden;
}
figure img {
  display: block;
  width: 100%;
  aspect-ratio: 16 / 10;
  object-fit: cover;
}
figcaption {
  padding: 10px 12px;
  color: var(--muted);
  font-size: 14px;
}
.app-shell {
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr);
  gap: 0;
  align-items: stretch;
}
.app-sidebar {
  position: sticky;
  top: 60px;
  height: calc(100vh - 60px);
  overflow-y: auto;
  padding: 20px 16px 28px;
  border-right: 1px solid #edf1f6;
  background: #fff;
  scrollbar-color: #d4ddea transparent;
  scrollbar-gutter: stable;
  scrollbar-width: thin;
}
.app-content {
  min-width: 0;
  padding: 34px clamp(24px, 4vw, 54px) 56px;
}
.app-sidebar::-webkit-scrollbar { width: 10px; }
.app-sidebar::-webkit-scrollbar-track { background: transparent; }
.app-sidebar::-webkit-scrollbar-thumb {
  border: 3px solid #fff;
  border-radius: 999px;
  background: #d4ddea;
  background-clip: padding-box;
}
.sidebar-heading {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 14px;
  color: #263244;
  font-size: 1.05rem;
  font-weight: 800;
}
.sidebar-icon {
  display: inline-grid;
  width: 22px;
  height: 22px;
  place-items: center;
  border-radius: 6px;
  background: #eef5ff;
  color: #2563eb;
  font-family: "Cascadia Mono", Consolas, monospace;
  font-size: 12px;
}
.source-filter-summary {
  display: grid;
  width: 100%;
  min-width: 0;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
  margin-bottom: 16px;
  border: 1px solid #dfe7f2;
  border-radius: 6px;
  background: #fbfcfe;
  color: #526173;
  padding: 6px 7px 6px 9px;
  text-align: left;
}
.source-filter-summary:hover,
.source-filter-summary.active {
  border-color: #bfd4fa;
  background: #f0f5ff;
  color: #2465dc;
  text-decoration: none;
}
.source-filter-current,
.source-filter-action {
  display: inline-flex;
  min-width: 0;
  align-items: center;
}
.source-filter-current { gap: 6px; }
.source-filter-current strong {
  min-width: 0;
  overflow: hidden;
  color: #263244;
  font-size: .78rem;
  font-weight: 760;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.source-filter-current em {
  flex: 0 0 auto;
  border-radius: 999px;
  background: #eef2f7;
  color: #667085;
  font-size: .68rem;
  font-style: normal;
  font-weight: 760;
  line-height: 1;
  padding: 3px 6px;
}
.source-filter-action {
  flex: 0 0 auto;
  color: #7b8798;
  font-size: .72rem;
  font-weight: 740;
  white-space: nowrap;
}
.catalog-tree {
  display: grid;
  gap: 10px;
}
.tree-group {
  display: grid;
  gap: 2px;
}
.tree-group-toggle {
  display: flex;
  width: 100%;
  align-items: center;
  justify-content: flex-start;
  gap: 7px;
  margin: 0;
  border-radius: 4px;
  color: #253247;
  cursor: pointer;
  font-size: .9rem;
  font-weight: 760;
  list-style: none;
  padding: 5px 6px;
}
.tree-group-toggle::-webkit-details-marker { display: none; }
.tree-group-toggle:hover {
  background: #f5f8fd;
  color: #2465dc;
}
.tree-group-toggle.tree-level-0 {
  color: #2f7cf6;
  font-size: .92rem;
  font-weight: 820;
}
.tree-group-toggle.tree-level-1 {
  color: #243244;
  font-size: .9rem;
}
.tree-group-toggle.tree-level-2,
.tree-group-toggle.tree-level-3 {
  color: #344054;
  font-size: .86rem;
}
.tree-group-toggle em {
  flex: 0 0 auto;
  margin-left: auto;
  border-radius: 999px;
  background: #eef2f7;
  color: #667085;
  font-size: .68rem;
  font-style: normal;
  font-weight: 760;
  line-height: 1;
  padding: 3px 6px;
}
.tree-chevron {
  width: 14px;
  height: 14px;
  flex: 0 0 14px;
  color: #8b96a8;
}
.tree-chevron::before {
  content: "›";
  display: block;
  font-size: 18px;
  line-height: 12px;
  transform: rotate(90deg);
}
.tree-group:not([open]) > .tree-group-toggle .tree-chevron::before {
  transform: rotate(0deg);
}
.tree-children {
  display: grid;
  gap: 2px;
  margin-left: 11px;
  border-left: 1px solid #eef2f7;
  padding-left: 9px;
}
.tree-item {
  display: grid;
  min-width: 0;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
  border-radius: 5px;
  color: #334155;
  padding: 6px 7px;
}
.tree-item:hover,
.tree-item.active {
  background: #eaf2ff;
  color: #155bd7;
  text-decoration: none;
}
.tree-item span,
.tree-item strong,
.tree-item small {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tree-item strong {
  display: block;
  font-size: .78rem;
  font-weight: 760;
}
.tree-item small {
  display: block;
  color: #7b8798;
  font-family: "Cascadia Mono", Consolas, monospace;
  font-size: .68rem;
}
.tree-item em {
  color: #7b8798;
  font-size: .66rem;
  font-style: normal;
  font-weight: 760;
}
.toolbar {
  display: grid;
  grid-template-columns: minmax(240px, 1fr) minmax(200px, 300px);
  gap: 12px;
  align-items: end;
}
label {
  display: grid;
  gap: 6px;
  color: var(--muted);
  font-size: 14px;
}
input, select {
  width: 100%;
  min-height: 40px;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 8px 10px;
  background: var(--surface);
  color: var(--text);
  font: inherit;
}
.table-wrap {
  overflow-x: auto;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 8px;
}
table {
  width: 100%;
  border-collapse: collapse;
  min-width: 720px;
}
th, td {
  padding: 10px 12px;
  border-bottom: 1px solid var(--line);
  text-align: left;
  vertical-align: top;
}
th {
  background: var(--surface-strong);
  color: #2b3b4f;
  font-weight: 700;
}
td code {
  display: block;
  margin-top: 4px;
}
code {
  padding: 2px 5px;
  border-radius: 5px;
  background: #eef2f6;
  color: #1e3a4f;
  font-family: "Cascadia Mono", Consolas, monospace;
  font-size: .92em;
}
pre {
  overflow-x: auto;
  min-height: 112px;
  margin: 0;
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #f7fbff;
  color: #0f172a;
}
pre code {
  padding: 0;
  background: transparent;
  color: inherit;
}
.definition-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 10px;
}
.definition-grid div {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 10px 12px;
}
dt { color: var(--muted); font-size: 13px; }
dd { margin: 4px 0 0; font-weight: 650; }
.interface-head {
  margin: 0 0 24px;
  padding: 6px 0 24px;
  border-bottom: 1px solid #e8eef6;
}
.interface-title-row {
  display: flex;
  gap: 14px;
  align-items: flex-start;
}
.interface-icon {
  display: inline-grid;
  width: 36px;
  height: 36px;
  flex: 0 0 36px;
  place-items: center;
  border: 1px solid #bfd4fa;
  border-radius: 7px;
  background: #eef5ff;
  color: #2563eb;
  font-family: "Cascadia Mono", Consolas, monospace;
  font-size: 15px;
  font-weight: 800;
}
.interface-head h1 {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  margin: 0 0 10px;
  color: #172033;
  font-size: clamp(30px, 3vw, 40px);
}
.interface-head h1 span {
  border: 1px solid #bfd4fa;
  border-radius: 6px;
  background: #eef5ff;
  color: #1d4ed8;
  font-size: .78rem;
  font-weight: 760;
  padding: 3px 7px;
}
.interface-head p {
  margin: 0;
  color: #314154;
  font-size: 1rem;
}
.interface-section {
  margin: 0 0 28px;
  padding-bottom: 26px;
  border-bottom: 1px solid #e8eef6;
}
.interface-section h2 {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 0 14px;
  color: #18243a;
  font-size: 1.18rem;
}
.interface-section h2::before {
  content: "";
  width: 4px;
  height: 18px;
  border-radius: 999px;
  background: #2563eb;
}
.metadata-list {
  display: grid;
  gap: 12px;
  margin: 0;
  max-width: 820px;
}
.metadata-list div {
  display: grid;
  grid-template-columns: 110px minmax(0, 1fr);
  gap: 16px;
  align-items: baseline;
}
.metadata-list dt {
  color: #7b8798;
  font-size: .86rem;
  font-weight: 760;
}
.metadata-list dd {
  min-width: 0;
  margin: 0;
  overflow-wrap: anywhere;
  color: #10213d;
  font-size: .95rem;
  font-weight: 500;
}
.section-note {
  margin: 18px 0 0;
  color: #314154;
}
.example-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
}
.example-grid h3 {
  margin-top: 0;
  color: #526173;
  font-size: .88rem;
}
.snapshot-note {
  margin: 0 0 12px;
  border: 1px solid #dfe7f2;
  border-radius: 6px;
  background: #fbfcfe;
  color: #40536b;
  padding: 9px 12px;
}
.sample-table {
  max-width: 100%;
}
.sample-table table {
  min-width: max-content;
}
.snapshot-more {
  margin: 8px 0 0;
  color: var(--muted);
  font-size: .86rem;
}
.empty-state {
  margin: 0;
  color: var(--muted);
}
.breadcrumb, .code-title, .build-note, footer {
  color: var(--muted);
}
.note {
  margin-top: 12px;
  padding: 12px;
  border-left: 4px solid var(--accent);
  background: var(--accent-soft);
  border-radius: 6px;
}
.doc-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 12px;
}
.doc-card {
  color: var(--text);
}
.doc-card strong, .doc-card span {
  display: block;
}
.doc-card span {
  color: var(--muted);
  font-size: 14px;
}
.markdown-body img {
  max-width: 100%;
  border: 1px solid var(--line);
  border-radius: 8px;
}
footer {
  border-top: 1px solid var(--line);
  padding: 22px clamp(18px, 4vw, 48px);
  font-size: 14px;
}
@media (max-width: 720px) {
  .site-header { align-items: flex-start; flex-direction: column; }
  .toolbar { grid-template-columns: 1fr; }
  .app-shell { grid-template-columns: 1fr; }
  .app-sidebar { position: static; height: auto; max-height: 55vh; border-right: 0; border-bottom: 1px solid var(--line); }
  .app-content { padding: 24px 16px 42px; }
  .example-grid { grid-template-columns: 1fr; }
  .metadata-list div { grid-template-columns: 1fr; gap: 2px; }
  main { width: min(100vw - 24px, 1180px); }
  .page-interfaces main { width: 100%; }
}
"""


if __name__ == "__main__":
    raise SystemExit(main())
