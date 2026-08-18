/** @type {import('next').NextConfig} */
const nextConfig = {
  typescript: {
    ignoreBuildErrors: false,
  },
  images: {
    unoptimized: true,
  },
  async rewrites() {
    const apiUrl = process.env.API_URL || process.env.NEXT_PUBLIC_API_URL
    if (!apiUrl) return []
    
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