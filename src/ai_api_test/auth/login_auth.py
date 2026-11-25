import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any
from urllib import request as url_request
from urllib.error import HTTPError


@dataclass(frozen=True)
class LoginConfig:
    enabled: bool
    login_url: str
    account: str
    password: str
    tenant_index: int
    user_info_url: str
    app_id: str
    timeout: int

    @classmethod
    def from_env(cls) -> "LoginConfig":
        # 登录配置统一从环境变量读取，环境变量可来自 .env。
        return cls(
            enabled=os.getenv("AUTH_ENABLED", "false").strip().lower() == "true",
            login_url=os.getenv("AUTH_LOGIN_URL", "").strip(),
            account=os.getenv("AUTH_ACCOUNT", "").strip(),
            password=os.getenv("AUTH_PASSWORD", "").strip(),
            tenant_index=int(os.getenv("AUTH_TENANT_INDEX", "0").strip() or "0"),
            user_info_url=os.getenv("AUTH_USER_INFO_URL", "").strip(),
            app_id=os.getenv("AUTH_APP_ID", "linker-user").strip(),
            timeout=int(os.getenv("AUTH_TIMEOUT", "20").strip() or "20"),
        )


class LoginSession:
    """参考 BaseRequest 的登录方式，封装接口测试执行前的登录态。"""

    def __init__(self, config: LoginConfig):
        self.config = config
        self._headers: dict[str, str] | None = None

    @classmethod
    def from_env(cls) -> "LoginSession":
        return cls(LoginConfig.from_env())

    def get_headers(self) -> dict[str, str]:
        # 未启用登录时仍返回基础 JSON 请求头，兼容无需登录的接口。
        if not self.config.enabled:
            return self._base_headers()

        self.ensure_login()
        return dict(self._headers or {})

    def ensure_login(self) -> None:
        if not self.config.enabled or self._headers is not None:
            return

        self._validate_config()
        headers = self._base_headers()
        login_response = self._post_json(
            self.config.login_url,
            {
                "appId": self.config.app_id,
                "password": hashlib.md5(self.config.password.encode()).hexdigest(),
                "userName": self.config.account,
            },
            headers,
        )
        token = self._read_nested(login_response, ["data", "token"])
        if not token:
            raise ValueError("登录响应中未找到 data.token，无法组装登录态请求头。")

        headers["Token"] = str(token)
        headers["Cookie"] = f"LINKER_TOKEN={token}"

        if self.config.user_info_url:
            tenant_id = self._load_tenant_id(headers)
            headers["Cookie"] = headers["Cookie"] + f";AGENT_TENANT_ID={tenant_id}"
            headers["Tenant-Id"] = tenant_id

        self._headers = headers

    def _validate_config(self) -> None:
        missing = []
        if not self.config.login_url:
            missing.append("AUTH_LOGIN_URL")
        if not self.config.account:
            missing.append("AUTH_ACCOUNT")
        if not self.config.password:
            missing.append("AUTH_PASSWORD")
        if missing:
            raise ValueError("登录配置缺失：" + ", ".join(missing))

    def _load_tenant_id(self, headers: dict[str, str]) -> str:
        # BaseRequest 中获取用户信息时传入 json=""，这里保持同样的请求体形式。
        user_info = self._post_json(self.config.user_info_url, "", headers)
        tenants = self._read_nested(
            user_info,
            ["data", "userCompleteInfo", "tenantInfoDTOList"],
        )
        if not isinstance(tenants, list) or self.config.tenant_index >= len(tenants):
            raise ValueError("用户信息响应中未找到可用租户信息，无法组装 Tenant-Id。")

        tenant_id = tenants[self.config.tenant_index].get("tenantId")
        if not tenant_id:
            raise ValueError("用户信息响应中未找到 tenantId。")
        return str(tenant_id)

    def _post_json(
        self,
        url: str,
        payload: Any | None,
        headers: dict[str, str],
    ) -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = url_request.Request(url, data=body, headers=headers, method="POST")
        try:
            with url_request.urlopen(request, timeout=self.config.timeout) as response:
                response_body = response.read().decode("utf-8")
        except HTTPError as error:
            response_body = error.read().decode("utf-8")
            raise RuntimeError(f"登录请求失败，HTTP {error.code}: {response_body}") from error

        try:
            return json.loads(response_body)
        except json.JSONDecodeError as error:
            raise ValueError(f"登录响应不是合法 JSON: {response_body}") from error

    def _base_headers(self) -> dict[str, str]:
        # 与 BaseRequest 保持一致，不手工设置 Content-Length，避免请求体过长时被截断。
        # 不声明 Accept-Encoding：urllib 不会自动解压，若服务端返回 gzip/br 响应会解析失败。
        return {
            "accept": "application/json, text/plain, */*",
            "accept-language": "zh-CN,zh;q=0.9",
            "cache-control": "no-cache",
            "content-type": "application/json",
            "pragma": "no-cache",
            "priority": "u=1, i",
            "user-agent": "Jenkins Probe",
            "Connection": "keep-alive",
        }

    def _read_nested(self, data: dict[str, Any], keys: list[str]) -> Any:
        current: Any = data
        for key in keys:
            if not isinstance(current, dict):
                return None
            current = current.get(key)
        return current
