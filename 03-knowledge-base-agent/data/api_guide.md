# 星云笔记开放 API 快速入门

## 认证

所有 API 使用 Bearer Token 认证：

```
Authorization: Bearer <access_token>
```

Token 通过 OAuth 2.0 的 `client_credentials` 模式获取，有效期 2 小时，可用 `refresh_token` 续期。

## 基础接口

### 创建笔记

```
POST /open/v2/notes
Content-Type: application/json

{"space_id": "sp_1024", "title": "周会纪要", "content_markdown": "…"}
```

参数：
- `space_id`：所属团队空间 ID，必填
- `title`：笔记标题，必填，上限 100 字符
- `content_markdown`：Markdown 正文，单篇上限 2 万字，超出返回 413

### 搜索笔记

```
GET /open/v2/notes/search?q={keyword}&space_id={space_id}&limit=20
```

返回按相关性排序的笔记列表，每条包含 `note_id`、`title`、`score` 与 `url`。
语义检索需在请求头加 `X-Search-Mode: semantic`（仅企业版可用）。

### 读取反向链接

```
GET /open/v2/notes/{note_id}/backlinks
```

返回引用了该笔记的所有笔记摘要，用于还原知识图谱中的入边。

## 限流

限流策略为令牌桶：团队版 60 次/秒，企业版 500 次/秒。
超出限额返回 `429`，并在 `Retry-After` 响应头中给出建议等待秒数，客户端应按该值退避重试。

## 错误码

| 状态码 | code | 含义 |
|--------|------|------|
| 401 | token_expired | Token 过期，请刷新 |
| 403 | space_forbidden | 当前成员没有该空间的写权限 |
| 413 | note_too_large | 正文超过 2 万字上限 |
| 429 | rate_limit | 触发限流，请按 Retry-After 退避 |
| 422 | duplicate_title | 同空间内标题重复 |
