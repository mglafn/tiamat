/** @type {import('next').NextConfig} */
const nextConfig = {
  typescript: {
    ignoreBuildErrors: False,
  },
  images: {
    unoptimized: true,
  },
  async rewrites() {
    const apiUrl = process.env.API_URL || process.env.NEXT_PUBLIC_API_URL
    if (!apiUrl) return []
    
    // Clean trailing slash
    const target = apiUrl.replace(/\/$/, "")

    return [
      {
        source: "/api/v1/:path*",
        destination: `${target}/api/v1/:path*`,
      },
      {
        source: "/health",
        destination: `${target}/health`,
      },
    ]
  },
}

export default nextConfig