# AI API Test Framework

这是一个收敛后的最小项目，只做一条链路：

```text
APIFOX/OpenAPI JSON
  -> 解析接口
  -> 生成接口测试用例
  -> 生成 pytest 测试代码
```

当前生成器是本地规则版，用来先跑通产品形态。后续接入真实大模型时，只需要替换用例生成器，不影响 APIFOX 解析和代码生成。

## 要求

- Python 3.12
- 当前代码只依赖 Python 标准库

## 目录结构

```text
examples/apifox/                 APIFOX/OpenAPI 示例文档
src/ai_api_test/cli.py           命令行入口
src/ai_api_test/knowledge/       APIFOX/OpenAPI 解析
src/ai_api_test/generator/       用例生成和 pytest 代码生成
src/ai_api_test/workflow/        最小链路编排
```

## 运行

不安装包，直接从项目根目录运行：

```powershell
python run.py generate-apifox examples/apifox/order-service.openapi.json --out generated/apifox
```

输出文件：

```text
generated/apifox/cases.json
generated/apifox/test_generated_api.py
```

## 配置 DeepSeek

项目会优先从环境变量或本地 `.env` 文件读取 DeepSeek 配置。不要把真实 API Key 写入源码。

复制示例配置：

```powershell
Copy-Item .env.example .env
```

然后在 `.env` 中填写：

```text
AI_PROVIDER=deepseek
DEEPSEEK_API_KEY=你的 DeepSeek API Key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
API_BASE_URL=https://你的测试环境域名
```

使用 DeepSeek 生成用例：

```powershell
python run.py generate-apifox examples/apifox/order-service.openapi.json --out generated/apifox --provider deepseek
```

## 配置请求域名

生成的 pytest 文件会自动向上查找项目根目录的 `.env` 文件，并读取：

```text
API_BASE_URL=https://你的测试环境域名
```

例如：

```text
API_BASE_URL=https://test-api.example.com
```

然后直接运行：

```powershell
pytest generated/apifox/test_generated_api.py
```

执行后会生成：

```text
generated/apifox/test_results.json
```

使用 AI 分析执行结果：

```powershell
python run.py analyze-result generated/apifox/test_results.json --out generated/apifox/analysis.md --provider deepseek
```

输出文件：

```text
generated/apifox/analysis.md
```

## 切换 AI 供应商

当前支持：

```text
deepseek
volcengine
qwen
```

生成用例时切换：

```powershell
python run.py generate-apifox examples/apifox/testdemo.openapi.json --out generated/apifox --provider qwen
```

分析结果时切换：

```powershell
python run.py analyze-result generated/apifox/test_results.json --out generated/apifox/analysis.md --provider volcengine
```

对应配置在 `.env.example` 或 `.env`：

```text
DEEPSEEK_API_KEY=...
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat

VOLCENGINE_API_KEY=...
VOLCENGINE_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
VOLCENGINE_MODEL=你的火山方舟模型或 endpoint id

QWEN_API_KEY=...
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen-plus
```

查看当前实际生效的供应商配置：

```powershell
python run.py show-config --provider qwen
```

## 下一步

建议只沿着这条链路继续迭代：

```text
1. 支持更多 APIFOX/OpenAPI 字段
2. 生成更多用例类型，比如必填缺失、类型错误、边界值
3. 接入真实 AI Provider
4. 增加人工确认后的代码写入流程
```
## 人工检查用例后再生成脚本

如果希望在 AI 生成用例后人工介入，可以先只生成 `cases.json`：

```powershell
python run.py generate-apifox examples/apifox/testdemo.openapi.json --out generated/apifox --provider deepseek --cases-only
```

人工检查、删减、修改 `generated/apifox/cases.json` 后，再用该文件覆盖生成测试脚本：

```powershell
python run.py generate-script generated/apifox/cases.json
```

默认会覆盖生成：

```text
generated/apifox/test_generated_api.py
```

如果想输出到其他路径，可以指定：

```powershell
python run.py generate-script generated/apifox/cases.json --out generated/apifox/test_reviewed_api.py
```

## 登录态配置

生成的测试脚本会在执行请求前读取登录配置。默认关闭登录：

```text
AUTH_ENABLED=false
```

需要登录态时，在 `.env` 或 `.env.example` 中配置：

```text
AUTH_ENABLED=true
AUTH_LOGIN_URL=http://你的域名/登录接口
AUTH_ACCOUNT=你的账号
AUTH_PASSWORD=你的密码
AUTH_APP_ID=linker-user
AUTH_USER_INFO_URL=http://你的域名/获取用户信息接口
AUTH_TENANT_INDEX=0
AUTH_TIMEOUT=20
```

登录方式参考 `BaseRequest.py`：

```text
1. 使用 appId、userName、md5(password) 调登录接口
2. 从响应 data.token 读取 token
3. 请求头写入 Token
4. Cookie 写入 LINKER_TOKEN
5. 如果配置 AUTH_USER_INFO_URL，再补 Tenant-Id 和 AGENT_TENANT_ID
```

## 响应字段断言

除了校验 HTTP 状态码，也可以校验响应 JSON 内部字段。推荐格式：

```json
{
  "type": "json_field",
  "path": "success",
  "expected": false
}
```

`path` 支持点号路径和数组下标：

```json
[
  {"type": "status_code", "expected": 200},
  {"type": "json_field", "path": "code", "expected": "500"},
  {"type": "json_field", "path": "success", "expected": false},
  {"type": "json_field", "path": "data.items[0].id", "expected": "123"}
]
```

也支持简写，框架会归一化为 `json_field`：

```json
{
  "assertions": {
    "status_code": 200,
    "success": false,
    "code": "500"
  }
}
```

## 校验用例文件

生成或人工修改 `cases.json` 后，可以先执行规则校验，检查结构错误、重复用例、非法断言和明显的假通过风险：

```powershell
python run.py validate-cases generated/apifox/cases.json
```

结合 OpenAPI 文档做接口对齐检查：

```powershell
python run.py validate-cases generated/apifox/cases.json --openapi examples/apifox/testdemo.openapi.json
```

开启 `--openapi` 后会额外检查：

```text
1. case 中的 method/path 是否存在于接口文档
2. request.path/request.query/request.body 是否缺少 OpenAPI 必填字段
3. request.path/request.query/request.body 是否包含文档未声明字段
4. 字段值是否和 OpenAPI 声明类型明显不匹配
5. missing_required 用例是否真的移除了 required=true 字段
```

开启 AI 语义审查：

```powershell
python run.py validate-cases generated/apifox/cases.json --openapi examples/apifox/testdemo.openapi.json --ai --provider qwen
```

`--ai` 会把 cases、本地规则 findings 和可选 OpenAPI 摘要交给模型 review，重点检查：

```text
1. 假通过风险：用例通过但实际断言的是失败响应或无意义结果
2. 业务语义不一致：case_id/name/request/assertions 表达的场景互相矛盾
3. 覆盖不足：缺少正向成功、鉴权失败、边界值、空值、枚举非法等场景
```

AI 结果会以 `ai_warning` 输出，默认作为建议项，不会因为 `--strict` 阻断；如果 AI 调用失败，会输出 `AI_REVIEW_FAILED` error。

输出 Markdown 或 JSON 报告：

```powershell
python run.py validate-cases generated/apifox/cases.json --format markdown --out generated/apifox/validation_report.md
python run.py validate-cases generated/apifox/cases.json --format json
```

默认只有 error 会让命令返回非 0；如果希望 warning 也阻断 CI，可以开启严格模式：

```powershell
python run.py validate-cases generated/apifox/cases.json --strict
```

默认 `validate-cases` 只做本地规则校验；只有显式传入 `--ai` 时才会调用模型。
