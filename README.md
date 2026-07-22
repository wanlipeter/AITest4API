# AI API Test Framework

面向 Apifox/OpenAPI 文档的接口自动化测试用例生成框架。

项目当前聚焦一条主链路：读取 Apifox 导出的 OpenAPI JSON，解析接口定义，生成接口测试用例，再渲染为可执行的 pytest 脚本。生成后的用例可以先人工复核，也可以通过本地规则和 AI 语义审查做质量校验，最后执行测试并输出结果分析。

```text
Apifox/OpenAPI JSON
  -> 解析接口 method/path/query/path/body 字段
  -> 生成 cases.json
  -> 校验用例结构、接口对齐和语义风险
  -> 生成 pytest 脚本
  -> 执行接口测试
  -> 分析 test_results.json
```

## 当前能力

- 支持解析 Apifox/OpenAPI JSON 中的 `paths`、HTTP method、`summary`/`operationId`、query 参数、path 参数、`application/json` 请求体字段和 2xx 成功状态码。
- 支持本地规则生成器，不调用外部模型，适合快速跑通链路。
- 支持 OpenAI-compatible Chat Completions 协议的云端模型生成用例，目前内置 `deepseek`、`volcengine`、`qwen` 三类 provider。
- 云端生成会要求每个接口至少 5 条 case，并对模型返回 JSON 做基础提取和常见语法修复。
- 支持从 `cases.json` 单独生成 pytest 脚本，方便先人工检查、删减和修改 AI 生成结果。
- 支持执行前自动登录，按环境变量组装 `Token`、`Cookie`、`Tenant-Id` 等请求头。
- 支持测试结果落盘为 `test_results.json`，并用 AI 生成中文分析报告。
- 支持 `validate-cases` 本地规则校验，可结合 OpenAPI 文档检查 method/path、必填字段、未声明字段和字段类型。
- 支持可选 AI 语义审查，检查假通过风险、场景矛盾和覆盖不足。
- 支持校验报告输出为 `text`、`json`、`markdown`。

## 环境要求

- Python 3.12
- 框架源码只依赖 Python 标准库
- 执行生成后的测试脚本需要安装 `pytest`

```powershell
pip install pytest
```

## 目录结构

```text
run.py                                  本地启动入口
examples/apifox/                        Apifox/OpenAPI 示例文档
src/ai_api_test/cli.py                  命令行入口
src/ai_api_test/knowledge/              OpenAPI 解析
src/ai_api_test/generator/              用例生成、归一化、pytest 代码生成
src/ai_api_test/providers/              AI provider 配置和 OpenAI-compatible 调用
src/ai_api_test/auth/                   登录态封装
src/ai_api_test/validator/              用例校验和报告渲染
src/ai_api_test/workflow/               生成、分析等流程编排
generated/apifox/                       默认输出目录
```

## 快速开始

不安装项目包，直接在项目根目录运行：

```powershell
python run.py generate-apifox examples/apifox/order-service.openapi.json --out generated/apifox
```

默认使用本地规则生成器，输出：

```text
generated/apifox/cases.json
generated/apifox/test_generated_api.py
```

配置接口测试环境地址：

```text
API_BASE_URL=https://你的测试环境域名
```

执行生成的测试脚本：

```powershell
pytest generated/apifox/test_generated_api.py
```

执行后会生成：

```text
generated/apifox/test_results.json
```

## 推荐工作流

更稳妥的流程是先只生成用例，校验和人工复核后再生成脚本：

```powershell
python run.py generate-apifox examples/apifox/testdemo.openapi.json --out generated/apifox --provider qwen --cases-only
```

校验结构和基本质量：

```powershell
python run.py validate-cases generated/apifox/cases.json
```

结合 OpenAPI 文档做接口对齐检查：

```powershell
python run.py validate-cases generated/apifox/cases.json --openapi examples/apifox/testdemo.openapi.json
```

人工修改 `generated/apifox/cases.json` 后重新生成脚本：

```powershell
python run.py generate-script generated/apifox/cases.json
```

运行测试：

```powershell
pytest generated/apifox/test_generated_api.py
```

分析结果：

```powershell
python run.py analyze-result generated/apifox/test_results.json --out generated/apifox/analysis.md --provider qwen
```

## 生成用例

使用本地规则生成器：

```powershell
python run.py generate-apifox examples/apifox/order-service.openapi.json --out generated/apifox --provider local
```

使用云端模型生成器：

```powershell
python run.py generate-apifox examples/apifox/order-service.openapi.json --out generated/apifox --provider deepseek
python run.py generate-apifox examples/apifox/order-service.openapi.json --out generated/apifox --provider volcengine
python run.py generate-apifox examples/apifox/order-service.openapi.json --out generated/apifox --provider qwen
```

只生成 `cases.json`，不生成测试脚本：

```powershell
python run.py generate-apifox examples/apifox/order-service.openapi.json --out generated/apifox --provider qwen --cases-only
```

本地规则生成器会尽量覆盖：

```text
success                 正向请求
missing_required        缺少必填字段；没有必填字段时生成额外参数场景
empty_value             空字符串、空数组、空对象
invalid_type            类型错误
not_found_or_not_exist  数据不存在
auth_or_permission      缺少鉴权或 header
```

云端模型生成器会根据 prompt 生成更丰富的场景，目标是每个接口 6-8 条，框架会校验每个接口至少 5 条。

## AI Provider 配置

配置可以来自环境变量，也可以写在项目根目录 `.env` 中。建议从 `.env.example` 复制一份本地 `.env`，真实密钥只放本地，不要提交。

```powershell
Copy-Item .env.example .env
```

常用配置：

```text
AI_PROVIDER=local

DEEPSEEK_API_KEY=你的 DeepSeek API Key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat

VOLCENGINE_API_KEY=你的火山方舟 API Key
VOLCENGINE_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
VOLCENGINE_MODEL=你的火山方舟模型或 endpoint id

QWEN_API_KEY=你的通义千问 API Key
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen-plus

API_BASE_URL=https://你的接口测试环境域名
```

查看当前生效配置：

```powershell
python run.py show-config --provider qwen
```

`show-config` 会脱敏显示 API Key。

## 登录态配置

生成的 pytest 脚本会在执行请求前读取登录配置。默认关闭登录：

```text
AUTH_ENABLED=false
```

需要登录态时配置：

```text
AUTH_ENABLED=true
AUTH_LOGIN_URL=https://你的域名/登录接口
AUTH_ACCOUNT=你的账号
AUTH_PASSWORD=你的密码
AUTH_APP_ID=linker-user
AUTH_USER_INFO_URL=https://你的域名/获取用户信息接口
AUTH_TENANT_INDEX=0
AUTH_TIMEOUT=20
```

登录流程：

```text
1. 使用 appId、userName、md5(password) 调登录接口
2. 从响应 data.token 读取 token
3. 请求头写入 Token
4. Cookie 写入 LINKER_TOKEN
5. 如果配置 AUTH_USER_INFO_URL，再读取租户信息并补充 Tenant-Id 和 AGENT_TENANT_ID
```

未启用登录时，脚本仍会自动携带基础 JSON 请求头。

## cases.json 格式

推荐顶层格式：

```json
{
  "cases": [
    {
      "case_id": "get_user_success",
      "case_type": "interface",
      "name": "正向用例-获取用户",
      "api": {
        "method": "GET",
        "path": "/api/user"
      },
      "request": {
        "query": {
          "id": "1"
        }
      },
      "assertions": [
        {
          "type": "status_code",
          "expected": 200
        },
        {
          "type": "json_field",
          "path": "success",
          "operator": "eq",
          "expected": true
        }
      ]
    }
  ]
}
```

也兼容根节点直接是 case 数组。`generate-script` 会在生成代码前自动归一化常见简写。

请求参数位置：

```text
request.path       path 参数
request.query      query 参数
request.body       JSON 请求体
request.headers    单个 case 额外请求头
```

断言类型：

```text
status_code        HTTP 状态码断言
json_field         响应 JSON 字段断言
body_field         json_field 兼容别名
response_field     json_field 兼容别名
```

`json_field.path` 支持点号路径和数组下标：

```json
[
  {"type": "json_field", "path": "success", "operator": "eq", "expected": true},
  {"type": "json_field", "path": "code", "operator": "eq", "expected": "200"},
  {"type": "json_field", "path": "message", "operator": "contains", "expected": "orderId"},
  {"type": "json_field", "path": "data.items[0].id", "operator": "exists"}
]
```

当前支持的 operator：

```text
eq          等于，不写 operator 时默认 eq
ne          不等于
exists      字段存在且不是 null
contains    实际值包含 expected
```

## 校验用例

基础校验：

```powershell
python run.py validate-cases generated/apifox/cases.json
```

结合 OpenAPI 文档校验：

```powershell
python run.py validate-cases generated/apifox/cases.json --openapi examples/apifox/testdemo.openapi.json
```

开启 AI 语义审查：

```powershell
python run.py validate-cases generated/apifox/cases.json --openapi examples/apifox/testdemo.openapi.json --ai --provider qwen
```

输出 Markdown 报告：

```powershell
python run.py validate-cases generated/apifox/cases.json --openapi examples/apifox/testdemo.openapi.json --format markdown --out generated/apifox/validation_report.md
```

输出 JSON 报告：

```powershell
python run.py validate-cases generated/apifox/cases.json --format json
```

默认只有 `error` 会让命令返回非 0。如果希望 `warning` 也阻断 CI：

```powershell
python run.py validate-cases generated/apifox/cases.json --strict
```

本地校验会检查：

```text
1. cases 根节点格式是否正确
2. case_id、name、api、request、assertions 是否齐全
3. case_id 是否重复
4. api.method/api.path 是否有效
5. GET 用例是否误放 request.body
6. assertions 是否为空，断言类型是否支持
7. 是否只有 status_code 断言
8. 正向用例是否断言了失败语义
9. 重复的请求和断言
```

传入 `--openapi` 后会额外检查：

```text
1. case 中的 method/path 是否存在于接口文档
2. request.path/request.query/request.body 是否缺少必填字段
3. request.path/request.query/request.body 是否包含文档未声明字段
4. 字段值是否和 OpenAPI 声明类型明显不匹配
5. missing_required 用例是否真的移除了 required=true 字段
```

`--ai` 会把 cases、本地规则 findings 和可选 OpenAPI 摘要交给模型 review，重点检查：

```text
1. 假通过风险：用例通过但实际断言的是失败响应或无意义结果
2. 业务语义不一致：case_id/name/request/assertions 表达的场景互相矛盾
3. 覆盖不足：缺少正向成功、鉴权失败、边界值、空值、枚举非法等场景
```

AI 结果会以 `ai_warning` 输出，默认作为建议项。若本地规则已有 `error`，AI 审查会自动跳过。

## 生成脚本与执行

从已经复核过的 `cases.json` 生成 pytest 脚本：

```powershell
python run.py generate-script generated/apifox/cases.json
```

默认输出到 `cases.json` 同目录：

```text
generated/apifox/test_generated_api.py
```

指定输出路径：

```powershell
python run.py generate-script generated/apifox/cases.json --out generated/apifox/test_reviewed_api.py
```

执行测试：

```powershell
pytest generated/apifox/test_generated_api.py
```

生成的测试脚本会读取：

```text
API_BASE_URL        被测服务地址，默认 http://localhost:8000
TEST_RESULT_PATH    测试结果输出路径，默认 test_generated_api.py 同目录 test_results.json
AUTH_*              登录态配置
```

## 分析测试结果

使用 AI 分析执行结果：

```powershell
python run.py analyze-result generated/apifox/test_results.json --out generated/apifox/analysis.md --provider deepseek
```

分析报告会按以下方向输出：

```text
1. 总体结论
2. 失败用例列表
3. 可能原因
4. 建议修复动作
5. 更像环境问题、数据问题、脚本问题还是接口缺陷
```

## OpenAPI 支持范围

当前解析器优先支持常见、简单、可稳定落地的 OpenAPI 结构：

```text
paths
GET/POST/PUT/PATCH/DELETE
operation.summary
operation.operationId
parameters 中的 query/path 参数
requestBody.content.application/json.schema
inline object schema 的 properties 和 required
responses 中第一个 2xx 状态码
```

暂未展开支持：

```text
$ref 复杂引用解析
oneOf/anyOf/allOf
深层嵌套 object 字段展开
form-data、multipart、xml 等非 JSON 请求体
response schema 自动生成强断言
```

## 常用命令速查

```powershell
python run.py generate-apifox examples/apifox/order-service.openapi.json --out generated/apifox
python run.py generate-apifox examples/apifox/order-service.openapi.json --out generated/apifox --provider qwen --cases-only
python run.py validate-cases generated/apifox/cases.json --openapi examples/apifox/order-service.openapi.json
python run.py validate-cases generated/apifox/cases.json --openapi examples/apifox/order-service.openapi.json --ai --provider qwen
python run.py generate-script generated/apifox/cases.json
pytest generated/apifox/test_generated_api.py
python run.py analyze-result generated/apifox/test_results.json --out generated/apifox/analysis.md --provider qwen
python run.py show-config --provider qwen
```
