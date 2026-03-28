# HTTP/1.1 Header Line Whitespace Rules

**Standard:** RFC 9112 (June 2022, obsoletes RFC 7230)

## Syntax

```
field-line = field-name ":" OWS field-value OWS
OWS        = *( SP / HTAB )   ; zero or more spaces/tabs
```

## Rules

- **No whitespace before the colon.** RFC 9112 §5.1 mandates a 400 rejection for any request with whitespace between the field name and colon.
- **OWS after the colon** — zero or more spaces/tabs are permitted.
- **OWS after the field value** — trailing whitespace is permitted and MUST be stripped before use.
- **Field names are case-insensitive** (RFC 9110 §5.1).

## Examples

| Form | Verdict | Reason |
|---|---|---|
| `content-length:13` | OK | No space before colon; zero OWS after is valid |
| `content-length : 13` | REJECT (400) | Space before colon is forbidden |
| `  content-length :13` | REJECT (400) | Leading whitespace = obs-fold (deprecated, RFC 9112 §5.2); also has space before colon |
| `content-length:   13   ` | OK | Multiple OWS after colon is fine; trailing spaces stripped, value is `13` |
