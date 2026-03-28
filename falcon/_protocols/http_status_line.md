# HTTP/1.1 Start-Line and Character Rules (RFC 9110 & 9112)

This document summarizes the current standards for HTTP/1.1 start-lines, whitespace handling, and character sets for methods and targets according to **RFC 9110 (Semantics)** and **RFC 9112 (HTTP/1.1 Message Format)**.

## 1. Message Start-Line Formats

HTTP/1.1 defines two types of start-lines: one for requests and one for responses.

### Request Line (RFC 9112, Section 3)
Sent by the client to initiate a request.
`method SP request-target SP HTTP-version CRLF`
*Example:* `GET /index.html HTTP/1.1\r\n`

### Status Line (RFC 9112, Section 4)
Sent by the server as the first line of a response.
`HTTP-version SP status-code SP [ reason-phrase ] CRLF`
*Example:* `HTTP/1.1 200 OK\r\n`

---

## 2. Whitespace and Delimiters

### Strict Grammar
The formal ABNF grammar requires **exactly one single space (SP, ASCII %x20)** between each component of the start-line.

### Multiple Spaces and Tabs
*   **Multiple Spaces:** Forbidden in the strict grammar.
*   **Tabs (HTAB):** Forbidden in the strict grammar.
*   **Lenient Parsing:** RFC 9112 notes that while some implementations may be robust and accept multiple whitespaces (SP, HTAB, VT, FF), this is **strongly discouraged**.

### Security Implications (Request Smuggling)
Inconsistent parsing of whitespace between intermediaries (e.g., a proxy and a backend) can lead to **Request Smuggling** or **Response Splitting** vulnerabilities. Modern security-focused implementations typically enforce the "single SP only" rule and return a `400 Bad Request` if violated.

---

## 3. HTTP Method (Verb) Characters

The HTTP method is defined as a `token` in **RFC 9110, Section 9.1**.

*   **Allowed Characters:**
    *   Alphanumerics: `A-Z`, `a-z`, `0-9`
    *   Special: `!`, `#`, `$`, `%`, `&`, `'`, `*`, `+`, `-`, `.`, `^`, `_`, `` ` ``, `|`, `~`
*   **Disallowed Characters:**
    *   Control characters (CTLs) and Whitespace (SP, HT).
    *   Delimiters: `"`, `(`, `)`, `,`, `/`, `:`, `;`, `<`, `=`, `>`, `?`, `@`, `[`, `\`, `]`, `{`, `}`.

---

## 4. Request-Target Characters

The `request-target` rules are defined in **RFC 9110, Section 7.1**, which points to **RFC 3986** for specific character sets.

### Formats (RFC 9110, Section 7.1)
1.  **origin-form (7.1.1):** `/path?query` (Most common).
2.  **absolute-form (7.1.2):** `http://www.example.com/path`
3.  **authority-form (7.1.3):** `www.example.com:80` (Used for `CONNECT`).
4.  **asterisk-form (7.1.4):** `*` (Used for `OPTIONS`).

### Allowed Character Sets (RFC 3986)
Any character not in these sets **must be percent-encoded** (e.g., Space as `%20`).

*   **Unreserved Characters (Section 2.3):** `A-Z`, `a-z`, `0-9`, `-`, `.`, `_`, `~`.
*   **Sub-delimiters (Section 2.2):** `!`, `$`, `&`, `'`, `(`, `)`, `*`, `+`, `,`, `;`, `=`.
*   **Other allowed in Path/Query:** `:`, `@`, `/`, `?`.
*   **Specifically Forbidden (Must Encode):** Control characters, Space, brackets `[` `]`, and non-ASCII octets.
