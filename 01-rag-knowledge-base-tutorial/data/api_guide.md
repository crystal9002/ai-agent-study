# 智能云盘 API 快速入门

## 认证

所有 API 使用 Bearer Token 认证：

```
Authorization: Bearer <access_token>
```

Token 通过 OAuth 2.0 的 client_credentials 模式获取，有效期 2 小时，可用 refresh_token 续期。

## 基础接口

### 上传文件

```
POST /v1/files/upload
Content-Type: multipart/form-data
```

参数：
- `file`：文件二进制
- `parent_id`：目标文件夹 ID，默认根目录
- `conflict_strategy`：`rename`（重命名）或 `overwrite`（覆盖），默认 `rename`

单次上传上限为 5 GB，超过请使用分片上传接口 `POST /v1/files/multipart/init`。

### 搜索文件

```
GET /v1/files/search?q={keyword}&limit=20
```

返回按相关性排序的文件列表，每条包含 `file_id`、`name`、`score` 与 `preview_url`。语义检索需在请求头加 `X-Search-Mode: semantic`（仅企业版可用）。

### 创建分享链接

```
POST /v1/shares
{"file_id": "f_123", "expire_days": 7, "password": "abc123"}
```

`expire_days` 可选 1~365，`password` 为 6 位提取码，不传则自动生成。

## 错误码

| 状态码 | code | 含义 |
|--------|------|------|
| 401 | token_expired | Token 过期，请刷新 |
| 403 | quota_exceeded | 存储空间不足 |
| 429 | rate_limit | 触发限流，请退避重试 |
| 413 | file_too_large | 超过单文件上限 |

限流策略为令牌桶，团队版 100 次/秒，超出返回 429 并在 `Retry-After` 头中给出建议等待秒数。
