const config = {
  output: "standalone",
  poweredByHeader: false,
  // Evidence generation can outlast Next's default 30-second rewrite proxy timeout.
  experimental: {proxyTimeout: 600000},
  async rewrites() {
    return [{source: "/api/:path*", destination: `${process.env.INTERNAL_API_URL || "http://127.0.0.1:8000"}/api/:path*`}];
  },
  async headers() {
    return [{source: "/:path*", headers: [
      {key: "X-Frame-Options", value: "DENY"},
      {key: "X-Content-Type-Options", value: "nosniff"},
      {key: "Referrer-Policy", value: "same-origin"},
      {key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()"}
    ]}];
  }
};
export default config;
