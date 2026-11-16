# API reference

The base path is `/api`. Responses are JSON. Errors are returned as `{"error": "<code>"}` with an appropriate HTTP status. Authenticated endpoints need `Authorization: Bearer <access_token>`.

## Auth
| Method | Path | Body / notes |
|---|---|---|
| POST | `/auth/register` | `{email, password, display_name, locale}` → `{access_token, expires_in, user}`. Also sets the refresh cookie. |
| POST | `/auth/login` | `{email, password}` |
| POST | `/auth/refresh` | Uses the cookie; rotates it. |
| POST | `/auth/logout` | |

## Account & settings
`GET /me` · `PATCH /me {locale, display_name, ai_provider_consent, remember_locations, shared_learning_opt_in}` · `POST /me/password {current_password, new_password}` · `POST /me/logout-all` · `GET /me/audit` · `GET /me/export` · `DELETE /me {password}` · `GET /meta` (public: doc types, processes, feature availability) · `GET /dashboard`

## Documents
| Method | Path | Notes |
|---|---|---|
| GET | `/documents` | Query parameters: `q` (natural language), `category`, `doc_type`, `source`, `issuer`, `from`, `to`, `tag`, `duplicates=1`, `include_archived=1` |
| POST | `/documents` | multipart `files[]`, `source=upload\|whatsapp_import` → processing starts asynchronously |
| GET | `/documents/:id` | metadata, text excerpt, duplicate info, bundles it belongs to |
| PATCH | `/documents/:id` | `display_name, doc_type, category_key, issuer, doc_date, expiry_date, tags, archived` |
| DELETE | `/documents/:id` | `{confirm: true}` required |
| POST | `/documents/:id/reprocess` · `/duplicate {action: keep_both\|archive_this\|not_duplicate}` · `/link {disposition: inline\|attachment}` → single-use URL |
| GET | `/documents/:id/thumbnail` | |
| POST | `/import/whatsapp` | multipart `file` (exported chat .zip) |
| GET | `/dl/:token` | signed, single-use, valid 120 s |

## Assistant
`POST /assistant/message {text, conversation_id?}` → `{conversation_id, message_id, lang, text, blocks[], actions[], quick_replies[]}`

Block types:
- `requirements`: `{results:[{requirement, status, best, alternatives, freshness, uncertain, acquisition, previously_found_in}], sources_searched, sources_unavailable, sources_failed}`
- `suggestions`: labelled suggestions, never requirements
- `proposal`: a memory change awaiting confirmation
- `documents`: content-search hits

`GET /conversations` · `GET /conversations/:id` · `DELETE /conversations/:id`

## Memory
`GET /memory` → `{checklists, facts, proposals}` · `POST /memory/checklists` · `PATCH|DELETE /memory/checklists/:id` · `POST /memory/proposals/:id {accept}` · `DELETE /memory/facts/:id` · `DELETE /memory {confirm:true}`

## Bundles
`GET|POST /bundles` · `GET|PATCH|DELETE /bundles/:id` · `POST /bundles/:id/items` · `PATCH|DELETE /bundles/:id/items/:item {custom_filename, label, selected, document_id}` · `POST /bundles/:id/links {item_ids?}` → one signed link per file (separate originals, no ZIP) · `POST /bundles/:id/combined-link` → optional merged PDF

## Categories & connectors
`GET|POST /categories` · `DELETE /categories/:key` (custom only) · `GET /connectors` (in search order, with an honest `state`) · `POST /connectors/:kind/connect` → `{auth_url}` · `GET /oauth/google/callback` · `DELETE /connectors/:kind` · `POST /connectors/:kind/import {ref}`
