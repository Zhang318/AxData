# AxData 发布打包验证

本文记录 AxData 发布到 PyPI 前的本地验证流程，以及 GitHub Release 与 PyPI 同步发布方式。

## 包边界

AxData 仓库内部保留 core、SDK、数据源插件等多个源码目录，这是为了让项目架构和插件开发边界清楚。

对 PyPI 公开发布时，当前阶段只发布一个用户入口包：

| PyPI 包名 | 构建方式 | 用途 |
| --- | --- | --- |
| `axdata` | `scripts/build_pypi_dist.py` 临时聚合构建 | Python SDK、CLI、核心框架和默认随包数据源能力 |

也就是说，普通用户只需要：

```powershell
python -m pip install axdata
```

发布用的 `axdata` wheel 会把以下内部模块打进同一个包里：

- `axdata`
- `axdata_core`
- `axdata_source_tdx`
- `axdata_source_tdx_ext`
- `axdata_source_tencent`
- `axdata_source_cninfo`

这样用户侧只有一个安装入口；仓库内部仍然可以继续按数据源插件、采集器插件和 core 分层开发。后续如果需要让某些插件独立发版，再单独拆出对应 PyPI 包。

## 本地 PyPI Readiness

运行：

```powershell
python scripts\pypi_readiness.py --json
```

脚本会在临时目录内完成：

- 构建单包版 `axdata` wheel 和 sdist。
- 运行 `twine check` 检查包元数据和 README 渲染。
- 创建全新的安装 venv，从本地 wheel 安装 `axdata`。
- 验证 `import axdata`、`import axdata_core` 和默认随包数据源模块。
- 验证 Provider entry point、包内 `axdata-provider.json` 和关键资源文件。
- 验证 `axdata` wheel 不再依赖未发布的 `axdata-core` 或 `axdata-source-*` 包。
- 验证 TDX/TDX Ext Provider 安装后默认进入 enabled 状态。
- 运行 `axdata --help`、`axdata init`、`axdata doctor`、`axdata status`、`axdata plugin list`。

保留临时目录以便排错：

```powershell
$work = "$env:TEMP\axdata-pypi-readiness"
python scripts\pypi_readiness.py --work-dir $work --json
```

如果只想跳过 `twine check`：

```powershell
python scripts\pypi_readiness.py --skip-twine-check --json
```

## GitHub Release 同步 PyPI

仓库内的 `.github/workflows/release.yml` 负责发布自动化：

- 发布 GitHub Release 时触发。
- 先运行 PyPI readiness，确认 wheel、sdist、README 元数据、安装和插件发现都正常。
- 构建单包版 `axdata` wheel 和 sdist。
- 把构建产物附加到 GitHub Release。
- 使用 PyPI Trusted Publishing 上传到 PyPI。

发布标签必须和 `packages/axdata-sdk/pyproject.toml` 里的版本一致。例如当前版本是 `0.1.1`，则 GitHub Release 标签应为 `v0.1.1` 或 `0.1.1`。PyPI 不允许覆盖已发布的同名同版本文件；如果要重新发布，需要先提升版本号。

### 首次发布前的 PyPI 设置

当前 workflow 使用 PyPI Trusted Publishing，不需要在 GitHub 仓库里保存 PyPI token。首次发布前，在 PyPI 的 `Add a new pending publisher` 中添加一条：

| 字段 | 值 |
| --- | --- |
| PyPI Project Name | `axdata` |
| Owner | `electkismet` |
| Repository name | `AxData` |
| Workflow name | `release.yml` |
| Environment name | `pypi-axdata` |

Pending publisher 不会提前占住包名，第一次真实发布成功后才会创建项目并变成普通 trusted publisher。

### 发布前检查

正式发布前建议按顺序确认：

1. `main` 分支干净，CI 通过。
2. 本地 PyPI readiness 通过。
3. PyPI 已配置 `axdata` 的 pending trusted publisher。
4. GitHub Release 标签等于当前包版本，例如 `v0.1.1`。

可以先只跑构建检查，不上传 PyPI：

```powershell
gh workflow run release.yml --repo electkismet/AxData --ref main -f publish=false
```

确认无误后，在 GitHub 创建并发布 Release。发布 Release 后，workflow 会自动上传 PyPI：

```powershell
git tag v0.1.1
git push origin v0.1.1
gh release create v0.1.1 --repo electkismet/AxData --title "AxData v0.1.1" --notes "Documentation and packaging metadata update"
```

如需手动重跑真实发布，必须从标签触发：

```powershell
gh workflow run release.yml --repo electkismet/AxData --ref v0.1.1 -f publish=true
```

## 本地脚本不包含的动作

该脚本不做：

- 不上传 PyPI。
- 不上传 TestPyPI。
- 不创建 GitHub release。
- 不修改 git remote。
- 不推送代码。
- 不请求真实数据源。
