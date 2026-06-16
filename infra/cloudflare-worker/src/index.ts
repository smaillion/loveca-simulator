interface Env {
  ORIGIN_BASE_URL: string;
  ALLOWED_ORIGINS?: string;
}

const API_PREFIX = "/api/";

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const requestUrl = new URL(request.url);
    const corsHeaders = buildCorsHeaders(request, env);

    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders });
    }

    if (!requestUrl.pathname.startsWith(API_PREFIX)) {
      return new Response("Not found", { status: 404, headers: corsHeaders });
    }

    if (!env.ORIGIN_BASE_URL) {
      return new Response("ORIGIN_BASE_URL is not configured", {
        status: 500,
        headers: corsHeaders,
      });
    }

    const originUrl = new URL(env.ORIGIN_BASE_URL);
    originUrl.pathname = requestUrl.pathname;
    originUrl.search = requestUrl.search;

    const upstream = await fetch(originUrl.toString(), {
      method: request.method,
      headers: request.headers,
      body: request.method === "GET" || request.method === "HEAD"
        ? undefined
        : request.body,
      redirect: "manual",
    });

    const responseHeaders = new Headers(upstream.headers);
    for (const [key, value] of corsHeaders.entries()) {
      responseHeaders.set(key, value);
    }
    return new Response(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: responseHeaders,
    });
  },
};

function buildCorsHeaders(request: Request, env: Env): Headers {
  const headers = new Headers();
  const origin = request.headers.get("Origin") ?? "";
  const allowed = new Set(
    (env.ALLOWED_ORIGINS ?? "")
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean),
  );
  if (origin && allowed.has(origin)) {
    headers.set("Access-Control-Allow-Origin", origin);
    headers.set("Vary", "Origin");
  }
  headers.set("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS");
  headers.set(
    "Access-Control-Allow-Headers",
    request.headers.get("Access-Control-Request-Headers") ?? "Content-Type",
  );
  headers.set("Access-Control-Max-Age", "86400");
  return headers;
}
