# Stable HTTP semantic-convention attribute names.
# Subset of https://opentelemetry.io/docs/specs/semconv/http/http-spans/
# Kept as plain constants so falcon.otel has no dependency on
# opentelemetry-semantic-conventions.

HTTP_REQUEST_METHOD = 'http.request.method'
HTTP_RESPONSE_STATUS_CODE = 'http.response.status_code'

URL_SCHEME = 'url.scheme'
URL_PATH = 'url.path'
URL_QUERY = 'url.query'

SERVER_ADDRESS = 'server.address'
SERVER_PORT = 'server.port'

CLIENT_ADDRESS = 'client.address'
CLIENT_PORT = 'client.port'

NETWORK_PROTOCOL_VERSION = 'network.protocol.version'

USER_AGENT_ORIGINAL = 'user_agent.original'
